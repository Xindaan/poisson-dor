from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib import parse, request

from .io import read_json, write_json
from .paths import DATA_DIR


HISTORICAL_MARKET_LINES_PATH = DATA_DIR / "historical_market_lines.json"
HISTORICAL_MARKET_LINE_SOURCES_PATH = DATA_DIR / "historical_market_line_sources.json"
CHECKBESTODDS_BASE_URL = "https://checkbestodds.com"
CHECKBESTODDS_ARCHIVE_URLS = {
    "2014": f"{CHECKBESTODDS_BASE_URL}/football-odds/archive-world-cup-2014",
    "2018": f"{CHECKBESTODDS_BASE_URL}/football-odds/archive-world-cup-2018",
    "2022": f"{CHECKBESTODDS_BASE_URL}/football-odds/archive-world-cup-2022",
}
CHECKBESTODDS_MORE_ODDS_TYPES = (
    "0,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,24,25,26,27,28,29,30,31,32,33,34,35,36"
)

MATCH_LINK_RE = re.compile(
    r'<a\s+href="(?P<href>(?:https?://checkbestodds\.com)?/football-odds/world-cup-\d{4}/[^"]+/\d+)"'
    r'[^>]*>(?P<match>[^<]+)</a>',
    re.IGNORECASE,
)
MARKET_HEADER_RE = re.compile(
    r'<div\s+id="(?P<id>[^"]+)"\s+class="tblehead"[^>]*>.*?<i>(?P<title>.*?)</i>.*?</div>',
    re.IGNORECASE | re.DOTALL,
)
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
SORT_ODD_RE = re.compile(r'toSort\s+noDsp">([0-9]+(?:\.[0-9]+)?)</span>', re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def load_historical_market_payload(
    path=HISTORICAL_MARKET_LINES_PATH,
) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "items": []})
    if isinstance(payload, list):
        payload = {"_meta": {}, "items": payload}
    if not isinstance(payload, dict):
        return {"_meta": {}, "items": []}
    return {
        "_meta": payload.get("_meta") or {},
        "items": normalise_historical_market_items(payload.get("items") or []),
    }


def load_historical_market_source_audit(
    path=HISTORICAL_MARKET_LINE_SOURCES_PATH,
) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "sources": [], "decision": {}})
    if not isinstance(payload, dict):
        return {"_meta": {}, "sources": [], "decision": {}}
    return {
        "_meta": payload.get("_meta") or {},
        "sources": [row for row in payload.get("sources", []) if isinstance(row, dict)],
        "decision": payload.get("decision") or {},
    }


def normalise_historical_market_items(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        row = dict(item)
        markets = row.get("markets") or {}
        over_under = []
        for line in markets.get("over_under") or []:
            normalised_line = normalise_over_under_market(line)
            if normalised_line:
                over_under.append(normalised_line)
        handicap = []
        for line in markets.get("handicap") or []:
            normalised_line = normalise_handicap_market(line)
            if normalised_line:
                handicap.append(normalised_line)
        row["markets"] = {
            "over_under": over_under,
            "btts": normalise_btts_market(markets.get("btts")),
            "handicap": handicap,
        }
        row["market_counts"] = market_counts(row["markets"])
        normalised.append(row)
    return normalised


def normalise_over_under_market(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    line = parse_float(row.get("line"))
    over = parse_probability(row.get("over_probability"))
    under = parse_probability(row.get("under_probability"))
    if line is None or over is None or under is None:
        return None
    return {
        **dict(row),
        "line": line,
        "over_probability": over,
        "under_probability": under,
    }


def normalise_btts_market(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    yes = parse_probability(row.get("yes_probability"))
    no = parse_probability(row.get("no_probability"))
    if yes is None or no is None:
        return None
    return {**dict(row), "yes_probability": yes, "no_probability": no}


def normalise_handicap_market(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    line = parse_float(row.get("line"))
    home = parse_probability(row.get("home_cover_probability"))
    away = parse_probability(row.get("away_cover_probability"))
    if line is None or home is None or away is None:
        return None
    return {
        **dict(row),
        "team": row.get("team") or "home",
        "line": line,
        "home_cover_probability": home,
        "away_cover_probability": away,
    }


def parse_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_probability(value: Any) -> float | None:
    parsed = parse_float(value)
    if parsed is None or parsed <= 0 or parsed >= 1:
        return None
    return parsed


def market_counts(markets: Mapping[str, Any]) -> dict[str, int]:
    return {
        "over_under": len(markets.get("over_under") or []),
        "btts": 1 if markets.get("btts") else 0,
        "handicap": len(markets.get("handicap") or []),
    }


def match_key(match: Any) -> str:
    return re.sub(r"\s+", " ", str(match or "").strip().lower())


def historical_markets_by_match(
    payload: Mapping[str, Any] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    payload = payload if payload is not None else load_historical_market_payload()
    lookup = {}
    for item in payload.get("items") or []:
        tournament = str(item.get("tournament") or "")
        match = match_key(item.get("match"))
        if tournament and match:
            lookup[(tournament, match)] = item
    return lookup


def apply_historical_market_lines(
    tournament: str,
    rows: Iterable[Mapping[str, Any]],
    payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    lookup = historical_markets_by_match(payload)
    enriched: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        item = lookup.get((str(tournament), match_key(next_row.get("match"))))
        if item:
            markets = item.get("markets") or {}
            if markets.get("over_under"):
                next_row["pre_over_under"] = markets["over_under"]
            if markets.get("btts"):
                next_row["pre_btts"] = markets["btts"]
            if markets.get("handicap"):
                next_row["pre_handicap"] = markets["handicap"]
            next_row["pre_extra_market_source"] = {
                "source": item.get("source"),
                "source_url": item.get("source_url"),
                "market_counts": item.get("market_counts") or market_counts(markets),
            }
        enriched.append(next_row)
    return enriched


def historical_market_constraints_from_row(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for market in row.get("pre_over_under") or []:
        if not isinstance(market, Mapping):
            continue
        line = parse_float(market.get("line"))
        over = parse_probability(market.get("over_probability"))
        if line is None or over is None:
            continue
        weight = 1.0 if abs(line - 2.5) < 0.001 else 0.45
        constraints.append(
            {
                "id": f"ou_{line:g}_over",
                "kind": "total_goals",
                "side": "over",
                "line": line,
                "target": over,
                "weight": weight,
                "source": market.get("source") or "historical_market_lines",
            }
        )
    btts = row.get("pre_btts") or {}
    if isinstance(btts, Mapping):
        yes = parse_probability(btts.get("yes_probability"))
        if yes is not None:
            constraints.append(
                {
                    "id": "btts_yes",
                    "kind": "btts",
                    "side": "yes",
                    "target": yes,
                    "weight": 0.7,
                    "source": btts.get("source") or "historical_market_lines",
                }
            )
    handicap_candidates = []
    for market in row.get("pre_handicap") or []:
        if not isinstance(market, Mapping):
            continue
        line = parse_float(market.get("line"))
        home_cover = parse_probability(market.get("home_cover_probability"))
        if line is None or home_cover is None:
            continue
        # Half-goal Asian handicap lines have no push and are safe to express
        # as score-grid constraints. Integer lines are imported but not active.
        if abs(line * 2 - round(line * 2)) > 0.001 or abs(line - round(line)) < 0.001:
            continue
        if abs(line) > 2.5 or int(market.get("bookmakers") or 0) < 2:
            continue
        if home_cover < 0.2 or home_cover > 0.8:
            continue
        handicap_candidates.append((abs(home_cover - 0.5), abs(line), line, home_cover, market))
    if handicap_candidates:
        _balance, _distance, line, home_cover, market = sorted(handicap_candidates)[0]
        constraints.append(
            {
                "id": f"handicap_home_{line:g}_cover",
                "kind": "handicap",
                "team": "home",
                "side": "cover",
                "line": line,
                "target": home_cover,
                "weight": 0.35,
                "source": market.get("source") or "historical_market_lines",
            }
        )
    return constraints


def historical_market_payload_summary(
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or load_historical_market_payload()
    items = payload.get("items") or []
    coverage = {
        "matches": len(items),
        "over_under": sum(1 for item in items if (item.get("market_counts") or {}).get("over_under")),
        "btts": sum(1 for item in items if (item.get("market_counts") or {}).get("btts")),
        "handicap": sum(1 for item in items if (item.get("market_counts") or {}).get("handicap")),
    }
    return {
        "status": "accepted_partial_coverage" if items else "no_imported_lines",
        "coverage": coverage,
        "updated_at": (payload.get("_meta") or {}).get("updated_at"),
        "source": (payload.get("_meta") or {}).get("source"),
        "source_url": (payload.get("_meta") or {}).get("source_url"),
    }


def refresh_checkbestodds_historical_markets(
    *,
    tournaments: Iterable[str] = ("2014", "2018", "2022"),
    limit: int | None = None,
    timeout: int = 20,
    write: bool = True,
) -> dict[str, Any]:
    requested = [str(tournament) for tournament in tournaments]
    items: list[dict[str, Any]] = []
    source_rows = []
    errors = []
    for tournament in requested:
        archive_url = CHECKBESTODDS_ARCHIVE_URLS.get(tournament)
        if not archive_url:
            errors.append({"tournament": tournament, "error": "unsupported_tournament"})
            continue
        archive_html = fetch_text(archive_url, timeout=timeout)
        links = parse_checkbestodds_archive_links(archive_html)
        before_count = len(items)
        tournament_errors = 0
        for link in links:
            if limit is not None and len(items) >= limit:
                break
            try:
                item = fetch_checkbestodds_match_markets(
                    tournament,
                    link["url"],
                    timeout=timeout,
                )
            except Exception as exc:  # pragma: no cover - live-source guardrail
                tournament_errors += 1
                errors.append({"tournament": tournament, "url": link["url"], "error": str(exc)})
                continue
            if item and sum(item.get("market_counts", {}).values()) > 0:
                items.append(item)
        imported_count = len(items) - before_count
        source_rows.append(
            {
                "id": f"checkbestodds_world_cup_{tournament}",
                "name": f"CheckBestOdds World Cup {tournament}",
                "url": archive_url,
                "accepted": imported_count > 0,
                "status": (
                    "accepted_partial_coverage"
                    if imported_count > 0
                    else "rejected_links_404_or_no_relevant_markets"
                ),
                "free": True,
                "markets": ["over_under", "btts", "handicap"],
                "match_links": len(links),
                "imported_matches": imported_count,
                "errors": tournament_errors,
                "note": (
                    "Freie Archivseiten liefern 1X2 und per xajax-Nachlade-POST "
                    "Over/Under, BTTS und Handicap-Tabellen, soweit historisch vorhanden."
                ),
            }
        )
        if limit is not None and len(items) >= limit:
            break

    updated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "_meta": {
            "source": "checkbestodds",
            "source_url": CHECKBESTODDS_BASE_URL,
            "updated_at": updated_at,
            "requested_tournaments": requested,
            "status": "accepted_partial_coverage" if items else "no_imported_lines",
            "matches_imported": len(items),
            "errors": errors[:25],
        },
        "items": items,
    }
    source_audit = {
        "_meta": {
            "updated_at": updated_at,
            "task": "T-0054b",
            "decision": "accepted_partial_coverage" if items else "no_accepted_historical_extra_markets",
        },
        "decision": {
            "status": "backtest_only" if items else "watch_only",
            "reason": (
                "historical_extra_markets_imported_but_require_backtest_value"
                if items
                else "no_free_reproducible_historical_extra_market_lines_imported"
            ),
            "recommendation": (
                "Use imported O/U, BTTS and handicap lines only in backtest-report "
                "until the market-score variant shows positive Kicktipp value."
            ),
        },
        "sources": [
            *source_rows,
            {
                "id": "fctables_worldcup_under_over",
                "name": "FCTables World Cup Under/Over pages",
                "url": "https://www.fctables.com/worldcup/",
                "accepted": False,
                "status": "rejected_not_market_odds",
                "free": True,
                "markets": ["over_under"],
                "note": "Under/Over content is match/team statistics, not pre-match bookmaker odds.",
            },
        ],
    }
    if write:
        write_json(HISTORICAL_MARKET_LINES_PATH, payload)
        write_json(HISTORICAL_MARKET_LINE_SOURCES_PATH, source_audit)
    return {**payload, "source_audit": source_audit}


def fetch_checkbestodds_match_markets(
    tournament: str,
    url: str,
    *,
    timeout: int = 20,
) -> dict[str, Any] | None:
    page = fetch_text(url, timeout=timeout)
    meta = parse_checkbestodds_match_page(page)
    if not meta:
        return None
    more_html = fetch_checkbestodds_more_odds(
        url,
        meta,
        timeout=timeout,
    )
    markets = parse_checkbestodds_more_odds_html(more_html)
    return {
        "tournament": str(tournament),
        "match": f"{meta['home']} - {meta['away']}",
        "home": meta["home"],
        "away": meta["away"],
        "kickoff_ts": meta["match_time"],
        "source": "checkbestodds",
        "source_url": url,
        "markets": markets,
        "market_counts": market_counts(markets),
        "quality": {
            "status": "backtest_only",
            "reasons": ["free_historical_snapshot", "requires_ablation_value_before_live_use"],
        },
    }


def fetch_text(url: str, *, timeout: int = 20, data: bytes | None = None) -> str:
    req = request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; wm-tipps/1.0)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_checkbestodds_archive_links(page_html: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen = set()
    for match in MATCH_LINK_RE.finditer(page_html):
        href = html.unescape(match.group("href"))
        url = parse.urljoin(CHECKBESTODDS_BASE_URL, href)
        if url in seen:
            continue
        seen.add(url)
        links.append({"match": clean_text(match.group("match")), "url": url})
    return links


def parse_checkbestodds_match_page(page_html: str) -> dict[str, Any] | None:
    home = text_for_id(page_html, "homeName")
    away = text_for_id(page_html, "awayName")
    match_time = attr_for_id(page_html, "matchTime", "ts")
    match_hash = attr_for_id(page_html, "matchHash", "value")
    if not home or not away or not match_time or not match_hash:
        return None
    return {
        "home": home,
        "away": away,
        "match_time": match_time,
        "match_hash": match_hash,
    }


def fetch_checkbestodds_more_odds(
    url: str,
    meta: Mapping[str, Any],
    *,
    timeout: int = 20,
) -> str:
    params = parse.urlencode(
        [
            ("xjxcls", "fx"),
            ("xjxmthd", "moreOddsFootball"),
            ("xjxargs[]", f"S{CHECKBESTODDS_MORE_ODDS_TYPES}"),
            ("xjxargs[]", f"S{meta['match_time']}"),
            ("xjxargs[]", f"S{meta['home']}"),
            ("xjxargs[]", f"S{meta['away']}"),
            ("xjxargs[]", f"S{meta['match_hash']}"),
        ]
    ).encode("utf-8")
    response = fetch_text(url, timeout=timeout, data=params)
    cdata_match = re.search(
        r'<cmd[^>]+id="moreOdds"[^>]*><!\[CDATA\[(.*?)\]\]></cmd>',
        response,
        re.IGNORECASE | re.DOTALL,
    )
    if not cdata_match:
        return response
    cdata = cdata_match.group(1)
    return cdata[1:] if cdata.startswith("S") else cdata


def parse_checkbestodds_more_odds_html(more_html: str) -> dict[str, Any]:
    markets: dict[str, Any] = {"over_under": [], "btts": None, "handicap": []}
    headers = list(MARKET_HEADER_RE.finditer(more_html))
    for index, header in enumerate(headers):
        title = clean_text(header.group("title"))
        start = header.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(more_html)
        segment = more_html[start:end]
        table_match = re.search(r"<table[^>]*>(.*?)</table>", segment, re.IGNORECASE | re.DOTALL)
        if not table_match:
            continue
        rows = parse_market_rows(table_match.group(1))
        market = consensus_market_from_rows(title, rows)
        if not market:
            continue
        if market["market"] == "over_under":
            markets["over_under"].append(market)
        elif market["market"] == "btts":
            markets["btts"] = market
        elif market["market"] == "handicap":
            markets["handicap"].append(market)
    markets["over_under"].sort(key=lambda row: row["line"])
    markets["handicap"].sort(key=lambda row: abs(row["line"]))
    return markets


def parse_market_rows(table_html: str) -> list[dict[str, Any]]:
    rows = []
    for row_match in ROW_RE.finditer(table_html):
        row_html = row_match.group(1)
        text = clean_text(row_html)
        if not text or "Bookmaker" in text or "Best odds" in text:
            continue
        cells = CELL_RE.findall(row_html)
        if len(cells) < 4:
            continue
        odds = [parse_odd_cell(cell) for cell in cells[1:3]]
        if odds[0] is None or odds[1] is None:
            continue
        rows.append(
            {
                "bookmaker": clean_text(cells[0]),
                "first": odds[0],
                "second": odds[1],
                "margin": parse_margin(clean_text(cells[3])),
            }
        )
    return rows


def consensus_market_from_rows(title: str, rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    lower_title = title.lower()
    pair = consensus_two_way(rows)
    if not pair:
        return None
    if lower_title.startswith("under/over"):
        line_match = re.search(r"([0-9]+(?:\.[0-9]+)?)", lower_title)
        if not line_match:
            return None
        line = float(line_match.group(1))
        return {
            "market": "over_under",
            "line": line,
            "under_probability": pair["first_probability"],
            "over_probability": pair["second_probability"],
            "bookmakers": pair["bookmakers"],
            "avg_overround": pair["avg_overround"],
            "source": "checkbestodds",
            "source_market": title,
        }
    if lower_title == "both teams to score odds":
        return {
            "market": "btts",
            "yes_probability": pair["first_probability"],
            "no_probability": pair["second_probability"],
            "bookmakers": pair["bookmakers"],
            "avg_overround": pair["avg_overround"],
            "source": "checkbestodds",
            "source_market": title,
        }
    if lower_title.startswith("asian handicap"):
        line_match = re.search(r"([-+]?[0-9]+(?:\.[0-9]+)?)", lower_title)
        if not line_match:
            return None
        line = float(line_match.group(1))
        return {
            "market": "handicap",
            "team": "home",
            "line": line,
            "home_cover_probability": pair["first_probability"],
            "away_cover_probability": pair["second_probability"],
            "bookmakers": pair["bookmakers"],
            "avg_overround": pair["avg_overround"],
            "source": "checkbestodds",
            "source_market": title,
        }
    return None


def consensus_two_way(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    first_probabilities = []
    second_probabilities = []
    overrounds = []
    for row in rows:
        first = parse_float(row.get("first"))
        second = parse_float(row.get("second"))
        if first is None or second is None or first <= 1.0 or second <= 1.0:
            continue
        overround = 1 / first + 1 / second
        if overround < 0.85 or overround > 1.35:
            continue
        first_probabilities.append((1 / first) / overround)
        second_probabilities.append((1 / second) / overround)
        overrounds.append(overround)
    if not first_probabilities:
        return None
    return {
        "first_probability": round(sum(first_probabilities) / len(first_probabilities), 4),
        "second_probability": round(sum(second_probabilities) / len(second_probabilities), 4),
        "avg_overround": round(sum(overrounds) / len(overrounds), 4),
        "bookmakers": len(first_probabilities),
    }


def text_for_id(page_html: str, element_id: str) -> str | None:
    match = re.search(
        rf'id="{re.escape(element_id)}"[^>]*>(.*?)</',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    return clean_text(match.group(1)) if match else None


def attr_for_id(page_html: str, element_id: str, attr: str) -> str | None:
    match = re.search(
        rf'id="{re.escape(element_id)}"[^>]*\s{re.escape(attr)}="([^"]+)"',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    return html.unescape(match.group(1)) if match else None


def parse_odd_cell(cell_html: str) -> float | None:
    match = SORT_ODD_RE.search(cell_html)
    if match:
        return parse_float(match.group(1))
    for token in re.findall(r"\b[0-9]+(?:\.[0-9]+)?\b", clean_text(cell_html)):
        parsed = parse_float(token)
        if parsed and parsed > 1.0:
            return parsed
    return None


def parse_margin(value: str) -> float | None:
    match = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", value)
    return parse_float(match.group(0)) if match else None


def clean_text(raw: Any) -> str:
    text = html.unescape(TAG_RE.sub(" ", str(raw or "")))
    return re.sub(r"\s+", " ", text).strip()
