from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.live_calibration import signal_calibration, totals_adjustment


def _pred(mid, home_xg, away_xg, effect=None):
    breakdown = {"home": {}, "away": {}}
    if effect:
        breakdown["home"][effect] = -0.1
    return {
        "match_id": mid,
        "xg": {"home": home_xg, "away": away_xg},
        "probabilities": {"blended": {"home": 0.5, "draw": 0.25, "away": 0.25}},
        "xg_breakdown": breakdown,
    }


class SignalBreakerTests(unittest.TestCase):
    def test_firing_detection_and_inert_when_insufficient(self):
        preds = [_pred("m1", 1.5, 1.0, "heat_effect")]
        results = {"m1": {"actual": [2, 0]}}
        rep = signal_calibration(preds, results, min_firings=10)
        heat = next(s for s in rep["signals"] if s["signal"] == "heat")
        self.assertEqual(heat["firings"], 1)
        self.assertEqual(heat["status"], "insufficient_data")
        self.assertEqual(heat["multiplier"], 1.0)
        # ein nicht gefeuertes Signal bleibt bei 0 Feuerungen
        travel = next(s for s in rep["signals"] if s["signal"] == "travel")
        self.assertEqual(travel["firings"], 0)


class TotalsAdjustTests(unittest.TestCase):
    def test_insufficient_data_is_inert(self):
        rep = totals_adjustment([_pred("m1", 1.5, 1.0)], {"m1": {"actual": [2, 1]}}, min_matches=15)
        self.assertEqual(rep["status"], "insufficient_data")
        self.assertEqual(rep["applied_multiplier"], 1.0)
        self.assertAlmostEqual(rep["expected_goals"], 2.5)
        self.assertAlmostEqual(rep["actual_goals"], 3.0)

    def test_active_above_threshold_but_not_applied(self):
        preds = [_pred(f"m{i}", 1.0, 1.0) for i in range(20)]
        results = {f"m{i}": {"actual": [2, 1]} for i in range(20)}  # 3 Tore real vs 2 erwartet
        rep = totals_adjustment(preds, results, min_matches=15)
        self.assertEqual(rep["status"], "active")
        self.assertGreater(rep["ratio"], 1.0)
        self.assertEqual(rep["applied_multiplier"], 1.0)  # advisory, nie automatisch


if __name__ == "__main__":
    unittest.main()
