from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.lineups import (
    _key_absences,
    _norm,
    _players_from_pool,
    starters_from_summary,
)


class NormTests(unittest.TestCase):
    def test_accent_and_alias_folding(self):
        self.assertEqual(_norm("Germany"), "germany")
        self.assertEqual(_norm("Curaçao"), "curacao")
        self.assertEqual(_norm("Türkiye"), "turkey")          # Alias
        self.assertEqual(_norm("Côte d'Ivoire"), "ivorycoast")  # Alias
        self.assertEqual(_norm("Korea Republic"), "southkorea")  # Alias
        self.assertEqual(_norm("Czechia"), "czechrepublic")     # Alias


class StartersTests(unittest.TestCase):
    def test_extracts_only_starters(self):
        summary = {
            "rosters": [
                {
                    "team": {"displayName": "Germany"},
                    "roster": [
                        {"starter": True, "athlete": {"displayName": "Manuel Neuer"}},
                        {"starter": True, "athlete": {"displayName": "Jamal Musiala"}},
                        {"starter": False, "athlete": {"displayName": "Bench Player"}},
                    ],
                }
            ]
        }
        out = starters_from_summary(summary)
        self.assertEqual(out, {"germany": ["Manuel Neuer", "Jamal Musiala"]})


class KeyAbsenceTests(unittest.TestCase):
    def test_flags_key_player_not_in_xi(self):
        pool = {
            "Germany": [
                {"name": "Jamal Musiala", "goal_share": 0.30},
                {"name": "Florian Wirtz", "goal_share": 0.25},
                {"name": "Reservist", "goal_share": 0.05},
            ]
        }
        xi = ["Manuel Neuer", "Jamal Musiala", "Kai Havertz"]
        absent = _key_absences("Germany", xi, pool)
        self.assertIn("Florian Wirtz", absent)        # Schluesselspieler fehlt
        self.assertNotIn("Jamal Musiala", absent)     # spielt
        self.assertNotIn("Reservist", absent)         # unter Schwelle

    def test_flags_key_player_flag_below_goal_share_threshold(self):
        # Pulisic-Fall: kreativer Star mit goal_share 0 (Topscorer-Bonus
        # neutral), aber key_player:true -- Ausfall muss trotzdem flaggen.
        pool = {
            "USA": [
                {"name": "Malik Tillman", "goal_share": 0.375},
                {"name": "Christian Pulisic", "goal_share": 0.0,
                 "key_player": True},
                {"name": "Reservist", "goal_share": 0.05},
            ]
        }
        xi = ["Matt Freese", "Malik Tillman", "Ricardo Pepi"]
        absent = _key_absences("USA", xi, pool)
        self.assertIn("Christian Pulisic", absent)    # key_player fehlt -> Alarm
        self.assertNotIn("Malik Tillman", absent)     # spielt
        self.assertNotIn("Reservist", absent)         # weder Schwelle noch Flag

    def test_players_extracted_from_nested_pool_payload(self):
        # Regression (T-0111): refresh_lineups lud das volle player_pool.json
        # {"_meta", "players"} und gab es direkt an _key_absences -> player_pool.get
        # (team) war None -> key_absences IMMER leer (Doku-Ausfall ueber sehen).
        payload = {
            "_meta": {"description": "..."},
            "players": {
                "Belgium": [
                    {"name": "Kevin De Bruyne", "goal_share": 0.47, "key_player": True},
                    {"name": "Jérémy Doku", "goal_share": 0.26},
                ]
            },
        }
        xi = ["Kevin De Bruyne", "Romelu Lukaku", "Leandro Trossard"]
        # Volles Payload direkt -> Bug-Zustand: nichts gefunden.
        self.assertEqual(_key_absences("Belgium", xi, payload), [])
        # Ueber die Extraktion (wie refresh_lineups jetzt) -> Ausfall erkannt.
        extracted = _players_from_pool(payload)
        self.assertIn("Jérémy Doku", _key_absences("Belgium", xi, extracted))


if __name__ == "__main__":
    unittest.main()
