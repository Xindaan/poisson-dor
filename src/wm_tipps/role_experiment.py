"""T-0060: Forward-A/B fuer den Rollen-/Aufstellungs-Pfad.

Misst auf ECHTEN WM-2026-Spielen, ob role-aware News (Lineup-Rollen)
Kicktipp-Punkte bringt -- die Frage, die der historische Backtest NICHT
beantworten kann (dort gibt es keine News/Lineup-Daten).

Pro Spiel und Runde werden zwei Tipps geloggt:
  - treatment: volles Modell mit Lineup-Rollen (apply_lineup_roles)
  - control:   identisch, aber role-off (alle als Starter, kein
               role-Daempfen der News)
Sobald das Ergebnis vorliegt (`data/manual_results.json`, ab Anstoss
pflegbar), werden beide Tipps mit der jeweiligen Rundenkonvention
gewertet und verglichen. Der einzige Unterschied zwischen den Armen ist
das role-Signal -> die Punktdifferenz IST der gemessene Rollen-Nutzen.
Diagnose, veraendert keine Live-Tipps.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from .context import load_context
from .fixtures import load_fixture_payload
from .io import read_json, write_json
from .lineup_roles import apply_lineup_roles
from .model import load_team_strength, predict_fixture
from .odds import odds_by_match
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import ROUND_ORDER, Score, actual_for_round, kicktipp_points

ROLE_AB_LOG_PATH = DATA_DIR / "role_ab_log.json"
ROLE_AB_REPORT_PATH = DATA_DIR / "role_ab_report.json"
ROLE_AB_MARKDOWN_PATH = EXPORTS_DIR / "role_ab_report.md"
MANUAL_RESULTS_PATH = DATA_DIR / "manual_results.json"

ROLE_OFF_SOURCE = "ab_role_off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _force_role_off(player_pool: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    pool = deepcopy(dict(player_pool))
    for roster in pool.values():
        for player in roster:
            player["role"] = "starter"  # role_factor 1.0 -> kein role-Daempfen
            player["role_source"] = ROLE_OFF_SOURCE
    return pool


def _load_inputs():
    fixtures_payload = load_fixture_payload()
    fixtures = fixtures_payload.get("fixtures", [])
    strengths = load_team_strength()
    market_payload = read_json(DATA_DIR / "market_signals.json", {"odds": [], "markets": []})
    news_payload = read_json(DATA_DIR / "news_items.json", {"items": []})
    context_payload = load_context()
    odds_lookup = odds_by_match(market_payload.get("odds", []))
    pool_payload = read_json(DATA_DIR / "player_pool.json", {"players": {}})
    player_pool = (pool_payload or {}).get("players", {}) if isinstance(pool_payload, dict) else {}
    return fixtures, strengths, news_payload.get("items", []), odds_lookup, context_payload, player_pool


def compute_role_ab_tips() -> list[dict[str, Any]]:
    fixtures, strengths, news, odds_lookup, context, pool = _load_inputs()
    pool_treatment = deepcopy(dict(pool))
    apply_lineup_roles(pool_treatment, news)
    pool_control = _force_role_off(pool)
    snapshot_at = _now().isoformat()
    entries: list[dict[str, Any]] = []
    for fixture in fixtures:
        treatment = predict_fixture(fixture, strengths, news, odds_lookup, context, pool_treatment)
        control = predict_fixture(fixture, strengths, news, odds_lookup, context, pool_control)
        stage = fixture.get("stage", "group")
        for round_id in ROUND_ORDER:
            t = treatment["round_tips"].get(round_id) or {}
            c = control["round_tips"].get(round_id) or {}
            entries.append(
                {
                    "match_id": fixture.get("match_id"),
                    "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                    "round_id": round_id,
                    "stage": stage,
                    "kickoff_utc": fixture.get("kickoff_utc"),
                    "treatment_tip": t.get("tip"),
                    "treatment": [t.get("home"), t.get("away")],
                    "control_tip": c.get("tip"),
                    "control": [c.get("home"), c.get("away")],
                    "differs": (t.get("home"), t.get("away")) != (c.get("home"), c.get("away")),
                    "snapshot_at": snapshot_at,
                }
            )
    return entries


def _entry_key(entry: Mapping[str, Any]) -> str:
    return f"{entry.get('match_id')}::{entry.get('round_id')}"


def _kickoff_passed(entry: Mapping[str, Any], now: datetime) -> bool:
    kickoff = entry.get("kickoff_utc")
    if not kickoff:
        return False
    try:
        return datetime.fromisoformat(str(kickoff)) <= now
    except ValueError:
        return False


def update_role_ab_log(
    entries: list[dict[str, Any]],
    *,
    existing: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Snapshot in den Log mergen; Eintraege nach Anpfiff einfrieren
    (letzter Pre-Kickoff-Tipp bleibt stehen)."""
    now = now or _now()
    if existing is None:
        existing = (read_json(ROLE_AB_LOG_PATH, {}) or {}).get("entries", [])
    by_key = {_entry_key(e): e for e in existing}
    for entry in entries:
        key = _entry_key(entry)
        previous = by_key.get(key)
        if previous and _kickoff_passed(previous, now):
            continue  # eingefroren
        by_key[key] = entry
    return list(by_key.values())


def normalize_manual_results(payload: Any) -> dict[str, dict[str, Any]]:
    """Rohes ``manual_results.json``-Payload -> {match_id: {actual, penalty_winner, shootout}}.

    ``shootout`` ist die reine Elfmeterbilanz und muss durchgereicht werden --
    ohne sie faellt ``actual_for_round`` auf die alte +1-Naeherung zurueck
    (T-0155).

    Als eigene Funktion, damit Aufrufer das Payload selbst lesen koennen (und
    z.B. ein gepatchtes ``read_json``/DATA_DIR respektieren), statt an
    ``MANUAL_RESULTS_PATH`` gebunden zu sein.
    """
    results = payload.get("results") if isinstance(payload, Mapping) else None
    out: dict[str, dict[str, Any]] = {}
    for match_id, value in (results or {}).items():
        if isinstance(value, list) and len(value) == 2:
            out[str(match_id)] = {
                "actual": [int(value[0]), int(value[1])],
                "penalty_winner": None,
                "shootout": None,
            }
        elif isinstance(value, Mapping) and value.get("actual"):
            actual = value["actual"]
            out[str(match_id)] = {
                "actual": [int(actual[0]), int(actual[1])],
                "penalty_winner": value.get("penalty_winner"),
                "shootout": value.get("shootout"),
            }
    return out


def load_manual_results() -> dict[str, dict[str, Any]]:
    return normalize_manual_results(read_json(MANUAL_RESULTS_PATH, {}))


def settle_role_ab(
    entries: list[dict[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rounds: dict[str, dict[str, int]] = {}
    movers: list[dict[str, Any]] = []
    for entry in entries:
        result = results.get(str(entry.get("match_id")))
        if not result or entry.get("treatment_tip") is None or entry.get("control_tip") is None:
            continue
        round_id = entry["round_id"]
        stage = entry.get("stage", "group")
        actual = actual_for_round(
            result["actual"], result.get("penalty_winner"), round_id, result.get("shootout")
        )
        treatment_points = kicktipp_points(
            Score(int(entry["treatment"][0]), int(entry["treatment"][1])), actual, stage, round_id=round_id
        )
        control_points = kicktipp_points(
            Score(int(entry["control"][0]), int(entry["control"][1])), actual, stage, round_id=round_id
        )
        bucket = rounds.setdefault(
            round_id, {"settled": 0, "treatment_points": 0, "control_points": 0, "differing": 0}
        )
        bucket["settled"] += 1
        bucket["treatment_points"] += treatment_points
        bucket["control_points"] += control_points
        if entry.get("differs"):
            bucket["differing"] += 1
            movers.append(
                {
                    "match": entry.get("match"),
                    "round_id": round_id,
                    "actual": actual.label,
                    "treatment_tip": entry.get("treatment_tip"),
                    "treatment_points": treatment_points,
                    "control_tip": entry.get("control_tip"),
                    "control_points": control_points,
                    "delta": treatment_points - control_points,
                }
            )
    for bucket in rounds.values():
        bucket["delta"] = bucket["treatment_points"] - bucket["control_points"]
    settled = sum(b["settled"] for b in rounds.values())
    treatment_total = sum(b["treatment_points"] for b in rounds.values())
    control_total = sum(b["control_points"] for b in rounds.values())
    differing = sum(b["differing"] for b in rounds.values())
    movers.sort(key=lambda m: m["delta"])
    if settled == 0:
        summary = (
            "Noch keine gesettleten Spiele. Ab Anstoss Ergebnisse in "
            "data/manual_results.json pflegen; dann misst der A/B den realen "
            "Rollen-Nutzen (treatment - control)."
        )
    else:
        summary = (
            f"{settled} gewertete Tipp-Slots, davon {differing} mit unterschiedlichem "
            f"Tipp (role-aware vs role-off). Netto: treatment {treatment_total} vs "
            f"control {control_total} -> {treatment_total - control_total:+d} Punkte durch "
            "Rollen/Aufstellungen."
        )
    return {
        "_meta": {
            "generated_at": _now().isoformat(),
            "settled_slots": settled,
            "differing_tips": differing,
            "treatment_points": treatment_total,
            "control_points": control_total,
            "net_delta": treatment_total - control_total,
            "summary": summary,
        },
        "per_round": [{"round_id": rid, **bucket} for rid, bucket in sorted(rounds.items())],
        "movers": movers,
    }


def build_role_ab(*, write: bool = True) -> dict[str, Any]:
    now = _now()
    entries = update_role_ab_log(compute_role_ab_tips(), now=now)
    log_payload = {"_meta": {"updated_at": now.isoformat(), "entries_count": len(entries)}, "entries": entries}
    report = settle_role_ab(entries, load_manual_results())
    if write:
        write_json(ROLE_AB_LOG_PATH, log_payload)
        write_json(ROLE_AB_REPORT_PATH, report)
        ROLE_AB_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        ROLE_AB_MARKDOWN_PATH.write_text(role_ab_markdown(report), encoding="utf-8")
    return report


def role_ab_markdown(report: Mapping[str, Any]) -> str:
    meta = report.get("_meta") or {}
    lines = [
        "# Rollen-A/B (T-0060): bringen die Aufstellungen was?",
        "",
        meta.get("summary", ""),
        "",
        f"Gewertete Tipp-Slots: {meta.get('settled_slots', 0)} | abweichend: "
        f"{meta.get('differing_tips', 0)} | netto treatment-control: "
        f"{meta.get('net_delta', 0):+d}.",
        "",
        "| Runde | gewertet | treatment | control | Delta | abweichend |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for bucket in report.get("per_round") or []:
        lines.append(
            "| {round} | {settled} | {treatment} | {control} | {delta:+d} | {differing} |".format(
                round=bucket.get("round_id"),
                settled=bucket.get("settled", 0),
                treatment=bucket.get("treatment_points", 0),
                control=bucket.get("control_points", 0),
                delta=int(bucket.get("delta", 0)),
                differing=bucket.get("differing", 0),
            )
        )
    movers = report.get("movers") or []
    if movers:
        lines.extend(
            [
                "",
                "## Spiele mit abweichendem Tipp",
                "",
                "| Spiel | Runde | Ergebnis | treatment | control | Delta |",
                "|---|---|---:|---:|---:|---:|",
            ]
        )
        for mover in movers:
            lines.append(
                "| {match} | {round} | {actual} | {t_tip} ({t_pts}) | {c_tip} ({c_pts}) | {delta:+d} |".format(
                    match=mover.get("match"),
                    round=mover.get("round_id"),
                    actual=mover.get("actual"),
                    t_tip=mover.get("treatment_tip"),
                    t_pts=mover.get("treatment_points"),
                    c_tip=mover.get("control_tip"),
                    c_pts=mover.get("control_points"),
                    delta=int(mover.get("delta", 0)),
                )
            )
    return "\n".join(lines)
