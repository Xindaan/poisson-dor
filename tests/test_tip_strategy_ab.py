from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.scoring import DEFAULT_ROUND_ID
from wm_tipps.tip_strategy_ab import KAPPAS, _aggregate, _live_samples, aggressive_tip


class AggressiveTipTests(unittest.TestCase):
    def test_higher_kappa_not_fewer_goals(self):
        base = aggressive_tip(1.5, 1.1, "group", DEFAULT_ROUND_ID, 1.0)
        aggr = aggressive_tip(1.5, 1.1, "group", DEFAULT_ROUND_ID, 1.5)
        self.assertGreaterEqual(sum(aggr), sum(base))

    def test_aggregate_structure(self):
        samples = [
            (1.5, 1.1, "group", [2, 1], None, None),
            (2.0, 0.5, "group", [2, 0], None, None),
        ]
        agg = _aggregate(samples, DEFAULT_ROUND_ID)
        self.assertEqual(set(agg.keys()), {str(k) for k in KAPPAS})
        self.assertEqual(agg["1.0"]["matches"], 2)
        self.assertIn("exact_hits", agg["1.0"])
        self.assertIsNotNone(agg["1.0"]["points_per_match"])

    def test_live_samples_only_played(self):
        preds = [{"match_id": "m1", "fixture": {"stage": "group"}, "xg": {"home": 1.5, "away": 1.0}}]
        fixtures = [
            {"match_id": "m1", "status": "played", "result": [2, 1]},
            {"match_id": "m2", "status": "scheduled", "result": None},
        ]
        samples = _live_samples(preds, fixtures)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0][3], [2, 1])


if __name__ == "__main__":
    unittest.main()
