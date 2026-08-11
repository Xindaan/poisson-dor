from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .fixtures import all_teams, load_fixture_payload
from .io import read_json, write_json
from .paths import DATA_DIR


FIFA_PROXY_TOP = 2180.0
FIFA_PROXY_STEP = 7.5
WORLD_ELO_WEIGHT = 0.82
FIFA_RANK_WEIGHT = 0.18
ATTACK_BASE = 1.0
ATTACK_RATING_DIVISOR = 650.0
PLAYER_XG_DELTA_CAP = 0.06


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fifa_rank_rating(rank: int | float | str | None) -> float:
    try:
        rank_value = int(rank or 0)
    except (TypeError, ValueError):
        return 1500.0
    if rank_value <= 0:
        return 1500.0
    return FIFA_PROXY_TOP - (rank_value - 1) * FIFA_PROXY_STEP


def _number(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def player_intelligence_for_team(
    team: str,
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None,
) -> dict[str, Any]:
    players = list((player_pool or {}).get(team) or [])
    if not players:
        return {
            "source": "player_pool.json",
            "players_tracked": 0,
            "top3_goals_since_2024": 0,
            "top_scorer_share": None,
            "depth_score": None,
            "xg_delta": 0.0,
            "note": (
                "Keine lokale Spielerpool-Coverage fuer dieses Team; "
                "Player-Intel bleibt neutral statt als Datenluecke bestraft zu werden."
            ),
        }
    top_share_values: list[float] = []
    goals_values: list[int] = []
    for player in players:
        try:
            top_share_values.append(float(player.get("goal_share", 0.0)))
        except (TypeError, ValueError):
            pass
        try:
            goals_values.append(int(player.get("goals_since_2024", 0)))
        except (TypeError, ValueError):
            pass
    top_share = max(top_share_values) if top_share_values else 0.4
    top3_goals = sum(goals_values)
    depth_score = min(1.0, top3_goals / 24.0)
    concentration_penalty = max(0.0, top_share - 0.68) * 0.05
    shared_creation_bonus = max(0.0, 0.52 - top_share) * 0.04 if top3_goals >= 12 else 0.0
    raw_delta = (depth_score - 0.45) * 0.08 - concentration_penalty + shared_creation_bonus
    player_xg_delta = clamp(raw_delta, -PLAYER_XG_DELTA_CAP, PLAYER_XG_DELTA_CAP)
    return {
        "source": "player_pool.json",
        "players_tracked": len(players),
        "top3_goals_since_2024": top3_goals,
        "top_scorer_share": round(top_share, 4),
        "depth_score": round(depth_score, 4),
        "xg_delta": round(player_xg_delta, 3),
        "note": (
            "Quantitativer Player-Intel-Proxy aus Nationalteam-Torschuetzen "
            "seit 2024; Guardian/FIFA-Kaderprofile sind Rollen-/Kader-"
            "Verifikation, sobald sie in lokale strukturierte Notizen "
            "uebernommen werden."
        ),
    }


def derive_strength(team: str, row: Mapping[str, Any]) -> dict[str, Any]:
    source_elo = _number(row, "world_elo", 1500.0)
    fifa_rank = row.get("fifa_rank")
    fifa_proxy = fifa_rank_rating(fifa_rank)
    form_adjustment = _number(row, "form_adjustment", 0.0)
    qualifier_adjustment = _number(row, "qualifier_adjustment", 0.0)
    attack_adjustment = _number(row, "attack_adjustment", 0.0)

    model_elo = (
        source_elo * WORLD_ELO_WEIGHT
        + fifa_proxy * FIFA_RANK_WEIGHT
        + form_adjustment
        + qualifier_adjustment
    )
    attack = clamp(ATTACK_BASE + (model_elo - 1500.0) / ATTACK_RATING_DIVISOR + attack_adjustment, 0.75, 2.15)
    return {
        "attack": round(attack, 2),
        "attack_adjustment": round(attack_adjustment, 2),
        "confederation": row.get("confederation"),
        "elo": round(model_elo),
        "fifa_rank": fifa_rank,
        "fifa_rank_rating": round(fifa_proxy, 1),
        "form_adjustment": round(form_adjustment, 1),
        "qualifier_adjustment": round(qualifier_adjustment, 1),
        "qualifier_status": row.get("qualifier_status", "unknown"),
        "source_elo": round(source_elo),
        "source_elo_rank": row.get("world_elo_rank"),
        "strength_note": row.get("note", ""),
        "team": team,
    }


def build_team_strengths(
    fixture_payload: Mapping[str, Any] | None = None,
    input_payload: Mapping[str, Any] | None = None,
    *,
    write: bool = True,
    player_pool_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fixtures = fixture_payload or load_fixture_payload()
    raw_inputs = input_payload or read_json(DATA_DIR / "team_strength_inputs.json", {"teams": {}})
    raw_player_pool = player_pool_payload or read_json(DATA_DIR / "player_pool.json", {"players": {}})
    player_pool = raw_player_pool.get("players", {}) if isinstance(raw_player_pool, Mapping) else {}
    rows = raw_inputs.get("teams", {}) if isinstance(raw_inputs, Mapping) else {}
    teams = all_teams(dict(fixtures)) or sorted(rows)

    payload: dict[str, Any] = {
        "_meta": {
            "description": "Teamstaerke aus kostenlosen FIFA-Rang-, World-Football-Elo-, Form- und Quali-Signalen.",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_meta": raw_inputs.get("_meta", {}) if isinstance(raw_inputs, Mapping) else {},
            "methodology": {
                "model_elo": "0.82 * world_elo + 0.18 * fifa_rank_proxy + form_adjustment + qualifier_adjustment",
                "fifa_rank_proxy": "2180 - 7.5 * (fifa_rank - 1)",
                "attack": "clamp(1.0 + (model_elo - 1500) / 650 + attack_adjustment, 0.75, 2.15)",
                "player_xg_delta": "small capped xG delta from current player_pool scorer depth and top-scorer concentration",
            },
            "missing_inputs": [],
            "team_count": len(teams),
            "player_intel_source": "data/player_pool.json plus manual/Guardian/FIFA role verification when available",
        }
    }

    missing_inputs: list[str] = []
    for team in teams:
        row = rows.get(team)
        if not isinstance(row, Mapping):
            missing_inputs.append(team)
            row = {"note": "fallback default because team_strength_inputs.json has no row"}
        strength = derive_strength(team, row)
        player_intel = player_intelligence_for_team(team, player_pool)
        strength["player_intel"] = player_intel
        strength["player_xg_delta"] = player_intel["xg_delta"]
        payload[team] = strength
    payload["_meta"]["missing_inputs"] = missing_inputs
    if write:
        write_json(DATA_DIR / "team_strength.json", payload)
    return payload
