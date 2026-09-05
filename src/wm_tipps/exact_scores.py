from __future__ import annotations

import re
from typing import Any

from .io import read_json
from .paths import DATA_DIR


EXACT_SCORE_PATH = DATA_DIR / "manual_exact_score_odds.json"
EXACT_SCORE_CALIBRATION_SOURCES_PATH = DATA_DIR / "exact_score_calibration_sources.json"
SCORE_RE = re.compile(r"^\d{1,2}:\d{1,2}$")


def parse_decimal(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if parsed <= 1.0:
        return None
    return parsed


def load_exact_score_payload(path=EXACT_SCORE_PATH) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "items": [], "visible_events": []})
    if isinstance(payload, list):
        payload = {"_meta": {}, "items": payload, "visible_events": []}
    if not isinstance(payload, dict):
        return {"_meta": {}, "items": [], "visible_events": []}
    return {
        "_meta": payload.get("_meta") or {},
        "items": normalise_exact_score_items(payload.get("items") or []),
        "visible_events": payload.get("visible_events") or [],
    }


def load_exact_score_calibration_sources(path=EXACT_SCORE_CALIBRATION_SOURCES_PATH) -> dict[str, Any]:
    payload = read_json(path, {"_meta": {}, "decision": {}, "sources": []})
    if not isinstance(payload, dict):
        return {"_meta": {}, "decision": {}, "sources": []}
    return {
        "_meta": payload.get("_meta") or {},
        "decision": payload.get("decision") or {},
        "sources": [row for row in payload.get("sources", []) if isinstance(row, dict)],
    }


def normalise_exact_score_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalised = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        prices = []
        seen: set[str] = set()
        for price in item.get("prices") or []:
            if not isinstance(price, dict):
                continue
            score = str(price.get("score") or price.get("selection") or "").strip()
            decimal_odds = parse_decimal(price.get("decimal_odds") or price.get("odds"))
            if not SCORE_RE.fullmatch(score) or decimal_odds is None or score in seen:
                continue
            seen.add(score)
            prices.append({"score": score, "decimal_odds": decimal_odds})
        row["prices"] = prices
        row["explicit_score_count"] = len(prices)
        row["quality"] = exact_score_quality(row)
        row["overround_explicit"] = round(sum(1.0 / p["decimal_odds"] for p in prices), 4)
        normalised.append(row)
    return normalised


def exact_score_quality(item: dict[str, Any]) -> dict[str, Any]:
    reasons = ["display_only_until_backtested"]
    if item.get("has_other_selection"):
        reasons.append("other_score_bucket_not_modelled")
    if len(item.get("prices") or []) < 20:
        reasons.append("partial_score_grid")
    if item.get("market") == "exact_score_regular_time":
        reasons.append("regular_time_market")
    return {"status": "watch_only", "reasons": reasons}


def exact_scores_by_match(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["match_id"]: item for item in items if item.get("match_id")}


def market_probabilities(item: dict[str, Any]) -> dict[str, float]:
    prices = item.get("prices") or []
    total = sum(1.0 / price["decimal_odds"] for price in prices)
    if total <= 0:
        return {}
    return {price["score"]: (1.0 / price["decimal_odds"]) / total for price in prices}


def build_exact_score_comparison(
    predictions: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
    source_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = payload or load_exact_score_payload()
    if source_audit is None:
        source_audit = load_exact_score_calibration_sources()
    items = payload.get("items") or []
    items_by_match = exact_scores_by_match(items)
    matches = []
    for prediction in predictions:
        match_id = prediction.get("match_id")
        item = items_by_match.get(match_id)
        if not item:
            continue
        matches.append(compare_prediction_to_exact_score_market(prediction, item))
    visible_events = payload.get("visible_events") or []
    imported_ids = {row.get("match_id") for row in items if row.get("match_id")}
    summary = {
        "visible_bwin_events": len(visible_events),
        "imported_matches": len(imported_ids),
        "not_imported_visible_events": sum(
            1 for row in visible_events if row.get("match_id") not in imported_ids
        ),
        "model_market_favorite_disagreements": sum(
            1
            for row in matches
            if row.get("model_favorite_score")
            and row.get("market_favorite_score")
            and row.get("model_favorite_score") != row.get("market_favorite_score")
        ),
        "recommended_tip_price_available": sum(
            1 for row in matches if row.get("recommended_tip_odds") is not None
        ),
    }
    return {
        "_meta": payload.get("_meta") or {},
        "summary": summary,
        "calibration": exact_score_calibration_decision(matches, source_audit),
        "matches": matches,
        "visible_events": visible_events,
    }


def exact_score_calibration_decision(
    matches: list[dict[str, Any]],
    source_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if source_audit is None:
        source_audit = load_exact_score_calibration_sources()
    audit_sources = source_audit.get("sources") or []
    audit_decision = source_audit.get("decision") or {}
    disagreement_count = sum(
        1
        for row in matches
        if row.get("model_favorite_score")
        and row.get("market_favorite_score")
        and row.get("model_favorite_score") != row.get("market_favorite_score")
    )
    return {
        "status": "watch_only",
        "reason": audit_decision.get("reason")
        or "no_historical_bwin_exact_score_backtest_dataset",
        "imported_matches": len(matches),
        "model_market_favorite_disagreements": disagreement_count,
        "source_audit_status": audit_decision.get("status") or "watch_only",
        "searched_sources_count": len(audit_sources),
        "accepted_sources_count": sum(1 for row in audit_sources if row.get("accepted") is True),
        "source_audit_updated_at": (source_audit.get("_meta") or {}).get("updated_at"),
        "recommendation": (
            audit_decision.get("recommendation")
            or (
                "Use Bwin exact-score as a manual watch/disagreement signal. Do not blend into "
                "scoreline probabilities until a historical exact-score snapshot dataset proves "
                "positive calibrated value against the current model/backtests."
            )
        ),
    }


def compare_prediction_to_exact_score_market(
    prediction: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    probs = market_probabilities(item)
    model_scores = {
        row.get("score"): row.get("probability")
        for row in prediction.get("top_scores", [])
        if row.get("score")
    }
    market_rows = sorted(
        (
            {
                "score": price["score"],
                "decimal_odds": price["decimal_odds"],
                "no_vig_probability": round(probs.get(price["score"], 0.0), 4),
                "model_probability": model_scores.get(price["score"]),
            }
            for price in item.get("prices", [])
        ),
        key=lambda row: row["decimal_odds"],
    )
    model_top = [row.get("score") for row in (prediction.get("top_scores") or [])[:6]]
    market_top = [row["score"] for row in market_rows[:6]]
    recommended_tip = (prediction.get("recommended_tip") or {}).get("tip")
    recommended_market = next(
        (row for row in market_rows if row["score"] == recommended_tip),
        None,
    )
    favorite = market_rows[0] if market_rows else None
    fixture = prediction.get("fixture") or {}
    return {
        "match_id": prediction.get("match_id"),
        "match_number": fixture.get("match_number"),
        "kickoff_utc": fixture.get("kickoff_utc"),
        "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
        "source": item.get("source"),
        "market": item.get("market"),
        "event_url": item.get("event_url"),
        "observed_at": item.get("observed_at"),
        "price_count": len(item.get("prices") or []),
        "overround_explicit": item.get("overround_explicit"),
        "quality": item.get("quality"),
        "model_favorite_score": (prediction.get("top_scores") or [{}])[0].get("score"),
        "market_favorite_score": favorite["score"] if favorite else None,
        "market_favorite_odds": favorite["decimal_odds"] if favorite else None,
        "recommended_tip": recommended_tip,
        "recommended_tip_odds": recommended_market["decimal_odds"] if recommended_market else None,
        "recommended_tip_market_probability": (
            recommended_market["no_vig_probability"] if recommended_market else None
        ),
        "top_overlap": sorted(set(model_top) & set(market_top)),
        "market_top_scores": market_rows[:8],
    }
