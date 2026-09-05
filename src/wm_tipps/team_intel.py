from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from .context import load_context
from .fixtures import all_teams, load_fixture_payload
from .io import read_json, write_csv_dicts, write_json
from .paths import DATA_DIR, EXPORTS_DIR


TEAM_INTEL_PATH = DATA_DIR / "team_intel_sources.json"
TEAM_INTEL_CHECKLIST_JSON = DATA_DIR / "team_intel_matchday_checklist.json"
TEAM_INTEL_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MACHINE_REACHABLE_STATUSES = {"active_json", "active_page", "active_rss"}


def load_team_intel_sources(path=TEAM_INTEL_PATH) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "sources": []})
    if not isinstance(payload, dict):
        return {"_meta": {}, "sources": []}
    sources = [row for row in payload.get("sources", []) if isinstance(row, dict)]
    return {"_meta": payload.get("_meta") or {}, "sources": sources}


def team_intel_report(
    fixtures: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fixtures = fixtures or load_fixture_payload()
    payload = payload or load_team_intel_sources()
    fixture_teams = set(all_teams(fixtures))
    sources = payload.get("sources") or []
    by_status = Counter(source.get("status", "unknown") for source in sources)
    by_type = Counter(source.get("source_type", "unknown") for source in sources)
    by_reliability = Counter(source.get("reliability", "unknown") for source in sources)
    team_rows = team_coverage_rows(fixture_teams, sources)
    host_rows = host_context_rows(sources)
    reachability_rows = source_reachability_rows(sources)
    checklist_rows = build_matchday_checklist(fixtures, payload)
    missing_team_specific = [
        row["team"] for row in team_rows if row.get("team_specific_official_count", 0) == 0
    ]
    return {
        "_meta": payload.get("_meta") or {},
        "summary": {
            "source_count": len(sources),
            "official_source_count": sum(1 for row in sources if row.get("official") is True),
            "active_sources": sum(1 for row in sources if row.get("status") in MACHINE_REACHABLE_STATUSES),
            "fixture_teams_with_official_watch": sum(
                1 for row in team_rows if row.get("official_watch_count", 0) > 0
            ),
            "fixture_teams_with_team_specific_official": sum(
                1 for row in team_rows if row.get("team_specific_official_count", 0) > 0
            ),
            "fixture_teams_missing_team_specific_official": len(missing_team_specific),
            "fixture_team_count": len(fixture_teams),
            "lineup_watch_sources": sum(
                1 for row in sources if "lineup" in set(row.get("signals") or [])
            ),
            "host_context_sources": sum(
                1 for row in sources if row.get("source_type") == "host_context"
            ),
            "active_json_sources": sum(1 for row in sources if row.get("status") == "active_json"),
            "machine_readability_audited_sources": sum(
                1
                for row in sources
                if row.get("machine_readability_decision") or row.get("machine_readable_alternatives")
            ),
            "reachability_counts": dict(Counter(row["reachability"] for row in reachability_rows)),
            "freshness_counts": dict(Counter(row["freshness"] for row in reachability_rows)),
            "matchday_checklist_count": len(checklist_rows),
            "status_counts": dict(sorted(by_status.items())),
            "type_counts": dict(sorted(by_type.items())),
            "reliability_counts": dict(sorted(by_reliability.items())),
        },
        "teams": team_rows,
        "missing_team_specific_official": missing_team_specific,
        "host_context": host_rows,
        "reachability": reachability_rows,
        "matchday_checklist": checklist_rows,
        "sources": sources,
    }


def team_coverage_rows(
    fixture_teams: set[str],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    all_team_sources = []
    for source in sources:
        teams = source.get("teams") or []
        if teams == ["*"]:
            all_team_sources.append(source)
            continue
        for team in teams:
            indexed[str(team)].append(source)
    rows = []
    for team in sorted(fixture_teams):
        team_sources = indexed.get(team, []) + all_team_sources
        official = [row for row in team_sources if row.get("official") is True]
        team_specific_official = [
            row
            for row in indexed.get(team, [])
            if row.get("official") is True
            and str(row.get("source_type") or "").startswith("official_federation")
        ]
        machine = [
            row
            for row in team_sources
            if row.get("status") in MACHINE_REACHABLE_STATUSES
        ]
        rows.append(
            {
                "team": team,
                "official_watch_count": len(official),
                "team_specific_official_count": len(team_specific_official),
                "machine_readable_count": len(machine),
                "source_ids": [row.get("id") for row in team_sources if row.get("id")],
            }
        )
    return rows


def host_context_rows(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for source in sources:
        if source.get("source_type") != "host_context":
            continue
        rows.append(
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "countries": source.get("countries", []),
                "signals": source.get("signals", []),
                "status": source.get("status"),
                "refresh_hint": source.get("refresh_hint"),
            }
        )
    return rows


def source_reachability_rows(
    sources: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for source in sources:
        status = source.get("status", "unknown")
        checked_at = source.get("checked_at") or source.get("last_checked_at")
        age_days = source_age_days(checked_at, now)
        rows.append(
            {
                "id": source.get("id"),
                "name": source.get("name"),
                "source_type": source.get("source_type"),
                "status": status,
                "reachability": reachability_bucket(status),
                "freshness": freshness_bucket(status, age_days),
                "checked_at": checked_at,
                "age_days": age_days,
                "refresh_hint": source.get("refresh_hint"),
                "url": source.get("url"),
            }
        )
    return sorted(rows, key=lambda row: (row["reachability"], row.get("id") or ""))


def reachability_bucket(status: str) -> str:
    if status in MACHINE_REACHABLE_STATUSES:
        return "machine_reachable"
    if status in {"blocked_curl_manual_watch"}:
        return "browser_or_manual"
    if status in {"manual_watch", "manual_watch_unverified"}:
        return "manual_watch"
    return "unknown"


def source_age_days(value: str | None, now: datetime) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, (now - parsed).days)


def freshness_bucket(status: str, age_days: int | None) -> str:
    if status == "manual_watch_unverified":
        return "needs_verification"
    if age_days is None:
        return "unknown_checked_at"
    if age_days > 14:
        return "stale"
    if age_days > 7:
        return "recheck_soon"
    return "fresh"


def build_matchday_checklist(
    fixtures: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    fixtures = fixtures or load_fixture_payload()
    payload = payload or load_team_intel_sources()
    sources = payload.get("sources") or []
    context = load_context().get("fixtures", {})
    now = now or datetime.now(timezone.utc)
    rows = []
    for fixture in fixtures.get("fixtures", []):
        kickoff = parse_datetime(fixture.get("kickoff_utc"))
        if not kickoff:
            continue
        match_id = fixture.get("match_id")
        host_country = (context.get(match_id) or {}).get("host_country")
        home_team = fixture.get("home_team")
        away_team = fixture.get("away_team")
        source_ids = checklist_source_ids(sources, home_team, away_team, host_country)
        missing = []
        for team in (home_team, away_team):
            if not team_specific_official_sources(sources, team):
                missing.append(f"official_team_source:{team}")
        if host_country and not host_weather_sources(sources, host_country):
            missing.append(f"weather_source:{host_country}")
        row = {
            "match_id": match_id,
            "match_number": fixture.get("match_number"),
            "kickoff_utc": fixture.get("kickoff_utc"),
            "match": f"{home_team} - {away_team}",
            "venue": fixture.get("venue"),
            "host_country": host_country,
            "status": matchday_status(kickoff, now, missing),
            "days_until": (kickoff - now).days,
            "checks": [
                {"type": "travel_context", "due_at": (kickoff - timedelta(hours=48)).isoformat()},
                {"type": "weather_first_pass", "due_at": (kickoff - timedelta(hours=72)).isoformat()},
                {"type": "pitch_context", "due_at": (kickoff - timedelta(hours=24)).isoformat()},
                {"type": "expected_lineup", "due_at": (kickoff - timedelta(hours=24)).isoformat()},
                {"type": "final_weather", "due_at": (kickoff - timedelta(hours=6)).isoformat()},
                {"type": "confirmed_lineup", "due_at": (kickoff - timedelta(minutes=90)).isoformat()},
            ],
            "missing": missing,
            "source_ids": source_ids,
        }
        rows.append(row)
    return sorted(rows, key=lambda row: (row.get("kickoff_utc") or "", row.get("match_id") or ""))


def export_matchday_checklist(
    fixtures: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = build_matchday_checklist(fixtures, payload)
    write_json(
        TEAM_INTEL_CHECKLIST_JSON,
        {
            "_meta": {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "note": "Chronological matchday checklist for free team intelligence: lineups, weather, pitch and travel.",
            },
            "items": rows,
        },
    )
    csv_rows = []
    for row in rows:
        due = {check["type"]: check["due_at"] for check in row.get("checks") or []}
        csv_rows.append(
            {
                "match_number": row.get("match_number"),
                "match_id": row.get("match_id"),
                "kickoff_utc": row.get("kickoff_utc"),
                "match": row.get("match"),
                "venue": row.get("venue"),
                "host_country": row.get("host_country"),
                "status": row.get("status"),
                "travel_context_due_at": due.get("travel_context"),
                "weather_first_pass_due_at": due.get("weather_first_pass"),
                "pitch_context_due_at": due.get("pitch_context"),
                "expected_lineup_due_at": due.get("expected_lineup"),
                "final_weather_due_at": due.get("final_weather"),
                "confirmed_lineup_due_at": due.get("confirmed_lineup"),
                "missing": ", ".join(row.get("missing") or []),
                "source_ids": ", ".join(row.get("source_ids") or []),
            }
        )
    csv_path = EXPORTS_DIR / "team_intel_matchday_checklist.csv"
    write_csv_dicts(
        csv_path,
        csv_rows,
        [
            "match_number",
            "match_id",
            "kickoff_utc",
            "match",
            "venue",
            "host_country",
            "status",
            "travel_context_due_at",
            "weather_first_pass_due_at",
            "pitch_context_due_at",
            "expected_lineup_due_at",
            "final_weather_due_at",
            "confirmed_lineup_due_at",
            "missing",
            "source_ids",
        ],
    )
    md_path = EXPORTS_DIR / "team_intel_matchday_checklist.md"
    lines = [
        "# Team-Intel Matchday Checklist",
        "",
        "Chronologisch sortiert. Zeiten sind UTC.",
        "",
        "| Spiel | Anpfiff | Match | Status | Kritische Checks | Quellen |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        checks = ", ".join(check["type"] for check in row.get("checks") or [])
        sources = ", ".join(row.get("source_ids") or [])
        lines.append(
            "| {match_number} | {kickoff_utc} | {match} | {status} | {checks} | {sources} |".format(
                match_number=row.get("match_number") or "",
                kickoff_utc=row.get("kickoff_utc") or "",
                match=row.get("match") or "",
                status=row.get("status") or "",
                checks=checks,
                sources=sources,
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "count": len(rows),
        "json_path": str(TEAM_INTEL_CHECKLIST_JSON),
        "csv_path": str(csv_path),
        "markdown_path": str(md_path),
        "items": rows,
    }


def refresh_team_intel_sources(
    *,
    statuses: set[str] | None = None,
    ids: set[str] | None = None,
    limit: int | None = None,
    timeout_seconds: int = 12,
    workers: int = 8,
    probe_func=None,
    path=TEAM_INTEL_PATH,
) -> dict[str, Any]:
    payload = load_team_intel_sources(path)
    sources = payload.get("sources") or []
    statuses = statuses or {"manual_watch_unverified"}
    candidates = [
        source
        for source in sources
        if source.get("id")
        and source.get("url")
        and source.get("status") in statuses
        and (ids is None or source.get("id") in ids)
    ]
    if limit is not None:
        candidates = candidates[:limit]
    if not candidates:
        return {
            "updated_at": None,
            "probed": 0,
            "status_counts": {},
            "diagnostics": [],
        }
    checked_at = datetime.now(timezone.utc).isoformat()
    probe_func = probe_func or probe_source_url

    by_id: dict[str, dict[str, Any]] = {}
    max_workers = max(1, min(workers, len(candidates) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(probe_func, source["url"], timeout_seconds): source
            for source in candidates
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                probe = future.result()
            except Exception as exc:  # pragma: no cover - diagnostics for live probes
                probe = {
                    "status": "error",
                    "http_status": None,
                    "error": str(exc),
                    "url": source.get("url"),
                }
            by_id[source["id"]] = probe

    diagnostics = []
    for source in sources:
        source_id = source.get("id")
        if source_id not in by_id:
            continue
        probe = by_id[source_id]
        new_status = source_status_from_probe(probe)
        source["checked_at"] = checked_at
        source["status"] = new_status
        source["http_status"] = probe.get("http_status")
        source["effective_url"] = probe.get("effective_url")
        source["content_type"] = probe.get("content_type")
        source["verification"] = verification_text(probe, checked_at, new_status)
        source["reachability_probe"] = probe
        if new_status == "active_json":
            source["refresh_hint"] = (
                "machine/json watch for roster, camp, fixture or team-update signals"
            )
        elif new_status == "active_page":
            source["refresh_hint"] = (
                "manual/page watch around roster, camp, injury and lineup "
                "windows; curl reachability verified"
            )
        elif new_status == "blocked_curl_manual_watch":
            source["refresh_hint"] = "browser/manual watch; curl probe is blocked"
        elif new_status == "manual_watch_unverified":
            source["refresh_hint"] = (
                "manual/page watch; live reachability needs replacement or retry"
            )
        diagnostics.append(
            {
                "id": source_id,
                "team": (source.get("teams") or [None])[0],
                "status": new_status,
                "http_status": probe.get("http_status"),
                "effective_url": probe.get("effective_url"),
                "error": probe.get("error"),
            }
        )

    payload["_meta"] = {
        **(payload.get("_meta") or {}),
        "updated_at": checked_at,
        "last_reachability_refresh": checked_at,
    }
    write_json(path, payload)
    status_counts = Counter(row["status"] for row in diagnostics)
    return {
        "updated_at": checked_at,
        "probed": len(diagnostics),
        "status_counts": dict(sorted(status_counts.items())),
        "diagnostics": sorted(diagnostics, key=lambda row: row.get("id") or ""),
    }


def probe_source_url(url: str, timeout_seconds: int = 12) -> dict[str, Any]:
    result = subprocess.run(
        [
            "curl",
            "-L",
            "-sS",
            "-o",
            "/dev/null",
            "--max-time",
            str(timeout_seconds),
            "--compressed",
            "-A",
            TEAM_INTEL_USER_AGENT,
            "-w",
            "%{http_code}\t%{url_effective}\t%{content_type}",
            url,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    parts = output.split("\t")
    http_status = parse_http_status(parts[0] if parts else "")
    return {
        "status": "ok" if result.returncode == 0 and http_status else "error",
        "http_status": http_status,
        "url": url,
        "effective_url": parts[1] if len(parts) > 1 else None,
        "content_type": parts[2] if len(parts) > 2 else None,
        "returncode": result.returncode,
        "error": (result.stderr or "").strip() or None,
    }


def parse_http_status(value: str | None) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def source_status_from_probe(probe: dict[str, Any]) -> str:
    http_status = probe.get("http_status")
    if isinstance(http_status, int) and 200 <= http_status < 400:
        content_type = str(probe.get("content_type") or "").lower()
        if "json" in content_type:
            return "active_json"
        return "active_page"
    if http_status in {401, 403, 429, 451}:
        return "blocked_curl_manual_watch"
    return "manual_watch_unverified"


def verification_text(probe: dict[str, Any], checked_at: str, status: str) -> str:
    date = checked_at.split("T", 1)[0]
    http_status = probe.get("http_status")
    effective_url = probe.get("effective_url") or probe.get("url") or ""
    error = probe.get("error")
    if status in {"active_json", "active_page"}:
        return f"curl GET HTTP {http_status} on {date}; effective URL {effective_url}."
    if status == "blocked_curl_manual_watch":
        return (
            f"curl GET HTTP {http_status} on {date}; keep as browser/manual "
            f"watch. Effective URL {effective_url}."
        )
    detail = f"curl GET HTTP {http_status}" if http_status else "curl probe failed"
    if error:
        detail = f"{detail}: {error[:160]}"
    return f"{detail} on {date}; keep unverified and search replacement if still needed."


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def matchday_status(kickoff: datetime, now: datetime, missing: list[str]) -> str:
    if kickoff <= now:
        return "past_or_live"
    if kickoff - now <= timedelta(minutes=90):
        return "confirmed_lineup_window"
    if kickoff - now <= timedelta(hours=6):
        return "final_weather_window"
    if kickoff - now <= timedelta(hours=72):
        return "pre_match_window"
    if missing:
        return "source_gap"
    return "scheduled"


def checklist_source_ids(
    sources: list[dict[str, Any]],
    home_team: str | None,
    away_team: str | None,
    host_country: str | None,
) -> list[str]:
    ids: list[str] = []
    for source in sources:
        source_id = source.get("id")
        if not source_id:
            continue
        teams = source.get("teams") or []
        countries = source.get("countries") or []
        signals = set(source.get("signals") or [])
        if teams == ["*"] and signals & {"lineup", "confirmed_lineup", "expected_lineup", "squad"}:
            ids.append(source_id)
        elif home_team in teams or away_team in teams:
            ids.append(source_id)
        elif host_country and host_country in countries:
            ids.append(source_id)
    return sorted(set(ids))


def team_specific_official_sources(sources: list[dict[str, Any]], team: str | None) -> list[dict[str, Any]]:
    if not team:
        return []
    return [
        source
        for source in sources
        if source.get("official") is True
        and str(source.get("source_type") or "").startswith("official_federation")
        and team in (source.get("teams") or [])
    ]


def host_weather_sources(sources: list[dict[str, Any]], host_country: str) -> list[dict[str, Any]]:
    return [
        source
        for source in sources
        if source.get("source_type") == "host_context"
        and host_country in (source.get("countries") or [])
        and "weather" in set(source.get("signals") or [])
    ]
