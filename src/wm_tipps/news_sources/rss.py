from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable


NAME = "rss"
# Verifiziert am 2026-05-10 / 2026-05-11 / 2026-05-19. Andere Quellen
# (Guardian, DW, Reuters Sports) sind ueber WebFetch geblockt; FIFA
# RSS-Endpoint liefert leer; UEFA RSS antwortet 503; DFB/Sportschau
# hatten keinen stabilen RSS-Pfad. TheFA/ScottishFA/DFB lieferten am
# 2026-05-19 HTML/404 statt RSS, US Soccer war per 403 geblockt.
# SkySports hat football-spezifische Feeds (Premier League 11095,
# Transfer Centre 12691) -- Premier League aufgenommen, weil Klub-
# Lineup-/Verletzungs-News fuer Nationalteam-Auswahl relevant sind;
# Codex' Relevance-Filter (T-0028) stuft Items ohne Fixture-Team-Mention
# ohnehin als noise ab.
USER_AGENT = "Mozilla/5.0 wm-tipps-rss/1.0"
OFFICIAL_FEEDS: tuple[str, ...] = (
    "https://canadasoccer.com/feed/",
)
TEAM_INTEL_FEEDS: tuple[str, ...] = (
    "https://www.insideworldfootball.com/feed/",
    "https://www.worldsoccer.com/feed",
)

DEFAULT_FEEDS: tuple[str, ...] = (
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.espn.com/espn/rss/soccer/news",
    "https://newsfeed.kicker.de/news/aktuell",
    "https://www.skysports.com/rss/11095",
    "https://www.90min.com/posts.rss",
    "https://www.fourfourtwo.com/feeds.xml",
    *TEAM_INTEL_FEEDS,
    *OFFICIAL_FEEDS,
)
ATOM_NS = "{http://www.w3.org/2005/Atom}"
HIGH_RELIABILITY_FEEDS = set(OFFICIAL_FEEDS)


def collect(
    teams: Iterable[str],
    *,
    per_team_limit: int = 6,
    feeds: Iterable[str] = DEFAULT_FEEDS,
) -> list[dict[str, Any]]:
    teams_list = list(teams)
    rows: list[dict[str, Any]] = []
    for url in feeds:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                text = response.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        rows.extend(parse_rss(text, teams_list, source=url))
    return rows


def parse_rss(text: str, teams: list[str], *, source: str = NAME) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = root.findall(".//item") or root.findall(f".//{ATOM_NS}entry")
    teams_lower = [team.lower() for team in teams]
    rows: list[dict[str, Any]] = []
    for item in items:
        title = (_text(item, "title") or "").strip()
        link = (_text(item, "link") or "").strip()
        summary = (_text(item, "description") or _text(item, "summary") or "").strip()
        published_raw = (
            _text(item, "pubDate") or _text(item, "published") or ""
        ).strip()
        haystack = f"{title} {summary}".lower()
        mentioned = [
            team for team, lower in zip(teams, teams_lower) if lower and lower in haystack
        ]
        rows.append(
            {
                "source": source,
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": _normalize_pubdate(published_raw),
                "teams": mentioned,
                "reliability": reliability_for_source(source),
            }
        )
    return rows


def reliability_for_source(source: str) -> str:
    return "high" if source in HIGH_RELIABILITY_FEEDS else "medium"


def _text(item: ET.Element, tag: str) -> str | None:
    element = item.find(tag)
    if element is None:
        element = item.find(f"{ATOM_NS}{tag}")
    if element is None:
        return None
    return element.text


def _normalize_pubdate(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is None:
            return value
        # Manche Feeds (z.B. SkySports) liefern pubDate ohne TZ-Info, dann
        # ist parsed offset-naive. UTC annehmen, damit freshness_status nicht
        # mit offset-aware now() kollidiert (TypeError).
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return value
