"""News-xG-Audit (read-only Diagnose).

Konsumiert ausschliesslich bestehende `news.py`-Funktionen -- Codex'
Modell-Domain bleibt unveraendert -- und macht sichtbar, welche News
aktuell einen xG-Malus erzeugen und wo die Fehlzuordnungs-Risikoklasse
liegt:

- je Fixture-Team die tatsaechlich gewerteten Impact-Items,
- Multi-Team-Sammelartikel (mit `count`/`suppress`-Entscheid je Team),
- Subject-Spieler, die laut Pool zu einem ANDEREN Team gehoeren,
- stale Impact-Items, die korrekt ignoriert werden.

Die Item-Auswahl spiegelt `news.team_news_impact` (gleiche Filterkette);
`test_news_audit` haelt `counted_items` gegen
`team_news_impact["deduped_impact_items"]`, damit der Spiegel nicht
still wegdriftet, falls die Modell-Auswahl spaeter geaendert wird.
"""
from __future__ import annotations

from typing import Any, Mapping

from .io import read_json, write_json
from .news import (
    XG_IMPACT_CATEGORIES,
    dedupe_impact_items,
    is_model_relevant_news,
    player_subject_keys,
    severity_rank,
    team_is_injury_subject,
    team_news_impact,
)
from .paths import DATA_DIR, EXPORTS_DIR

NEWS_AUDIT_PATH = DATA_DIR / "news_audit.json"
NEWS_AUDIT_MARKDOWN_PATH = EXPORTS_DIR / "news_audit.md"

# Mindestlaenge eines Namens-Tokens, damit es als Spieler-Subject in den
# Pool-Index geht (vermeidet Rauschen wie "de", "van").
MIN_SUBJECT_TOKEN_LEN = 4


def _has_impact_category(item: Mapping[str, Any]) -> bool:
    return (
        bool(set(item.get("categories") or []) & XG_IMPACT_CATEGORIES)
        and severity_rank(item.get("severity", "noise")) >= 2
    )


def _counted_impact_items(
    team: str,
    news_items: list[dict[str, Any]],
    player_pool: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Spiegelt news.team_news_impact (gleiche Auswahl der Items, die fuer
    # dieses Team tatsaechlich einen xG-Malus erzeugen).
    relevant = [
        item
        for item in news_items
        if team in (item.get("teams") or [])
        and item.get("freshness") != "stale"
        and is_model_relevant_news(item)
    ]
    impact = [item for item in relevant if _has_impact_category(item)]
    deduped = dedupe_impact_items(team, impact)
    return [item for item in deduped if team_is_injury_subject(team, item, player_pool)]


def _player_token_owners(player_pool: Mapping[str, Any]) -> dict[str, set[str]]:
    # name-Token (>= MIN_SUBJECT_TOKEN_LEN) + Aliasse -> Teams, die so
    # einen Spieler fuehren. Basis fuer die "Subject gehoert anderem
    # Team"-Heuristik.
    owners: dict[str, set[str]] = {}
    for team, players in (player_pool or {}).items():
        for player in players or []:
            names = [str(player.get("name", ""))]
            names.extend(str(alias) for alias in (player.get("source_aliases") or []))
            for name in names:
                for token in name.lower().replace("-", " ").replace("'", " ").split():
                    if len(token) >= MIN_SUBJECT_TOKEN_LEN:
                        owners.setdefault(token, set()).add(team)
    return owners


def _item_flags(
    team: str,
    item: Mapping[str, Any],
    token_owners: Mapping[str, set[str]],
) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    if len(item.get("teams") or []) > 1:
        flags.append("multi_team")
    subjects = player_subject_keys(team, item)
    foreign = sorted(
        {
            token
            for token in subjects
            if token in token_owners and team not in token_owners[token]
        }
    )
    if foreign:
        flags.append("subject_in_other_pool:" + ",".join(foreign))
    return flags, subjects


def build_news_audit(
    *,
    news_items: list[dict[str, Any]] | None = None,
    player_pool: Mapping[str, Any] | None = None,
    fixture_teams: set[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    if news_items is None:
        news_items = read_json(DATA_DIR / "news_items.json", {"items": []}).get("items", [])
    if player_pool is None:
        player_pool = read_json(DATA_DIR / "player_pool.json", {"players": {}}).get("players", {})
    if fixture_teams is None:
        fixtures = read_json(DATA_DIR / "fixtures.json", {"fixtures": []}).get("fixtures", [])
        fixture_teams = set()
        for fixture in fixtures:
            fixture_teams.add(fixture.get("home_team"))
            fixture_teams.add(fixture.get("away_team"))
        fixture_teams.discard(None)

    token_owners = _player_token_owners(player_pool)

    team_rows: list[dict[str, Any]] = []
    flagged_team_items = 0
    for team in sorted(fixture_teams):
        impact = team_news_impact(team, news_items, player_pool)
        if impact["attack_delta"] == 0 and impact["defense_delta"] == 0:
            continue
        items: list[dict[str, Any]] = []
        for item in _counted_impact_items(team, news_items, player_pool):
            flags, subjects = _item_flags(team, item, token_owners)
            if flags:
                flagged_team_items += 1
            items.append(
                {
                    "title": item.get("title", ""),
                    "severity": item.get("severity"),
                    "categories": sorted(set(item.get("categories") or [])),
                    "teams": item.get("teams") or [],
                    "subject_keys": subjects,
                    "flags": flags,
                }
            )
        team_rows.append(
            {
                "team": team,
                "attack_delta": impact["attack_delta"],
                "defense_delta": impact["defense_delta"],
                "critical": impact["critical"],
                "important": impact["important"],
                "counted_items": len(items),
                "items": items,
            }
        )

    # Risikoklasse global (nicht auf Fixture-Teams beschraenkt): jedes
    # impact-faehige Multi-Team-Item mit dem count/suppress-Entscheid je
    # genanntem Team.
    risk_items: list[dict[str, Any]] = []
    for item in news_items:
        teams = item.get("teams") or []
        if (
            len(teams) > 1
            and _has_impact_category(item)
            and is_model_relevant_news(item)
            and item.get("freshness") != "stale"
        ):
            risk_items.append(
                {
                    "title": item.get("title", ""),
                    "severity": item.get("severity"),
                    "teams": teams,
                    "decisions": [
                        {
                            "team": team,
                            "action": "count"
                            if team_is_injury_subject(team, item, player_pool)
                            else "suppress",
                        }
                        for team in teams
                    ],
                }
            )

    # Stale Impact-Items: waeren ohne den freshness-Filter gewertet
    # worden -- listen, um zu zeigen, dass nichts Altes durchrutscht.
    stale_impact = [
        {
            "title": item.get("title", ""),
            "severity": item.get("severity"),
            "teams": item.get("teams") or [],
        }
        for item in news_items
        if _has_impact_category(item) and item.get("freshness") == "stale"
    ]

    payload = {
        "_meta": {
            "teams_with_effect": len(team_rows),
            "risk_items": len(risk_items),
            "flagged_team_items": flagged_team_items,
            "stale_impact_items": len(stale_impact),
            "fixture_teams_scanned": len(fixture_teams),
        },
        "teams": team_rows,
        "risk_items": risk_items,
        "stale_impact_items": stale_impact,
    }

    if write:
        write_json(NEWS_AUDIT_PATH, payload)
        NEWS_AUDIT_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        NEWS_AUDIT_MARKDOWN_PATH.write_text(news_audit_markdown(payload), encoding="utf-8")

    return payload


def news_audit_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# News-xG-Audit",
        "",
        f"- Teams mit aktivem News-Effekt: **{meta.get('teams_with_effect', 0)}** "
        f"(von {meta.get('fixture_teams_scanned', 0)} Fixture-Teams)",
        f"- Multi-Team-Items (Risikoklasse): **{meta.get('risk_items', 0)}**",
        f"- markierte (Team, Item)-Paare: **{meta.get('flagged_team_items', 0)}**",
        f"- stale Impact-Items (ignoriert): **{meta.get('stale_impact_items', 0)}**",
        "",
        "## Aktive News-Effekte je Team",
        "",
    ]
    teams = payload.get("teams") or []
    if not teams:
        lines.append("_Kein Team hat aktuell einen News-xG-Effekt._")
    for row in teams:
        lines.append(
            f"### {row['team']} -- attack {row['attack_delta']}, defense {row['defense_delta']} "
            f"(crit {row['critical']}, imp {row['important']})"
        )
        for item in row.get("items") or []:
            flag_txt = f"  [FLAG: {', '.join(item['flags'])}]" if item.get("flags") else ""
            lines.append(
                f"- [{item.get('severity')}] ({', '.join(item.get('categories') or [])}) "
                f"teams={item.get('teams')}{flag_txt}"
            )
            lines.append(f"  - {item.get('title', '')}")
        lines.append("")

    lines.append("## Multi-Team-Items (count/suppress je Team)")
    lines.append("")
    risk = payload.get("risk_items") or []
    if not risk:
        lines.append("_Keine impact-faehigen Multi-Team-Items._")
    for item in risk:
        decisions = ", ".join(f"{d['team']}={d['action']}" for d in item.get("decisions") or [])
        lines.append(f"- [{item.get('severity')}] {item.get('title', '')}")
        lines.append(f"  - {decisions}")
    lines.append("")

    stale = payload.get("stale_impact_items") or []
    if stale:
        lines.append("## Stale Impact-Items (korrekt ignoriert)")
        lines.append("")
        for item in stale:
            lines.append(f"- [{item.get('severity')}] {item.get('title', '')} teams={item.get('teams')}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
