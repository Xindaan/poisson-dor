from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .io import read_csv_dicts, read_json, write_json
from .paths import DATA_DIR


OUTCOMES = ("home", "draw", "away")
MAX_MATCH_ODDS_OVERROUND = 1.25
MAX_CONSENSUS_DEVIATION = 0.12
BWIN_SOURCE = "bwin_world_cup_2026"
DEFAULT_MATCH_ODDS_FRESH_HOURS = 24.0
MAX_CONSENSUS_SOURCE_GAP_HOURS = 24.0
LOW_OVERROUND_OK_SOURCES = {
    "oddschecker_us_world_cup_2026",
    "odds_school_world_cup_2026",
    "sportytrader_world_cup_2026",
    "wincomparator_world_cup_2026",
}


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def normalize_decimal_odds(odds: Mapping[str, Any]) -> dict[str, float]:
    implied: dict[str, float] = {}
    for outcome in OUTCOMES:
        decimal = _to_float(odds.get(outcome))
        if not decimal or decimal <= 1.0:
            continue
        implied[outcome] = 1.0 / decimal
    total = sum(implied.values())
    if not implied or total <= 0:
        return {}
    return {outcome: probability / total for outcome, probability in implied.items()}


def odds_overround(odds: Mapping[str, Any]) -> float | None:
    implied = []
    for outcome in OUTCOMES:
        decimal = _to_float(odds.get(outcome))
        if not decimal or decimal <= 1.0:
            return None
        implied.append(1.0 / decimal)
    return sum(implied)


def match_odds_quality(odds: Mapping[str, Any], source: str | None = None) -> dict[str, Any]:
    overround = odds_overround(odds)
    reasons: list[str] = []
    if overround is None:
        reasons.append("incomplete_or_invalid")
    elif overround < 1.0 and source not in LOW_OVERROUND_OK_SOURCES:
        reasons.append("overround_low")
    elif overround > MAX_MATCH_ODDS_OVERROUND:
        reasons.append("overround_high")
    return {"status": "usable" if not reasons else "watch_only", "reasons": reasons}


def _has_complete_probabilities(probabilities: Mapping[str, Any]) -> bool:
    return all(outcome in probabilities for outcome in OUTCOMES)


def _dedupe_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source", "manual"))
        current = by_source.get(source)
        if current is None or str(row.get("last_updated", "")) >= str(current.get("last_updated", "")):
            by_source[source] = row
    return list(by_source.values())


def _match_number_value(fixture: Mapping[str, Any]) -> int:
    try:
        return int(fixture.get("match_number", 9999))
    except (TypeError, ValueError):
        return 9999


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def latest_source_cohort(
    rows: list[dict[str, Any]],
    *,
    max_gap_hours: float = MAX_CONSENSUS_SOURCE_GAP_HOURS,
) -> list[dict[str, Any]]:
    """Keep only sources observed close to the freshest source for a match."""
    dated = [
        (row, parsed)
        for row in rows
        for parsed in [parse_iso_datetime(row.get("last_updated"))]
        if parsed is not None
    ]
    if not dated:
        return rows
    latest = max(parsed for _, parsed in dated)
    cutoff = latest - timedelta(hours=max_gap_hours)
    cohort = [row for row, parsed in dated if parsed >= cutoff]
    return cohort if len(cohort) >= 2 else rows


def _future_fixture_rows(
    fixtures: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        kickoff = parse_iso_datetime(fixture.get("kickoff_utc"))
        if not kickoff or kickoff <= now:
            continue
        if str(fixture.get("status") or "").lower() == "played":
            continue
        rows.append(fixture)
    return sorted(rows, key=lambda row: (str(row.get("kickoff_utc", "")), _match_number_value(row)))


def _match_label(fixture: Mapping[str, Any]) -> str:
    return f"{fixture.get('home_team')} - {fixture.get('away_team')}"


def source_freshness_summary(
    odds_items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MATCH_ODDS_FRESH_HOURS,
) -> list[dict[str, Any]]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in odds_items:
        grouped.setdefault(str(row.get("source") or "manual"), []).append(row)
    summaries: list[dict[str, Any]] = []
    for source, rows in sorted(grouped.items()):
        parsed_dates = [
            parsed
            for parsed in (parse_iso_datetime(row.get("last_updated")) for row in rows)
            if parsed is not None
        ]
        latest = max(parsed_dates) if parsed_dates else None
        fresh_rows = 0
        stale_rows = 0
        invalid_rows = 0
        for row in rows:
            parsed = parse_iso_datetime(row.get("last_updated"))
            if parsed is None:
                invalid_rows += 1
                continue
            age_hours = (now - parsed).total_seconds() / 3600
            if age_hours <= max_age_hours:
                fresh_rows += 1
            else:
                stale_rows += 1
        summaries.append(
            {
                "source": source,
                "rows": len(rows),
                "fresh_rows": fresh_rows,
                "stale_rows": stale_rows,
                "invalid_rows": invalid_rows,
                "latest_updated_at": latest.isoformat() if latest else None,
                "latest_age_hours": round((now - latest).total_seconds() / 3600, 2) if latest else None,
                "status": "fresh" if fresh_rows else "stale" if stale_rows else "missing_timestamp",
            }
        )
    return summaries


def match_odds_freshness(
    fixtures: list[dict[str, Any]],
    odds_items: list[dict[str, Any]],
    *,
    source: str = BWIN_SOURCE,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MATCH_ODDS_FRESH_HOURS,
) -> dict[str, Any]:
    """Summarize whether upcoming fixtures have fresh odds from one source.

    Coverage (`odds_coverage`) answers "do we have usable odds?". This answers
    the operational update question: "are the odds fresh enough for the next
    Kicktipp transfer?".
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    future = _future_fixture_rows(fixtures, now=now)
    by_match: dict[str, list[dict[str, Any]]] = {}
    for row in odds_items:
        if row.get("source") != source:
            continue
        match_id = str(row.get("match_id") or "")
        if match_id:
            by_match.setdefault(match_id, []).append(row)

    fresh_matches: list[dict[str, Any]] = []
    stale_matches: list[dict[str, Any]] = []
    missing_matches: list[dict[str, Any]] = []
    latest_source_update: datetime | None = None
    for fixture in future:
        match_id = str(fixture.get("match_id") or "")
        rows = by_match.get(match_id, [])
        dated_rows = [
            (parsed, row)
            for row in rows
            for parsed in [parse_iso_datetime(row.get("last_updated"))]
            if parsed is not None
        ]
        if not dated_rows:
            missing_matches.append(
                {
                    "match_id": match_id,
                    "match": _match_label(fixture),
                    "match_number": fixture.get("match_number"),
                    "kickoff_utc": fixture.get("kickoff_utc"),
                    "reason": "missing",
                }
            )
            continue
        updated_at, row = max(dated_rows, key=lambda item: item[0])
        latest_source_update = updated_at if latest_source_update is None else max(latest_source_update, updated_at)
        age_hours = (now - updated_at).total_seconds() / 3600
        item = {
            "match_id": match_id,
            "match": _match_label(fixture),
            "match_number": fixture.get("match_number"),
            "kickoff_utc": fixture.get("kickoff_utc"),
            "last_updated": updated_at.isoformat(),
            "age_hours": round(age_hours, 2),
            "decimal_odds": row.get("decimal_odds"),
        }
        if age_hours <= max_age_hours:
            fresh_matches.append(item)
        else:
            stale_matches.append({**item, "reason": "stale"})

    total = len(future)
    fresh_count = len(fresh_matches)
    missing_count = len(missing_matches)
    stale_count = len(stale_matches)
    if total == 0:
        status = "ok"
        status_detail = "Keine kommenden Spiele im Fixture-Set."
    elif fresh_count == total:
        status = "ok"
        status_detail = f"{fresh_count}/{total} kommende Spiele haben frische {source}-Quoten."
    elif fresh_count == 0:
        status = "failed"
        status_detail = f"0/{total} kommende Spiele haben frische {source}-Quoten."
    else:
        status = "warning"
        status_detail = (
            f"{fresh_count}/{total} kommende Spiele haben frische {source}-Quoten; "
            f"{missing_count} fehlen, {stale_count} sind alt."
        )

    return {
        "source": source,
        "now": now.isoformat(),
        "max_age_hours": max_age_hours,
        "status": status,
        "status_detail": status_detail,
        "future_matches": total,
        "fresh_matches": fresh_count,
        "missing_matches": missing_count,
        "stale_matches": stale_count,
        "latest_source_update": latest_source_update.isoformat() if latest_source_update else None,
        "fresh": fresh_matches,
        "missing": missing_matches,
        "stale": stale_matches,
        "sources": source_freshness_summary(odds_items, now=now, max_age_hours=max_age_hours),
    }


def market_quality(
    spread: float | None,
    liquidity: float | None,
    updated_at: str | None,
    *,
    probability: float | None = None,
    source_type: str | None = None,
    max_spread: float = 0.08,
    min_liquidity: float = 1000.0,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    effective_max_age = (
        168.0
        if source_type == "bookmaker_futures" and max_age_hours is None
        else 24.0 if max_age_hours is None else max_age_hours
    )
    if source_type == "bookmaker_futures":
        if probability is None or probability <= 0.0 or probability >= 1.0:
            reasons.append("probability_invalid")
    else:
        if spread is None:
            reasons.append("spread_missing")
        elif spread > max_spread:
            reasons.append("spread_wide")
        if liquidity is None:
            reasons.append("liquidity_missing")
        elif liquidity < min_liquidity:
            reasons.append("liquidity_thin")
    if updated_at:
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_hours = (now - parsed).total_seconds() / 3600
            if age_hours > effective_max_age:
                reasons.append("stale")
        except ValueError:
            reasons.append("timestamp_invalid")
    else:
        reasons.append("timestamp_missing")
    status = "usable" if not reasons else "watch_only"
    return {"status": status, "reasons": reasons}


def load_manual_odds(path=None) -> list[dict[str, Any]]:
    path = path or DATA_DIR / "manual_odds.csv"
    rows = []
    for row in read_csv_dicts(path):
        probabilities = normalize_decimal_odds(row)
        decimal_odds = {
            "home": _to_float(row.get("home")),
            "draw": _to_float(row.get("draw")),
            "away": _to_float(row.get("away")),
        }
        rows.append(
            {
                "match_id": row.get("match_id", ""),
                "source": row.get("source", "manual"),
                "last_updated": row.get("last_updated", ""),
                "decimal_odds": decimal_odds,
                "overround": odds_overround(row),
                "quality": match_odds_quality(row, row.get("source")),
                "probabilities": probabilities,
            }
        )
    return rows


def load_manual_markets(path=None) -> list[dict[str, Any]]:
    path = path or DATA_DIR / "manual_markets.json"
    items = read_json(path, [])
    normalized = []
    for item in items:
        probability = _to_float(item.get("probability"))
        spread = _to_float(item.get("spread"))
        liquidity = _to_float(item.get("liquidity"))
        max_age_hours = _to_float(item.get("max_age_hours"))
        normalized.append(
            {
                **item,
                "probability": probability,
                "spread": spread,
                "liquidity": liquidity,
                "quality": market_quality(
                    spread,
                    liquidity,
                    item.get("last_updated"),
                    probability=probability,
                    source_type=item.get("source_type"),
                    max_age_hours=max_age_hours,
                ),
            }
        )
    return normalized


def refresh_market_data() -> dict[str, Any]:
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "odds": load_manual_odds(),
        "markets": load_manual_markets(),
    }
    write_json(DATA_DIR / "market_signals.json", payload)
    return payload


def odds_by_match(odds_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in odds_items:
        match_id = item.get("match_id")
        probabilities = item.get("probabilities") or {}
        if match_id and _has_complete_probabilities(probabilities):
            grouped.setdefault(match_id, []).append(item)
    best: dict[str, dict[str, Any]] = {}
    for match_id, rows in grouped.items():
        best[match_id] = consensus_odds(match_id, rows)
    return best


def consensus_odds(match_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        row for row in rows
        if row.get("probabilities")
        and (row.get("quality") or {}).get("status", "usable") == "usable"
    ]
    usable = latest_source_cohort(_dedupe_sources(usable))
    usable = drop_consensus_outliers(usable)
    if not usable:
        usable = latest_source_cohort(
            _dedupe_sources([row for row in rows if row.get("probabilities")])
        )
    if len(usable) == 1:
        row = dict(usable[0])
        row["source_count"] = 1
        row["sources"] = [row.get("source", "manual")]
        return row

    probabilities = {
        outcome: sum(float(row["probabilities"][outcome]) for row in usable) / len(usable)
        for outcome in OUTCOMES
    }
    decimal_odds = {
        outcome: round(
            sum(float(row["decimal_odds"][outcome]) for row in usable) / len(usable),
            4,
        )
        for outcome in OUTCOMES
    }
    sources = sorted({str(row.get("source", "manual")) for row in usable})
    updated = max(str(row.get("last_updated", "")) for row in usable)
    overrounds = [
        float(row["overround"]) for row in usable
        if row.get("overround") is not None
    ]
    return {
        "match_id": match_id,
        "source": f"consensus_{len(sources)}_sources",
        "sources": sources,
        "source_count": len(sources),
        "last_updated": updated,
        "decimal_odds": decimal_odds,
        "probabilities": {outcome: round(value, 4) for outcome, value in probabilities.items()},
        "overround": round(sum(overrounds) / len(overrounds), 4) if overrounds else None,
        "quality": {"status": "usable", "reasons": []},
    }


def drop_consensus_outliers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) < 3:
        return rows
    medians = {}
    for outcome in OUTCOMES:
        values = sorted(float(row["probabilities"][outcome]) for row in rows)
        medians[outcome] = values[len(values) // 2]
    kept = []
    for row in rows:
        max_deviation = max(
            abs(float(row["probabilities"][outcome]) - medians[outcome])
            for outcome in OUTCOMES
        )
        if max_deviation <= MAX_CONSENSUS_DEVIATION:
            kept.append(row)
    return kept if len(kept) >= 2 else rows


def odds_coverage(fixtures: list[dict[str, Any]], odds_items: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in odds_items:
        match_id = item.get("match_id")
        if match_id:
            grouped.setdefault(str(match_id), []).append(item)
    consensus = odds_by_match(odds_items)
    rows = []
    status_counts: dict[str, int] = {}
    source_count_distribution: dict[str, int] = {}
    for fixture in sorted(fixtures, key=lambda row: (str(row.get("kickoff_utc", "")), _match_number_value(row))):
        match_id = str(fixture.get("match_id") or "")
        raw = grouped.get(match_id, [])
        raw_sources = sorted({str(row.get("source", "manual")) for row in raw})
        complete_usable = [
            row for row in raw
            if _has_complete_probabilities(row.get("probabilities") or {})
            and (row.get("quality") or {}).get("status", "usable") == "usable"
        ]
        usable_sources = sorted({str(row.get("source", "manual")) for row in complete_usable})
        consensus_item = consensus.get(match_id)
        consensus_count = int((consensus_item or {}).get("source_count") or 0)
        if consensus_count >= 3:
            status = "strong"
        elif consensus_count == 2:
            status = "ok"
        elif consensus_count == 1:
            status = "single_source"
        elif raw_sources:
            status = "watch_only"
        else:
            status = "missing"
        status_counts[status] = status_counts.get(status, 0) + 1
        source_count_distribution[str(consensus_count)] = source_count_distribution.get(str(consensus_count), 0) + 1
        overrounds = [
            float(row["overround"]) for row in raw
            if row.get("overround") is not None
        ]
        quality_reasons = sorted({
            str(reason)
            for row in raw
            for reason in ((row.get("quality") or {}).get("reasons") or [])
        })
        rows.append(
            {
                "match_id": match_id,
                "match_number": fixture.get("match_number"),
                "kickoff_utc": fixture.get("kickoff_utc"),
                "group": fixture.get("group"),
                "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                "raw_source_count": len(raw_sources),
                "raw_sources": raw_sources,
                "usable_source_count": len(usable_sources),
                "usable_sources": usable_sources,
                "consensus_source_count": consensus_count,
                "consensus_sources": (consensus_item or {}).get("sources") or [],
                "status": status,
                "overround_min": round(min(overrounds), 4) if overrounds else None,
                "overround_max": round(max(overrounds), 4) if overrounds else None,
                "quality_reasons": quality_reasons,
            }
        )
    summary = {
        "total": len(rows),
        "with_raw_odds": sum(1 for row in rows if row["raw_source_count"] > 0),
        "with_consensus": sum(1 for row in rows if row["consensus_source_count"] > 0),
        "missing": sum(1 for row in rows if row["status"] == "missing"),
        "strong": sum(1 for row in rows if row["status"] == "strong"),
        "status_counts": status_counts,
        "source_count_distribution": source_count_distribution,
    }
    return {"summary": summary, "matches": rows}
