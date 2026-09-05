from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.news import entry_disruption_severity
from wm_tipps.prep_disruption import (
    PREP_DISRUPTION_CAP,
    build_prep_disruption_index,
    context_entry,
)


def _news(team, title, summary="", *, teams=None, freshness="fresh", model_relevant=True):
    return {
        "title": title, "summary": summary,
        "teams": teams or ([team] if isinstance(team, str) else list(team)),
        "freshness": freshness, "model_relevant": model_relevant,
        "relevance": "high" if model_relevant else "low",
        "severity": "noise", "categories": ["travel"],
    }


class EntryDisruptionDetectionTests(unittest.TestCase):
    """T-0067: verbreiterte Auto-Erkennung mit Fan-Ausschluss + zwei Stufen."""

    def test_strong_matchday_arrival(self):
        self.assertEqual(
            entry_disruption_severity("Iran", _news("Iran", "Iran only allowed to enter on matchday")),
            "strong",
        )

    def test_german_matchday_phrase_strong(self):
        self.assertEqual(
            entry_disruption_severity("Iran", _news("Iran", "Iran darf wohl nur an Spieltagen in die USA")),
            "strong",
        )

    def test_denied_visas_word_order_mild(self):
        # Frueher verpasst: 'denied visas' (andere Wortstellung als 'visas denied').
        self.assertEqual(
            entry_disruption_severity("Iran", _news("Iran", "Iran says US denied visas to key World Cup officials")),
            "mild",
        )

    def test_staff_blocked_mild(self):
        self.assertEqual(
            entry_disruption_severity("Iran", _news("Iran", "Iran staff blocked from entering US after players given visas")),
            "mild",
        )

    def test_detected_even_when_classified_noise(self):
        # KERN-FIX: Item als noise/irrelevant klassifiziert, aber klare Phrase
        # -> trotzdem erkannt (frueher killte das is_model_relevant_news-Gate).
        item = _news("Iran", "Iran only allowed to enter on matchday", model_relevant=False)
        self.assertEqual(entry_disruption_severity("Iran", item), "strong")

    def test_fan_only_clause_not_flagged(self):
        self.assertIsNone(
            entry_disruption_severity("Iran", _news("Iran", "Iran fans denied entry to the United States"))
        )

    def test_neutral_positive_news_not_flagged(self):
        self.assertIsNone(
            entry_disruption_severity("Iran", _news("Iran", "Iran players receive US visas and arrive at training camp"))
        )

    def test_stale_not_flagged(self):
        self.assertIsNone(
            entry_disruption_severity("Iran", _news("Iran", "Iran only allowed to enter on matchday", freshness="stale"))
        )

    def test_host_nations_never_flagged(self):
        # Gastgeber tauchen als Zielland in Gast-Artikeln auf -> kein Signal.
        for host in ("USA", "Mexico", "Canada"):
            self.assertIsNone(
                entry_disruption_severity(host, _news(host, f"Iran only allowed to enter {host} on matchday")),
                host,
            )

    def test_multi_team_incidental_attribution(self):
        item = _news(
            ["Senegal", "Iran"], "Travel update",
            "Senegal were refused visas this week, while Iran trained as planned.",
            teams=["Senegal", "Iran"],
        )
        self.assertIsNone(entry_disruption_severity("Iran", item))  # nur inzidentell
        self.assertEqual(entry_disruption_severity("Senegal", item), "mild")  # Phrase in Senegal-Klausel

NOW = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)

FIXTURES = [
    {"match_id": "m1", "home_team": "Iran", "away_team": "USA",
     "kickoff_utc": "2026-06-11T19:00:00+00:00"},
    {"match_id": "m2", "home_team": "Iran", "away_team": "Spain",
     "kickoff_utc": "2026-06-16T19:00:00+00:00"},
    {"match_id": "m0", "home_team": "Iran", "away_team": "Wales",
     "kickoff_utc": "2026-06-05T19:00:00+00:00"},  # Vergangenheit
]


def _entry_news(team, title, summary=""):
    return {
        "title": title, "summary": summary, "categories": ["travel"],
        "severity": "important", "teams": [team] if isinstance(team, str) else list(team),
        "freshness": "fresh", "model_relevant": True, "relevance": "high",
    }


class PrepDisruptionTests(unittest.TestCase):
    def test_manual_override_applies_to_correct_side(self):
        manual = {"m1": {"team": "Iran", "severity": "strong", "reason": "Matchday-Einreise"}}
        idx = build_prep_disruption_index(FIXTURES, [], now=NOW, manual=manual)
        self.assertIn("m1", idx)
        self.assertEqual(idx["m1"]["home"]["team"], "Iran")
        self.assertEqual(idx["m1"]["home"]["basis"], "manual")
        self.assertEqual(idx["m1"]["home"]["xg_delta"], -0.08)  # strong
        self.assertIsNone(idx["m1"]["away"])

    def test_manual_explicit_delta_is_clamped(self):
        manual = {"m1": {"team": "USA", "xg_delta": -0.5}}  # ueber Deckel
        idx = build_prep_disruption_index(FIXTURES, [], now=NOW, manual=manual)
        self.assertEqual(idx["m1"]["away"]["team"], "USA")
        self.assertEqual(idx["m1"]["away"]["xg_delta"], PREP_DISRUPTION_CAP)

    def test_news_strong_applies_to_next_fixture(self):
        news = [_entry_news("Iran", "Iran only allowed to enter on matchday, <48h")]
        idx = build_prep_disruption_index(FIXTURES, news, now=NOW, manual={})
        # m1 ist das naechste Spiel (>= now), nicht m2, nicht das vergangene m0.
        self.assertIn("m1", idx)
        self.assertEqual(idx["m1"]["home"]["basis"], "news")
        self.assertEqual(idx["m1"]["home"]["xg_delta"], -0.05)
        self.assertNotIn("m2", idx)

    def test_manual_overrides_news_for_same_slot(self):
        news = [_entry_news("Iran", "Iran denied entry until matchday")]
        manual = {"m1": {"team": "Iran", "severity": "strong", "reason": "bestaetigt"}}
        idx = build_prep_disruption_index(FIXTURES, news, now=NOW, manual=manual)
        self.assertEqual(idx["m1"]["home"]["basis"], "manual")
        self.assertEqual(idx["m1"]["home"]["xg_delta"], -0.08)

    def test_manual_team_suppresses_news_for_later_match(self):
        # Iran hat manuellen Eintrag fuer m1 (Opener). NACH dem Opener ist
        # m2 das naechste Spiel -- ohne Suppression haette die alte
        # Visa-News m2 (regulaere Anreise) faelschlich getroffen.
        later = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
        news = [_entry_news("Iran", "Iran only allowed to enter on matchday")]
        manual = {"m1": {"team": "Iran", "severity": "strong", "reason": "Opener bestaetigt"}}
        idx = build_prep_disruption_index(FIXTURES, news, now=later, manual=manual)
        self.assertNotIn("m2", idx)  # News fuer Iran komplett unterdrueckt
        self.assertEqual(idx["m1"]["home"]["basis"], "manual")

    def test_news_mild_tier_applies(self):
        news = [_entry_news("Iran", "Iran staff blocked from entering US")]
        idx = build_prep_disruption_index(FIXTURES, news, now=NOW, manual={})
        self.assertEqual(idx["m1"]["home"]["basis"], "news")
        self.assertEqual(idx["m1"]["home"]["xg_delta"], -0.03)  # mild

    def test_team_without_future_fixture_skipped(self):
        only_past = [FIXTURES[2]]  # nur m0 (Vergangenheit)
        news = [_entry_news("Iran", "Iran refused entry")]
        idx = build_prep_disruption_index(only_past, news, now=NOW, manual={})
        self.assertEqual(idx, {})

    def test_incidental_multi_team_news_not_applied(self):
        # Sammelartikel: Phrase betrifft USA, Iran nur inzidentell genannt.
        news = [_entry_news(
            ["USA", "Iran"],
            "USA logistics update",
            "USA were denied entry to a stadium tour, while Iran trained as planned.",
        )]
        idx = build_prep_disruption_index(FIXTURES, news, now=NOW, manual={})
        # Iran darf NICHT betroffen sein (Phrase steht in der USA-Klausel).
        iran_hit = any(
            (row.get("home") or {}).get("team") == "Iran"
            or (row.get("away") or {}).get("team") == "Iran"
            for row in idx.values()
        )
        self.assertFalse(iran_hit)

    def test_no_disruptions_empty_index(self):
        idx = build_prep_disruption_index(FIXTURES, [], now=NOW, manual={})
        self.assertEqual(idx, {})

    def test_context_entry_shape(self):
        manual = {"m1": {"team": "Iran", "severity": "mild"}}
        idx = build_prep_disruption_index(FIXTURES, [], now=NOW, manual=manual)
        entry = context_entry(idx["m1"])
        self.assertEqual(entry["home_xg_delta"], -0.04)
        self.assertEqual(entry["away_xg_delta"], 0.0)
        self.assertEqual(entry["home"]["team"], "Iran")


if __name__ == "__main__":
    unittest.main()
