from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.fixtures import parse_openfootball_cup
from wm_tipps.model import (
    blend_market_probabilities,
    build_bonus_predictions,
    calibrate_score_matrix,
    calibrate_score_matrix_from_xg,
    calibrate_score_matrix_to_market_constraints,
    expected_goals,
    market_constraint_probability,
    market_constraints_from_outcomes,
    outcome_probabilities,
    predict_fixture,
    score_matrix,
    total_goal_scale_for_market_constraints,
    total_goal_scale_for_target_draw,
    stability_for,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID, round_name
from wm_tipps.watcher import cadence_seconds


class ModelTests(unittest.TestCase):
    def test_score_matrix_sums_to_one(self):
        matrix = score_matrix(1.4, 1.1)
        self.assertAlmostEqual(sum(matrix.values()), 1.0)

    def test_market_calibration_changes_outcome(self):
        matrix = score_matrix(1.2, 1.2)
        target = blend_market_probabilities(outcome_probabilities(matrix), {"home": 0.60, "draw": 0.20, "away": 0.20}, weight=0.5)
        calibrated = calibrate_score_matrix(matrix, target)
        outcomes = outcome_probabilities(calibrated)
        self.assertGreater(outcomes["home"], outcome_probabilities(matrix)["home"])

    def test_draw_target_total_goal_scale_moves_toward_market_draw(self):
        base = score_matrix(1.28, 1.28)
        base_draw = outcome_probabilities(base)["draw"]
        scale = total_goal_scale_for_target_draw(1.28, 1.28, base_draw - 0.05)
        self.assertGreater(scale, 1.0)
        calibrated, meta = calibrate_score_matrix_from_xg(
            1.28,
            1.28,
            {"home": 0.45, "draw": 0.20, "away": 0.35},
            total_mode="draw_target",
        )
        self.assertAlmostEqual(sum(calibrated.values()), 1.0)
        self.assertEqual(meta["total_mode"], "draw_target")
        self.assertGreater(meta["total_scale"], 1.0)

    def test_market_score_calibrator_fits_outcomes_and_extra_constraints(self):
        matrix = score_matrix(1.2, 1.1)
        constraints = [
            *market_constraints_from_outcomes({"home": 0.45, "draw": 0.25, "away": 0.30}),
            {
                "id": "over_2_5",
                "kind": "total_goals",
                "side": "over",
                "line": 2.5,
                "target": 0.58,
            },
            {"id": "btts_yes", "kind": "btts", "side": "yes", "target": 0.52},
        ]
        calibrated, fit = calibrate_score_matrix_to_market_constraints(matrix, constraints)
        self.assertAlmostEqual(sum(calibrated.values()), 1.0)
        self.assertLess(fit["max_error"], 0.02)
        self.assertAlmostEqual(
            market_constraint_probability(calibrated, constraints[3]),
            0.58,
            delta=0.02,
        )
        self.assertAlmostEqual(
            market_constraint_probability(calibrated, constraints[4]),
            0.52,
            delta=0.02,
        )

    def test_market_constraint_total_scale_uses_goal_shape_targets(self):
        base = score_matrix(1.1, 1.1)
        over_constraint = {
            "id": "over_2_5",
            "kind": "total_goals",
            "side": "over",
            "line": 2.5,
            "target": market_constraint_probability(
                base,
                {"kind": "total_goals", "side": "over", "line": 2.5},
            ) + 0.12,
        }
        scale = total_goal_scale_for_market_constraints(1.1, 1.1, [over_constraint])
        self.assertGreater(scale, 1.0)

    def test_openfootball_parser_extracts_fixture(self):
        text = """
Group A | Mexico      South Africa
▪ Group A
Thu June 11
  13:00 UTC-6     Mexico       v South Africa        @ Mexico City
"""
        parsed = parse_openfootball_cup(text)
        self.assertEqual(parsed["fixtures"][0]["home_team"], "Mexico")
        self.assertEqual(parsed["fixtures"][0]["away_team"], "South Africa")

    def test_future_missing_lineup_is_not_urgent(self):
        fixture = {"kickoff_utc": "2099-06-11T19:00:00+00:00"}
        details = {"home_news": {"lineup_confirmed": False}, "away_news": {"lineup_confirmed": False}}
        self.assertEqual(stability_for(fixture, [], details), "stabil")

    def test_critical_news_on_home_lifts_away_xg_and_drops_home_xg(self):
        fixture = {
            "home_team": "Mexico",
            "away_team": "South Africa",
            "match_id": "ga-001",
            "venue": "Mexico City",
        }
        strengths = {"Mexico": {"elo": 1700}, "South Africa": {"elo": 1500}}
        clean_home, clean_away, _ = expected_goals(fixture, strengths, [], {})
        bad_news = [
            {
                "teams": ["Mexico"],
                "severity": "critical",
                "freshness": "fresh",
                "categories": ["injury"],
            }
        ]
        bad_home, bad_away, _ = expected_goals(fixture, strengths, bad_news, {})
        self.assertLess(bad_home, clean_home)
        self.assertGreater(bad_away, clean_away)

    def test_prep_disruption_reduces_affected_team_xg(self):
        fixture = {
            "home_team": "Iran", "away_team": "USA",
            "match_id": "prep-001", "venue": "Mexico City",
        }
        strengths = {"Iran": {"elo": 1600}, "USA": {"elo": 1600}}
        neutral = {"fixtures": {"prep-001": {
            "home_advantage_xg": 0.0,
            "prep_disruption": {"home_xg_delta": 0.0, "away_xg_delta": 0.0},
        }}}
        disrupted = {"fixtures": {"prep-001": {
            "home_advantage_xg": 0.0,
            "prep_disruption": {
                "home_xg_delta": -0.08, "away_xg_delta": 0.0,
                "home": {"team": "Iran", "xg_delta": -0.08, "basis": "manual"},
                "away": None,
            },
        }}}
        base_home, _, base_det = expected_goals(fixture, strengths, [], neutral)
        dis_home, _, det = expected_goals(fixture, strengths, [], disrupted)
        self.assertLess(dis_home, base_home)
        self.assertEqual(det["breakdown"]["home"]["prep_disruption_effect"], -0.08)
        self.assertEqual(base_det["breakdown"]["home"]["prep_disruption_effect"], 0.0)

    def test_heat_context_improves_relative_chance_for_adapted_team(self):
        fixture = {
            "home_team": "Spain",
            "away_team": "Sweden",
            "match_id": "heat-001",
            "venue": "Miami (Miami Gardens)",
            "local_time": "2026-06-20 15:00 UTC-4",
        }
        strengths = {"Spain": {"elo": 1800}, "Sweden": {"elo": 1800}}
        neutral_context = {
            "fixtures": {
                "heat-001": {
                    "home_advantage_xg": 0.0,
                    "heat_stress": {"home_xg_delta": 0.0, "away_xg_delta": 0.0},
                }
            }
        }
        base_home, base_away, _ = expected_goals(fixture, strengths, [], neutral_context)
        hot_home, hot_away, details = expected_goals(fixture, strengths, [], {})
        self.assertGreater(hot_home - hot_away, base_home - base_away)
        self.assertLess(hot_away, base_away)
        self.assertEqual(details["breakdown"]["heat_stress"]["risk"], "high")

    def test_player_intel_xg_delta_changes_expected_goals(self):
        fixture = {
            "home_team": "Alpha",
            "away_team": "Beta",
            "match_id": "player-001",
            "venue": "Toronto",
        }
        base_strengths = {"Alpha": {"elo": 1600}, "Beta": {"elo": 1600}}
        intel_strengths = {
            "Alpha": {"elo": 1600, "player_xg_delta": 0.05},
            "Beta": {"elo": 1600, "player_xg_delta": -0.02},
        }
        context = {
            "fixtures": {
                "player-001": {
                    "home_advantage_xg": 0.0,
                    "heat_stress": {"home_xg_delta": 0.0, "away_xg_delta": 0.0},
                }
            }
        }
        base_home, base_away, _ = expected_goals(fixture, base_strengths, [], context)
        intel_home, intel_away, details = expected_goals(fixture, intel_strengths, [], context)
        self.assertGreater(intel_home, base_home)
        self.assertLess(intel_away, base_away)
        self.assertEqual(details["breakdown"]["home"]["player_intel_effect"], 0.05)

    def test_predict_fixture_contains_round_specific_tips(self):
        fixture = {
            "home_team": "Alpha",
            "away_team": "Beta",
            "match_id": "round-001",
            "stage": "round_of_32",
            "venue": "Toronto",
        }
        strengths = {"Alpha": {"elo": 1700}, "Beta": {"elo": 1500}}
        context = {
            "fixtures": {
                "round-001": {
                    "home_advantage_xg": 0.0,
                    "heat_stress": {"home_xg_delta": 0.0, "away_xg_delta": 0.0},
                }
            }
        }
        result = predict_fixture(fixture, strengths, [], {}, context)
        self.assertIn(DEFAULT_ROUND_ID, result["round_tips"])
        self.assertIn(SECONDARY_ROUND_ID, result["round_tips"])
        self.assertEqual(result["score_calibration"]["market_blend_weight"], 0.20)
        self.assertEqual(result["score_calibration"]["calibrator"], "market_score_v1")
        self.assertEqual(result["recommended_tip"], result["round_tips"][DEFAULT_ROUND_ID])
        self.assertEqual(result["round_tips"][SECONDARY_ROUND_ID]["round_name"],
                         round_name(SECONDARY_ROUND_ID))

    def test_third_place_prediction_only_contains_tippable_round(self):
        fixture = {
            "home_team": "Alpha",
            "away_team": "Beta",
            "match_id": "ko-103",
            "stage": "third_place",
            "venue": "Miami",
        }
        strengths = {"Alpha": {"elo": 1700}, "Beta": {"elo": 1500}}
        context = {
            "fixtures": {
                "ko-103": {
                    "home_advantage_xg": 0.0,
                    "heat_stress": {"home_xg_delta": 0.0, "away_xg_delta": 0.0},
                }
            }
        }
        result = predict_fixture(fixture, strengths, [], {}, context)
        # T-0150 final (Betreiber-Bestaetigung): beide Runden tippen Platz 3.
        self.assertIn(DEFAULT_ROUND_ID, result["round_tips"])
        self.assertIn(SECONDARY_ROUND_ID, result["round_tips"])
        self.assertEqual(result["recommended_tip"], result["round_tips"][DEFAULT_ROUND_ID])

    def test_build_bonus_predictions_uses_ko_sim_and_topscorer(self):
        teams = [f"T{i}" for i in range(8)]
        strengths = {team: {"elo": 1500 + i * 25, "attack": 1.0 + i * 0.05} for i, team in enumerate(teams)}
        player_pool = {team: [{"goal_share": 0.4}] for team in teams}
        result = build_bonus_predictions(
            teams, strengths, markets=[], n_simulations=500, player_pool=player_pool
        )
        self.assertIn("world_champion", result)
        self.assertIn("semifinalists", result)
        self.assertIn("top_scorer_team", result)
        self.assertGreater(len(result["world_champion"]), 0)
        champion_first = result["world_champion"][0]
        self.assertIn("team", champion_first)
        self.assertIn("probability", champion_first)
        # Stronger teams should rank higher on average -- strongest is T7
        self.assertEqual(champion_first["team"], "T7")
        # Probabilities sind aus Monte-Carlo, summieren sich auf qualified_pool
        self.assertAlmostEqual(
            sum(row["probability"] for row in result["world_champion"]), 1.0, places=4
        )

    def test_bonus_market_probabilities_are_category_specific(self):
        teams = ["A", "B", "C", "D"]
        strengths = {team: {"elo": 1500 + i * 25, "attack": 1.0} for i, team in enumerate(teams)}
        markets = [
            {
                "category": "world_champion",
                "outcome": "D",
                "probability": 0.12,
                "quality": {"status": "usable", "reasons": []},
            },
            {
                "category": "semifinalist",
                "outcome": "D",
                "probability": 0.48,
                "quality": {"status": "usable", "reasons": []},
            },
        ]
        result = build_bonus_predictions(teams, strengths, markets=markets, n_simulations=300)
        champion_d = next(row for row in result["world_champion"] if row["team"] == "D")
        semi_d = next(row for row in result["semifinalists"] if row["team"] == "D")
        self.assertEqual(champion_d["market_probability"], 0.12)
        self.assertEqual(semi_d["market_probability"], 0.48)

    def test_watcher_cadence(self):
        self.assertEqual(cadence_seconds(100), 86400)
        self.assertEqual(cadence_seconds(36), 21600)
        self.assertEqual(cadence_seconds(12), 7200)
        self.assertEqual(cadence_seconds(1), 900)


if __name__ == "__main__":
    unittest.main()
