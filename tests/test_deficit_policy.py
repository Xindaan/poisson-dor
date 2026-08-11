from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.deficit_policy import (
    MIN_RIVAL_TIPS,
    _chase_tip,
    _field_consensus,
    _leader_name,
    _p_beat,
    _p_catch_up,
    _rel_of,
    _regime,
    _unrel,
    build_deficit_policy,
    non_tippable_match_ids,
    simulate_catch_up,
)
from wm_tipps.knockout import KNOCKOUT_STAGE_BY_MATCH
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID


class RegimeTests(unittest.TestCase):
    def test_protect_when_ahead_or_level(self):
        self.assertEqual(_regime(0, 30), "protect")
        self.assertEqual(_regime(-3, 30), "protect")

    def test_chase_when_far_behind_and_late(self):
        # SPAET (M<=CHASE_MAX_M_LEFT=12) UND grosser Rueckstand: D=13, M=8 ->
        # 1.5*sqrt(8)=4.2 -> chase
        self.assertEqual(_regime(13, 8), "chase")

    def test_no_chase_when_behind_but_many_games_left(self):
        # T-0080/Codex-Gate: D=13, M=20 -> trotz sqrt-Schwelle NEUTRAL, weil >12
        # bedeutende Restspiele (frueh ist der Rueckstand mit Normaltippen schliessbar).
        self.assertEqual(_regime(13, 20), "neutral")

    def test_neutral_when_behind_but_early(self):
        # D=8, M=48 -> viele Restspiele -> neutral (genug Spiele zum Aufholen)
        self.assertEqual(_regime(8, 48), "neutral")


class RelTests(unittest.TestCase):
    def test_rel_roundtrip_home_and_away_favorite(self):
        self.assertEqual(_rel_of((2, 1), "home"), (2, 1))
        self.assertEqual(_rel_of((1, 2), "away"), (2, 1))  # favoriten-relativ identisch
        self.assertEqual(_unrel((2, 1), "home"), "2:1")
        self.assertEqual(_unrel((2, 1), "away"), "1:2")

    def test_field_consensus_modal(self):
        modal = {"a": (2, 1), "b": (2, 1), "c": (1, 0)}
        self.assertEqual(_field_consensus(modal, "home"), "2:1")
        self.assertEqual(_field_consensus(modal, "away"), "1:2")


class ChaseTipTests(unittest.TestCase):
    def test_chase_targets_uncovered_outcome(self):
        # Feld tippt 2:0 (Heimsieg); bei realer Remis-Wahrscheinlichkeit schlaegt
        # ein Remis-Tipp das 2:0 auf allen Remis-Ausgaengen.
        dist = {"2:0": 0.4, "1:1": 0.35, "0:1": 0.25}
        chase = _chase_tip("2:0", dist, "group", DEFAULT_ROUND_ID)
        # Der Chase-Tipp darf nicht der Feld-Tipp selbst sein
        self.assertNotEqual(chase, "2:0")


class ChaseGateTests(unittest.TestCase):
    def test_p_beat_uses_probabilities(self):
        # Feld 2:0; Remis-Tipp schlaegt es nur auf Remis-Ausgaengen -> P-beat = P(Remis)
        dist = {"2:0": 0.5, "1:1": 0.3, "0:1": 0.2}
        self.assertAlmostEqual(_p_beat("1:1", "2:0", dist, "group", DEFAULT_ROUND_ID), 0.3)

    def test_strong_favorite_in_chase_keeps_ep(self):
        # Klarer Favorit: dekorrelierter Ausgang zu unwahrscheinlich -> Gate haelt EP-Max
        predictions = [
            {"match_id": "m1", "xg": {"home": 2.6, "away": 0.4},
             "fixture": {"stage": "group", "home_team": "Fav", "away_team": "Outsider"},
             "round_tips": {DEFAULT_ROUND_ID: {"tip": "2:0"}}},
        ]
        pool_tips = {"actuals": {}, "players": {DEFAULT_ROUND_ID: {"riv": {"m0": "2:0"}}}}
        standings = {"observations": [
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-06-18", "deficit_to_leader": 13,
             "me_rank": 9, "field_size": 12, "entries": [{"rank": 1, "name": "x", "points": 20}]}]}
        # SPAET-Szenario erzwingen (M<=12): K.o.-Phase weitgehend gespielt -> nur wenige
        # bedeutende Restspiele, sonst greift der Spaet-Gate und Regime waere neutral.
        fixtures = [{"match_id": "m1", "status": "scheduled", "stage": "group"}]
        fixtures += [{"match_id": f"ko{i}", "status": "played", "stage": "knockout"} for i in range(31)]
        out = build_deficit_policy(predictions=predictions, pool_tips=pool_tips, standings=standings,
                                   fixtures=fixtures, write=False)
        rd = out["rounds"][DEFAULT_ROUND_ID]
        self.assertEqual(rd["regime"], "chase")
        rec = rd["upcoming"][0]
        # Trotz Chase-Regime: Gate haelt EP-Max, weil der Chase-Tipp chancenlos ist
        self.assertLess(rec["chase_pbeat"], 0.30)
        self.assertFalse(rec["deviates_from_ep"])
        self.assertEqual(rec["policy_tip"], rec["ep_tip"])


class BuildTests(unittest.TestCase):
    def test_build_smoke_with_synthetic_inputs(self):
        predictions = [
            {"match_id": "m1", "xg": {"home": 1.8, "away": 0.7}, "fixture": {"stage": "group", "home_team": "A", "away_team": "B"},
             "round_tips": {DEFAULT_ROUND_ID: {"tip": "1:0"}}},
        ]
        pool_tips = {"actuals": {}, "players": {DEFAULT_ROUND_ID: {"riv": {"m0": "2:1"}}}}
        standings = {"observations": [
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-06-18T08:00", "deficit_to_leader": 13,
             "me_rank": 9, "field_size": 12, "entries": [{"rank": 1, "name": "x", "points": 20}]}]}
        fixtures = [{"match_id": "m1", "status": "scheduled", "stage": "group"}]
        out = build_deficit_policy(predictions=predictions, pool_tips=pool_tips, standings=standings,
                                   fixtures=fixtures, write=False)
        rd = out["rounds"][DEFAULT_ROUND_ID]
        # Default-Runde: 1 offenes Gruppenspiel + 32 tippbare K.o.-Spiele, INKL. Platz 3
        # (T-0150 final: beide Runden tippen Platz 3).
        self.assertEqual(rd["matches_left"], 33)
        # D=13, M=33 -> >12 bedeutende Restspiele -> Spaet-Gate haelt EP-Max (kein Chase)
        self.assertEqual(rd["regime"], "neutral")
        self.assertEqual(len(rd["upcoming"]), 1)
        rec = rd["upcoming"][0]
        self.assertEqual(rec["ep_tip"], "1:0")
        self.assertIn("policy_tip", rec)


class NonTippableTests(unittest.TestCase):
    """Spiel um Platz 3 ist nur in der Zweitrunde tippbar."""

    def test_third_place_tippable_in_both_rounds(self):
        # T-0150 final (Andre 14.7.): beide Runden tippen Platz 3 -> kein Skip.
        self.assertEqual(non_tippable_match_ids(DEFAULT_ROUND_ID), frozenset())
        self.assertEqual(non_tippable_match_ids(SECONDARY_ROUND_ID), frozenset())

    def test_third_place_counted_and_recommended_for_both_rounds(self):
        predictions = [
            {"match_id": mid, "xg": {"home": 1.6, "away": 1.0},
             "fixture": {"stage": "third_place" if mid == "ko-103" else "final",
                         "home_team": "A", "away_team": "B"},
             "round_tips": {DEFAULT_ROUND_ID: {"tip": "1:0"},
                            SECONDARY_ROUND_ID: {"tip": "2:1"}}}
            for mid in ("ko-103", "ko-104")
        ]
        fixtures = [{"match_id": f"ko-{n:03d}", "status": "played", "stage": "knockout"} for n in range(73, 103)]
        fixtures += [{"match_id": "ko-103", "status": "scheduled", "stage": "third_place"},
                     {"match_id": "ko-104", "status": "scheduled", "stage": "final"}]
        pool_tips = {"actuals": {}, "players": {
            DEFAULT_ROUND_ID: {"riv": {"m0": "2:1"}},
            SECONDARY_ROUND_ID: {"riv": {"m0": "2:1"}},
        }}
        standings = {"observations": [
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-07-10", "deficit_to_leader": 5,
             "me_rank": 2, "field_size": 12, "entries": [{"rank": 1, "name": "Tipper-A", "points": 30}]},
            {"round_id": SECONDARY_ROUND_ID, "observed_at": "2026-07-10", "deficit_to_leader": 5,
             "me_rank": 7, "field_size": 40, "entries": [{"rank": 1, "name": "Tipper-A", "points": 30}]},
        ]}
        out = build_deficit_policy(predictions=predictions, pool_tips=pool_tips, standings=standings,
                                   fixtures=fixtures, write=False)
        default = out["rounds"][DEFAULT_ROUND_ID]
        secondary = out["rounds"][SECONDARY_ROUND_ID]
        self.assertEqual(default["matches_left"], 2)
        self.assertEqual([r["match_id"] for r in default["upcoming"]], ["ko-103", "ko-104"])
        self.assertEqual(secondary["matches_left"], 2)
        self.assertEqual([r["match_id"] for r in secondary["upcoming"]], ["ko-103", "ko-104"])
        self.assertEqual(out["_meta"]["non_tippable_by_round"][DEFAULT_ROUND_ID], [])
        self.assertEqual(out["_meta"]["non_tippable_by_round"][SECONDARY_ROUND_ID], [])


class PerRivalChaseTests(unittest.TestCase):
    """T-0080: Chase gegen EINEN konkreten Rivalen (den Fuehrenden)."""

    def _inputs(self, leader_tips, deficit=8):
        # m1 = offenes Spiel. h0..h7 = gespielte Historie; sie MUESSEN Predictions haben,
        # sonst stehen sie nicht in match_fav und die Tipps des Leaders zaehlen nicht.
        def pred(mid, stage):
            return {"match_id": mid, "xg": {"home": 1.4, "away": 1.3},
                    "fixture": {"stage": stage, "home_team": "A", "away_team": "B"},
                    "round_tips": {DEFAULT_ROUND_ID: {"tip": "1:0"}}}

        predictions = [pred("m1", "quarter")] + [pred(f"h{i}", "group") for i in range(MIN_RIVAL_TIPS)]
        actuals = {f"h{i}": [1, 0] for i in range(MIN_RIVAL_TIPS)}
        pool_tips = {"actuals": actuals, "players": {DEFAULT_ROUND_ID: {"Tipper-A": leader_tips}}}
        standings = {"observations": [
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-07-10", "deficit_to_leader": deficit,
             "me_rank": 3, "field_size": 12, "entries": [{"rank": 1, "name": "Tipper-A", "points": 195}]}]}
        # Spaet erzwingen: 30 K.o. gespielt -> M klein -> Chase-Regime moeglich
        fixtures = [{"match_id": "m1", "status": "scheduled", "stage": "quarter"}]
        fixtures += [{"match_id": f"h{i}", "status": "played", "stage": "group"} for i in range(MIN_RIVAL_TIPS)]
        fixtures += [{"match_id": f"ko-{n:03d}", "status": "played", "stage": "knockout"} for n in range(73, 103)]
        return predictions, pool_tips, standings, fixtures

    def test_leader_name_from_latest_observation(self):
        standings = {"observations": [
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-07-01", "entries": [{"rank": 1, "name": "Alt"}]},
            {"round_id": DEFAULT_ROUND_ID, "observed_at": "2026-07-10", "entries": [{"rank": 2, "name": "X"},
                                                                                    {"rank": 1, "name": "Tipper-A"}]},
        ]}
        self.assertEqual(_leader_name(standings, DEFAULT_ROUND_ID), "Tipper-A")

    def test_thin_leader_profile_disables_rival_overlay(self):
        thin = {"m1": "2:1"}  # nur 1 verwertbarer Tipp < MIN_RIVAL_TIPS
        preds, pool_tips, standings, fixtures = self._inputs(thin)
        out = build_deficit_policy(predictions=preds, pool_tips=pool_tips, standings=standings,
                                   fixtures=fixtures, write=False)
        rd = out["rounds"][DEFAULT_ROUND_ID]
        self.assertFalse(rd["target_rival"]["reliable"])
        self.assertNotIn("rival_tip", rd["upcoming"][0])  # kein Overlay ohne belastbares Profil
        self.assertEqual(rd["rival_deviations"], 0)

    def test_rival_overlay_targets_leader_and_never_lowers_pbeat(self):
        # Leader tippt konsistent favoriten-relativ 2:1 auf 8 Historien-Spielen -> belastbar
        rich = {f"h{i}": "2:1" for i in range(MIN_RIVAL_TIPS)}
        preds, pool_tips, standings, fixtures = self._inputs(rich)
        out = build_deficit_policy(predictions=preds, pool_tips=pool_tips, standings=standings,
                                   fixtures=fixtures, write=False)
        rd = out["rounds"][DEFAULT_ROUND_ID]
        self.assertEqual(rd["target_rival"]["name"], "Tipper-A")
        self.assertTrue(rd["target_rival"]["reliable"])
        rec = rd["upcoming"][0]
        # Der Gegen-Tipp ist per Konstruktion mindestens so gut wie EP-Max gegen den Rivalen
        self.assertGreaterEqual(rec["rival_chase_pbeat"], rec["ep_pbeat_vs_rival"])
        # policy_tip (feld-basiert) bleibt unberuehrt -> rein additiv
        self.assertIn("policy_tip", rec)
        # Abweichung nur, wenn sie den Rivalen echt haeufiger schlaegt UND das Gate nimmt
        # Die Kosten sind kontrafaktisch (was Abweichen KOSTEN WUERDE) und werden auch
        # ohne Abweichung ausgewiesen. Sie duerfen negativ sein: `ep_tip` ist der
        # Pipeline-Tipp (Blend/Kalibrierung), nicht zwingend der Argmax der lokalen
        # _resolved_dist -- live bei ko-100 gemessen (-0.034).
        self.assertIsInstance(rec["rival_chase_ep_cost"], float)
        self.assertEqual(rec["no_gain_with_ep"], rec["ep_pbeat_vs_rival"] == 0.0)
        if rec["rival_deviates_from_ep"]:
            self.assertGreaterEqual(rec["rival_chase_pbeat"], 0.30)
            self.assertGreater(rec["rival_chase_pbeat"], rec["ep_pbeat_vs_rival"])
        else:
            self.assertEqual(rec["rival_policy_tip"], rec["ep_tip"])


class CatchUpTests(unittest.TestCase):
    """T-0080: P(Rueckstand einholen) -- nicht per-Spiel-P(schlagen)."""

    def test_convolution_sums_two_matches(self):
        # Zwei Spiele, je +2 mit p=0.5 / -1 mit p=0.5 -> P(gesamt >= 4) = 0.25
        d = {2: 0.5, -1: 0.5}
        self.assertAlmostEqual(_p_catch_up([d, d], 4), 0.25)

    def test_unreachable_deficit_is_zero(self):
        # Max +4 pro Spiel; 2 Spiele -> 9 Punkte sind unerreichbar
        d = {4: 1.0}
        self.assertEqual(_p_catch_up([d, d], 9), 0.0)

    def test_no_remaining_matches_returns_none(self):
        self.assertIsNone(_p_catch_up([], 5))


class MonteCarloCatchUpTests(unittest.TestCase):
    """T-0142: Bracket-Simulation + gezogener Rivalen-Tipp."""

    STRENGTHS = {t: {"rating": 1800} for t in ("A", "B")}

    def _single_final(self, rival_rel_dist, deficit, iterations=1200, seed=1):
        # Alle K.o.-Spiele ausser dem Finale (104) haben schon Sieger -> genau 1 Restspiel.
        winners = {n: "A" for n in KNOCKOUT_STAGE_BY_MATCH if n != 104}
        preds = {"ko-104": {"match_id": "ko-104", "xg": {"home": 1.5, "away": 1.1},
                            "fixture": {"stage": "final", "home_team": "A", "away_team": "B"}}}
        return simulate_catch_up(
            predictions_by_id=preds, winners=winners, strengths=self.STRENGTHS,
            rival_rel_dist=rival_rel_dist, deficit=deficit, round_id=DEFAULT_ROUND_ID,
            skip_ids=non_tippable_match_ids(DEFAULT_ROUND_ID), iterations=iterations, seed=seed,
        )

    def test_deterministic_given_seed(self):
        a = self._single_final({(2, 1): 1.0}, 1)
        b = self._single_final({(2, 1): 1.0}, 1)
        self.assertEqual(a["p_ep_max"], b["p_ep_max"])
        self.assertEqual(a["simulated_matches"], 1)

    def test_unreachable_deficit_is_zero(self):
        # Max 6 Punkte im KO der Default-Runde -> 99 sind unerreichbar
        out = self._single_final({(2, 1): 1.0}, 99)
        self.assertEqual(out["p_ep_max"], 0.0)
        self.assertEqual(out["p_rival_chase"], 0.0)

    def test_matches_analytic_when_rival_is_deterministic(self):
        # Kreuzvalidierung: EIN Spiel, Rivale mit Punktmasse -> MC muss die analytische
        # Faltung treffen (das ist genau der Fall, den _p_catch_up exakt rechnet).
        from wm_tipps.deficit_policy import _diff_dist, _resolved_dist, _fav_side, _ep_tip, _unrel

        dist = _resolved_dist(1.5, 1.1, "final", DEFAULT_ROUND_ID)
        fav = _fav_side(dist)
        ep = _ep_tip(dist, "final", DEFAULT_ROUND_ID)
        rel = (2, 1)
        rival_tip = _unrel(rel, fav)
        exact = _p_catch_up([_diff_dist(ep, rival_tip, dist, "final", DEFAULT_ROUND_ID)], 1)

        mc = self._single_final({rel: 1.0}, 1, iterations=12000, seed=7)
        self.assertAlmostEqual(mc["p_ep_max"], exact, delta=3 * mc["p_ep_max_ci95"] + 0.01)

    def test_spread_rival_beats_deterministic_for_ep_max(self):
        # Kernbefund T-0142: ein Rivale, der auch danebenliegt, laesst EP-Max Boden
        # gutmachen. Deterministisch (Punktmasse) ist die Chance systematisch kleiner.
        det = self._single_final({(2, 1): 1.0}, 1, iterations=6000, seed=3)
        spread = self._single_final({(2, 1): 0.5, (1, 0): 0.3, (3, 0): 0.2}, 1, iterations=6000, seed=3)
        self.assertGreater(spread["p_ep_max"], det["p_ep_max"])

    def test_paired_delta_is_consistent_with_marginals(self):
        mc = self._single_final({(2, 1): 0.6, (1, 0): 0.4}, 1, iterations=3000, seed=11)
        self.assertAlmostEqual(mc["chase_minus_ep"], mc["p_rival_chase"] - mc["p_ep_max"], places=3)
        # Die beiden Flags schliessen sich aus (und sind bei Gleichstand beide False)
        self.assertFalse(mc["chase_better"] and mc["ep_better"])

    def test_no_rival_distribution_returns_none(self):
        self.assertIsNone(self._single_final({}, 1))

    def test_secondary_round_simulates_third_place_from_semifinal_losers(self):
        predictions = {
            "ko-101": {
                "match_id": "ko-101",
                "xg": {"home": 1.5, "away": 1.1},
                "fixture": {"stage": "semi", "home_team": "A", "away_team": "B"},
            },
            "ko-102": {
                "match_id": "ko-102",
                "xg": {"home": 1.4, "away": 1.2},
                "fixture": {"stage": "semi", "home_team": "C", "away_team": "D"},
            },
        }
        strengths = {team: {"rating": 1800} for team in ("A", "B", "C", "D")}
        winners = {number: "A" for number in range(73, 101)}
        out = simulate_catch_up(
            predictions_by_id=predictions,
            winners=winners,
            strengths=strengths,
            rival_rel_dist={(2, 1): 1.0},
            deficit=1,
            round_id=SECONDARY_ROUND_ID,
            skip_ids=non_tippable_match_ids(SECONDARY_ROUND_ID),
            iterations=100,
            seed=7,
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["simulated_matches"], 4)


if __name__ == "__main__":
    unittest.main()
