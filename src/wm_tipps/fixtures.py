from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .io import read_json, write_json
from .paths import DATA_DIR, RAW_DIR


OPENFOOTBALL_2026_URL = "https://raw.githubusercontent.com/openfootball/worldcup/master/2026--usa/cup.txt"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def fixture_key(group: str, home: str, away: str) -> str:
    """Stabiler, positions-UNABHAENGIGER Schluessel je Gruppenspiel (T-0081).
    Jede Paarung kommt in der Gruppe genau einmal vor -> Teams identifizieren
    das Spiel eindeutig, egal wie openfootball die Datei umsortiert/Spiele
    droppt. Die sequentielle match_id ist NICHT stabil (positionell)."""
    return f"g{str(group).lower()}-{_slug(home)}-v-{_slug(away)}"


def _utc_iso(year: int, month: int, day: int, time_text: str, offset_hours: int) -> str:
    hour, minute = (int(part) for part in time_text.split(":"))
    local = datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=offset_hours)))
    return local.astimezone(timezone.utc).isoformat()


def parse_openfootball_cup(text: str) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    fixtures: list[dict[str, Any]] = []
    current_group: str | None = None
    current_date: tuple[int, int] | None = None
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    group_line = re.compile(r"^Group\s+([A-L])\s*\|\s*(.+)$")
    date_line = re.compile(r"^\w+\s+([A-Za-z]+)\s+(\d{1,2})\s*$")
    match_line = re.compile(r"^\s*(\d{1,2}:\d{2})\s+UTC([+-]\d+)\s+(.+?)\s+v\s+(.+?)\s+@\s+(.+?)\s*$")
    # Gespieltes Spiel: "HOME  H-A (HT-AT)  AWAY  @ Venue" (T-0081). openfootball
    # ersetzt das "v" durch das Ergebnis -- diese Zeilen MUSS der Parser auch
    # erfassen, sonst fallen gespielte Spiele raus und die match_ids verrutschen.
    played_line = re.compile(
        r"^\s*(\d{1,2}:\d{2})\s+UTC([+-]\d+)\s+(.+?)\s+(\d+)-(\d+)(?:\s+\(\d+-\d+\))?\s+(.+?)\s+@\s+(.+?)\s*$"
    )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        group_match = group_line.match(line)
        if group_match:
            group = group_match.group(1)
            teams = re.split(r"\s{2,}|\t+", group_match.group(2).strip())
            teams = [team.strip() for team in teams if team.strip()]
            groups[group] = teams
            current_group = group
            continue
        section_match = re.match(r"^▪\s+Group\s+([A-L])", line)
        if section_match:
            current_group = section_match.group(1)
            continue
        date_match = date_line.match(line)
        if date_match and date_match.group(1).lower() in months:
            current_date = (months[date_match.group(1).lower()], int(date_match.group(2)))
            continue
        played_match = played_line.match(raw_line)
        if played_match and current_group and current_date:
            time_text, offset, home, home_goals, away_goals, away, venue = played_match.groups()
            match_number = len(fixtures) + 1
            home_team = " ".join(home.split())
            away_team = " ".join(away.split())
            fixtures.append(
                {
                    "match_id": f"g{current_group.lower()}-{match_number:03d}",
                    "match_number": match_number,
                    "key": fixture_key(current_group, home_team, away_team),
                    "stage": "group",
                    "group": current_group,
                    "home_team": home_team,
                    "away_team": away_team,
                    "kickoff_utc": _utc_iso(2026, current_date[0], current_date[1], time_text, int(offset)),
                    "local_time": f"2026-{current_date[0]:02d}-{current_date[1]:02d} {time_text} UTC{int(offset):+d}",
                    "venue": " ".join(venue.split()),
                    "status": "played",
                    "result": [int(home_goals), int(away_goals)],
                }
            )
            continue
        match_match = match_line.match(raw_line)
        if match_match and current_group and current_date:
            time_text, offset, home, away, venue = match_match.groups()
            match_number = len(fixtures) + 1
            home_team = " ".join(home.split())
            away_team = " ".join(away.split())
            fixtures.append(
                {
                    "match_id": f"g{current_group.lower()}-{match_number:03d}",
                    "match_number": match_number,
                    "key": fixture_key(current_group, home_team, away_team),
                    "stage": "group",
                    "group": current_group,
                    "home_team": home_team,
                    "away_team": away_team,
                    "kickoff_utc": _utc_iso(2026, current_date[0], current_date[1], time_text, int(offset)),
                    "local_time": f"2026-{current_date[0]:02d}-{current_date[1]:02d} {time_text} UTC{int(offset):+d}",
                    "venue": " ".join(venue.split()),
                    "status": "scheduled",
                }
            )
    return {"groups": groups, "fixtures": fixtures}


def fetch_openfootball_text() -> str | None:
    try:
        with urllib.request.urlopen(OPENFOOTBALL_2026_URL, timeout=25) as response:
            return response.read().decode("utf-8")
    except OSError:
        return None


def load_fixture_payload() -> dict[str, Any]:
    return read_json(DATA_DIR / "fixtures.json", {"groups": {}, "fixtures": []})


def _load_manual_results() -> dict[str, dict[str, Any]]:
    payload = read_json(DATA_DIR / "manual_results.json", {})
    results = payload.get("results") if isinstance(payload, dict) else None
    out: dict[str, dict[str, Any]] = {}
    for match_id, value in (results or {}).items():
        if isinstance(value, list) and len(value) == 2:
            out[str(match_id)] = {"actual": [int(value[0]), int(value[1])], "penalty_winner": None}
        elif isinstance(value, Mapping) and value.get("actual"):
            actual = value["actual"]
            out[str(match_id)] = {
                "actual": [int(actual[0]), int(actual[1])],
                "penalty_winner": value.get("penalty_winner"),
            }
    return out


def _apply_manual_results(
    fixtures: list[dict[str, Any]],
    manual_results: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for fixture in fixtures:
        row = dict(fixture)
        result = manual_results.get(str(row.get("match_id")))
        if result and result.get("actual"):
            actual = result["actual"]
            row["status"] = "played"
            row["result"] = [int(actual[0]), int(actual[1])]
            if result.get("penalty_winner"):
                row["penalty_winner"] = result["penalty_winner"]
        merged.append(row)
    return merged


def _manual_knockout_result_placeholders(
    manual_results: Mapping[str, Mapping[str, Any]],
    existing_match_ids: set[str],
) -> list[dict[str, Any]]:
    from .knockout import KNOCKOUT_STAGE_BY_MATCH

    placeholders: list[dict[str, Any]] = []
    for match_id, result in manual_results.items():
        if match_id in existing_match_ids or not str(match_id).startswith("ko-"):
            continue
        if not result.get("actual"):
            continue
        try:
            match_number = int(str(match_id).split("-", 1)[1])
        except (IndexError, ValueError):
            continue
        placeholders.append(
            {
                "match_id": str(match_id),
                "match_number": match_number,
                "key": str(match_id),
                "stage": KNOCKOUT_STAGE_BY_MATCH.get(match_number, "knockout"),
                "status": "scheduled",
            }
        )
    return placeholders


def _with_knockout_fixtures(
    parsed: dict[str, Any],
    existing: dict[str, Any],
    *,
    manual_results: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from .knockout import resolve_knockout_fixtures

    parsed_fixtures = parsed.get("fixtures", [])
    group_fixtures = [
        fixture for fixture in parsed_fixtures if fixture.get("stage", "group") == "group"
    ]
    existing_knockout = [
        fixture
        for fixture in (existing.get("fixtures", []) + parsed_fixtures)
        if fixture.get("stage", "group") != "group"
    ]
    manual_results = _load_manual_results() if manual_results is None else manual_results
    existing_ids = {str(fixture.get("match_id")) for fixture in existing_knockout}
    existing_knockout.extend(_manual_knockout_result_placeholders(manual_results, existing_ids))
    existing_knockout = _apply_manual_results(existing_knockout, manual_results)
    resolved = resolve_knockout_fixtures(
        group_fixtures,
        existing_knockout_fixtures=existing_knockout,
    )
    parsed["fixtures"] = sorted(
        [*group_fixtures, *resolved["fixtures"]],
        key=lambda row: int(row.get("match_number") or 9999),
    )
    parsed["knockout_status"] = resolved["status"]
    return parsed


def refresh_fixtures(*, live: bool = True) -> dict[str, Any]:
    # T-0081: Plan waehrend des Turniers einfrieren. openfootball entfernt
    # gespielte Spiele aus cup.txt und unser Parser nummeriert die match_ids
    # neu (positionell) -> alle per match_id gekeyten Daten (Ergebnisse,
    # Tipps, History, Eval) wuerden verrutschen. Bei "pinned": true bleibt
    # der bestehende Plan unveraendert. Zum Loesen "pinned" auf false setzen.
    existing = load_fixture_payload()
    if existing.get("pinned"):
        return existing
    text = fetch_openfootball_text() if live else None
    if text:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / "openfootball_2026_cup.txt").write_text(text, encoding="utf-8")
        parsed = parse_openfootball_cup(text)
    else:
        parsed = load_fixture_payload()
    parsed = _with_knockout_fixtures(parsed, existing)
    parsed["updated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["source"] = OPENFOOTBALL_2026_URL if text else "local"
    write_json(DATA_DIR / "fixtures.json", parsed)
    return parsed


def all_teams(payload: dict[str, Any]) -> list[str]:
    teams = set()
    for group_teams in payload.get("groups", {}).values():
        teams.update(group_teams)
    for fixture in payload.get("fixtures", []):
        if fixture.get("has_pending_slot"):
            continue
        teams.add(fixture.get("home_team", ""))
        teams.add(fixture.get("away_team", ""))
    return sorted(team for team in teams if team and team != "unbekannt")
