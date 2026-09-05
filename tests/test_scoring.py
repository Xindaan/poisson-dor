from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.scoring import (  # noqa: E402
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    Score,
    _home_shootout_prob,
    actual_for_round,
    best_kicktipp_tip,
    is_knockout_stage,
    is_stage_tippable,
    kicktipp_points,
    points_for_stage,
    resolve_extra_time,
    resolve_knockout_draw_probabilities,
    round_name,
    round_resolves_penalties,
    round_rules_payload,
)


class ExtraTimeKnockoutTests(unittest.TestCase):
    def test_is_knockout_stage(self):
        self.assertFalse(is_knockout_stage("group"))
        self.assertFalse(is_knockout_stage("Vorrunde"))
        for ko in ("knockout", "round_of_32", "round_of_16", "final", "quarter_final"):
            self.assertTrue(is_knockout_stage(ko), ko)

    def test_et_reduces_draw_mass_and_conserves_total(self):
        probs = {"0:0": 0.08, "1:1": 0.16, "2:2": 0.02, "1:0": 0.19, "0:1": 0.19, "2:1": 0.18, "1:2": 0.18}
        resolved = resolve_extra_time(probs)
        draw_before = sum(p for l, p in probs.items() if l.split(":")[0] == l.split(":")[1])
        draw_after = sum(p for l, p in resolved.items() if l.split(":")[0] == l.split(":")[1])
        self.assertLess(draw_after, draw_before)              # Remis schrumpft
        self.assertLess(draw_after, draw_before * 0.75)       # spuerbar (~45-50% entschieden)
        self.assertAlmostEqual(sum(resolved.values()), 1.0, places=6)  # Masse erhalten

    def test_decisive_cells_unchanged_by_et(self):
        probs = {"1:1": 0.4, "2:0": 0.6}
        resolved = resolve_extra_time(probs)
        self.assertAlmostEqual(resolved.get("2:0", 0.0), 0.6)  # entscheidende Zelle bleibt

    def test_pool_b_ko_no_longer_overtips_draw(self):
        # Remislastige 90'-Matrix -> Pool B tippt nach ET-Transform entscheidend.
        heavy = {"1:1": 0.30, "0:0": 0.06, "1:0": 0.17, "0:1": 0.14, "2:1": 0.14, "1:2": 0.11, "2:0": 0.05, "0:2": 0.03}
        tip = best_kicktipp_tip(heavy, "knockout", round_id=SECONDARY_ROUND_ID)
        self.assertNotEqual(tip["home"], tip["away"])

    def test_pool_b_ko_keeps_draw_when_overwhelming(self):
        # Bei extrem dominanter Remis-Masse bleibt 1:1 auch nach ET EP-optimal.
        tip = best_kicktipp_tip({"1:1": 1.0}, "knockout", round_id=SECONDARY_ROUND_ID)
        self.assertEqual((tip["home"], tip["away"]), (1, 1))


class PenaltyAwareKnockoutTests(unittest.TestCase):
    def test_round_resolves_penalties_flag(self):
        self.assertTrue(round_resolves_penalties(DEFAULT_ROUND_ID))  # Elfer-Scope
        self.assertFalse(round_resolves_penalties(SECONDARY_ROUND_ID))  # Zweitrunde: nach Verlaengerung

    def test_resolve_redistributes_draws_and_conserves_mass(self):
        resolved = resolve_knockout_draw_probabilities({"1:1": 0.6, "2:0": 0.4}, home_shootout_prob=0.5)
        self.assertAlmostEqual(resolved.get("2:1", 0), 0.3)
        self.assertAlmostEqual(resolved.get("1:2", 0), 0.3)
        self.assertAlmostEqual(resolved.get("2:0", 0), 0.4)
        self.assertNotIn("1:1", resolved)
        self.assertAlmostEqual(sum(resolved.values()), 1.0)

    def test_home_shootout_prob_tilts_toward_favorite(self):
        # Heim klar favorisiert (mehr Heimsieg-Wkt) -> > 0.5, aber gedaempft.
        favorite = _home_shootout_prob({"2:0": 0.6, "0:2": 0.2, "1:1": 0.2})
        self.assertGreater(favorite, 0.5)
        self.assertLess(favorite, 0.75)
        even = _home_shootout_prob({"2:0": 0.3, "0:2": 0.3, "1:1": 0.4})
        self.assertAlmostEqual(even, 0.5)

    def test_penalty_round_knockout_never_tips_a_draw(self):
        # Matrix komplett auf 1:1 -> im KO der Elfer-Runde entscheidet immer der Elfer,
        # ein Remis-Tipp kann nie exakt sein -> Modell tippt entscheidend.
        tip = best_kicktipp_tip({"1:1": 1.0}, "knockout", round_id=DEFAULT_ROUND_ID)
        self.assertNotEqual(tip["home"], tip["away"])

    def test_secondary_round_knockout_keeps_draw(self):
        # Die Zweitrunde wertet nach Verlaengerung -> 1:1 bleibt moeglich.
        tip = best_kicktipp_tip({"1:1": 1.0}, "knockout", round_id=SECONDARY_ROUND_ID)
        self.assertEqual((tip["home"], tip["away"]), (1, 1))

    def test_group_stage_keeps_draw_for_both_rounds(self):
        for round_id in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID):
            tip = best_kicktipp_tip({"1:1": 1.0}, "group", round_id=round_id)
            self.assertEqual((tip["home"], tip["away"]), (1, 1))


class ScoringTests(unittest.TestCase):
    def test_group_exact_difference_tendency(self):
        self.assertEqual(kicktipp_points(Score(2, 1), Score(2, 1), "group"), 4)
        self.assertEqual(kicktipp_points(Score(2, 1), Score(3, 2), "group"), 3)
        self.assertEqual(kicktipp_points(Score(2, 1), Score(3, 1), "group"), 2)
        self.assertEqual(kicktipp_points(Score(1, 2), Score(3, 1), "group"), 0)
        # T-0097: falscher Remis-Score = nur Tendenz (2), NICHT Tordifferenz (3)
        self.assertEqual(kicktipp_points(Score(2, 2), Score(1, 1), "group"), 2)
        self.assertEqual(kicktipp_points(Score(0, 0), Score(2, 2), "group"), 2)
        self.assertEqual(kicktipp_points(Score(1, 0), Score(1, 1), "group"), 0)  # Nicht-Remis-Tipp auf Remis

    def test_knockout_points(self):
        # T-0097: falscher Remis-Score (1:1 auf 2:2) = Tendenz (3), nicht Tordifferenz (4)
        self.assertEqual(kicktipp_points(Score(1, 1), Score(2, 2), "knockout"), 3)
        self.assertEqual(kicktipp_points(Score(4, 2), Score(5, 3), "knockout"), 4)
        self.assertEqual(kicktipp_points(Score(4, 2), Score(3, 2), "knockout"), 3)

    def test_secondary_round_knockout_points(self):
        """Wertungsregeln der Zweitrunde -- RUNDENAGNOSTISCH.

        Die konkreten Punktwerte kommen aus der Rundenkonfiguration und
        unterscheiden sich zwischen den neutralen Defaults und einer lokalen
        `rounds_local.py`. Fest verdrahtete Zahlen liessen diesen Test genau
        dann brechen, wenn jemand die oeffentlichen Defaults anpasst -- ohne
        dass am Verhalten etwas falsch waere.
        """
        frueh = points_for_stage("round_of_32", SECONDARY_ROUND_ID)
        self.assertEqual(
            kicktipp_points(Score(1, 1), Score(1, 1), "round_of_32", SECONDARY_ROUND_ID),
            frueh["exact"],
        )
        self.assertEqual(
            # T-0097: falscher Remis-Score = Tendenz, nicht Tordifferenz
            kicktipp_points(Score(1, 1), Score(2, 2), "round_of_32", SECONDARY_ROUND_ID),
            frueh["tendency"],
        )
        self.assertEqual(
            kicktipp_points(Score(2, 1), Score(3, 1), "round_of_32", SECONDARY_ROUND_ID),
            frueh["tendency"],
        )
        # In den spaeten K.o.-Runden zaehlt die eskalierende Runde hoeher.
        # RUNDENAGNOSTISCH: die konkreten Punktwerte stehen in der
        # Rundenkonfiguration (neutrale Defaults ODER eine lokale
        # rounds_local.py) und duerfen sich unterscheiden. Geprueft wird die
        # REGEL -- exakt > Differenz > Tendenz, und spaet > Gruppenphase.
        spaet = points_for_stage("final", SECONDARY_ROUND_ID)
        gruppe = points_for_stage("group", SECONDARY_ROUND_ID)
        self.assertEqual(
            kicktipp_points(Score(1, 1), Score(1, 1), "final", SECONDARY_ROUND_ID),
            spaet["exact"],
        )
        self.assertEqual(
            kicktipp_points(Score(2, 1), Score(3, 2), "final", SECONDARY_ROUND_ID),
            spaet["difference"],
        )
        self.assertEqual(
            kicktipp_points(Score(2, 1), Score(3, 1), "final", SECONDARY_ROUND_ID),
            spaet["tendency"],
        )
        self.assertGreater(spaet["exact"], spaet["difference"])
        self.assertGreater(spaet["difference"], spaet["tendency"])
        self.assertGreater(spaet["exact"], gruppe["exact"])

    def test_best_tip_uses_expected_points(self):
        probabilities = {"1:0": 0.30, "2:1": 0.25, "1:1": 0.20, "0:1": 0.25}
        best = best_kicktipp_tip(probabilities, "group", max_goals=2)
        self.assertIn(best["tip"], {"1:0", "2:1"})
        self.assertEqual(best["round_name"], round_name(DEFAULT_ROUND_ID))

    def test_round_rules_payload_lists_both_rounds(self):
        payload = {row["id"]: row for row in round_rules_payload()}
        self.assertIn(DEFAULT_ROUND_ID, payload)
        self.assertIn(SECONDARY_ROUND_ID, payload)
        # Rundenagnostisch: WELCHE Stage hoeher wertet und mit welchen Zahlen,
        # ist Konfiguration. Geprueft wird, dass der Payload die Struktur
        # transportiert und dass die Eskalation ueberhaupt eskaliert.
        secondary = payload[SECONDARY_ROUND_ID]
        self.assertIsInstance(secondary["knockout"]["exact"], int)
        stage_points = secondary.get("stage_points") or {}
        self.assertTrue(stage_points, "eskalierende Runde ohne stage_points")
        self.assertTrue(
            any(
                sp["exact"] > secondary["knockout"]["exact"]
                for sp in stage_points.values()
            ),
            "keine Stage wertet hoeher als die Basis-KO-Wertung",
        )
        # Welche Bonusfragen eine Runde stellt, ist Konfiguration und
        # unterscheidet sich zwischen den neutralen Defaults und einer lokalen
        # rounds_local.py. Geprueft wird deshalb die Struktur, nicht der Inhalt.
        for round_id in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID):
            questions = payload[round_id]["bonus_questions"]
            self.assertIsInstance(questions, list)
            self.assertTrue(questions, f"{round_id}: keine Bonusfragen")
            for question in questions:
                self.assertIn(question, payload[round_id]["bonus_points"])

    def test_third_place_tippable_in_both_rounds(self):
        # T-0150 final (Betreiber-Bestaetigung, beide Tippabgabe-Screens): Platz 3 ist in
        # BEIDEN Runden tippbar.
        self.assertTrue(is_stage_tippable("third_place", DEFAULT_ROUND_ID))
        self.assertTrue(is_stage_tippable("third_place", SECONDARY_ROUND_ID))
        payload = {row["id"]: row for row in round_rules_payload()}
        self.assertEqual(payload[DEFAULT_ROUND_ID]["non_tippable_stages"], [])
        self.assertEqual(payload[SECONDARY_ROUND_ID]["non_tippable_stages"], [])

    def test_actual_for_round_penalty_convention(self):
        """Die Elfer-Runde wertet die volle Linie: Stand n.V. PLUS Elfmetertore.

        Realfall ko-088 (T-0155): 1:1 n.V., Elfer 2:4 -> Kicktipp wertet 3:5.
        Empirisch entschieden -- nur diese Konvention reproduziert die
        beobachteten Punktestaende einer Runde mit Elfmeter-Scope; an ko-088
        haengt ein grosser Teil der Abweichungen.
        """
        score_15 = actual_for_round([1, 1], "away", DEFAULT_ROUND_ID, [2, 4])
        self.assertEqual((score_15.home, score_15.away), (3, 5))
        # Die Zweitrunde wertet "nach Verlaengerung" -- Elfer aendern nichts.
        score_et = actual_for_round([1, 1], "away", SECONDARY_ROUND_ID, [2, 4])
        self.assertEqual((score_et.home, score_et.away), (1, 1))

    def test_actual_for_round_falls_back_when_shootout_missing(self):
        """Ohne erfasste Elferbilanz greift die dokumentierte +1-Naeherung.

        Sie ist NICHT die echte Kicktipp-Linie (siehe Docstring von
        actual_for_round) und existiert nur fuer Datensaetze, in denen die
        Bilanz nie erfasst wurde. Der Test pinnt sie, damit der Unterschied
        zur echten Konvention sichtbar bleibt statt still zu verschwimmen.
        """
        genaehert = actual_for_round([1, 1], "away", DEFAULT_ROUND_ID)
        self.assertEqual((genaehert.home, genaehert.away), (1, 2))
        echt = actual_for_round([1, 1], "away", DEFAULT_ROUND_ID, [2, 4])
        self.assertNotEqual((genaehert.home, genaehert.away), (echt.home, echt.away))

    def test_actual_for_round_no_penalty_is_identity(self):
        score = actual_for_round([2, 0], None, DEFAULT_ROUND_ID)
        self.assertEqual((score.home, score.away), (2, 0))


if __name__ == "__main__":
    unittest.main()
