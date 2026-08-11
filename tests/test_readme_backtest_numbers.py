"""Klassenschutz: die im README genannten Backtest-Zahlen muessen stimmen.

Anlass (T-0160): zweimal hintereinander behauptete ein geschriebenes Artefakt
bessere Zahlen, als der Code liefert -- erst `data/backtest_report.json`
(aus einem aelteren Codestand, nie neu gerechnet), dann das README, das die
Zahlen aus genau diesem stalen Report abgeschrieben hatte. Beide Male fiel es
niemandem auf. Die Einzelzahlen zu korrigieren fixt den Vorfall, nicht die
Klasse.

Zwei Stufen, beide billig -- ein frischer Backtest kostet ~80s und hat in
einer 25s-Suite nichts verloren:

  1. FRISCHE: ist `backtest_report.json` juenger als der Code, aus dem er
     entsteht (Modell, Scoring, Rundenregeln, Backtest, Historik-Loader)?
     Genau hier ging es schief -- der Report ueberlebte Code-Aenderungen.
  2. DECKUNG: taucht jede im README-Backtest-Abschnitt genannte Punktzahl
     auch im Report auf? Faengt Abschreibfehler und erfundene Zahlen.

Dazu unten eine dritte, gleichartige Stufe fuer die generierten Artefakte des
Spieler-Boards (`GenerierteArtefakteAktuellTest`).

Fehlt eine der beiden Dateien (frischer Clone, oeffentliche Verteilung),
skippt der Test -- er ist ein Autoren-Schutz, kein Nutzer-Gate.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "backtest_report.json"

# Der Public-Override liegt privat unter tools/public/; im Snapshot heisst er README.md.
README_CANDIDATES = (ROOT / "tools" / "public" / "README.md", ROOT / "README.md")

# Was den Report inhaltlich bestimmt. Aendert sich davon etwas, ohne dass der
# Report neu gerechnet wird, sind seine Zahlen still veraltet.
#
# NUR CODE, bewusst OHNE die data/backtest_*.json: jeder Aufruf, der
# `build_historical_dataset()` anfasst (z.B. `risk-dial` ueber
# `_backtest_samples`), schreibt diese Dateien neu und macht sie juenger als den
# Report -- ohne dass sich an den Zahlen irgendetwas aendert. Nachgemessen am
# 21.07.2026: nach so einem Lauf unterschied sich ausschliesslich der
# `_meta`-Block, der `results`-Block (die eigentlichen Spieldaten) war
# byte-identisch. Ein mtime-Test ueber diese Dateien meldet also verlaesslich
# Fehlalarme und wuerde als "der Test spinnt halt" weggeklickt -- genau die
# Sorte Schutz, die dann nichts mehr schuetzt.
REPORT_INPUTS = (
    ROOT / "src" / "wm_tipps" / "backtest.py",
    ROOT / "src" / "wm_tipps" / "model.py",
    ROOT / "src" / "wm_tipps" / "scoring.py",
    ROOT / "src" / "wm_tipps" / "round_rules.py",
    ROOT / "src" / "wm_tipps" / "historical.py",
)

SECTION_START = "## What the backtest says"
SECTION_END = "## Architecture"
# Punkte pro Spiel stehen im README dreistellig ("1.909"); Jahreszahlen und
# Prozentwerte haben ein anderes Format und werden so nicht mitgefangen.
PPM_PATTERN = re.compile(r"\b([0-2]\.\d{3})\b")
TOLERANCE = 0.0005


def _readme() -> Path | None:
    return next((p for p in README_CANDIDATES if p.exists()), None)


def _report_values(payload: dict) -> set[float]:
    """Alle Punkte-pro-Spiel-Werte des Reports, egal auf welcher Ebene."""
    values: set[float] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"points_per_match", "points_per_match_delta"} and isinstance(value, (int, float)):
                    values.add(round(float(value), 4))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return values


class ReadmeBacktestNumbersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not REPORT.exists():
            raise unittest.SkipTest(
                "data/backtest_report.json fehlt -- `cli backtest-report` laufen lassen."
            )
        path = _readme()
        if path is None:
            raise unittest.SkipTest("Kein README gefunden.")
        cls.readme_path = path
        cls.readme = path.read_text(encoding="utf-8")
        cls.payload = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_report_is_newer_than_its_inputs(self):
        """Frische-Stufe -- wirkt NUR beim Autor, nicht beim Nutzer.

        Der Test vergleicht mtimes. In einem frischen Clone schreibt git alle
        Dateien im selben Moment, also ist der Report nie aelter als seine
        Eingaben und der Test feuert dort grundsaetzlich nicht. Er ist damit
        kein Nutzer-Gate, sondern ein Schutz gegen genau den Ablauf, der
        T-0160 ausgeloest hat: Code aendern, Report nicht neu rechnen,
        README-Zahlen still veralten lassen.
        Im Public-Snapshot ist backtest_report.json ohnehin ausgeschlossen --
        dort skippt die ganze Klasse (setUpClass).
        """
        report_mtime = REPORT.stat().st_mtime
        stale = [
            p.relative_to(ROOT)
            for p in REPORT_INPUTS
            if p.exists() and p.stat().st_mtime > report_mtime
        ]
        self.assertEqual(
            stale,
            [],
            "backtest_report.json ist aelter als seine Eingaben "
            f"({', '.join(str(p) for p in stale)}). Neu rechnen: "
            "`PYTHONPATH=src python3 -m wm_tipps.cli backtest-report`. "
            "Sonst behauptet das README Zahlen, die der Code nicht mehr liefert.",
        )

    def test_every_readme_number_exists_in_the_report(self):
        start = self.readme.find(SECTION_START)
        self.assertNotEqual(start, -1, f"'{SECTION_START}' nicht im README gefunden.")
        end = self.readme.find(SECTION_END, start)
        section = self.readme[start : end if end != -1 else len(self.readme)]

        claimed = {float(m) for m in PPM_PATTERN.findall(section)}
        self.assertTrue(claimed, "Keine Punkte-pro-Spiel-Zahlen im README-Abschnitt gefunden.")

        actual = _report_values(self.payload)
        # Das README nennt auch ABGELEITETE Werte ("+0.055 gegenueber Elo",
        # "trails by 0.274") -- die stehen so in keinem Report-Feld. Paarweise
        # Differenzen sind deshalb ebenfalls gueltig.
        # Preis dieser Lockerung: bei ~50 Werten entstehen ~1200 Differenzen,
        # eine falsche Zahl kann also zufaellig treffen. Der Test faengt damit
        # zuverlaessig STALE Zahlen (die Report-Werte verschieben sich alle
        # gemeinsam) und nur wahrscheinlich einen Tippfehler.
        derived = {
            round(abs(a - b), 4)
            for a in actual
            for b in actual
            if a != b
        }
        allowed = actual | derived
        unmatched = sorted(
            value
            for value in claimed
            if not any(abs(value - real) <= TOLERANCE for real in allowed)
        )
        self.assertEqual(
            unmatched,
            [],
            f"{self.readme_path.name} nennt Zahlen, die im Backtest-Report nicht vorkommen: "
            f"{unmatched}. Entweder ist das README falsch oder der Report veraltet.",
        )




# --- Generierte Artefakte, die den Turnierstand widerspiegeln sollen ---------
#
# Gleiche Fehlerklasse wie oben (T-0160): ein committetes Artefakt behauptet
# einen Stand, den der Code nicht mehr liefert. Der Ausloeser hier war das
# Spieler-Board, das nach Turnierende noch "54/72 Spiele" im Kopf trug.
#
# BEWUSST NICHT abgedeckt: exports/entry_watch.md und exports/matchday_dry_run.*.
# Die sind an ein Live-Fenster gebunden ("Fixtures mit Anstoss in den naechsten
# 3 Tagen") und tragen ihr Laufdatum im Kopf. Ein mtime-Test wuerde dort
# dauerhaft rot stehen, weil fixtures.json zwangslaeufig juenger ist, obwohl das
# Dokument genau das ist, was es sein soll: ein datierter Beispiellauf.
ARTEFAKT_EINGABEN = {
    ROOT / "exports" / "player_watch.md": (
        ROOT / "analysis" / "wm_player_ratings.py",
        ROOT / "data" / "fixtures.json",
    ),
    ROOT / "analysis" / "wm_player_board.html": (
        ROOT / "analysis" / "wm_player_ratings.py",
        ROOT / "data" / "fixtures.json",
    ),
}


# Toleranz gegen Checkout-Rauschen. `git clone` schreibt die Dateien NICHT mit
# identischer mtime -- die Reihenfolge im Checkout entscheidet, und damit ist
# jede Eingabe mal ein paar Millisekunden juenger als das Artefakt. Ohne
# Toleranz stand dieser Test in JEDEM frischen Clone rot (am 21.07.2026 in allen
# drei Public-Umgebungen nachgestellt) und waere damit genau das geworden, was
# er verhindern soll: eine Warnung, die man wegklickt.
# Echte Veralterung ist immer Stunden bis Tage alt, nie Sekunden.
FRISCHE_TOLERANZ_SEKUNDEN = 600


class GenerierteArtefakteAktuellTest(unittest.TestCase):
    """Wie die Frische-Stufe oben ein Autoren-Schutz, kein Nutzer-Gate."""

    def test_artefakte_sind_juenger_als_ihre_eingaben(self):
        for artefakt, eingaben in ARTEFAKT_EINGABEN.items():
            if not artefakt.exists():
                continue  # im Public-Snapshot ggf. nicht enthalten
            with self.subTest(artefakt=artefakt.name):
                grenze = artefakt.stat().st_mtime + FRISCHE_TOLERANZ_SEKUNDEN
                veraltet = [
                    p.relative_to(ROOT)
                    for p in eingaben
                    if p.exists() and p.stat().st_mtime > grenze
                ]
                self.assertEqual(
                    veraltet,
                    [],
                    f"{artefakt.relative_to(ROOT)} ist aelter als "
                    f"{', '.join(str(p) for p in veraltet)}. Neu bauen: "
                    "`PYTHONPATH=src python3 analysis/wm_player_ratings.py --html` "
                    "bzw. `--watch`.",
                )


if __name__ == "__main__":
    unittest.main()
