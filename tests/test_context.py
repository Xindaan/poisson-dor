from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.context import (
    altitude_context_for_fixture,
    build_travel_index,
    context_for_fixture,
    heat_context_for_fixture,
)


class ContextTests(unittest.TestCase):
    def test_heat_context_flags_open_high_wbgt_venue(self):
        fixture = {
            "home_team": "Spain",
            "away_team": "Sweden",
            "local_time": "2026-06-20 15:00 UTC-4",
            "match_id": "heat-1",
            "venue": "Miami (Miami Gardens)",
        }
        context = context_for_fixture(fixture)
        heat = context["heat_stress"]
        self.assertEqual(heat["risk"], "high")
        self.assertIn("heat_high", context["flags"])
        self.assertFalse(heat["air_conditioned"])

    def test_climate_control_mitigates_player_field_wbgt(self):
        fixture = {
            "home_team": "Germany",
            "away_team": "Ecuador",
            "local_time": "2026-06-16 15:00 UTC-5",
            "match_id": "heat-2",
            "venue": "Dallas (Arlington)",
        }
        heat = heat_context_for_fixture(fixture)
        self.assertEqual(heat["risk"], "low")
        self.assertEqual(heat["ambient_risk"], "high")
        self.assertTrue(heat["air_conditioned"])

    def test_heat_adaptation_moves_xg_towards_better_adapted_team(self):
        fixture = {
            "home_team": "Spain",
            "away_team": "Sweden",
            "local_time": "2026-06-20 15:00 UTC-4",
            "match_id": "heat-3",
            "venue": "Miami (Miami Gardens)",
        }
        heat = heat_context_for_fixture(fixture)
        self.assertGreater(heat["home_adaptation_xg_delta"], 0)
        self.assertLess(heat["away_adaptation_xg_delta"], 0)

    def test_altitude_suppresses_xg_for_both_teams(self):
        fixture = {
            "home_team": "Germany",
            "away_team": "Curaçao",
            "venue": "Mexico City",
            "match_id": "alt-1",
        }
        alt = altitude_context_for_fixture(fixture)
        self.assertEqual(alt["risk"], "high")  # 2240 m
        self.assertLess(alt["pace_xg_delta"], 0)
        # Beide ziehen xG ab, keiner ist Heimnation hier.
        self.assertLess(alt["home_xg_delta"], 0)
        self.assertLess(alt["away_xg_delta"], 0)
        self.assertFalse(alt["home_acclimatized"])

    def test_altitude_acclimatization_helps_host_nation(self):
        fixture = {
            "home_team": "Mexico",
            "away_team": "Germany",
            "venue": "Mexico City",
            "match_id": "alt-2",
        }
        alt = altitude_context_for_fixture(fixture)
        self.assertTrue(alt["home_acclimatized"])
        # Mexico (akklimatisiert) verliert weniger xG als der Gast.
        self.assertGreater(alt["home_xg_delta"], alt["away_xg_delta"])

    def test_low_altitude_venue_has_no_effect(self):
        fixture = {
            "home_team": "USA",
            "away_team": "England",
            "venue": "Miami (Miami Gardens)",
            "match_id": "alt-3",
        }
        alt = altitude_context_for_fixture(fixture)
        self.assertEqual(alt["risk"], "low")
        self.assertEqual(alt["home_xg_delta"], 0.0)
        self.assertEqual(alt["away_xg_delta"], 0.0)

    def test_travel_index_no_effect_for_first_match(self):
        fixtures = [
            {"match_id": "m1", "home_team": "A", "away_team": "B",
             "venue": "Miami (Miami Gardens)", "kickoff_utc": "2026-06-11T19:00:00+00:00"},
        ]
        index = build_travel_index(fixtures)
        self.assertEqual(index["m1"]["home_xg_delta"], 0.0)
        self.assertIsNone(index["m1"]["home_km"])

    def test_travel_index_penalizes_long_trip_short_rest(self):
        fixtures = [
            # Team A: Spiel 1 in Seattle (Westkueste)
            {"match_id": "m1", "home_team": "A", "away_team": "X",
             "venue": "Seattle", "kickoff_utc": "2026-06-11T19:00:00+00:00"},
            # Team A: Spiel 2 in Miami (Ostkueste, ~4400 km) nach 2 Tagen
            {"match_id": "m2", "home_team": "A", "away_team": "Y",
             "venue": "Miami (Miami Gardens)", "kickoff_utc": "2026-06-13T19:00:00+00:00"},
        ]
        index = build_travel_index(fixtures)
        m2 = index["m2"]
        self.assertGreater(m2["home_km"], 3000)
        self.assertLess(m2["home_xg_delta"], 0)  # weite Reise + < 72 h Erholung
        # Gegner Y hat kein Vorspiel -> kein Effekt.
        self.assertEqual(m2["away_xg_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
