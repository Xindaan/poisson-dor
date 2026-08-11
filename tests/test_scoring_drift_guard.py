"""T-0125 Scoring-Drift-Guard.

Die Kicktipp-Wertung ist DREIFACH implementiert: Kern (`wm_tipps.scoring`),
das explorative `analysis/rival_lab.py` und `analysis/rival-profiles/tidy.py`.
Bewusst KEIN Refactoring/Zusammenlegen mitten im Turnier (T-0125) -- stattdessen
dieser Guard: alle drei muessen auf identischem (stage, round_id, tip, actual)
DIESELBEN Punkte liefern. Rot, sobald eine Regelaenderung nur in einem Zweig
landet (die 4-6-8-Eskalation ab Achtelfinale musste schon dreifach nachgezogen
werden -- genau der Fehlerfall, der vor dem ersten Achtelfinale auffliegen muss).

Die beiden analysis-Zweige sind der Nicht-stdlib-Carve-out (numpy/pandas). Fehlt
das, skippt der Guard sauber (bare-stdlib), statt die stdlib-only-Suite zu brechen.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wm_tipps.scoring import (  # noqa: E402
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    Score,
    kicktipp_points as core_score,
    points_for_stage as core_table,
)

ROUND_IDS = (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID)
# Alle real vorkommenden Stages: Gruppe (2-3-4), R32 (eskalierende Runde wie
# Vorrunde), ab Achtelfinale (4-6-8); die flache Runde bleibt 3-4-6 im K.o.
STAGES = (
    "group", "round_of_32", "round_of_16",
    "quarter", "semi", "final", "third_place",
)
# (tip_h, tip_a, act_h, act_a) -- exakt / Tordifferenz / Tendenz / Miss plus die
# Remis-Sonderregel (falscher Remis = nur Tendenz, T-0097).
SCENARIOS = (
    (2, 1, 2, 1),   # exakt
    (3, 2, 2, 1),   # gleiche Tordifferenz (Nicht-Remis)
    (3, 0, 2, 1),   # gleiche Tendenz, andere Differenz
    (0, 2, 2, 1),   # Tendenz falsch -> 0
    (1, 1, 1, 1),   # Remis exakt
    (2, 2, 1, 1),   # falscher Remis-Score -> nur Tendenz
    (1, 1, 2, 1),   # Remis-Tipp auf Nicht-Remis -> 0
    (2, 1, 1, 1),   # Nicht-Remis-Tipp auf Remis -> 0
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _RIVAL_LAB = _load(ROOT / "analysis" / "rival_lab.py", "drift_rival_lab")
    _TIDY = _load(ROOT / "analysis" / "rival-profiles" / "tidy.py", "drift_tidy")
    _SKIP = ""
except Exception as exc:  # noqa: BLE001 -- Carve-out fehlt (numpy/pandas) o.ae.
    _RIVAL_LAB = _TIDY = None
    _SKIP = f"analysis-Zweige nicht ladbar ({type(exc).__name__}: {exc})"


@unittest.skipUnless(_RIVAL_LAB is not None, _SKIP or "analysis-Zweige fehlen")
class ScoringDriftGuardTests(unittest.TestCase):
    def test_points_tables_agree(self):
        for round_id in ROUND_IDS:
            for stage in STAGES:
                core = dict(core_table(stage, round_id))
                rl = dict(_RIVAL_LAB.points_table(stage, round_id))
                td = dict(_TIDY.points_table(stage, round_id))
                where = f"{round_id}/{stage}"
                self.assertEqual(core, rl, f"points_table Drift Kern<>rival_lab @ {where}")
                self.assertEqual(core, td, f"points_table Drift Kern<>tidy @ {where}")

    def test_scoring_agrees(self):
        for round_id in ROUND_IDS:
            for stage in STAGES:
                for th, ta, ah, aa in SCENARIOS:
                    core = core_score(Score(th, ta), Score(ah, aa), stage, round_id)
                    rl = _RIVAL_LAB.kicktipp_points((th, ta), (ah, aa), stage, round_id)
                    td = _TIDY.score_points(th, ta, ah, aa, stage, round_id)
                    where = f"{round_id}/{stage} tip {th}:{ta} act {ah}:{aa}"
                    self.assertEqual(core, rl, f"Scoring Drift Kern<>rival_lab @ {where}")
                    self.assertEqual(core, td, f"Scoring Drift Kern<>tidy @ {where}")


if __name__ == "__main__":
    unittest.main()
