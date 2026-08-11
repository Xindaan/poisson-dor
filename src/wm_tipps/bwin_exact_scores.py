from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import re
import subprocess

from .exact_scores import SCORE_RE, load_exact_score_payload, normalise_exact_score_items, parse_decimal
from .fixtures import load_fixture_payload
from .io import write_json
from .paths import DATA_DIR


BWIN_EXACT_SCORE_PATH = DATA_DIR / "manual_exact_score_odds.json"
BWIN_CDS_BASE_URL = "https://row2-cds-api.itsfogo.com/bettingoffer/fixture-view"
BWIN_PUBLIC_ACCESS_ID = "NWQyNmIwMjUtZDQ3NC00NDQxLWI5YTktNjdkYjZjOTg1OWEz"
BWIN_FIXTURE_ID_RE = re.compile(r"2(?::|%3A)(\d+)", re.IGNORECASE)


def extract_bwin_fixture_id(event_url: str) -> str | None:
    match = BWIN_FIXTURE_ID_RE.search(event_url or "")
    if not match:
        return None
    return f"2:{match.group(1)}"


def build_bwin_fixture_view_url(
    bwin_fixture_id: str,
    *,
    public_access_id: str = BWIN_PUBLIC_ACCESS_ID,
    lang: str = "de",
    country: str = "DE",
) -> str:
    params = {
        "x-bwin-accessid": public_access_id,
        "lang": lang,
        "country": country,
        "userCountry": country,
        "offerMapping": "All",
        "scoreboardMode": "Full",
        "fixtureIds": bwin_fixture_id,
        "state": "Latest",
        "includePrecreatedBetBuilder": "false",
        "supportVirtual": "true",
        "isBettingInsightsEnabled": "false",
        "useRegionalisedConfiguration": "true",
        "includeRelatedFixtures": "false",
    }
    return f"{BWIN_CDS_BASE_URL}?{urlencode(params)}"


def fetch_bwin_fixture_view(event_url: str, *, timeout_seconds: int = 20) -> dict[str, Any]:
    bwin_fixture_id = extract_bwin_fixture_id(event_url)
    if not bwin_fixture_id:
        raise ValueError(f"Bwin fixture id fehlt in URL: {event_url}")
    api_url = build_bwin_fixture_view_url(bwin_fixture_id)
    request = Request(
        api_url,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": event_url,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError):
        return fetch_bwin_fixture_view_with_curl(api_url, event_url, timeout_seconds=timeout_seconds)


def fetch_bwin_fixture_view_with_curl(
    api_url: str,
    event_url: str,
    *,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            "curl",
            "-L",
            "-sS",
            "--fail",
            "--max-time",
            str(timeout_seconds),
            "-A",
            (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "-H",
            "accept: application/json, text/plain, */*",
            "-H",
            f"referer: {event_url}",
            api_url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def market_parameter(market: dict[str, Any], key: str) -> str | None:
    for param in market.get("parameters") or []:
        if param.get("key") == key:
            value = param.get("value")
            return str(value) if value is not None else None
    return None


def is_regular_time_correct_score_market(market: dict[str, Any]) -> bool:
    if market_parameter(market, "MarketType") != "CorrectScore":
        return False
    return market_parameter(market, "Period") == "RegularTime"


def parse_bwin_exact_score_item(
    payload: dict[str, Any],
    visible_event: dict[str, Any],
    fixture: dict[str, Any] | None = None,
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    fixture_payload = payload.get("fixture") or {}
    markets = fixture_payload.get("optionMarkets") or []
    market = next((row for row in markets if is_regular_time_correct_score_market(row)), None)
    if not market:
        raise ValueError(f"Kein Regular-Time-Correct-Score-Markt fuer {visible_event.get('match_id')}")

    prices: list[dict[str, Any]] = []
    other_selection: dict[str, Any] | None = None
    for option in market.get("options") or []:
        if option.get("status") != "Visible":
            continue
        name = str((option.get("name") or {}).get("value") or "").strip()
        decimal_odds = parse_decimal((option.get("price") or {}).get("odds"))
        if decimal_odds is None:
            continue
        if SCORE_RE.fullmatch(name):
            prices.append({"score": name, "decimal_odds": decimal_odds})
        else:
            other_selection = {"selection": name, "decimal_odds": decimal_odds}

    match = visible_event.get("match") or ""
    home_team = (fixture or {}).get("home_team")
    away_team = (fixture or {}).get("away_team")
    if not home_team and " - " in match:
        home_team, away_team = match.split(" - ", 1)
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    item = {
        "away_team": away_team,
        "bwin_fixture_id": extract_bwin_fixture_id(visible_event.get("event_url", "")),
        "event_url": visible_event.get("event_url"),
        "expanded": True,
        "has_other_selection": other_selection is not None,
        "home_team": home_team,
        "market": "exact_score_regular_time",
        "market_id": market.get("id"),
        "market_name": (market.get("name") or {}).get("value"),
        "match_id": visible_event.get("match_id"),
        "observed_at": observed_at,
        "other_selection_name": (other_selection or {}).get("selection"),
        "other_selection_odds": (other_selection or {}).get("decimal_odds"),
        "prices": prices,
        "regular_time_only": True,
        "source": "bwin_de",
        "source_type": "bookmaker_exact_score",
        "total_bwin_market_count": len(markets),
    }
    return normalise_exact_score_items([item])[0]


def import_bwin_exact_scores(
    *,
    include_existing: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    payload = load_exact_score_payload()
    fixtures = {
        row.get("match_id"): row
        for row in load_fixture_payload().get("fixtures", [])
        if row.get("match_id")
    }
    visible_events = payload.get("visible_events") or []
    existing = {
        row.get("match_id"): row
        for row in payload.get("items") or []
        if row.get("match_id")
    }
    observed_at = datetime.now(timezone.utc).isoformat()
    diagnostics: list[dict[str, Any]] = []
    attempted = 0
    for event in visible_events:
        match_id = event.get("match_id")
        if not match_id:
            continue
        if not include_existing and match_id in existing:
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        try:
            api_payload = fetch_bwin_fixture_view(event.get("event_url", ""))
            existing[match_id] = parse_bwin_exact_score_item(
                api_payload,
                event,
                fixtures.get(match_id),
                observed_at=observed_at,
            )
            diagnostics.append({"match_id": match_id, "status": "imported", "prices": len(existing[match_id]["prices"])})
        except Exception as exc:  # pragma: no cover - live network diagnostics
            diagnostics.append({"match_id": match_id, "status": "error", "error": str(exc)})

    imported_ids = set(existing)
    updated_visible = []
    for event in visible_events:
        row = dict(event)
        row["status"] = "imported_exact_score" if row.get("match_id") in imported_ids else "event_visible_not_imported"
        updated_visible.append(row)
    updated = {
        "_meta": {
            **(payload.get("_meta") or {}),
            "api_base_url": BWIN_CDS_BASE_URL,
            "cost": "free",
            "note": (
                "Bwin.de CDS exact-score snapshot. Regular-time exact-score prices are "
                "display/watch signals only until historical calibration allows blending."
            ),
            "source": "bwin_de_exact_score_regular_time",
            "updated_at": observed_at,
        },
        "items": sorted(existing.values(), key=lambda row: row.get("match_id", "")),
        "visible_events": updated_visible,
    }
    write_json(BWIN_EXACT_SCORE_PATH, updated)
    return {
        "updated_at": observed_at,
        "visible_events": len(visible_events),
        "imported_matches": len(existing),
        "diagnostics": diagnostics,
    }
