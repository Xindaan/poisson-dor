"""Bausteine fuer Kicktipp-Rundenregeln: Punkteschemata und `TipRound`.

Bewusst OHNE paket-interne Imports. Sowohl `scoring` (neutrale Defaults) als
auch das optionale private `rounds_local` (echte Runden) bauen darauf auf --
laege der Baustein in einem der beiden, waere der jeweils andere Import
zirkulaer und die Ladereihenfolge waere eine Falle.

Regelschema-Vokabular:
  * "classic"    -- Gruppe 2-3-4, K.o. flach 3-4-6 ueber alle Runden.
  * "escalating" -- Gruppe 2-3-4, K.o. 3-4-6, Halbfinale und Finale 4-6-8.
Beides sind gaengige Kicktipp-Konfigurationen; eigene Runden definiert man in
einer lokalen `rounds_local.py` (siehe `rounds_local.example.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


GROUP_POINTS = {"tendency": 2, "difference": 3, "exact": 4}
KNOCKOUT_POINTS = {"tendency": 3, "difference": 4, "exact": 6}
ESCALATING_LATE_KNOCKOUT_POINTS = {"tendency": 4, "difference": 6, "exact": 8}
GROUP_STAGES = {"group", "gruppenphase", "vorrunde"}
# Nur die beiden Endspiel-Runden. Bewusst knapp gehalten: die Defaults sind
# Beispielkonfigurationen, keine Nachbildung einer bestimmten realen Runde.
# Wer frueher eskalieren will (ab Achtelfinale o.ae.), setzt `stage_points`
# in einer eigenen rounds_local.py -- siehe rounds_local.example.py.
ESCALATING_LATE_KNOCKOUT_STAGES = {
    "semi",
    "semi_final",
    "final",
}

# Marker im `result_scope`, die "diese Runde wertet Elfmetertore mit" bedeuten.
# Deutsch UND englisch, damit eigene Runden nicht raten muessen, welches Wort
# der Parser erwartet. Rein additiv -- bestehende deutsche Scopes unveraendert.
PENALTY_SCOPE_MARKERS = ("elfmeter", "penalt")


def scope_resolves_penalties(result_scope: str) -> bool:
    """True, wenn dieser Ergebnis-Scope Elfmetertore in die Wertung nimmt."""
    scope = (result_scope or "").lower()
    return any(marker in scope for marker in PENALTY_SCOPE_MARKERS)


@dataclass(frozen=True)
class TipRound:
    id: str
    name: str
    group_points: Mapping[str, int]
    knockout_points: Mapping[str, int]
    bonus_questions: tuple[str, ...]
    bonus_points: Mapping[str, int | None]
    result_scope: str
    stage_points: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    non_tippable_stages: frozenset[str] = field(default_factory=frozenset)

    def points_for_stage(self, stage: str) -> Mapping[str, int]:
        stage_normalized = (stage or "group").lower()
        if stage_normalized in GROUP_STAGES:
            return self.group_points
        if stage_normalized in self.stage_points:
            return self.stage_points[stage_normalized]
        return self.knockout_points

    def payload(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "group": dict(self.group_points),
            "knockout": dict(self.knockout_points),
            "bonus_questions": list(self.bonus_questions),
            "bonus_points": dict(self.bonus_points),
            "result_scope": self.result_scope,
            "non_tippable_stages": sorted(self.non_tippable_stages),
        }
        if self.stage_points:
            payload["stage_points"] = {
                stage: dict(points)
                for stage, points in sorted(self.stage_points.items())
            }
        return payload
