"""T-0113: xG-Malus fuer bestaetigte XI-Ausfaelle von Pool-Schluesselspielern.

Deckt ab: default-AUS (forward-gated), Frische-Gate (XI<->Spiel-Linkage),
Positions-Routing, key_player-Floor, News-Doppelzaehl-Schutz, gespielte Spiele
und die Integration in model.expected_goals (eigene Breakdown-Zeile).
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.lineup_absence import (
    LINEUP_ABSENCE_XG_ENABLED,
    build_lineup_absence_index,
    player_absence_effect,
)
from wm_tipps.lineups import _key_absences, absent_key_players
from wm_tipps.model import expected_goals


def _fixture(match_id="m1", status="scheduled"):
    return {
        "match_id": match_id,
        "home_team": "Alpha",
        "away_team": "Beta",
        "status": status,
    }


def _payload(meta_match_id="m1", xi=None):
    # XI OHNE die Pool-Schluesselspieler -> sie gelten als ausgefallen.
    return {
        "lineups": {"Alpha": xi or ["Keeper Alpha", "Mid Alpha", "Back Alpha"]},
        "lineups_meta": {"Alpha": {"match_id": meta_match_id}},
    }


class FlagWiringTests(unittest.TestCase):
    def test_flag_is_bool(self):
        # Der Hebel ist per Betreiber-Entscheid (T-0113, 2026-06-22) aktiv (True).
        # Test pinnt den Wert NICHT (er kann jederzeit auf False gesetzt werden),
        # prueft nur, dass es ein sauberer Schalter ist.
        self.assertIsInstance(LINEUP_ABSENCE_XG_ENABLED, bool)

    def test_disabled_returns_empty_even_with_absence(self):
        pool = {"Alpha": [{"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"}]}
        idx = build_lineup_absence_index([_fixture()], pool, _payload(), enabled=False)
        self.assertEqual(idx, {})

    def test_default_follows_module_flag(self):
        # Aufruf ohne enable-Argument muss exakt dem Modul-Flag folgen.
        pool = {"Alpha": [{"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"}]}
        idx = build_lineup_absence_index([_fixture()], pool, _payload())
        if LINEUP_ABSENCE_XG_ENABLED:
            self.assertIn("m1", idx)
        else:
            self.assertEqual(idx, {})


class FreshnessGateTests(unittest.TestCase):
    def setUp(self):
        self.pool = {"Alpha": [{"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"}]}

    def test_match_id_mismatch_no_effect(self):
        # XI wurde fuer ein ANDERES Spiel erfasst -> darf dieses nicht bestrafen.
        idx = build_lineup_absence_index(
            [_fixture("m1")], self.pool, _payload(meta_match_id="other"), enabled=True
        )
        self.assertEqual(idx, {})

    def test_match_id_match_fires(self):
        idx = build_lineup_absence_index(
            [_fixture("m1")], self.pool, _payload(meta_match_id="m1"), enabled=True
        )
        self.assertIn("m1", idx)

    def test_missing_meta_no_effect(self):
        payload = {"lineups": {"Alpha": ["Keeper Alpha"]}}  # kein lineups_meta
        idx = build_lineup_absence_index([_fixture()], self.pool, payload, enabled=True)
        self.assertEqual(idx, {})

    def test_played_fixture_skipped(self):
        idx = build_lineup_absence_index(
            [_fixture(status="played")], self.pool, _payload(), enabled=True
        )
        self.assertEqual(idx, {})


class RoutingTests(unittest.TestCase):
    def test_attacking_absence_reduces_own_attack(self):
        pool = {"Alpha": [{"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"}]}
        idx = build_lineup_absence_index([_fixture()], pool, _payload(), enabled=True)
        row = idx["m1"]
        self.assertLess(row["home_xg_delta"], 0.0)   # eigene Offensive runter
        self.assertEqual(row["away_xg_delta"], 0.0)  # kein Gegner-Boost
        self.assertEqual(row["absent"]["Alpha"][0]["routed"], "attack")

    def test_defensive_absence_boosts_opponent(self):
        pool = {"Alpha": [{"name": "Back Star", "goal_share": 0.0, "key_player": True, "position": "DF"}]}
        idx = build_lineup_absence_index([_fixture()], pool, _payload(), enabled=True)
        row = idx["m1"]
        self.assertGreater(row["away_xg_delta"], 0.0)  # Gegner trifft mehr
        self.assertEqual(row["home_xg_delta"], 0.0)
        self.assertEqual(row["absent"]["Alpha"][0]["routed"], "defense")

    def test_higher_goal_share_means_bigger_malus(self):
        small = player_absence_effect({"name": "S", "goal_share": 0.2, "position": "FW"}, [])[0]
        big = player_absence_effect({"name": "B", "goal_share": 0.6, "position": "FW"}, [])[0]
        self.assertLess(big, small)  # negativer = staerker


class KeyPlayerFloorTests(unittest.TestCase):
    def test_key_player_zero_goal_share_still_penalized(self):
        # van-Dijk-Fall: key_player True, goal_share 0 (Topscorer-Bonus neutral).
        # Per reinem goal_share waere der Malus 0 -- der PLAYER_SCALE_MIN-Floor
        # gibt ihm einen kleinen, nicht-null Malus.
        pool = {"Alpha": [{"name": "Creative Star", "goal_share": 0.0, "key_player": True, "position": "FW"}]}
        idx = build_lineup_absence_index([_fixture()], pool, _payload(), enabled=True)
        self.assertIn("m1", idx)
        self.assertLess(idx["m1"]["home_xg_delta"], 0.0)


class NewsDedupeTests(unittest.TestCase):
    def test_player_with_xg_news_not_double_counted(self):
        pool = {"Alpha": [{"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"}]}
        # xG-wirksame News ueber genau diesen Spieler -> Ausfall-Malus muss
        # uebersprungen werden (er haengt schon per News im xG).
        news = [{
            "id": "n1",
            "teams": ["Alpha"],
            "players": ["Striker Alpha"],
            "categories": ["injury"],
            "severity": "critical",
            "freshness": "fresh",
            "model_relevant": True,
            "title": "Striker Alpha ruled out for Alpha",
            "summary": "Striker Alpha is ruled out with a hamstring injury.",
        }]
        idx = build_lineup_absence_index([_fixture()], pool, _payload(), news, enabled=True)
        self.assertEqual(idx, {})  # kein zusaetzlicher Malus


class ExpectedGoalsIntegrationTests(unittest.TestCase):
    def test_lineup_absence_lowers_xg_and_shows_breakdown(self):
        fixture = _fixture()
        strengths = {}  # symmetrisch (DEFAULT_RATING)
        # Beide Contexts muessen truthy sein (ein leeres {} ist falsy -> expected_goals
        # faellt auf context_for_fixture mit echten Heat/Travel-Effekten zurueck).
        # Sie unterscheiden sich daher NUR im lineup_absence-Delta.
        base_ctx = {"fixtures": {"m1": {"lineup_absence": {
            "home_xg_delta": 0.0, "away_xg_delta": 0.0,
        }}}}
        absent_ctx = {"fixtures": {"m1": {"lineup_absence": {
            "home_xg_delta": -0.2, "away_xg_delta": 0.0,
        }}}}
        home0, away0, d0 = expected_goals(fixture, strengths, [], base_ctx)
        home1, away1, d1 = expected_goals(fixture, strengths, [], absent_ctx)
        self.assertLess(home1, home0)            # Heim-xG sinkt
        self.assertAlmostEqual(away1, away0)     # Auswaerts unveraendert
        self.assertEqual(d1["breakdown"]["home"]["lineup_absence_effect"], -0.2)
        self.assertEqual(d0["breakdown"]["home"]["lineup_absence_effect"], 0.0)


class DetectorRefactorTests(unittest.TestCase):
    def test_absent_key_players_returns_dicts_keyabsences_names(self):
        pool = {"Alpha": [
            {"name": "Striker Alpha", "goal_share": 0.4, "position": "FW"},
            {"name": "Sub Alpha", "goal_share": 0.05},
        ]}
        xi = ["Keeper Alpha", "Mid Alpha"]
        dicts = absent_key_players("Alpha", xi, pool)
        names = _key_absences("Alpha", xi, pool)
        self.assertEqual([p["name"] for p in dicts], ["Striker Alpha"])  # Dicts
        self.assertEqual(names, ["Striker Alpha"])                       # Namen
        self.assertTrue(all(isinstance(p, dict) for p in dicts))


if __name__ == "__main__":
    unittest.main()
