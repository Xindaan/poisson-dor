"""Backtest ueber abgeschlossene Turniere.

Spielt Modellvarianten gegen sieben historische Turniere (WM 2010/2014/
2018/2022, EM 2016/2020/2024, zusammen 405 Spiele mit Quotendeckung) und
misst sie in Kicktipp-Punkten pro Spiel und Exakt-Trefferquote -- nicht in
Tendenz-Genauigkeit, weil die Punkteregel das eigentliche Ziel ist.

Datenquelle: `historical` (openfootball) und `historical_markets`. Der
Vergleichsmassstab sind die Varianten in VARIANT_NAMES, u. a. reine
Elo-Ableitung, reine Quotenableitung und deren Ensemble.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from .io import read_json, write_json
from .historical import historical_dataset_path
from .historical_markets import (
    apply_historical_market_lines,
    historical_market_constraints_from_row,
    historical_market_payload_summary,
    load_historical_market_payload,
    load_historical_market_source_audit,
)
from .model import (
    ENSEMBLE_MARKET_BLEND_WEIGHT,
    LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT,
    MARKET_SCORE_CALIBRATOR_VERSION,
    SUPPORTED_MARKET_SCORE_CONSTRAINTS,
    blend_market_probabilities,
    calibrate_score_matrix,
    calibrate_score_matrix_from_xg,
    conditional_draw_tilt,
    outcome_probabilities,
    score_matrix,
)
from . import model as _model  # T-0104: model.DRAW_DC_RHO zur Laufzeit lesen (toggle-bar)
from .odds import normalize_decimal_odds
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import (
    DEFAULT_ROUND_ID,
    Score,
    actual_for_round,
    best_kicktipp_tip,
    kicktipp_points,
)


VARIANT_NAMES = ("naive", "elo", "odds", "ensemble")
REPORT_TOURNAMENTS = (
    "2010", "2014", "2018", "2022",
    "euro-2016", "euro-2020", "euro-2024",
)
MARKET_OVERRIDE_THRESHOLD = 0.12
# T-0058 (Codex-Entscheid): Verdict-Regel auf fairem Quoten-Nenner.
# keep_full nur, wenn der Ensemble-Vorteil ueber Odds-only mindestens
# VERDICT_MIN_PPM_EDGE Punkte/Spiel betraegt UND mehr Turniere vorn als
# hinten liegen (Mehrheits- statt Jedes-Turnier-Regel -- bestraft nicht
# mehr Daten). Darunter/uneinheitlich -> needs_more_data; netto<=0 ohne
# jeden Turniervorteil -> simplify.
VERDICT_MIN_PPM_EDGE = 0.05
VERDICT_MIN_COVERAGE = 50
BACKTEST_REPORT_PATH = DATA_DIR / "backtest_report.json"
BACKTEST_REPORT_MARKDOWN_PATH = EXPORTS_DIR / "backtest_report.md"
ODDS_VARIANT_NOTE = (
    "odds ist ein 1X2-Quoten-kalibrierter Score-Tipp mit aus der "
    "Remiswahrscheinlichkeit abgeleiteter Torhoehe, kein historischer "
    "Exact-Score-Markt."
)
REPORT_CAVEAT = (
    "Backtest umfasst WM 2010/2014/2018/2022 + EM 2016/2020/2024 "
    "(Vorrunde + KO); KO-Elo ist ein Pre-Turnier-Snapshot. Quoten liegen "
    "fuer WM 2014/2018/2022 + EM 2016/2020/2024 (342 Spiele) vor; nur WM "
    "2010 ist ohne Quoten. Den Odds-Vergleich nur auf der Quoten-Teilmenge "
    "lesen (gleicher Nenner). Pragmatischer Kicktipp-Check, keine "
    "Betting-Edge-Behauptung."
)


def _xg_from_pre_match(
    pre_elo: Mapping[str, Any] | None,
    pre_odds: Mapping[str, Any] | None = None,
) -> tuple[float, float, bool] | None:
    if pre_elo and pre_elo.get("home") is not None and pre_elo.get("away") is not None:
        rating_diff = float(pre_elo["home"]) - float(pre_elo["away"])
        return (
            1.28 * math.exp(rating_diff / 780),
            1.28 * math.exp(-rating_diff / 780),
            True,
        )
    if pre_odds:
        return (1.28, 1.28, False)
    return None


def tip_from_elo(home_elo: float, away_elo: float, stage: str, round_id: str = DEFAULT_ROUND_ID) -> tuple[int, int]:
    base = 1.28
    rating_diff = float(home_elo) - float(away_elo)
    home_xg = base * math.exp(rating_diff / 780)
    away_xg = base * math.exp(-rating_diff / 780)
    matrix = score_matrix(home_xg, away_xg)
    tip = best_kicktipp_tip(matrix, stage, round_id=round_id)
    return int(tip["home"]), int(tip["away"])


def tip_from_odds(
    pre_odds: Mapping[str, Any],
    pre_elo: Mapping[str, Any] | None,
    stage: str,
    round_id: str = DEFAULT_ROUND_ID,
) -> tuple[int, int] | None:
    return _tip_from_odds_with_options(
        pre_odds,
        pre_elo,
        stage,
        round_id=round_id,
        draw_target_total=True,
    )


def _tip_from_odds_with_options(
    pre_odds: Mapping[str, Any],
    pre_elo: Mapping[str, Any] | None,
    stage: str,
    *,
    round_id: str = DEFAULT_ROUND_ID,
    draw_target_total: bool,
    extra_market_constraints: list[Mapping[str, Any]] | None = None,
) -> tuple[int, int] | None:
    probabilities = normalize_decimal_odds(pre_odds)
    if not probabilities:
        return None
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, _ = xg
    if draw_target_total:
        market_constraints = None
        if extra_market_constraints:
            from .model import market_constraints_from_outcomes

            market_constraints = [
                *market_constraints_from_outcomes(probabilities),
                *extra_market_constraints,
            ]
        calibrated, _ = calibrate_score_matrix_from_xg(
            home_xg,
            away_xg,
            probabilities,
            total_mode="market_constraints",
            market_constraints=market_constraints,
        )
    else:
        matrix = score_matrix(home_xg, away_xg)
        calibrated = calibrate_score_matrix(matrix, probabilities)
    tip = best_kicktipp_tip(calibrated, stage, round_id=round_id)
    return int(tip["home"]), int(tip["away"])


def ensemble_calibrated_matrix(
    pre_elo: Mapping[str, Any] | None,
    pre_odds: Mapping[str, Any] | None,
    *,
    market_weight: float = ENSEMBLE_MARKET_BLEND_WEIGHT,
) -> dict[str, float] | None:
    """Die Score-Matrix, auf der `tip_from_ensemble` tippt (Modell, ggf.
    markt-geblendet + kalibriert). Spiegelt `_tip_from_ensemble_with_options`;
    `test_calibration_fit` haelt den Spiegel via Tip-Reconciliation. Fuer
    den Offline-Kalibrier-Fit (T-0073)."""
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, has_elo = xg
    matrix = score_matrix(home_xg, away_xg)
    model_probabilities = outcome_probabilities(matrix)
    market_probabilities = normalize_decimal_odds(pre_odds or {})
    market_for_blend: Mapping[str, float] | None = market_probabilities
    if has_elo and market_probabilities:
        model_favorite = max(model_probabilities, key=lambda key: model_probabilities[key])
        market_favorite = max(market_probabilities, key=lambda key: market_probabilities[key])
        market_edge = market_probabilities[market_favorite] - model_probabilities[market_favorite]
        if market_favorite != model_favorite and market_edge < MARKET_OVERRIDE_THRESHOLD:
            market_for_blend = None
    if not market_for_blend:
        return dict(matrix)
    blended = blend_market_probabilities(model_probabilities, market_for_blend, weight=market_weight)
    return calibrate_score_matrix(matrix, blended)


def tip_from_ensemble(
    pre_elo: Mapping[str, Any] | None,
    pre_odds: Mapping[str, Any] | None,
    stage: str,
    round_id: str = DEFAULT_ROUND_ID,
) -> tuple[int, int] | None:
    return _tip_from_ensemble_with_options(
        pre_elo,
        pre_odds,
        stage,
        round_id=round_id,
        market_weight=ENSEMBLE_MARKET_BLEND_WEIGHT,
    )


def _tip_from_ensemble_with_options(
    pre_elo: Mapping[str, Any] | None,
    pre_odds: Mapping[str, Any] | None,
    stage: str,
    *,
    round_id: str = DEFAULT_ROUND_ID,
    market_weight: float,
) -> tuple[int, int] | None:
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, has_elo = xg
    matrix = score_matrix(home_xg, away_xg)
    if _model.DRAW_DC_RHO:
        matrix = _model.dixon_coles_adjust(matrix, _model.DRAW_DC_RHO)  # T-0104/H13: Belief at-source
    model_probabilities = outcome_probabilities(matrix)
    market_probabilities = normalize_decimal_odds(pre_odds or {})
    market_for_blend: Mapping[str, float] | None = market_probabilities
    if has_elo and market_probabilities:
        model_favorite = max(model_probabilities, key=lambda key: model_probabilities[key])
        market_favorite = max(market_probabilities, key=lambda key: market_probabilities[key])
        market_edge = market_probabilities[market_favorite] - model_probabilities[market_favorite]
        if market_favorite != model_favorite and market_edge < MARKET_OVERRIDE_THRESHOLD:
            market_for_blend = None
    if not market_for_blend:
        tip = best_kicktipp_tip(conditional_draw_tilt(matrix), stage, round_id=round_id)
        return int(tip["home"]), int(tip["away"])
    blended = blend_market_probabilities(model_probabilities, market_for_blend, weight=market_weight)
    calibrated = calibrate_score_matrix(matrix, blended)
    tip = best_kicktipp_tip(conditional_draw_tilt(calibrated), stage, round_id=round_id)
    return int(tip["home"]), int(tip["away"])


def variant_tips(row: Mapping[str, Any], round_id: str = DEFAULT_ROUND_ID) -> dict[str, tuple[int, int] | None]:
    stage = row.get("stage", "group")
    tips: dict[str, tuple[int, int] | None] = {name: None for name in VARIANT_NAMES}
    if "favorite_tip" in row:
        home, away = row["favorite_tip"]
        tips["naive"] = (int(home), int(away))
    if "model_tip" in row:
        home, away = row["model_tip"]
        tips["ensemble"] = (int(home), int(away))
    pre_elo = row.get("pre_elo") or {}
    if pre_elo.get("home") is not None and pre_elo.get("away") is not None:
        tips["elo"] = tip_from_elo(pre_elo["home"], pre_elo["away"], stage, round_id)
        if tips["naive"] is None:
            tips["naive"] = tips["elo"]
    pre_odds = row.get("pre_odds")
    if pre_odds:
        tips["odds"] = tip_from_odds(pre_odds, pre_elo or None, stage, round_id)
    if tips["ensemble"] is None:
        tips["ensemble"] = tip_from_ensemble(pre_elo or None, pre_odds, stage, round_id)
    return tips


def _accumulate(
    totals: dict[str, dict[str, int]],
    name: str,
    tip: tuple[int, int] | None,
    actual: Score,
    stage: str,
    round_id: str = DEFAULT_ROUND_ID,
) -> None:
    bucket = totals.setdefault(name, {"points": 0, "matches": 0})
    if tip is None:
        return
    bucket["points"] += kicktipp_points(Score(*tip), actual, stage, round_id=round_id)
    bucket["matches"] += 1


def _empty_result() -> dict[str, Any]:
    variants = {
        name: {"matches": 0, "points": 0, "points_per_match": None}
        for name in VARIANT_NAMES
    }
    return {
        "matches": 0,
        "variants": variants,
        "favorite_points": 0,
        "model_points": 0,
        "points_per_match_favorite": None,
        "points_per_match_model": None,
    }


def _normalize_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    return []


def run_backtest(dataset_path: Path | str | None = None, round_id: str = DEFAULT_ROUND_ID) -> dict[str, Any]:
    path = Path(dataset_path) if dataset_path else DATA_DIR / "backtest_sample.json"
    rows = _normalize_rows(read_json(path, []))
    if not rows:
        return _empty_result()
    totals: dict[str, dict[str, int]] = {}
    for row in rows:
        actual = actual_for_round(
            row["actual"], row.get("penalty_winner"), round_id, row.get("shootout")
        )
        stage = row.get("stage", "group")
        tips = variant_tips(row, round_id)
        for name in VARIANT_NAMES:
            _accumulate(totals, name, tips[name], actual, stage, round_id)

    variants: dict[str, dict[str, Any]] = {}
    for name in VARIANT_NAMES:
        bucket = totals.get(name, {"points": 0, "matches": 0})
        per_match = (
            round(bucket["points"] / bucket["matches"], 3) if bucket["matches"] else None
        )
        variants[name] = {
            "points": bucket["points"],
            "matches": bucket["matches"],
            "points_per_match": per_match,
        }
    return {
        "matches": len(rows),
        "group_matches": sum(1 for r in rows if r.get("stage", "group") == "group"),
        "knockout_matches": sum(1 for r in rows if r.get("stage") == "knockout"),
        "round_id": round_id,
        "variants": variants,
        # Legacy-Aliase aus dem 5-Zeilen-Sample, damit alte Konsumenten von data/backtest_result.json nicht brechen.
        "favorite_points": variants["naive"]["points"],
        "model_points": variants["ensemble"]["points"],
        "points_per_match_favorite": variants["naive"]["points_per_match"],
        "points_per_match_model": variants["ensemble"]["points_per_match"],
    }


def build_backtest_report(
    *,
    include_sample: bool = False,
    write: bool = True,
    datasets: list[tuple[str, Path | str]] | None = None,
    json_path: Path | str = BACKTEST_REPORT_PATH,
    markdown_path: Path | str = BACKTEST_REPORT_MARKDOWN_PATH,
    round_id: str = DEFAULT_ROUND_ID,
    historical_market_payload: Mapping[str, Any] | None = None,
    historical_market_source_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    dataset_specs = datasets or default_report_datasets(include_sample=include_sample)
    market_payload = (
        historical_market_payload
        if historical_market_payload is not None
        else load_historical_market_payload()
    )
    market_source_audit = (
        historical_market_source_audit
        if historical_market_source_audit is not None
        else load_historical_market_source_audit()
    )
    tournaments = [
        evaluate_backtest_dataset(
            tournament,
            Path(path),
            round_id,
            historical_market_payload=market_payload,
        )
        for tournament, path in dataset_specs
    ]
    combined_rows = [
        row
        for tournament in tournaments
        for row in tournament["evaluated_matches"]
    ]
    combined = summarize_evaluated_matches("combined", combined_rows)
    # Fairer Vergleich: alle Varianten NUR auf den Spielen mit Quoten, damit
    # man Ensemble nicht (252 Spiele) gegen odds (Teilmenge) mit
    # unterschiedlichem Nenner vergleicht. Das ist die ehrliche Same-Subset-
    # Gegenueberstellung; die Headline-Tabelle "Kombiniert" nutzt dagegen die
    # volle Abdeckung je Variante.
    odds_covered_rows = [
        row for row in combined_rows
        if row["variants"]["odds"]["points"] is not None
    ]
    odds_covered = summarize_evaluated_matches("odds_covered", odds_covered_rows)
    score_calibration = score_calibration_audit(
        combined_rows,
        round_id=round_id,
        historical_market_payload=market_payload,
        historical_market_source_audit=market_source_audit,
    )
    verdict = report_verdict(tournaments, combined)
    public_tournaments = [
        public_report_section(tournament)
        for tournament in tournaments
    ]
    report = {
        "_meta": {
            "include_sample": include_sample,
            "round_id": round_id,
            "tournaments": [row["tournament"] for row in tournaments],
            "odds_variant_note": ODDS_VARIANT_NOTE,
            "caveat": REPORT_CAVEAT,
        },
        "verdict": verdict,
        "combined": public_report_section(combined),
        "odds_covered": public_report_section(odds_covered),
        "score_calibration": score_calibration,
        "tournaments": public_tournaments,
    }
    if write:
        write_json(Path(json_path), report)
        Path(markdown_path).parent.mkdir(parents=True, exist_ok=True)
        Path(markdown_path).write_text(backtest_report_markdown(report), encoding="utf-8")
    return report


def default_report_datasets(*, include_sample: bool = False) -> list[tuple[str, Path]]:
    datasets = [
        (tournament, historical_dataset_path(tournament))
        for tournament in REPORT_TOURNAMENTS
    ]
    if include_sample:
        return [("sample", DATA_DIR / "backtest_sample.json"), *datasets]
    return datasets


# Punkt C: Sweep des Markt-Blend-Gewichts gegen die Quoten-Spiele -- haelt
# die in T-0053 gewaehlten 15%? 0.0 = pures Modell (Elo+Kontext, kein
# Markt), hoehere Werte = mehr Markt.
BLEND_SWEEP_WEIGHTS = (0.0, 0.10, 0.15, 0.20, 0.25, 0.35, 0.50, 1.0)
BLEND_SWEEP_PATH = DATA_DIR / "blend_sweep.json"
BLEND_SWEEP_MARKDOWN_PATH = EXPORTS_DIR / "blend_sweep.md"


def _odds_covered_rows_for_report(round_id: str) -> list[dict[str, Any]]:
    payload = load_historical_market_payload()
    rows: list[dict[str, Any]] = []
    for tournament, path in default_report_datasets():
        section = evaluate_backtest_dataset(
            tournament, Path(path), round_id, historical_market_payload=payload
        )
        for row in section["evaluated_matches"]:
            if row["variants"]["odds"]["points"] is not None:
                rows.append(row)
    return rows


def blend_weight_sweep(
    *,
    round_id: str = DEFAULT_ROUND_ID,
    weights: tuple[float, ...] = BLEND_SWEEP_WEIGHTS,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ensemble-Punkte je Markt-Blend-Gewicht auf den Quoten-Spielen.

    Zeigt, ob das Live-Gewicht (ENSEMBLE_MARKET_BLEND_WEIGHT) datenseitig
    haelt oder ein anderes Gewicht besser waere. Diagnose, veraendert
    keine Live-Tipps.
    """
    odds_rows = rows if rows is not None else _odds_covered_rows_for_report(round_id)
    results: list[dict[str, Any]] = []
    for weight in weights:
        points = 0
        matches = 0
        for row in odds_rows:
            source_row = row.get("source_row") or {}
            tip = _tip_from_ensemble_with_options(
                source_row.get("pre_elo") or None,
                source_row.get("pre_odds"),
                row.get("stage", "group"),
                round_id=round_id,
                market_weight=weight,
            )
            if tip is None:
                continue
            actual = Score(*[int(part) for part in row["actual"].split(":")])
            points += kicktipp_points(Score(*tip), actual, row.get("stage", "group"), round_id=round_id)
            matches += 1
        results.append(
            {
                "market_weight": weight,
                "points": points,
                "matches": matches,
                "points_per_match": round(points / matches, 4) if matches else None,
                "is_current": abs(weight - ENSEMBLE_MARKET_BLEND_WEIGHT) < 1e-9,
            }
        )
    scored = [r for r in results if r["points_per_match"] is not None]
    best = max(scored, key=lambda r: r["points_per_match"]) if scored else None
    current = next((r for r in results if r["is_current"]), None)
    return {
        "_meta": {
            "round_id": round_id,
            "matches": len(odds_rows),
            "current_weight": ENSEMBLE_MARKET_BLEND_WEIGHT,
            "best_weight": best["market_weight"] if best else None,
            "best_minus_current_ppm": (
                round(best["points_per_match"] - current["points_per_match"], 4)
                if best and current and current["points_per_match"] is not None
                else None
            ),
            "summary": (
                "Markt-Blend-Sweep auf den Quoten-Spielen: 0.0 = pures Modell "
                "(Elo+Kontext), hoehere Werte mischen mehr Markt bei. Zeigt, ob "
                f"das Live-Gewicht {ENSEMBLE_MARKET_BLEND_WEIGHT:.0%} haelt. Diagnose, "
                "veraendert keine Live-Tipps."
            ),
        },
        "weights": results,
    }


def blend_weight_sweep_markdown(report: Mapping[str, Any]) -> str:
    meta = report.get("_meta") or {}
    lines = [
        "# Markt-Blend-Gewicht-Sweep (Punkt C)",
        "",
        meta.get("summary", ""),
        "",
        (
            f"Quoten-Spiele: {meta.get('matches', 0)}. Live-Gewicht: "
            f"{meta.get('current_weight')}. Bestes Gewicht im Sweep: "
            f"{meta.get('best_weight')} (Delta zum Live-Gewicht: "
            f"{meta.get('best_minus_current_ppm')} Punkte/Spiel)."
        ),
        "",
        "| Markt-Gewicht | Spiele | Punkte | Punkte/Spiel | |",
        "|---:|---:|---:|---:|---|",
    ]
    for row in report.get("weights") or []:
        marker = " <- live" if row.get("is_current") else ""
        lines.append(
            "| {weight:.0%} | {matches} | {points} | {ppm} |{marker} |".format(
                weight=row.get("market_weight", 0.0),
                matches=row.get("matches", 0),
                points=row.get("points", 0),
                ppm=format_optional(row.get("points_per_match")),
                marker=marker,
            )
        )
    return "\n".join(lines)


def build_blend_weight_sweep(*, round_id: str = DEFAULT_ROUND_ID, write: bool = True) -> dict[str, Any]:
    report = blend_weight_sweep(round_id=round_id)
    if write:
        write_json(BLEND_SWEEP_PATH, report)
        BLEND_SWEEP_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        BLEND_SWEEP_MARKDOWN_PATH.write_text(blend_weight_sweep_markdown(report), encoding="utf-8")
    return report


def score_calibration_audit(
    rows: list[dict[str, Any]],
    *,
    round_id: str = DEFAULT_ROUND_ID,
    historical_market_payload: Mapping[str, Any] | None = None,
    historical_market_source_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    odds_rows = [
        row for row in rows
        if row["variants"]["odds"]["points"] is not None
    ]
    if not odds_rows:
        return {
            "summary": "Keine Spiele mit historischen Quoten fuer Score-Kalibrierung.",
            "matches": 0,
            "variants": {},
            "per_tournament": [],
        }
    variant_specs = {
        "odds_legacy_outcome_only": (
            "Odds-only alt: 1X2-Outcome-Kalibrierung ohne Torhoehenanpassung",
            lambda row: _tip_from_odds_with_options(
                row.get("pre_odds") or {},
                row.get("pre_elo") or None,
                row.get("stage", "group"),
                round_id=round_id,
                draw_target_total=False,
            ),
        ),
        "odds_draw_total": (
            "Odds-only neu: Torhoehe aus 1X2-Remiswahrscheinlichkeit",
            lambda row: _tip_from_odds_with_options(
                row.get("pre_odds") or {},
                row.get("pre_elo") or None,
                row.get("stage", "group"),
                round_id=round_id,
                draw_target_total=True,
            ),
        ),
        "odds_market_score_v1": (
            "Odds-only + historische O/U/BTTS/Handicap-Zusatzmaerkte",
            lambda row: _tip_from_odds_with_options(
                row.get("pre_odds") or {},
                row.get("pre_elo") or None,
                row.get("stage", "group"),
                round_id=round_id,
                draw_target_total=True,
                extra_market_constraints=historical_market_constraints_from_row(row),
            ),
        ),
        "ensemble_legacy_35": (
            f"Ensemble alt: Marktgewicht {LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT:.0%}",
            lambda row: _tip_from_ensemble_with_options(
                row.get("pre_elo") or None,
                row.get("pre_odds"),
                row.get("stage", "group"),
                round_id=round_id,
                market_weight=LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT,
            ),
        ),
        "ensemble_current_15": (
            f"Ensemble neu: Marktgewicht {ENSEMBLE_MARKET_BLEND_WEIGHT:.0%}",
            lambda row: _tip_from_ensemble_with_options(
                row.get("pre_elo") or None,
                row.get("pre_odds"),
                row.get("stage", "group"),
                round_id=round_id,
                market_weight=ENSEMBLE_MARKET_BLEND_WEIGHT,
            ),
        ),
    }

    evaluated: dict[str, list[dict[str, Any]]] = {
        name: [] for name in variant_specs
    }
    per_tournament: dict[str, dict[str, dict[str, int]]] = {}
    # T-0054c: Disagreement-Daten direkt aus den hier ohnehin berechneten
    # Tipps sammeln -- kein zweiter (teurer) Kalibrierungs-Durchlauf.
    disagreement_inputs: list[dict[str, Any]] = []
    extra_market_matches = 0
    for row in odds_rows:
        stage = row.get("stage", "group")
        actual = Score(*[int(part) for part in row["actual"].split(":")])
        tournament = str(row.get("tournament", "unknown"))
        per_tournament.setdefault(
            tournament,
            {name: {"points": 0, "matches": 0} for name in variant_specs},
        )
        original_row = row.get("source_row") or {}
        constraints = historical_market_constraints_from_row(original_row)
        if constraints:
            extra_market_matches += 1
        row_tips: dict[str, tuple[tuple[int, int], int]] = {}
        for name, (_label, fn) in variant_specs.items():
            tip = fn(original_row)
            if tip is None:
                continue
            points = kicktipp_points(Score(*tip), actual, stage, round_id=round_id)
            row_tips[name] = (tip, points)
            evaluated[name].append(
                {
                    "tournament": tournament,
                    "match": row.get("match"),
                    "tip": score_label(tip),
                    "actual": actual.label,
                    "points": points,
                }
            )
            per_tournament[tournament][name]["points"] += points
            per_tournament[tournament][name]["matches"] += 1
        draw_total = row_tips.get("odds_draw_total")
        market_score = row_tips.get("odds_market_score_v1")
        if draw_total and market_score and draw_total[0] != market_score[0]:
            disagreement_inputs.append(
                {
                    "tournament": tournament,
                    "match": row.get("match"),
                    "actual": actual.label,
                    "draw_total_tip": score_label(draw_total[0]),
                    "draw_total_points": draw_total[1],
                    "market_score_tip": score_label(market_score[0]),
                    "market_score_points": market_score[1],
                    "delta": market_score[1] - draw_total[1],
                    "markets": _market_constraint_label(constraints),
                }
            )

    variants = {
        name: {
            "label": label,
            "matches": len(matches),
            "points": sum(int(match["points"]) for match in matches),
            "points_per_match": (
                round(sum(int(match["points"]) for match in matches) / len(matches), 3)
                if matches else None
            ),
        }
        for name, (label, _fn) in variant_specs.items()
        for matches in [evaluated[name]]
    }
    variants["odds_draw_total"]["delta_vs_legacy_points"] = (
        variants["odds_draw_total"]["points"] - variants["odds_legacy_outcome_only"]["points"]
    )
    variants["odds_market_score_v1"]["delta_vs_draw_total_points"] = (
        variants["odds_market_score_v1"]["points"] - variants["odds_draw_total"]["points"]
    )
    variants["odds_market_score_v1"]["extra_market_matches"] = extra_market_matches
    variants["ensemble_current_15"]["delta_vs_legacy_points"] = (
        variants["ensemble_current_15"]["points"] - variants["ensemble_legacy_35"]["points"]
    )
    per_tournament_rows = []
    for tournament, buckets in sorted(per_tournament.items()):
        per_tournament_rows.append(
            {
                "tournament": tournament,
                "variants": {
                    name: {
                        **bucket,
                        "points_per_match": (
                            round(bucket["points"] / bucket["matches"], 3)
                            if bucket["matches"] else None
                        ),
                    }
                    for name, bucket in buckets.items()
                },
            }
        )
    return {
        "summary": (
            "Score-Kalibrierung 2.0: Odds-only formt die Torhoehe ueber "
            "die 1X2-Remiswahrscheinlichkeit; das Ensemble nutzt ein "
            f"vorsichtigeres Marktgewicht von {ENSEMBLE_MARKET_BLEND_WEIGHT:.0%} "
            f"statt {LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT:.0%}."
        ),
        "matches": len(odds_rows),
        "variants": variants,
        "market_score_calibrator": market_score_calibrator_audit(
            odds_rows,
            historical_market_payload=historical_market_payload,
            historical_market_source_audit=historical_market_source_audit,
        ),
        "market_score_disagreement": summarize_market_score_disagreement(
            disagreement_inputs, extra_market_matches
        ),
        "per_tournament": per_tournament_rows,
    }


def _market_constraint_label(constraints: list[Mapping[str, Any]]) -> str:
    bits = []
    for constraint in constraints:
        kind = constraint.get("kind")
        if kind == "total_goals":
            bits.append(f"O/U{constraint.get('line'):g}>{constraint.get('target'):.2f}")
        elif kind == "btts":
            bits.append(f"BTTS{constraint.get('target'):.2f}")
        elif kind == "handicap":
            bits.append(f"AH{constraint.get('line'):+g}cov{constraint.get('target'):.2f}")
    return ", ".join(bits)


def summarize_market_score_disagreement(
    records: list[Mapping[str, Any]],
    extra_market_games: int,
) -> dict[str, Any]:
    """T-0054c: Fasst die abweichenden Tipps odds_draw_total vs
    odds_market_score_v1 zusammen.

    `records` enthaelt nur Spiele mit unterschiedlichem Tipp (in
    score_calibration_audit ohne zweiten Kalibrierungslauf gesammelt).
    Zeigt, wo die historischen Zusatzmaerkte (O/U/BTTS/Handicap) Punkte
    bringen oder kosten -- so wird der +3-Befund nicht als breiter Vorteil
    missverstanden, sondern als Bilanz weniger Spiele mit vielen
    punktneutralen Tippwechseln.
    """
    movers: list[dict[str, Any]] = []
    differing = len(records)
    neutral = 0
    helped_games = helped_points = 0
    hurt_games = hurt_points = 0
    for record in records:
        delta = int(record.get("delta") or 0)
        if delta == 0:
            neutral += 1
            continue
        if delta > 0:
            helped_games += 1
            helped_points += delta
        else:
            hurt_games += 1
            hurt_points += delta
        movers.append(dict(record))
    movers.sort(key=lambda mover: mover["delta"])
    net_points = helped_points + hurt_points
    extra_games = extra_market_games
    return {
        "summary": (
            f"Zusatzmaerkte aendern {differing} Tipps, aber nur "
            f"{helped_games + hurt_games} aendern Punkte (netto {net_points:+d}: "
            f"+{helped_points} aus {helped_games} Spielen, {hurt_points} aus "
            f"{hurt_games}). {neutral} Tippwechsel sind punktneutral. Duenner, "
            "konzentrierter Vorteil -- bleibt backtest-only."
        ),
        "extra_market_games": extra_games,
        "differing_tips": differing,
        "neutral_tip_changes": neutral,
        "net_points": net_points,
        "helped": {"games": helped_games, "points": helped_points},
        "hurt": {"games": hurt_games, "points": hurt_points},
        "movers": movers,
    }


def market_score_calibrator_audit(
    rows: list[dict[str, Any]],
    *,
    historical_market_payload: Mapping[str, Any] | None = None,
    historical_market_source_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = {
        "1x2": sum(1 for row in rows if (row.get("source_row") or {}).get("pre_odds")),
        "over_under": sum(1 for row in rows if (row.get("source_row") or {}).get("pre_over_under")),
        "btts": sum(1 for row in rows if (row.get("source_row") or {}).get("pre_btts")),
        "handicap": sum(1 for row in rows if (row.get("source_row") or {}).get("pre_handicap")),
    }
    extra_total = coverage["over_under"] + coverage["btts"] + coverage["handicap"]
    status = "ready_waiting_for_extra_markets" if extra_total == 0 else "extra_markets_available"
    source_audit = (
        historical_market_source_audit
        if historical_market_source_audit is not None
        else load_historical_market_source_audit()
    )
    payload_summary = historical_market_payload_summary(
        historical_market_payload
        if historical_market_payload is not None
        else load_historical_market_payload()
    )
    return {
        "version": MARKET_SCORE_CALIBRATOR_VERSION,
        "status": status,
        "supported_constraints": list(SUPPORTED_MARKET_SCORE_CONSTRAINTS),
        "historical_coverage": coverage,
        "historical_import": payload_summary,
        "source_audit": {
            "decision": source_audit.get("decision") or {},
            "accepted_sources_count": sum(1 for row in source_audit.get("sources") or [] if row.get("accepted") is True),
            "searched_sources_count": len(source_audit.get("sources") or []),
            "updated_at": (source_audit.get("_meta") or {}).get("updated_at"),
        },
        "summary": (
            "T-0054a Market-Score-Calibrator ist technisch bereit fuer "
            "Over/Under, BTTS und Handicap; im historischen WM-Datensatz "
            "liegen aktuell aber nur 1X2-Quoten vor."
            if extra_total == 0
            else (
                "T-0054b hat historische Zusatzmaerkte importiert; sie bleiben "
                "backtest-only, bis die Zusatzmarkt-Variante gegen 1X2-only "
                "positiven Kicktipp-Wert zeigt."
            )
        ),
    }


def evaluate_backtest_dataset(
    tournament: str,
    path: Path,
    round_id: str = DEFAULT_ROUND_ID,
    *,
    historical_market_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _normalize_rows(read_json(path, []))
    rows = apply_historical_market_lines(tournament, rows, historical_market_payload)
    evaluated = [
        evaluate_backtest_match(tournament, index + 1, row, round_id)
        for index, row in enumerate(rows)
    ]
    return summarize_evaluated_matches(tournament, evaluated)


def evaluate_backtest_match(
    tournament: str,
    index: int,
    row: Mapping[str, Any],
    round_id: str = DEFAULT_ROUND_ID,
) -> dict[str, Any]:
    actual = actual_for_round(
            row["actual"], row.get("penalty_winner"), round_id, row.get("shootout")
        )
    stage = row.get("stage", "group")
    tips = variant_tips(row, round_id)
    variants = {}
    for name in VARIANT_NAMES:
        tip = tips[name]
        if tip is None:
            variants[name] = {"tip": None, "points": None}
            continue
        variants[name] = {
            "tip": score_label(tip),
            "points": kicktipp_points(Score(*tip), actual, stage, round_id=round_id),
        }
    return {
        "tournament": tournament,
        "index": index,
        "match": row.get("match"),
        "stage": stage,
        "actual": actual.label,
        "variants": variants,
        "source_row": dict(row),
    }


def summarize_evaluated_matches(
    tournament: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_matches = len(rows)
    variants = {
        name: summarize_variant(rows, name, total_matches)
        for name in VARIANT_NAMES
    }
    for variant in variants.values():
        add_delta_fields(variant, variants, "odds")
        add_delta_fields(variant, variants, "elo")
    head_to_head_rows = {
        "ensemble_vs_odds": head_to_head(rows, "ensemble", "odds"),
        "ensemble_vs_elo": head_to_head(rows, "ensemble", "elo"),
        "odds_vs_elo": head_to_head(rows, "odds", "elo"),
    }
    variant_ranking = ranked_variants(variants)
    return {
        "tournament": tournament,
        "matches": total_matches,
        "variants": variants,
        "best_variant": variant_ranking[0] if variant_ranking else None,
        "worst_variant": variant_ranking[-1] if variant_ranking else None,
        "head_to_head": head_to_head_rows,
        "ensemble_odds_differing_matches": head_to_head_rows["ensemble_vs_odds"][
            "differing_matches"
        ],
        "evaluated_matches": rows,
    }


def public_report_section(section: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in section.items() if key != "evaluated_matches"}


def ranked_variants(variants: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranking = []
    for index, name in enumerate(VARIANT_NAMES):
        row = variants[name]
        if row.get("points_per_match") is None:
            continue
        ranking.append(
            {
                "name": name,
                "points": row["points"],
                "matches": row["matches"],
                "points_per_match": row["points_per_match"],
                "rank_key": (
                    row["points_per_match"],
                    row["points"],
                    -index,
                ),
            }
        )
    ranking.sort(key=lambda row: row["rank_key"], reverse=True)
    for row in ranking:
        del row["rank_key"]
    return ranking


def summarize_variant(
    rows: list[dict[str, Any]],
    name: str,
    total_matches: int,
) -> dict[str, Any]:
    points = 0
    matches = 0
    for row in rows:
        variant = row["variants"][name]
        if variant["points"] is None:
            continue
        points += int(variant["points"])
        matches += 1
    return {
        "points": points,
        "matches": matches,
        "points_per_match": round(points / matches, 3) if matches else None,
        "coverage": round(matches / total_matches, 3) if total_matches else None,
    }


def add_delta_fields(
    variant: dict[str, Any],
    variants: Mapping[str, Mapping[str, Any]],
    baseline: str,
) -> None:
    baseline_row = variants.get(baseline) or {}
    variant[f"delta_vs_{baseline}_points"] = (
        variant["points"] - baseline_row["points"]
        if variant.get("matches") and baseline_row.get("matches")
        else None
    )
    variant_ppm = variant.get("points_per_match")
    baseline_ppm = baseline_row.get("points_per_match")
    variant[f"delta_vs_{baseline}_ppm"] = (
        round(variant_ppm - baseline_ppm, 3)
        if variant_ppm is not None and baseline_ppm is not None
        else None
    )


def head_to_head(
    rows: list[dict[str, Any]],
    left: str,
    right: str,
) -> dict[str, Any]:
    compared = 0
    left_wins = 0
    right_wins = 0
    ties = 0
    point_delta = 0
    differing_tips = 0
    differing_matches = []
    for row in rows:
        left_row = row["variants"][left]
        right_row = row["variants"][right]
        if left_row["points"] is None or right_row["points"] is None:
            continue
        compared += 1
        delta = int(left_row["points"]) - int(right_row["points"])
        point_delta += delta
        if delta > 0:
            left_wins += 1
        elif delta < 0:
            right_wins += 1
        else:
            ties += 1
        if left_row["tip"] != right_row["tip"]:
            differing_tips += 1
            differing_matches.append(
                {
                    "tournament": row["tournament"],
                    "match": row.get("match"),
                    "actual": row.get("actual"),
                    f"{left}_tip": left_row["tip"],
                    f"{left}_points": left_row["points"],
                    f"{right}_tip": right_row["tip"],
                    f"{right}_points": right_row["points"],
                    "point_delta": delta,
                }
            )
    return {
        "left": left,
        "right": right,
        "compared": compared,
        "left_wins": left_wins,
        "right_wins": right_wins,
        "ties": ties,
        "point_delta": point_delta,
        "differing_tips": differing_tips,
        "differing_matches": differing_matches,
    }


def report_verdict(
    tournaments: list[dict[str, Any]],
    combined: Mapping[str, Any],
) -> dict[str, Any]:
    # Ensemble-vs-Odds nur auf gemeinsam getippten Spielen vergleichen
    # (head_to_head-Overlap). KO-Spiele ohne Quoten verzerren so nicht das
    # Urteil: Ensemble deckt sie via Elo ab, Odds nicht.
    h2h = (combined.get("head_to_head") or {}).get("ensemble_vs_odds") or {}
    compared = h2h.get("compared", 0)
    net_delta = h2h.get("point_delta", 0)
    ppm_delta = round(net_delta / compared, 4) if compared else 0.0
    # Nur Turniere mit Quoten-Overlap zaehlen fuer ahead/behind.
    per_tournament_deltas = [
        h.get("point_delta", 0)
        for t in tournaments
        for h in [(t.get("head_to_head", {}).get("ensemble_vs_odds", {}) or {})]
        if h.get("compared", 0) > 0
    ]
    ahead = sum(1 for d in per_tournament_deltas if d > 0)
    behind = sum(1 for d in per_tournament_deltas if d < 0)

    if not tournaments or compared == 0:
        status = "needs_more_data"
        summary = "Datenabdeckung reicht nicht fuer ein belastbares Odds-vs-Ensemble-Urteil."
    elif compared < VERDICT_MIN_COVERAGE:
        status = "needs_more_data"
        summary = (
            f"Quoten-Coverage zu klein ({compared} Spiele, unter {VERDICT_MIN_COVERAGE}) "
            "fuer ein belastbares Odds-vs-Ensemble-Urteil."
        )
    elif ppm_delta >= VERDICT_MIN_PPM_EDGE and ahead > behind:
        status = "keep_full_intelligence"
        summary = (
            f"Ensemble holt im Quoten-Overlap einen kleinen, pragmatisch relevanten "
            f"Kicktipp-Vorteil gegenueber 1X2-Odds-only (+{ppm_delta:.3f}/Spiel, "
            f"{ahead} Turniere vorn vs {behind}) -- duenner Vorteil, weiter beobachten. "
            "Keine 'wir schlagen den Markt'-Behauptung, sondern kleiner Zusatznutzen "
            "plus bessere Erklaerbarkeit/Watchlist."
        )
    elif ppm_delta <= 0 and ahead == 0:
        status = "simplify_to_odds_plus_watch"
        summary = (
            "Ensemble ist netto gleichauf/schlechter und zeigt auch turnierweise keinen "
            "Vorteil; naechster Schritt waere Vereinfachung auf Quotenassistent plus "
            "News-Warnsystem."
        )
    else:
        status = "needs_more_data"
        summary = (
            f"Ensemble-Vorteil liegt im Rauschbereich ({ppm_delta:+.3f}/Spiel, Schwelle "
            f"+{VERDICT_MIN_PPM_EDGE}) oder ist turnierweise uneinheitlich "
            f"({ahead} vorn, {behind} hinten); mehr Daten vor einer Festlegung."
        )
    return {
        "status": status,
        "summary": summary,
        "caveat": REPORT_CAVEAT,
        "points_per_match_delta": ppm_delta,
        "compared": compared,
        "tournaments_ahead": ahead,
        "tournaments_behind": behind,
        "decision_metric": (
            f"keep_full_intelligence wenn Ensemble-vs-Odds >= +{VERDICT_MIN_PPM_EDGE} "
            f"Punkte/Spiel im Quoten-Overlap UND mehr Turniere vorn als hinten; "
            f"simplify_to_odds_plus_watch wenn netto <=0 und kein Turnier vorn; sonst "
            f"needs_more_data (Coverage < {VERDICT_MIN_COVERAGE} oder Delta im "
            f"Rauschbereich 0..{VERDICT_MIN_PPM_EDGE} bzw. uneinheitlich)."
        ),
        "odds_variant_note": ODDS_VARIANT_NOTE,
    }


def score_label(tip: tuple[int, int] | None) -> str | None:
    if tip is None:
        return None
    return f"{int(tip[0])}:{int(tip[1])}"


def backtest_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Lohnt-sich-das?-Ablation-Report",
        "",
        f"**Verdict:** `{report['verdict']['status']}`",
        "",
        report["verdict"]["summary"],
        "",
        f"> {report['verdict']['caveat']}",
        "",
        f"Odds-Hinweis: {report['_meta']['odds_variant_note']}",
        "",
        "## Fairer Vergleich (nur Spiele mit Quoten)",
        "",
        (
            "Gleiche Teilmenge fuer alle Varianten: die "
            f"{report.get('odds_covered', {}).get('matches', 0)} Spiele, fuer "
            "die historische Quoten vorliegen. Nur so ist odds gegen "
            "ensemble/elo vergleichbar (gleicher Nenner)."
        ),
        "",
        variant_table(report.get("odds_covered", {"variants": {}})),
        "",
        "## Score-Kalibrierung 2.0",
        "",
        score_calibration_table(report.get("score_calibration", {})),
        "",
        "## Kombiniert (volle Abdeckung je Variante)",
        "",
        (
            "Achtung: odds laeuft hier auf weniger Spielen als "
            "ensemble/elo/naive (nur Spiele mit Quoten). Die Punktsummen sind "
            "daher NICHT 1:1 vergleichbar -- dafuer den fairen Vergleich oben "
            "nutzen."
        ),
        "",
        variant_table(report["combined"]),
        "",
        "## Turniere",
        "",
    ]
    for tournament in report["tournaments"]:
        lines.extend(
            [
                f"### {tournament['tournament']}",
                "",
                variant_table(tournament),
                "",
            ]
        )
    lines.extend(
        [
            "## Ensemble vs Odds-only: abweichende Tipps",
            "",
            differing_matches_table(
                report["combined"]["ensemble_odds_differing_matches"]
            ),
            "",
        ]
    )
    return "\n".join(lines)


def score_calibration_table(section: Mapping[str, Any]) -> str:
    if not section or not section.get("variants"):
        return "Noch keine Score-Kalibrierungsdaten."
    variants = section.get("variants") or {}
    market_calibrator = section.get("market_score_calibrator") or {}
    lines = [
        section.get("summary", ""),
        "",
        "| Kalibrierung | Spiele | Punkte | Punkte/Spiel | Delta |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in (
        "odds_legacy_outcome_only",
        "odds_draw_total",
        "odds_market_score_v1",
        "ensemble_legacy_35",
        "ensemble_current_15",
    ):
        row = variants.get(name)
        if not row:
            continue
        delta = row.get("delta_vs_legacy_points")
        if name == "odds_market_score_v1":
            delta = row.get("delta_vs_draw_total_points")
        lines.append(
            "| {label} | {matches} | {points} | {ppm} | {delta} |".format(
                label=row.get("label", name),
                matches=row.get("matches", 0),
                points=row.get("points", 0),
                ppm=format_optional(row.get("points_per_match")),
                delta=format_optional(delta),
            )
        )
    if market_calibrator:
        coverage = market_calibrator.get("historical_coverage") or {}
        market_import = market_calibrator.get("historical_import") or {}
        import_coverage = market_import.get("coverage") or {}
        source_audit = market_calibrator.get("source_audit") or {}
        lines.extend(
            [
                "",
                "### T-0054 Market-Score-Calibrator",
                "",
                market_calibrator.get("summary", ""),
                "",
                (
                    "Historischer Zusatzmarkt-Import: "
                    f"{import_coverage.get('matches', 0)} Spiele, "
                    f"{source_audit.get('accepted_sources_count', 0)}/"
                    f"{source_audit.get('searched_sources_count', 0)} Quellen akzeptiert."
                ),
                "",
                "| Signal | Historische Spiele |",
                "|---|---:|",
            ]
        )
        for signal in SUPPORTED_MARKET_SCORE_CONSTRAINTS:
            lines.append(f"| {signal} | {coverage.get(signal, 0)} |")
    disagreement = section.get("market_score_disagreement") or {}
    if disagreement.get("differing_tips"):
        helped = disagreement.get("helped") or {}
        hurt = disagreement.get("hurt") or {}
        lines.extend(
            [
                "",
                "### T-0054c Zusatzmarkt-Disagreement",
                "",
                disagreement.get("summary", ""),
                "",
                (
                    f"Abweichende Tipps: {disagreement.get('differing_tips', 0)} "
                    f"({disagreement.get('neutral_tip_changes', 0)} punktneutral). "
                    f"Geholfen: +{helped.get('points', 0)} aus {helped.get('games', 0)} "
                    f"Spielen. Geschadet: {hurt.get('points', 0)} aus "
                    f"{hurt.get('games', 0)}. Netto {disagreement.get('net_points', 0):+d}."
                ),
                "",
                "| Turnier | Spiel | Ergebnis | 1X2-only | +Maerkte | Delta | Maerkte |",
                "|---|---|---:|---:|---:|---:|---|",
            ]
        )
        for mover in disagreement.get("movers", []):
            lines.append(
                "| {tournament} | {match} | {actual} | {dt_tip} ({dt_pts}) | "
                "{ms_tip} ({ms_pts}) | {delta:+d} | {markets} |".format(
                    tournament=mover.get("tournament"),
                    match=mover.get("match"),
                    actual=mover.get("actual"),
                    dt_tip=mover.get("draw_total_tip"),
                    dt_pts=mover.get("draw_total_points"),
                    ms_tip=mover.get("market_score_tip"),
                    ms_pts=mover.get("market_score_points"),
                    delta=int(mover.get("delta") or 0),
                    markets=mover.get("markets"),
                )
            )
    return "\n".join(lines)


def variant_table(section: Mapping[str, Any]) -> str:
    lines = [
        (
            "| Variante | Coverage | Spiele | Punkte | Punkte/Spiel | "
            "Delta vs Odds | Delta vs Elo |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in VARIANT_NAMES:
        row = section["variants"][name]
        lines.append(
            (
                "| {name} | {coverage} | {matches} | {points} | {ppm} | "
                "{odds_delta} | {elo_delta} |"
            ).format(
                name=name,
                coverage=format_optional(row.get("coverage")),
                matches=row["matches"],
                points=row["points"],
                ppm=format_optional(row.get("points_per_match")),
                odds_delta=format_optional(row.get("delta_vs_odds_ppm")),
                elo_delta=format_optional(row.get("delta_vs_elo_ppm")),
            )
        )
    return "\n".join(lines)


def differing_matches_table(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "Keine abweichenden Ensemble-vs-Odds-only-Tipps."
    lines = [
        "| Turnier | Spiel | Ergebnis | Ensemble | Odds-only | Delta |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {tournament} | {match} | {actual} | {ensemble_tip} ({ensemble_points}) | "
            "{odds_tip} ({odds_points}) | {delta:+d} |".format(
                tournament=row.get("tournament"),
                match=row.get("match"),
                actual=row.get("actual"),
                ensemble_tip=row.get("ensemble_tip"),
                ensemble_points=row.get("ensemble_points"),
                odds_tip=row.get("odds_tip"),
                odds_points=row.get("odds_points"),
                delta=int(row.get("point_delta") or 0),
            )
        )
    return "\n".join(lines)


def format_optional(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)
