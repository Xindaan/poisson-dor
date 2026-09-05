from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.topscorer import DEFAULT_TOP_SHARE, team_topscorer_probabilities


class TopscorerTests(unittest.TestCase):
    def test_probabilities_sum_to_one(self):
        teams = ["A", "B", "C"]
        pool = {
            "A": [{"goal_share": 0.5}],
            "B": [{"goal_share": 0.4}],
            "C": [{"goal_share": 0.3}],
        }
        xg = {"A": 1.5, "B": 1.2, "C": 1.0}
        result = team_topscorer_probabilities(teams, pool, xg)
        self.assertAlmostEqual(sum(result.values()), 1.0, places=6)
        self.assertEqual(set(result.keys()), set(teams))

    def test_higher_team_xg_yields_higher_probability(self):
        teams = ["High", "Low"]
        pool = {"High": [{"goal_share": 0.4}], "Low": [{"goal_share": 0.4}]}
        xg = {"High": 2.0, "Low": 1.0}
        result = team_topscorer_probabilities(teams, pool, xg)
        self.assertGreater(result["High"], result["Low"])
        self.assertAlmostEqual(result["High"] / result["Low"], 2.0, delta=0.01)

    def test_team_without_players_uses_default(self):
        teams = ["A", "B"]
        pool = {"A": [{"goal_share": 0.6}]}  # B fehlt
        xg = {"A": 1.0, "B": 1.0}
        result = team_topscorer_probabilities(teams, pool, xg)
        # Score A = 1.0 * 0.6 = 0.6; Score B = 1.0 * 0.4 = 0.4; Total = 1.0
        self.assertAlmostEqual(result["A"], 0.6, delta=0.01)
        self.assertAlmostEqual(result["B"], 0.4, delta=0.01)

    def test_top_player_share_picks_max(self):
        teams = ["A", "B"]
        pool = {
            "A": [{"goal_share": 0.3}, {"goal_share": 0.5}, {"goal_share": 0.2}],
            "B": [{"goal_share": 0.4}],
        }
        xg = {"A": 1.0, "B": 1.0}
        result = team_topscorer_probabilities(teams, pool, xg)
        # A nutzt max=0.5, B nutzt 0.4 -> A > B
        self.assertGreater(result["A"], result["B"])

    def test_empty_teams_returns_empty_dict(self):
        self.assertEqual(team_topscorer_probabilities([], {}, {}), {})

    def test_invalid_goal_share_is_skipped(self):
        teams = ["A"]
        pool = {"A": [{"goal_share": "abc"}, {"goal_share": 0.4}]}
        result = team_topscorer_probabilities(teams, pool, {"A": 1.0})
        # Nur ein Team, normalized = 1.0; Kein Crash trotz "abc"
        self.assertAlmostEqual(result["A"], 1.0, places=6)

    def test_default_top_share_value(self):
        self.assertEqual(DEFAULT_TOP_SHARE, 0.4)


if __name__ == "__main__":
    unittest.main()
