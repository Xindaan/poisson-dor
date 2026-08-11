from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.rival_profiles import (
    _norm_actual,
    _parse,
    _pearson,
    _pool_points,
    _profile,
    _round_profiles,
    _verdict,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID


class ScoringAndActualTests(unittest.TestCase):
    def test_norm_actual_handles_string_and_list(self):
        # T-0097-Regression: String-actuals duerfen nicht uebersprungen werden
        self.assertEqual(_norm_actual("2:0"), (2, 0))
        self.assertEqual(_norm_actual([1, 3]), (1, 3))
        self.assertIsNone(_norm_actual(None))
        self.assertIsNone(_norm_actual("kaputt"))

    def test_norm_actual_dict_per_pool_penalty(self):
        # T-0120 Option A: K.o.-Elfmeter-Spiel -> Dict mit pro-Pool-Scoreline.
        # NIE-MAR live: regulaer 1:1 (Scope n.V.), inkl. Elfer 3:4.
        ko = {"regulation": [1, 1], "penalty": [3, 4]}
        self.assertEqual(_norm_actual(ko, DEFAULT_ROUND_ID), (3, 4))         # Default: inkl. Elfmeter
        self.assertEqual(_norm_actual(ko, SECONDARY_ROUND_ID), (1, 1))    # Zweitrunde: nach Verlaengerung
        # fehlender penalty-Key -> defensiv auf regulation
        self.assertEqual(_norm_actual({"regulation": [2, 1]}, DEFAULT_ROUND_ID), (2, 1))

    def test_ko_penalty_tip_scores_differ_per_pool(self):
        # Derselbe Tipp 1:2 auf NIE-MAR (reg 1:1 / pen 3:4) wird je Pool anders gewertet:
        #   Default-Runde: gegen 3:4 -> gleiche Tordifferenz -> Differenz-Punkte
        #   Zweitrunde: gegen 1:1 (Remis), 1:2 ist Auswaerts -> 0 Pkt
        ko = {"ko-075": {"regulation": [1, 1], "penalty": [3, 4]}}
        pbi = {"ko-075": {"match_id": "ko-075", "fixture": {"stage": "round_of_32"}}}
        p15 = _profile("X", {"ko-075": "1:2"}, ko, {}, pbi, DEFAULT_ROUND_ID)
        pvv = _profile("X", {"ko-075": "1:2"}, ko, {}, pbi, SECONDARY_ROUND_ID)
        self.assertEqual(p15["points"], 4)
        self.assertEqual(pvv["points"], 0)

    def test_pool_points_wrong_draw_is_tendency_not_difference(self):
        # 2:2 auf 1:1 = falscher Remis-Score -> Tendenz (2), NICHT Tordifferenz (3)
        self.assertEqual(_pool_points((2, 2), (1, 1), "group", DEFAULT_ROUND_ID), 2)
        self.assertEqual(_pool_points((1, 1), (1, 1), "group", DEFAULT_ROUND_ID), 4)  # exakt
        self.assertEqual(_pool_points((2, 1), (1, 0), "group", DEFAULT_ROUND_ID), 3)  # Diff (Nicht-Remis)
        self.assertEqual(_pool_points((3, 0), (1, 0), "group", DEFAULT_ROUND_ID), 2)  # Tendenz
        self.assertEqual(_pool_points((0, 1), (1, 0), "group", DEFAULT_ROUND_ID), 0)  # falsch
        self.assertEqual(_pool_points((1, 1), (2, 0), "group", DEFAULT_ROUND_ID), 0)  # Remis-Tipp, Nicht-Remis

    def test_string_actual_is_counted_as_played(self):
        # Regression: frueher wurde "2:0" (str) uebersprungen -> played zu niedrig
        tips = {"m1": "0:1", "m2": "1:0"}
        actuals = {"m1": "0:1", "m2": "2:0"}  # beide als String gespeichert
        prof = _profile("T", tips, actuals, {}, {}, DEFAULT_ROUND_ID)
        self.assertEqual(prof["played"], 2)
        self.assertEqual(prof["exact_rate"], 0.5)  # m1 exakt (0:1)


class HelperTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(_parse("2:1"), (2, 1))
        self.assertIsNone(_parse("kaputt"))

    def test_pearson_perfect_positive(self):
        self.assertEqual(_pearson([1, 2, 3], [2, 4, 6]), 1.0)

    def test_pearson_too_few(self):
        self.assertIsNone(_pearson([1, 2], [3, 4]))


class ProfileTests(unittest.TestCase):
    def test_profile_metrics(self):
        # Spieler tippt 2 Heimsiege + 1 Remis; ein Spiel hat ein Ergebnis
        tips = {"m1": "2:0", "m2": "1:0", "m3": "1:1"}
        actuals = {"m1": [2, 0]}  # m1 exakt getroffen
        model_tips = {"m1": "1:0", "m2": "1:0", "m3": "1:0"}  # m2 == Modell
        preds_by_id = {"m1": {"fixture": {"stage": "group"}}}
        prof = _profile("Tester", tips, actuals, model_tips, preds_by_id, DEFAULT_ROUND_ID)
        self.assertEqual(prof["tips"], 3)
        self.assertAlmostEqual(prof["draw_rate"], round(1 / 3, 3))
        self.assertAlmostEqual(prof["mean_tip_goals"], round((2 + 1 + 2) / 3, 2))
        self.assertAlmostEqual(prof["model_similarity"], round(1 / 3, 3))  # nur m2
        self.assertEqual(prof["played"], 1)
        self.assertEqual(prof["points"], 4)  # m1 exakt
        self.assertEqual(prof["exact_rate"], 1.0)
        self.assertEqual(prof["home_lean"], round(2 / 3, 3))  # 2 Heim, 0 Auswaerts

    def test_empty_profile(self):
        self.assertIsNone(_profile("X", {}, {}, {}, {}, DEFAULT_ROUND_ID))


class RoundAndVerdictTests(unittest.TestCase):
    def test_round_sorts_by_points_and_computes_corr(self):
        players = {
            "A": {f"m{i}": "1:0" for i in range(10)},
            "B": {f"m{i}": "3:1" for i in range(10)},
        }
        actuals = {f"m{i}": [1, 0] for i in range(10)}  # A trifft exakt, B Tendenz
        rd = _round_profiles(DEFAULT_ROUND_ID, players, actuals, [])
        self.assertEqual(rd["players"], 2)
        # A (1:0 exakt) muss vor B (3:1) liegen
        self.assertEqual(rd["profiles"][0]["name"], "A")
        self.assertEqual(rd["profiles"][0]["points"], 40)  # 10x exakt

    def test_verdict_low_corr_matches_risk_dial(self):
        v = _verdict({"aggressiveness_points_corr": 0.05, "reliable_players": 9})
        self.assertIn("NICHT", v)

    def test_verdict_no_data(self):
        v = _verdict({"aggressiveness_points_corr": None, "reliable_players": 1})
        self.assertIn("zu wenig Daten", v)


if __name__ == "__main__":
    unittest.main()
