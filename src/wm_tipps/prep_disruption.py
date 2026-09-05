"""Prep-/Einreise-Stoerung als Kontext-Signal (T-0066).

Zwei Quellen, EIN Effekt: ein kleiner, geclampter xG-Malus fuer das
betroffene Team in einem konkreten Spiel, weil dessen Vorbereitung/
Einreise gestoert ist (z.B. Einreise nur am Spieltag, <48h trotz
FIFA-48h-Regel, verweigertes Visum).

1. Manueller Per-Match-Override (`data/manual_prep_disruption.json`) --
   autoritativ (Policy: manuelle Daten zuerst, nichts erfinden).
2. Kuratiertes News-Sub-Signal (`news.entry_disruption_severity`) -- nur
   eindeutige Einreise-Phrasen, zugeordnet ans NAECHSTE Spiel des Teams.
   Manuell schlaegt News.

Nicht backtestbar -> bewusst klein und immer als eigene Breakdown-Zeile
sichtbar (kein stilles, politisch aufgeladenes Signal im Tipp).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .io import read_json
from .news import entry_disruption_severity
from .paths import DATA_DIR

MANUAL_PREP_DISRUPTION_PATH = DATA_DIR / "manual_prep_disruption.json"

# Deckel je Team/Spiel, an der bestehenden Reise/Rest-Mechanik orientiert
# (TRAVEL_TOTAL_CAP -0.10, REST_PENALTY_MAX -0.03).
PREP_DISRUPTION_CAP = -0.10
# Manuelle Severity -> Malus, falls kein expliziter xg_delta gesetzt ist.
SEVERITY_XG = {"mild": -0.04, "strong": -0.08}
# Automatischer Malus aus News (konservativer als manuell). Zwei Stufen
# analog zur News-Erkennung (T-0067): mild < strong.
NEWS_SEVERITY_XG = {"mild": -0.03, "strong": -0.05}
_SEVERITY_RANK = {"mild": 1, "strong": 2}


def load_manual_prep_disruptions() -> dict[str, Any]:
    payload = read_json(MANUAL_PREP_DISRUPTION_PATH, {"disruptions": {}})
    if not isinstance(payload, dict):
        return {}
    disruptions = payload.get("disruptions")
    return disruptions if isinstance(disruptions, dict) else {}


def _clamp_delta(value: float) -> float:
    return round(max(PREP_DISRUPTION_CAP, min(0.0, float(value))), 3)


def _manual_delta(entry: Mapping[str, Any]) -> float:
    if entry.get("xg_delta") is not None:
        return _clamp_delta(entry["xg_delta"])
    severity = str(entry.get("severity", "")).lower()
    return _clamp_delta(SEVERITY_XG.get(severity, SEVERITY_XG["mild"]))


def _parse_kickoff(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _next_fixture_for_team(
    fixtures: list[dict[str, Any]], team: str, now: datetime
) -> dict[str, Any] | None:
    upcoming = []
    for fixture in fixtures:
        if team not in (fixture.get("home_team"), fixture.get("away_team")):
            continue
        kickoff = _parse_kickoff(fixture.get("kickoff_utc"))
        if kickoff is None or kickoff < now:
            continue
        upcoming.append((kickoff, fixture))
    if not upcoming:
        return None
    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[0][1]


def _apply(
    index: dict[str, dict[str, Any]],
    fixture: Mapping[str, Any],
    team: str,
    delta: float,
    *,
    basis: str,
    reason: str,
    source: Any,
    overwrite: bool = False,
) -> None:
    match_id = fixture.get("match_id")
    if not match_id:
        return
    side = "home" if team == fixture.get("home_team") else "away"
    row = index.setdefault(match_id, {"home": None, "away": None})
    if row[side] is not None and not overwrite:
        return
    row[side] = {
        "team": team,
        "xg_delta": _clamp_delta(delta),
        "basis": basis,
        "reason": reason,
        "source": source,
    }


def build_prep_disruption_index(
    fixtures: list[dict[str, Any]],
    news_items: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    player_pool: Mapping[str, Any] | None = None,
    manual: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """match_id -> {"home": detail|None, "away": detail|None}.

    detail = {team, xg_delta, basis ('manual'|'news'), reason, source}.
    """
    if news_items is None:
        news_items = read_json(DATA_DIR / "news_items.json", {"items": []}).get("items", [])
    if manual is None:
        manual = load_manual_prep_disruptions()
    now = now or datetime.now(timezone.utc)

    fixture_teams = {
        team
        for fixture in fixtures
        for team in (fixture.get("home_team"), fixture.get("away_team"))
        if team
    }
    index: dict[str, dict[str, Any]] = {}

    # Teams mit manuellem Eintrag: der Mensch hat fuer dieses Team
    # entschieden -> automatisches News-Signal komplett unterdruecken, damit
    # eine (oft team-, nicht spiel-genaue) News nie ein Folgespiel faelschlich
    # trifft (z.B. Iran-Visa-News -> spaeteres Spiel mit regulaerer Anreise).
    manual_teams = {
        entry.get("team")
        for entry in manual.values()
        if isinstance(entry, dict) and entry.get("team")
    }

    # 1) News -> staerkste Stoerung je Team -> naechstes Spiel des Teams.
    team_news: dict[str, tuple[str, dict[str, Any]]] = {}
    for item in news_items:
        for team in item.get("teams") or []:
            if team not in fixture_teams or team in manual_teams:
                continue
            severity = entry_disruption_severity(team, item, player_pool)
            if not severity:
                continue
            previous = team_news.get(team)
            if previous is None or _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(previous[0], 0):
                team_news[team] = (severity, item)

    for team, (severity, item) in team_news.items():
        fixture = _next_fixture_for_team(fixtures, team, now)
        if not fixture:
            continue
        _apply(
            index,
            fixture,
            team,
            NEWS_SEVERITY_XG.get(severity, NEWS_SEVERITY_XG["strong"]),
            basis="news",
            reason=item.get("title", ""),
            source=item.get("url") or item.get("source"),
        )

    # 2) Manueller Override -> autoritativ (ueberschreibt News).
    fixtures_by_id = {fixture.get("match_id"): fixture for fixture in fixtures}
    for match_id, entry in manual.items():
        fixture = fixtures_by_id.get(match_id)
        if not fixture or not isinstance(entry, dict):
            continue
        team = entry.get("team")
        if team not in (fixture.get("home_team"), fixture.get("away_team")):
            continue
        _apply(
            index,
            fixture,
            team,
            _manual_delta(entry),
            basis="manual",
            reason=entry.get("reason", ""),
            source=entry.get("source"),
            overwrite=True,
        )

    return index


def context_entry(row: Mapping[str, Any]) -> dict[str, Any]:
    """Bringt eine Index-Zeile in die Form, die `model.expected_goals`
    liest (analog heat_stress/travel_stress)."""
    home = row.get("home")
    away = row.get("away")
    return {
        "home_xg_delta": (home or {}).get("xg_delta", 0.0),
        "away_xg_delta": (away or {}).get("xg_delta", 0.0),
        "home": home,
        "away": away,
    }
