"""News-Review-Queue (Codex-Roadmap #6).

Statt immer mehr RSS-Quellen: eine human-in-the-loop Review-Queue fuer
'moeglicherweise modellwirksame' News. Die News-Heuristik hatte schwache
Precision/Recall (T-0068-Eval) und produziert Fehler wie die
Schiedsrichter-News (T-0083, fuer beide Teams als Spielerausfall
gewertet). Die Queue listet Kandidaten mit Team/Spieler/Impact und laesst
per CLI **promoten** (-> manual_news.json) oder **dismissen**
(-> bleibt aus der Queue). Promote/Dismiss sind explizite menschliche
Entscheidungen; nichts wird automatisch modellwirksam.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .io import read_json, write_json
from .news import XG_IMPACT_CATEGORIES, fingerprint, is_model_relevant_news
from .paths import DATA_DIR

REVIEW_DECISIONS_PATH = DATA_DIR / "news_review_decisions.json"
MANUAL_NEWS_PATH = DATA_DIR / "manual_news.json"
_MANUAL_FIELDS = (
    "source", "title", "summary", "url", "published_at",
    "teams", "players", "categories", "severity", "reliability",
)


def item_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or fingerprint(dict(item)))


def load_decisions(path=None) -> dict[str, Any]:
    return read_json(path or REVIEW_DECISIONS_PATH, {})


def save_decisions(decisions: Mapping[str, Any], path=None) -> None:
    write_json(path or REVIEW_DECISIONS_PATH, dict(decisions))


def _manual_keys(manual_news: Iterable[Mapping[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for item in manual_news:
        if item.get("url"):
            keys.add(str(item["url"]))
        if item.get("title"):
            keys.add(str(item["title"]).strip().lower())
    return keys


def _suggested_action(item: Mapping[str, Any]) -> str:
    categories = set(item.get("categories") or [])
    severity = str(item.get("severity") or "")
    has_player = bool(item.get("players"))
    if categories & XG_IMPACT_CATEGORIES and severity in {"critical", "important"} and has_player:
        return "promote"
    return "watch"


def build_review_queue(
    news_items: Iterable[Mapping[str, Any]],
    manual_news: Iterable[Mapping[str, Any]] | None = None,
    decisions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    decisions = decisions or {}
    manual_keys = _manual_keys(manual_news or [])
    queue: list[dict[str, Any]] = []
    for item in news_items:
        if not is_model_relevant_news(dict(item)):
            continue
        if item.get("freshness") == "stale":
            continue
        if not (set(item.get("categories") or []) & XG_IMPACT_CATEGORIES):
            continue
        if not (item.get("teams") or []):
            continue
        iid = item_id(item)
        if iid in decisions:
            continue
        url = str(item.get("url") or "")
        title_key = str(item.get("title") or "").strip().lower()
        if url in manual_keys or (title_key and title_key in manual_keys):
            continue
        queue.append(
            {
                "id": iid,
                "title": item.get("title"),
                "teams": item.get("teams") or [],
                "players": item.get("players") or [],
                "categories": item.get("categories") or [],
                "severity": item.get("severity"),
                "relevance": item.get("relevance"),
                "no_player_subject": not item.get("players"),
                "suggested": _suggested_action(item),
            }
        )
    queue.sort(key=lambda row: (row["suggested"] != "promote", str(row["title"])))
    return {
        "queue": queue,
        "count": len(queue),
        "promote_suggested": sum(1 for row in queue if row["suggested"] == "promote"),
    }


def _manual_entry(item: Mapping[str, Any]) -> dict[str, Any]:
    entry = {field: item.get(field) for field in _MANUAL_FIELDS if item.get(field) is not None}
    entry.setdefault("reliability", "medium")
    entry["promoted_via"] = "news-review"
    return entry


def apply_decision(
    item_id_value: str,
    action: str,
    news_items: Iterable[Mapping[str, Any]],
    *,
    now: str | None = None,
    decisions_path=None,
    manual_path=None,
) -> dict[str, Any]:
    if action not in {"promote", "dismiss"}:
        raise ValueError(f"unbekannte Aktion: {action}")
    now = now or datetime.now(timezone.utc).isoformat()
    items_by_id = {item_id(item): dict(item) for item in news_items}
    item = items_by_id.get(item_id_value)
    if item is None:
        return {"ok": False, "reason": "id_not_found", "id": item_id_value}
    decisions = load_decisions(decisions_path)
    result: dict[str, Any] = {"ok": True, "id": item_id_value, "action": action, "title": item.get("title")}
    if action == "promote":
        manual = read_json(manual_path or MANUAL_NEWS_PATH, [])
        keys = _manual_keys(manual)
        if not (str(item.get("url") or "") in keys or str(item.get("title") or "").strip().lower() in keys):
            manual.append(_manual_entry(item))
            write_json(manual_path or MANUAL_NEWS_PATH, manual)
            result["promoted"] = True
        else:
            result["promoted"] = False
            result["note"] = "bereits in manual_news"
    decisions[item_id_value] = {"action": action, "at": now, "title": item.get("title")}
    save_decisions(decisions, decisions_path)
    return result
