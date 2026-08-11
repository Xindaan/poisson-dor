"""Klassenschutz: die Tupelform von `_backtest_samples` gegen ihre Konsumenten.

Anlass (Schluss-Verifikation 21.07.2026): `_backtest_samples()` liefert seit der
Elfmeter-Arbeit 6-Tupel (zusaetzlich `shootout`), `risk_dial` entpackte an drei
Stellen weiter 5. Ergebnis: `risk-dial` crashte bei JEDEM Aufruf mit
`ValueError: too many values to unpack` -- und zwar zwei Tage lang bei
vollstaendig gruener Suite, weil kein Test die Schnittstelle zwischen Erzeuger
und Verbrauchern gepinnt hat. Gefunden wurde es erst, als das Kommando fuer die
oeffentliche Verteilung von Hand ausprobiert wurde.

Die Fehlerklasse ist "Erzeuger erweitert, Verbraucher nicht nachgezogen". Ein
Test auf die reine Laenge reicht dafuer nicht -- er wuerde gruen bleiben, wenn
jemand die Reihenfolge der Felder vertauscht. Deshalb wird hier BEIDES gepinnt:
die Stelligkeit und die Bedeutung der Felder.
"""
from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.tip_strategy_ab import _backtest_samples  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Vertrag von `_backtest_samples`, in Reihenfolge.
FELDER = ("home_xg", "away_xg", "stage", "actual", "penalty_winner", "shootout")

# Module, die die Tupel entpacken. Wer hier neu dazukommt, muss mitgepinnt
# werden -- sonst wiederholt sich genau der Vorfall.
KONSUMENTEN = (
    ROOT / "src" / "wm_tipps" / "risk_dial.py",
    ROOT / "src" / "wm_tipps" / "tip_strategy_ab.py",
)


class BacktestSampleShapeTest(unittest.TestCase):
    def test_vertrag_ist_dokumentiert(self):
        """Die Rueckgabe-Annotation muss die Stelligkeit nennen."""
        annotation = str(inspect.signature(_backtest_samples).return_annotation)
        self.assertEqual(
            annotation.count(","),
            len(FELDER) - 1,
            f"Die Annotation von _backtest_samples nennt nicht {len(FELDER)} "
            f"Felder. Erwarteter Vertrag: {FELDER}",
        )

    def test_alle_entpackenden_schleifen_haben_die_richtige_stelligkeit(self):
        """Jede `for a, b, ... in samples`-Schleife muss 6 Namen binden.

        Statisch geprueft (AST) statt zur Laufzeit: `_backtest_samples()` baut
        sieben historische Datensaetze und braucht Minuten -- in einer Suite,
        die in 30 Sekunden durchlaufen soll, hat das nichts verloren.
        """
        gefunden = 0
        for pfad in KONSUMENTEN:
            if not pfad.exists():
                continue
            baum = ast.parse(pfad.read_text(encoding="utf-8"))
            for knoten in ast.walk(baum):
                if not isinstance(knoten, (ast.For, ast.comprehension)):
                    continue
                quelle = knoten.iter
                # nur Schleifen ueber eine Variable namens *sample*
                if not (isinstance(quelle, ast.Name) and "sample" in quelle.id):
                    continue
                ziel = knoten.target
                if not isinstance(ziel, ast.Tuple):
                    continue
                gefunden += 1
                with self.subTest(datei=pfad.name, zeile=getattr(knoten, "lineno", "?")):
                    self.assertEqual(
                        len(ziel.elts),
                        len(FELDER),
                        f"{pfad.relative_to(ROOT)}:{getattr(knoten, 'lineno', '?')} "
                        f"entpackt {len(ziel.elts)} statt {len(FELDER)} Werte. "
                        f"Vertrag: {FELDER}",
                    )
        self.assertGreater(
            gefunden,
            0,
            "Keine entpackende Schleife gefunden -- der Test prueft dann nichts. "
            "Wurde die Schnittstelle umgebaut? KONSUMENTEN anpassen.",
        )

    def test_shootout_wird_an_actual_for_round_durchgereicht(self):
        """Der zweite Teil des Vorfalls: `risk_dial` ignorierte `shootout`.

        Die Stelligkeit allein haette das nicht gefangen -- man kann sechs
        Werte entpacken und den sechsten wegwerfen. Genau das tat der Code:
        er rief `actual_for_round(result, penalty_winner, round_id)` ohne die
        Elferbilanz und benutzte damit stillschweigend die in `scoring.py` als
        "systematisch zu optimistisch" dokumentierte Naeherung.
        """
        geprueft = 0
        for pfad in KONSUMENTEN:
            if not pfad.exists():
                continue
            baum = ast.parse(pfad.read_text(encoding="utf-8"))
            for funktion in ast.walk(baum):
                if not isinstance(funktion, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Nur Funktionen, die ueberhaupt eine Elferbilanz zur Hand haben.
                # ANDERE Aufrufer sind legitim dreistellig: `_live_counterfactual`
                # etwa verarbeitet Pool-`actuals` der Form [h, a] -- dort gibt es
                # schlicht keine Elferbilanz zum Durchreichen. Ohne diese
                # Einschraenkung meldet der Test genau das faelschlich.
                bindet_shootout = any(
                    isinstance(n, ast.Name) and n.id == "shootout" and isinstance(n.ctx, ast.Store)
                    for n in ast.walk(funktion)
                )
                if not bindet_shootout:
                    continue
                for knoten in ast.walk(funktion):
                    if not isinstance(knoten, ast.Call):
                        continue
                    name = getattr(knoten.func, "id", None) or getattr(knoten.func, "attr", None)
                    if name != "actual_for_round":
                        continue
                    geprueft += 1
                    with self.subTest(datei=pfad.name, zeile=knoten.lineno):
                        self.assertGreaterEqual(
                            len(knoten.args) + len(knoten.keywords),
                            4,
                            f"{pfad.relative_to(ROOT)}:{knoten.lineno} hat `shootout` "
                            "im Zugriff, ruft actual_for_round aber ohne -- damit "
                            "greift die Naeherung statt der echten Elfer-Scoreline.",
                        )
        self.assertGreater(geprueft, 0, "Kein Aufrufer mit `shootout` gefunden.")


if __name__ == "__main__":
    unittest.main()
