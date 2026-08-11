from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from .dashboard import build_watchlist, final_tips
from .fixtures import load_fixture_payload
from .io import read_json, write_json
from .paths import DATA_DIR, EXPORTS_DIR
from .team_intel import (
    build_matchday_checklist,
    load_team_intel_sources,
    parse_datetime,
    reachability_bucket,
)


MATCHDAY_COMMAND_JSON = DATA_DIR / "matchday_command_center.json"
MATCHDAY_COMMAND_STATE = DATA_DIR / "matchday_command_state.json"
MATCHDAY_COMMAND_MARKDOWN = EXPORTS_DIR / "matchday_command_center.md"
LOCAL_TZ = ZoneInfo("Europe/Berlin")

CHECK_LABELS = {
    "weather_first_pass": "T-72 Wetter",
    "travel_context": "T-48 Reise",
    "pitch_context": "T-24 Pitch",
    "expected_lineup": "T-24 Expected Lineup",
    "final_weather": "T-6 Wetter final",
    "confirmed_lineup": "T-90 Confirmed Lineup",
}

ACTION_SIGNAL_HINTS = {
    "weather_first_pass": {"weather", "heat", "humidity", "wind", "storm", "alerts", "temperature", "rain"},
    "travel_context": {"travel", "venue", "general"},
    "pitch_context": {"pitch", "venue"},
    "expected_lineup": {"expected_lineup", "lineup", "squad", "roster", "coach", "injury"},
    "final_weather": {"weather", "heat", "humidity", "wind", "storm", "alerts", "temperature", "rain"},
    "confirmed_lineup": {"confirmed_lineup", "lineup"},
}

LINEUP_CHECKS = {"expected_lineup", "confirmed_lineup"}
VALID_STATUSES = {"offen", "geprueft", "kritisch", "warte_auf_lineup", "gespielt"}


def build_matchday_command_center(
    fixtures: dict[str, Any] | None = None,
    predictions_payload: dict[str, Any] | None = None,
    team_intel_payload: dict[str, Any] | None = None,
    state_payload: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    fixtures = fixtures or load_fixture_payload()
    if predictions_payload is None:
        predictions_payload = read_json(DATA_DIR / "predictions.json", {"predictions": []})
    if team_intel_payload is None:
        team_intel_payload = load_team_intel_sources()
    if state_payload is None:
        state_payload = load_matchday_command_state()
    now = normalize_now(now)

    predictions = predictions_payload.get("predictions") or []
    predictions_by_id = {row.get("match_id"): row for row in predictions if row.get("match_id")}
    watchlist = build_watchlist(predictions)
    watch_by_id = {row.get("match_id"): row for row in watchlist if row.get("match_id")}
    final_by_id = {row.get("match_id"): row for row in final_tips(predictions) if row.get("match_id")}
    sources = team_intel_payload.get("sources") or []
    source_lookup = {source.get("id"): source for source in sources if source.get("id")}
    checklist = build_matchday_checklist(fixtures, team_intel_payload, now=now)

    rows = []
    for item in checklist:
        match_id = item.get("match_id")
        prediction = predictions_by_id.get(match_id, {})
        watch = watch_by_id.get(match_id, {})
        final_tip = final_by_id.get(match_id, {})
        actions = build_actions(item, source_lookup, state_payload, now)
        rows.append(
            command_row(
                item,
                prediction,
                final_tip,
                watch,
                actions,
                source_lookup,
                state_payload,
                now,
            )
        )

    rows = sorted(rows, key=command_sort_key)
    focus_items = [row for row in rows if is_focus_item(row, now)]
    next_items = sorted(
        [row for row in rows if row.get("next_action_at")],
        key=lambda row: (row.get("next_action_at") or "", row.get("kickoff_utc") or ""),
    )[:12]
    summary = command_summary(rows, focus_items, next_items, now)
    payload = {
        "_meta": {
            "updated_at": now.isoformat(),
            "local_date": local_date(now),
            "timezone": str(LOCAL_TZ),
            "state_path": str(MATCHDAY_COMMAND_STATE),
            "note": "Chronological matchday command center: due checks, source links, watch status and manual checked-state overlays.",
        },
        "summary": summary,
        "quality": _quality_snapshot(),
        "today_items": focus_items,
        "next_items": next_items,
        "items": rows,
    }

    if write:
        ensure_state_template()
        write_json(MATCHDAY_COMMAND_JSON, payload)
        MATCHDAY_COMMAND_MARKDOWN.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def normalize_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def load_matchday_command_state(path=MATCHDAY_COMMAND_STATE) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "checks": {}, "matches": {}})
    if not isinstance(payload, dict):
        return {"_meta": {}, "checks": {}, "matches": {}}
    return {
        "_meta": payload.get("_meta") or {},
        "checks": payload.get("checks") if isinstance(payload.get("checks"), dict) else {},
        "matches": payload.get("matches") if isinstance(payload.get("matches"), dict) else {},
    }


def ensure_state_template(path=MATCHDAY_COMMAND_STATE) -> None:
    if path.exists():
        return
    write_json(
        path,
        {
            "_meta": {
                "note": (
                    "Optional manual overlay. Example check key: ga-001:travel_context "
                    "with status geprueft/offen/kritisch/warte_auf_lineup plus note."
                )
            },
            "checks": {},
            "matches": {},
        },
    )


def build_actions(
    checklist_row: dict[str, Any],
    source_lookup: dict[str, dict[str, Any]],
    state_payload: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    match_id = str(checklist_row.get("match_id") or "")
    source_ids = checklist_row.get("source_ids") or []
    actions = []
    for check in checklist_row.get("checks") or []:
        check_type = str(check.get("type") or "")
        due_at = parse_datetime(check.get("due_at"))
        check_id = f"{match_id}:{check_type}"
        state = check_state(state_payload, check_id)
        status = action_status(check_type, due_at, state, now)
        actions.append(
            {
                "id": check_id,
                "type": check_type,
                "label": CHECK_LABELS.get(check_type, check_type),
                "due_at": check.get("due_at"),
                "due_local": local_datetime(due_at),
                "is_due": bool(due_at and due_at <= now and status != "geprueft"),
                "status": status,
                "note": state.get("note"),
                "checked_at": state.get("checked_at"),
                "source_links": source_links_for_action(check_type, source_ids, source_lookup),
            }
        )
    return sorted(actions, key=lambda row: row.get("due_at") or "")


def check_state(state_payload: dict[str, Any], check_id: str) -> dict[str, Any]:
    raw = (state_payload.get("checks") or {}).get(check_id) or {}
    return raw if isinstance(raw, dict) else {}


def action_status(
    check_type: str,
    due_at: datetime | None,
    state: dict[str, Any],
    now: datetime,
) -> str:
    status = state.get("status")
    if status in VALID_STATUSES:
        return status
    if due_at and due_at <= now and check_type in LINEUP_CHECKS:
        return "warte_auf_lineup"
    return "offen"


def command_row(
    checklist_row: dict[str, Any],
    prediction: dict[str, Any],
    final_tip: dict[str, Any],
    watch: dict[str, Any],
    actions: list[dict[str, Any]],
    source_lookup: dict[str, dict[str, Any]],
    state_payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    match_id = str(checklist_row.get("match_id") or "")
    due_actions = [row for row in actions if row.get("is_due")]
    upcoming_actions = [
        row
        for row in actions
        if not parse_datetime(row.get("due_at")) or parse_datetime(row.get("due_at")) > now
    ]
    next_action = upcoming_actions[0] if upcoming_actions else None
    status = match_status(
        match_id, watch, actions, state_payload, now,
        kickoff=parse_datetime(checklist_row.get("kickoff_utc")),
    )
    return {
        "match_id": match_id,
        "match_number": checklist_row.get("match_number"),
        "kickoff_utc": checklist_row.get("kickoff_utc"),
        "kickoff_local": local_datetime(parse_datetime(checklist_row.get("kickoff_utc"))),
        "match": checklist_row.get("match"),
        "group": final_tip.get("group"),
        "venue": checklist_row.get("venue"),
        "host_country": checklist_row.get("host_country"),
        "tip": final_tip.get("tip") or (prediction.get("recommended_tip") or {}).get("tip"),
        "expected_points": final_tip.get("expected_points") or (prediction.get("recommended_tip") or {}).get("expected_points"),
        "stability": final_tip.get("status") or prediction.get("stability"),
        "status": status,
        "status_detail": status_detail(status, watch, due_actions),
        "reasons": watch.get("reasons") or [],
        "watch_details": watch.get("details") or [],
        "due_actions": due_actions,
        "next_actions": upcoming_actions[:2],
        "next_action_at": next_action.get("due_at") if next_action else None,
        "actions": actions,
        "source_links": source_links_for_ids(checklist_row.get("source_ids") or [], source_lookup),
    }


def match_status(
    match_id: str,
    watch: dict[str, Any],
    actions: list[dict[str, Any]],
    state_payload: dict[str, Any],
    now: datetime,
    kickoff: datetime | None = None,
) -> str:
    # Terminal: sobald angepfiffen, entfallen alle Pre-Match-Checks. Ohne das
    # blieben gespielte Spiele ewig 'warte_auf_lineup' (ihre Lineup-Checks
    # sind faellig <= now und werden nie 'geprueft') und standen als Fokus
    # ganz oben.
    if kickoff is not None and kickoff <= now:
        return "gespielt"
    override = ((state_payload.get("matches") or {}).get(match_id) or {}).get("status")
    if override in VALID_STATUSES:
        return override
    if "kritische News" in set(watch.get("reasons") or []):
        return "kritisch"
    due_or_checked = [
        action
        for action in actions
        if (parse_datetime(action.get("due_at")) and parse_datetime(action.get("due_at")) <= now)
    ]
    if due_or_checked and all(action.get("status") == "geprueft" for action in due_or_checked):
        return "geprueft"
    if any(action.get("is_due") and action.get("type") in LINEUP_CHECKS for action in actions):
        return "warte_auf_lineup"
    return "offen"


def status_detail(status: str, watch: dict[str, Any], due_actions: list[dict[str, Any]]) -> str:
    if status == "gespielt":
        return "Spiel ist angepfiffen/vorbei — Pre-Match-Checks entfallen."
    if status == "kritisch":
        titles = [detail.get("title") for detail in watch.get("details") or [] if detail.get("title")]
        return titles[0] if titles else "Kritisches Watchlist-Signal vor Tippabgabe pruefen."
    if status == "warte_auf_lineup":
        return "Lineup-Fenster ist offen; bestaetigte oder erwartete Aufstellung pruefen."
    if status == "geprueft":
        return "Alle aktuell faelligen Checks sind als geprueft markiert."
    if due_actions:
        return f"{len(due_actions)} Check(s) faellig."
    return "Naechster Check ist noch nicht faellig."


def is_focus_item(row: dict[str, Any], now: datetime) -> bool:
    if row.get("status") == "gespielt":
        return False  # angepfiffen/vorbei -> kein Fokus mehr
    if row.get("status") in {"kritisch", "warte_auf_lineup"}:
        return True
    for action in row.get("due_actions") or []:
        due_at = parse_datetime(action.get("due_at"))
        if due_at and local_date(due_at) == local_date(now):
            return True
    return False


def command_summary(
    rows: list[dict[str, Any]],
    focus_items: list[dict[str, Any]],
    next_items: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    due_now = [row for row in rows if row.get("due_actions")]
    return {
        "matches": len(rows),
        "focus_items": len(focus_items),
        "critical": sum(1 for row in rows if row.get("status") == "kritisch"),
        "waiting_lineup": sum(1 for row in rows if row.get("status") == "warte_auf_lineup"),
        "open_due": len(due_now),
        "checked": sum(1 for row in rows if row.get("status") == "geprueft"),
        "played": sum(1 for row in rows if row.get("status") == "gespielt"),
        "next_check_at": (next_items[0].get("next_action_at") if next_items else None),
        "local_date": local_date(now),
    }


def command_sort_key(row: dict[str, Any]) -> tuple[int, str, int]:
    kickoff = parse_datetime(row.get("kickoff_utc"))
    kickoff_key = int(kickoff.timestamp()) if kickoff else 0
    return (kickoff_key, str(row.get("kickoff_utc") or ""), int(row.get("match_number") or 9999))


def source_links_for_action(
    check_type: str,
    source_ids: list[str],
    source_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    hints = ACTION_SIGNAL_HINTS.get(check_type, set())
    rows = []
    for source_id in source_ids:
        source = source_lookup.get(source_id)
        if not source:
            continue
        signals = set(source.get("signals") or [])
        if hints and not (signals & hints):
            continue
        rows.append(source_link(source))
    return rows[:6] or source_links_for_ids(source_ids, source_lookup)[:4]


def source_links_for_ids(
    source_ids: list[str],
    source_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for source_id in source_ids:
        source = source_lookup.get(source_id)
        if source:
            rows.append(source_link(source))
    return sorted(rows, key=lambda row: (row.get("reachability") != "machine_reachable", row.get("id") or ""))[:8]


def source_link(source: dict[str, Any]) -> dict[str, Any]:
    status = str(source.get("status") or "unknown")
    return {
        "id": source.get("id"),
        "name": source.get("name") or source.get("id"),
        "url": source.get("url"),
        "status": status,
        "reachability": reachability_bucket(status),
        "signals": source.get("signals") or [],
        "official": source.get("official") is True,
    }


def local_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.astimezone(LOCAL_TZ).isoformat()


def local_date(value: datetime) -> str:
    return value.astimezone(LOCAL_TZ).date().isoformat()


def _quality_snapshot() -> dict[str, Any]:
    """Quoten-/Daten-Quality aus dem letzten update-all-Lauf (T-0127).
    Macht `quality_status=warning|failed` sichtbar, statt nur im JSON zu stehen."""
    status = read_json(DATA_DIR / "update_all_status.json", {})
    if not isinstance(status, dict):
        return {}
    return {
        "status": status.get("quality_status"),
        "messages": status.get("quality_messages") or [],
    }


def _quality_banner_lines(payload: dict[str, Any]) -> list[str]:
    quality = payload.get("quality") or {}
    status = quality.get("status")
    if status not in {"warning", "failed"}:
        return []
    label = "FEHLER" if status == "failed" else "WARNUNG"
    msgs = "; ".join(quality.get("messages") or []) or "keine Details"
    return [f"> **Daten-Qualitaet {label}:** {msgs}", ""]


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "# Matchday Command Center",
        "",
        f"Stand: {(payload.get('_meta') or {}).get('updated_at', '')}",
        f"Lokaler Tag: {summary.get('local_date', '')}",
        "",
        *_quality_banner_lines(payload),
        "| Fokus | Kritisch | Warte Lineup | Faellige Spiele | Naechster Check |",
        "|---:|---:|---:|---:|---|",
        "| {focus} | {critical} | {lineup} | {open_due} | {next_check} |".format(
            focus=summary.get("focus_items", 0),
            critical=summary.get("critical", 0),
            lineup=summary.get("waiting_lineup", 0),
            open_due=summary.get("open_due", 0),
            next_check=summary.get("next_check_at") or "n/a",
        ),
        "",
        "## Heute / Fokus",
        "",
    ]
    append_rows(lines, payload.get("today_items") or [])
    lines.extend(["", "## Naechste Checks", ""])
    append_rows(lines, payload.get("next_items") or [])
    return "\n".join(lines) + "\n"


def append_rows(lines: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        lines.append("- Keine faelligen Fokus-Checks.")
        return
    for row in rows:
        actions = row.get("due_actions") or row.get("next_actions") or []
        action_text = ", ".join(
            f"{action.get('label')} ({action.get('due_local') or action.get('due_at')})"
            for action in actions[:3]
        ) or "kein Check"
        links = ", ".join(
            f"[{link.get('name')}]({link.get('url')})"
            for link in (row.get("source_links") or [])[:4]
            if link.get("url")
        )
        lines.append(
            "- {match} ({kickoff}) - {status}; Tipp {tip}; Checks: {checks}".format(
                match=row.get("match"),
                kickoff=row.get("kickoff_local") or row.get("kickoff_utc"),
                status=row.get("status"),
                tip=row.get("tip") or "n/a",
                checks=action_text,
            )
        )
        if row.get("status_detail"):
            lines.append(f"  - Hinweis: {row.get('status_detail')}")
        if links:
            lines.append(f"  - Quellen: {links}")
