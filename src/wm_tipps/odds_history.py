"""Append-only Odds-Snapshot-Historie (Codex-Roadmap #1).

Speichert jeden GEAENDERTEN Quotenstand je (match_id, market, source) als
JSONL-Zeile, damit Bewegungen sichtbar werden: alte->neue Quote, Markt
kippt, stale Quelle, Closing-Line-Naehe. Diese Historie ist NICHT
rekonstruierbar (Live-Beobachtung) -> wird committet, nicht gitignored.

Append-on-change: ein neuer Snapshot wird nur geschrieben, wenn sich der
Wert gegenueber dem letzten Snapshot fuer denselben Schluessel aendert.
Wiederholte Refreshes derselben statischen CSV erzeugen also keine
Duplikat-Zeilen.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .paths import DATA_DIR

ODDS_SNAPSHOT_PATH = DATA_DIR / "odds_snapshots.jsonl"
_OUTCOMES = ("home", "draw", "away")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_snapshots(path=None) -> list[dict[str, Any]]:
    path = path or ODDS_SNAPSHOT_PATH
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def snapshot_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("match_id")),
        str(record.get("market")),
        str(record.get("source")),
    )


def _value_payload(record: Mapping[str, Any]) -> Any:
    """Vergleichsrelevanter Wert (ohne Zeitstempel) zur Aenderungserkennung."""
    market = record.get("market")
    if market == "1x2":
        odds = record.get("decimal_odds") or {}
        return [round(float(odds[o]), 4) if odds.get(o) is not None else None for o in _OUTCOMES]
    if market == "exact_score":
        prices = record.get("prices") or []
        return sorted(
            (str(p.get("score")), round(float(p["decimal_odds"]), 4) if p.get("decimal_odds") is not None else None)
            for p in prices
        )
    return {k: v for k, v in record.items() if k not in ("observed_at", "source_updated")}


def last_for_key(snapshots: Iterable[Mapping[str, Any]], key: tuple[str, str, str]) -> dict | None:
    last = None
    for rec in snapshots:
        if snapshot_key(rec) == key:
            last = rec
    return last


def append_snapshots(records: Iterable[Mapping[str, Any]], path=None, existing=None) -> dict[str, Any]:
    """Haengt nur GEAENDERTE Snapshots an. Gibt Zaehler + die neuen Keys zurueck."""
    path = path or ODDS_SNAPSHOT_PATH
    snapshots = list(existing if existing is not None else load_snapshots(path))
    appended: list[dict[str, Any]] = []
    for record in records:
        key = snapshot_key(record)
        prev = last_for_key(snapshots, key)
        if prev is not None and _value_payload(prev) == _value_payload(record):
            continue
        appended.append(dict(record))
        snapshots.append(dict(record))
    if appended:
        with path.open("a", encoding="utf-8") as fh:
            for record in appended:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "appended": len(appended),
        "total": len(snapshots),
        "appended_keys": sorted({"|".join(snapshot_key(r)) for r in appended}),
    }


def record_from_consensus(consensus: Mapping[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    return {
        "observed_at": observed_at or _now(),
        "source_updated": consensus.get("last_updated"),
        "match_id": consensus.get("match_id"),
        "market": "1x2",
        "source": "consensus",
        "decimal_odds": consensus.get("decimal_odds"),
        "probabilities": consensus.get("probabilities"),
        "overround": consensus.get("overround"),
        "source_count": consensus.get("source_count"),
    }


def record_from_exact_score(item: Mapping[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    return {
        "observed_at": observed_at or item.get("observed_at") or _now(),
        "match_id": item.get("match_id"),
        "market": "exact_score",
        "source": "bwin",
        "prices": [
            {"score": p.get("score"), "decimal_odds": p.get("decimal_odds")}
            for p in (item.get("prices") or [])
        ],
        "overround_explicit": item.get("overround_explicit"),
    }


def capture_market_snapshots(odds_items, exact_items=None, path=None) -> dict[str, Any]:
    """Baut Snapshots aus 1X2-Konsens + optionalen Bwin-Exact-Scores und
    haengt nur Geaendertes an."""
    from .odds import odds_by_match  # lazy: vermeidet Import-Zyklus

    now = _now()
    records: list[dict[str, Any]] = []
    for match_id, cons in sorted(odds_by_match(odds_items).items()):
        if cons.get("decimal_odds"):
            records.append(record_from_consensus(cons, observed_at=now))
    for item in exact_items or []:
        records.append(record_from_exact_score(item, observed_at=item.get("observed_at") or now))
    return append_snapshots(records, path=path)


def _drift(first: Mapping[str, Any], last: Mapping[str, Any]) -> dict[str, float] | None:
    fp = first.get("probabilities") or {}
    lp = last.get("probabilities") or {}
    if not fp or not lp:
        return None
    out = {}
    for o in _OUTCOMES:
        if fp.get(o) is not None and lp.get(o) is not None:
            out[o] = round(float(lp[o]) - float(fp[o]), 4)
    return out or None


def _stale_days(observed_at: str | None, now: datetime) -> float | None:
    if not observed_at:
        return None
    try:
        ts = datetime.fromisoformat(observed_at)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return round((now - ts).total_seconds() / 86400.0, 2)


def summarize_movements(snapshots: Iterable[Mapping[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Pro (match_id, market, source): Anzahl Snapshots, erster/letzter
    Stand, ob bewegt, Wahrscheinlichkeits-Drift (1x2) und Stale-Tage."""
    now = now or datetime.now(timezone.utc)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    rows = list(snapshots)
    for rec in rows:
        grouped.setdefault(snapshot_key(rec), []).append(rec)
    movements: list[dict[str, Any]] = []
    for key, recs in grouped.items():
        recs = sorted(recs, key=lambda r: str(r.get("observed_at") or ""))
        first, last = recs[0], recs[-1]
        match_id, market, source = key
        moved = _value_payload(first) != _value_payload(last)
        entry = {
            "match_id": match_id,
            "market": market,
            "source": source,
            "snapshots": len(recs),
            "moved": moved,
            "first_observed_at": first.get("observed_at"),
            "last_observed_at": last.get("observed_at"),
            "stale_days": _stale_days(last.get("observed_at"), now),
        }
        if market == "1x2":
            entry["first_decimal_odds"] = first.get("decimal_odds")
            entry["last_decimal_odds"] = last.get("decimal_odds")
            entry["prob_drift"] = _drift(first, last)
        elif market == "exact_score":
            entry["price_count"] = len(last.get("prices") or [])
        movements.append(entry)
    movements.sort(key=lambda m: (not m["moved"], m["match_id"], m["market"], m["source"]))
    return {
        "snapshot_count": len(rows),
        "keys": len(grouped),
        "moved_count": sum(1 for m in movements if m["moved"]),
        "movements": movements,
    }
