from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import datetime, timezone

from wm_tipps.matchday_command import build_matchday_command_center


def fixture():
    return {
        "match_id": "m1",
        "match_number": 1,
        "kickoff_utc": "2099-06-11T19:00:00+00:00",
        "home_team": "Mexico",
        "away_team": "South Africa",
        "venue": "Mexico City",
        "group": "A",
    }


def prediction(*, critical: bool = False):
    row = {
        "match_id": "m1",
        "fixture": fixture(),
        "recommended_tip": {"tip": "1:0", "expected_points": 1.4},
        "stability": "stabil",
        "news": [],
    }
    if critical:
        row["stability"] = "volatil"
        row["news"] = [
            {
                "id": "n1",
                "severity": "critical",
                "freshness": "fresh",
                "model_relevant": True,
                "relevance": "high",
                "title": "Mexico captain ruled out",
                "source": "test",
                "teams": ["Mexico"],
                "categories": ["injury"],
            }
        ]
    return row


def team_intel_payload():
    return {
        "sources": [
            {
                "id": "global-lineups",
                "name": "Global lineups",
                "url": "https://example.test/lineups",
                "official": False,
                "source_type": "lineup_watch",
                "status": "active_page",
                "teams": ["*"],
                "signals": ["lineup", "confirmed_lineup"],
            },
            {
                "id": "mexico",
                "name": "Mexico official",
                "url": "https://example.test/mexico",
                "official": True,
                "source_type": "official_federation_page",
                "status": "active_page",
                "teams": ["Mexico"],
                "signals": ["squad", "injury", "lineup"],
            },
            {
                "id": "south-africa",
                "name": "South Africa official",
                "url": "https://example.test/south-africa",
                "official": True,
                "source_type": "official_federation_page",
                "status": "active_page",
                "teams": ["South Africa"],
                "signals": ["squad", "lineup"],
            },
        ]
    }


class MatchdayCommandTests(unittest.TestCase):
    def test_critical_watchlist_match_is_focus_item_with_source_links(self):
        report = build_matchday_command_center(
            {"fixtures": [fixture()]},
            {"predictions": [prediction(critical=True)]},
            team_intel_payload(),
            {"checks": {}, "matches": {}},
            now=datetime(2099, 5, 20, tzinfo=timezone.utc),
            write=False,
        )

        self.assertEqual(report["summary"]["critical"], 1)
        row = report["today_items"][0]
        self.assertEqual(row["status"], "kritisch")
        self.assertEqual(row["tip"], "1:0")
        self.assertTrue(row["source_links"])
        self.assertIn("Mexico captain ruled out", row["status_detail"])

    def test_lineup_window_waits_for_confirmed_lineup(self):
        report = build_matchday_command_center(
            {"fixtures": [fixture()]},
            {"predictions": [prediction()]},
            team_intel_payload(),
            {"checks": {}, "matches": {}},
            now=datetime(2099, 6, 11, 17, 30, tzinfo=timezone.utc),
            write=False,
        )

        row = report["today_items"][0]
        self.assertEqual(row["status"], "warte_auf_lineup")
        self.assertIn("confirmed_lineup", [action["type"] for action in row["due_actions"]])

    def test_kicked_off_match_is_played_and_not_focus(self):
        # Nach Anpfiff: terminal 'gespielt', kein Fokus, keine Lineup-Wartung
        # -- selbst mit kritischer News (Terminal-Zustand hat Vorrang).
        report = build_matchday_command_center(
            {"fixtures": [fixture()]},
            {"predictions": [prediction(critical=True)]},
            team_intel_payload(),
            {"checks": {}, "matches": {}},
            now=datetime(2099, 6, 11, 21, 0, tzinfo=timezone.utc),  # 2h nach Anpfiff 19:00
            write=False,
        )
        row = report["items"][0]
        self.assertEqual(row["status"], "gespielt")
        self.assertIn("Pre-Match-Checks entfallen", row["status_detail"])
        self.assertEqual(report["today_items"], [])
        self.assertEqual(report["summary"]["played"], 1)
        self.assertEqual(report["summary"]["waiting_lineup"], 0)

    def test_checked_state_marks_current_due_checks_done(self):
        report = build_matchday_command_center(
            {"fixtures": [fixture()]},
            {"predictions": [prediction()]},
            team_intel_payload(),
            {
                "checks": {
                    "m1:weather_first_pass": {"status": "geprueft"},
                    "m1:travel_context": {"status": "geprueft"},
                },
                "matches": {},
            },
            now=datetime(2099, 6, 9, 19, 0, tzinfo=timezone.utc),
            write=False,
        )

        row = report["items"][0]
        self.assertEqual(row["status"], "geprueft")
        self.assertEqual(row["due_actions"], [])
        self.assertEqual(report["summary"]["checked"], 1)


if __name__ == "__main__":
    unittest.main()
