from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.risk_dial import (
    RISK_KAPPAS,
    _candidate_stats,
    _live_counterfactual,
    _overtake_grid,
    _tilt_tip,
    _variance_frontier,
    _verdict,
)
from wm_tipps.scoring import (
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    Score,
    points_for_stage,
    round_resolves_penalties,
)


class TiltSelectorTests(unittest.TestCase):
    def test_kappa0_is_ep_max(self):
        cands = [
            {"score": Score(1, 0), "ep": 2.0, "sigma": 1.0, "p_exact": 0.3},
            {"score": Score(2, 1), "ep": 1.5, "sigma": 2.0, "p_exact": 0.2},
        ]
        self.assertEqual(_tilt_tip(cands, 0.0).label, "1:0")

    def test_high_kappa_prefers_sigma(self):
        cands = [
            {"score": Score(1, 0), "ep": 2.0, "sigma": 1.0, "p_exact": 0.3},
            {"score": Score(2, 1), "ep": 1.5, "sigma": 2.0, "p_exact": 0.2},
        ]
        # kappa=1.0: 1:0->3.0, 2:1->3.5 -> der varianzreichere Tipp gewinnt
        self.assertEqual(_tilt_tip(cands, 1.0).label, "2:1")

    def test_candidate_stats_exact_certainty_has_zero_sigma(self):
        # Sicheres Ergebnis 1:0 -> exakter Tipp 1:0 = immer 4 Pkt, sigma 0
        stats = _candidate_stats({"1:0": 1.0}, "group", DEFAULT_ROUND_ID)
        by_label = {f"{c['score'].home}:{c['score'].away}": c for c in stats}
        self.assertAlmostEqual(by_label["1:0"]["ep"], 4.0)
        self.assertAlmostEqual(by_label["1:0"]["sigma"], 0.0)
        # 2:1 trifft die Tordifferenz nicht (1 vs 1? nein: 1:0 diff 1, 2:1 diff 1)
        self.assertAlmostEqual(by_label["2:1"]["ep"], 3.0)  # difference
        self.assertAlmostEqual(by_label["0:1"]["ep"], 0.0)  # falsche Tendenz


class VarianceFrontierTests(unittest.TestCase):
    def test_frontier_sigma_max_costs_ep(self):
        samples = [
            # 6-Tupel wie `_backtest_samples`: (..., penalty_winner, shootout).
            # Gruppenspiele haben kein Elfmeterschiessen -> beide None.
            (1.6, 0.9, "group", [1, 0], None, None),
            (1.2, 1.1, "group", [2, 2], None, None),
            (2.1, 0.5, "group", [3, 0], None, None),
        ]
        fr = _variance_frontier(samples, DEFAULT_ROUND_ID)
        self.assertEqual(fr["matches"], 3)
        # Sigma-Max opfert EP gegenueber EP-Max (oder ist gleich, nie hoeher)
        self.assertLessEqual(fr["sigma_max"]["mean_ep"], fr["ep_max"]["mean_ep"] + 1e-9)
        self.assertIn("std_gain_for_max_variance", fr)
        self.assertTrue(0.0 <= fr["flip_rate"] <= 1.0)


class OvertakeGridTests(unittest.TestCase):
    def test_deficit_zero_clone_is_certain(self):
        # Leader = kappa=0-Klon; bei D=0 ist sum(adv)>=0 immer wahr -> P=1.0
        n = 30
        pts = {k: [2] * n for k in RISK_KAPPAS}
        grid = _overtake_grid(pts, [True] * n)
        cell = next(c for c in grid["cells"] if c["deficit"] == 0)
        self.assertEqual(cell["by_kappa"]["0.0"], 1.0)
        self.assertEqual(cell["best_kappa"], 0.0)

    def test_identical_kappas_cannot_overtake_positive_deficit(self):
        # Alle kappas identisch zum Klon -> adv=0 -> P(sum>=1)=0
        n = 30
        pts = {k: [3] * n for k in RISK_KAPPAS}
        grid = _overtake_grid(pts, [True] * n)
        cell = next(c for c in grid["cells"] if c["deficit"] == 1 and c["matches_left"] == 3)
        self.assertEqual(cell["by_kappa"]["2.0"], 0.0)


class LiveCounterfactualTests(unittest.TestCase):
    def test_counterfactual_ranks_against_field(self):
        predictions = [
            {"match_id": "m1", "xg": {"home": 1.8, "away": 0.7}, "fixture": {"stage": "group"}},
        ]
        pool_tips = {
            "actuals": {"m1": [1, 0]},
            "players": {DEFAULT_ROUND_ID: {"rivalA": {"m1": "1:0"}, "rivalB": {"m1": "0:2"}}},
        }
        lv = _live_counterfactual(DEFAULT_ROUND_ID, predictions, pool_tips)
        self.assertEqual(lv["played"], 1)
        self.assertEqual(lv["field_size"], 2)
        # rivalA traf exakt (4 Pkt) -> Leader
        self.assertEqual(lv["field_leader_points"], 4)
        self.assertEqual(set(lv["our_by_kappa"]), {f"{k}" for k in RISK_KAPPAS})
        for row in lv["our_by_kappa"].values():
            self.assertGreaterEqual(row["rank"], 1)

    def test_no_played_matches(self):
        lv = _live_counterfactual(DEFAULT_ROUND_ID, [], {"actuals": {}, "players": {}})
        self.assertEqual(lv["played"], 0)

    def test_knockout_penalty_actuals_are_normalized_per_round(self):
        predictions = [
            {"match_id": "m1", "xg": {"home": 1.0, "away": 1.0}, "fixture": {"stage": "round_of_32"}},
        ]
        actual = {"regulation": [1, 1], "penalty": [4, 5]}

        default_pool = {
            "actuals": {"m1": actual},
            "players": {DEFAULT_ROUND_ID: {"shootout": {"m1": "4:5"}, "draw": {"m1": "1:1"}}},
        }
        # RUNDENAGNOSTISCH: geprueft wird, WELCHER Tipp als exakt gewertet wird,
        # nicht mit wieviel Punkten. Die Punktwerte kommen aus der Runden-
        # konfiguration und duerfen sich zwischen neutralen Defaults und einer
        # lokalen rounds_local.py unterscheiden.
        exakt_default = points_for_stage("round_of_32", DEFAULT_ROUND_ID)["exact"]
        exakt_secondary = points_for_stage("round_of_32", SECONDARY_ROUND_ID)["exact"]

        default_live = _live_counterfactual(DEFAULT_ROUND_ID, predictions, default_pool)
        self.assertEqual(default_live["played"], 1)
        # Runde mit Elfmeter-Scope -> die Elfer-Scoreline 4:5 ist der exakte Tipp.
        self.assertTrue(round_resolves_penalties(DEFAULT_ROUND_ID))
        self.assertEqual(default_live["field_leader_points"], exakt_default)

        secondary_pool = {
            "actuals": {"m1": actual},
            "players": {SECONDARY_ROUND_ID: {"shootout": {"m1": "4:5"}, "draw": {"m1": "1:1"}}},
        }
        secondary_live = _live_counterfactual(SECONDARY_ROUND_ID, predictions, secondary_pool)
        self.assertEqual(secondary_live["played"], 1)
        # Runde ohne Elfmeter-Scope -> das Remis 1:1 ist der exakte Tipp.
        self.assertFalse(round_resolves_penalties(SECONDARY_ROUND_ID))
        self.assertEqual(secondary_live["field_leader_points"], exakt_secondary)


class VerdictTests(unittest.TestCase):
    def test_no_usable_variance_says_dont_chase(self):
        v = _verdict({"std_gain_for_max_variance": -0.05, "ep_cost_for_max_variance": 0.62})
        self.assertIn("KEIN nutzbarer", v)

    def test_meaningful_variance_says_limited(self):
        v = _verdict({"std_gain_for_max_variance": 0.5, "ep_cost_for_max_variance": 0.3})
        self.assertIn("Begrenzter", v)


if __name__ == "__main__":
    unittest.main()
