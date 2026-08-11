from __future__ import annotations

import importlib.util

import re
from datetime import datetime, timezone
from typing import Any

from .exact_scores import build_exact_score_comparison, load_exact_score_payload
from .fixtures import load_fixture_payload
from .historical_markets import historical_market_payload_summary, load_historical_market_payload
from .history import enrich_history_events
from .io import read_json, write_json, write_csv_dicts
from .lint import run_lint
from .news import (
    XG_IMPACT_CATEGORIES,
    dedupe_model_relevant_news,
    is_model_relevant_news,
    severity_rank,
)
from .odds import BWIN_SOURCE, match_odds_freshness, odds_coverage, parse_iso_datetime
from .paths import DATA_DIR, EXPORTS_DIR, PROJECT_ROOT
from .scoring import (
    DEFAULT_ROUND_ID,
    ROUND_ORDER,
    is_stage_tippable,
    round_name,
    round_rules_payload,
)
from .team_intel import team_intel_report


# Quoten, die aelter sind als dies, werden in der Match-Kachel als veraltet
# markiert. Bewusst milder als das operative Freshness-Gate
# (DEFAULT_MATCH_ODDS_FRESH_HOURS=24), damit die Dauer-Notiz nicht bei jedem
# Spiel schreit, aber klar veraltete oder fehlende Quoten sichtbar werden.
ODDS_TILE_STALE_HOURS = 72.0


def odds_status_for_prediction(
    prediction: dict[str, Any],
    *,
    now: datetime,
    stale_hours: float = ODDS_TILE_STALE_HOURS,
) -> dict[str, Any] | None:
    """Per-Match-Status fuer die Quoten-Notiz in der Match-Kachel.

    Nur fuer noch nicht gespielte Spiele relevant (der Tipp zaehlt noch):
    - "missing": keine Marktquoten -> Tipp rein modellbasiert, nicht
      marktkorrigiert (genau der Fall, der in der K.o.-Runde Punkte kostete).
    - "stale": Quoten vorhanden, aber aelter als ``stale_hours``.
    - "ok": frische Quoten.
    Liefert ``None`` fuer bereits gespielte Spiele (dort zaehlt der Tipp nicht
    mehr, eine Notiz waere nur Rauschen).
    """
    fixture = prediction.get("fixture") or {}
    if fixture.get("status") == "played":
        return None
    odds = prediction.get("odds")
    if not odds:
        return {"state": "missing", "last_updated": None, "age_hours": None}
    last_updated = parse_iso_datetime(odds.get("last_updated"))
    if last_updated is None:
        return {"state": "stale", "last_updated": None, "age_hours": None}
    age_hours = (now - last_updated).total_seconds() / 3600
    state = "stale" if age_hours > stale_hours else "ok"
    return {
        "state": state,
        "last_updated": last_updated.isoformat(),
        "age_hours": round(age_hours, 1),
    }


CLI_UI_COMMANDS = [
    {
        "command": "refresh-fixtures",
        "group": "Grunddaten",
        "purpose": "Spielplan aktualisieren.",
        "ui_section": "Spiele / Statusleiste / Pipeline",
        "artifacts": ["data/fixtures.json"],
        "run_args": ["refresh-fixtures"],
    },
    {
        "command": "refresh-context",
        "group": "Kontext",
        "purpose": "Host-City, Reise- und Umfeldkontext bauen.",
        "ui_section": "Spiele / Pipeline",
        "artifacts": ["data/context.json"],
        "run_args": ["refresh-context"],
    },
    {
        "command": "refresh-news",
        "group": "News",
        "purpose": "News, manuelle Notizen und Relevanzfilter aktualisieren.",
        "ui_section": "News-Radar / Watchlist / Pipeline",
        "artifacts": ["data/news_items.json"],
        "run_args": ["refresh-news"],
    },
    {
        "command": "refresh-odds",
        "group": "Quoten",
        "purpose": "Matchquoten und Futures normalisieren.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/market_signals.json"],
        "run_args": ["refresh-odds"],
    },
    {
        "command": "refresh-markets",
        "group": "Quoten",
        "purpose": "Alias fuer Markt-/Quotenrefresh.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/market_signals.json"],
        "run_args": ["refresh-markets"],
    },
    {
        "command": "refresh-historical-markets",
        "group": "Backtest",
        "purpose": "Freie historische O/U-, BTTS- und Handicap-Linien fuer Score-Kalibrierung importieren.",
        "ui_section": "Quoten & Maerkte / Pipeline / Lohnt sich das?",
        "artifacts": ["data/historical_market_lines.json", "data/historical_market_line_sources.json"],
        "run_args": ["refresh-historical-markets"],
    },
    {
        "command": "odds-report",
        "group": "Quoten",
        "purpose": "Quotenabdeckung und Konsensstaerke pruefen.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/market_signals.json"],
        "run_args": ["odds-report"],
    },
    {
        "command": "odds-history",
        "group": "Quoten",
        "purpose": "Quotenbewegungen ueber Zeit (append-on-change Snapshot-Historie).",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/odds_snapshots.jsonl"],
        "run_args": ["odds-history"],
    },
    {
        "command": "news-review",
        "group": "News",
        "purpose": "Review-Queue moeglicher Modell-News (promote/dismiss, human-in-the-loop).",
        "ui_section": "News-Radar / Pipeline",
        "artifacts": ["data/news_items.json"],
        "run_args": ["news-review"],
    },
    {
        "command": "lineup-lock",
        "group": "Lineups",
        "purpose": "Pre-Kickoff Aufstellungs-Readiness je Spiel im Fenster.",
        "ui_section": "Pipeline",
        "artifacts": ["data/manual_lineups.json", "data/news_items.json"],
        "run_args": ["lineup-lock"],
    },
    {
        "command": "refresh-lineups",
        "group": "Lineups",
        "purpose": "Bestaetigte Startelfen headless aus ESPN (Pre-Kickoff-Fenster) -> manual_lineups.json.",
        "ui_section": "Pipeline",
        "artifacts": ["data/manual_lineups.json"],
        "run_args": ["refresh-lineups"],
    },
    {
        "command": "signal-breaker",
        "group": "Live-Kalibrierung",
        "purpose": "Per-Signal Live-Kalibrierung (gated, advisory).",
        "ui_section": "Pipeline",
        "artifacts": ["data/predictions.json"],
        "run_args": ["signal-breaker"],
    },
    {
        "command": "totals-adjust",
        "group": "Live-Kalibrierung",
        "purpose": "Turnier-Torlevel vs Modell, geshrinkte λ-Empfehlung (gated, advisory).",
        "ui_section": "Pipeline",
        "artifacts": ["data/predictions.json"],
        "run_args": ["totals-adjust"],
    },
    {
        "command": "exact-score-report",
        "group": "Exact-Score",
        "purpose": "Bwin Exact-Score gegen Modell-Tipps vergleichen.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/manual_exact_score_odds.json", "data/exact_score_calibration_sources.json"],
        "run_args": ["exact-score-report"],
    },
    {
        "command": "refresh-bwin-exact-scores",
        "group": "Exact-Score",
        "purpose": "Freie Bwin-CDS-Exact-Score-Snapshots importieren.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/manual_exact_score_odds.json"],
        "run_args": ["refresh-bwin-exact-scores"],
    },
    {
        "command": "refresh-bwin-match-odds",
        "group": "Quoten",
        "purpose": "Bwin-1X2-Matchquoten (CDS, headless) in manual_odds.csv fortschreiben.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/manual_odds.csv"],
        "run_args": ["refresh-bwin-match-odds"],
    },
    {
        "command": "team-intel-report",
        "group": "Team-Intel",
        "purpose": "Team-Intel-Quellen, Freshness und Reachability auswerten.",
        "ui_section": "News-Radar / Pipeline",
        "artifacts": ["data/team_intel_sources.json"],
        "run_args": ["team-intel-report"],
    },
    {
        "command": "team-intel-checklist",
        "group": "Team-Intel",
        "purpose": "Chronologische Spieltagschecks exportieren.",
        "ui_section": "News-Radar / Watchlist / Pipeline",
        "artifacts": [
            "data/team_intel_matchday_checklist.json",
            "exports/team_intel_matchday_checklist.csv",
            "exports/team_intel_matchday_checklist.md",
        ],
        "run_args": ["team-intel-checklist"],
    },
    {
        "command": "refresh-team-intel-sources",
        "group": "Team-Intel",
        "purpose": "Kostenlose Reachability der Team-Intel-Quellen pruefen.",
        "ui_section": "News-Radar / Pipeline",
        "artifacts": ["data/team_intel_sources.json"],
        "run_args": ["refresh-team-intel-sources"],
    },
    {
        "command": "source-watch",
        "group": "Quellenwatch",
        "purpose": "Bwin und andere beobachtete Quellen ueberwachen.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/source_watch_status.json", "data/source_watch_manual.json"],
        "run_args": ["source-watch"],
    },
    {
        "command": "build-predictions",
        "group": "Modell",
        "purpose": "Tippmodell, Wahrscheinlichkeiten und Bonus bauen.",
        "ui_section": "Spiele / Bonus / Watchlist / Pipeline",
        "artifacts": ["data/predictions.json", "data/prediction_history.json"],
        "run_args": ["build-predictions"],
    },
    {
        "command": "build-strengths",
        "group": "Modell",
        "purpose": "Teamstaerken aus Elo, FIFA-Rang und Form bauen.",
        "ui_section": "Spiele / Pipeline",
        "artifacts": ["data/team_strength.json", "data/team_strength_inputs.json"],
        "run_args": ["build-strengths"],
    },
    {
        "command": "build-dashboard",
        "group": "Dashboard",
        "purpose": "Dashboard-Payload aus vorhandenen Artefakten bauen.",
        "ui_section": "Pipeline",
        "artifacts": ["data/dashboard.json"],
        "run_args": ["build-dashboard"],
    },
    {
        "command": "export-tips",
        "group": "Export",
        "purpose": "Finale Kicktipp-Liste und CSV exportieren.",
        "ui_section": "Finale Tipps / Pipeline",
        "artifacts": ["exports/final_tips.csv", "exports/final_tips.md"],
        "run_args": ["export-tips"],
    },
    {
        "command": "backtest",
        "group": "Backtest",
        "purpose": "Legacy-/Turnier-Backtests fuer Variantenvergleich bauen.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": [
            "data/backtest_result.json",
            "data/backtest_result_2018.json",
            "data/backtest_result_2022.json",
        ],
        "run_args": ["backtest"],
    },
    {
        "command": "backtest-report",
        "group": "Backtest",
        "purpose": "Odds-only-Ablation und Lohnt-sich-das-Verdict bauen.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/backtest_report.json", "exports/backtest_report.md"],
        "run_args": ["backtest-report"],
    },
    {
        "command": "context-ablation",
        "group": "Backtest",
        "purpose": "Per-Signal-Ablation der Kontext-Effekte: bewegt jeder kleine Effekt wirklich einen Tipp?",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/context_ablation.json", "exports/context_ablation.md"],
        "run_args": ["context-ablation"],
    },
    {
        "command": "lineup-roles",
        "group": "Spielerdaten",
        "purpose": "role aus echten Aufstellungen (manuelle XIs + confirmed/expected-Lineup-News); Dry-Run-Zaehler.",
        "ui_section": "Pipeline",
        "artifacts": ["data/manual_lineups.json"],
        "run_args": ["lineup-roles"],
    },
    {
        "command": "blend-sweep",
        "group": "Backtest",
        "purpose": "Markt-Blend-Gewicht (0..100%) gegen die Quoten-Spiele sweepen: haelt das Live-Gewicht 15%?",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/blend_sweep.json", "exports/blend_sweep.md"],
        "run_args": ["blend-sweep"],
    },
    {
        "command": "role-ab",
        "group": "Spielerdaten",
        "purpose": "Forward-A/B: misst auf echten Spielen, ob role-aware (Lineups) vs role-off Punkte bringt.",
        "ui_section": "Pipeline",
        "artifacts": ["data/role_ab_report.json", "data/role_ab_log.json", "exports/role_ab_report.md"],
        "run_args": ["role-ab"],
    },
    {
        "command": "news-audit",
        "group": "Spielerdaten",
        "purpose": "Read-only Diagnose: welche News erzeugen einen xG-Malus, wo droht Fehlzuordnung (Multi-Team, Fremd-Subject, stale)?",
        "ui_section": "Pipeline",
        "artifacts": ["data/news_audit.json", "exports/news_audit.md"],
        "run_args": ["news-audit"],
    },
    {
        "command": "eval-live",
        "group": "Backtest",
        "purpose": "Live-Lernschleife: Modell-Tipps gegen echte Ergebnisse -- erzielte Punkte/Runde + Brier/Log-Loss Modell/Markt/Blend + Drift.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/live_eval.json", "exports/live_eval.md"],
        "run_args": ["eval-live"],
    },
    {
        "command": "strategy-ab",
        "group": "Backtest",
        "purpose": "Aggressivitaets-A/B: kappa-Tor-Inflation vor EP-Max, Punkte + Exakt je kappa (Backtest + live). Tippt das Modell zu konservativ?",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/strategy_ab.json", "exports/strategy_ab.md"],
        "run_args": ["strategy-ab"],
    },
    {
        "command": "favorite-calibration",
        "group": "Backtest",
        "purpose": "Favoriten-/Gastgeber-Kalibrierung: ist das Modell auf Favoriten under-confident (vs Markt)? Deckt der +0.18-Host-Bonus den realen Heimturnier-Effekt? Reliability je Prob-Bin ueber 405 Spiele.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/favorite_host_calibration.json", "exports/favorite_host_calibration.md"],
        "run_args": ["favorite-calibration"],
    },
    {
        "command": "calibrate-fit",
        "group": "Backtest",
        "purpose": "Offline within-class Temperatur-Fit (T-0073): ist das Modell innerhalb der Ergebnis-Klasse zu scharf/unscharf? Read-only.",
        "ui_section": "Quoten & Maerkte / Pipeline",
        "artifacts": ["data/calibration_fit.json", "exports/calibration_fit.md"],
        "run_args": ["calibrate-fit"],
    },
    {
        "command": "matchday-dry-run",
        "group": "Matchday",
        "purpose": "Spieltagssimulation fuer Watchlist, History und Tipps pruefen.",
        "ui_section": "Watchlist / Pipeline",
        "artifacts": ["data/matchday_dry_run.json", "exports/matchday_dry_run.md"],
        "run_args": ["matchday-dry-run"],
    },
    {
        "command": "matchday-command",
        "group": "Matchday",
        "purpose": "Operatives Command Center mit Fokus, Checks und Quellenlinks bauen.",
        "ui_section": "Watchlist / Pipeline",
        "artifacts": [
            "data/matchday_command_center.json",
            "data/matchday_command_state.json",
            "exports/matchday_command_center.md",
        ],
        "run_args": ["matchday-command"],
    },
    {
        "command": "lint",
        "group": "Qualitaet",
        "purpose": "Daten- und Quellkonsistenz pruefen.",
        "ui_section": "Pipeline",
        "artifacts": [],
        "live_status": "lint",
        "run_args": ["lint"],
    },
    {
        "command": "refresh-player-pool",
        "group": "Bonus",
        "purpose": "Topscorer-Team-Spielerpool aus CC0-Daten bauen.",
        "ui_section": "Bonus / Pipeline",
        "artifacts": ["data/player_pool.json"],
        "run_args": ["refresh-player-pool"],
    },
    {
        "command": "watch",
        "group": "Automation",
        "purpose": "Regelmaessige Refresh-Zyklen lokal ausfuehren.",
        "ui_section": "Statusleiste / Watchlist / Pipeline",
        "artifacts": ["data/watch_state.json"],
        "run_args": ["watch", "--iterations", "1", "--sleep-cap", "0"],
        "run_label": "1 Zyklus",
    },
    {
        "command": "update-all",
        "group": "Automation",
        "purpose": "Alle aktuellen Daten, Signale, Modelle und Exporte sequenziell aktualisieren.",
        "ui_section": "Pipeline / alle Tabs",
        "artifacts": ["data/update_all_status.json", "data/dashboard.json", "exports/final_tips.csv"],
        "run_args": ["update-all"],
        "run_label": "Alles updaten",
    },
    {
        "command": "serve-dashboard",
        "group": "Dashboard",
        "purpose": "Lokalen Dashboard-Server mit UI-Command-Runner starten.",
        "ui_section": "Pipeline",
        "artifacts": ["data/dashboard.json"],
        "runnable": False,
        "disabled_reason": "Dieser Server muss im Terminal laufen, bevor UI-Kommandos gestartet werden koennen.",
    },
]

# Pool-Analytik-Karten nur anbieten, wenn die Module vorhanden sind. Sie werten
# die Tipps der Mitspieler aus und fehlen in der oeffentlichen Verteilung.
# Eigener find_spec statt Import aus update_all: update_all importiert dieses
# Modul, ein Rueckimport waere zirkulaer.
POOL_ANALYTICS_AVAILABLE = importlib.util.find_spec("wm_tipps.deficit_policy") is not None
if POOL_ANALYTICS_AVAILABLE:
    CLI_UI_COMMANDS.extend(
        [
        {
            "command": "risk-dial",
            "group": "Backtest",
            "purpose": "Risk-Dial (Chase vs Protect): EP-Preis + Varianz je kappa, P(Ueberholen)-Grid (Rueckstand x Restspiele) + Live-Counterfactual gegen echte Crowd. Wann lohnt Aggression fuer RANG (nicht Punkte)?",
            "ui_section": "Quoten & Maerkte / Pipeline",
            "artifacts": ["data/risk_dial.json", "exports/risk_dial.md"],
            "run_args": ["risk-dial"],
        },
        {
            "command": "rival-profiles",
            "group": "Backtest",
            "purpose": "Per-Spieler Tipp-Profile aus manual_pool_tips: Remis-Rate, Aggressivitaet, Modell-Aehnlichkeit, Punkte je Rivale + Korr(Aggressivitaet, Punkte). Zahlt sich Aggression im echten Pool aus?",
            "ui_section": "Quoten & Maerkte / Pipeline",
            "artifacts": ["data/rival_profiles.json", "exports/rival_profiles.md"],
            "run_args": ["rival-profiles"],
        },
        {
            "command": "deficit-policy",
            "group": "Backtest",
            "purpose": "Deficit-Policy (Chase vs Protect je Rueckstand): feld-relative Tipp-Empfehlung je Spiel/Runde -- vorn=Cover, weit hinten+spaet=dekorrelieren, sonst EP-Max. Aus der Platz-1-Sim (T-0100).",
            "ui_section": "Quoten & Maerkte / Pipeline",
            "artifacts": ["data/deficit_policy.json", "exports/deficit_policy.md"],
            "run_args": ["deficit-policy"],
        },
        ]
    )


def chronology_key(row: dict[str, Any]) -> tuple[str, int, str]:
    fixture = row.get("fixture", row)
    match_number = fixture.get("match_number", row.get("match_number", 9999))
    try:
        match_number_value = int(match_number)
    except (TypeError, ValueError):
        match_number_value = 9999
    return (
        str(fixture.get("kickoff_utc") or row.get("kickoff_utc") or ""),
        match_number_value,
        str(row.get("match_id") or fixture.get("match_id") or ""),
    )


def build_dashboard_payload() -> dict[str, Any]:
    fixtures = load_fixture_payload()
    predictions = read_json(DATA_DIR / "predictions.json", {"predictions": [], "bonus": {}})
    news = read_json(DATA_DIR / "news_items.json", {"items": []})
    markets = read_json(DATA_DIR / "market_signals.json", {"odds": [], "markets": []})
    exact_scores = load_exact_score_payload()
    backtest_report = read_json(DATA_DIR / "backtest_report.json", {})
    context_ablation = read_json(DATA_DIR / "context_ablation.json", {})
    blend_sweep = read_json(DATA_DIR / "blend_sweep.json", {})
    role_ab = read_json(DATA_DIR / "role_ab_report.json", {})
    news_audit = read_json(DATA_DIR / "news_audit.json", {})
    live_eval = read_json(DATA_DIR / "live_eval.json", {})
    strategy_ab = read_json(DATA_DIR / "strategy_ab.json", {})
    risk_dial = read_json(DATA_DIR / "risk_dial.json", {})
    favorite_host_calibration = read_json(DATA_DIR / "favorite_host_calibration.json", {})
    rival_profiles = read_json(DATA_DIR / "rival_profiles.json", {})
    deficit_policy = read_json(DATA_DIR / "deficit_policy.json", {})
    calibration_fit = read_json(DATA_DIR / "calibration_fit.json", {})
    historical_market_lines = historical_market_payload_summary(load_historical_market_payload())
    matchday_command = read_json(DATA_DIR / "matchday_command_center.json", {})
    matchday_dry_run = read_json(DATA_DIR / "matchday_dry_run.json", {})
    source_watch = read_json(DATA_DIR / "source_watch_status.json", {"sources": []})
    context = read_json(DATA_DIR / "context.json", {"fixtures": {}})
    history = read_json(DATA_DIR / "prediction_history.json", {"events": []})
    watch_state = read_json(DATA_DIR / "watch_state.json", {})
    command_runs = read_json(DATA_DIR / "ui_command_runs.json", {"last_runs": {}, "history": []})
    update_all_status = read_json(DATA_DIR / "update_all_status.json", {})
    prediction_rows = predictions.get("predictions", [])
    watchlist = build_watchlist(prediction_rows)
    history_events = enrich_history_events(
        history.get("events", []),
        prediction_rows,
        predictions.get("bonus") or {},
    )
    # Typvertrag des Bonus-Blocks halten: die Kategorien sind IMMER eine Liste
    # bzw. ein Mapping, auch wenn noch keine Predictions gebaut wurden (frischer
    # Clone, serve-dashboard vor build-predictions). Vorher fehlten die Keys
    # dann ganz, und Konsumenten sahen `None` statt einer leeren Collection.
    # Fuer assets/app.js aendert das nichts: dort steht `bonus.world_champion
    # || []` bzw. `|| {}`, was fehlenden Key und leere Collection identisch
    # behandelt -- beide Renderer zeigen unveraendert "Keine Daten.".
    bonus_payload = dict(predictions.get("bonus") or {})
    bonus_payload.setdefault("world_champion", [])
    bonus_payload.setdefault("group_winners", {})
    rounds = prediction_rounds(predictions)
    final_rows = final_tips(prediction_rows)
    final_rows_by_round = final_tips_by_round(prediction_rows, rounds)
    all_final_rows = all_round_final_tips(prediction_rows, rounds)
    display_watch_state = current_watch_state(
        watch_state,
        fixtures=fixtures,
        predictions=prediction_rows,
        news=news,
        markets=markets,
        watchlist=watchlist,
        final_rows=all_final_rows or final_rows,
    )
    from .live_calibration import signal_calibration, totals_adjustment
    from .lineup_lock import lineup_lock_status
    from .news_review import build_review_queue, load_decisions
    from .odds_history import load_snapshots, summarize_movements
    from .role_experiment import load_manual_results

    fixture_rows = fixtures.get("fixtures", [])
    live_results = {
        fx["match_id"]: {"actual": fx.get("result")}
        for fx in fixture_rows
        if fx.get("status") == "played" and fx.get("result")
    }
    live_results.update(load_manual_results())
    manual_news = read_json(DATA_DIR / "manual_news.json", [])
    odds_history_summary = summarize_movements(load_snapshots())
    news_review_summary = build_review_queue(news.get("items", []), manual_news, load_decisions())
    lineup_lock_summary = lineup_lock_status(prediction_rows, fixture_rows, news.get("items", []))
    signal_breaker_summary = signal_calibration(prediction_rows, live_results)
    totals_adjust_summary = totals_adjustment(prediction_rows, live_results)
    odds_freshness = match_odds_freshness(
        fixtures.get("fixtures", []),
        markets.get("odds", []),
        source=BWIN_SOURCE,
    )
    odds_now = datetime.now(timezone.utc)
    odds_status_by_match = {}
    for prediction in prediction_rows:
        status = odds_status_for_prediction(prediction, now=odds_now)
        if status is not None:
            odds_status_by_match[prediction["match_id"]] = status
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "fixtures_updated_at": fixtures.get("updated_at"),
        "knockout_status": fixtures.get("knockout_status") or {},
        "prediction_updated_at": predictions.get("updated_at"),
        "news_updated_at": news.get("updated_at"),
        "market_updated_at": markets.get("updated_at"),
        "fixture_count": len(fixtures.get("fixtures", [])),
        "predictions": prediction_rows,
        "default_round_id": predictions.get("default_round_id") or DEFAULT_ROUND_ID,
        "rounds": rounds,
        "bonus": bonus_payload,
        "lineup_roles": predictions.get("lineup_roles") or {},
        "news": news.get("items", []),
        "markets": markets,
        "exact_score_odds": build_exact_score_comparison(prediction_rows, exact_scores),
        "backtest_report": backtest_report if isinstance(backtest_report, dict) else {},
        "context_ablation": context_ablation if isinstance(context_ablation, dict) else {},
        "blend_sweep": blend_sweep if isinstance(blend_sweep, dict) else {},
        "role_ab": role_ab if isinstance(role_ab, dict) else {},
        "news_audit": news_audit if isinstance(news_audit, dict) else {},
        "live_eval": live_eval if isinstance(live_eval, dict) else {},
        "strategy_ab": strategy_ab if isinstance(strategy_ab, dict) else {},
        # Pool-Analytik-Keys nur setzen, wenn die Module vorhanden sind. Fehlen
        # sie, blendet das Frontend die zugehoerigen Panels ganz aus, statt
        # eine Anleitung fuer ein nicht existierendes Kommando anzuzeigen.
        **(
            {
                "risk_dial": risk_dial if isinstance(risk_dial, dict) else {},
                "rival_profiles": rival_profiles if isinstance(rival_profiles, dict) else {},
                "deficit_policy": deficit_policy if isinstance(deficit_policy, dict) else {},
            }
            if POOL_ANALYTICS_AVAILABLE
            else {}
        ),
        "favorite_host_calibration": favorite_host_calibration if isinstance(favorite_host_calibration, dict) else {},
        "calibration_fit": calibration_fit if isinstance(calibration_fit, dict) else {},
        "historical_market_lines": historical_market_lines,
        "matchday_command": compact_matchday_command(matchday_command),
        "matchday_dry_run": matchday_dry_run if isinstance(matchday_dry_run, dict) else {},
        "source_watch": source_watch,
        "odds_coverage": odds_coverage(fixtures.get("fixtures", []), markets.get("odds", [])),
        "odds_freshness": odds_freshness,
        "odds_status_by_match": odds_status_by_match,
        "team_intel": team_intel_report(fixtures),
        "prediction_history": history_events,
        "prediction_history_updated_at": history.get("updated_at"),
        "context": context,
        "watch_state": display_watch_state,
        "update_all_status": update_all_status if isinstance(update_all_status, dict) else {},
        "ui_command_runs": command_runs if isinstance(command_runs, dict) else {"last_runs": {}, "history": []},
        "watchlist": watchlist,
        "final_tips": final_rows,
        "final_tips_by_round": final_rows_by_round,
        "all_final_tips": all_final_rows,
        "data_quality": {"news": news.get("data_quality", [])},
        "odds_history": odds_history_summary,
        "news_review": news_review_summary,
        "lineup_lock": lineup_lock_summary,
        "signal_breaker": signal_breaker_summary,
        "totals_adjust": totals_adjust_summary,
    }
    payload["cli_ui_coverage"] = build_cli_ui_coverage(payload)
    write_json(DATA_DIR / "dashboard.json", payload)
    return payload


def build_cli_ui_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    lint_result = run_lint()
    rows = [cli_command_row(spec, payload, lint_result) for spec in CLI_UI_COMMANDS]
    status_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        group_counts[row["group"]] = group_counts.get(row["group"], 0) + 1
    return {
        "summary": {
            "commands_total": len(rows),
            "ok": status_counts.get("ok", 0),
            "missing": status_counts.get("missing", 0),
            "watch": status_counts.get("watch", 0),
            "groups": group_counts,
            "lint_issues": lint_result.get("count", 0),
            "lint_info": len(lint_result.get("info") or []),
        },
        "commands": rows,
    }


def cli_command_row(
    spec: dict[str, Any],
    payload: dict[str, Any],
    lint_result: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [artifact_info(path) for path in spec.get("artifacts", [])]
    missing = [artifact for artifact in artifacts if not artifact["exists"]]
    status = "ok"
    status_detail = "Alle erwarteten Artefakte sind vorhanden."
    if spec.get("live_status") == "lint":
        status = "ok" if lint_result.get("count", 0) == 0 else "watch"
        status_detail = (
            f"{lint_result.get('count', 0)} Issues, "
            f"{len(lint_result.get('info') or [])} Info-Hinweise."
        )
    elif missing:
        status = "missing"
        status_detail = "Fehlende Artefakte: " + ", ".join(artifact["path"] for artifact in missing)
    return {
        "command": spec["command"],
        "group": spec["group"],
        "purpose": spec["purpose"],
        "ui_section": spec["ui_section"],
        "status": status,
        "status_detail": status_detail,
        "signal": cli_command_signal(spec["command"], payload, lint_result),
        "runnable": spec.get("runnable", True),
        "run_args": spec.get("run_args") or [spec["command"]],
        "run_label": spec.get("run_label", "Ausfuehren"),
        "disabled_reason": spec.get("disabled_reason"),
        "artifacts": artifacts,
        "updated_at": newest_artifact_update(artifacts),
    }


def artifact_info(relative_path: str) -> dict[str, Any]:
    path = PROJECT_ROOT / relative_path
    exists = path.exists()
    info: dict[str, Any] = {
        "path": relative_path,
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "updated_at": None,
    }
    if exists:
        info["updated_at"] = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return info


def newest_artifact_update(artifacts: list[dict[str, Any]]) -> str | None:
    updates = [artifact.get("updated_at") for artifact in artifacts if artifact.get("updated_at")]
    return max(updates) if updates else None


def cli_command_signal(
    command: str,
    payload: dict[str, Any],
    lint_result: dict[str, Any],
) -> str:
    if command == "refresh-fixtures":
        return f"{payload.get('fixture_count', 0)} Spiele"
    if command == "refresh-context":
        fixtures = (payload.get("context") or {}).get("fixtures") or {}
        return f"{len(fixtures)} Kontext-Zeilen"
    if command == "refresh-news":
        return f"{len(payload.get('news') or [])} News"
    if command in {"refresh-odds", "refresh-markets"}:
        markets = payload.get("markets") or {}
        return f"{len(markets.get('odds') or [])} Quoten, {len(markets.get('markets') or [])} Futures"
    if command == "refresh-historical-markets":
        summary = (payload.get("historical_market_lines") or {}).get("coverage") or {}
        return f"{summary.get('matches', 0)} Spiele, O/U {summary.get('over_under', 0)}, BTTS {summary.get('btts', 0)}"
    if command == "odds-report":
        summary = (payload.get("odds_coverage") or {}).get("summary") or {}
        return f"{summary.get('with_consensus', 0)}/{summary.get('total', 0)} Konsens"
    if command == "odds-history":
        summary = payload.get("odds_history") or {}
        return f"{summary.get('snapshot_count', 0)} Snapshots, {summary.get('moved_count', 0)} bewegt"
    if command == "news-review":
        queue = payload.get("news_review") or {}
        return f"{queue.get('count', 0)} Kandidaten, {queue.get('promote_suggested', 0)} Promote-Vorschlag"
    if command == "lineup-lock":
        lock = payload.get("lineup_lock") or {}
        return f"{lock.get('lockable', 0)}/{lock.get('in_window', 0)} lockable im Fenster"
    if command == "refresh-lineups":
        data = read_json(PROJECT_ROOT / "data" / "manual_lineups.json", {})
        teams = (data.get("lineups") or {}) if isinstance(data, dict) else {}
        return f"{len(teams)} Teams mit bestaetigter XI (ESPN)"
    if command == "signal-breaker":
        breaker = payload.get("signal_breaker") or {}
        return f"{breaker.get('played_with_result', 0)} Spiele, min {breaker.get('min_firings', 10)} Feuerungen"
    if command == "totals-adjust":
        totals = payload.get("totals_adjust") or {}
        return f"{totals.get('matches', 0)}/{totals.get('min_matches', 15)} Spiele, {totals.get('status', 'insufficient_data')}"
    if command in {"exact-score-report", "refresh-bwin-exact-scores"}:
        summary = (payload.get("exact_score_odds") or {}).get("summary") or {}
        return f"{summary.get('imported_matches', 0)} importiert, {summary.get('model_market_favorite_disagreements', 0)} Abweichungen"
    if command == "refresh-bwin-match-odds":
        freshness = payload.get("odds_freshness") or {}
        if freshness.get("future_matches"):
            return (
                f"Bwin frisch {freshness.get('fresh_matches', 0)}/"
                f"{freshness.get('future_matches', 0)} kommende Spiele"
            )
        odds = (payload.get("markets") or {}).get("odds") or []
        bwin = sum(1 for row in odds if row.get("source") == "bwin_world_cup_2026")
        return f"{bwin} Bwin-1X2-Zeilen in manual_odds.csv"
    if command == "team-intel-report":
        summary = (payload.get("team_intel") or {}).get("summary") or {}
        return f"{summary.get('source_count', 0)} Quellen, {summary.get('active_sources', 0)} aktiv"
    if command == "team-intel-checklist":
        checklist = (payload.get("team_intel") or {}).get("matchday_checklist") or []
        return f"{len(checklist)} Checklisten-Zeilen"
    if command == "refresh-team-intel-sources":
        summary = (payload.get("team_intel") or {}).get("summary") or {}
        return f"{summary.get('machine_reachable_sources', 0)} machine-reachable"
    if command == "source-watch":
        sources = (payload.get("source_watch") or {}).get("sources") or []
        return f"{len(sources)} beobachtete Quellen"
    if command == "build-predictions":
        return f"{len(payload.get('predictions') or [])} Predictions"
    if command == "build-strengths":
        return f"{payload.get('fixture_count', 0)} Fixture-Teams abgedeckt"
    if command == "build-dashboard":
        return f"{len(payload)} Payload-Bloecke"
    if command == "export-tips":
        return f"{len(payload.get('final_tips') or [])} finale Tipps"
    if command == "backtest":
        return "sample/2018/2022 Artefakte"
    if command == "backtest-report":
        verdict = ((payload.get("backtest_report") or {}).get("verdict") or {}).get("status")
        return verdict or "kein Verdict"
    if command == "context-ablation":
        effects = (payload.get("context_ablation") or {}).get("effects") or []
        total_changes = sum(item.get("tip_changes_total", 0) for item in effects)
        return f"{len(effects)} Effekte, {total_changes} Tippwechsel"
    if command == "lineup-roles":
        summary = payload.get("lineup_roles") or {}
        return (
            f"{summary.get('teams_with_lineup', 0)} Teams mit XI, "
            f"{summary.get('players_updated', 0)} Rollen ({summary.get('starters', 0)} starter, "
            f"{summary.get('rotation', 0)} rotation)"
        )
    if command == "blend-sweep":
        meta = (payload.get("blend_sweep") or {}).get("_meta") or {}
        return (
            f"live {meta.get('current_weight')}, best {meta.get('best_weight')} "
            f"(+{meta.get('best_minus_current_ppm')}/Spiel)"
        )
    if command == "role-ab":
        meta = (payload.get("role_ab") or {}).get("_meta") or {}
        return (
            f"{meta.get('settled_slots', 0)} gewertet, {meta.get('differing_tips', 0)} abweichend, "
            f"netto {meta.get('net_delta', 0):+d}"
        )
    if command == "news-audit":
        meta = (payload.get("news_audit") or {}).get("_meta") or {}
        return (
            f"{meta.get('teams_with_effect', 0)} Teams betroffen, "
            f"{meta.get('risk_items', 0)} Multi-Team, {meta.get('flagged_team_items', 0)} markiert, "
            f"{meta.get('stale_impact_items', 0)} stale"
        )
    if command == "calibrate-fit":
        meta = (payload.get("calibration_fit") or {}).get("_meta") or {}
        return (
            f"T* {meta.get('best_temperature', '-')} ({meta.get('within_class_sharpness', '-')}), "
            f"rho* {meta.get('best_rho', '-')}, {meta.get('matches', 0)} Spiele"
        )
    if command == "strategy-ab":
        meta = (payload.get("strategy_ab") or {}).get("_meta") or {}
        return f"bestes kappa {meta.get('backtest_best_kappa')} -- {meta.get('verdict') or '-'}"
    if command == "risk-dial":
        meta = (payload.get("risk_dial") or {}).get("_meta") or {}
        return meta.get("verdict") or "-"
    if command == "favorite-calibration":
        meta = (payload.get("favorite_host_calibration") or {}).get("_meta") or {}
        return meta.get("verdict") or "-"
    if command == "rival-profiles":
        meta = (payload.get("rival_profiles") or {}).get("_meta") or {}
        return meta.get("verdict") or "-"
    if command == "deficit-policy":
        meta = (payload.get("deficit_policy") or {}).get("_meta") or {}
        return meta.get("verdict") or "-"
    if command == "eval-live":
        live = payload.get("live_eval") or {}
        meta = live.get("_meta") or {}
        default_round = (live.get("rounds") or {}).get(DEFAULT_ROUND_ID) or {}
        ppm = default_round.get("points_per_match")
        theta = (live.get("totals") or {}).get("inflation_theta")
        return (
            f"{meta.get('matches_evaluated', 0)} Spiele, "
            f"{ppm if ppm is not None else '-'} Pkt/Spiel, "
            f"beste Quelle {meta.get('best_calibrated_source') or '-'}, "
            f"theta {theta if theta is not None else '-'}, "
            f"{meta.get('results_pending', 0)} offen"
        )
    if command == "matchday-dry-run":
        return (payload.get("matchday_dry_run") or {}).get("status") or "kein Probelauf"
    if command == "matchday-command":
        summary = (payload.get("matchday_command") or {}).get("summary") or {}
        return f"{summary.get('focus_items', 0)} Fokus, {summary.get('open_due', 0)} faellig"
    if command == "lint":
        return f"{lint_result.get('count', 0)} Issues, {len(lint_result.get('info') or [])} Info"
    if command == "refresh-player-pool":
        pool = read_json(DATA_DIR / "player_pool.json", {"players": {}})
        return f"{len((pool.get('players') or {}))} Teams"
    if command == "watch":
        watch_state = payload.get("watch_state") or {}
        return f"{watch_state.get('watchlist', 0)} Watchlist, {watch_state.get('exported_tips', 0)} Tipps"
    if command == "update-all":
        status = payload.get("update_all_status") or {}
        if not status:
            return "noch nicht gelaufen"
        base = f"{status.get('steps_ok', 0)}/{status.get('steps_total', 0)} Schritte"
        quality = status.get("quality_status")
        if quality == "failed":
            return f"FEHLER Quoten-Quality ({base})"
        if quality == "warning":
            return f"WARNUNG Quoten-Quality ({base})"
        return base
    return ""


def compact_matchday_command(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "_meta": payload.get("_meta") or {},
        "summary": payload.get("summary") or {},
        "today_items": payload.get("today_items") or [],
        "next_items": payload.get("next_items") or [],
    }


def current_watch_state(
    raw_state: dict[str, Any],
    *,
    fixtures: dict[str, Any],
    predictions: list[dict[str, Any]],
    news: dict[str, Any],
    markets: dict[str, Any],
    watchlist: list[dict[str, Any]],
    final_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    state = dict(raw_state) if isinstance(raw_state, dict) else {}
    state.update(
        {
            "fixtures": len(fixtures.get("fixtures", [])),
            "predictions": len(predictions),
            "news_items": len(news.get("items", [])),
            "market_items": len(markets.get("odds", [])) + len(markets.get("markets", [])),
            "watchlist": len(watchlist),
            "exported_tips": len(final_rows),
        }
    )
    return state


def build_watchlist(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for prediction in predictions:
        # Die Watchlist ist eine Handlungsliste VOR dem Anpfiff. Fuer ein
        # gespieltes Spiel ist nichts mehr zu tun -- ohne diesen Guard
        # meldete sie zuletzt 104 von 104 Spielen, davon 60x "warte auf
        # Lineup" fuer laengst gelaufene Partien (T-0169). Die
        # Nachbarfunktion odds_status_for_prediction (oben) macht es
        # seit jeher richtig; hier fehlte es als einziger Stelle.
        if prediction["fixture"].get("status") == "played":
            continue
        reasons = []
        details = []
        hours_left = hours_until_kickoff(prediction["fixture"])
        if prediction.get("stability") != "stabil":
            reasons.append(prediction.get("stability"))
            details.append(
                {
                    "type": "status",
                    "label": prediction.get("stability"),
                    "detail": "Stabilitaetsstatus des Modells ist nicht stabil.",
                }
            )
        relevant_news = [
            item
            for item in prediction.get("news", [])
            if item.get("freshness") != "stale"
            and is_model_relevant_news(item)
            and severity_rank(item.get("severity", "noise")) >= 2
        ]
        relevant_news = dedupe_model_relevant_news(
            [prediction["fixture"].get("home_team"), prediction["fixture"].get("away_team")],
            relevant_news,
        )
        if any(item.get("severity") == "critical" for item in relevant_news):
            reasons.append("kritische News")
        elif relevant_news:
            reasons.append("wichtige News")
        for item in relevant_news[:3]:
            details.append(news_watch_detail(prediction["fixture"], item))
        heat = (prediction.get("context") or {}).get("heat_stress") or {}
        if heat.get("risk") in {"moderate", "high"}:
            reasons.append("Heat-Stress")
            details.append(heat_watch_detail(heat))
        if not prediction.get("odds") and hours_left is not None and hours_left <= 168:
            reasons.append("keine Quoten")
            details.append(
                {
                    "type": "odds",
                    "label": "keine Quoten",
                    "detail": "Es sind weniger als 7 Tage bis Anpfiff und keine Quoten importiert.",
                }
            )
        if reasons:
            fixture = prediction["fixture"]
            rows.append(
                {
                    "group": fixture.get("group"),
                    "match_id": prediction["match_id"],
                    "match_number": fixture.get("match_number"),
                    "kickoff_utc": fixture.get("kickoff_utc"),
                    "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                    "tip": prediction.get("recommended_tip", {}).get("tip"),
                    "expected_points": prediction.get("recommended_tip", {}).get("expected_points"),
                    "round_tips": prediction.get("round_tips") or {},
                    "stability": prediction.get("stability"),
                    "xg": prediction.get("xg"),
                    "reasons": sorted(set(reason for reason in reasons if reason)),
                    "details": details,
                }
            )
    return sorted(rows, key=chronology_key)


def heat_watch_detail(heat: dict[str, Any]) -> dict[str, Any]:
    home_delta = numeric_value(heat.get("home_xg_delta"))
    away_delta = numeric_value(heat.get("away_xg_delta"))
    return {
        "type": "heat",
        "label": heat.get("risk"),
        "detail": (
            f"WBGT effektiv {heat.get('effective_wbgt_c', 'n/a')}C "
            f"(ambient {heat.get('estimated_wbgt_c', 'n/a')}C); "
            f"xG-Delta Heim {home_delta:+.3f}, "
            f"Auswaerts {away_delta:+.3f}."
        ),
        "source": heat.get("source"),
    }


def numeric_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def news_watch_detail(fixture: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "news",
        "label": item.get("severity"),
        "title": item.get("title"),
        "source": item.get("source"),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "freshness": item.get("freshness"),
        "categories": item.get("categories", []),
        "relevance": item.get("relevance"),
        "effect": news_model_effect_label(fixture, item),
    }


def news_model_effect_label(fixture: dict[str, Any], item: dict[str, Any]) -> str:
    categories = set(item.get("categories") or [])
    if not (categories & XG_IMPACT_CATEGORIES):
        return "Watchlist-Signal ohne direkte xG-Aenderung."
    severity = item.get("severity")
    if severity == "critical":
        attack_delta = -0.18
        defense_delta = 0.10
    elif severity == "important":
        attack_delta = -0.07
        defense_delta = 0.04
    else:
        return "Keine direkte xG-Aenderung."
    teams = set(item.get("teams") or [])
    parts = []
    home = fixture.get("home_team")
    away = fixture.get("away_team")
    if home in teams:
        parts.append(
            f"{home} xG {attack_delta:+.2f}; {away} xG {defense_delta * 0.45:+.2f}"
        )
    if away in teams:
        parts.append(
            f"{away} xG {attack_delta:+.2f}; {home} xG {defense_delta * 0.45:+.2f}"
        )
    return "; ".join(parts) if parts else "Teambezug unklar, keine xG-Aenderung."


def hours_until_kickoff(fixture: dict[str, Any]) -> float | None:
    kickoff_text = fixture.get("kickoff_utc")
    if not kickoff_text:
        return None
    try:
        kickoff = datetime.fromisoformat(str(kickoff_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (kickoff - datetime.now(timezone.utc)).total_seconds() / 3600


def prediction_rounds(prediction_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw_rounds = (prediction_payload or {}).get("rounds")
    rounds = raw_rounds if isinstance(raw_rounds, list) else round_rules_payload()
    by_id = {
        str(row.get("id")): row
        for row in rounds
        if isinstance(row, dict) and row.get("id")
    }
    for row in round_rules_payload():
        by_id.setdefault(str(row["id"]), row)
    ordered = [by_id[round_id] for round_id in ROUND_ORDER if round_id in by_id]
    ordered.extend(row for round_id, row in sorted(by_id.items()) if round_id not in ROUND_ORDER)
    return ordered


def _round_rule_summary(round_row: dict[str, Any]) -> str:
    group = round_row.get("group") or {}
    knockout = round_row.get("knockout") or {}
    stage_points = round_row.get("stage_points") or {}

    def _triple(points: dict[str, Any]) -> str:
        return f"{points.get('tendency')}-{points.get('difference')}-{points.get('exact')}"

    late_ko = stage_points.get("round_of_16") if isinstance(stage_points, dict) else None
    if isinstance(late_ko, dict) and _triple(late_ko) != _triple(knockout):
        return (
            f"Vorrunde {_triple(group)}, 16tel {_triple(knockout)}, "
            f"ab 8tel {_triple(late_ko)}"
        )
    return f"Vorrunde {_triple(group)}, KO {_triple(knockout)}"


def _round_tip(prediction: dict[str, Any], round_id: str) -> dict[str, Any]:
    round_tips = prediction.get("round_tips") or {}
    if isinstance(round_tips, dict) and isinstance(round_tips.get(round_id), dict):
        return round_tips[round_id]
    if round_id == DEFAULT_ROUND_ID:
        tip = prediction.get("recommended_tip") or {}
        return tip if isinstance(tip, dict) else {}
    return {}


def final_tips_for_round(
    predictions: list[dict[str, Any]],
    *,
    round_id: str = DEFAULT_ROUND_ID,
    round_display_name: str | None = None,
    rule_summary: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for prediction in sorted(predictions, key=chronology_key):
        fixture = prediction["fixture"]
        if not is_stage_tippable(fixture.get("stage", "group"), round_id):
            continue
        tip = _round_tip(prediction, round_id)
        if not tip:
            continue
        rows.append(
            {
                "round_id": round_id,
                "round_name": round_display_name or round_name(round_id),
                "rule_summary": rule_summary,
                "group": fixture.get("group"),
                "match_id": prediction["match_id"],
                "match_number": fixture.get("match_number"),
                "kickoff_utc": fixture.get("kickoff_utc"),
                "stage": fixture.get("stage"),
                "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                "tip": tip.get("tip"),
                "expected_points": tip.get("expected_points"),
                "status": prediction.get("stability"),
            }
        )
    return rows


def final_tips(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    default_round = next(
        (row for row in prediction_rounds() if row.get("id") == DEFAULT_ROUND_ID),
        {},
    )
    return final_tips_for_round(
        predictions,
        round_id=DEFAULT_ROUND_ID,
        round_display_name=str(default_round.get("name") or round_name(DEFAULT_ROUND_ID)),
        rule_summary=_round_rule_summary(default_round) if default_round else None,
    )


def final_tips_by_round(
    predictions: list[dict[str, Any]],
    rounds: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for round_row in rounds or prediction_rounds():
        round_id = str(round_row.get("id") or DEFAULT_ROUND_ID)
        result[round_id] = final_tips_for_round(
            predictions,
            round_id=round_id,
            round_display_name=str(round_row.get("name") or round_name(round_id)),
            rule_summary=_round_rule_summary(round_row),
        )
    return result


def all_round_final_tips(
    predictions: list[dict[str, Any]],
    rounds: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    round_rows = rounds or prediction_rounds()
    by_round = final_tips_by_round(predictions, round_rows)
    round_index = {str(row.get("id")): index for index, row in enumerate(round_rows)}
    for round_id in [str(row.get("id")) for row in round_rows]:
        rows.extend(by_round.get(round_id, []))
    return sorted(
        rows,
        key=lambda row: (
            *chronology_key(row),
            round_index.get(str(row.get("round_id")), 999),
        ),
    )


def _safe_round_filename(round_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", round_id.lower()).strip("-") or "runde"


def export_tips() -> dict[str, Any]:
    dashboard = build_dashboard_payload()
    final_rows = dashboard["final_tips"]
    all_final_rows = dashboard.get("all_final_tips") or final_rows
    by_round = dashboard.get("final_tips_by_round") or {DEFAULT_ROUND_ID: final_rows}
    watch_rows = dashboard["watchlist"]
    write_csv_dicts(
        EXPORTS_DIR / "final_tips.csv",
        all_final_rows,
        [
            "round_name",
            "round_id",
            "match_number",
            "match_id",
            "kickoff_utc",
            "group",
            "stage",
            "match",
            "tip",
            "expected_points",
            "status",
        ],
    )
    for round_id, rows in by_round.items():
        write_csv_dicts(
            EXPORTS_DIR / f"final_tips_{_safe_round_filename(str(round_id))}.csv",
            rows,
            [
                "round_name",
                "round_id",
                "match_number",
                "match_id",
                "kickoff_utc",
                "group",
                "stage",
                "match",
                "tip",
                "expected_points",
                "status",
            ],
        )
    write_csv_dicts(
        EXPORTS_DIR / "watchlist.csv",
        watch_rows,
        ["match_number", "match_id", "kickoff_utc", "group", "match", "tip", "expected_points", "stability", "reasons", "details"],
    )
    md_lines = [
        "# Finale Kicktipp-Tipps",
        "",
        f"Stand: {dashboard['updated_at']}",
        "",
    ]
    rounds = dashboard.get("rounds") or []
    round_names = {str(row.get("id")): str(row.get("name") or row.get("id")) for row in rounds}
    round_summaries = {str(row.get("id")): _round_rule_summary(row) for row in rounds if isinstance(row, dict)}
    for round_id, rows in by_round.items():
        md_lines.extend(
            [
                f"## {round_names.get(str(round_id), str(round_id))}",
                "",
                f"Regeln: {round_summaries.get(str(round_id), rows[0].get('rule_summary') if rows else 'n/a')}",
                "",
                "| Runde | Nr | Stage | Anpfiff | Spiel | Tipp | Erwartete Punkte | Status |",
                "|---|---:|---|---|---|---:|---:|---|",
            ]
        )
        for row in rows:
            md_lines.append(
                f"| {row['round_id']} | {row['match_number']} | {row['stage']} | {row['kickoff_utc']} | {row['match']} | {row['tip']} | {row['expected_points']} | {row['status']} |"
            )
        md_lines.append("")
    md_lines.append("")
    md_lines.append("## Watchlist")
    md_lines.append("")
    if watch_rows:
        for row in watch_rows:
            md_lines.append(f"- {row['match']}: {', '.join(row['reasons'])}")
            for detail in row.get("details", [])[:3]:
                label = detail.get("title") or detail.get("detail") or detail.get("label")
                effect = detail.get("effect")
                suffix = f" ({effect})" if effect else ""
                md_lines.append(f"  - {label}{suffix}")
    else:
        md_lines.append("- Keine offenen Flags.")
    md_lines.append("")
    md_lines.append("## Tipp-History")
    md_lines.append("")
    history_rows = dashboard.get("prediction_history", [])[:20]
    if history_rows:
        for row in history_rows:
            md_lines.append(f"- {row.get('summary')}")
    else:
        md_lines.append("- Noch keine Tipp-Aenderungen protokolliert.")
    (EXPORTS_DIR / "final_tips.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return {"final_tips": all_final_rows, "default_final_tips": final_rows, "watchlist": watch_rows}
