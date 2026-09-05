from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.dashboard import (
    all_round_final_tips,
    build_watchlist,
    current_watch_state,
    final_tips,
    final_tips_by_round,
    odds_status_for_prediction,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID, round_name


def prediction(match_id, match_number, kickoff, home, away):
    return {
        "fixture": {
            "away_team": away,
            "group": "A",
            "home_team": home,
            "kickoff_utc": kickoff,
            "match_number": match_number,
        },
        "match_id": match_id,
        "recommended_tip": {"expected_points": 1.2, "tip": "1:0"},
        "round_tips": {
            DEFAULT_ROUND_ID: {"expected_points": 1.2, "tip": "1:0"},
            SECONDARY_ROUND_ID: {"expected_points": 1.6, "tip": "2:1"},
        },
        "stability": "stabil",
    }


class DashboardTests(unittest.TestCase):
    def test_final_tips_are_chronological(self):
        rows = final_tips(
            [
                prediction("later", 2, "2026-06-12T02:00:00+00:00", "B", "C"),
                prediction("first", 1, "2026-06-11T19:00:00+00:00", "A", "D"),
                prediction("same-time-higher-number", 3, "2026-06-12T02:00:00+00:00", "E", "F"),
            ]
        )
        self.assertEqual([row["match_id"] for row in rows], ["first", "later", "same-time-higher-number"])
        self.assertEqual(rows[0]["match_number"], 1)
        self.assertTrue(all(row["round_name"] == round_name(DEFAULT_ROUND_ID) for row in rows))

    def test_final_tips_by_round_keeps_round_specific_tips(self):
        rows_by_round = final_tips_by_round(
            [prediction("m1", 1, "2026-06-11T19:00:00+00:00", "A", "B")]
        )
        self.assertEqual(rows_by_round[DEFAULT_ROUND_ID][0]["tip"], "1:0")
        self.assertEqual(rows_by_round[SECONDARY_ROUND_ID][0]["tip"], "2:1")
        all_rows = all_round_final_tips(
            [prediction("m1", 1, "2026-06-11T19:00:00+00:00", "A", "B")]
        )
        self.assertEqual({row["round_name"] for row in all_rows}, {round_name(DEFAULT_ROUND_ID), round_name(SECONDARY_ROUND_ID)})

    def test_third_place_export_in_both_rounds(self):
        # T-0150 final (Betreiber-Bestaetigung): Platz 3 ist in BEIDEN Runden tippbar.
        row = prediction("ko-103", 103, "2026-07-18T21:00:00+00:00", "A", "B")
        row["fixture"]["stage"] = "third_place"
        rows_by_round = final_tips_by_round([row])
        self.assertEqual(
            [tip["match_id"] for tip in rows_by_round[DEFAULT_ROUND_ID]],
            ["ko-103"],
        )
        self.assertEqual(
            [tip["match_id"] for tip in rows_by_round[SECONDARY_ROUND_ID]],
            ["ko-103"],
        )

    def test_watchlist_ignores_low_relevance_noise(self):
        row = prediction("m1", 1, "2099-06-11T19:00:00+00:00", "England", "Ghana")
        row["news"] = [
            {
                "severity": "critical",
                "freshness": "fresh",
                "model_relevant": False,
                "relevance": "low",
                "title": "League promotion race",
                "teams": ["England"],
            }
        ]
        self.assertEqual(build_watchlist([row]), [])

    def test_watchlist_ueberspringt_gespielte_spiele(self):
        """T-0169: Die Watchlist ist eine Handlungsliste VOR dem Anpfiff.

        Ohne diesen Guard stand am Turnierende jedes einzelne Spiel drauf
        (104 von 104), darunter 60x "warte auf Lineup" fuer laengst
        gelaufene Partien -- eine Alarmliste, die alles enthaelt,
        alarmiert nicht. Der Zustand war im Payload vorhanden und wurde
        nur nicht abgefragt.
        """
        offen = prediction("m1", 1, "2099-06-11T19:00:00+00:00", "Spain", "Peru")
        offen["stability"] = "volatil"
        gespielt = prediction("m2", 2, "2020-06-11T19:00:00+00:00", "Italy", "Chile")
        gespielt["stability"] = "volatil"
        gespielt["fixture"]["status"] = "played"

        rows = build_watchlist([offen, gespielt])
        self.assertEqual(["m1"], [row["match_id"] for row in rows])

    def test_watchlist_guard_gilt_fuer_jeden_grund(self):
        """Isomorphie-Check zur Klasse: der Guard darf nicht nur den
        Stabilitaets-Zweig abdecken. News, Heat-Stress und fehlende
        Quoten haben eigene Auslesepfade -- jeder davon haette ein
        gespieltes Spiel sonst wieder hereingeholt.
        """
        faelle = {
            "stabilitaet": lambda row: row.update({"stability": "volatil"}),
            "news": lambda row: row.update({
                "news": [{
                    "severity": "critical",
                    "freshness": "fresh",
                    "model_relevant": True,
                    "relevance": "high",
                    "title": "Kapitaen faellt aus",
                    "teams": ["Italy"],
                    "categories": ["injury"],
                }],
            }),
            "heat": lambda row: row.update({
                "context": {"heat_stress": {"risk": "high"}},
            }),
            "keine_quoten": lambda row: row.update({"odds": None}),
        }
        for name, aufbau in faelle.items():
            with self.subTest(grund=name):
                row = prediction("m9", 9, "2020-06-11T19:00:00+00:00", "Italy", "Chile")
                row["fixture"]["status"] = "played"
                aufbau(row)
                self.assertEqual([], build_watchlist([row]))

    def test_watchlist_exposes_news_details_and_effect(self):
        row = prediction("m1", 1, "2099-06-11T19:00:00+00:00", "France", "Senegal")
        row["stability"] = "volatil"
        row["news"] = [
            {
                "severity": "critical",
                "freshness": "fresh",
                "model_relevant": True,
                "relevance": "high",
                "title": "France striker ruled out",
                "source": "source",
                "teams": ["France"],
                "categories": ["injury"],
            }
        ]
        watch = build_watchlist([row])
        self.assertEqual(len(watch), 1)
        self.assertIn("kritische News", watch[0]["reasons"])
        news_detail = next(detail for detail in watch[0]["details"] if detail["type"] == "news")
        self.assertIn("France xG -0.18", news_detail["effect"])

    def test_watchlist_dedupes_same_player_impact_from_multiple_sources(self):
        row = prediction("m1", 1, "2099-06-11T19:00:00+00:00", "Germany", "Curaçao")
        row["news"] = [
            {
                "id": "bbc-karl",
                "severity": "critical",
                "freshness": "fresh",
                "model_relevant": True,
                "relevance": "high",
                "title": "Germany forward Karl ruled out of World Cup",
                "summary": "Germany forward Lennart Karl is ruled out of the 2026 World Cup with a thigh injury.",
                "source": "bbc",
                "teams": ["Germany"],
                "categories": ["injury"],
            },
            {
                "id": "espn-karl",
                "severity": "critical",
                "freshness": "fresh",
                "model_relevant": True,
                "relevance": "high",
                "title": "Germany's Karl out of WC after training injury",
                "summary": "Germany's 18-year-old midfielder Lennart Karl will miss the World Cup after suffering an injury in training on Friday.",
                "source": "espn",
                "teams": ["Germany"],
                "categories": ["injury"],
            },
        ]
        watch = build_watchlist([row])
        news_details = [detail for detail in watch[0]["details"] if detail["type"] == "news"]
        self.assertEqual(len(news_details), 1)
        self.assertIn("Germany xG -0.18", news_details[0]["effect"])

    def test_current_watch_state_overrides_stale_counts(self):
        state = current_watch_state(
            {"watchlist": 99, "next_cadence_seconds": 86400},
            fixtures={"fixtures": [{}, {}]},
            predictions=[{"match_id": "m1"}],
            news={"items": [{}, {}, {}]},
            markets={"odds": [{}, {}], "markets": [{}]},
            watchlist=[],
            final_rows=[{}],
        )
        self.assertEqual(state["watchlist"], 0)
        self.assertEqual(state["fixtures"], 2)
        self.assertEqual(state["market_items"], 3)
        self.assertEqual(state["next_cadence_seconds"], 86400)


class OddsStatusTests(unittest.TestCase):
    NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)

    def _pred(self, *, odds, status="scheduled"):
        return {"match_id": "ko-076", "fixture": {"status": status}, "odds": odds}

    def test_missing_odds_flagged(self):
        status = odds_status_for_prediction(self._pred(odds=None), now=self.NOW)
        self.assertEqual(status["state"], "missing")

    def test_fresh_odds_ok(self):
        odds = {"last_updated": "2026-06-30T06:00:00+00:00"}
        status = odds_status_for_prediction(self._pred(odds=odds), now=self.NOW)
        self.assertEqual(status["state"], "ok")

    def test_old_odds_stale(self):
        odds = {"last_updated": "2026-06-20T06:00:00+00:00"}  # ~10 Tage alt
        status = odds_status_for_prediction(self._pred(odds=odds), now=self.NOW)
        self.assertEqual(status["state"], "stale")

    def test_played_match_returns_none(self):
        status = odds_status_for_prediction(
            self._pred(odds=None, status="played"), now=self.NOW
        )
        self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
