"""Bwin-1X2-Matchquoten aus der freien CDS-API (headless, automatisierbar).

Codex' Befund: Bwin-1X2 war bisher nur per Agent-Chrome pflegbar. Aber die
CDS-`fixture-view`-Antwort (die wir fuer Exact-Score schon nutzen) enthaelt
auch den 1X2-Markt: MarketType `3way`, Period `RegularTime`, Optionen
`[Heim, X, Auswaerts]`. Damit holen wir die 1X2-Quoten OHNE Chrome und
schreiben die `bwin_world_cup_2026`-Zeilen in `data/manual_odds.csv` fort.
-> kann in `update-all`/Briefing laufen (schliesst die Chrome-Luecke).

Read-only nach aussen (GET), schreibt nur `manual_odds.csv`.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .bwin_exact_scores import BWIN_PUBLIC_ACCESS_ID, fetch_bwin_fixture_view, market_parameter
from .exact_scores import load_exact_score_payload, parse_decimal
from .fixtures import load_fixture_payload
from .paths import DATA_DIR

MANUAL_ODDS_PATH = DATA_DIR / "manual_odds.csv"
BWIN_ODDS_SOURCE = "bwin_world_cup_2026"
BWIN_COMPETITION_FIXTURES_URL = "https://row2-cds-api.itsfogo.com/bettingoffer/fixtures"
BWIN_WORLD_CUP_COMPETITION_ID = "0:14"
BWIN_EVENT_URL_BASE = "https://www.bwin.de/de/sports/events"
_DRAW_NAMES = {"x", "unentschieden", "draw", "remis", "tie"}
_FIELDS = ["match_id", "source", "home", "draw", "away", "last_updated"]
_TEAM_ALIASES = {
    "aegypten": "egypt",
    "algerien": "algeria",
    "argentinien": "argentina",
    "australien": "australia",
    "belgien": "belgium",
    "bosnien herzegowina": "bosnia-herzegovina",
    "brasilien": "brazil",
    "deutschland": "germany",
    "elfenbeinkuste": "ivory-coast",
    "england": "england",
    "frankreich": "france",
    "ghana": "ghana",
    "kanada": "canada",
    "kap verde": "cape-verde",
    "kolumbien": "colombia",
    "marokko": "morocco",
    "mexiko": "mexico",
    "niederlande": "netherlands",
    "norwegen": "norway",
    "paraguay": "paraguay",
    "portugal": "portugal",
    "schweiz": "switzerland",
    "senegal": "senegal",
    "spanien": "spain",
    "usa": "usa",
}


def is_regular_time_3way_market(market: dict[str, Any]) -> bool:
    return (
        market_parameter(market, "MarketType") == "3way"
        and market_parameter(market, "Period") == "RegularTime"
    )


def parse_bwin_match_odds(payload: dict[str, Any]) -> dict[str, float] | None:
    """Extrahiert {home, draw, away} Dezimalquoten aus dem 3way/RegularTime-
    Markt der fixture-view-Antwort. None, wenn der Markt fehlt/unvollstaendig."""
    fixture_payload = payload.get("fixture") or payload
    markets = fixture_payload.get("optionMarkets") or payload.get("optionMarkets") or []
    market = next((m for m in markets if is_regular_time_3way_market(m)), None)
    if not market:
        return None
    home = draw = away = None
    rest: list[float] = []
    for option in market.get("options") or []:
        if option.get("status") not in (None, "Visible"):
            continue
        name = str((option.get("name") or {}).get("value") or "").strip()
        odds = parse_decimal((option.get("price") or {}).get("odds"))
        if odds is None:
            continue
        if name.lower() in _DRAW_NAMES:
            draw = odds
        else:
            rest.append(odds)
    # Bwin ordnet [Heim, X, Auswaerts] -> die zwei Nicht-X-Optionen sind
    # Heim (zuerst) und Auswaerts (zuletzt).
    if len(rest) == 2 and draw is not None:
        home, away = rest[0], rest[1]
    if home is None or draw is None or away is None:
        return None
    return {"home": round(home, 4), "draw": round(draw, 4), "away": round(away, 4)}


def build_bwin_competition_fixtures_url(
    *,
    competition_id: str = BWIN_WORLD_CUP_COMPETITION_ID,
) -> str:
    params = {
        "x-bwin-accessid": BWIN_PUBLIC_ACCESS_ID,
        "lang": "de",
        "country": "DE",
        "userCountry": "DE",
        "offerMapping": "All",
        "state": "Latest",
        "fixtureTypes": "Standard",
        "sportIds": "4",
        "regionIds": "6",
        "competitionIds": competition_id,
        "includePrecreatedBetBuilder": "false",
        "supportVirtual": "true",
        "isBettingInsightsEnabled": "false",
        "useRegionalisedConfiguration": "true",
        "includeRelatedFixtures": "false",
    }
    return f"{BWIN_COMPETITION_FIXTURES_URL}?{urlencode(params)}"


def fetch_bwin_competition_fixtures(*, timeout_seconds: int = 20) -> dict[str, Any]:
    api_url = build_bwin_competition_fixtures_url()
    request = Request(
        api_url,
        headers={
            "Accept": "application/json, text/plain, */*",
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
                api_url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)


def _utc_key(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _team_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = _TEAM_ALIASES.get(text, text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _bwin_fixture_name(fixture: dict[str, Any]) -> str:
    name = fixture.get("name")
    if isinstance(name, dict):
        return str(name.get("value") or "")
    return str(name or "")


def _split_bwin_fixture_name(name: str) -> tuple[str, str] | None:
    if "boost" in name.casefold():
        return None
    parts = re.split(r"\s+[-–]\s+", name, maxsplit=1)
    if len(parts) != 2:
        return None
    return _team_key(parts[0]), _team_key(parts[1])


def _bwin_event_url(fixture: dict[str, Any]) -> str:
    name = _bwin_fixture_name(fixture).casefold()
    slug = quote(re.sub(r"\s+[-–]\s+", "-", name).replace(" ", "-"), safe="-")
    fixture_id = quote(str(fixture.get("id") or fixture.get("fixtureId") or ""), safe="")
    return f"{BWIN_EVENT_URL_BASE}/{slug}-{fixture_id}"


def _fixture_index(fixtures: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for fixture in fixtures:
        kickoff = _utc_key(fixture.get("kickoff_utc"))
        if not kickoff:
            continue
        key = (kickoff, _team_key(fixture.get("home_team")), _team_key(fixture.get("away_team")))
        indexed[key] = fixture
    return indexed


def bwin_competition_events(
    payload: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_key = _fixture_index(fixtures)
    events: list[dict[str, Any]] = []
    for bwin_fixture in payload.get("fixtures") or []:
        teams = _split_bwin_fixture_name(_bwin_fixture_name(bwin_fixture))
        kickoff = _utc_key(bwin_fixture.get("startDate") or bwin_fixture.get("date"))
        odds = parse_bwin_match_odds({"fixture": bwin_fixture})
        if not teams or not kickoff or not odds:
            continue
        fixture = by_key.get((kickoff, teams[0], teams[1]))
        if not fixture:
            continue
        events.append(
            {
                "match_id": fixture["match_id"],
                "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                "event_url": _bwin_event_url(bwin_fixture),
                "event_name": _bwin_fixture_name(bwin_fixture),
                "kickoff_utc": fixture.get("kickoff_utc"),
                "odds": odds,
            }
        )
    return events


def _read_manual_odds_rows() -> list[dict[str, str]]:
    if not MANUAL_ODDS_PATH.exists():
        return []
    with MANUAL_ODDS_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_manual_odds_rows(rows: list[dict[str, str]]) -> None:
    with MANUAL_ODDS_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in _FIELDS})


def apply_bwin_odds_to_csv(
    fresh: dict[str, dict[str, float]],
    rows: list[dict[str, str]],
    now_iso: str,
) -> tuple[list[dict[str, str]], int, int]:
    """Aktualisiert/ergaenzt die bwin_world_cup_2026-Zeile je match_id mit
    den frischen 1X2-Quoten. Andere Zeilen bleiben unberuehrt. Gibt
    (neue_rows, updated, added) zurueck."""
    updated = 0
    seen_bwin: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        mid = row.get("match_id")
        if row.get("source") == BWIN_ODDS_SOURCE and mid in fresh:
            o = fresh[mid]
            row = {
                **row,
                "home": f"{o['home']:.4f}",
                "draw": f"{o['draw']:.4f}",
                "away": f"{o['away']:.4f}",
                "last_updated": now_iso,
            }
            updated += 1
            seen_bwin.add(mid)
        out.append(row)
    added = 0
    for mid, o in fresh.items():
        if mid in seen_bwin:
            continue
        out.append(
            {
                "match_id": mid,
                "source": BWIN_ODDS_SOURCE,
                "home": f"{o['home']:.4f}",
                "draw": f"{o['draw']:.4f}",
                "away": f"{o['away']:.4f}",
                "last_updated": now_iso,
            }
        )
        added += 1
    return out, updated, added


def refresh_bwin_match_odds(*, write: bool = True, limit: int | None = None) -> dict[str, Any]:
    payload = load_exact_score_payload()
    visible_events = payload.get("visible_events") or []
    fixtures = load_fixture_payload().get("fixtures", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    fresh: dict[str, dict[str, float]] = {}
    diagnostics: list[dict[str, Any]] = []
    attempted = 0
    try:
        competition_payload = fetch_bwin_competition_fixtures()
        competition_events = bwin_competition_events(competition_payload, fixtures)
        for event in competition_events:
            if limit is not None and attempted >= limit:
                break
            match_id = event["match_id"]
            attempted += 1
            fresh[match_id] = event["odds"]
            diagnostics.append(
                {
                    "match_id": match_id,
                    "status": "ok",
                    "source": "competition_fixtures",
                    "event_url": event["event_url"],
                    **event["odds"],
                }
            )
    except Exception as exc:  # pragma: no cover - live network diagnostics
        diagnostics.append({"status": "competition_error", "error": str(exc)})
    for event in visible_events:
        match_id = event.get("match_id")
        url = event.get("event_url")
        if not match_id or not url:
            continue
        if match_id in fresh:
            continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        try:
            data = fetch_bwin_fixture_view(url)
            odds = parse_bwin_match_odds(data)
            if odds:
                fresh[match_id] = odds
                diagnostics.append({"match_id": match_id, "status": "ok", **odds})
            else:
                diagnostics.append({"match_id": match_id, "status": "no_3way_market"})
        except Exception as exc:  # pragma: no cover - live network diagnostics
            diagnostics.append({"match_id": match_id, "status": "error", "error": str(exc)})

    updated = added = 0
    if fresh and write:
        rows, updated, added = apply_bwin_odds_to_csv(fresh, _read_manual_odds_rows(), now_iso)
        _write_manual_odds_rows(rows)
        # market_signals.json gleich mitziehen, damit Konsens/Dashboard nicht
        # einen update-all-Lauf hinterherhinken (refresh-odds laeuft frueher).
        from .odds import refresh_market_data

        refresh_market_data()
    return {
        "_meta": {
            "source": "bwin_de_cds_3way_regular_time",
            "api_base_url": "https://row2-cds-api.itsfogo.com/bettingoffer/fixture-view",
            "updated_at": now_iso,
            "events_probed": attempted,
            "matches_with_odds": len(fresh),
            "csv_rows_updated": updated,
            "csv_rows_added": added,
            "note": "Bwin-1X2 headless ueber dieselbe CDS-API wie Exact-Score; kein Chrome noetig.",
        },
        "items": diagnostics,
    }
