"""T-0184 Klassenschutz: kein stiller `stage`-Default auf "group".

Fehlt zu einem Spiel die Stage, ist sie UNBEKANNT -- nicht "Gruppe". Wer den
Default setzt, wertet ein K.o.-Spiel unbemerkt mit Gruppen-Punkten (2-3-4 statt
3-4-6 bzw. 4-6-8) und verschleiert dabei einen Datendefekt.

Gefunden 23.08.26 im Isomorphie-Check zu T-0179, wo dieselbe Klasse in
`rival_profiles._stage_of` und `rival_lab.player_profile` behoben wurde. Hier
die verbleibenden Stellen, die eine Prediction pro Match NACHSCHLAGEN:
`risk_dial._live_counterfactual`, `tip_strategy_ab._live_samples`,
`deficit_policy` (Verteilungsaufbau).

ABGRENZUNG -- bewusst NICHT erfasst: Stellen, die ueber `fixtures` iterieren
(`deficit_policy:119`, `fixtures.py`, `model.py`), denn dort ist `stage` ein
Pflichtfeld der Fixture-Zeile; und die Backtest-Zeilen (`backtest.py`), deren
`stage` aus einer anderen Quelle mit eigener Semantik stammt.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps import deficit_policy, risk_dial, tip_strategy_ab  # noqa: E402

QUELLEN = (
    (risk_dial, "risk_dial._live_counterfactual"),
    (tip_strategy_ab, "tip_strategy_ab._live_samples"),
    (deficit_policy, "deficit_policy (Verteilungsaufbau)"),
)


class StageDefaultGuardTests(unittest.TestCase):
    def test_kein_stiller_group_default_bei_prediction_lookups(self):
        """Textbasiert, aber gezielt: die drei Module duerfen `stage` nicht mehr
        aus einer Prediction mit `"group"`-Default ziehen.

        Bewusst eine Quelltext-Pruefung -- die betroffenen Funktionen brauchen
        Pool-Daten/Standings als Eingabe, ein Verhaltenstest waere hier ein
        Nachbau der halben Pipeline. Der WIRKSAMKEITS-Nachweis liegt bei den
        Verhaltenstests von T-0179 (`test_rival_profiles`,
        `test_rival_lab_stage_fallback`), die dieselbe Klasse an den Stellen
        pruefen, wo sie guenstig testbar ist.
        """
        import inspect

        for modul, name in QUELLEN:
            quelltext = inspect.getsource(modul)
            with self.subTest(quelle=name):
                self.assertNotIn(
                    '(pred.get("fixture") or {}).get("stage", "group")', quelltext,
                    f"{name}: stiller Gruppen-Default wieder eingebaut.",
                )
                self.assertNotIn(
                    '(p.get("fixture") or {}).get("stage", "group")', quelltext,
                    f"{name}: stiller Gruppen-Default wieder eingebaut.",
                )

    def test_prediction_ohne_stage_wird_uebersprungen(self):
        """Verhaltensnachweis auf der guenstig testbaren Stelle: derselbe
        Codepfad wie in den drei Modulen, hier ueber `rival_profiles._profile`
        (T-0179) -- ohne Stage kein Punkt, sichtbar in `skipped_stage`."""
        from wm_tipps.rival_profiles import _profile
        from wm_tipps.scoring import DEFAULT_ROUND_ID

        prof = _profile(
            "X", {"ko-091": "2:0"}, {"ko-091": [2, 0]}, {},
            {"ko-091": {"fixture": {}}},          # Prediction da, Stage fehlt
            DEFAULT_ROUND_ID,
        )
        self.assertEqual(prof["played"], 0)
        self.assertEqual(prof["points"], 0)
        self.assertEqual(prof["skipped_stage"], 1)


if __name__ == "__main__":
    unittest.main()
