"""T-0040-role-data: role (starter/rotation/backup) aus echten Aufstellungen.

Pre-Tournament gibt es keine Minuten-Daten; ab Turnierstart (11.06.2026)
liefern bestaetigte/erwartete Startelf-Listen die echte Startelf-Wahrheit.
Diese Mechanik leitet `role` aus einer Startelf (XI) ab und ueberschreibt
damit die heuristische Projektion:

- Pool-Spieler in der XI  -> starter
- Pool-Spieler NICHT in der XI (aber im Kader-Pool) -> rotation

Quellen (hoehere Prioritaet gewinnt):
  1. `data/manual_lineups.json` (manuell gepflegt, zuverlaessig, Policy:
     manuelle Daten zuerst)  -> role_source "manual_lineup"
  2. confirmed_lineup-News (automatisch)  -> "news_confirmed_lineup"
  3. expected_lineup-News (automatisch)   -> "news_expected_lineup"

Die News-Extraktion ist best-effort (Freitext); die manuelle Datei ist
der verlaessliche Pfad. Manuelle role-Overrides (role_source == "manual")
bleiben unangetastet.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .io import read_json
from .paths import DATA_DIR
from .player_pool import HEURISTIC_ROLE_SOURCE, _name_token_set

MANUAL_LINEUPS_PATH = DATA_DIR / "manual_lineups.json"
MIN_XI_NAMES = 9  # eine plausible Startelf hat ~11 Namen; konservativ.

MANUAL_ROLE_SOURCE = "manual_lineup"
NEWS_CONFIRMED_ROLE_SOURCE = "news_confirmed_lineup"
NEWS_EXPECTED_ROLE_SOURCE = "news_expected_lineup"
# Hoehere Zahl gewinnt; heuristische/leere Rollen verlieren immer.
LINEUP_SOURCE_PRIORITY = {
    MANUAL_ROLE_SOURCE: 3,
    NEWS_CONFIRMED_ROLE_SOURCE: 2,
    NEWS_EXPECTED_ROLE_SOURCE: 1,
}
# role_source-Werte, die eine echte manuelle Pflege markieren und NICHT
# von Lineup-Daten ueberschrieben werden duerfen.
PROTECTED_ROLE_SOURCES = {"manual"}

_XI_KEYWORD_RE = re.compile(
    r"(?:starting\s+xi|probable\s+xi|expected\s+xi|predicted\s+xi|confirmed\s+xi"
    r"|line[\s-]?up|startelf|\bxi)\s*[:\-]\s*(?P<list>.+)",
    re.IGNORECASE | re.DOTALL,
)
_NAME_RE = re.compile(
    r"[A-ZÀ-Þ][A-Za-zÀ-ÿ.'’\-]+(?:\s+[A-ZÀ-Þ][A-Za-zÀ-ÿ.'’\-]+)*"
)


def load_manual_lineups() -> dict[str, list[str]]:
    payload = read_json(MANUAL_LINEUPS_PATH, {})
    lineups = payload.get("lineups") if isinstance(payload, dict) else None
    out: dict[str, list[str]] = {}
    for team, names in (lineups or {}).items():
        if isinstance(names, list):
            clean = [str(n).strip() for n in names if str(n).strip()]
            if clean:
                out[str(team)] = clean
    return out


def extract_xi_names(text: str) -> list[str] | None:
    """Best-effort: Startelf-Namen aus Freitext nach einem Lineup-Keyword.

    Liefert None, wenn keine plausible XI (>= MIN_XI_NAMES Namen) gefunden
    wird -- dann greift kein automatischer Rollenwechsel (kein Risiko).
    """
    if not text:
        return None
    match = _XI_KEYWORD_RE.search(text)
    if not match:
        return None
    segment = match.group("list")
    names: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,;/]|\band\b|•|\|| - ", segment):
        part = part.strip(" .-\t")
        name_match = _NAME_RE.match(part)
        if not name_match:
            continue
        name = " ".join(name_match.group(0).split())
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)
    return names if len(names) >= MIN_XI_NAMES else None


def lineup_xis_from_news(news_items: list[Mapping[str, Any]]) -> dict[str, tuple[list[str], str]]:
    """{team: (xi_names, role_source)} aus confirmed/expected-Lineup-News.

    confirmed gewinnt gegen expected; bei Gleichstand der erste Treffer
    (News ist nach Frische sortiert). Nur News mit extrahierbarer XI.
    """
    result: dict[str, tuple[list[str], str]] = {}
    for item in news_items or []:
        categories = set(item.get("categories") or [])
        if "confirmed_lineup" in categories:
            source = NEWS_CONFIRMED_ROLE_SOURCE
        elif "expected_lineup" in categories:
            source = NEWS_EXPECTED_ROLE_SOURCE
        else:
            continue
        teams = item.get("teams") or []
        if not teams:
            continue
        xi = extract_xi_names(f"{item.get('title', '')} {item.get('summary', '')}")
        if not xi:
            continue
        for team in teams:
            team = str(team)
            existing = result.get(team)
            if existing and LINEUP_SOURCE_PRIORITY[existing[1]] >= LINEUP_SOURCE_PRIORITY[source]:
                continue
            result[team] = (xi, source)
    return result


def resolve_lineups(
    news_items: list[Mapping[str, Any]] | None = None,
    manual_lineups: Mapping[str, list[str]] | None = None,
) -> dict[str, tuple[list[str], str]]:
    """Manuelle + News-Quellen zu {team: (xi_names, role_source)} mergen."""
    manual = dict(manual_lineups) if manual_lineups is not None else load_manual_lineups()
    resolved: dict[str, tuple[list[str], str]] = {}
    if news_items:
        resolved.update(lineup_xis_from_news(news_items))
    for team, names in manual.items():
        resolved[str(team)] = (list(names), MANUAL_ROLE_SOURCE)  # manuell gewinnt
    return resolved


def _player_in_xi(player: Mapping[str, Any], xi_token_sets: list[frozenset[str]]) -> bool:
    pool_tokens = _name_token_set(str(player.get("name", "")))
    for alias in player.get("source_aliases", []) or []:
        pool_tokens = pool_tokens | _name_token_set(str(alias))
    if not pool_tokens:
        return False
    for xi_tokens in xi_token_sets:
        if not xi_tokens:
            continue
        # XI listet oft nur Nachnamen -> Subset-Relation in beide Richtungen.
        if xi_tokens <= pool_tokens or pool_tokens <= xi_tokens:
            return True
    return False


def apply_lineup_roles(
    players: dict[str, list[dict[str, Any]]],
    news_items: list[Mapping[str, Any]] | None = None,
    manual_lineups: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Setzt role + role_source aus Aufstellungen (in place).

    Ueberschreibt heuristische/leere Rollen; echte manuelle Rollen
    (role_source == "manual") bleiben. Liefert eine Zusammenfassung.
    """
    resolved = resolve_lineups(news_items, manual_lineups)
    teams_applied = 0
    starters = rotation = 0
    by_source: dict[str, int] = {}
    for team, roster in players.items():
        entry = resolved.get(team)
        if not entry:
            continue
        xi_names, source = entry
        xi_token_sets = [_name_token_set(name) for name in xi_names]
        teams_applied += 1
        for player in roster:
            if player.get("role_source") in PROTECTED_ROLE_SOURCES:
                continue
            in_xi = _player_in_xi(player, xi_token_sets)
            player["role"] = "starter" if in_xi else "rotation"
            player["role_source"] = source
            by_source[source] = by_source.get(source, 0) + 1
            if in_xi:
                starters += 1
            else:
                rotation += 1
    return {
        "teams_with_lineup": teams_applied,
        "players_updated": starters + rotation,
        "starters": starters,
        "rotation": rotation,
        "by_source": by_source,
    }
