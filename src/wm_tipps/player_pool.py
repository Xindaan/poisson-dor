from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .fixtures import all_teams, load_fixture_payload
from .paths import DATA_DIR, RAW_DIR


SOURCE_URL = "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"
SOURCE_NAME = "martj42/international_results goalscorers.csv"
LICENSE_URL = "https://raw.githubusercontent.com/martj42/international_results/master/LICENSE"
SINCE_DATE = "2024-01-01"

# CC0-Quelle nutzt teils andere Team-Namen als openfootball/Fixtures-Plan.
TEAM_ALIASES = {
    "United States": "USA",
    "Czechia": "Czech Republic",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Korea Republic": "South Korea",
    "DR Congo": "DR Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Czech Republic": "Czech Republic",
}
DISPLAY_TEAM_ALIASES = {
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "USA": "United States",
}
SCORER_ALIASES = {
    "Julián Álvarez": "Julián Alvarez",
    "Mohamed El Amine Amoura": "Mohamed Amoura",
}


def fetch_goalscorers(*, force: bool = False, timeout: int = 60) -> str:
    cache_path = RAW_DIR / "international_goalscorers.csv"
    if not force and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    with urllib.request.urlopen(SOURCE_URL, timeout=timeout) as response:
        text = response.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def parse_goalscorers(
    csv_text: str,
    fixture_teams: set[str],
    *,
    since: str = SINCE_DATE,
) -> dict[str, Counter]:
    counts, _, _, _ = parse_goalscorers_detailed(csv_text, fixture_teams, since=since)
    return counts


def parse_goalscorers_detailed(
    csv_text: str,
    fixture_teams: set[str],
    *,
    since: str = SINCE_DATE,
) -> tuple[dict[str, Counter], dict[tuple[str, str], set[str]], dict[str, int], tuple[str | None, str | None]]:
    grouped_counts: dict[str, Counter] = defaultdict(Counter)
    display_names: dict[tuple[str, str], str] = {}
    raw_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    source_aliases: dict[tuple[str, str], set[str]] = defaultdict(set)
    team_totals: dict[str, int] = defaultdict(int)
    all_dates: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        date = row.get("date") or ""
        if date:
            all_dates.append(date)
        if date < since:
            continue
        if str(row.get("own_goal", "")).strip().upper() == "TRUE":
            continue
        raw_team = (row.get("team") or "").strip()
        if not raw_team:
            continue
        team = TEAM_ALIASES.get(raw_team, raw_team)
        if team not in fixture_teams:
            continue
        scorer = (row.get("scorer") or "").strip()
        if not scorer:
            continue
        canonical_scorer = SCORER_ALIASES.get(scorer, scorer)
        scorer_key = scorer_group_key(canonical_scorer)
        grouped_counts[team][scorer_key] += 1
        raw_names[(team, scorer_key)].add(scorer)
        display_key = (team, scorer_key)
        current_display = display_names.get(display_key)
        if current_display is None or display_name_quality(canonical_scorer) > display_name_quality(current_display):
            display_names[display_key] = canonical_scorer
        team_totals[team] += 1
    counts: dict[str, Counter] = defaultdict(Counter)
    for team, scorer_counts in grouped_counts.items():
        for scorer_key, goals in scorer_counts.items():
            display = display_names[(team, scorer_key)]
            counts[team][display] = goals
            for raw_name in raw_names.get((team, scorer_key), set()):
                if raw_name != display:
                    source_aliases[(team, display)].add(raw_name)
    date_range = (min(all_dates), max(all_dates)) if all_dates else (None, None)
    return counts, source_aliases, team_totals, date_range


def scorer_group_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def display_name_quality(value: str) -> tuple[int, int]:
    non_ascii = sum(1 for char in value if ord(char) > 127)
    return (non_ascii, len(value))


def _name_token_set(name: str) -> frozenset[str]:
    tokens = {
        re.sub(r"[^a-z0-9]+", "", part)
        for part in scorer_group_key(name).split()
    }
    return frozenset(token for token in tokens if len(token) >= 3)


def load_position_role_overrides() -> dict[str, list[dict[str, Any]]]:
    """Manuell gepflegte position/role je Team-Spieler aus dem bestehenden
    player_pool.json -- damit ein CSV-Rebuild (T-0040-Daten von Codex aus
    Squad-Quellen) nicht ueberschrieben wird.
    """
    path = DATA_DIR / "player_pool.json"
    if not path.exists():
        return {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    overrides: dict[str, list[dict[str, Any]]] = {}
    for team, roster in (existing.get("players") or {}).items():
        for player in roster or []:
            if player.get("position") or player.get("role"):
                overrides.setdefault(team, []).append(player)
    return overrides


def _apply_overrides(team: str, name: str, overrides: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    tokens = _name_token_set(name)
    for prev in overrides.get(team, []):
        prev_tokens = _name_token_set(str(prev.get("name", "")))
        for alias in prev.get("source_aliases", []):
            prev_tokens = prev_tokens | _name_token_set(str(alias))
        if tokens & prev_tokens:
            carried = {}
            if prev.get("position"):
                carried["position"] = prev["position"]
            # Nur MANUELL gepflegte Rollen carryen; heuristische Rollen
            # (role_source == heuristic_v1) werden je Build neu berechnet.
            if prev.get("role") and prev.get("role_source") != HEURISTIC_ROLE_SOURCE:
                carried["role"] = prev["role"]
                if prev.get("role_source"):
                    carried["role_source"] = prev["role_source"]
            if prev.get("key_player"):
                carried["key_player"] = True
            return carried
    return {}


# T-0040-role: Transparente Rollen-Heuristik aus vorhandenen Pool-Signalen.
# WICHTIG: goal_share unter den Top-3-Torschuetzen ist KEIN zuverlaessiges
# Startelf-Signal -- niedrig-scorende Stammspieler (z.B. Lucas Paqueta,
# Gonzalo Plata, Che Adams) wuerden sonst faelschlich gedaempft. Deshalb
# Default starter und rotation nur bei eindeutig geringster Involvierung.
# Echte Lineup-/Minutendaten gehoeren als manuelle role (role_source !=
# heuristic_v1) gepflegt und gewinnen gegen die Heuristik.
HEURISTIC_ROLE_SOURCE = "heuristic_v1"
ROTATION_MAX_SHARE = 0.15
ROTATION_MAX_GOALS = 2


def _safe_share(player: dict[str, Any]) -> float:
    try:
        return float(player.get("goal_share") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _heuristic_role(player: dict[str, Any], rank: int) -> str:
    """Konservative Rollen-Projektion: starter als Default, rotation nur
    bei eindeutig geringster Involvierung. backup wird ohne echte
    Lineup-Daten nicht vergeben.
    """
    if player.get("key_player"):
        return "starter"
    if rank == 0:  # Team-Top-Scorer
        return "starter"
    try:
        goals = int(player.get("goals_since_2024") or 0)
    except (TypeError, ValueError):
        goals = 0
    if _safe_share(player) < ROTATION_MAX_SHARE and goals <= ROTATION_MAX_GOALS:
        return "rotation"
    return "starter"


def assign_heuristic_roles(players: dict[str, list[dict[str, Any]]]) -> None:
    """Setzt role + role_source fuer alle Pool-Spieler OHNE manuelle Rolle.
    Manuelle Rollen (role gesetzt, role_source != heuristic_v1) bleiben
    unangetastet. In place.
    """
    for roster in players.values():
        order = sorted(range(len(roster)), key=lambda i: -_safe_share(roster[i]))
        rank_of = {idx: rank for rank, idx in enumerate(order)}
        for idx, player in enumerate(roster):
            # Manuell gepflegte Rolle = role gesetzt mit role_source != heuristic_v1
            # (auch Legacy ohne role_source). Diese gewinnt gegen die Heuristik.
            has_manual_role = (
                bool(player.get("role"))
                and player.get("role_source") != HEURISTIC_ROLE_SOURCE
            )
            if has_manual_role:
                continue
            player["role"] = _heuristic_role(player, rank_of[idx])
            player["role_source"] = HEURISTIC_ROLE_SOURCE


def load_key_player_additions() -> dict[str, list[dict[str, Any]]]:
    """Manuell hinzugefuegte Schluesselspieler (Guardian-Stars ohne Top-3-
    Tore, goal_share 0) je Team -- damit ein CSV-Rebuild sie nicht verliert.
    """
    path = DATA_DIR / "player_pool.json"
    if not path.exists():
        return {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    additions: dict[str, list[dict[str, Any]]] = {}
    for team, roster in (existing.get("players") or {}).items():
        for player in roster or []:
            try:
                share = float(player.get("goal_share", 0.0))
            except (TypeError, ValueError):
                share = 0.0
            if player.get("key_player") and share == 0.0:
                additions.setdefault(team, []).append(player)
    return additions


def build_player_pool(
    *,
    force_fetch: bool = False,
    write: bool = True,
    fixture_payload: dict[str, Any] | None = None,
    csv_text: str | None = None,
    preserve_overrides: bool = True,
) -> dict[str, Any]:
    fixtures = fixture_payload if fixture_payload is not None else load_fixture_payload()
    fixture_teams = set(all_teams(fixtures))
    text = csv_text if csv_text is not None else fetch_goalscorers(force=force_fetch)
    counts, source_aliases, team_totals, source_date_range = parse_goalscorers_detailed(text, fixture_teams)
    overrides = load_position_role_overrides() if preserve_overrides else {}
    key_additions = load_key_player_additions() if preserve_overrides else {}
    players: dict[str, list[dict[str, Any]]] = {}
    for team in sorted(fixture_teams):
        top3 = sorted(counts[team].items(), key=lambda item: (-item[1], item[0]))[:3]
        if not top3:
            continue
        total = sum(goals for _, goals in top3) or 1
        rows: list[dict[str, Any]] = []
        share_sum = 0.0
        for index, (name, goals) in enumerate(top3):
            if index == len(top3) - 1:
                goal_share = round(max(0.0, 1.0 - share_sum), 4)
            else:
                goal_share = round(goals / total, 4)
                share_sum += goal_share
            row = {
                "name": name,
                "goal_share": goal_share,
                "goals_since_2024": goals,
                "note": (
                    f"{goals} von {total} Top-3-Toren seit 2024; "
                    f"Team gesamt: {team_totals.get(team, 0)}."
                ),
            }
            aliases = sorted(source_aliases.get((team, name), set()))
            if aliases:
                row["source_aliases"] = aliases
            row.update(_apply_overrides(team, name, overrides))
            rows.append(row)
        # Manuell hinzugefuegte Schluesselspieler (Guardian-Stars) wieder
        # anhaengen, falls sie nicht ohnehin unter den Top-3-Torschuetzen sind.
        present = set().union(*(_name_token_set(r["name"]) for r in rows)) if rows else set()
        for keyp in key_additions.get(team, []):
            if not (_name_token_set(str(keyp.get("name", ""))) & present):
                rows.append(dict(keyp))
        players[team] = rows
    # T-0040-role: Rollen heuristisch projizieren (manuelle Rollen gewinnen).
    assign_heuristic_roles(players)
    start_date, end_date = source_date_range
    payload = {
        "_meta": {
            "description": "Spielerdaten fuer Topscorer-Modell. Pro Team Top-3-Torschuetzen mit goal_share als Anteil an den Top-3-Toren des Teams in Nationalmannschafts-Spielen seit Anfang 2024.",
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "license": "CC0 1.0 Universal",
            "license_url": LICENSE_URL,
            "source_date_range": f"{start_date} bis {end_date}" if start_date and end_date else "unbekannt",
            "filter": "date >= 2024-01-01, team == WM-2026-Fixture-Team oder Alias, own_goal == FALSE, scorer vorhanden.",
            "method": "Spielernamen werden akzent-/reihenfolge-tolerant gruppiert; goal_share = goals(spieler, seit 2024) / sum(goals(top-3, seit 2024)).",
            "optional_fields": "position (ST/CF/FW/LW/RW/AM/MF/CM/DM/LM/RM/W oder GK/DF/CB/LB/RB/LWB/RWB/WB/SW) und role (starter/rotation/backup) je Spieler steuern das richtungssensitive News-Modell (T-0040). position manuell aus Squad-Quellen (Guardian Player-Guide, Wikipedia-Squads, FIFA-Squad) pflegen; Rebuild bewahrt sie via preserve_overrides.",
            "role_assignment": "T-0040-role: role wird je Build heuristisch projiziert (role_source=heuristic_v1) -- key_player/Top-Scorer/relevante Tore => starter, nur eindeutig geringste Involvierung (goal_share<0.15 und <=2 Tore, kein key_player/Top-Scorer) => rotation. KEINE echten Lineup-/Minutendaten: goal_share unter Top-3-Torschuetzen ist kein zuverlaessiges Startelf-Signal, deshalb konservativ. Echte Rollen als role mit role_source!=heuristic_v1 pflegen; die gewinnen und ueberleben den Rebuild.",
            "fallback": "Teams ohne Eintrag erhalten im Modell default_top_share=0.4; aktuelle Abdeckung hat keinen Fallback-Fall.",
            "coverage": f"{len(players)}/{len(fixture_teams)} Fixture-Teams mit mindestens einem Torschuetzen seit 2024.",
            "team_aliases": DISPLAY_TEAM_ALIASES,
            "scorer_aliases": SCORER_ALIASES,
            "updated_at": datetime.now(timezone.utc).date().isoformat(),
        },
        "players": players,
    }
    if write:
        write_player_pool(payload)
    return payload


def write_player_pool(payload: dict[str, Any]) -> None:
    path = DATA_DIR / "player_pool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
