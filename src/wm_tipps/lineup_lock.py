"""Lineup-Lock-Status vor Anpfiff (Codex-Roadmap #2).

Berichtet je Spiel im Pre-Kickoff-Fenster, ob bestaetigte Aufstellungen
vorliegen (manuell > confirmed-News > expected-News > keine) und ob der
Tipp damit als 'final' gelten kann.

Nachtspiel-Logik: wer Tipps von Hand eingibt, ist bei spaeten Anstossen
schon im Bett -- die bestaetigten XIs (~1h vor Anpfiff) kommen dann zu
spaet, um den Tipp noch zu aendern. Fuer solche Spiele dient der Lock dem
Modell-Record, nicht der Eingabe; der Report markiert das explizit. Das
Zeitfenster ist ueber NIGHT_WINDOW_* konfigurierbar.

Reiner Report (mutiert nichts). Das eigentliche Einfrieren des Tipps
passiert weiter ueber tip_snapshots (zum Anpfiff).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .lineup_roles import (
    NEWS_CONFIRMED_ROLE_SOURCE,
    NEWS_EXPECTED_ROLE_SOURCE,
    lineup_xis_from_news,
    load_manual_lineups,
)
from .scoring import DEFAULT_ROUND_ID

# Anstosszeiten (lokal, CEST) in diesem Fenster gelten als "Nachtspiel":
# Tipp wird vorab eingegeben, spaete Lineup-News aendern ihn nicht mehr.
NIGHT_WINDOW_START_HOUR = 22
NIGHT_WINDOW_END_HOUR = 6


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _lineup_source(team: str, manual: Mapping[str, Any], news_xis: Mapping[str, Any]) -> str:
    if team in manual and manual[team]:
        return "manual"
    entry = news_xis.get(team)
    if entry:
        return entry[1]  # NEWS_CONFIRMED_ROLE_SOURCE | NEWS_EXPECTED_ROLE_SOURCE
    return "none"


def _is_locked(source: str) -> bool:
    return source in {"manual", NEWS_CONFIRMED_ROLE_SOURCE}


def lineup_lock_status(
    predictions: Iterable[Mapping[str, Any]],
    fixtures: Iterable[Mapping[str, Any]],
    news_items: Iterable[Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    window_minutes: int = 90,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=window_minutes)
    manual = load_manual_lineups()
    news_xis = lineup_xis_from_news(list(news_items or []))
    tips = {p.get("match_id"): p for p in predictions}

    rows: list[dict[str, Any]] = []
    for fx in fixtures:
        if fx.get("status") == "played":
            continue
        kickoff = _parse(fx.get("kickoff_utc") or fx.get("kickoff"))
        if kickoff is None or not (now <= kickoff <= horizon):
            continue
        home = fx.get("home") or fx.get("home_team")
        away = fx.get("away") or fx.get("away_team")
        hs = _lineup_source(home, manual, news_xis)
        as_ = _lineup_source(away, manual, news_xis)
        kickoff_cest_hour = (kickoff + timedelta(hours=2)).hour  # CEST = UTC+2 (Sommer)
        pred = tips.get(fx.get("match_id"), {})
        round_tips = pred.get("round_tips") or {}
        rows.append(
            {
                "match_id": fx.get("match_id"),
                "kickoff_utc": kickoff.isoformat(),
                "home": home,
                "away": away,
                "home_lineup": hs,
                "away_lineup": as_,
                "lockable": _is_locked(hs) and _is_locked(as_),
                "is_night_match": (
                    kickoff_cest_hour >= NIGHT_WINDOW_START_HOUR
                    or kickoff_cest_hour < NIGHT_WINDOW_END_HOUR
                ),
                "tip_primary": (round_tips.get(DEFAULT_ROUND_ID) or {}).get("tip"),
            }
        )
    rows.sort(key=lambda r: r["kickoff_utc"])
    return {
        "now": now.isoformat(),
        "window_minutes": window_minutes,
        "in_window": len(rows),
        "lockable": sum(1 for r in rows if r["lockable"]),
        "waiting_for_lineup": sum(1 for r in rows if not r["lockable"]),
        "night_matches": sum(1 for r in rows if r["is_night_match"]),
        "matches": rows,
        "note": (
            "Nachtspiele (Anpfiff im konfigurierten Nachtfenster) werden vorab "
            "eingetragen -- "
            "ihr Lock dient dem Modell-Record, nicht der Eingabe."
        ),
    }
