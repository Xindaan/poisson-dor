from __future__ import annotations

from typing import Any

from .fixtures import all_teams, load_fixture_payload
from .io import read_csv_dicts, read_json
from .odds import load_manual_odds, odds_coverage
from .exact_scores import SCORE_RE, parse_decimal
from .paths import DATA_DIR


REQUIRED_STRENGTH_FIELDS = ("world_elo", "fifa_rank")


def lint_team_strength_inputs(teams: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    payload = read_json(DATA_DIR / "team_strength_inputs.json", {})
    if not isinstance(payload, dict):
        return [{"file": "team_strength_inputs.json", "issue": "payload kein dict"}]
    if "_meta" not in payload or "updated_at" not in (payload.get("_meta") or {}):
        issues.append({"file": "team_strength_inputs.json", "issue": "_meta.updated_at fehlt"})
    rows = payload.get("teams", {})
    for team in teams:
        row = rows.get(team)
        if not isinstance(row, dict):
            issues.append({"file": "team_strength_inputs.json", "team": team, "issue": "kein Eintrag"})
            continue
        for field in REQUIRED_STRENGTH_FIELDS:
            if row.get(field) in (None, ""):
                issues.append({"file": "team_strength_inputs.json", "team": team, "issue": f"{field} fehlt"})
    return issues


def lint_player_pool(teams: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    payload = read_json(DATA_DIR / "player_pool.json", {})
    if not isinstance(payload, dict):
        return [{"file": "player_pool.json", "issue": "payload kein dict"}]
    players_by_team = payload.get("players", {})
    if not isinstance(players_by_team, dict):
        return [{"file": "player_pool.json", "issue": "players-Field ist kein dict"}]
    for team, players in players_by_team.items():
        if team not in teams:
            issues.append({"file": "player_pool.json", "team": team, "issue": "Team nicht im Fixtures-Plan"})
            continue
        if not isinstance(players, list):
            issues.append({"file": "player_pool.json", "team": team, "issue": "players ist keine Liste"})
            continue
        share_sum = 0.0
        for player in players:
            if not isinstance(player, dict):
                issues.append({"file": "player_pool.json", "team": team, "issue": "Spieler-Eintrag kein dict"})
                continue
            if not player.get("name"):
                issues.append({"file": "player_pool.json", "team": team, "issue": "Spieler ohne name"})
            try:
                share = float(player.get("goal_share", 0.0))
                share_sum += share
            except (TypeError, ValueError):
                issues.append({"file": "player_pool.json", "team": team, "issue": "goal_share nicht numerisch"})
        if share_sum > 1.0 + 1e-6:
            issues.append({"file": "player_pool.json", "team": team, "issue": f"goal_share-Summe {share_sum:.3f} > 1.0"})
    return issues


def lint_manual_odds(fixture_match_ids: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rows = read_csv_dicts(DATA_DIR / "manual_odds.csv")
    if not rows:
        return issues
    expected = {"match_id", "home", "draw", "away"}
    header = set(rows[0].keys())
    missing = expected - header
    if missing:
        issues.append({"file": "manual_odds.csv", "issue": f"Header fehlt: {sorted(missing)}"})
    seen_sources: set[tuple[str, str]] = set()
    for row in rows:
        mid = row.get("match_id", "")
        source = row.get("source", "manual")
        if mid and mid not in fixture_match_ids:
            issues.append({"file": "manual_odds.csv", "row_match_id": mid, "issue": "match_id nicht im Spielplan"})
        source_key = (mid, source)
        if mid and source_key in seen_sources:
            issues.append({"file": "manual_odds.csv", "row_match_id": mid, "source": source, "issue": "Quelle fuer Spiel doppelt"})
        seen_sources.add(source_key)
        for outcome in ("home", "draw", "away"):
            value = row.get(outcome, "")
            if value in (None, ""):
                continue
            try:
                if float(value.replace(",", ".")) <= 1.0:
                    issues.append({"file": "manual_odds.csv", "row_match_id": mid, "issue": f"{outcome}-Quote <= 1.0"})
            except (AttributeError, ValueError):
                issues.append({"file": "manual_odds.csv", "row_match_id": mid, "issue": f"{outcome} nicht numerisch"})
    return issues


def lint_manual_markets(teams: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    items = read_json(DATA_DIR / "manual_markets.json", [])
    if not isinstance(items, list):
        return [{"file": "manual_markets.json", "issue": "payload keine Liste"}]
    for item in items:
        if not isinstance(item, dict):
            continue
        cat = item.get("category")
        if cat in {"world_champion", "semifinalist", "top_scorer_team"}:
            outcome = item.get("outcome")
            if outcome and outcome not in teams:
                issues.append({
                    "file": "manual_markets.json",
                    "outcome": outcome,
                    "issue": "Team nicht im Spielplan",
                })
    return issues


def lint_manual_exact_scores(fixture_match_ids: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    payload = read_json(DATA_DIR / "manual_exact_score_odds.json", {"items": [], "visible_events": []})
    if not isinstance(payload, dict):
        return [{"file": "manual_exact_score_odds.json", "issue": "payload kein dict"}]
    for event in payload.get("visible_events") or []:
        match_id = event.get("match_id")
        if match_id and match_id not in fixture_match_ids:
            issues.append({
                "file": "manual_exact_score_odds.json",
                "row_match_id": match_id,
                "issue": "visible_event match_id nicht im Spielplan",
            })
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            issues.append({"file": "manual_exact_score_odds.json", "issue": "item kein dict"})
            continue
        match_id = item.get("match_id")
        if match_id not in fixture_match_ids:
            issues.append({
                "file": "manual_exact_score_odds.json",
                "row_match_id": match_id,
                "issue": "match_id nicht im Spielplan",
            })
        seen_scores: set[str] = set()
        prices = item.get("prices") or []
        if not prices:
            issues.append({
                "file": "manual_exact_score_odds.json",
                "row_match_id": match_id,
                "issue": "keine Exact-Score-Preise",
            })
        for price in prices:
            score = str(price.get("score") or price.get("selection") or "")
            if not SCORE_RE.fullmatch(score):
                issues.append({
                    "file": "manual_exact_score_odds.json",
                    "row_match_id": match_id,
                    "issue": f"ungueltiger Score {score}",
                })
            if score in seen_scores:
                issues.append({
                    "file": "manual_exact_score_odds.json",
                    "row_match_id": match_id,
                    "issue": f"Score doppelt {score}",
                })
            seen_scores.add(score)
            if parse_decimal(price.get("decimal_odds") or price.get("odds")) is None:
                issues.append({
                    "file": "manual_exact_score_odds.json",
                    "row_match_id": match_id,
                    "issue": f"ungueltige Quote fuer {score}",
                })
    return issues


def lint_team_intel_sources(teams: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    payload = read_json(DATA_DIR / "team_intel_sources.json", {"sources": []})
    if not isinstance(payload, dict):
        return [{"file": "team_intel_sources.json", "issue": "payload kein dict"}]
    seen_ids: set[str] = set()
    for source in payload.get("sources") or []:
        if not isinstance(source, dict):
            issues.append({"file": "team_intel_sources.json", "issue": "source kein dict"})
            continue
        source_id = source.get("id")
        if not source_id:
            issues.append({"file": "team_intel_sources.json", "issue": "source id fehlt"})
        elif source_id in seen_ids:
            issues.append({"file": "team_intel_sources.json", "source": source_id, "issue": "source id doppelt"})
        seen_ids.add(source_id)
        for field in ("name", "url", "source_type", "status", "reliability"):
            if not source.get(field):
                issues.append({"file": "team_intel_sources.json", "source": source_id, "issue": f"{field} fehlt"})
        for team in source.get("teams") or []:
            if team != "*" and team not in teams:
                issues.append({
                    "file": "team_intel_sources.json",
                    "source": source_id,
                    "team": team,
                    "issue": "Team nicht im Spielplan",
                })
        if source.get("source_type") == "host_context" and not source.get("countries"):
            issues.append({
                "file": "team_intel_sources.json",
                "source": source_id,
                "issue": "host_context ohne countries",
            })
    return issues


def lint_odds_coverage(fixtures: dict[str, Any]) -> list[dict[str, Any]]:
    """Info-Hinweise zur Quoten-Abdeckung -- keine harten Fehler.

    Liefert eine eigene Liste, damit run_lint.count nur echte
    Schema-/Konsistenzfehler zaehlt.
    """
    coverage = odds_coverage(fixtures.get("fixtures", []), load_manual_odds())
    summary = coverage.get("summary", {})
    counts = summary.get("status_counts", {})
    info: list[dict[str, Any]] = []
    missing = summary.get("missing", 0)
    single = counts.get("single_source", 0)
    watch_only = counts.get("watch_only", 0)
    if missing:
        info.append({"file": "manual_odds.csv", "severity": "info", "issue": f"{missing} Spiele ohne Quoten-Konsensus"})
    if single:
        info.append({"file": "manual_odds.csv", "severity": "info", "issue": f"{single} Spiele nur single-source"})
    if watch_only:
        info.append({"file": "manual_odds.csv", "severity": "info", "issue": f"{watch_only} Spiele nur watch-only (unvollstaendige/alte Quoten)"})
    return info


def run_lint() -> dict[str, Any]:
    fixtures = load_fixture_payload()
    teams = all_teams(fixtures)
    match_ids = {f.get("match_id", "") for f in fixtures.get("fixtures", []) if f.get("match_id")}
    all_issues: list[dict[str, Any]] = []
    all_issues.extend(lint_team_strength_inputs(teams))
    all_issues.extend(lint_player_pool(teams))
    all_issues.extend(lint_manual_odds(match_ids))
    all_issues.extend(lint_manual_markets(set(teams)))
    all_issues.extend(lint_manual_exact_scores(match_ids))
    all_issues.extend(lint_team_intel_sources(set(teams)))
    info = lint_odds_coverage(fixtures)
    return {
        "issues": all_issues,
        "count": len(all_issues),
        "info": info,
        "teams_total": len(teams),
    }
