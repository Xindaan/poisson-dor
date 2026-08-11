from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.favorite_host_calibration import (
    _bin,
    _favorite_calibration,
    _host_calibration,
    _outcome,
    _verdict,
)


class HelperTests(unittest.TestCase):
    def test_outcome(self):
        self.assertEqual(_outcome([2, 0]), "home")
        self.assertEqual(_outcome([1, 1]), "draw")
        self.assertEqual(_outcome([0, 3]), "away")

    def test_bin_boundaries(self):
        self.assertEqual(_bin(0.55), (0.50, 0.60))
        self.assertEqual(_bin(0.95), (0.85, 1.01))
        self.assertIsNone(_bin(0.30))  # kein klarer Favorit


class FavoriteCalibrationTests(unittest.TestCase):
    def test_underconfident_favorite_positive_gap(self):
        # Modell sagt Favorit 0.55, Favorit gewinnt aber jedes Mal -> Gap > 0
        model = {"home": 0.55, "draw": 0.25, "away": 0.20}
        mkt = {"home": 0.60, "draw": 0.22, "away": 0.18}
        samples = [(model, model, mkt, "home", {}) for _ in range(10)]
        res = _favorite_calibration(samples)
        self.assertEqual(res["matches"], 10)
        self.assertGreater(res["mean_gap_model"], 0.0)  # under-confident
        # Markt war naeher an der Realitaet (0.60 vs 0.55) -> kleinerer Gap
        self.assertLess(res["mean_gap_market"], res["mean_gap_model"])
        bin_row = next(b for b in res["bins"] if b["bin"] == "0.5-0.6")
        self.assertEqual(bin_row["actual_fav_winrate"], 1.0)

    def test_tossups_excluded(self):
        model = {"home": 0.35, "draw": 0.33, "away": 0.32}  # Favorit < 0.40
        res = _favorite_calibration([(model, model, None, "home", {})])
        self.assertEqual(res["matches"], 0)


class HostCalibrationTests(unittest.TestCase):
    def test_bonus_raises_host_winprob(self):
        # Host=home, leicht unterlegen per Elo; +0.18 muss die Host-Siegwkt heben
        pre_elo = {"home": 1700, "away": 1750}
        model = {"home": 0.40, "draw": 0.28, "away": 0.32}
        host_rows = [("home", pre_elo, None, model, None, None, "home", "T: H - A [1,0]")]
        res = _host_calibration(host_rows)
        self.assertEqual(res["matches"], 1)
        self.assertGreater(res["model_pred_with_bonus_018"], res["model_pred_no_bonus"])
        self.assertEqual(res["actual_host_winrate"], 1.0)  # host won

    def test_empty(self):
        self.assertEqual(_host_calibration([])["matches"], 0)


class VerdictTests(unittest.TestCase):
    def test_underconfident_and_adequate_host(self):
        fav = {"mean_gap_model": 0.037, "mean_gap_ensemble": 0.03, "mean_gap_market": 0.007}
        host = {"matches": 29, "raw_host_effect": 0.069, "residual_after_bonus": 0.027}
        v = _verdict(fav, host)
        self.assertIn("under-confident", v)
        self.assertIn("adaequat", v)

    def test_host_bonus_too_small(self):
        fav = {"mean_gap_model": 0.0, "mean_gap_ensemble": 0.0, "mean_gap_market": 0.0}
        host = {"matches": 20, "raw_host_effect": 0.15, "residual_after_bonus": 0.10}
        self.assertIn("zu KLEIN", _verdict(fav, host))


if __name__ == "__main__":
    unittest.main()
