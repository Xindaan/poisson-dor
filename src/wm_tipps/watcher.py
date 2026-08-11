from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .context import refresh_context
from .dashboard import build_dashboard_payload, export_tips
from .fixtures import load_fixture_payload, refresh_fixtures, all_teams
from .io import write_json
from .matchday_command import build_matchday_command_center
from .model import build_predictions
from .news import refresh_news
from .odds import refresh_market_data
from .paths import DATA_DIR
from .source_watch import refresh_source_watch
from .strength import build_team_strengths


def hours_until_next_kickoff(fixtures: list[dict[str, Any]], now: datetime | None = None) -> float | None:
    now = now or datetime.now(timezone.utc)
    upcoming: list[float] = []
    for fixture in fixtures:
        kickoff_text = fixture.get("kickoff_utc")
        if not kickoff_text:
            continue
        try:
            kickoff = datetime.fromisoformat(str(kickoff_text).replace("Z", "+00:00"))
        except ValueError:
            continue
        hours = (kickoff - now).total_seconds() / 3600
        if hours >= 0:
            upcoming.append(hours)
    return min(upcoming) if upcoming else None


def cadence_seconds(hours_left: float | None) -> int:
    if hours_left is None:
        return 24 * 3600
    if hours_left <= 1.5:
        return 15 * 60
    if hours_left <= 24:
        return 2 * 3600
    if hours_left <= 48:
        return 6 * 3600
    return 24 * 3600


def run_refresh_cycle(*, live_news: bool = False, refresh_fixture_source: bool = False) -> dict[str, Any]:
    fixture_payload = refresh_fixtures(live=True) if refresh_fixture_source else load_fixture_payload()
    fixtures = fixture_payload.get("fixtures", [])
    teams = all_teams(fixture_payload)
    context = refresh_context(fixtures)
    strengths = build_team_strengths(fixture_payload)
    markets = refresh_market_data()
    source_watch = refresh_source_watch(fixtures, market_payload=markets, probe_live=live_news)
    news = refresh_news(teams, live=live_news)
    predictions = build_predictions()
    command_center = build_matchday_command_center(
        fixture_payload,
        predictions,
        write=True,
    )
    dashboard = build_dashboard_payload()
    exports = export_tips()
    hours_left = hours_until_next_kickoff(fixtures)
    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "next_kickoff_hours": None if hours_left is None else round(hours_left, 3),
        "next_cadence_seconds": cadence_seconds(hours_left),
        "live_news": live_news,
        "fixtures": len(fixtures),
        "news_items": len(news.get("items", [])),
        "market_items": len(markets.get("markets", [])) + len(markets.get("odds", [])),
        "source_watch_alerts": sum(
            1 for source in source_watch.get("sources", []) if source.get("status") != "ok"
        ),
        "strengths": len(strengths) - 1,
        "predictions": len(predictions.get("predictions", [])),
        "watchlist": len(dashboard.get("watchlist", [])),
        "command_focus": (command_center.get("summary") or {}).get("focus_items", 0),
        "exported_tips": len(exports.get("final_tips", [])),
    }
    write_json(DATA_DIR / "watch_state.json", state)
    return state


def watch(
    *,
    live_news: bool = False,
    refresh_fixture_source: bool = False,
    iterations: int = 0,
    sleep_cap_seconds: int | None = None,
) -> list[dict[str, Any]]:
    states = []
    count = 0
    while True:
        state = run_refresh_cycle(live_news=live_news, refresh_fixture_source=refresh_fixture_source)
        states.append(state)
        count += 1
        if iterations and count >= iterations:
            return states
        sleep_for = state["next_cadence_seconds"]
        if sleep_cap_seconds is not None:
            sleep_for = min(sleep_for, sleep_cap_seconds)
        time.sleep(sleep_for)
