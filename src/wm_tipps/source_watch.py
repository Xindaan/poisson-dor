from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

from .io import read_json, write_json
from .odds import load_manual_markets, load_manual_odds
from .paths import DATA_DIR


BWIN_WORLD_CUP_URL = "https://www.bwin.de/de/sports/fu%C3%9Fball-4/wetten/welt-6/wm-2026-0%3A14"
BWIN_MATCH_ODDS_SOURCE = "bwin_world_cup_2026"
BWIN_FUTURES_SOURCE = "bwin_de_gesamtwetten_2026"
EXACT_SCORE_KEYWORDS = (
    "genaues ergebnis",
    "exaktes ergebnis",
    "korrektes ergebnis",
    "correct score",
)
EXACT_SCORE_SECTION_MARKERS = (
    "genaues ergebnis - reguläre spielzeit",
    "genaues ergebnis - regulaere spielzeit",
    "correct score - regular time",
)
EXACT_SCORE_STOP_MARKERS = (
    "genaues ergebnis (mehrere optionen)",
    "spiel wird mit genau",
    "correct score (multiple options)",
)
SCORE_RE = re.compile(r"\b\d{1,2}:\d{1,2}\b")
DECIMAL_RE = re.compile(r"(?<![:\d])\d{1,3}(?:[.,]\d{2})(?![:\d])")
SCORE_OR_DECIMAL_RE = re.compile(
    rf"{SCORE_RE.pattern}|{DECIMAL_RE.pattern}"
)


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _source_count(rows: list[Mapping[str, Any]], source: str) -> int:
    return len(
        {
            str(row.get("match_id"))
            for row in rows
            if row.get("source") == source and row.get("match_id")
        }
    )


def _market_counts(rows: list[Mapping[str, Any]], source: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("source") != source:
            continue
        key = str(row.get("category") or row.get("market") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def parse_bwin_page_snapshot(text: str, *, checked_at: str | None = None) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.casefold())

    def count_after(label: str) -> int | None:
        match = re.search(rf"{re.escape(label.casefold())}\s+(\d+)", normalized)
        return int(match.group(1)) if match else None

    return {
        "status": "ok",
        "checked_at": checked_at or _now_iso(),
        "url": BWIN_WORLD_CUP_URL,
        "match_count": count_after("Spiele"),
        "overall_market_count": count_after("Gesamtwetten"),
        "special_market_count": count_after("Spezial"),
        "exact_score_visible": any(keyword in normalized for keyword in EXACT_SCORE_KEYWORDS),
    }


def _clean_snapshot_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(
        r"^-\s*(?:generic|text|button|tab|link)(?:\s+\"[^\"]*\")?:\s*",
        "",
        cleaned,
    )
    return cleaned.strip().strip('"')


def _extract_section(
    text: str,
    *,
    start_markers: tuple[str, ...],
    stop_markers: tuple[str, ...],
) -> str:
    lines = [_clean_snapshot_line(line) for line in text.splitlines()]
    start_index: int | None = None
    for index, line in enumerate(lines):
        folded = line.casefold()
        if any(marker in folded for marker in start_markers):
            start_index = index
            break
    if start_index is None:
        return ""

    section_lines: list[str] = []
    for line in lines[start_index:]:
        folded = line.casefold()
        stop_positions = [
            folded.find(marker)
            for marker in stop_markers
            if marker in folded
        ]
        if stop_positions:
            earliest_stop = min(stop_positions)
            if earliest_stop > 0:
                section_lines.append(line[:earliest_stop])
            break
        section_lines.append(line)
    return "\n".join(section_lines)


def parse_bwin_exact_score_snapshot(
    text: str,
    *,
    checked_at: str | None = None,
    url: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any]:
    section = _extract_section(
        text,
        start_markers=EXACT_SCORE_SECTION_MARKERS,
        stop_markers=EXACT_SCORE_STOP_MARKERS,
    )
    folded_section = section.casefold()
    tokens = [match.group(0) for match in SCORE_OR_DECIMAL_RE.finditer(section)]
    prices: dict[str, float] = {}
    for index, token in enumerate(tokens):
        if not SCORE_RE.fullmatch(token):
            continue
        if token in prices:
            continue
        for candidate in tokens[index + 1 :]:
            if SCORE_RE.fullmatch(candidate):
                break
            if not DECIMAL_RE.fullmatch(candidate):
                continue
            odds = float(candidate.replace(",", "."))
            if 1.0 < odds <= 1001.0:
                prices[token] = odds
            break

    rows = [
        {"selection": selection, "decimal_odds": odds}
        for selection, odds in prices.items()
    ]
    status = "ok" if rows else "not_found"
    return {
        "status": status,
        "checked_at": checked_at or _now_iso(),
        "url": url or BWIN_WORLD_CUP_URL,
        "market": "exact_score_regular_time",
        "home_team": home_team,
        "away_team": away_team,
        "price_count": len(rows),
        "has_more_button": "mehr anzeigen" in folded_section or "show more" in folded_section,
        "prices": rows,
    }


def parse_bwin_event_snapshot(
    text: str,
    *,
    checked_at: str | None = None,
    url: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.casefold())
    market_count_match = re.search(r"alle wetten\s+(\d+)", normalized)
    exact_prices = parse_bwin_exact_score_snapshot(
        text,
        checked_at=checked_at,
        url=url,
        home_team=home_team,
        away_team=away_team,
    )
    price_count = exact_prices["price_count"]
    if price_count and exact_prices["has_more_button"]:
        exact_status = "visible_partial_prices"
    elif price_count:
        exact_status = "visible_with_prices"
    elif any(keyword in normalized for keyword in EXACT_SCORE_KEYWORDS):
        exact_status = "visible_not_extracted"
    else:
        exact_status = "not_visible"
    return {
        "status": "ok",
        "checked_at": checked_at or _now_iso(),
        "url": url or BWIN_WORLD_CUP_URL,
        "event_market_count": int(market_count_match.group(1)) if market_count_match else None,
        "exact_score_visible": exact_status != "not_visible",
        "exact_score_status": exact_status,
        "exact_score_prices_count": price_count,
        "exact_score_has_more": exact_prices["has_more_button"],
        "exact_score_sample": exact_prices["prices"][:8],
    }


def probe_bwin_world_cup_page(*, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        BWIN_WORLD_CUP_URL,
        headers={"User-Agent": "Mozilla/5.0 wm-tipps-source-watch/1.0"},
    )
    checked_at = _now_iso()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - Source-Watch darf nie den Watch-Cycle stoppen.
        return {
            "status": "error",
            "checked_at": checked_at,
            "url": BWIN_WORLD_CUP_URL,
            "error": str(exc),
        }
    return parse_bwin_page_snapshot(text, checked_at=checked_at)


def build_source_watch_status(
    fixtures: list[dict[str, Any]],
    odds: list[dict[str, Any]],
    markets: list[dict[str, Any]],
    *,
    live_probe: dict[str, Any] | None = None,
    manual_observations: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    fixture_count = len(fixtures)
    imported_bwin_matches = _source_count(odds, BWIN_MATCH_ODDS_SOURCE)
    market_counts = _market_counts(markets, BWIN_FUTURES_SOURCE)
    manual_observation = dict((manual_observations or {}).get("bwin_de_world_cup_2026", {}))
    observed = live_probe if live_probe and live_probe.get("status") == "ok" else manual_observation
    flags: list[str] = []
    actions: list[str] = []

    if imported_bwin_matches < fixture_count:
        flags.append("partial_match_odds")
        actions.append(
            f"Bwin-Matchquoten decken importiert {imported_bwin_matches}/{fixture_count} Gruppenspiele ab."
        )

    if observed:
        visible_matches = observed.get("match_count")
        if isinstance(visible_matches, int) and visible_matches > imported_bwin_matches:
            flags.append("bwin_page_expanded")
            actions.append(
                f"Bwin-Seite zeigt {visible_matches} Spiele; manual_odds.csv sollte nachgezogen werden."
            )
        exact_score_status = str(observed.get("exact_score_status") or "")
        exact_score_prices = observed.get("exact_score_prices_count")
        if isinstance(exact_score_prices, int) and exact_score_prices > 0:
            flags.append("exact_score_prices_visible")
            actions.append(
                f"Bwin-Exact-Score zeigt {exact_score_prices} sichtbare Preise; noch nicht im Modell-Konsens genutzt."
            )
            if observed.get("exact_score_has_more"):
                flags.append("exact_score_partial_sample")
                actions.append("Exact-Score hat 'Mehr anzeigen'; Browser-Snapshot erneut erweitern, bevor Preise importiert werden.")
        elif observed.get("exact_score_visible") or exact_score_status in {"needs_browser_check", "visible_not_extracted"}:
            flags.append("exact_score_watch")
            actions.append("Exact-Score/Genaues-Ergebnis bei Bwin erneut pruefen und ggf. robust extrahieren.")
    if not live_probe or live_probe.get("status") != "ok":
        flags.append("live_probe_missing")
        if manual_observation:
            actions.append("Bwin-Live-Probe nicht ok; letzter Browser-Snapshot wird als Fallback angezeigt.")
        else:
            actions.append("Bwin-Live-Probe nicht ok; manuelle Sicht aus dem Browser weiter als Fallback nutzen.")

    if not market_counts:
        flags.append("futures_missing")
        actions.append("Bwin-Gesamtwetten fuer Bonusfragen fehlen in manual_markets.json.")

    source = {
        "id": "bwin_de_world_cup_2026",
        "name": "Bwin.de WM 2026",
        "url": BWIN_WORLD_CUP_URL,
        "status": "watch" if flags else "ok",
        "flags": flags,
        "actions": actions,
        "imported_match_odds": imported_bwin_matches,
        "fixture_count": fixture_count,
        "imported_futures": market_counts,
        "live_probe": live_probe or {"status": "not_run"},
        "manual_observation": manual_observation,
    }
    return {"updated_at": _now_iso(now), "sources": [source]}


def refresh_source_watch(
    fixtures: list[dict[str, Any]],
    *,
    market_payload: Mapping[str, Any] | None = None,
    probe_live: bool = False,
) -> dict[str, Any]:
    odds = list((market_payload or {}).get("odds", [])) if market_payload else load_manual_odds()
    markets = list((market_payload or {}).get("markets", [])) if market_payload else load_manual_markets()
    manual_observations = read_json(DATA_DIR / "source_watch_manual.json", {})
    live_probe = probe_bwin_world_cup_page() if probe_live else None
    payload = build_source_watch_status(
        fixtures,
        odds,
        markets,
        live_probe=live_probe,
        manual_observations=manual_observations,
    )
    write_json(DATA_DIR / "source_watch_status.json", payload)
    return payload
