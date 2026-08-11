from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.eval_live import build_live_eval, live_eval_markdown
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID  # noqa: E402

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def _pred(match_id, home, away, tip, ep, *, stage="group", model=None, blended=None, market=None,
          kickoff="2026-06-11T19:00:00+00:00", xg=(1.5, 1.0)):
    return {
        "match_id": match_id,
        "fixture": {"home_team": home, "away_team": away, "stage": stage, "kickoff_utc": kickoff},
        "xg": {"home": xg[0], "away": xg[1]},
        "probabilities": {"model": model or {"home": 0.6, "draw": 0.25, "away": 0.15},
                          "blended": blended or {"home": 0.55, "draw": 0.25, "away": 0.20}},
        "odds": {"probabilities": market or {"home": 0.5, "draw": 0.27, "away": 0.23}, "source": "x"},
        "round_tips": {
            DEFAULT_ROUND_ID: {"tip": tip, "expected_points": ep},
            SECONDARY_ROUND_ID: {"tip": tip, "expected_points": ep},
        },
    }


PREDS = [
    _pred("ga-001", "Mexico", "South Africa", "1:0", 1.74),
    _pred("ga-002", "South Korea", "Czech Republic", "2:1", 1.20),
    _pred("gd-019", "USA", "Paraguay", "1:0", 1.50,
          kickoff="2026-06-12T19:00:00+00:00"),  # gespielt (vor NOW), aber Ergebnis fehlt
]
RESULTS = {
    "ga-001": {"actual": [2, 0], "penalty_winner": None},
    "ga-002": {"actual": [2, 1], "penalty_winner": None},
}


class LiveEvalTests(unittest.TestCase):
    def setUp(self):
        self.ev = build_live_eval(predictions=PREDS, results=RESULTS, backtest_ppm=1.95, now=NOW, write=False)

    def test_earned_points_per_round(self):
        # Mexico 2:0 vs Tipp 1:0 -> Tendenz richtig = 2; SK 2:1 vs 2:1 -> exakt = 4.
        r = self.ev["rounds"][DEFAULT_ROUND_ID]
        self.assertEqual(r["matches"], 2)
        self.assertEqual(r["points_total"], 6)  # 2 + 4
        self.assertEqual(r["points_per_match"], 3.0)

    def test_only_matches_with_results_counted(self):
        # gd-019 hat kein Ergebnis -> nicht ausgewertet, aber als pending gezaehlt.
        self.assertEqual(self.ev["_meta"]["matches_evaluated"], 2)
        self.assertEqual(self.ev["_meta"]["results_pending"], 1)

    def test_calibration_brier_per_source(self):
        cal = self.ev["calibration"]
        for src in ("model", "blended", "market"):
            self.assertEqual(cal[src]["matches"], 2)
            self.assertIsNotNone(cal[src]["mean_brier"])
        # best_calibrated_source ist die mit kleinstem Brier
        best = self.ev["_meta"]["best_calibrated_source"]
        self.assertEqual(best, min(("model", "blended", "market"), key=lambda s: cal[s]["mean_brier"]))

    def test_drift_flags_small_n(self):
        self.assertEqual(self.ev["drift"]["backtest_ppm"], 1.95)
        self.assertIn("zu klein", self.ev["drift"]["note"])  # n < 10

    def test_penalty_winner_applies_in_ko(self):
        # KO-Spiel 1:1, Elfer-Sieger home: Elfer-Runde wertet 2:1, die andere 1:1.
        preds = [_pred("ko-1", "A", "B", "1:0", 1.0, stage="knockout")]
        res = {"ko-1": {"actual": [1, 1], "penalty_winner": "home"}}
        ev = build_live_eval(predictions=preds, results=res, backtest_ppm=1.95, now=NOW, write=False)
        m = ev["matches"][0]["rounds"]
        # Elfer-Runde: actual wird 2:1 -> Tipp 1:0 hat dieselbe Tordifferenz (+1) = 4 (KO)
        self.assertEqual(m[DEFAULT_ROUND_ID]["points"], 4)
        # Zweitrunde: actual bleibt 1:1 -> Tipp 1:0 (Heimsieg) vs Remis -> 0
        self.assertEqual(m[SECONDARY_ROUND_ID]["points"], 0)

    def test_results_from_fixtures_extracts_played(self):
        from wm_tipps.eval_live import _results_from_fixtures
        fx = [
            {"match_id": "ga-001", "status": "played", "result": [2, 0]},
            {"match_id": "ga-003", "status": "scheduled", "result": None},
        ]
        r = _results_from_fixtures(fx)
        self.assertEqual(r["ga-001"]["actual"], [2, 0])
        self.assertEqual(r["ga-001"]["source"], "openfootball")
        self.assertNotIn("ga-003", r)

    def test_totals_inflation_theta(self):
        # observed: (2+0)+(2+1)=5 Tore; Modell-erwartet: 2*(1.5+1.0)=5 -> theta=1.0
        t = self.ev["totals"]
        self.assertEqual(t["matches"], 2)
        self.assertEqual(t["observed_goals"], 5.0)
        self.assertEqual(t["model_expected_goals"], 5.0)
        self.assertAlmostEqual(t["inflation_theta"], 1.0, places=4)
        self.assertIn("Prior", t["note"])  # n < 20

    def test_markdown_renders(self):
        text = live_eval_markdown(self.ev)
        self.assertIn("Live-Auswertung", text)
        self.assertIn("Mexico 2:0 South Africa", text)


if __name__ == "__main__":
    unittest.main()
