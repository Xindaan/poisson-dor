"""Pre-Kickoff-Tipp-Snapshot (T-0081 Teil a).

Friert je Spiel/Runde den Modell-Tipp ein, der VOR Anstoss live war --
damit die Live-Auswertung (eval_live) das wertet, was tatsaechlich getippt
wurde, nicht den nachtraeglich (mit Post-Match-Inputs / geaendertem
Spielplan) neu gerechneten Tipp. Analog zum Rollen-A/B-Log: vor Anstoss
aktualisieren, ab Anstoss einfrieren.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .io import read_json, write_json
from .paths import DATA_DIR

TIP_SNAPSHOTS_PATH = DATA_DIR / "tip_snapshots.json"


def _parse_kickoff(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_tip_snapshots() -> dict[str, Any]:
    payload = read_json(TIP_SNAPSHOTS_PATH, {"snapshots": {}})
    snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
    return snapshots if isinstance(snapshots, dict) else {}


def update_tip_snapshots(
    predictions: list[dict[str, Any]],
    existing: Mapping[str, Any] | None = None,
    *,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Je Spiel den aktuellen Tipp festhalten; sobald angepfiffen, einfrieren.
    Eingefrorene Eintraege werden NICHT mehr ueberschrieben (auch wenn der
    nachtraegliche Build einen anderen Tipp rechnet)."""
    snapshots = dict(existing if existing is not None else load_tip_snapshots())
    now = now or datetime.now(timezone.utc)
    for prediction in predictions:
        match_id = prediction.get("match_id")
        if not match_id:
            continue
        previous = snapshots.get(match_id)
        if isinstance(previous, Mapping) and previous.get("frozen"):
            continue
        fixture = prediction.get("fixture") or {}
        kickoff = _parse_kickoff(fixture.get("kickoff_utc"))
        round_tips = {
            round_id: (row or {}).get("tip")
            for round_id, row in (prediction.get("round_tips") or {}).items()
        }
        snapshots[match_id] = {
            "match": f"{fixture.get('home_team', '?')} - {fixture.get('away_team', '?')}",
            "kickoff_utc": fixture.get("kickoff_utc"),
            "round_tips": round_tips,
            "frozen": kickoff is not None and kickoff <= now,
            "snapshot_at": now.isoformat(),
        }
    if write:
        write_json(TIP_SNAPSHOTS_PATH, {"snapshots": snapshots, "updated_at": now.isoformat()})
    return snapshots


def snapshot_tip(snapshots: Mapping[str, Any], match_id: str, round_id: str) -> str | None:
    """Eingefrorenen Pre-Kickoff-Tipp je Spiel/Runde, falls vorhanden."""
    entry = snapshots.get(match_id)
    if isinstance(entry, Mapping):
        return ((entry.get("round_tips") or {}).get(round_id))
    return None
