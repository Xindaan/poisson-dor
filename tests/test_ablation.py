from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.ablation import CONTEXT_EFFECTS, _tip_for, context_ablation, news_market_conflicts
from wm_tipps.scoring import DEFAULT_ROUND_ID

ROUND = DEFAULT_ROUND_ID


def _fixture_with_heat(home_xg: float, away_xg: float, heat_delta: float) -> dict:
    current = _tip_for(home_xg, away_xg, None, "group", ROUND)
    return {
        "match_id": "t1",
        "fixture": {"home_team": "A", "away_team": "B", "stage": "group"},
        "xg": {"home": home_xg, "away": away_xg},
        "xg_breakdown": {
            "home": {"heat_effect": heat_delta, "altitude_effect": 0.0,
                     "travel_effect": 0.0, "player_intel_effect": 0.0, "news_effect": 0.0},
            "away": {"heat_effect": 0.0, "altitude_effect": 0.0,
                     "travel_effect": 0.0, "player_intel_effect": 0.0, "news_effect": 0.0},
        },
        "round_tips": {
            ROUND: {"home": current["home"], "away": current["away"],
                    "tip": current["tip"], "expected_points": current["expected_points"]},
        },
        "odds": {},
    }


class ContextAblationTests(unittest.TestCase):
    def test_effects_cover_all_context_signals(self):
        report = context_ablation({"predictions": [_fixture_with_heat(2.0, 1.0, -0.6)]})
        self.assertEqual(
            [item["effect"] for item in report["effects"]],
            [key for key, _ in CONTEXT_EFFECTS],
        )

    def test_nonzero_effect_is_counted_and_recomputed(self):
        # heat -0.6 entfernen -> ablated home_xg = 2.6; Tippwechsel genau dann,
        # wenn der neu gerechnete Tipp abweicht (deterministisch ueber _tip_for).
        home_xg, away_xg, heat = 2.0, 1.0, -0.6
        report = context_ablation({"predictions": [_fixture_with_heat(home_xg, away_xg, heat)]})
        heat_item = next(e for e in report["effects"] if e["effect"] == "heat_effect")
        self.assertEqual(heat_item["fixtures_affected"], 1)
        current = _tip_for(home_xg, away_xg, None, "group", ROUND)
        ablated = _tip_for(home_xg - heat, away_xg, None, "group", ROUND)
        if (ablated["home"], ablated["away"]) != (current["home"], current["away"]):
            self.assertEqual(heat_item["tip_changes_total"], 1)
            change = heat_item["changed_fixtures"][0]
            self.assertEqual(change["without_effect_tip"], ablated["tip"])
            self.assertEqual(change["with_effect_tip"], current["tip"])
        else:
            self.assertEqual(heat_item["tip_changes_total"], 0)
        # Invariante: Mover-Zahl == tip_changes_total.
        self.assertEqual(len(heat_item["changed_fixtures"]), heat_item["tip_changes_total"])

    def test_zero_delta_effect_is_inert(self):
        report = context_ablation({"predictions": [_fixture_with_heat(2.0, 1.0, -0.6)]})
        altitude = next(e for e in report["effects"] if e["effect"] == "altitude_effect")
        self.assertEqual(altitude["fixtures_affected"], 0)
        self.assertEqual(altitude["tip_changes_total"], 0)
        self.assertEqual(altitude["changed_fixtures"], [])

    def test_repo_predictions_ablation_invariants(self):
        import json
        from wm_tipps.paths import DATA_DIR

        path = DATA_DIR / "predictions.json"
        if not path.exists():
            self.skipTest("predictions.json nicht gebaut.")
        predictions = json.loads(path.read_text(encoding="utf-8"))
        if not predictions.get("predictions"):
            self.skipTest("Keine Predictions vorhanden.")
        report = context_ablation(predictions)
        self.assertEqual(len(report["effects"]), len(CONTEXT_EFFECTS))
        for item in report["effects"]:
            self.assertEqual(item["tip_changes_total"], sum(item["tip_changes"].values()))
            self.assertEqual(len(item["changed_fixtures"]), item["tip_changes_total"])
            self.assertGreaterEqual(item["fixtures_affected"], 0)


class NewsMarketConflictTests(unittest.TestCase):
    """T-0144: News dreht den Tipp gegen einen klaren Marktfavoriten."""

    def _prediction(self, status="scheduled", odds_away=1.87, odds_home=4.1):
        return {
            "match_id": "ko-099",
            "fixture": {"stage": "quarter", "home_team": "Norway", "away_team": "England",
                        "status": status},
            "odds": {"decimal_odds": {"home": odds_home, "draw": 3.7, "away": odds_away}},
            "xg_breakdown": {"home": {"news_effect": 0.065}, "away": {"news_effect": -0.522}},
        }

    def _report(self, with_tip="1:0", without_tip="0:1"):
        return {"effects": [{"effect": "news_effect", "changed_fixtures": [
            {"match_id": "ko-099", "round_id": ROUND,
             "with_effect_tip": with_tip, "without_effect_tip": without_tip}]}]}

    def test_flags_flip_against_market_favorite(self):
        out = news_market_conflicts(self._report(), {"predictions": [self._prediction()]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["market_favorite"], "away")
        self.assertAlmostEqual(out[0]["market_probability"], 0.510, places=2)
        self.assertEqual(out[0]["without_news_tip"], "0:1")

    def test_flip_with_the_market_is_not_flagged(self):
        # News dreht auf 0:2 -- das ist der Marktfavorit (away) -> kein Konflikt
        out = news_market_conflicts(self._report(with_tip="0:2"), {"predictions": [self._prediction()]})
        self.assertEqual(out, [])

    def test_played_matches_are_ignored(self):
        out = news_market_conflicts(self._report(), {"predictions": [self._prediction(status="played")]})
        self.assertEqual(out, [])

    def test_weak_market_favorite_is_not_flagged(self):
        # Fast-Coinflip (kein klarer Favorit) -> unter der 45%-Schwelle, kein Konflikt
        pred = self._prediction(odds_away=2.9, odds_home=2.8)
        out = news_market_conflicts(self._report(), {"predictions": [pred]})
        self.assertEqual(out, [])

    def test_missing_odds_is_not_flagged(self):
        pred = self._prediction()
        pred.pop("odds")
        out = news_market_conflicts(self._report(), {"predictions": [pred]})
        self.assertEqual(out, [])

    def test_draw_tip_is_not_a_conflict(self):
        out = news_market_conflicts(self._report(with_tip="1:1"), {"predictions": [self._prediction()]})
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
