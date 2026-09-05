"""Die eine Quelle fuer "welches Spiel ist wie ausgegangen" (T-0188).

Vorher baute sich jeder Auswertungspfad diese Antwort selbst zusammen --
`eval_live`, `cli._played_results`, `dashboard` -- jeweils mit einer eigenen
Vorstellung davon, welche Felder ein Ergebnis hat. Drei Kopien, drei
Abweichungen; die teuerste: alle drei warfen den ``penalty_winner`` weg, den
das Fixture traegt, weil sie ihn hart auf ``None`` setzten.

Was das kostet, ist keine Kosmetik: ohne Elfmeter-Sieger wertet eine Runde
mit Elfmeter-Scope ein 1:1 n.V. als Remis. Ein Tipp "1:1" bekaeme dort die
volle Exakt-Punktzahl statt der real erzielten 0 -- der Rueckstand auf das
Feld verschwindet aus der eigenen Auswertung. Maskiert war das nur, solange
jemand jedes Elferspiel von Hand in ``manual_results.json`` nachtraegt.

Rangfolge, an einer Stelle festgelegt:
  1. Fixtures (``status == "played"`` plus ``result``) sind die Basis --
     stabile match_id, kommt automatisch aus openfootball.
  2. ``manual_results.json`` ueberschreibt: Korrekturen, und vor allem die
     Elferbilanz (``shootout``), die die Fixture-Zeile nicht fuehrt.

Rueckgabe je Spiel: ``actual``, ``penalty_winner``, ``shootout``, ``source``
-- genau die vier Felder, die ``scoring.actual_for_round`` braucht.
"""
from __future__ import annotations

from typing import Any, Mapping

from .io import read_json
from .paths import DATA_DIR
from .role_experiment import normalize_manual_results


def results_from_fixtures(fixtures: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Ergebnisse gespielter Spiele aus den Fixtures.

    Der ``penalty_winner`` wird MITGENOMMEN, wenn die Fixture-Zeile ihn
    fuehrt -- `knockout._winner_loser` schreibt ihn dort hin, und ohne ihn
    ist ein K.o.-Remis nicht aufloesbar. ``shootout`` fuehren Fixture-Zeilen
    nicht; die reine Elferbilanz kommt aus ``manual_results.json``.
    """
    out: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        result = fixture.get("result")
        if fixture.get("status") != "played":
            continue
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            continue
        match_id = fixture.get("match_id")
        if not match_id:
            continue
        try:
            actual = [int(result[0]), int(result[1])]
        except (TypeError, ValueError):
            continue
        penalty_winner = fixture.get("penalty_winner")
        out[str(match_id)] = {
            "actual": actual,
            "penalty_winner": penalty_winner if penalty_winner in {"home", "away"} else None,
            "shootout": None,
            "source": "openfootball",
        }
    return out


def merge_manual_results(
    auto: Mapping[str, Mapping[str, Any]],
    manual: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Manuelle Ergebnisse ueber die automatischen legen.

    Feldweise statt Eintrag-ersetzend: ein manueller Eintrag ohne
    ``penalty_winner`` darf den aus dem Fixture nicht loeschen. Genau so ist
    die alte ``dict.update``-Variante Information losgeworden.
    """
    merged = {match_id: dict(row) for match_id, row in auto.items()}
    for match_id, row in manual.items():
        target = merged.setdefault(str(match_id), {"source": "manual_results"})
        if row.get("actual"):
            target["actual"] = list(row["actual"])
            target["source"] = "manual_results"
        for key in ("penalty_winner", "shootout"):
            if row.get(key) is not None:
                target[key] = row[key]
            else:
                target.setdefault(key, None)
    return merged


def played_results(
    fixtures: list[Mapping[str, Any]] | None = None,
    manual_payload: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Alle bekannten Ergebnisse: Fixtures als Basis, manuelle als Override.

    Ohne Argumente liest die Funktion ``data/fixtures.json`` und
    ``data/manual_results.json``.
    """
    if fixtures is None:
        payload = read_json(DATA_DIR / "fixtures.json", {"fixtures": []})
        fixtures = payload.get("fixtures", []) if isinstance(payload, Mapping) else []
    if manual_payload is None:
        manual_payload = read_json(DATA_DIR / "manual_results.json", {})
    return merge_manual_results(
        results_from_fixtures(list(fixtures)),
        normalize_manual_results(manual_payload),
    )
