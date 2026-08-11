from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.lineup_roles import (
    MANUAL_ROLE_SOURCE,
    NEWS_CONFIRMED_ROLE_SOURCE,
    NEWS_EXPECTED_ROLE_SOURCE,
    apply_lineup_roles,
    extract_xi_names,
    lineup_xis_from_news,
    resolve_lineups,
)

SPAIN_XI = [
    "Simon", "Carvajal", "Le Normand", "Laporte", "Cucurella",
    "Rodri", "Pedri", "Fabian", "Yamal", "Morata", "Nico Williams",
]


def _spain_pool():
    return {
        "Spain": [
            {"name": "Lamine Yamal", "goal_share": 0.3, "role": "starter", "role_source": "heuristic_v1"},
            {"name": "Alvaro Morata", "goal_share": 0.4, "role": "starter", "role_source": "heuristic_v1"},
            {"name": "Ansu Fati", "goal_share": 0.1, "role": "starter", "role_source": "heuristic_v1"},
        ]
    }


class ExtractXiTests(unittest.TestCase):
    def test_extracts_clean_starting_xi(self):
        names = extract_xi_names(
            "England XI: Pickford, Walker, Stones, Guehi, Shaw, Rice, "
            "Bellingham, Foden, Saka, Kane, Gordon"
        )
        self.assertIsNotNone(names)
        self.assertIn("Pickford", names)
        self.assertIn("Kane", names)
        self.assertGreaterEqual(len(names), 11)

    def test_preview_article_yields_no_xi(self):
        self.assertIsNone(
            extract_xi_names("Shankland, Gunn and a midfield conundrum - Clarke's big decision")
        )

    def test_too_few_names_yields_none(self):
        self.assertIsNone(extract_xi_names("Lineup: Kane, Foden, Saka"))


class ApplyLineupRolesTests(unittest.TestCase):
    def test_manual_lineup_sets_starter_and_rotation(self):
        players = _spain_pool()
        summary = apply_lineup_roles(players, news_items=[], manual_lineups={"Spain": SPAIN_XI})
        by_name = {p["name"]: p for p in players["Spain"]}
        # Yamal/Morata in der XI (Nachname-Match) -> starter.
        self.assertEqual(by_name["Lamine Yamal"]["role"], "starter")
        self.assertEqual(by_name["Alvaro Morata"]["role"], "starter")
        # Ansu Fati NICHT in der XI -> rotation (Bench-Inferenz).
        self.assertEqual(by_name["Ansu Fati"]["role"], "rotation")
        for player in players["Spain"]:
            self.assertEqual(player["role_source"], MANUAL_ROLE_SOURCE)
        self.assertEqual(summary["teams_with_lineup"], 1)
        self.assertEqual(summary["starters"], 2)
        self.assertEqual(summary["rotation"], 1)

    def test_true_manual_role_is_protected(self):
        players = _spain_pool()
        players["Spain"][2]["role"] = "backup"
        players["Spain"][2]["role_source"] = "manual"
        apply_lineup_roles(players, news_items=[], manual_lineups={"Spain": SPAIN_XI})
        # Echte manuelle Rolle bleibt, auch wenn Spieler nicht in der XI ist.
        self.assertEqual(players["Spain"][2]["role"], "backup")
        self.assertEqual(players["Spain"][2]["role_source"], "manual")

    def test_no_lineup_leaves_roles_untouched(self):
        players = _spain_pool()
        summary = apply_lineup_roles(players, news_items=[], manual_lineups={})
        self.assertEqual(summary["teams_with_lineup"], 0)
        for player in players["Spain"]:
            self.assertEqual(player["role_source"], "heuristic_v1")


class LineupNewsTests(unittest.TestCase):
    def test_confirmed_lineup_news_extracted(self):
        news = [
            {
                "categories": ["confirmed_lineup"],
                "teams": ["England"],
                "title": "England Starting XI: Pickford, Walker, Stones, Guehi, "
                "Shaw, Rice, Bellingham, Foden, Saka, Kane, Gordon",
                "summary": "",
            }
        ]
        got = lineup_xis_from_news(news)
        self.assertIn("England", got)
        self.assertEqual(got["England"][1], NEWS_CONFIRMED_ROLE_SOURCE)

    def test_confirmed_beats_expected(self):
        xi = "Pickford, Walker, Stones, Guehi, Shaw, Rice, Bellingham, Foden, Saka, Kane, Gordon"
        news = [
            {"categories": ["expected_lineup"], "teams": ["England"], "title": f"Expected XI: {xi}", "summary": ""},
            {"categories": ["confirmed_lineup"], "teams": ["England"], "title": f"Confirmed XI: {xi}", "summary": ""},
        ]
        got = lineup_xis_from_news(news)
        self.assertEqual(got["England"][1], NEWS_CONFIRMED_ROLE_SOURCE)

    def test_resolve_lineups_manual_wins_over_news(self):
        xi = "Pickford, Walker, Stones, Guehi, Shaw, Rice, Bellingham, Foden, Saka, Kane, Gordon"
        news = [{"categories": ["confirmed_lineup"], "teams": ["Spain"], "title": f"Confirmed XI: {xi}", "summary": ""}]
        resolved = resolve_lineups(news_items=news, manual_lineups={"Spain": SPAIN_XI})
        self.assertEqual(resolved["Spain"][1], MANUAL_ROLE_SOURCE)


if __name__ == "__main__":
    unittest.main()
