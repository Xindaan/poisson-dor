from __future__ import annotations

import importlib.util
import traceback
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .ablation import build_context_ablation
from .backtest import build_backtest_report, build_blend_weight_sweep
from .calibration_fit import build_calibration_fit
from .eval_live import build_live_eval
from .news_audit import build_news_audit
from .tip_strategy_ab import build_strategy_ab
from .favorite_host_calibration import build_favorite_host_calibration
from .role_experiment import build_role_ab, normalize_manual_results
from .bwin_exact_scores import import_bwin_exact_scores
from .bwin_match_odds import refresh_bwin_match_odds
from .context import refresh_context
from .dashboard import build_dashboard_payload, export_tips
from .fixtures import all_teams, load_fixture_payload, refresh_fixtures
from .knockout import knockout_results_freshness
from .lineups import refresh_lineups
from .io import read_json, write_json
from .matchday_command import build_matchday_command_center
from .matchday_dry_run import build_matchday_dry_run
from .model import build_predictions
from .news import refresh_news
from .odds import BWIN_SOURCE, match_odds_freshness, refresh_market_data
from .paths import DATA_DIR
from .player_pool import build_player_pool
from .source_watch import refresh_source_watch
from .strength import build_team_strengths
from .team_intel import export_matchday_checklist, refresh_team_intel_sources

# --- Optionale Pool-Analytik -------------------------------------------------
# risk_dial / rival_profiles / deficit_policy werten die Tipps der Mitspieler
# aus und brauchen dafuer personenbezogene Eingabedateien. Sie sind deshalb
# nicht Teil der oeffentlichen Verteilung. `find_spec` statt try/except, damit
# ein FEHLER IN einem der Module laut durchschlaegt und nur die ABWESENHEIT
# die Schritte still auslaesst.
POOL_ANALYTICS_AVAILABLE = importlib.util.find_spec("wm_tipps.deficit_policy") is not None
if POOL_ANALYTICS_AVAILABLE:
    from .deficit_policy import build_deficit_policy
    from .rival_profiles import build_rival_profiles
    from .risk_dial import build_risk_dial


UPDATE_ALL_STATUS_PATH = DATA_DIR / "update_all_status.json"
StepFunc = Callable[[], Any]
StepSpec = tuple[str, str, StepFunc]


def _fixture_signature(payload: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    return tuple(
        sorted(
            (
                row.get("match_id"),
                row.get("match_number"),
                row.get("stage"),
                row.get("home_team"),
                row.get("away_team"),
                row.get("status"),
                tuple(row.get("result") or ()),
                row.get("penalty_winner"),
                bool(row.get("has_pending_slot")),
            )
            for row in payload.get("fixtures", [])
        )
    )


def run_update_all(
    *,
    live_news: bool = True,
    refresh_fixture_source: bool = True,
    probe_live_sources: bool = True,
    refresh_exact_scores: bool = True,
    refresh_match_odds: bool = True,
    refresh_team_intel: bool = True,
    refresh_player_pool: bool = False,
    include_backtest_report: bool = True,
    write: bool = True,
    steps: Sequence[StepSpec] | None = None,
) -> dict[str, Any]:
    started_at = _now_iso()
    step_rows: list[dict[str, Any]] = []
    shared: dict[str, Any] = {}
    step_specs = list(steps) if steps is not None else default_update_steps(
        shared,
        live_news=live_news,
        refresh_fixture_source=refresh_fixture_source,
        probe_live_sources=probe_live_sources,
        refresh_exact_scores=refresh_exact_scores,
        refresh_match_odds=refresh_match_odds,
        refresh_team_intel=refresh_team_intel,
        refresh_player_pool=refresh_player_pool,
        include_backtest_report=include_backtest_report,
    )

    for name, label, func in step_specs:
        step_rows.append(run_update_step(name, label, func))

    quality = (
        build_update_quality_gates(
            step_rows,
            refresh_match_odds=refresh_match_odds,
            custom_steps=False,
        )
        if steps is None
        else {"status": "ok", "messages": [], "gates": []}
    )
    finished_at = _now_iso()
    ok_steps = sum(1 for row in step_rows if row.get("ok"))
    # Fehlgeschlagene Gates beim NAMEN nennen (frueher pauschal
    # "odds-freshness-gate", auch wenn ein anderes Gate rot war).
    failed_gate_names = [
        str(gate.get("name"))
        for gate in quality.get("gates", [])
        if gate.get("status") == "failed"
    ]
    failed_steps = [row["name"] for row in step_rows if not row.get("ok")]
    failed_steps.extend(failed_gate_names)
    payload = {
        "ok": ok_steps == len(step_rows) and quality.get("status") != "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "steps_total": len(step_rows),
        "steps_ok": ok_steps,
        "steps_failed": len(step_rows) - ok_steps + len(failed_gate_names),
        "failed_steps": failed_steps,
        "quality_status": quality.get("status", "ok"),
        "quality_messages": quality.get("messages", []),
        "quality_gates": quality.get("gates", []),
        "options": {
            "live_news": live_news,
            "refresh_fixture_source": refresh_fixture_source,
            "probe_live_sources": probe_live_sources,
            "refresh_exact_scores": refresh_exact_scores,
            "refresh_match_odds": refresh_match_odds,
            "refresh_team_intel": refresh_team_intel,
            "refresh_player_pool": refresh_player_pool,
            "include_backtest_report": include_backtest_report,
        },
        "steps": step_rows,
    }
    if write:
        write_json(UPDATE_ALL_STATUS_PATH, payload)
        try:
            build_dashboard_payload()
            payload["dashboard_refreshed_after_status"] = True
            write_json(UPDATE_ALL_STATUS_PATH, payload)
        except Exception as exc:  # noqa: BLE001 - Statusdatei soll trotz Dashboard-Fehler erhalten bleiben.
            payload["dashboard_refreshed_after_status"] = False
            payload["dashboard_refresh_error"] = str(exc)
            payload["ok"] = False
            payload["failed_steps"] = [*payload.get("failed_steps", []), "build-dashboard-after-status"]
            payload["steps_failed"] = int(payload.get("steps_failed", 0)) + 1
            write_json(UPDATE_ALL_STATUS_PATH, payload)
    return payload


def default_update_steps(
    shared: dict[str, Any],
    *,
    live_news: bool,
    refresh_fixture_source: bool,
    probe_live_sources: bool,
    refresh_exact_scores: bool,
    refresh_match_odds: bool,
    refresh_team_intel: bool,
    refresh_player_pool: bool,
    include_backtest_report: bool,
) -> list[StepSpec]:
    def fixture_payload() -> dict[str, Any]:
        payload = shared.get("fixtures")
        if isinstance(payload, dict):
            return payload
        payload = load_fixture_payload()
        shared["fixtures"] = payload
        return payload

    def set_fixtures() -> dict[str, Any]:
        shared["fixtures"] = refresh_fixtures(live=refresh_fixture_source)
        return shared["fixtures"]

    def set_markets() -> dict[str, Any]:
        shared["markets"] = refresh_market_data()
        return shared["markets"]

    def market_payload() -> dict[str, Any]:
        payload = shared.get("markets")
        if isinstance(payload, dict):
            return payload
        payload = read_json(DATA_DIR / "market_signals.json", {"odds": [], "markets": []})
        shared["markets"] = payload
        return payload

    def set_predictions() -> dict[str, Any]:
        shared["predictions"] = build_predictions()
        return shared["predictions"]

    def predictions_payload() -> dict[str, Any]:
        payload = shared.get("predictions")
        if isinstance(payload, dict):
            return payload
        payload = read_json(DATA_DIR / "predictions.json", {"predictions": [], "bonus": {}})
        shared["predictions"] = payload
        return payload

    def reconcile_knockout_results() -> dict[str, Any]:
        before = fixture_payload()
        before_signature = _fixture_signature(before)
        refreshed = refresh_fixtures(live=False)
        shared["fixtures"] = refreshed
        fixtures_changed = _fixture_signature(refreshed) != before_signature
        summary: dict[str, Any] = {
            "fixtures_changed": fixtures_changed,
            "fixtures": len(refreshed.get("fixtures", [])),
        }
        result: dict[str, Any] = {"summary": summary}
        if not fixtures_changed:
            return result

        # Fresh KO pairings can become visible only after late actuals land.
        # Pull match odds again with the new fixtures before rebuilding tips.
        if refresh_match_odds:
            try:
                odds_result = refresh_bwin_match_odds()
                result["bwin_match_odds"] = summarize_result(odds_result)
            except Exception as exc:  # noqa: BLE001 - final prediction rebuild should still proceed.
                result["bwin_match_odds_error"] = str(exc)
        shared["markets"] = refresh_market_data()
        refresh_context(refreshed.get("fixtures", []))
        shared["predictions"] = build_predictions()
        build_matchday_command_center(refreshed, shared["predictions"], write=True)
        build_matchday_dry_run(refreshed, shared["predictions"], write=True)
        summary["predictions_rebuilt"] = True
        summary["markets_refreshed"] = True
        return result

    steps: list[StepSpec] = [
        ("refresh-fixtures", "Spielplan/Fixture-Quelle aktualisieren", set_fixtures),
        (
            "refresh-context",
            "Host-City, Reise- und Umfeldkontext bauen",
            lambda: refresh_context(fixture_payload().get("fixtures", [])),
        ),
        (
            "build-strengths",
            "Teamstaerken aus Elo/FIFA/Form bauen",
            lambda: build_team_strengths(fixture_payload()),
        ),
    ]
    if refresh_exact_scores:
        steps.append(
            (
                "refresh-bwin-exact-scores",
                "Bwin Exact-Score-Snapshots aktualisieren",
                lambda: import_bwin_exact_scores(include_existing=True),
            )
        )
    if refresh_match_odds:
        # Bwin-1X2 nutzt die von Exact-Score gepflegten visible_events. Wenn
        # Exact-Score uebersprungen wird, arbeitet dieser Schritt mit dem
        # zuletzt gespeicherten Payload weiter und bleibt unabhaengig schaltbar.
        steps.append(
            (
                "refresh-bwin-match-odds",
                "Bwin-1X2-Matchquoten (CDS) in manual_odds.csv fortschreiben",
                refresh_bwin_match_odds,
            )
        )
    steps.extend(
        [
            ("refresh-odds", "Manuelle Quoten und Futures normalisieren", set_markets),
            (
                "source-watch",
                "Bwin/Quellen-Watch aktualisieren",
                lambda: refresh_source_watch(
                    fixture_payload().get("fixtures", []),
                    market_payload=market_payload(),
                    probe_live=probe_live_sources,
                ),
            ),
        ]
    )
    if refresh_team_intel:
        steps.append(
            (
                "refresh-team-intel-sources",
                "Team-Intel-Reachability gezielt nachpruefen",
                lambda: refresh_team_intel_sources(),
            )
        )
    steps.extend(
        [
            (
                "team-intel-checklist",
                "Chronologische Matchday-Checkliste exportieren",
                lambda: export_matchday_checklist(fixture_payload()),
            ),
            (
                "refresh-news",
                "News, manuelle Notizen und Relevanzfilter aktualisieren",
                lambda: refresh_news(
                    all_teams(fixture_payload()),
                    live=live_news,
                    per_team_limit=6,
                ),
            ),
            (
                "refresh-player-pool",
                "Topscorer-Team-Spielerpool aktualisieren",
                lambda: build_player_pool(
                    force_fetch=refresh_player_pool,
                    fixture_payload=fixture_payload(),
                ),
            ),
            (
                "refresh-lineups",
                "Bestaetigte Startelfen (ESPN, headless) fuer Spiele im Pre-Kickoff-Fenster",
                refresh_lineups,
            ),
            ("build-predictions", "Tipps, Wahrscheinlichkeiten und Boni bauen", set_predictions),
            (
                "matchday-command",
                "Operatives Matchday Command Center bauen",
                lambda: build_matchday_command_center(
                    fixture_payload(),
                    predictions_payload(),
                    write=True,
                ),
            ),
            (
                "matchday-dry-run",
                "Matchday-Workflow-Probelauf bauen",
                lambda: build_matchday_dry_run(
                    fixture_payload(),
                    predictions_payload(),
                    write=True,
                ),
            ),
        ]
    )
    if include_backtest_report:
        steps.append(
            (
                "backtest-report",
                "Odds-only-Ablation-Report aktualisieren",
                lambda: build_backtest_report(include_sample=False),
            )
        )
        steps.append(
            (
                "context-ablation",
                "Per-Signal-Kontext-Ablation aktualisieren",
                build_context_ablation,
            )
        )
    steps.append(
        (
            "role-ab",
            "Rollen-A/B (role-aware vs role-off) loggen + settlen",
            build_role_ab,
        )
    )
    steps.append(
        (
            "news-audit",
            "News-xG-Audit: aktive Mali + Fehlzuordnungs-Risikoklasse pruefen",
            build_news_audit,
        )
    )
    # Live-Auswertung (echte Ergebnisse) -- nicht backtest-gebunden, immer.
    steps.append(
        (
            "eval-live",
            "Live-Auswertung gegen echte Ergebnisse aktualisieren",
            build_live_eval,
        )
    )
    # Backtest-gestuetzte Diagnosen: nur wenn der Backtest-Report mitlaeuft
    # (sonst zu schwer). Schliesst die Stale-Luecke fuer diese Karten:
    # Blend-Sweep, Kalibrierungs-Fit, Aggressivitaets-A/B.
    if include_backtest_report:
        steps.extend(
            [
                ("blend-sweep", "Markt-Blend-Sweep aktualisieren", build_blend_weight_sweep),
                ("calibrate-fit", "Backtest-Kalibrierungs-Fit aktualisieren", build_calibration_fit),
                ("strategy-ab", "Aggressivitaets-A/B aktualisieren", build_strategy_ab),
                ("favorite-calibration", "Favoriten-/Gastgeber-Kalibrierung aktualisieren", build_favorite_host_calibration),
            ]
        )
        if POOL_ANALYTICS_AVAILABLE:
            steps.extend(
                [
                    ("risk-dial", "Risk-Dial (Chase vs Protect) aktualisieren", build_risk_dial),
                    ("rival-profiles", "Per-Spieler Tipp-Profile aktualisieren", build_rival_profiles),
                    ("deficit-policy", "Deficit-Policy Tipp-Empfehlung aktualisieren", build_deficit_policy),
                ]
            )
    steps.extend(
        [
            (
                "reconcile-knockout-results",
                "Frische KO-Ergebnisse final in Fixtures, Quoten und Tipps synchronisieren",
                reconcile_knockout_results,
            ),
            ("export-tips", "Finale Tipps und Watchlist exportieren", export_tips),
            ("build-dashboard", "Dashboard-Payload final neu bauen", build_dashboard_payload),
        ]
    )
    return steps


def build_update_quality_gates(
    step_rows: list[dict[str, Any]],
    *,
    refresh_match_odds: bool,
    custom_steps: bool = False,
) -> dict[str, Any]:
    if custom_steps:
        return {"status": "ok", "messages": [], "gates": []}
    gates: list[dict[str, Any]] = []
    messages: list[str] = []

    if refresh_match_odds:
        step = next((row for row in step_rows if row.get("name") == "refresh-bwin-match-odds"), None)
        if not step:
            gates.append(
                {
                    "name": "bwin-match-odds-import",
                    "status": "failed",
                    "message": "Bwin-Matchquoten-Import fehlt im update-all-Lauf.",
                }
            )
        elif not step.get("ok"):
            gates.append(
                {
                    "name": "bwin-match-odds-import",
                    "status": "failed",
                    "message": "Bwin-Matchquoten-Import ist fehlgeschlagen.",
                }
            )
        else:
            summary = step.get("summary") or {}
            events_probed = int(summary.get("events_probed") or 0)
            matches_with_odds = int(summary.get("matches_with_odds") or 0)
            rows_written = int(summary.get("csv_rows_updated") or 0) + int(summary.get("csv_rows_added") or 0)
            if events_probed > 0 and matches_with_odds == 0:
                status = "warning"
                message = (
                    "Bwin-CDS wurde geprobt, lieferte aber 0 1X2-Matchquoten; "
                    "Browser-/manuelle Bwin-Daten koennen aktueller sein als der automatische Import."
                )
            elif matches_with_odds > 0 and rows_written == 0:
                status = "warning"
                message = (
                    f"Bwin-CDS fand {matches_with_odds} Spiele, schrieb aber keine CSV-Zeile; "
                    "bitte pruefen, ob manual_odds.csv wirklich aktualisiert wurde."
                )
            else:
                status = "ok"
                message = (
                    f"Bwin-CDS: {matches_with_odds}/{events_probed} geprobte Events mit Quoten, "
                    f"{rows_written} CSV-Zeilen geschrieben."
                )
            gates.append(
                {
                    "name": "bwin-match-odds-import",
                    "status": status,
                    "message": message,
                    "events_probed": events_probed,
                    "matches_with_odds": matches_with_odds,
                    "csv_rows_written": rows_written,
                }
            )
    else:
        gates.append(
            {
                "name": "bwin-match-odds-import",
                "status": "skipped",
                "message": "Bwin-Matchquoten-Import wurde per Option uebersprungen.",
            }
        )

    fixtures = read_json(DATA_DIR / "fixtures.json", {"fixtures": []})
    markets = read_json(DATA_DIR / "market_signals.json", {"odds": []})
    freshness = match_odds_freshness(
        fixtures.get("fixtures", []) if isinstance(fixtures, dict) else [],
        markets.get("odds", []) if isinstance(markets, dict) else [],
        source=BWIN_SOURCE,
    )
    gates.append(
        {
            "name": "bwin-freshness",
            "status": freshness.get("status", "failed"),
            "message": freshness.get("status_detail", ""),
            "source": freshness.get("source"),
            "future_matches": freshness.get("future_matches", 0),
            "fresh_matches": freshness.get("fresh_matches", 0),
            "missing_matches": freshness.get("missing_matches", 0),
            "stale_matches": freshness.get("stale_matches", 0),
            "latest_source_update": freshness.get("latest_source_update"),
            "missing": freshness.get("missing", [])[:12],
            "stale": freshness.get("stale", [])[:12],
        }
    )

    # Beide Eingaben ueber denselben read_json/DATA_DIR ziehen, damit das Gate
    # nie fixtures aus Quelle A gegen Ergebnisse aus Quelle B prueft.
    manual_results = normalize_manual_results(read_json(DATA_DIR / "manual_results.json", {}))
    ko_freshness = knockout_results_freshness(
        fixtures.get("fixtures", []) if isinstance(fixtures, dict) else [],
        manual_results,
    )
    gates.append(
        {
            "name": "knockout-results-freshness",
            "status": ko_freshness.get("status", "failed"),
            "message": ko_freshness.get("status_detail", ""),
            "stale_results": ko_freshness.get("stale_results", []),
            "unresolved_ties": ko_freshness.get("unresolved_ties", []),
            "stages": ko_freshness.get("stages", []),
        }
    )

    rank = {"failed": 3, "warning": 2, "skipped": 1, "ok": 0}
    worst = max((str(gate.get("status") or "failed") for gate in gates), key=lambda item: rank.get(item, 3))
    status = "failed" if rank.get(worst, 3) >= 3 else "warning" if rank.get(worst, 0) == 2 else "ok"
    for gate in gates:
        if gate.get("status") in {"failed", "warning"}:
            messages.append(str(gate.get("message") or gate.get("name")))
    return {"status": status, "messages": messages, "gates": gates}


def run_update_step(name: str, label: str, func: StepFunc) -> dict[str, Any]:
    started_at = _now_iso()
    started_perf = perf_counter()
    try:
        result = func()
        ok = True
        error = None
        error_type = None
        trace = None
    except Exception as exc:  # noqa: BLE001 - update-all soll Folgechecks weiterlaufen lassen.
        result = None
        ok = False
        error = str(exc)
        error_type = exc.__class__.__name__
        trace = traceback.format_exc(limit=4)
    duration = perf_counter() - started_perf
    row = {
        "name": name,
        "label": label,
        "ok": ok,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "duration_seconds": round(duration, 3),
        "summary": summarize_result(result),
    }
    if not ok:
        row["error"] = error
        row["error_type"] = error_type
        row["trace_tail"] = trace
    return row


def summarize_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {}
    if isinstance(result, list):
        return {"items": len(result)}
    if not isinstance(result, dict):
        return {"type": type(result).__name__, "value": str(result)[:160]}

    summary: dict[str, Any] = {}
    for key in (
        "status",
        "updated_at",
        "count",
        "visible_events",
        "imported_matches",
        "probed",
        "steps_total",
        "steps_ok",
    ):
        if key in result:
            summary[key] = result.get(key)
    if "fixtures" in result and isinstance(result.get("fixtures"), list):
        summary["fixtures"] = len(result["fixtures"])
    if "groups" in result and isinstance(result.get("groups"), dict):
        summary["groups"] = len(result["groups"])
    if "items" in result and isinstance(result.get("items"), list):
        summary["items"] = len(result["items"])
    if "predictions" in result and isinstance(result.get("predictions"), list):
        summary["predictions"] = len(result["predictions"])
    if "bonus" in result and isinstance(result.get("bonus"), dict):
        summary["bonus_blocks"] = len(result["bonus"])
    if "odds" in result and isinstance(result.get("odds"), list):
        summary["odds"] = len(result["odds"])
    if "markets" in result and isinstance(result.get("markets"), list):
        summary["markets"] = len(result["markets"])
    if "sources" in result and isinstance(result.get("sources"), list):
        summary["sources"] = len(result["sources"])
    if "final_tips" in result and isinstance(result.get("final_tips"), list):
        summary["final_tips"] = len(result["final_tips"])
    if "watchlist" in result and isinstance(result.get("watchlist"), list):
        summary["watchlist"] = len(result["watchlist"])
    if "summary" in result and isinstance(result.get("summary"), dict):
        compact = {
            key: value
            for key, value in result["summary"].items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        summary["summary"] = compact
    if "_meta" in result and isinstance(result.get("_meta"), dict):
        meta = result["_meta"]
        for key in (
            "updated_at",
            "generated_at",
            "team_count",
            "teams_with_data",
            "events_probed",
            "matches_with_odds",
            "csv_rows_updated",
            "csv_rows_added",
        ):
            if key in meta and key not in summary:
                summary[key] = meta.get(key)
    return summary or {"keys": sorted(str(key) for key in result.keys())[:12]}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
