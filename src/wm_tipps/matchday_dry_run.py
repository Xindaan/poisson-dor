from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .dashboard import all_round_final_tips, build_watchlist, chronology_key, final_tips
from .fixtures import load_fixture_payload
from .io import read_json, write_json
from .paths import DATA_DIR, EXPORTS_DIR
from .team_intel import build_matchday_checklist, load_team_intel_sources, parse_datetime


MATCHDAY_DRY_RUN_JSON = DATA_DIR / "matchday_dry_run.json"
MATCHDAY_DRY_RUN_MARKDOWN = EXPORTS_DIR / "matchday_dry_run.md"

SCENARIOS = [
    {
        "label": "T-48h",
        "offset": timedelta(hours=48),
        "expected_status": "pre_match_window",
        "required_due_checks": {"weather_first_pass", "travel_context"},
    },
    {
        "label": "T-24h",
        "offset": timedelta(hours=24),
        "expected_status": "pre_match_window",
        "required_due_checks": {
            "weather_first_pass",
            "travel_context",
            "pitch_context",
            "expected_lineup",
        },
    },
    {
        "label": "T-6h",
        "offset": timedelta(hours=6),
        "expected_status": "final_weather_window",
        "required_due_checks": {
            "weather_first_pass",
            "travel_context",
            "pitch_context",
            "expected_lineup",
            "final_weather",
        },
    },
    {
        "label": "T-90m",
        "offset": timedelta(minutes=90),
        "expected_status": "confirmed_lineup_window",
        "required_due_checks": {
            "weather_first_pass",
            "travel_context",
            "pitch_context",
            "expected_lineup",
            "final_weather",
            "confirmed_lineup",
        },
    },
]


def build_matchday_dry_run(
    fixtures: dict[str, Any] | None = None,
    predictions_payload: dict[str, Any] | None = None,
    team_intel_payload: dict[str, Any] | None = None,
    history_payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    fixtures = fixtures or load_fixture_payload()
    if predictions_payload is None:
        predictions_payload = read_json(DATA_DIR / "predictions.json", {"predictions": []})
    if team_intel_payload is None:
        team_intel_payload = load_team_intel_sources()
    if history_payload is None:
        history_payload = read_json(DATA_DIR / "prediction_history.json", {"events": []})
    now = now or datetime.now(timezone.utc)

    prediction_rows = predictions_payload.get("predictions") or []
    final_rows = final_tips(prediction_rows)
    all_final_rows = all_round_final_tips(prediction_rows)
    watch_rows = build_watchlist(prediction_rows)
    target = next_target_fixture(fixtures.get("fixtures", []), now)
    if not target:
        report = empty_report(now, final_rows, all_final_rows, watch_rows, history_payload)
    else:
        scenarios = [
            simulate_scenario(scenario, target, fixtures, team_intel_payload)
            for scenario in SCENARIOS
        ]
        checks = dry_run_checks(final_rows, all_final_rows, watch_rows, history_payload, scenarios)
        report = {
            "_meta": {
                "updated_at": now.isoformat(),
                "note": "Local matchday workflow dry run for watchlist, history and final-tip ergonomics.",
            },
            "status": report_status(checks),
            "target_match": target_summary(target),
            "counts": {
                "final_tips": len(final_rows),
                "all_round_final_tips": len(all_final_rows),
                "watchlist": len(watch_rows),
                "history_events": len(history_payload.get("events") or []),
                "scenarios": len(scenarios),
            },
            "checks": checks,
            "scenarios": scenarios,
        }

    if write:
        write_json(MATCHDAY_DRY_RUN_JSON, report)
        MATCHDAY_DRY_RUN_MARKDOWN.write_text(
            render_matchday_dry_run_markdown(report),
            encoding="utf-8",
        )
    return report


def next_target_fixture(fixtures: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    rows = []
    for fixture in fixtures:
        kickoff = parse_datetime(fixture.get("kickoff_utc"))
        if not kickoff:
            continue
        if kickoff >= now:
            rows.append(fixture)
    rows = sorted(rows, key=chronology_key)
    return rows[0] if rows else None


def simulate_scenario(
    scenario: dict[str, Any],
    target: dict[str, Any],
    fixtures: dict[str, Any],
    team_intel_payload: dict[str, Any],
) -> dict[str, Any]:
    kickoff = parse_datetime(target.get("kickoff_utc"))
    simulated_now = kickoff - scenario["offset"] if kickoff else datetime.now(timezone.utc)
    checklist = build_matchday_checklist(fixtures, team_intel_payload, now=simulated_now)
    row = next((item for item in checklist if item.get("match_id") == target.get("match_id")), {})
    due_checks = due_check_types(row.get("checks") or [], simulated_now)
    required = sorted(scenario["required_due_checks"])
    missing_required = [check for check in required if check not in due_checks]
    status_ok = row.get("status") == scenario["expected_status"]
    return {
        "label": scenario["label"],
        "simulated_now_utc": simulated_now.isoformat(),
        "status": row.get("status"),
        "expected_status": scenario["expected_status"],
        "status_ok": status_ok,
        "due_checks": due_checks,
        "required_due_checks": required,
        "missing_required_checks": missing_required,
        "missing_sources": row.get("missing") or [],
        "source_ids": row.get("source_ids") or [],
        "result": "pass" if status_ok and not missing_required else "review",
    }


def due_check_types(checks: list[dict[str, Any]], now: datetime) -> list[str]:
    due = []
    for check in checks:
        due_at = parse_datetime(check.get("due_at"))
        if due_at and due_at <= now and check.get("type"):
            due.append(str(check["type"]))
    return sorted(due)


def dry_run_checks(
    final_rows: list[dict[str, Any]],
    all_final_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    history_payload: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    stale_history = same_tip_history_events(history_payload.get("events") or [])
    windows_ok = bool(scenarios) and all(row.get("result") == "pass" for row in scenarios)
    checks = [
        check_row(
            "final_tips_chronological",
            rows_are_chronological(final_rows),
            f"{len(final_rows)} finale Tipps sind chronologisch sortiert.",
            "Finale Tipps sind nicht chronologisch sortiert.",
        ),
        check_row(
            "all_round_final_tips_chronological",
            rows_are_chronological(all_final_rows),
            f"{len(all_final_rows)} finale Tipps ueber alle Runden sind chronologisch sortiert.",
            "Mehr-Runden-Finaltipps sind nicht chronologisch sortiert.",
        ),
        check_row(
            "watchlist_chronological",
            rows_are_chronological(watch_rows),
            f"{len(watch_rows)} Watchlist-Zeilen sind chronologisch sortiert.",
            "Watchlist-Zeilen sind nicht chronologisch sortiert.",
        ),
        check_row(
            "history_only_tip_changes",
            not stale_history,
            "Prediction-History enthaelt nur echte Tippwechsel.",
            f"{len(stale_history)} History-Eintraege haben identische from_tip/to_tip Werte.",
            details=stale_history[:5],
        ),
        check_row(
            "matchday_windows_fire",
            windows_ok,
            "T-48h/T-24h/T-6h/T-90m Checks feuern im erwarteten Fenster.",
            "Mindestens ein simuliertes Matchday-Fenster braucht Review.",
            details=[row for row in scenarios if row.get("result") != "pass"],
        ),
    ]
    return checks


def check_row(
    check_id: str,
    passed: bool,
    pass_detail: str,
    fail_detail: str,
    *,
    details: list[Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": check_id,
        "status": "pass" if passed else "review",
        "detail": pass_detail if passed else fail_detail,
    }
    if details:
        row["details"] = details
    return row


def rows_are_chronological(rows: list[dict[str, Any]]) -> bool:
    keys = [chronology_key(row) for row in rows]
    return keys == sorted(keys)


def same_tip_history_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stale = []
    for event in events:
        if "from_tip" not in event or "to_tip" not in event:
            continue
        if str(event.get("from_tip") or "") == str(event.get("to_tip") or ""):
            stale.append(
                {
                    "match_id": event.get("match_id"),
                    "match": event.get("match"),
                    "from_tip": event.get("from_tip"),
                    "to_tip": event.get("to_tip"),
                    "changed_at": event.get("changed_at"),
                }
            )
    return stale


def report_status(checks: list[dict[str, Any]]) -> str:
    return "pass" if all(row.get("status") == "pass" for row in checks) else "review"


def target_summary(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": fixture.get("match_id"),
        "match_number": fixture.get("match_number"),
        "kickoff_utc": fixture.get("kickoff_utc"),
        "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
        "venue": fixture.get("venue"),
        "group": fixture.get("group"),
    }


def empty_report(
    now: datetime,
    final_rows: list[dict[str, Any]],
    all_final_rows: list[dict[str, Any]],
    watch_rows: list[dict[str, Any]],
    history_payload: dict[str, Any],
) -> dict[str, Any]:
    checks = dry_run_checks(final_rows, all_final_rows, watch_rows, history_payload, [])
    checks.append(
        {
            "id": "target_match_available",
            "status": "review",
            "detail": "Kein zukuenftiges Spiel fuer den Matchday-Probelauf gefunden.",
        }
    )
    return {
        "_meta": {"updated_at": now.isoformat()},
        "status": "review",
        "target_match": {},
        "counts": {
            "final_tips": len(final_rows),
            "all_round_final_tips": len(all_final_rows),
            "watchlist": len(watch_rows),
            "history_events": len(history_payload.get("events") or []),
            "scenarios": 0,
        },
        "checks": checks,
        "scenarios": [],
    }


def render_matchday_dry_run_markdown(report: dict[str, Any]) -> str:
    target = report.get("target_match") or {}
    lines = [
        "# Matchday-Probelauf",
        "",
        f"Status: {report.get('status', 'review')}",
        f"Stand: {(report.get('_meta') or {}).get('updated_at', '')}",
        "",
        "## Zielspiel",
        "",
        f"- Spiel: {target.get('match', 'n/a')}",
        f"- Anpfiff: {target.get('kickoff_utc', 'n/a')}",
        f"- Venue: {target.get('venue', 'n/a')}",
        "",
        "## Ergonomie-Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for check in report.get("checks") or []:
        lines.append(
            f"| {check.get('id', '')} | {check.get('status', '')} | {check.get('detail', '')} |"
        )
    lines.extend(
        [
            "",
            "## Simulierte Fenster",
            "",
            "| Fenster | Simulierte Zeit UTC | Status | Due Checks | Quellen | Ergebnis |",
            "|---|---|---|---|---|---|",
        ]
    )
    for scenario in report.get("scenarios") or []:
        lines.append(
            "| {label} | {time} | {status} | {checks} | {sources} | {result} |".format(
                label=scenario.get("label", ""),
                time=scenario.get("simulated_now_utc", ""),
                status=scenario.get("status", ""),
                checks=", ".join(scenario.get("due_checks") or []),
                sources=", ".join(scenario.get("source_ids") or []),
                result=scenario.get("result", ""),
            )
        )
    lines.append("")
    return "\n".join(lines)
