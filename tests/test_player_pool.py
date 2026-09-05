from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.player_pool import (
    HEURISTIC_ROLE_SOURCE,
    assign_heuristic_roles,
    build_player_pool,
    parse_goalscorers,
)


SAMPLE_CSV = """date,home_team,away_team,team,scorer,minute,own_goal,penalty
2023-09-01,Argentina,Mexico,Argentina,Old Goal,33,FALSE,FALSE
2024-03-01,Argentina,Mexico,Argentina,Lionel Messi,12,FALSE,FALSE
2024-03-01,Argentina,Mexico,Argentina,Julian Alvarez,55,FALSE,FALSE
2024-06-15,Argentina,Brazil,Argentina,Lautaro Martinez,67,FALSE,FALSE
2024-06-15,Argentina,Brazil,Argentina,Lautaro Martinez,88,FALSE,FALSE
2024-06-15,Argentina,Brazil,Argentina,Lautaro Martinez,90,FALSE,FALSE
2024-09-09,Argentina,USA,Argentina,Own Goal Guy,3,TRUE,FALSE
2024-10-10,United States,Canada,United States,Christian Pulisic,18,FALSE,FALSE
2025-03-15,USA,Mexico,USA,Christian Pulisic,42,FALSE,FALSE
"""


class PlayerPoolTests(unittest.TestCase):
    def test_parse_filters_pre_2024_and_own_goals(self):
        counts = parse_goalscorers(SAMPLE_CSV, {"Argentina"})
        self.assertNotIn("Old Goal", counts["Argentina"])
        self.assertNotIn("Own Goal Guy", counts["Argentina"])
        self.assertEqual(counts["Argentina"]["Lautaro Martinez"], 3)
        self.assertEqual(counts["Argentina"]["Lionel Messi"], 1)

    def test_parse_resolves_alias_united_states_to_usa(self):
        counts = parse_goalscorers(SAMPLE_CSV, {"USA"})
        self.assertEqual(counts["USA"]["Christian Pulisic"], 2)

    def test_repo_pool_has_position_coverage(self):
        import json
        from wm_tipps.paths import DATA_DIR

        pool = json.loads((DATA_DIR / "player_pool.json").read_text(encoding="utf-8"))["players"]
        with_pos = sum(1 for rows in pool.values() for p in rows if p.get("position"))
        total = sum(len(rows) for rows in pool.values())
        # Wikipedia-Squad-Positionen sind eingepflegt (T-0040-Daten).
        self.assertGreaterEqual(with_pos, int(0.8 * total))
        # Position muss ein valides Kuerzel sein.
        valid = {"GK", "DF", "MF", "FW"}
        for rows in pool.values():
            for p in rows:
                if p.get("position"):
                    self.assertIn(p["position"], valid, p["name"])
        # Bekannter Defensiv-Pool-Spieler routet korrekt.
        kimmich = next((p for p in pool.get("Germany", []) if "Kimmich" in p["name"]), None)
        self.assertIsNotNone(kimmich)
        self.assertEqual(kimmich["position"], "DF")

    def test_build_pool_normalises_to_top3_total(self):
        result = build_player_pool(
            csv_text=SAMPLE_CSV,
            fixture_payload={"fixtures": [], "groups": {"A": ["Argentina"]}},
            write=False,
        )
        argentina = result["players"]["Argentina"]
        self.assertEqual(argentina[0]["name"], "Lautaro Martinez")
        self.assertAlmostEqual(sum(p["goal_share"] for p in argentina), 1.0, places=4)
        # Top-3 = 3 + 1 + 1 = 5; Lautaro 3/5 = 0.6
        self.assertAlmostEqual(argentina[0]["goal_share"], 0.6, places=4)

    def test_build_pool_meta_contains_source(self):
        result = build_player_pool(
            csv_text=SAMPLE_CSV,
            fixture_payload={"fixtures": [], "groups": {"A": ["Argentina"]}},
            write=False,
        )
        self.assertIn("source", result["_meta"])
        self.assertIn("CC0", result["_meta"]["license"])

    def test_heuristic_role_assignment(self):
        # T-0040-role: starter als Default, rotation nur bei eindeutig
        # geringster Involvierung. Niedrig-scorende Stammspieler (Paqueta-
        # Profil, share 0.18) duerfen NICHT rotation werden.
        roster = [
            {"name": "Top Scorer", "goal_share": 0.55, "goals_since_2024": 9},
            {"name": "Star Defender", "goal_share": 0.0, "goals_since_2024": 0,
             "key_player": True},
            {"name": "Paqueta Profil", "goal_share": 0.18, "goals_since_2024": 2},
            {"name": "Fringe Forward", "goal_share": 0.05, "goals_since_2024": 1},
        ]
        assign_heuristic_roles({"X": roster})
        by_name = {p["name"]: p for p in roster}
        self.assertEqual(by_name["Top Scorer"]["role"], "starter")       # rank 0
        self.assertEqual(by_name["Star Defender"]["role"], "starter")    # key_player
        self.assertEqual(by_name["Paqueta Profil"]["role"], "starter")   # share >= 0.15
        self.assertEqual(by_name["Fringe Forward"]["role"], "rotation")  # share<0.15, <=2 Tore
        for player in roster:
            self.assertEqual(player["role_source"], HEURISTIC_ROLE_SOURCE)

    def test_manual_role_wins_and_heuristic_recomputes(self):
        # Manuelle Rolle (auch Legacy ohne role_source) gewinnt; eine
        # heuristische Rolle wird neu berechnet (nicht eingefroren).
        roster = [
            {"name": "Boss", "goal_share": 0.7, "goals_since_2024": 9},
            {"name": "Legacy Manual", "goal_share": 0.6, "goals_since_2024": 8,
             "role": "rotation"},  # kein role_source -> manuell
            {"name": "Frozen Heuristic", "goal_share": 0.05, "goals_since_2024": 1,
             "role": "starter", "role_source": HEURISTIC_ROLE_SOURCE},
        ]
        assign_heuristic_roles({"X": roster})
        by_name = {p["name"]: p for p in roster}
        # Manuelle rotation auf einem Top-Scorer bleibt erhalten.
        self.assertEqual(by_name["Legacy Manual"]["role"], "rotation")
        self.assertNotEqual(by_name["Legacy Manual"].get("role_source"), HEURISTIC_ROLE_SOURCE)
        # Eingefrorene Heuristik-Rolle wird neu berechnet -> rotation.
        self.assertEqual(by_name["Frozen Heuristic"]["role"], "rotation")

    def test_repo_pool_role_coverage(self):
        import json
        from wm_tipps.paths import DATA_DIR

        pool = json.loads((DATA_DIR / "player_pool.json").read_text(encoding="utf-8"))["players"]
        valid = {"starter", "rotation", "backup"}
        total = 0
        with_role = 0
        for rows in pool.values():
            for player in rows:
                total += 1
                role = player.get("role")
                if role:
                    with_role += 1
                    self.assertIn(role, valid, player["name"])
                    # key_player ist nie rotation/backup.
                    if player.get("key_player"):
                        self.assertEqual(role, "starter", player["name"])
        self.assertEqual(with_role, total)  # jeder Pool-Spieler hat eine Rolle

    def test_rebuild_preserves_manual_position_role(self):
        from unittest import mock
        from wm_tipps import player_pool as pp

        existing = {
            "players": {
                "Argentina": [
                    {"name": "Lautaro Martinez", "goal_share": 0.5,
                     "position": "ST", "role": "starter"},
                ]
            }
        }
        with mock.patch.object(pp, "load_position_role_overrides", return_value=existing["players"]):
            result = build_player_pool(
                csv_text=SAMPLE_CSV,
                fixture_payload={"fixtures": [], "groups": {"A": ["Argentina"]}},
                write=False,
            )
        lautaro = next(p for p in result["players"]["Argentina"] if "Lautaro" in p["name"])
        self.assertEqual(lautaro["position"], "ST")
        self.assertEqual(lautaro["role"], "starter")
        # Spieler ohne Override behalten keine erfundenen Felder.
        messi = next(p for p in result["players"]["Argentina"] if "Messi" in p["name"])
        self.assertNotIn("position", messi)

    def test_rebuild_preserves_key_player_additions(self):
        from unittest import mock
        from wm_tipps import player_pool as pp

        # Ein Guardian-Star ohne Tore (nicht in der CSV) soll den Rebuild ueberleben.
        additions = {"Argentina": [
            {"name": "Cuti Romero", "goal_share": 0.0, "position": "DF", "key_player": True},
        ]}
        with mock.patch.object(pp, "load_key_player_additions", return_value=additions), \
             mock.patch.object(pp, "load_position_role_overrides", return_value={}):
            result = build_player_pool(
                csv_text=SAMPLE_CSV,
                fixture_payload={"fixtures": [], "groups": {"A": ["Argentina"]}},
                write=False,
            )
        names = [p["name"] for p in result["players"]["Argentina"]]
        self.assertIn("Cuti Romero", names)
        romero = next(p for p in result["players"]["Argentina"] if p["name"] == "Cuti Romero")
        self.assertEqual(romero["position"], "DF")
        self.assertTrue(romero["key_player"])
        # Top-3-Torschuetzen weiterhin da.
        self.assertEqual(sum(1 for p in result["players"]["Argentina"] if p["goal_share"] > 0), 3)


if __name__ == "__main__":
    unittest.main()
