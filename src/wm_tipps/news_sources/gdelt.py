from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Iterable


NAME = "gdelt"
ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_TIMEOUT = 5
DEFAULT_KEYWORDS = "injury OR lineup OR squad OR suspended"
INTER_REQUEST_SLEEP = 1.0  # GDELT rate-limit ~1 req/s; verhindert HTTP 429.


def collect(
    teams: Iterable[str],
    *,
    per_team_limit: int = 6,
    keywords: str = DEFAULT_KEYWORDS,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Holt News-Treffer pro Team von GDELT.

    Query ist bewusst breit (kein '"World Cup"' mehr), weil das Schluesselwort
    Pre-Tournament zu eng filtert. Per-Team-Timeout knapp gehalten, damit ein
    haengender Call den ganzen Live-Refresh nicht aufhaelt.
    """
    rows: list[dict[str, Any]] = []
    for index, team in enumerate(teams):
        if index > 0:
            time.sleep(INTER_REQUEST_SLEEP)
        # GDELT verlangt Klammern um OR-Gruppen, sonst wirft die API
        # "Queries containing OR'd terms must be surrounded by ()" und der
        # Response ist kein JSON (Adapter returnt dann []).
        query = f'"{team}" ({keywords})'
        try:
            rows.extend(_fetch_articles(query, per_team_limit, timeout=timeout))
        except OSError:
            continue
    return rows


def _fetch_articles(query: str, max_records: int, *, timeout: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": max_records,
            "sort": "HybridRel",
        }
    )
    url = f"{ENDPOINT}?{params}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []
    for article in data.get("articles", []):
        rows.append(
            {
                "source": article.get("domain", NAME),
                "title": article.get("title", ""),
                "summary": "",
                "url": article.get("url", ""),
                "published_at": article.get("seendate", ""),
                "reliability": "medium",
            }
        )
    return rows
