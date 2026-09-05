from __future__ import annotations

from typing import Any, Mapping


DEFAULT_TOP_SHARE = 0.4


def _top_player_share(players: list[Mapping[str, Any]]) -> float:
    shares: list[float] = []
    for player in players:
        try:
            shares.append(float(player.get("goal_share", 0.0)))
        except (TypeError, ValueError):
            continue
    return max(shares) if shares else DEFAULT_TOP_SHARE


def team_topscorer_probabilities(
    teams: list[str],
    player_pool: Mapping[str, list[Mapping[str, Any]]],
    expected_team_goals: Mapping[str, float],
    *,
    default_top_share: float = DEFAULT_TOP_SHARE,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for team in teams:
        players = player_pool.get(team) or []
        top_share = _top_player_share(players) if players else default_top_share
        try:
            team_xg = float(expected_team_goals.get(team, 1.0))
        except (TypeError, ValueError):
            team_xg = 1.0
        scores[team] = max(0.0, team_xg) * max(0.0, top_share)
    if not scores:
        return {}
    total = sum(scores.values()) or 1.0
    return {team: round(score / total, 4) for team, score in scores.items()}
