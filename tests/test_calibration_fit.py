from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.backtest import ensemble_calibrated_matrix, tip_from_ensemble
from wm_tipps.calibration_fit import (
    RHO_GRID,
    TEMPERATURE_GRID,
    dixon_coles_adjust,
    fit_blend_weight,
    fit_rho,
    fit_temperature,
    temper_within_class,
)
from wm_tipps.historical import build_historical_dataset
from wm_tipps.model import conditional_draw_tilt
from wm_tipps.scoring import best_kicktipp_tip


class TemperWithinClassTests(unittest.TestCase):
    def test_identity_at_T1(self):
        m = {"2:0": 0.3, "1:0": 0.2, "1:1": 0.3, "0:1": 0.2}
        self.assertEqual(temper_within_class(m, 1.0), m)

    def test_conserves_class_mass(self):
        m = {"2:0": 0.3, "1:0": 0.1, "1:1": 0.4, "0:1": 0.2}  # H 0.4 / D 0.4 / A 0.2
        t = temper_within_class(m, 1.3)
        self.assertAlmostEqual(t["2:0"] + t["1:0"], 0.4)
        self.assertAlmostEqual(t["1:1"], 0.4)
        self.assertAlmostEqual(t["0:1"], 0.2)
        self.assertAlmostEqual(sum(t.values()), 1.0)

    def test_flattens_when_T_gt_1(self):
        m = {"2:0": 0.35, "1:0": 0.05}  # eine Klasse
        t = temper_within_class(m, 1.5)
        self.assertLess(t["2:0"], 0.35)       # groesste Zelle schrumpft
        self.assertGreater(t["1:0"], 0.05)    # kleinste waechst
        self.assertAlmostEqual(t["2:0"] + t["1:0"], 0.4)


class FitTemperatureTests(unittest.TestCase):
    def test_fit_structure(self):
        matches = [
            ({"1:0": 0.5, "2:0": 0.3, "1:1": 0.2}, "1:0"),
            ({"2:1": 0.4, "1:0": 0.3, "1:1": 0.3}, "1:1"),
        ]
        fit = fit_temperature(matches)
        self.assertIn(fit["best_T"], TEMPERATURE_GRID)
        self.assertEqual(len(fit["grid"]), len(TEMPERATURE_GRID))
        self.assertIsNotNone(fit["base_loglik"])


class DixonColesTests(unittest.TestCase):
    M = {"0:0": 0.1, "1:0": 0.2, "1:1": 0.15, "0:1": 0.1, "2:0": 0.45}

    def test_identity_at_rho0(self):
        self.assertEqual(dixon_coles_adjust(self.M, 0.0), self.M)

    def test_negative_rho_lifts_draw_share(self):
        adj = dixon_coles_adjust(self.M, -0.1)
        self.assertAlmostEqual(sum(adj.values()), 1.0)
        # Remis (1:1) relativ zu 1:0 angehoben
        self.assertGreater(adj["1:1"] / adj["1:0"], self.M["1:1"] / self.M["1:0"])

    def test_fit_rho_structure(self):
        matches = [({"1:0": 0.5, "1:1": 0.3, "0:1": 0.2}, "1:1"),
                   ({"2:1": 0.4, "1:1": 0.3, "1:0": 0.3}, "1:1")]
        fit = fit_rho(matches)
        self.assertIn(fit["best_rho"], RHO_GRID)
        self.assertEqual(len(fit["grid"]), len(RHO_GRID))


class EnsembleMatrixReconciliationTests(unittest.TestCase):
    def test_matrix_tip_equals_tip_from_ensemble(self):
        # Spiegel-Schutz: best_kicktipp_tip(conditional_draw_tilt(
        # ensemble_calibrated_matrix)) muss exakt den tip_from_ensemble
        # reproduzieren (sonst driftet der Fit). Der Tilt (T-0103/H4) ist ein
        # Tipp-Stage-Transform und gehoert daher in BEIDE Seiten des Spiegels.
        # Der DC-rho (T-0104/H13) wirkt dagegen AT-SOURCE (vor Blend) und laesst sich
        # NICHT aus der kalibrierten Matrix nachbilden -> der Spiegel wird rein
        # strukturell bei DC=0 geprueft; die DC-Wirkung deckt der CV-Harness +
        # run_backtest ab. (ensemble_calibrated_matrix bleibt bewusst DC-frei = Referenz.)
        # write=False + Rueckgabewert statt Schreiben/Lesen der echten data/-Datei
        # (T-0070: Tests duerfen die getrackten Backtest-JSONs nicht churnen).
        import wm_tipps.model as wm_model
        self.addCleanup(setattr, wm_model, "DRAW_DC_RHO", wm_model.DRAW_DC_RHO)
        wm_model.DRAW_DC_RHO = 0.0
        data = build_historical_dataset("2018", write=False)
        rows = [r for r in data.get("results", []) if r.get("pre_odds")]
        self.assertTrue(rows)
        for row in rows[:6]:
            matrix = ensemble_calibrated_matrix(row["pre_elo"], row["pre_odds"])
            self.assertIsNotNone(matrix)
            tip = best_kicktipp_tip(conditional_draw_tilt(matrix), row["stage"])
            ens = tip_from_ensemble(row["pre_elo"], row["pre_odds"], row["stage"])
            self.assertEqual((tip["home"], tip["away"]), ens, row.get("match"))

    def test_fit_blend_weight_structure(self):
        data = build_historical_dataset("2018", write=False)
        rows = [
            (r["pre_elo"], r["pre_odds"], f"{int(r['actual'][0])}:{int(r['actual'][1])}")
            for r in data.get("results", [])
            if r.get("pre_odds")
        ][:20]
        self.assertTrue(rows)
        fit = fit_blend_weight(rows)
        self.assertIn("best_weight", fit)
        self.assertEqual(fit["live_weight"], round(0.20, 4))
        self.assertTrue(any(g["weight"] == 0.15 for g in fit["grid"]))


if __name__ == "__main__":
    unittest.main()
