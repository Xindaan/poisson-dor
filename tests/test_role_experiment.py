from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.role_experiment import (
    ROLE_OFF_SOURCE,
    _force_role_off,
    normalize_manual_results,
    settle_role_ab,
    update_role_ab_log,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID


class ForceRoleOffTests(unittest.TestCase):
    def test_all_roles_become_starter(self):
        pool = {"X": [
            {"name": "A", "role": "rotation", "role_source": "heuristic_v1"},
            {"name": "B"},
        ]}
        off = _force_role_off(pool)
        for player in off["X"]:
            self.assertEqual(player["role"], "starter")
            self.assertEqual(player["role_source"], ROLE_OFF_SOURCE)
        # Original unveraendert (deepcopy).
        self.assertEqual(pool["X"][0]["role"], "rotation")


class SettleTests(unittest.TestCase):
    def _entry(self, **kw):
        base = {
            "match_id": "m1", "match": "A - B", "round_id": DEFAULT_ROUND_ID,
            "stage": "group", "kickoff_utc": "2026-06-11T19:00:00+00:00",
            "treatment_tip": "2:0", "treatment": [2, 0],
            "control_tip": "1:0", "control": [1, 0], "differs": True,
        }
        base.update(kw)
        return base

    def test_settles_and_computes_delta(self):
        # actual 2:0: treatment 2:0 = exakt (4), control 1:0 = Tendenz (2) -> +2.
        report = settle_role_ab([self._entry()], {"m1": {"actual": [2, 0], "penalty_winner": None}})
        meta = report["_meta"]
        self.assertEqual(meta["settled_slots"], 1)
        self.assertEqual(meta["differing_tips"], 1)
        self.assertEqual(meta["treatment_points"], 4)
        self.assertEqual(meta["control_points"], 2)
        self.assertEqual(meta["net_delta"], 2)
        self.assertEqual(report["movers"][0]["delta"], 2)

    def test_unsettled_without_result(self):
        report = settle_role_ab([self._entry()], {})
        self.assertEqual(report["_meta"]["settled_slots"], 0)
        self.assertEqual(report["_meta"]["net_delta"], 0)

    def test_knockout_penalty_convention_per_round(self):
        # KO 1:1, Elfer-Sieger away. Die Elfer-Runde wertet 1:2 (nach Elfer).
        entry = self._entry(
            round_id=DEFAULT_ROUND_ID, stage="knockout",
            treatment_tip="1:2", treatment=[1, 2],
            control_tip="1:1", control=[1, 1],
        )
        report = settle_role_ab([entry], {"m1": {"actual": [1, 1], "penalty_winner": "away"}})
        # treatment 1:2 trifft die Elfer-Wertung (away +1) besser als control 1:1.
        self.assertGreater(report["_meta"]["treatment_points"], report["_meta"]["control_points"])


class LogFreezeTests(unittest.TestCase):
    def test_past_kickoff_entries_are_frozen(self):
        now = datetime(2026, 6, 12, tzinfo=timezone.utc)
        existing = [{
            "match_id": "m1", "round_id": DEFAULT_ROUND_ID,
            "kickoff_utc": "2026-06-11T19:00:00+00:00", "treatment_tip": "1:0",
        }]
        # Neuer Snapshot fuer dasselbe (vergangene) Spiel darf NICHT ueberschreiben.
        new = [{
            "match_id": "m1", "round_id": DEFAULT_ROUND_ID,
            "kickoff_utc": "2026-06-11T19:00:00+00:00", "treatment_tip": "9:9",
        }]
        merged = update_role_ab_log(new, existing=existing, now=now)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["treatment_tip"], "1:0")  # eingefroren

    def test_future_entries_get_updated(self):
        now = datetime(2026, 6, 10, tzinfo=timezone.utc)
        existing = [{
            "match_id": "m2", "round_id": DEFAULT_ROUND_ID,
            "kickoff_utc": "2026-06-11T19:00:00+00:00", "treatment_tip": "1:0",
        }]
        new = [{
            "match_id": "m2", "round_id": DEFAULT_ROUND_ID,
            "kickoff_utc": "2026-06-11T19:00:00+00:00", "treatment_tip": "2:1",
        }]
        merged = update_role_ab_log(new, existing=existing, now=now)
        self.assertEqual(merged[0]["treatment_tip"], "2:1")  # aktualisiert


class NormalizeManualResultsTests(unittest.TestCase):
    """T-0185: unbrauchbare Eintraege werden UEBERSPRUNGEN, nicht geworfen.

    Die Funktion war inkonsistent: eine blanke Liste falscher Laenge (`[2]`)
    wurde still uebersprungen, das aequivalente `{"actual": [2]}` warf dagegen
    `IndexError`, weil nur auf truthy statt auf Laenge geprueft wurde.
    Aufgefallen 23.08.26, als `win_sim_v2` in T-0182 auf diese Funktion
    umgestellt wurde -- der dortige Loop hatte den Fall vorher selbst per
    `len(act) != 2 -> continue` abgefangen, der Umbau haette die Fragilitaet
    also erst eingeschleppt.
    """

    def test_beide_gueltigen_formate(self):
        payload = {"results": {
            "kurz": [1, 0],
            "voll": {"actual": [1, 1], "penalty_winner": "away", "shootout": [2, 4]},
        }}
        out = normalize_manual_results(payload)
        self.assertEqual(out["kurz"], {"actual": [1, 0], "penalty_winner": None, "shootout": None})
        self.assertEqual(out["voll"]["actual"], [1, 1])
        self.assertEqual(out["voll"]["penalty_winner"], "away")
        self.assertEqual(out["voll"]["shootout"], [2, 4])

    def test_unbrauchbare_eintraege_werfen_nicht(self):
        payload = {"results": {
            "zu_kurz_liste": [2],
            "zu_kurz_dict": {"actual": [2]},
            "leer": {"actual": []},
            "kein_actual": {"penalty_winner": "home"},
            "none": None,
            "string": {"actual": "1:0"},
        }}
        out = normalize_manual_results(payload)  # darf nicht werfen
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
