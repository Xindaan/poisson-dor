"""Monte-Carlo-Simulation der K.o.-Phase.

Simuliert den Turnierbaum ab dem Sechzehntelfinale: je Paarung eine
Score-Matrix aus `model`, daraus Sieger (inkl. Verlaengerung und
Elfmeterschiessen), daraus die naechste Runde. Ergebnis sind
Fortkommens- und Titelwahrscheinlichkeiten je Team.

Bereits gespielte K.o.-Spiele werden als feststehend geseedet, statt
sie erneut zu simulieren -- sonst zaehlt die Realitaet doppelt.
Bracket-Struktur: `data/bracket_2026.json`.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .io import read_json
from .model import score_matrix
from .paths import DATA_DIR


DEFAULT_RATING = 1500.0
BASE_XG = 1.28
RATING_DIVISOR = 780.0
PENALTY_BIAS = 1 / 2000
BRACKET_PATH = DATA_DIR / "bracket_2026.json"
MANUAL_KNOCKOUT_SLOTS_PATH = DATA_DIR / "manual_knockout_slots.json"

KNOCKOUT_STAGE_BY_MATCH = {
    **{match_number: "round_of_32" for match_number in range(73, 89)},
    **{match_number: "round_of_16" for match_number in range(89, 97)},
    **{match_number: "quarter" for match_number in range(97, 101)},
    101: "semi",
    102: "semi",
    103: "third_place",
    104: "final",
}

KNOCKOUT_MATCH_SCHEDULE: dict[int, dict[str, str]] = {
    73: {"kickoff_utc": "2026-06-28T19:00:00+00:00", "local_time": "2026-06-28 12:00 UTC-7", "venue": "Los Angeles (Inglewood)"},
    74: {"kickoff_utc": "2026-06-29T20:30:00+00:00", "local_time": "2026-06-29 16:30 UTC-4", "venue": "Boston (Foxborough)"},
    75: {"kickoff_utc": "2026-06-30T01:00:00+00:00", "local_time": "2026-06-29 19:00 UTC-6", "venue": "Monterrey (Guadalupe)"},
    76: {"kickoff_utc": "2026-06-29T17:00:00+00:00", "local_time": "2026-06-29 12:00 UTC-5", "venue": "Houston"},
    77: {"kickoff_utc": "2026-06-30T21:00:00+00:00", "local_time": "2026-06-30 17:00 UTC-4", "venue": "New York/New Jersey (East Rutherford)"},
    78: {"kickoff_utc": "2026-06-30T17:00:00+00:00", "local_time": "2026-06-30 12:00 UTC-5", "venue": "Dallas (Arlington)"},
    79: {"kickoff_utc": "2026-07-01T01:00:00+00:00", "local_time": "2026-06-30 19:00 UTC-6", "venue": "Mexico City"},
    80: {"kickoff_utc": "2026-07-01T16:00:00+00:00", "local_time": "2026-07-01 12:00 UTC-4", "venue": "Atlanta"},
    81: {"kickoff_utc": "2026-07-02T00:00:00+00:00", "local_time": "2026-07-01 17:00 UTC-7", "venue": "San Francisco Bay Area (Santa Clara)"},
    82: {"kickoff_utc": "2026-07-01T20:00:00+00:00", "local_time": "2026-07-01 13:00 UTC-7", "venue": "Seattle"},
    83: {"kickoff_utc": "2026-07-02T23:00:00+00:00", "local_time": "2026-07-02 19:00 UTC-4", "venue": "Toronto"},
    84: {"kickoff_utc": "2026-07-02T19:00:00+00:00", "local_time": "2026-07-02 12:00 UTC-7", "venue": "Los Angeles (Inglewood)"},
    85: {"kickoff_utc": "2026-07-03T03:00:00+00:00", "local_time": "2026-07-02 20:00 UTC-7", "venue": "Vancouver"},
    86: {"kickoff_utc": "2026-07-03T22:00:00+00:00", "local_time": "2026-07-03 18:00 UTC-4", "venue": "Miami (Miami Gardens)"},
    87: {"kickoff_utc": "2026-07-04T01:30:00+00:00", "local_time": "2026-07-03 20:30 UTC-5", "venue": "Kansas City"},
    88: {"kickoff_utc": "2026-07-03T18:00:00+00:00", "local_time": "2026-07-03 13:00 UTC-5", "venue": "Dallas (Arlington)"},
    89: {"kickoff_utc": "2026-07-04T21:00:00+00:00", "local_time": "2026-07-04 17:00 UTC-4", "venue": "Philadelphia"},
    90: {"kickoff_utc": "2026-07-04T17:00:00+00:00", "local_time": "2026-07-04 12:00 UTC-5", "venue": "Houston"},
    91: {"kickoff_utc": "2026-07-05T20:00:00+00:00", "local_time": "2026-07-05 16:00 UTC-4", "venue": "New York/New Jersey (East Rutherford)"},
    92: {"kickoff_utc": "2026-07-06T00:00:00+00:00", "local_time": "2026-07-05 18:00 UTC-6", "venue": "Mexico City"},
    93: {"kickoff_utc": "2026-07-06T19:00:00+00:00", "local_time": "2026-07-06 14:00 UTC-5", "venue": "Dallas (Arlington)"},
    94: {"kickoff_utc": "2026-07-07T00:00:00+00:00", "local_time": "2026-07-06 17:00 UTC-7", "venue": "Seattle"},
    95: {"kickoff_utc": "2026-07-07T16:00:00+00:00", "local_time": "2026-07-07 12:00 UTC-4", "venue": "Atlanta"},
    96: {"kickoff_utc": "2026-07-07T20:00:00+00:00", "local_time": "2026-07-07 13:00 UTC-7", "venue": "Vancouver"},
    97: {"kickoff_utc": "2026-07-09T20:00:00+00:00", "local_time": "2026-07-09 16:00 UTC-4", "venue": "Boston (Foxborough)"},
    98: {"kickoff_utc": "2026-07-10T19:00:00+00:00", "local_time": "2026-07-10 12:00 UTC-7", "venue": "Los Angeles (Inglewood)"},
    99: {"kickoff_utc": "2026-07-11T21:00:00+00:00", "local_time": "2026-07-11 17:00 UTC-4", "venue": "Miami (Miami Gardens)"},
    100: {"kickoff_utc": "2026-07-12T01:00:00+00:00", "local_time": "2026-07-11 20:00 UTC-5", "venue": "Kansas City"},
    101: {"kickoff_utc": "2026-07-14T19:00:00+00:00", "local_time": "2026-07-14 14:00 UTC-5", "venue": "Dallas (Arlington)"},
    102: {"kickoff_utc": "2026-07-15T19:00:00+00:00", "local_time": "2026-07-15 15:00 UTC-4", "venue": "Atlanta"},
    103: {"kickoff_utc": "2026-07-18T21:00:00+00:00", "local_time": "2026-07-18 17:00 UTC-4", "venue": "Miami (Miami Gardens)"},
    104: {"kickoff_utc": "2026-07-19T19:00:00+00:00", "local_time": "2026-07-19 15:00 UTC-4", "venue": "New York/New Jersey (East Rutherford)"},
}


def _round_label(remaining: int) -> str:
    if remaining == 1:
        return "champion"
    if remaining == 2:
        return "final"
    if remaining == 4:
        return "semi"
    if remaining == 8:
        return "quarter"
    return f"round_of_{remaining}"


def _is_power_of_two(value: int) -> bool:
    return value >= 2 and (value & (value - 1)) == 0


def _rating(team: str, strengths: Mapping[str, Mapping[str, Any]]) -> float:
    try:
        return float(strengths.get(team, {}).get("elo", DEFAULT_RATING))
    except (TypeError, ValueError):
        return DEFAULT_RATING


def _standing_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(row.get("points", 0) or 0),
        -(int(row.get("gf", 0) or 0) - int(row.get("ga", 0) or 0)),
        -int(row.get("gf", 0) or 0),
        str(row.get("team", "")),
    )


def _add_pending(pending: list[dict[str, Any]], match_number: int, reason: str, **extra: Any) -> None:
    row = {"match_number": match_number, "reason": reason}
    row.update(extra)
    pending.append(row)


def _sample_score(matrix: Mapping[str, float], rng: random.Random) -> tuple[int, int]:
    threshold = rng.random()
    cumulative = 0.0
    last_label = next(iter(matrix))
    for label, probability in matrix.items():
        cumulative += probability
        last_label = label
        if threshold <= cumulative:
            break
    home_goals, away_goals = (int(part) for part in last_label.split(":"))
    return home_goals, away_goals


def knockout_feeds() -> dict[int, tuple[int, int]]:
    """match_number -> (home_from, away_from). Nur Runden ab dem Achtelfinale.

    Aus dem Bracket-JSON gelesen (nicht dupliziert), damit eine Bracket-Aenderung
    nicht still auseinanderlaeuft.
    """
    feeds: dict[int, tuple[int, int]] = {}
    for entry in load_2026_bracket().get("rounds", []):
        for match in (entry or {}).get("matches", []):
            if "home_from" in match and "away_from" in match:
                feeds[int(match["match_number"])] = (int(match["home_from"]), int(match["away_from"]))
    return feeds


def matchup_xg(
    home: str,
    away: str,
    strengths: Mapping[str, Mapping[str, Any]],
) -> tuple[float, float]:
    """Erwartete Tore einer beliebigen Paarung aus den Team-Staerken (Elo-Proxy).

    Fuer Spiele, die noch kein Fixture/keine Prediction haben (simulierte K.o.-Runden).
    """
    diff = _rating(home, strengths) - _rating(away, strengths)
    return BASE_XG * math.exp(diff / RATING_DIVISOR), BASE_XG * math.exp(-diff / RATING_DIVISOR)


def simulate_match(
    home: str,
    away: str,
    strengths: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> str:
    diff = _rating(home, strengths) - _rating(away, strengths)
    home_xg, away_xg = matchup_xg(home, away, strengths)
    matrix = score_matrix(home_xg, away_xg)
    home_goals, away_goals = _sample_score(matrix, rng)
    if home_goals > away_goals:
        return home
    if away_goals > home_goals:
        return away
    # Remis: Penalty-Proxy mit Elo-Bias, geclampt damit Underdogs nicht
    # auf 0% fallen.
    p_home = max(0.1, min(0.9, 0.5 + diff * PENALTY_BIAS))
    return home if rng.random() < p_home else away


def simulate_bracket(
    qualified_teams: list[str],
    strengths: Mapping[str, Mapping[str, Any]],
    *,
    n_simulations: int = 20000,
    seed: int | None = 42,
) -> dict[str, dict[str, float]]:
    n = len(qualified_teams)
    if not _is_power_of_two(n):
        raise ValueError(
            f"qualified_teams muss Potenz von 2 sein und >= 2, ist aber {n}."
        )
    rng = random.Random(seed)
    rounds: list[int] = []
    size = n
    while size >= 1:
        rounds.append(size)
        size //= 2
    counts: dict[int, dict[str, int]] = {
        round_size: {team: 0 for team in qualified_teams} for round_size in rounds
    }

    for _ in range(n_simulations):
        bracket = list(qualified_teams)
        rng.shuffle(bracket)
        active = bracket
        for team in active:
            counts[len(active)][team] += 1
        while len(active) > 1:
            next_active: list[str] = []
            for index in range(0, len(active), 2):
                winner = simulate_match(active[index], active[index + 1], strengths, rng)
                next_active.append(winner)
            active = next_active
            for team in active:
                counts[len(active)][team] += 1

    result: dict[str, dict[str, float]] = {}
    for round_size in rounds:
        label = _round_label(round_size)
        result[label] = {
            team: round(count / n_simulations, 4)
            for team, count in counts[round_size].items()
        }
    return result


def _xg_for(home: str, away: str, strengths: Mapping[str, Mapping[str, Any]]) -> tuple[float, float]:
    diff = _rating(home, strengths) - _rating(away, strengths)
    return BASE_XG * math.exp(diff / RATING_DIVISOR), BASE_XG * math.exp(-diff / RATING_DIVISOR)


def simulate_group_stage(
    group_fixtures: Mapping[str, list[Mapping[str, Any]]],
    strengths: Mapping[str, Mapping[str, Any]],
    rng: random.Random,
) -> dict[str, list[dict[str, Any]]]:
    """Spielt fuer jede Gruppe ihre Vorrundenspiele durch, liefert Standings.

    Tiebreaker: Punkte desc -> Tordifferenz desc -> Tore desc -> Team-Name asc.
    Head-to-head ist bewusst nicht implementiert (Edge-Case selten, Sample-Skip
    durch deterministischen Name-Tiebreak ist OK fuer ~5000 Sims).
    """
    standings: dict[str, list[dict[str, Any]]] = {}
    for group_letter, fixtures in group_fixtures.items():
        teams_in_group: set[str] = set()
        for fixture in fixtures:
            teams_in_group.add(fixture.get("home_team", ""))
            teams_in_group.add(fixture.get("away_team", ""))
        stats = {
            team: {
                "team": team,
                "group": group_letter,
                "points": 0,
                "gf": 0,
                "ga": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
            }
            for team in teams_in_group
            if team
        }
        for fixture in fixtures:
            home = fixture.get("home_team", "")
            away = fixture.get("away_team", "")
            if not home or not away:
                continue
            home_xg, away_xg = _xg_for(home, away, strengths)
            matrix = score_matrix(home_xg, away_xg)
            h_goals, a_goals = _sample_score(matrix, rng)
            stats[home]["gf"] += h_goals
            stats[home]["ga"] += a_goals
            stats[away]["gf"] += a_goals
            stats[away]["ga"] += h_goals
            if h_goals > a_goals:
                stats[home]["points"] += 3
                stats[home]["wins"] += 1
                stats[away]["losses"] += 1
            elif a_goals > h_goals:
                stats[away]["points"] += 3
                stats[away]["wins"] += 1
                stats[home]["losses"] += 1
            else:
                stats[home]["points"] += 1
                stats[away]["points"] += 1
                stats[home]["draws"] += 1
                stats[away]["draws"] += 1
        ranked = sorted(stats.values(), key=_standing_sort_key)
        standings[group_letter] = ranked
    return standings


def qualified_from_standings(standings: Mapping[str, list[Mapping[str, Any]]]) -> list[str]:
    """Top-2 jeder Gruppe + 8 beste Drittplatzierte = 32 Teams fuer Round of 32.

    Reihenfolge: erst alle Top-1 (Gruppe A bis L), dann alle Top-2,
    dann die 8 besten Dritten -- liefert determinitisch fuer Tests.
    """
    top1: list[str] = []
    top2: list[str] = []
    thirds: list[Mapping[str, Any]] = []
    for _, ranked in sorted(standings.items()):
        if len(ranked) >= 1:
            top1.append(ranked[0]["team"])
        if len(ranked) >= 2:
            top2.append(ranked[1]["team"])
        if len(ranked) >= 3:
            thirds.append(ranked[2])
    thirds_sorted = sorted(thirds, key=_standing_sort_key)
    best_thirds = [r["team"] for r in thirds_sorted[:8]]
    return top1 + top2 + best_thirds


def group_standings_from_results(
    fixtures: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Berechnet Gruppentabellen aus echten Resultaten.

    Lokal entscheidbar sind Punkte, Tordifferenz und erzielte Tore. Wenn danach
    ein Gleichstand bleibt, markieren wir die Gruppe als manuell zu klaeren,
    statt daraus KO-Fixtures als sichere Wahrheit abzuleiten.
    """
    stats_by_group: dict[str, dict[str, dict[str, Any]]] = {}
    fixture_count_by_group: dict[str, int] = defaultdict(int)
    played_count_by_group: dict[str, int] = defaultdict(int)
    for fixture in fixtures:
        if fixture.get("stage") != "group" or not fixture.get("group"):
            continue
        group = str(fixture["group"])
        fixture_count_by_group[group] += 1
        stats_by_group.setdefault(group, {})
        for team in (fixture.get("home_team"), fixture.get("away_team")):
            if not team:
                continue
            stats_by_group[group].setdefault(
                str(team),
                {
                    "team": str(team),
                    "group": group,
                    "points": 0,
                    "gf": 0,
                    "ga": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "played": 0,
                    "tiebreak_status": "decided",
                },
            )
        if fixture.get("status") != "played" or not fixture.get("result"):
            continue
        home = str(fixture.get("home_team") or "")
        away = str(fixture.get("away_team") or "")
        if not home or not away:
            continue
        try:
            home_goals = int(fixture["result"][0])
            away_goals = int(fixture["result"][1])
        except (TypeError, ValueError, IndexError):
            continue
        played_count_by_group[group] += 1
        stats_by_group[group][home]["played"] += 1
        stats_by_group[group][away]["played"] += 1
        stats_by_group[group][home]["gf"] += home_goals
        stats_by_group[group][home]["ga"] += away_goals
        stats_by_group[group][away]["gf"] += away_goals
        stats_by_group[group][away]["ga"] += home_goals
        if home_goals > away_goals:
            stats_by_group[group][home]["points"] += 3
            stats_by_group[group][home]["wins"] += 1
            stats_by_group[group][away]["losses"] += 1
        elif away_goals > home_goals:
            stats_by_group[group][away]["points"] += 3
            stats_by_group[group][away]["wins"] += 1
            stats_by_group[group][home]["losses"] += 1
        else:
            stats_by_group[group][home]["points"] += 1
            stats_by_group[group][away]["points"] += 1
            stats_by_group[group][home]["draws"] += 1
            stats_by_group[group][away]["draws"] += 1

    standings: dict[str, list[dict[str, Any]]] = {}
    unresolved_tiebreaks: list[dict[str, Any]] = []
    for group, rows_by_team in sorted(stats_by_group.items()):
        rows = sorted(rows_by_team.values(), key=_standing_sort_key)
        buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[
                (
                    int(row.get("points", 0) or 0),
                    int(row.get("gf", 0) or 0) - int(row.get("ga", 0) or 0),
                    int(row.get("gf", 0) or 0),
                )
            ].append(row)
        for tied_rows in buckets.values():
            if len(tied_rows) <= 1:
                continue
            positions = [rows.index(row) + 1 for row in tied_rows]
            teams = [str(row["team"]) for row in tied_rows]
            for row in tied_rows:
                row["tiebreak_status"] = "manual_required"
            unresolved_tiebreaks.append(
                {"group": group, "teams": teams, "positions": positions}
            )
        standings[group] = rows

    complete_groups = [
        group
        for group in sorted(stats_by_group)
        if fixture_count_by_group.get(group) >= 6
        and played_count_by_group.get(group) >= fixture_count_by_group.get(group)
    ]
    open_groups = [group for group in sorted(stats_by_group) if group not in complete_groups]
    return {
        "standings": standings,
        "complete_groups": complete_groups,
        "open_groups": open_groups,
        "unresolved_tiebreaks": unresolved_tiebreaks,
    }


def load_2026_bracket() -> dict[str, Any]:
    payload = read_json(BRACKET_PATH, {})
    if not isinstance(payload, dict):
        raise ValueError(f"{BRACKET_PATH} enthaelt kein JSON-Objekt.")
    return payload


def _manual_knockout_slots(
    payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    raw_payload = read_json(MANUAL_KNOCKOUT_SLOTS_PATH, {}) if payload is None else payload
    if not isinstance(raw_payload, Mapping):
        return {}, {}

    raw_slots = raw_payload.get("slots", raw_payload)
    if not isinstance(raw_slots, Mapping):
        return {}, {}

    slots: dict[str, str] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for raw_slot, raw_entry in raw_slots.items():
        slot = str(raw_slot).strip()
        if isinstance(raw_entry, Mapping):
            team = str(raw_entry.get("team") or "").strip()
            entry = {str(key): value for key, value in raw_entry.items()}
        else:
            team = str(raw_entry or "").strip()
            entry = {"team": team}
        if not slot or not team:
            continue
        entry["team"] = team
        slots[slot] = team
        metadata[slot] = entry
    return slots, metadata


def _position_map(
    standings: Mapping[str, list[Mapping[str, Any]]]
) -> tuple[dict[str, str], str]:
    positions: dict[str, str] = {}
    thirds: list[Mapping[str, Any]] = []
    # K.o.-Fixtures haben group=None und gehoeren nicht in die Gruppenphasen-Positionierung
    for group_letter, ranked in sorted(
        item for item in standings.items() if item[0] is not None
    ):
        for index, row in enumerate(ranked[:3], start=1):
            team = str(row.get("team", ""))
            if team:
                positions[f"{index}{group_letter}"] = team
        if len(ranked) >= 3:
            thirds.append(ranked[2])
    best_thirds = sorted(thirds, key=_standing_sort_key)[:8]
    qualified_third_groups = "".join(sorted(str(row.get("group", "")) for row in best_thirds))
    return positions, qualified_third_groups


def _third_assignment(
    bracket_payload: Mapping[str, Any], qualified_third_groups: str
) -> Mapping[str, str]:
    assignment = bracket_payload.get("third_place_assignment", {})
    combinations = assignment.get("combinations", []) if isinstance(assignment, Mapping) else []
    for row in combinations:
        if row.get("qualified_groups") == qualified_third_groups:
            slots = row.get("slots", {})
            if isinstance(slots, Mapping):
                return slots
    raise ValueError(
        "Keine FIFA-2026-Drittplatzierten-Zuordnung fuer Gruppen "
        f"{qualified_third_groups or '<leer>'} gefunden."
    )


def round_of_32_matchups(
    standings: Mapping[str, list[Mapping[str, Any]]],
    bracket_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Loest die echten FIFA-2026-Round-of-32-Slots aus Gruppenstandings auf."""
    bracket = bracket_payload or load_2026_bracket()
    positions, qualified_third_groups = _position_map(standings)
    third_slots = _third_assignment(bracket, qualified_third_groups)
    matchups: list[dict[str, Any]] = []
    for match in bracket.get("round_of_32", []):
        match_number = int(match["match_number"])
        home_slot = str(match["home_slot"])
        away_slot = str(match.get("away_slot") or "")
        third_place_column = match.get("third_place_column")
        if third_place_column:
            away_slot = str(third_slots[str(third_place_column)])
            pool = set(str(match.get("third_place_pool", "")))
            if away_slot[1:] not in pool:
                raise ValueError(
                    f"M{match_number}: Slot {away_slot} passt nicht zum Pool "
                    f"{''.join(sorted(pool))}."
                )
        home = positions.get(home_slot)
        away = positions.get(away_slot)
        if not home or not away:
            raise ValueError(
                f"M{match_number}: Slot-Aufloesung fehlgeschlagen "
                f"({home_slot}={home}, {away_slot}={away})."
            )
        if home_slot[1:] == away_slot[1:]:
            raise ValueError(
                f"M{match_number}: Teams aus Gruppe {home_slot[1:]} "
                "treffen direkt aufeinander."
            )
        matchups.append(
            {
                "match_number": match_number,
                "home_slot": home_slot,
                "away_slot": away_slot,
                "home": home,
                "away": away,
                "qualified_third_groups": qualified_third_groups,
            }
        )
    return sorted(matchups, key=lambda item: item["match_number"])


def _slot_group(slot: str) -> str:
    return slot[1:] if len(slot) >= 2 else ""


def _positions_for_completed_groups(
    standings_payload: Mapping[str, Any],
) -> tuple[dict[str, str], set[str]]:
    standings = standings_payload.get("standings", {})
    complete_groups = set(standings_payload.get("complete_groups", []))
    unresolved_groups = {
        str(row.get("group"))
        for row in standings_payload.get("unresolved_tiebreaks", [])
    }
    positions: dict[str, str] = {}
    for group_letter, ranked in sorted(standings.items()):
        if group_letter not in complete_groups or group_letter in unresolved_groups:
            continue
        for index, row in enumerate(ranked[:3], start=1):
            team = str(row.get("team", ""))
            if team:
                positions[f"{index}{group_letter}"] = team
    return positions, unresolved_groups


def _third_slots_if_decided(
    bracket_payload: Mapping[str, Any],
    standings_payload: Mapping[str, Any],
) -> tuple[Mapping[str, str] | None, str | None]:
    standings = standings_payload.get("standings", {})
    if standings_payload.get("open_groups"):
        return None, None
    if standings_payload.get("unresolved_tiebreaks"):
        return None, None
    thirds: list[Mapping[str, Any]] = []
    for ranked in standings.values():
        if len(ranked) >= 3:
            thirds.append(ranked[2])
    if len(thirds) < 12:
        return None, None
    thirds_sorted = sorted(thirds, key=_standing_sort_key)
    boundary_key = lambda row: (
        int(row.get("points", 0) or 0),
        int(row.get("gf", 0) or 0) - int(row.get("ga", 0) or 0),
        int(row.get("gf", 0) or 0),
    )
    if boundary_key(thirds_sorted[7]) == boundary_key(thirds_sorted[8]):
        return None, None
    best_thirds = thirds_sorted[:8]
    qualified_third_groups = "".join(sorted(str(row.get("group", "")) for row in best_thirds))
    return _third_assignment(bracket_payload, qualified_third_groups), qualified_third_groups


def _third_rank_key(row: Mapping[str, Any]) -> tuple[int, int, int]:
    return (
        int(row.get("points", 0) or 0),
        int(row.get("gf", 0) or 0) - int(row.get("ga", 0) or 0),
        int(row.get("gf", 0) or 0),
    )


def _third_slot_candidates(
    bracket_payload: Mapping[str, Any],
    standings_payload: Mapping[str, Any],
) -> dict[str, set[str]]:
    """Moegliche Drittplatzierten-Slots je FIFA-Spalte.

    Noch offene Gruppen bleiben optional. Komplett gespielte Gruppendritte,
    die selbst im schlechtesten Fall Top-8 bleiben, werden als Pflichtgruppen
    behandelt; komplett gespielte Gruppendritte mit schon acht besseren
    abgeschlossenen Drittplatzierten sind ausgeschlossen. Dadurch koennen
    einzelne Annexe-C-Spalten schon vor Abschluss aller Gruppen sicher werden.
    """
    assignment = bracket_payload.get("third_place_assignment", {})
    combinations = assignment.get("combinations", []) if isinstance(assignment, Mapping) else []
    columns = assignment.get("columns", []) if isinstance(assignment, Mapping) else []
    standings = standings_payload.get("standings", {})
    complete_groups = set(standings_payload.get("complete_groups", []))
    if standings_payload.get("unresolved_tiebreaks"):
        return {str(column): set() for column in columns}

    complete_thirds = [
        ranked[2]
        for group, ranked in standings.items()
        if group in complete_groups and len(ranked) >= 3
    ]
    open_groups = set(standings_payload.get("open_groups", []))
    required: set[str] = set()
    excluded: set[str] = set()
    for row in complete_thirds:
        group = str(row.get("group", ""))
        better_completed = [
            other
            for other in complete_thirds
            if _third_rank_key(other) > _third_rank_key(row)
        ]
        if len(better_completed) + len(open_groups) <= 7:
            required.add(group)
        if len(better_completed) >= 8:
            excluded.add(group)

    candidates = [
        row
        for row in combinations
        if required <= set(str(row.get("qualified_groups", "")))
        and not (excluded & set(str(row.get("qualified_groups", ""))))
    ]
    return {
        str(column): {
            str((row.get("slots") or {}).get(str(column)))
            for row in candidates
            if isinstance(row.get("slots"), Mapping) and (row.get("slots") or {}).get(str(column))
        }
        for column in columns
    }


def _knockout_fixture(
    match_number: int,
    home: str,
    away: str,
    *,
    home_slot: str | None = None,
    away_slot: str | None = None,
    source: str = "fifa_bracket",
    existing: Mapping[str, Any] | None = None,
    pending_slots: list[str] | None = None,
    pending_reason: str | None = None,
) -> dict[str, Any]:
    schedule = KNOCKOUT_MATCH_SCHEDULE.get(match_number, {})
    has_pending_slot = bool(pending_slots)
    fixture = {
        "match_id": f"ko-{match_number:03d}",
        "match_number": match_number,
        "key": f"ko-{match_number:03d}",
        "stage": KNOCKOUT_STAGE_BY_MATCH.get(match_number, "knockout"),
        "group": None,
        "home_team": home,
        "away_team": away,
        "home_slot": home_slot,
        "away_slot": away_slot,
        "kickoff_utc": schedule.get("kickoff_utc"),
        "local_time": schedule.get("local_time"),
        "venue": schedule.get("venue"),
        "status": "slot_pending" if has_pending_slot else "scheduled",
        "source": source,
        "has_pending_slot": has_pending_slot,
        "pending_slots": pending_slots or [],
    }
    if pending_reason:
        fixture["pending_reason"] = pending_reason
    if existing and not has_pending_slot:
        for key in ("status", "result", "penalty_winner", "notes"):
            if key in existing:
                if key == "status" and existing[key] == "slot_pending":
                    continue
                fixture[key] = existing[key]
    return fixture


def _winner_loser(fixture: Mapping[str, Any]) -> tuple[str | None, str | None]:
    result = fixture.get("result")
    if not isinstance(result, (list, tuple)) or len(result) < 2:
        return None, None
    home = str(fixture.get("home_team") or "")
    away = str(fixture.get("away_team") or "")
    if not home or not away:
        return None, None
    try:
        home_goals = int(result[0])
        away_goals = int(result[1])
    except (TypeError, ValueError):
        return None, None
    if home_goals > away_goals:
        return home, away
    if away_goals > home_goals:
        return away, home
    penalty_winner = fixture.get("penalty_winner")
    if penalty_winner == "home":
        return home, away
    if penalty_winner == "away":
        return away, home
    return None, None


def match_winner(fixture: Mapping[str, Any]) -> str | None:
    """Sieger eines gespielten K.o.-Spiels (Elfmeter beruecksichtigt), sonst None.

    Duenner oeffentlicher Zugang zu ``_winner_loser`` -- damit Aufrufer die Sieger-
    Logik nicht ein zweites Mal implementieren (Drift-Risiko, vgl. T-0138).
    """
    return _winner_loser(fixture)[0]


def match_loser(fixture: Mapping[str, Any]) -> str | None:
    """Verlierer eines gespielten K.o.-Spiels mit derselben Aufloesungslogik."""
    return _winner_loser(fixture)[1]


def knockout_round_sizes() -> dict[str, int]:
    """Erwartete Spielzahl je K.o.-Runde, aus dem Bracket abgeleitet."""
    sizes: dict[str, int] = {}
    for match_number in sorted(KNOCKOUT_STAGE_BY_MATCH):
        stage = KNOCKOUT_STAGE_BY_MATCH[match_number]
        sizes[stage] = sizes.get(stage, 0) + 1
    return sizes


def knockout_results_freshness(
    fixtures: list[Mapping[str, Any]],
    manual_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Ist der K.o.-Bracket auf dem Stand seiner Ergebnis-Quellen? (T-0137)

    Zwei stille Fehlmodi, die je ein Folgespiel verschwinden lassen:

    - ``stale_results``: ein ``ko-*``-Ergebnis liegt in ``manual_results.json``,
      das Fixture ist aber nicht ``played`` -> Artefakt aelter als seine Quelle.
    - ``unresolved_ties``: ein K.o.-Remis ist ``played``, hat aber keinen
      ``penalty_winner`` -> ``_winner_loser`` liefert keinen Sieger.

    Eine nur teilweise gefuellte Runde ist fuer sich KEIN Fehler (ein
    Feeder-Spiel kann schlicht noch nicht angepfiffen sein) und wird nur
    informativ unter ``stages`` gemeldet.
    """
    ko_fixtures = [
        fixture
        for fixture in fixtures
        if str(fixture.get("match_id") or "").startswith("ko-")
    ]
    by_id = {str(fixture.get("match_id")): fixture for fixture in ko_fixtures}

    stale_results: list[dict[str, Any]] = []
    for match_id in sorted(manual_results):
        if not str(match_id).startswith("ko-"):
            continue
        actual = (manual_results[match_id] or {}).get("actual")
        if not actual:
            continue
        fixture = by_id.get(str(match_id))
        if fixture is not None and fixture.get("status") == "played":
            continue
        stale_results.append(
            {
                "match_id": str(match_id),
                "manual_result": [int(actual[0]), int(actual[1])],
                "reason": "fixture_missing" if fixture is None else "not_played",
            }
        )

    unresolved_ties: list[dict[str, Any]] = []
    for fixture in ko_fixtures:
        if fixture.get("status") != "played":
            continue
        result = fixture.get("result")
        if not isinstance(result, (list, tuple)) or len(result) < 2:
            continue
        try:
            home_goals = int(result[0])
            away_goals = int(result[1])
        except (TypeError, ValueError):
            continue
        if home_goals != away_goals:
            continue
        if fixture.get("penalty_winner") in {"home", "away"}:
            continue
        unresolved_ties.append(
            {
                "match_id": str(fixture.get("match_id")),
                "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                "result": [home_goals, away_goals],
            }
        )

    present: dict[str, int] = {}
    for fixture in ko_fixtures:
        stage = str(fixture.get("stage") or "knockout")
        present[stage] = present.get(stage, 0) + 1
    stages = [
        {
            "stage": stage,
            "present": present.get(stage, 0),
            "expected": expected,
            "partial": 0 < present.get(stage, 0) < expected,
        }
        for stage, expected in knockout_round_sizes().items()
    ]

    parts: list[str] = []
    if stale_results:
        ids = ", ".join(row["match_id"] for row in stale_results)
        parts.append(
            f"{len(stale_results)} K.o.-Ergebnis(se) aus manual_results.json fehlen in "
            f"fixtures.json ({ids}); refresh-fixtures laufen lassen, sonst bleibt die "
            "Folgerunde ein Spiel zu kurz."
        )
    if unresolved_ties:
        ids = ", ".join(row["match_id"] for row in unresolved_ties)
        parts.append(
            f"{len(unresolved_ties)} K.o.-Remis ohne penalty_winner ({ids}); Sieger nicht "
            "aufloesbar, das Folgespiel entfaellt still."
        )
    status = "failed" if parts else "ok"
    if not parts:
        played = sum(1 for fixture in ko_fixtures if fixture.get("status") == "played")
        parts.append(f"K.o.-Bracket konsistent ({played} gespielte K.o.-Spiele).")
    return {
        "status": status,
        "status_detail": " ".join(parts),
        "stale_results": stale_results,
        "unresolved_ties": unresolved_ties,
        "stages": stages,
    }


def resolve_knockout_fixtures(
    group_fixtures: list[Mapping[str, Any]],
    *,
    existing_knockout_fixtures: list[Mapping[str, Any]] | None = None,
    bracket_payload: Mapping[str, Any] | None = None,
    manual_slots: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    bracket = bracket_payload or load_2026_bracket()
    existing_by_number = {
        int(fixture.get("match_number")): fixture
        for fixture in (existing_knockout_fixtures or [])
        if fixture.get("match_number") is not None
    }
    standings_payload = group_standings_from_results(group_fixtures)
    positions, unresolved_groups = _positions_for_completed_groups(standings_payload)
    manual_positions, manual_slot_metadata = _manual_knockout_slots(manual_slots)
    applied_manual_slots: dict[str, dict[str, Any]] = {}
    manual_slot_conflicts: list[dict[str, Any]] = []
    for slot, team in sorted(manual_positions.items()):
        computed_team = positions.get(slot)
        if computed_team and computed_team != team:
            manual_slot_conflicts.append(
                {
                    "slot": slot,
                    "manual_team": team,
                    "computed_team": computed_team,
                    "metadata": manual_slot_metadata.get(slot, {}),
                }
            )
            continue
        if not computed_team:
            positions[slot] = team
            applied_manual_slots[slot] = manual_slot_metadata.get(slot, {"team": team})
    third_slots, qualified_third_groups = _third_slots_if_decided(bracket, standings_payload)
    third_slot_candidates = _third_slot_candidates(bracket, standings_payload)
    fixtures_by_number: dict[int, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []

    for match in bracket.get("round_of_32", []):
        match_number = int(match["match_number"])
        home_slot = str(match["home_slot"])
        away_slot = str(match.get("away_slot") or "")
        pending_reason = "slot_pending"
        if match.get("third_place_column"):
            third_place_column = str(match["third_place_column"])
            if third_slots is None:
                candidates = third_slot_candidates.get(third_place_column, set())
                pending_reason = "third_assignment_pending"
                if len(candidates) == 1:
                    away_slot = next(iter(candidates))
                else:
                    away_slot = ""
                    _add_pending(
                        pending,
                        match_number,
                        pending_reason,
                        home_slot=home_slot,
                        third_place_column=third_place_column,
                        third_place_candidates=sorted(candidates),
                        open_groups=standings_payload.get("open_groups", []),
                        unresolved_groups=sorted(unresolved_groups),
                    )
            else:
                away_slot = str(third_slots[third_place_column])
        home = positions.get(home_slot)
        away = positions.get(away_slot)
        away_pending_slot = away_slot or str(match.get("third_place_column") or "unknown")
        pending_slots = [
            slot
            for slot, team in ((home_slot, home), (away_pending_slot, away))
            if not team
        ]
        pending_slots = list(dict.fromkeys(pending_slots))
        if pending_slots:
            if match.get("third_place_column") and not any(
                row.get("match_number") == match_number for row in pending
            ):
                _add_pending(
                    pending,
                    match_number,
                    pending_reason,
                    home_slot=home_slot,
                    away_slot=away_slot or None,
                    third_place_column=match.get("third_place_column"),
                    open_groups=standings_payload.get("open_groups", []),
                    unresolved_groups=sorted(unresolved_groups),
                )
            elif not match.get("third_place_column"):
                _add_pending(
                    pending,
                    match_number,
                    "slot_pending",
                    missing_slots=pending_slots,
                    open_groups=sorted({_slot_group(slot) for slot in pending_slots if slot}),
                    unresolved_groups=sorted(unresolved_groups),
                )
            fixtures_by_number[match_number] = _knockout_fixture(
                match_number,
                str(home or "unbekannt"),
                str(away or "unbekannt"),
                home_slot=home_slot,
                away_slot=away_slot or None,
                existing=existing_by_number.get(match_number),
                pending_slots=pending_slots,
                pending_reason=pending_reason if match.get("third_place_column") else "slot_pending",
            )
            continue
        fixtures_by_number[match_number] = _knockout_fixture(
            match_number,
            str(home),
            str(away),
            home_slot=home_slot,
            away_slot=away_slot,
            existing=existing_by_number.get(match_number),
        )

    winners: dict[int, str] = {}
    losers: dict[int, str] = {}
    for match_number, fixture in {**existing_by_number, **fixtures_by_number}.items():
        winner, loser = _winner_loser(fixture)
        if winner:
            winners[match_number] = winner
        if loser:
            losers[match_number] = loser

    for round_definition in bracket.get("rounds", []):
        for match in round_definition.get("matches", []):
            match_number = int(match["match_number"])
            home_from = int(match["home_from"])
            away_from = int(match["away_from"])
            home = winners.get(home_from)
            away = winners.get(away_from)
            if not home or not away:
                _add_pending(
                    pending,
                    match_number,
                    "previous_winner_pending",
                    home_from=home_from,
                    away_from=away_from,
                )
                continue
            fixtures_by_number[match_number] = _knockout_fixture(
                match_number,
                home,
                away,
                home_slot=f"W{home_from}",
                away_slot=f"W{away_from}",
                existing=existing_by_number.get(match_number),
            )
            winner, loser = _winner_loser(fixtures_by_number[match_number])
            if winner:
                winners[match_number] = winner
            if loser:
                losers[match_number] = loser

    if 101 in losers and 102 in losers:
        fixtures_by_number[103] = _knockout_fixture(
            103,
            losers[101],
            losers[102],
            home_slot="L101",
            away_slot="L102",
            existing=existing_by_number.get(103),
        )
    else:
        _add_pending(pending, 103, "semi_loser_pending", home_from=101, away_from=102)

    resolved = [fixtures_by_number[key] for key in sorted(fixtures_by_number)]
    safe_resolved = [fixture for fixture in resolved if not fixture.get("has_pending_slot")]
    status = {
        "resolved": [
            {
                "match_number": fixture["match_number"],
                "match_id": fixture["match_id"],
                "stage": fixture["stage"],
                "match": f"{fixture['home_team']} - {fixture['away_team']}",
                "kickoff_utc": fixture.get("kickoff_utc"),
                "status": fixture.get("status"),
            }
            for fixture in safe_resolved
        ],
        "listed": [
            {
                "match_number": fixture["match_number"],
                "match_id": fixture["match_id"],
                "stage": fixture["stage"],
                "match": f"{fixture['home_team']} - {fixture['away_team']}",
                "kickoff_utc": fixture.get("kickoff_utc"),
                "status": fixture.get("status"),
                "has_pending_slot": bool(fixture.get("has_pending_slot")),
                "pending_slots": fixture.get("pending_slots") or [],
            }
            for fixture in resolved
        ],
        "pending": sorted(pending, key=lambda row: int(row.get("match_number", 999))),
        "standings": standings_payload,
        "qualified_third_groups": qualified_third_groups,
        "manual_slots": [
            {"slot": slot, **metadata}
            for slot, metadata in sorted(applied_manual_slots.items())
        ],
        "manual_slot_conflicts": manual_slot_conflicts,
    }
    return {"fixtures": resolved, "status": status}


def simulate_tournament(
    fixture_payload: Mapping[str, Any],
    strengths: Mapping[str, Mapping[str, Any]],
    *,
    n_simulations: int = 5000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """WM-2026-Vollsimulation: Vorrunde + Round of 32 -> Champion.

    Die KO-Phase nutzt die echten FIFA-2026-Slots inklusive Annexe-C-
    Zuordnung der acht besten Drittplatzierten.
    """
    rng = random.Random(seed)
    bracket = load_2026_bracket()
    group_fixtures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fixture in fixture_payload.get("fixtures", []):
        if fixture.get("stage") == "group" and fixture.get("group"):
            group_fixtures[fixture["group"]].append(fixture)
    if not group_fixtures:
        return {}

    rounds_order = ["round_of_32", "round_of_16", "quarter", "semi", "final", "champion"]
    next_round = {
        "round_of_16": "quarter",
        "quarter": "semi",
        "semi": "final",
        "final": "champion",
    }
    counts: dict[str, dict[str, int]] = {label: defaultdict(int) for label in rounds_order}
    group_winner_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    completed = 0

    for _ in range(n_simulations):
        standings = simulate_group_stage(group_fixtures, strengths, rng)
        matchups = round_of_32_matchups(standings, bracket)
        if len(matchups) != 16:
            continue
        completed += 1
        for group_letter, ranked in standings.items():
            if ranked:
                group_winner_counts[str(group_letter)][str(ranked[0]["team"])] += 1
        winners_by_match: dict[int, str] = {}
        for matchup in matchups:
            home = matchup["home"]
            away = matchup["away"]
            winner = simulate_match(home, away, strengths, rng)
            winners_by_match[int(matchup["match_number"])] = winner
            counts["round_of_32"][home] += 1
            counts["round_of_32"][away] += 1
        round_of_32_winners = [winners_by_match[number] for number in range(73, 89)]
        for winner in round_of_32_winners:
            counts["round_of_16"][winner] += 1
        for round_definition in bracket.get("rounds", []):
            round_name = str(round_definition.get("name", ""))
            target_label = next_round.get(round_name)
            if not target_label:
                continue
            round_winners: list[str] = []
            for match in round_definition.get("matches", []):
                home = winners_by_match[int(match["home_from"])]
                away = winners_by_match[int(match["away_from"])]
                winner = simulate_match(home, away, strengths, rng)
                winners_by_match[int(match["match_number"])] = winner
                round_winners.append(winner)
            for winner in round_winners:
                counts[target_label][winner] += 1

    if not completed:
        return {}

    result: dict[str, Any] = {
        label: {team: round(count / completed, 4) for team, count in counts[label].items()}
        for label in rounds_order
    }
    result["group_winners"] = {
        group: {team: round(count / completed, 4) for team, count in team_counts.items()}
        for group, team_counts in sorted(group_winner_counts.items())
    }
    return result
