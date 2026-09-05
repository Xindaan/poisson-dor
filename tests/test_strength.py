from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.strength import (
    build_team_strengths,
    derive_strength,
    fifa_rank_rating,
    player_intelligence_for_team,
)


class StrengthTests(unittest.TestCase):
    def test_fifa_rank_rating_is_monotonic(self):
        self.assertGreater(fifa_rank_rating(1), fifa_rank_rating(25))
        self.assertGreater(fifa_rank_rating(25), fifa_rank_rating(80))

    def test_derive_strength_keeps_model_contract(self):
        row = {
            "world_elo": 2000,
            "world_elo_rank": 5,
            "fifa_rank": 3,
            "form_adjustment": 4,
            "attack_adjustment": 0.1,
            "qualifier_status": "qualified",
        }
        strength = derive_strength("Testland", row)
        self.assertIn("elo", strength)
        self.assertIn("attack", strength)
        self.assertGreater(strength["elo"], 2000)
        self.assertGreater(strength["attack"], 1.0)

    def test_build_team_strengths_flags_missing_inputs(self):
        fixtures = {"groups": {"A": ["Alpha", "Beta"]}, "fixtures": []}
        inputs = {"teams": {"Alpha": {"world_elo": 1700, "fifa_rank": 40}}}
        payload = build_team_strengths(fixtures, inputs, write=False)
        self.assertIn("Alpha", payload)
        self.assertIn("Beta", payload["_meta"]["missing_inputs"])

    def test_player_intelligence_generates_capped_xg_delta(self):
        pool = {
            "Alpha": [
                {"name": "A", "goal_share": 0.45, "goals_since_2024": 10},
                {"name": "B", "goal_share": 0.35, "goals_since_2024": 8},
                {"name": "C", "goal_share": 0.20, "goals_since_2024": 6},
            ]
        }
        intel = player_intelligence_for_team("Alpha", pool)
        self.assertEqual(intel["players_tracked"], 3)
        self.assertEqual(intel["top3_goals_since_2024"], 24)
        self.assertGreater(intel["xg_delta"], 0)

    def test_player_intelligence_is_neutral_without_coverage(self):
        intel = player_intelligence_for_team("Uncovered", {})
        self.assertEqual(intel["players_tracked"], 0)
        self.assertEqual(intel["xg_delta"], 0.0)
        self.assertIsNone(intel["top_scorer_share"])

    def test_build_team_strengths_embeds_player_intel(self):
        fixtures = {"groups": {"A": ["Alpha"]}, "fixtures": []}
        inputs = {"teams": {"Alpha": {"world_elo": 1700, "fifa_rank": 40}}}
        pool = {"players": {"Alpha": [{"name": "A", "goal_share": 0.5, "goals_since_2024": 12}]}}
        payload = build_team_strengths(fixtures, inputs, write=False, player_pool_payload=pool)
        self.assertIn("player_intel", payload["Alpha"])
        self.assertIn("player_xg_delta", payload["Alpha"])


if __name__ == "__main__":
    unittest.main()
