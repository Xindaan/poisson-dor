"""Kommandozeilen-Einstieg: `python3 -m wm_tipps.cli <command>`.

Duenne Schicht -- jedes Subkommando delegiert an sein Fachmodul. Die
wichtigsten Einstiegspunkte:

  refresh-fixtures / refresh-odds / refresh-news   Daten holen
  build-predictions                                Tipps rechnen
  backtest                                         gegen historische Turniere pruefen
  update-all                                       komplette Pipeline
  serve-dashboard                                  lokales Dashboard
  watch                                            Dauerbetrieb mit Refresh-Kadenz

Kommandos zur Auswertung der Mitspieler-Tipps werden nur registriert, wenn
die zugehoerigen Module vorhanden sind (siehe POOL_ANALYTICS_AVAILABLE).
"""
from __future__ import annotations

import argparse
import json
import sys

from .backtest import build_backtest_report, run_backtest
from .bwin_exact_scores import import_bwin_exact_scores
from .lint import run_lint
from .player_pool import build_player_pool
from .context import refresh_context
from .dashboard import build_dashboard_payload, export_tips
from .dashboard_server import serve_dashboard
from .exact_scores import build_exact_score_comparison, load_exact_score_payload
from .fixtures import all_teams, load_fixture_payload, refresh_fixtures
from .historical_markets import (
    historical_market_payload_summary,
    refresh_checkbestodds_historical_markets,
)
from .io import read_json, write_json
from .matchday_command import build_matchday_command_center
from .matchday_dry_run import build_matchday_dry_run
from .model import build_predictions
from .news import refresh_news
from .odds import load_manual_odds, odds_coverage, refresh_market_data
from .paths import DATA_DIR, ensure_dirs
from .source_watch import refresh_source_watch
from .strength import build_team_strengths
from .team_intel import (
    export_matchday_checklist,
    parse_datetime,
    refresh_team_intel_sources,
    team_intel_report,
)
from .update_all import POOL_ANALYTICS_AVAILABLE, run_update_all
from .watcher import watch


def cmd_refresh_fixtures(args: argparse.Namespace) -> dict:
    return refresh_fixtures(live=not args.no_live)


def cmd_refresh_context(args: argparse.Namespace) -> dict:
    payload = load_fixture_payload()
    return refresh_context(payload.get("fixtures", []))


def cmd_refresh_news(args: argparse.Namespace) -> dict:
    teams = all_teams(load_fixture_payload())
    return refresh_news(teams, live=args.live, per_team_limit=args.limit)


def cmd_refresh_odds(args: argparse.Namespace) -> dict:
    payload = refresh_market_data()
    from .odds_history import capture_market_snapshots

    payload["odds_snapshots"] = capture_market_snapshots(
        payload.get("odds") or load_manual_odds()
    )
    return payload


def cmd_refresh_historical_markets(args: argparse.Namespace) -> dict:
    tournaments = [
        tournament.strip()
        for tournament in args.tournaments.split(",")
        if tournament.strip()
    ]
    payload = refresh_checkbestodds_historical_markets(
        tournaments=tournaments,
        limit=args.limit,
        timeout=args.timeout,
    )
    audit = payload.get("source_audit") or {}
    return {
        "_meta": payload.get("_meta") or {},
        "summary": historical_market_payload_summary(payload),
        "source_audit": {
            "decision": audit.get("decision") or {},
            "sources": [
                {
                    "id": source.get("id"),
                    "accepted": source.get("accepted"),
                    "status": source.get("status"),
                    "match_links": source.get("match_links"),
                    "imported_matches": source.get("imported_matches"),
                    "errors": source.get("errors"),
                }
                for source in audit.get("sources") or []
            ],
        },
    }


def cmd_odds_report(args: argparse.Namespace) -> dict:
    fixtures = load_fixture_payload()
    return odds_coverage(fixtures.get("fixtures", []), load_manual_odds())


def cmd_exact_score_report(args: argparse.Namespace) -> dict:
    predictions = build_predictions() if args.rebuild else read_prediction_rows()
    return build_exact_score_comparison(predictions, load_exact_score_payload())


def cmd_refresh_bwin_exact_scores(args: argparse.Namespace) -> dict:
    payload = import_bwin_exact_scores(
        include_existing=not args.missing_only,
        limit=args.limit,
    )
    from .odds_history import append_snapshots, record_from_exact_score

    payload["odds_snapshots"] = append_snapshots(
        [record_from_exact_score(item) for item in payload.get("items") or []]
    )
    return payload


def cmd_refresh_bwin_match_odds(args: argparse.Namespace) -> dict:
    from .bwin_match_odds import refresh_bwin_match_odds

    return refresh_bwin_match_odds(limit=args.limit)


def cmd_refresh_lineups(args: argparse.Namespace) -> dict:
    from .lineups import refresh_lineups

    return refresh_lineups(window_minutes=args.window, lookback_minutes=args.lookback)


def cmd_odds_history(args: argparse.Namespace) -> dict:
    from .odds_history import load_snapshots, summarize_movements

    summary = summarize_movements(load_snapshots())
    if getattr(args, "match", None):
        summary["movements"] = [
            m for m in summary["movements"] if m["match_id"] == args.match
        ]
    return summary


def cmd_news_review(args: argparse.Namespace) -> dict:
    from .news_review import apply_decision, build_review_queue, load_decisions

    news_items = read_json(DATA_DIR / "news_items.json", {"items": []}).get("items", [])
    if getattr(args, "promote", None):
        return apply_decision(args.promote, "promote", news_items)
    if getattr(args, "dismiss", None):
        return apply_decision(args.dismiss, "dismiss", news_items)
    manual = read_json(DATA_DIR / "manual_news.json", [])
    return build_review_queue(news_items, manual, load_decisions())


def _played_results() -> dict:
    from .role_experiment import load_manual_results

    fixtures = load_fixture_payload().get("fixtures", [])
    results = {
        fx["match_id"]: {"actual": fx.get("result")}
        for fx in fixtures
        if fx.get("status") == "played" and fx.get("result")
    }
    results.update(load_manual_results())
    return results


def cmd_lineup_lock(args: argparse.Namespace) -> dict:
    from .lineup_lock import lineup_lock_status

    fixtures = load_fixture_payload().get("fixtures", [])
    news_items = read_json(DATA_DIR / "news_items.json", {"items": []}).get("items", [])
    return lineup_lock_status(
        read_prediction_rows(), fixtures, news_items, window_minutes=args.window
    )


def cmd_signal_breaker(args: argparse.Namespace) -> dict:
    from .live_calibration import signal_calibration, signal_points_calibration

    rows = read_prediction_rows()
    results = _played_results()
    report = signal_calibration(rows, results)
    # T-0076: Punkte-Gate zusaetzlich zum Brier-Gate (Brier ist blind fuer
    # den realisierten Punkte-Schaden -- siehe Modul-Docstring).
    ablation = read_json(DATA_DIR / "context_ablation.json", {"effects": []})
    stages = {
        row.get("match_id"): (row.get("fixture") or {}).get("stage", "group") for row in rows
    }
    report["points_gate"] = signal_points_calibration(ablation, results, stages)
    return report


def cmd_totals_adjust(args: argparse.Namespace) -> dict:
    from .live_calibration import totals_adjustment

    return totals_adjustment(read_prediction_rows(), _played_results())


def read_prediction_rows() -> list[dict]:
    payload = read_json(DATA_DIR / "predictions.json", {"predictions": []})
    return payload.get("predictions", [])


def cmd_team_intel_report(args: argparse.Namespace) -> dict:
    return team_intel_report(load_fixture_payload())


def cmd_team_intel_checklist(args: argparse.Namespace) -> dict:
    return export_matchday_checklist(load_fixture_payload())


def cmd_refresh_team_intel_sources(args: argparse.Namespace) -> dict:
    statuses = None
    if args.statuses:
        statuses = {
            status.strip()
            for status in args.statuses.split(",")
            if status.strip()
        }
    ids = None
    if args.ids:
        ids = {
            source_id.strip()
            for source_id in args.ids.split(",")
            if source_id.strip()
        }
    return refresh_team_intel_sources(
        statuses=statuses,
        ids=ids,
        limit=args.limit,
        timeout_seconds=args.timeout,
        workers=args.workers,
    )


def cmd_source_watch(args: argparse.Namespace) -> dict:
    fixtures = load_fixture_payload()
    markets = refresh_market_data()
    return refresh_source_watch(
        fixtures.get("fixtures", []),
        market_payload=markets,
        probe_live=args.probe_live,
    )


def cmd_build_predictions(args: argparse.Namespace) -> dict:
    return build_predictions()


def cmd_build_strengths(args: argparse.Namespace) -> dict:
    return build_team_strengths()


def cmd_export_tips(args: argparse.Namespace) -> dict:
    return export_tips()


def cmd_build_dashboard(args: argparse.Namespace) -> dict:
    return build_dashboard_payload()


def cmd_context_ablation(args: argparse.Namespace) -> dict:
    from .ablation import build_context_ablation

    return build_context_ablation()


def cmd_blend_sweep(args: argparse.Namespace) -> dict:
    from .backtest import build_blend_weight_sweep

    return build_blend_weight_sweep()


def cmd_role_ab(args: argparse.Namespace) -> dict:
    # Forward-A/B: loggt treatment (role-aware) vs control (role-off) je
    # Spiel und settlet gegen data/manual_results.json (ab Anstoss).
    from .role_experiment import build_role_ab

    return build_role_ab()


def cmd_calibrate_fit(args: argparse.Namespace) -> dict:
    # Offline within-class Temperatur-Fit auf dem 7-Turnier-Backtest.
    # Read-only Diagnose (T-0073): ist das Modell innerhalb der Klasse zu
    # scharf/unscharf? Live-Anwendung folgt separat mit Backtest-Validierung.
    from .calibration_fit import build_calibration_fit

    return build_calibration_fit()


def cmd_strategy_ab(args: argparse.Namespace) -> dict:
    # Aggressivitaets-A/B (T-0082): kappa-Tor-Inflation vor EP-Max, Punkte +
    # Exakt-Treffer je kappa auf Backtest + Live. Read-only.
    from .tip_strategy_ab import build_strategy_ab

    return build_strategy_ab()


def cmd_favorite_calibration(args: argparse.Namespace) -> dict:
    # Favoriten-/Gastgeber-Kalibrierung (T-0084): ist das Modell auf Favoriten
    # under-confident? Deckt der +0.18-Host-Bonus den realen Heim-Effekt? Read-only.
    from .favorite_host_calibration import build_favorite_host_calibration

    return build_favorite_host_calibration()


# Pool-Analytik: nur definiert, wenn die Module vorhanden sind. Die MODULE sind
# public; die Tipprunden-DATEN, die sie lesen, sind es nicht -- fuer die eigene
# Runde legt man sie selbst an (Vorlagen: data/manual_*.example.json).
POOL_DATEI_HINWEISE = {
    "manual_pool_tips.json": "Tipps der Mitspieler je Runde und Spiel",
    "manual_standings.json": "beobachtete Zwischenstaende je Spieltag",
    "manual_bonus_tips.json": "Bonusfragen-Picks der Mitspieler",
}


def _pool_daten_pruefen(*dateien: str, kern: bool = True) -> bool:
    """Meldet fehlende Tipprunden-Daten verstaendlich statt sie zu verschweigen.

    Ohne diese Dateien laufen die Kommandos zwar durch (`read_json` liefert
    einen leeren Default), erzeugen aber ein leeres Artefakt -- fuer jemanden,
    der das Repo frisch geklont hat, sieht das nach einem Defekt aus.
    `kern=False` fuer Kommandos, deren Hauptteil auch ohne die Daten sinnvoll
    ist (Risk-Dial rechnet den Backtest-Teil ohne jede Crowd).
    """
    fehlend = [name for name in dateien if not (DATA_DIR / name).exists()]
    if not fehlend:
        return True
    print("", file=sys.stderr)
    print("Hinweis: Tipprunden-Daten fehlen.", file=sys.stderr)
    for name in fehlend:
        beispiel = name.replace(".json", ".example.json")
        vorhanden = " (Vorlage vorhanden)" if (DATA_DIR / beispiel).exists() else ""
        print(f"  fehlt : data/{name} -- {POOL_DATEI_HINWEISE.get(name, '')}", file=sys.stderr)
        print(f"  Schema: data/{beispiel}{vorhanden}", file=sys.stderr)
    # Den cp-Befehl fuer die ERSTE fehlende Datei zeigen, nicht pauschal fuer
    # pool_tips -- sonst nennt die Meldung eine andere Datei als die, die fehlt.
    erste = fehlend[0]
    print(
        "  Vorgehen: Vorlage kopieren und mit den Daten der eigenen "
        "Kicktipp-Runde fuellen, z.B.\n"
        f"            cp data/{erste.replace('.json', '.example.json')} data/{erste}",
        file=sys.stderr,
    )
    if kern:
        print(
            "  Bis dahin bleibt die Auswertung leer -- das ist kein Fehler.",
            file=sys.stderr,
        )
    else:
        print(
            "  Der Backtest-Teil wird trotzdem gerechnet; nur der Vergleich gegen "
            "das echte Feld entfaellt.",
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    return False


if POOL_ANALYTICS_AVAILABLE:

    def cmd_risk_dial(args: argparse.Namespace) -> dict:
        # Risk-Dial (T-0075): Chase vs Protect. EP-Preis + Varianz je kappa,
        # P(Ueberholen)-Grid (D x M) + Live-Counterfactual gegen die echte Crowd.
        from .risk_dial import build_risk_dial

        _pool_daten_pruefen("manual_pool_tips.json", kern=False)
        return build_risk_dial()

    def cmd_rival_profiles(args: argparse.Namespace) -> dict:
        # Per-Spieler Tipp-Profile (T-0080): Remis-Rate, Aggressivitaet, Modell-
        # Aehnlichkeit, Punkte je Rivale + Korr(Aggressivitaet, Punkte). Read-only.
        from .rival_profiles import build_rival_profiles

        _pool_daten_pruefen("manual_pool_tips.json")
        return build_rival_profiles()

    def cmd_deficit_policy(args: argparse.Namespace) -> dict:
        # Deficit-Policy (T-0080/T-0100): feld-relative Tipp-Empfehlung je Regime
        # (protect=Cover / chase=dekorrelieren / neutral=EP-Max). Read-only Overlay.
        from .deficit_policy import build_deficit_policy

        _pool_daten_pruefen("manual_pool_tips.json", "manual_standings.json")
        return build_deficit_policy()


def cmd_eval_live(args: argparse.Namespace) -> dict:
    # Live-Lernschleife: Modell-Tipps gegen echte Ergebnisse bewerten
    # (Punkte + Brier/Log-Loss + Modell/Markt/Blend-Vergleich). Read-only.
    from .eval_live import build_live_eval

    return build_live_eval()


def cmd_news_audit(args: argparse.Namespace) -> dict:
    # Read-only Diagnose: welche News erzeugen aktuell einen xG-Malus,
    # wo liegt die Fehlzuordnungs-Risikoklasse (Multi-Team, Fremd-Subject,
    # stale)? Aendert das News-Modell nicht.
    from .news_audit import build_news_audit

    return build_news_audit()


def cmd_lineup_roles(args: argparse.Namespace) -> dict:
    # Dry-Run: zeigt, welche Teams aus manuellen XIs + Lineup-News echte
    # Rollen bekommen wuerden (build-predictions wendet es live an).
    from .io import read_json
    from .paths import DATA_DIR
    from .lineup_roles import apply_lineup_roles

    pool = (read_json(DATA_DIR / "player_pool.json", {"players": {}}) or {}).get("players", {})
    news = (read_json(DATA_DIR / "news_items.json", {"items": []}) or {}).get("items", [])
    return apply_lineup_roles(pool, news)


def cmd_serve_dashboard(args: argparse.Namespace) -> dict:
    return serve_dashboard(host=args.host, port=args.port)


def cmd_backtest(args: argparse.Namespace) -> dict:
    tournament = getattr(args, "tournament", "sample")
    if tournament == "sample":
        result = run_backtest()
        result_path = DATA_DIR / "backtest_result.json"
    else:
        from .historical import build_historical_dataset, historical_dataset_path

        build_historical_dataset(tournament)
        result = run_backtest(historical_dataset_path(tournament))
        result["_meta"] = {"tournament": tournament}
        result_path = DATA_DIR / f"backtest_result_{tournament}.json"
    write_json(result_path, result)
    return result


def cmd_backtest_report(args: argparse.Namespace) -> dict:
    return build_backtest_report(include_sample=args.include_sample)


def cmd_matchday_dry_run(args: argparse.Namespace) -> dict:
    return build_matchday_dry_run()


def cmd_matchday_command(args: argparse.Namespace) -> dict:
    now = parse_datetime(args.at) if args.at else None
    if args.at and now is None:
        raise SystemExit("--at muss ein ISO-Datum sein, z.B. 2026-06-11T17:30:00+00:00")
    return build_matchday_command_center(now=now)


def cmd_lint(args: argparse.Namespace) -> dict:
    return run_lint()


def cmd_refresh_player_pool(args: argparse.Namespace) -> dict:
    return build_player_pool(force_fetch=args.force)


def cmd_watch(args: argparse.Namespace) -> dict:
    states = watch(
        live_news=args.live_news,
        refresh_fixture_source=args.refresh_fixtures,
        iterations=args.iterations,
        sleep_cap_seconds=args.sleep_cap,
    )
    return {"cycles": states}


def cmd_update_all(args: argparse.Namespace) -> dict:
    return run_update_all(
        live_news=not args.no_live_news,
        refresh_fixture_source=not args.no_live_fixtures,
        probe_live_sources=not args.no_live_source_probe,
        refresh_exact_scores=not args.skip_bwin_exact,
        refresh_match_odds=not args.skip_bwin_match_odds,
        refresh_team_intel=not args.skip_team_intel,
        refresh_player_pool=args.refresh_player_pool,
        include_backtest_report=not args.skip_backtest_report,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WM 2026 Kicktipp Dashboard Pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    fixtures = sub.add_parser("refresh-fixtures")
    fixtures.add_argument("--no-live", action="store_true", help="Nur lokale Fixture-Datei nutzen.")
    fixtures.set_defaults(func=cmd_refresh_fixtures)

    context = sub.add_parser("refresh-context")
    context.set_defaults(func=cmd_refresh_context)

    news = sub.add_parser("refresh-news")
    news.add_argument("--live", action="store_true", help="Kostenlose Live-News-Suche via GDELT versuchen.")
    news.add_argument("--limit", type=int, default=4)
    news.set_defaults(func=cmd_refresh_news)

    odds = sub.add_parser("refresh-odds")
    odds.set_defaults(func=cmd_refresh_odds)

    markets = sub.add_parser("refresh-markets")
    markets.set_defaults(func=cmd_refresh_odds)

    historical_markets = sub.add_parser("refresh-historical-markets")
    historical_markets.add_argument(
        "--tournaments",
        default="2014,2018,2022",
        help="Kommagetrennte WM-Jahre fuer freie historische Zusatzmaerkte.",
    )
    historical_markets.add_argument("--limit", type=int, default=None)
    historical_markets.add_argument("--timeout", type=int, default=20)
    historical_markets.set_defaults(func=cmd_refresh_historical_markets)

    odds_report = sub.add_parser("odds-report")
    odds_report.set_defaults(func=cmd_odds_report)

    odds_history_cmd = sub.add_parser("odds-history")
    odds_history_cmd.add_argument(
        "--match", default=None, help="Nur dieses Spiel (match_id)."
    )
    odds_history_cmd.set_defaults(func=cmd_odds_history)

    news_review_cmd = sub.add_parser("news-review")
    news_review_cmd.add_argument(
        "--promote", default=None, help="News-id in manual_news.json uebernehmen."
    )
    news_review_cmd.add_argument(
        "--dismiss", default=None, help="News-id verwerfen (bleibt aus der Queue)."
    )
    news_review_cmd.set_defaults(func=cmd_news_review)

    lineup_lock_cmd = sub.add_parser("lineup-lock")
    lineup_lock_cmd.add_argument(
        "--window", type=int, default=90, help="Pre-Kickoff-Fenster in Minuten."
    )
    lineup_lock_cmd.set_defaults(func=cmd_lineup_lock)

    signal_breaker_cmd = sub.add_parser("signal-breaker")
    signal_breaker_cmd.set_defaults(func=cmd_signal_breaker)

    totals_adjust_cmd = sub.add_parser("totals-adjust")
    totals_adjust_cmd.set_defaults(func=cmd_totals_adjust)

    context_ablation_cmd = sub.add_parser("context-ablation")
    context_ablation_cmd.set_defaults(func=cmd_context_ablation)

    lineup_roles_cmd = sub.add_parser("lineup-roles")
    lineup_roles_cmd.set_defaults(func=cmd_lineup_roles)

    blend_sweep_cmd = sub.add_parser("blend-sweep")
    blend_sweep_cmd.set_defaults(func=cmd_blend_sweep)

    role_ab_cmd = sub.add_parser("role-ab")
    role_ab_cmd.set_defaults(func=cmd_role_ab)

    news_audit_cmd = sub.add_parser("news-audit")
    news_audit_cmd.set_defaults(func=cmd_news_audit)

    eval_live_cmd = sub.add_parser("eval-live")
    eval_live_cmd.set_defaults(func=cmd_eval_live)

    strategy_ab_cmd = sub.add_parser("strategy-ab")
    strategy_ab_cmd.set_defaults(func=cmd_strategy_ab)

    favorite_calibration_cmd = sub.add_parser("favorite-calibration")
    favorite_calibration_cmd.set_defaults(func=cmd_favorite_calibration)

    # Pool-Analytik nur registrieren, wenn die Module vorhanden sind -- sonst
    # stuenden tote Kommandos im --help. Die Daten, die sie auswerten, legt
    # jeder fuer seine eigene Runde an (data/manual_*.example.json).
    if POOL_ANALYTICS_AVAILABLE:
        risk_dial_cmd = sub.add_parser(
            "risk-dial",
            help="Lohnt sich Risiko? Punkte-Preis und Varianz je Aggressionsgrad, "
            "plus Wahrscheinlichkeit, einen Rueckstand aufzuholen.",
        )
        risk_dial_cmd.set_defaults(func=cmd_risk_dial)

        rival_profiles_cmd = sub.add_parser(
            "rival-profiles",
            help="Tippverhalten der Mitspieler: Remis-Quote, Torfreude, "
            "Aehnlichkeit zum Modell, erzielte Punkte. Braucht "
            "data/manual_pool_tips.json.",
        )
        rival_profiles_cmd.set_defaults(func=cmd_rival_profiles)

        deficit_policy_cmd = sub.add_parser(
            "deficit-policy",
            help="Empfehlung je nach Tabellenlage: Feld spiegeln, vom Feld "
            "abweichen oder normal tippen. Braucht data/manual_pool_tips.json "
            "und data/manual_standings.json.",
        )
        deficit_policy_cmd.set_defaults(func=cmd_deficit_policy)

    calibrate_fit_cmd = sub.add_parser("calibrate-fit")
    calibrate_fit_cmd.set_defaults(func=cmd_calibrate_fit)

    exact_score_report = sub.add_parser("exact-score-report")
    exact_score_report.add_argument(
        "--rebuild",
        action="store_true",
        help="Vor dem Vergleich Vorhersagen neu bauen.",
    )
    exact_score_report.set_defaults(func=cmd_exact_score_report)

    bwin_exact = sub.add_parser("refresh-bwin-exact-scores")
    bwin_exact.add_argument(
        "--missing-only",
        action="store_true",
        help="Nur sichtbare Bwin-Events ohne importierte Exact-Score-Preise abrufen.",
    )
    bwin_exact.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximal so viele sichtbare Bwin-Events live abrufen.",
    )
    bwin_exact.set_defaults(func=cmd_refresh_bwin_exact_scores)

    bwin_match_odds = sub.add_parser("refresh-bwin-match-odds")
    bwin_match_odds.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximal so viele sichtbare Bwin-Events live abrufen.",
    )
    bwin_match_odds.set_defaults(func=cmd_refresh_bwin_match_odds)

    lineups_cmd = sub.add_parser("refresh-lineups")
    lineups_cmd.add_argument(
        "--window", type=int, default=75,
        help="Spiele mit Anpfiff in den naechsten N Minuten beruecksichtigen.",
    )
    lineups_cmd.add_argument(
        "--lookback", type=int, default=20,
        help="Auch Spiele beruecksichtigen, die vor N Minuten angepfiffen wurden.",
    )
    lineups_cmd.set_defaults(func=cmd_refresh_lineups)

    team_intel = sub.add_parser("team-intel-report")
    team_intel.set_defaults(func=cmd_team_intel_report)

    team_intel_checklist = sub.add_parser("team-intel-checklist")
    team_intel_checklist.set_defaults(func=cmd_team_intel_checklist)

    team_intel_refresh = sub.add_parser("refresh-team-intel-sources")
    team_intel_refresh.add_argument(
        "--statuses",
        default=None,
        help="Kommagetrennte Statuswerte; Default prueft manual_watch_unverified.",
    )
    team_intel_refresh.add_argument(
        "--ids",
        default=None,
        help="Kommagetrennte Source-IDs fuer gezielte Rechecks.",
    )
    team_intel_refresh.add_argument("--limit", type=int, default=None)
    team_intel_refresh.add_argument("--timeout", type=int, default=12)
    team_intel_refresh.add_argument("--workers", type=int, default=8)
    team_intel_refresh.set_defaults(func=cmd_refresh_team_intel_sources)

    source_watch = sub.add_parser("source-watch")
    source_watch.add_argument("--probe-live", action="store_true", help="Bwin.de-Seite live pruefen, Fehler nur reporten.")
    source_watch.set_defaults(func=cmd_source_watch)

    predictions = sub.add_parser("build-predictions")
    predictions.set_defaults(func=cmd_build_predictions)

    strengths = sub.add_parser("build-strengths")
    strengths.set_defaults(func=cmd_build_strengths)

    dashboard = sub.add_parser("build-dashboard")
    dashboard.set_defaults(func=cmd_build_dashboard)

    serve = sub.add_parser("serve-dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8002)
    serve.set_defaults(func=cmd_serve_dashboard)

    export = sub.add_parser("export-tips")
    export.set_defaults(func=cmd_export_tips)

    backtest = sub.add_parser("backtest")
    backtest.add_argument(
        "--tournament",
        choices=["sample", "2010", "2014", "2018", "2022"],
        default="sample",
        help="sample (klassisches 5-Spiele-Sample) oder 2010/2014/2018/2022 (echte WM-Datasets aus openfootball).",
    )
    backtest.set_defaults(func=cmd_backtest)

    backtest_report = sub.add_parser("backtest-report")
    backtest_report.add_argument(
        "--include-sample",
        action="store_true",
        help="Das 7-Spiele-Sample zusaetzlich zu 2018/2022 aufnehmen.",
    )
    backtest_report.set_defaults(func=cmd_backtest_report)

    matchday_dry_run = sub.add_parser("matchday-dry-run")
    matchday_dry_run.set_defaults(func=cmd_matchday_dry_run)

    matchday_command = sub.add_parser("matchday-command")
    matchday_command.add_argument(
        "--at",
        default=None,
        help="Optionaler ISO-Zeitpunkt fuer Simulation/Review, z.B. 2026-06-11T17:30:00+00:00.",
    )
    matchday_command.set_defaults(func=cmd_matchday_command)

    lint = sub.add_parser("lint")
    lint.set_defaults(func=cmd_lint)

    pool = sub.add_parser("refresh-player-pool")
    pool.add_argument(
        "--force",
        action="store_true",
        help="Cache in data/raw/ ignorieren und neu von github.com/martj42 laden.",
    )
    pool.set_defaults(func=cmd_refresh_player_pool)

    watcher = sub.add_parser("watch")
    watcher.add_argument("--live-news", action="store_true", help="Kostenlose Live-News-Suche in jeden Zyklus aufnehmen.")
    watcher.add_argument("--refresh-fixtures", action="store_true", help="Fixture-Quelle in jedem Zyklus live pruefen.")
    watcher.add_argument("--iterations", type=int, default=0, help="0 bedeutet dauerhaft laufen.")
    watcher.add_argument("--sleep-cap", type=int, default=None, help="Maximale Schlafzeit pro Zyklus, nuetzlich fuer Tests.")
    watcher.set_defaults(func=cmd_watch)

    update_all = sub.add_parser("update-all")
    update_all.add_argument("--no-live-news", action="store_true", help="Keine kostenlosen Live-News-Feeds abrufen.")
    update_all.add_argument("--no-live-fixtures", action="store_true", help="Fixture-Quelle nicht live pruefen, lokale Datei nutzen.")
    update_all.add_argument("--no-live-source-probe", action="store_true", help="Source-Watch ohne Live-Probe ausfuehren.")
    update_all.add_argument("--skip-bwin-exact", action="store_true", help="Bwin Exact-Score-Import ueberspringen.")
    update_all.add_argument("--skip-bwin-match-odds", action="store_true", help="Bwin-1X2-Matchquoten-Import ueberspringen.")
    update_all.add_argument("--skip-team-intel", action="store_true", help="Team-Intel-Reachability-Recheck ueberspringen.")
    update_all.add_argument("--refresh-player-pool", action="store_true", help="CC0-Spielerpool-Cache live neu laden.")
    update_all.add_argument("--skip-backtest-report", action="store_true", help="Ablation-Report nicht neu schreiben.")
    update_all.set_defaults(func=cmd_update_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_dirs()
    parser = build_parser()
    args = parser.parse_args(argv)
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
