"""Vorhersage-Kern: von Teamstaerke zu Score-Verteilung zu Tipp.

Pipeline je Spiel:
  1. Basis-xG aus Team-Elo/FIFA-Rang (`strength`) plus Spielerqualitaet.
  2. Modifikatoren: Umfeld (`context` -- Hitze, Hoehe, Reise), verletzungs-
     bedingte Ausfaelle (`lineup_absence`), News-Signale (`news`).
  3. Poisson-Score-Matrix, optional Dixon-Coles-korreliert.
  4. Blend mit Marktquoten, sofern vorhanden (`odds`).
  5. Punktoptimaler Tipp je Rundenregelwerk (`scoring`).

Schreibt `data/predictions.json` -- die Datei, aus der Dashboard, Exports
und Live-Auswertung lesen.
"""
from __future__ import annotations

import hashlib
import json as _json
import math
from datetime import datetime, timezone
from typing import Any, Mapping

from .context import context_for_fixture, load_context
from .fixtures import all_teams, load_fixture_payload
from .history import record_prediction_history
from .io import read_json, write_json
from .news import (
    dedupe_model_relevant_news,
    is_model_relevant_news,
    news_for_fixture,
    severity_rank,
    team_news_impact,
)
from .odds import odds_by_match
from .paths import DATA_DIR
from .signal_blend import (
    NEWS_MARKET_VETO_ENABLED,
    guard_contradictory_levers,
    resolve_blend_weight,
    resolve_news_veto,
)
from .scoring import (
    DEFAULT_ROUND_ID,
    ROUND_ORDER,
    best_kicktipp_tip,
    default_rules_payload,
    is_stage_tippable,
    round_rules_payload,
)


DEFAULT_RATING = 1500
# T-0079 (2026-06-12): 0.15 -> 0.20. Blend-Sweep-Optimum auf 342 Backtest-
# Spielen (je Rundenprofil +4 Pkt gegenueber 0.15) + Scoreline-Likelihood
# (T-0078: Markt probabilistisch schaerfer). Betreiber-Entscheid.
ENSEMBLE_MARKET_BLEND_WEIGHT = 0.20
LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT = 0.35
MARKET_SCORE_CALIBRATOR_VERSION = "market_score_v1"
SUPPORTED_MARKET_SCORE_CONSTRAINTS = ("1x2", "over_under", "btts", "handicap")
SCORE_TOTAL_SCALE_MIN = 0.65
SCORE_TOTAL_SCALE_MAX = 1.55
SCORE_TOTAL_SCALE_STEPS = 120
MARKET_CONSTRAINT_ITERATIONS = 80
MARKET_CONSTRAINT_EPSILON = 0.0001


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def load_team_strength() -> dict[str, dict[str, Any]]:
    payload = read_json(DATA_DIR / "team_strength.json", {})
    return payload if isinstance(payload, dict) else {}


def rating_for(team: str, strengths: Mapping[str, Mapping[str, Any]]) -> float:
    try:
        return float(strengths.get(team, {}).get("elo", DEFAULT_RATING))
    except (TypeError, ValueError):
        return DEFAULT_RATING


def numeric_field(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def strength_snapshot(team: str, strengths: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    row = strengths.get(team, {})
    return {
        "attack": row.get("attack"),
        "confederation": row.get("confederation"),
        "elo": row.get("elo", DEFAULT_RATING),
        "fifa_rank": row.get("fifa_rank"),
        "fifa_rank_rating": row.get("fifa_rank_rating"),
        "form_adjustment": row.get("form_adjustment"),
        "qualifier_adjustment": row.get("qualifier_adjustment"),
        "qualifier_status": row.get("qualifier_status"),
        "player_intel": row.get("player_intel"),
        "player_xg_delta": row.get("player_xg_delta"),
        "source_elo": row.get("source_elo"),
        "source_elo_rank": row.get("source_elo_rank"),
    }


def expected_goals(
    fixture: dict[str, Any],
    strengths: Mapping[str, Mapping[str, Any]],
    news_items: list[dict[str, Any]],
    context_payload: Mapping[str, Any],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> tuple[float, float, dict[str, Any]]:
    home = fixture["home_team"]
    away = fixture["away_team"]
    rating_diff = rating_for(home, strengths) - rating_for(away, strengths)
    base = 1.28
    home_xg_base = base * math.exp(rating_diff / 780)
    away_xg_base = base * math.exp(-rating_diff / 780)

    context = context_payload.get("fixtures", {}).get(fixture["match_id"]) or context_for_fixture(fixture)
    advantage = float(context.get("home_advantage_xg") or 0.0)
    heat = context.get("heat_stress") or {}
    home_heat_effect = numeric_field(heat, "home_xg_delta")
    away_heat_effect = numeric_field(heat, "away_xg_delta")
    altitude = context.get("altitude_stress") or {}
    home_altitude_effect = numeric_field(altitude, "home_xg_delta")
    away_altitude_effect = numeric_field(altitude, "away_xg_delta")
    travel = context.get("travel_stress") or {}
    home_travel_effect = numeric_field(travel, "home_xg_delta")
    away_travel_effect = numeric_field(travel, "away_xg_delta")
    prep = context.get("prep_disruption") or {}
    home_prep_effect = numeric_field(prep, "home_xg_delta")
    away_prep_effect = numeric_field(prep, "away_xg_delta")
    # T-0113: bestaetigter XI-Ausfall eines Pool-Schluesselspielers. Eigene
    # Breakdown-Zeile; ohne frische, fuer dieses Spiel erfasste XI fehlt der
    # Eintrag -> Effekt 0 (Frische-Gate in lineup_absence.build_*_index).
    absence = context.get("lineup_absence") or {}
    home_absence_effect = numeric_field(absence, "home_xg_delta")
    away_absence_effect = numeric_field(absence, "away_xg_delta")
    home_player_effect = numeric_field(strengths.get(home, {}), "player_xg_delta")
    away_player_effect = numeric_field(strengths.get(away, {}), "player_xg_delta")
    home_after_context = (
        home_xg_base + advantage + home_heat_effect + home_altitude_effect
        + home_travel_effect + home_prep_effect + home_absence_effect + home_player_effect
    )
    away_after_context = (
        away_xg_base - advantage * 0.45 + away_heat_effect + away_altitude_effect
        + away_travel_effect + away_prep_effect + away_absence_effect + away_player_effect
    )

    home_impact = team_news_impact(home, news_items, player_pool)
    away_impact = team_news_impact(away, news_items, player_pool)
    # defense_delta ist Defizit-Indikator (positiv = schwaechere Verteidigung),
    # daher Plus: schlechtere Defensive auf einer Seite hebt das xG der Gegenseite.
    home_news_effect = home_impact["attack_delta"] + away_impact["defense_delta"] * 0.45
    away_news_effect = away_impact["attack_delta"] + home_impact["defense_delta"] * 0.45

    home_xg_raw = home_after_context + home_news_effect
    away_xg_raw = away_after_context + away_news_effect
    home_xg = clamp(home_xg_raw, 0.25, 3.75)
    away_xg = clamp(away_xg_raw, 0.25, 3.75)

    breakdown = {
        "rating_diff": round(rating_diff, 1),
        "base": base,
        "home": {
            "base_xg": round(home_xg_base, 3),
            "advantage_xg": round(advantage, 3),
            "heat_effect": round(home_heat_effect, 3),
            "altitude_effect": round(home_altitude_effect, 3),
            "travel_effect": round(home_travel_effect, 3),
            "prep_disruption_effect": round(home_prep_effect, 3),
            "lineup_absence_effect": round(home_absence_effect, 3),
            "player_intel_effect": round(home_player_effect, 3),
            "news_effect": round(home_news_effect, 3),
            "raw": round(home_xg_raw, 3),
            "clamped": round(home_xg, 3),
        },
        "away": {
            "base_xg": round(away_xg_base, 3),
            "advantage_xg": round(-advantage * 0.45, 3),
            "heat_effect": round(away_heat_effect, 3),
            "altitude_effect": round(away_altitude_effect, 3),
            "travel_effect": round(away_travel_effect, 3),
            "prep_disruption_effect": round(away_prep_effect, 3),
            "lineup_absence_effect": round(away_absence_effect, 3),
            "player_intel_effect": round(away_player_effect, 3),
            "news_effect": round(away_news_effect, 3),
            "raw": round(away_xg_raw, 3),
            "clamped": round(away_xg, 3),
        },
        "heat_stress": heat,
        "altitude_stress": altitude,
        "travel_stress": travel,
        "prep_disruption": prep,
    }

    return (
        home_xg,
        away_xg,
        {
            "context": context,
            "home_news": home_impact,
            "away_news": away_impact,
            "breakdown": breakdown,
        },
    )


def score_matrix(home_xg: float, away_xg: float, max_goals: int = 6) -> dict[str, float]:
    matrix: dict[str, float] = {}
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            matrix[f"{home_goals}:{away_goals}"] = poisson(home_goals, home_xg) * poisson(away_goals, away_xg)
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def outcome_probabilities(matrix: Mapping[str, float]) -> dict[str, float]:
    probs = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for score, probability in matrix.items():
        home, away = (int(part) for part in score.split(":"))
        if home > away:
            probs["home"] += probability
        elif home < away:
            probs["away"] += probability
        else:
            probs["draw"] += probability
    return probs


def blend_market_probabilities(
    model_probs: Mapping[str, float],
    market_probs: Mapping[str, float] | None,
    weight: float = ENSEMBLE_MARKET_BLEND_WEIGHT,
) -> dict[str, float]:
    if not market_probs:
        return {key: round(float(value), 4) for key, value in model_probs.items()}
    blended = {}
    for outcome in ("home", "draw", "away"):
        blended[outcome] = (1 - weight) * model_probs.get(outcome, 0.0) + weight * market_probs.get(outcome, 0.0)
    total = sum(blended.values())
    return {key: round(value / total, 4) for key, value in blended.items()}


def total_goal_scale_for_target_draw(
    home_xg: float,
    away_xg: float,
    target_draw_probability: float | None,
    *,
    min_scale: float = SCORE_TOTAL_SCALE_MIN,
    max_scale: float = SCORE_TOTAL_SCALE_MAX,
    steps: int = SCORE_TOTAL_SCALE_STEPS,
) -> float:
    if target_draw_probability is None or target_draw_probability <= 0:
        return 1.0
    best_scale = 1.0
    best_error = float("inf")
    for index in range(max(1, steps) + 1):
        scale = min_scale + (max_scale - min_scale) * index / max(1, steps)
        matrix = score_matrix(home_xg * scale, away_xg * scale)
        draw_probability = outcome_probabilities(matrix)["draw"]
        error = abs(draw_probability - target_draw_probability)
        if error < best_error:
            best_error = error
            best_scale = scale
    return best_scale


def market_constraints_from_outcomes(
    target_outcomes: Mapping[str, float],
    *,
    source: str = "1x2",
) -> list[dict[str, Any]]:
    constraints = []
    for outcome in ("home", "draw", "away"):
        if outcome in target_outcomes:
            constraints.append(
                {
                    "id": f"1x2_{outcome}",
                    "kind": "outcome",
                    "outcome": outcome,
                    "target": float(target_outcomes[outcome]),
                    "source": source,
                }
            )
    return constraints


def calibrate_score_matrix(
    matrix: Mapping[str, float],
    target_outcomes: Mapping[str, float],
) -> dict[str, float]:
    current = outcome_probabilities(matrix)
    calibrated: dict[str, float] = {}
    for score, probability in matrix.items():
        home, away = (int(part) for part in score.split(":"))
        outcome = "home" if home > away else "away" if home < away else "draw"
        ratio = target_outcomes.get(outcome, current[outcome]) / max(current[outcome], 0.0001)
        calibrated[score] = probability * ratio
    total = sum(calibrated.values())
    return {score: probability / total for score, probability in calibrated.items()}


# --------------------------------------------------------------------------- #
# T-0103 / H4: conditional Remis-Tilt (CV-gegated, analysis/cv_backtest.py)
# --------------------------------------------------------------------------- #
# Der LOTO-CV-Backtest zeigt: EP-Max tippt remis-nahe Spiele zu selten Remis
# (Modell deckelt die draw-Wkt bei ~0.30, real ~0.35). Ein kleiner FLACHER Tilt
# auf Spiele mit Modell-draw>=TAU kreuzt die EP-Entscheidungsgrenze auf genau
# diesen marginalen Spielen -> robuster Gewinn (in-sample +0.0296 ppm ~+12/405,
# OOS +0.016 ~+6/405; auf delta- UND tau-Achse bestaetigt, Overfit-Gap ~0).
# Klein/geclampt; DRAW_TILT_DELTA=0 schaltet den Tilt komplett aus (Identitaet).
# RETIRED in T-0104 (DELTA=0): H4 war live-inert (0 Flips) UND inkompatibel mit dem
# staerkeren DC-rho -- zusammen -17/405 (DC hebt draw -> mehr Spiele kreuzen tau=0.27 ->
# H4 ueber-tiltet). DC ersetzt H4 (DC-allein +12/405, +3 live-gespielt). Code bleibt
# (delta=0 = no-op), reversibel.
DRAW_TILT_DELTA = 0.0
DRAW_TILT_TAU = 0.27
# T-0104: Dixon-Coles-rho an der QUELLE (dixon_coles_adjust, s.u.). rho<0 hebt 0:0/1:1 und
# senkt 1:0/0:1 in der ROHEN Poisson-Matrix VOR Blend/Kalibrierung. CV-Harness H13: rho=-0.15
# OOS +0.030 (alle 7 Folds, irreduzibel -- H14 uniform-Scale + H15 nur-1:0/0:1 reverten).
# WIRKT ueber die Tor-HOEHE der Favoriten-Tipps (1:0->2:1), NICHT ueber Remis (L9). Echte
# Belief-Korrektur (Standard-Dixon-Coles) -> fliesst bewusst in Anzeige UND Tipp (konsistent).
# Regime-abhaengig: + in torreichen Turnieren, leicht - in torarmen (euro-2016). 0.0 = aus.
DRAW_DC_RHO = -0.15


def conditional_draw_tilt(
    matrix: Mapping[str, float],
    delta: float | None = None,
    tau: float | None = None,
) -> dict[str, float]:
    """H4: hebt die Remis-Wkt um delta NUR wenn sie schon >= tau ist (remis-nahe
    Spiele), senkt Heim/Auswaerts proportional, re-kalibriert die Score-Matrix.
    delta<=0 oder draw<tau -> unveraenderte Matrix. Reiner Tipp-Stage-Transform:
    aendert die Tippwahl, NICHT die angezeigten Modell-Wahrscheinlichkeiten.
    delta/tau=None -> Modul-Defaults zur Laufzeit (toggle-bar fuer Experimente)."""
    delta = DRAW_TILT_DELTA if delta is None else delta
    tau = DRAW_TILT_TAU if tau is None else tau
    if delta <= 0:
        return dict(matrix)
    outcomes = outcome_probabilities(matrix)
    if outcomes["draw"] < tau:
        return dict(matrix)
    boosted = min(0.97, max(0.01, outcomes["draw"] + delta))
    others = [key for key in outcomes if key != "draw"]
    remainder = sum(outcomes[key] for key in others)
    target = {"draw": boosted}
    if remainder > 1e-9:
        scale = (1 - boosted) / remainder
        for key in others:
            target[key] = outcomes[key] * scale
    else:
        for key in others:
            target[key] = (1 - boosted) / 2
    return calibrate_score_matrix(matrix, target)


def dixon_coles_adjust(matrix: Mapping[str, float], rho: float) -> dict[str, float]:
    """Dixon-Coles-Korrektur der vier niedrigen Zellen, danach renormiert. rho<0 hebt
    0:0/1:1 und senkt 1:0/0:1 -> korrigiert die Low-Cell-Fehlanpassung der Unabhaengig-
    keits-Poisson. tau(0,0)=1-lam*mu*rho, tau(0,1)=1+lam*rho, tau(1,0)=1+mu*rho,
    tau(1,1)=1-rho (lam/mu = erwartete Tore je Team aus den Matrix-Randsummen). rho=0 ->
    Identitaet. T-0104/H13: at-source (vor Blend) ist der staerkste Backtest-Hebel."""
    if rho == 0.0:
        return dict(matrix)
    lam = sum(int(label.split(":")[0]) * probability for label, probability in matrix.items())
    mu = sum(int(label.split(":")[1]) * probability for label, probability in matrix.items())
    tau = {
        "0:0": 1.0 - lam * mu * rho,
        "0:1": 1.0 + lam * rho,
        "1:0": 1.0 + mu * rho,
        "1:1": 1.0 - rho,
    }
    adjusted = {label: max(0.0, probability * tau.get(label, 1.0)) for label, probability in matrix.items()}
    total = sum(adjusted.values()) or 1.0
    return {label: probability / total for label, probability in adjusted.items()}


def _score_parts(score: str) -> tuple[int, int]:
    home, away = (int(part) for part in score.split(":"))
    return home, away


def _constraint_matches_score(score: str, constraint: Mapping[str, Any]) -> bool:
    home, away = _score_parts(score)
    kind = constraint.get("kind")
    if kind == "outcome":
        outcome = "home" if home > away else "away" if home < away else "draw"
        return outcome == constraint.get("outcome")
    if kind == "total_goals":
        total_goals = home + away
        line = float(constraint.get("line", 2.5))
        side = constraint.get("side", "over")
        return total_goals > line if side == "over" else total_goals < line
    if kind == "btts":
        yes = home > 0 and away > 0
        return yes if constraint.get("side", "yes") == "yes" else not yes
    if kind == "handicap":
        team = constraint.get("team", "home")
        line = float(constraint.get("line", 0.0))
        if team == "away":
            cover = away + line > home
        else:
            cover = home + line > away
        return cover if constraint.get("side", "cover") == "cover" else not cover
    return False


def market_constraint_probability(
    matrix: Mapping[str, float],
    constraint: Mapping[str, Any],
) -> float:
    return sum(
        probability
        for score, probability in matrix.items()
        if _constraint_matches_score(score, constraint)
    )


def _complete_outcome_constraints(constraints: list[Mapping[str, Any]]) -> dict[str, float] | None:
    if len(constraints) != 3:
        return None
    outcomes = {}
    for constraint in constraints:
        if constraint.get("kind") != "outcome":
            return None
        outcome = constraint.get("outcome")
        if outcome not in {"home", "draw", "away"}:
            return None
        outcomes[str(outcome)] = float(constraint.get("target", 0.0))
    if set(outcomes) != {"home", "draw", "away"}:
        return None
    return outcomes


def _normalize_matrix(matrix: Mapping[str, float]) -> dict[str, float]:
    total = sum(float(value) for value in matrix.values())
    if total <= 0:
        return {score: 0.0 for score in matrix}
    return {score: float(probability) / total for score, probability in matrix.items()}


def calibrate_score_matrix_to_market_constraints(
    matrix: Mapping[str, float],
    constraints: list[Mapping[str, Any]],
    *,
    iterations: int = MARKET_CONSTRAINT_ITERATIONS,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not constraints:
        normalized = _normalize_matrix(matrix)
        return normalized, {"iterations": 0, "constraints": [], "max_error": 0.0}

    outcome_targets = _complete_outcome_constraints(constraints)
    if outcome_targets is not None:
        calibrated = calibrate_score_matrix(matrix, outcome_targets)
        fit = [
            {
                "id": constraint.get("id"),
                "kind": constraint.get("kind"),
                "target": round(float(constraint.get("target", 0.0)), 4),
                "actual": round(market_constraint_probability(calibrated, constraint), 4),
                "error": 0.0,
            }
            for constraint in constraints
        ]
        return calibrated, {"iterations": 1, "constraints": fit, "max_error": 0.0}

    calibrated = _normalize_matrix(matrix)
    for _ in range(max(1, iterations)):
        for constraint in constraints:
            target = clamp(float(constraint.get("target", 0.0)), MARKET_CONSTRAINT_EPSILON, 1 - MARKET_CONSTRAINT_EPSILON)
            current = clamp(
                market_constraint_probability(calibrated, constraint),
                MARKET_CONSTRAINT_EPSILON,
                1 - MARKET_CONSTRAINT_EPSILON,
            )
            true_factor = target / current
            false_factor = (1 - target) / (1 - current)
            adjusted = {}
            for score, probability in calibrated.items():
                factor = true_factor if _constraint_matches_score(score, constraint) else false_factor
                adjusted[score] = probability * factor
            calibrated = _normalize_matrix(adjusted)

    fit = []
    max_error = 0.0
    for constraint in constraints:
        target = float(constraint.get("target", 0.0))
        actual = market_constraint_probability(calibrated, constraint)
        error = abs(actual - target)
        max_error = max(max_error, error)
        fit.append(
            {
                "id": constraint.get("id"),
                "kind": constraint.get("kind"),
                "target": round(target, 4),
                "actual": round(actual, 4),
                "error": round(error, 4),
            }
        )
    return calibrated, {
        "iterations": max(1, iterations),
        "constraints": fit,
        "max_error": round(max_error, 4),
    }


def _is_goal_shape_constraint(constraint: Mapping[str, Any]) -> bool:
    kind = constraint.get("kind")
    if kind in {"total_goals", "btts", "handicap"}:
        return True
    return kind == "outcome" and constraint.get("outcome") == "draw"


def total_goal_scale_for_market_constraints(
    home_xg: float,
    away_xg: float,
    constraints: list[Mapping[str, Any]],
    *,
    min_scale: float = SCORE_TOTAL_SCALE_MIN,
    max_scale: float = SCORE_TOTAL_SCALE_MAX,
    steps: int = SCORE_TOTAL_SCALE_STEPS,
) -> float:
    shape_constraints = [
        constraint for constraint in constraints
        if _is_goal_shape_constraint(constraint)
    ]
    if not shape_constraints:
        return 1.0
    best_scale = 1.0
    best_error = float("inf")
    for index in range(max(1, steps) + 1):
        scale = min_scale + (max_scale - min_scale) * index / max(1, steps)
        matrix = score_matrix(home_xg * scale, away_xg * scale)
        error = 0.0
        for constraint in shape_constraints:
            target = float(constraint.get("target", 0.0))
            actual = market_constraint_probability(matrix, constraint)
            weight = float(constraint.get("weight", 1.0))
            error += weight * (actual - target) ** 2
        if error < best_error:
            best_error = error
            best_scale = scale
    return best_scale


def calibrate_score_matrix_from_xg(
    home_xg: float,
    away_xg: float,
    target_outcomes: Mapping[str, float],
    *,
    total_mode: str = "base",
    market_constraints: list[Mapping[str, Any]] | None = None,
) -> tuple[dict[str, float], dict[str, Any]]:
    constraints = list(market_constraints or market_constraints_from_outcomes(target_outcomes))
    scale = 1.0
    if total_mode == "draw_target":
        scale = total_goal_scale_for_target_draw(
            home_xg,
            away_xg,
            float(target_outcomes.get("draw", 0.0) or 0.0),
        )
    elif total_mode == "market_constraints":
        scale = total_goal_scale_for_market_constraints(home_xg, away_xg, constraints)
    matrix = score_matrix(home_xg * scale, away_xg * scale)
    calibrated, fit = calibrate_score_matrix_to_market_constraints(matrix, constraints)
    return calibrated, {
        "calibrator": MARKET_SCORE_CALIBRATOR_VERSION,
        "total_mode": total_mode,
        "total_scale": round(scale, 4),
        "base_total_xg": round(home_xg + away_xg, 3),
        "calibrated_total_xg": round((home_xg + away_xg) * scale, 3),
        "target_draw_probability": round(float(target_outcomes.get("draw", 0.0) or 0.0), 4),
        "supported_constraints": list(SUPPORTED_MARKET_SCORE_CONSTRAINTS),
        "active_constraints": [
            str(constraint.get("id") or constraint.get("kind"))
            for constraint in constraints
        ],
        "constraint_fit": fit,
    }


def hours_until_kickoff(fixture: Mapping[str, Any], now: datetime | None = None) -> float | None:
    kickoff_text = fixture.get("kickoff_utc")
    if not kickoff_text:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        kickoff = datetime.fromisoformat(str(kickoff_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (kickoff - now).total_seconds() / 3600


def stability_for(
    fixture: Mapping[str, Any],
    fixture_news: list[dict[str, Any]],
    details: Mapping[str, Any],
) -> str:
    model_news = [
        item
        for item in fixture_news
        if item.get("freshness") != "stale" and is_model_relevant_news(item)
    ]
    critical = sum(1 for item in model_news if item.get("severity") == "critical")
    important = sum(1 for item in model_news if item.get("severity") == "important")
    lineup_known = details["home_news"]["lineup_confirmed"] and details["away_news"]["lineup_confirmed"]
    if critical:
        return "volatil"
    hours_left = hours_until_kickoff(fixture)
    if important:
        return "volatil" if hours_left is not None and hours_left <= 48 else "stabil"
    if hours_left is not None and hours_left <= 48 and not lineup_known:
        return "warte auf Lineup"
    return "stabil"


def top_scores(matrix: Mapping[str, float], limit: int = 6) -> list[dict[str, Any]]:
    return [
        {"score": score, "probability": round(probability, 4)}
        for score, probability in sorted(matrix.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def explanation(
    fixture: dict[str, Any],
    outcome_probs: Mapping[str, float],
    fixture_news: list[dict[str, Any]],
    context: Mapping[str, Any],
    odds_item: Mapping[str, Any] | None,
    strengths: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    home = fixture["home_team"]
    away = fixture["away_team"]
    likely = max(outcome_probs, key=lambda key: outcome_probs[key])
    labels = {"home": home, "draw": "Remis", "away": away}
    rows = [f"Grundsignal favorisiert {labels[likely]} ({outcome_probs[likely]:.0%})."]
    if odds_item:
        source_count = odds_item.get("source_count")
        if source_count and source_count > 1:
            rows.append(
                f"Quotenkonsens aus {source_count} Quellen wurde no-vig kalibriert "
                f"und mit {ENSEMBLE_MARKET_BLEND_WEIGHT:.0%} Gewicht beigemischt."
            )
        else:
            rows.append(
                f"Quotenquelle {odds_item.get('source')} wurde no-vig kalibriert "
                f"und mit {ENSEMBLE_MARKET_BLEND_WEIGHT:.0%} Gewicht beigemischt."
            )
    if context.get("flags"):
        rows.append("Kontext-Flags: " + ", ".join(context["flags"]) + ".")
    heat = context.get("heat_stress") or {}
    home_heat_delta = numeric_field(heat, "home_xg_delta")
    away_heat_delta = numeric_field(heat, "away_xg_delta")
    if heat.get("risk") in {"elevated", "moderate", "high"} or heat.get("ambient_risk") in {"moderate", "high"}:
        rows.append(
            "Heat-Stress "
            f"{heat.get('risk', 'unknown')}: WBGT effektiv {heat.get('effective_wbgt_c', 'n/a')}C "
            f"(ambient {heat.get('estimated_wbgt_c', 'n/a')}C), "
            f"xG-Effekt {home} {home_heat_delta:+.3f}, "
            f"{away} {away_heat_delta:+.3f}."
        )
    strengths = strengths or {}
    home_player_delta = numeric_field(strengths.get(home, {}), "player_xg_delta")
    away_player_delta = numeric_field(strengths.get(away, {}), "player_xg_delta")
    if abs(home_player_delta) >= 0.01 or abs(away_player_delta) >= 0.01:
        rows.append(
            "Player-Intel-Proxy: "
            f"{home} {home_player_delta:+.3f} xG, "
            f"{away} {away_player_delta:+.3f} xG."
        )
    major_news = [
        item
        for item in fixture_news
        if severity_rank(item.get("severity", "noise")) >= 2
        and is_model_relevant_news(item)
    ]
    major_news = dedupe_model_relevant_news([home, away], major_news)
    if major_news:
        rows.append(f"{len(major_news)} wichtige News-Meldung(en) vor Tippabgabe pruefen.")
    return rows


def predict_fixture(
    fixture: dict[str, Any],
    strengths: Mapping[str, Mapping[str, Any]],
    all_news: list[dict[str, Any]],
    odds_lookup: Mapping[str, Mapping[str, Any]],
    context_payload: Mapping[str, Any],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    fixture_news = news_for_fixture(fixture, all_news)
    home_xg, away_xg, details = expected_goals(fixture, strengths, fixture_news, context_payload, player_pool)
    matrix = score_matrix(home_xg, away_xg)
    if DRAW_DC_RHO:
        matrix = dixon_coles_adjust(matrix, DRAW_DC_RHO)  # T-0104/H13: Belief-Korrektur
    model_outcomes = outcome_probabilities(matrix)
    odds_item = odds_lookup.get(fixture["match_id"])
    market_probs = (odds_item or {}).get("probabilities")

    # T-0144 (forward-gated, default AUS): verwirft den News-Effekt, wenn ER es ist,
    # der den Modell-Favoriten gegen einen klaren Marktfavoriten dreht. Live gemessen
    # kosten genau diese Flips -2.10 Pkt/Stueck. No-Op, solange
    # signal_blend.NEWS_MARKET_VETO_ENABLED False ist -- dann faellt auch die
    # zusaetzliche score_matrix weg. KONTRAER zu T-0136 (siehe guard).
    guard_contradictory_levers()
    news_veto_info: dict[str, Any] = {"applied": False}
    breakdown = details.get("breakdown") or {}
    if NEWS_MARKET_VETO_ENABLED and market_probs:
        home_news = float((breakdown.get("home") or {}).get("news_effect") or 0.0)
        away_news = float((breakdown.get("away") or {}).get("news_effect") or 0.0)
        if home_news or away_news:
            home_xg_no_news = clamp(home_xg - home_news, 0.25, 3.75)
            away_xg_no_news = clamp(away_xg - away_news, 0.25, 3.75)
            matrix_no_news = score_matrix(home_xg_no_news, away_xg_no_news)
            if DRAW_DC_RHO:
                matrix_no_news = dixon_coles_adjust(matrix_no_news, DRAW_DC_RHO)
            outcomes_no_news = outcome_probabilities(matrix_no_news)
            veto, news_veto_info = resolve_news_veto(
                model_outcomes, outcomes_no_news, market_probs, breakdown
            )
            if veto:
                home_xg, away_xg = home_xg_no_news, away_xg_no_news
                matrix, model_outcomes = matrix_no_news, outcomes_no_news
    if news_veto_info.get("applied"):
        breakdown["news_veto"] = news_veto_info

    # T-0136 (forward-gated, default AUS): senkt das Markt-Gewicht NUR fuer dieses
    # Spiel, wenn die Modell-Gegenposition zum Markt signal-getrieben ist. No-Op,
    # solange signal_blend.SIGNAL_AWARE_BLEND_ENABLED False ist.
    blend_weight, signal_blend_info = resolve_blend_weight(
        model_outcomes,
        market_probs,
        details.get("breakdown"),
        base_weight=ENSEMBLE_MARKET_BLEND_WEIGHT,
    )
    if signal_blend_info.get("applied"):
        details["breakdown"]["signal_blend"] = signal_blend_info
    blended_outcomes = blend_market_probabilities(
        model_outcomes,
        market_probs,
        weight=blend_weight,
    )
    score_constraints = market_constraints_from_outcomes(blended_outcomes)
    calibrated_matrix, score_fit = calibrate_score_matrix_to_market_constraints(
        matrix,
        score_constraints,
    )
    stage = fixture.get("stage", "group")
    # T-0103/H4: kleiner conditional Remis-Tilt NUR fuer die Tippwahl -- die
    # angezeigten Wahrscheinlichkeiten/top_scores bleiben Modell-ehrlich.
    tip_matrix = conditional_draw_tilt(calibrated_matrix)
    round_tips = {
        round_id: best_kicktipp_tip(tip_matrix, stage, round_id=round_id)
        for round_id in ROUND_ORDER
        if is_stage_tippable(stage, round_id)
    }
    best_tip = round_tips.get(DEFAULT_ROUND_ID) or next(iter(round_tips.values()), {})
    return {
        "match_id": fixture["match_id"],
        "fixture": fixture,
        "xg": {"home": round(home_xg, 3), "away": round(away_xg, 3)},
        "probabilities": {
            "model": {key: round(value, 4) for key, value in model_outcomes.items()},
            "blended": blended_outcomes,
        },
        "top_scores": top_scores(calibrated_matrix, limit=12),
        "xg_breakdown": details["breakdown"],
        "score_calibration": {
            "calibrator": MARKET_SCORE_CALIBRATOR_VERSION,
            "market_blend_weight": ENSEMBLE_MARKET_BLEND_WEIGHT,
            "legacy_market_blend_weight": LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT,
            "score_shape": "outcome_class_calibration",
            "odds_only_score_shape": "draw_target_total_xg",
            "supported_extra_constraints": list(SUPPORTED_MARKET_SCORE_CONSTRAINTS[1:]),
            "active_extra_constraints": [],
            "activation_status": "1x2_only; Zusatzmaerkte noch nicht im historischen Backtest.",
            "constraint_fit": score_fit,
        },
        "recommended_tip": best_tip,
        "round_tips": round_tips,
        "stability": stability_for(fixture, fixture_news, details),
        "news": fixture_news[:8],
        "context": details["context"],
        "strength": {
            "home": strength_snapshot(fixture["home_team"], strengths),
            "away": strength_snapshot(fixture["away_team"], strengths),
        },
        "odds": odds_item,
        "explanation": explanation(fixture, blended_outcomes, fixture_news, details["context"], odds_item, strengths),
    }


def _bootstrap_qualified_teams(
    teams: list[str],
    strengths: Mapping[str, Mapping[str, Any]],
    target: int = 32,
) -> list[str]:
    """Top-Teams nach model_elo als Bootstrap-Bracket-Teilnehmer.

    Trimmt zur naechsten Potenz von 2, damit simulate_bracket es nehmen kann.
    Echte Gruppen-Tabellen-Logik (Sieger/Zweiter pro Gruppe etc.) folgt in
    einem spaeteren Refactor.
    """
    ordered = sorted(teams, key=lambda team: rating_for(team, strengths), reverse=True)
    qualified = ordered[:target]
    while qualified and (len(qualified) & (len(qualified) - 1)) != 0:
        qualified = qualified[:-1]
    return qualified


def build_bonus_predictions(
    teams: list[str],
    strengths: Mapping[str, Mapping[str, Any]],
    markets: list[dict[str, Any]],
    *,
    n_simulations: int = 5000,
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
    fixture_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from .knockout import simulate_bracket, simulate_tournament
    from .topscorer import team_topscorer_probabilities

    futures_by_category: dict[str, dict[str, dict[str, Any]]] = {}
    for item in markets:
        category = item.get("category")
        outcome = item.get("outcome")
        if (
            category in {"world_champion", "semifinalist", "top_scorer_team"}
            and outcome
            and item.get("probability") is not None
            and (item.get("quality") or {}).get("status") == "usable"
        ):
            futures_by_category.setdefault(str(category), {})[str(outcome)] = item

    qualified: list[str] = []
    group_winner_probs: dict[str, dict[str, float]] = {}
    used_tournament_path = False
    if fixture_payload and fixture_payload.get("fixtures"):
        tournament = simulate_tournament(fixture_payload, strengths, n_simulations=n_simulations)
        if tournament:
            champion_probs = tournament.get("champion", {})
            semi_probs = tournament.get("semi", {})
            group_winner_probs = tournament.get("group_winners", {})
            # qualified_pool: Teams mit nicht-trivialer round_of_32-Rate.
            qualified_pool = tournament.get("round_of_32", {})
            qualified = sorted(qualified_pool, key=lambda t: -qualified_pool.get(t, 0.0))[:32]
            used_tournament_path = True
    if not used_tournament_path:
        qualified = _bootstrap_qualified_teams(teams, strengths)
        if qualified:
            bracket = simulate_bracket(qualified, strengths, n_simulations=n_simulations)
            champion_probs = bracket.get("champion", {})
            semi_probs = bracket.get("semi", {})
        else:
            champion_probs = {}
            semi_probs = {}

    if player_pool is None:
        pool_payload = read_json(DATA_DIR / "player_pool.json", {"players": {}})
        player_pool = pool_payload.get("players", {}) if isinstance(pool_payload, dict) else {}
    expected_team_goals = {
        team: float(strengths.get(team, {}).get("attack", 1.0)) for team in teams
    }
    topscorer_probs = team_topscorer_probabilities(teams, player_pool, expected_team_goals)

    def _market_prob(category: str, team: str) -> float | None:
        item = futures_by_category.get(category, {}).get(team)
        if not item or item.get("probability") is None:
            return None
        try:
            return float(item["probability"])
        except (TypeError, ValueError):
            return None

    champion = sorted(
        [
            {
                "team": team,
                "probability": round(champion_probs.get(team, 0.0), 4),
                "market_probability": _market_prob("world_champion", team),
            }
            for team in teams
        ],
        key=lambda row: -row["probability"],
    )
    semifinalists = sorted(
        [
            {
                "team": team,
                "probability": round(semi_probs.get(team, 0.0), 4),
                "market_probability": _market_prob("semifinalist", team),
            }
            for team in teams
        ],
        key=lambda row: -row["probability"],
    )
    top_scorer_team = sorted(
        [
            {
                "team": team,
                "probability": topscorer_probs.get(team, 0.0),
                "market_probability": _market_prob("top_scorer_team", team),
            }
            for team in teams
        ],
        key=lambda row: -row["probability"],
    )
    group_winners = {
        group: sorted(
            [
                {
                    "team": team,
                    "probability": round(probability, 4),
                    "market_probability": None,
                }
                for team, probability in teams_probs.items()
            ],
            key=lambda row: -row["probability"],
        )[:6]
        for group, teams_probs in sorted(group_winner_probs.items())
    }
    return {
        "world_champion": champion[:12],
        "semifinalists": semifinalists[:16],
        "group_winners": group_winners,
        "top_scorer_team": top_scorer_team[:12],
        "qualified_pool": qualified,
    }


def _content_signature(payload: Any) -> str:
    encoded = _json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()[:12]


def build_predictions() -> dict[str, Any]:
    previous_payload = read_json(DATA_DIR / "predictions.json", {"predictions": [], "bonus": {}})
    fixtures_payload = load_fixture_payload()
    fixtures = fixtures_payload.get("fixtures", [])
    prediction_fixtures = [
        fixture
        for fixture in fixtures
        if not fixture.get("has_pending_slot") and fixture.get("status") != "slot_pending"
    ]
    strengths = load_team_strength()
    market_payload = read_json(DATA_DIR / "market_signals.json", {"odds": [], "markets": []})
    news_payload = read_json(DATA_DIR / "news_items.json", {"items": []})
    context_payload = load_context()
    odds_lookup = odds_by_match(market_payload.get("odds", []))
    player_pool_payload = read_json(DATA_DIR / "player_pool.json", {"players": {}})
    player_pool = (player_pool_payload or {}).get("players", {}) if isinstance(player_pool_payload, dict) else {}
    # T-0040-role-data: role aus echten Aufstellungen (manuelle Datei +
    # confirmed/expected-Lineup-News) ueberschreibt die Heuristik in-memory.
    # Ab Turnierstart liefern echte XIs die Startelf-Wahrheit; vorher leer.
    from .lineup_roles import apply_lineup_roles

    lineup_role_summary = apply_lineup_roles(player_pool, news_payload.get("items", []))
    # T-0066: Einreise-/Prep-Stoerung (manuell + News) als eigener
    # Kontext-Effekt in den Payload mergen (eigene Breakdown-Zeile).
    from .prep_disruption import build_prep_disruption_index, context_entry

    prep_index = build_prep_disruption_index(
        prediction_fixtures, news_payload.get("items", []), player_pool=player_pool
    )
    if prep_index:
        fixtures_by_id = {fx["match_id"]: fx for fx in prediction_fixtures}
        ctx_fixtures = context_payload.setdefault("fixtures", {})
        for match_id, row in prep_index.items():
            if match_id not in ctx_fixtures:
                ctx_fixtures[match_id] = context_for_fixture(fixtures_by_id[match_id])
            ctx_fixtures[match_id]["prep_disruption"] = context_entry(row)
    # T-0113: XI-Ausfall-xG-Malus (forward-gated; Index leer ohne frische,
    # spiel-spezifische XI). Liest bestaetigte XIs + XI<->Spiel-Linkage,
    # injiziert pro Spiel eine lineup_absence-Kontextzeile (analog prep_disruption).
    from .lineup_absence import build_lineup_absence_index

    absence_index = build_lineup_absence_index(
        prediction_fixtures,
        player_pool,
        read_json(DATA_DIR / "manual_lineups.json", {}),
        news_payload.get("items", []),
    )
    if absence_index:
        fixtures_by_id = {fx["match_id"]: fx for fx in prediction_fixtures}
        ctx_fixtures = context_payload.setdefault("fixtures", {})
        for match_id, row in absence_index.items():
            if match_id not in ctx_fixtures:
                ctx_fixtures[match_id] = context_for_fixture(fixtures_by_id[match_id])
            ctx_fixtures[match_id]["lineup_absence"] = row
    predictions = [
        predict_fixture(fixture, strengths, news_payload.get("items", []), odds_lookup, context_payload, player_pool)
        for fixture in prediction_fixtures
    ]
    teams = all_teams(fixtures_payload)
    bonus = build_bonus_predictions(
        teams,
        strengths,
        market_payload.get("markets", []),
        player_pool=player_pool,
        fixture_payload=fixtures_payload,
    )
    inputs_signature = {
        "strengths": _content_signature(strengths),
        "player_pool": _content_signature(player_pool),
        "markets": _content_signature(market_payload.get("markets", [])),
        "news": _content_signature([item.get("id") for item in news_payload.get("items", [])]),
    }
    previous_signature = previous_payload.get("inputs_signature") or {}
    changed_inputs = [
        key for key, value in inputs_signature.items() if previous_signature.get(key) != value
    ]
    # Beim ersten Build (kein previous) ist alles "neu" -- nicht als Trigger zaehlen.
    if not previous_signature:
        changed_inputs = []

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "default_round_id": DEFAULT_ROUND_ID,
        "rules": default_rules_payload(),
        "rounds": round_rules_payload(),
        "score_calibration": {
            "calibrator": MARKET_SCORE_CALIBRATOR_VERSION,
            "market_blend_weight": ENSEMBLE_MARKET_BLEND_WEIGHT,
            "legacy_market_blend_weight": LEGACY_ENSEMBLE_MARKET_BLEND_WEIGHT,
            "odds_only_score_shape": "draw_target_total_xg",
            "supported_extra_constraints": list(SUPPORTED_MARKET_SCORE_CONSTRAINTS[1:]),
            "active_extra_constraints": [],
            "backtest_scope": "WM 2010/2014/2018/2022 via backtest-report",
        },
        "predictions": predictions,
        "bonus": bonus,
        "lineup_roles": lineup_role_summary,
        "inputs_signature": inputs_signature,
    }
    history = record_prediction_history(
        previous_payload.get("predictions", []),
        predictions,
        previous_bonus=previous_payload.get("bonus") or {},
        current_bonus=bonus,
        changed_inputs=changed_inputs,
    )
    payload["history_events"] = len(history.get("events", []))
    # T-0081: Pre-Kickoff-Tipps einfrieren (vor Anstoss aktualisieren, ab
    # Anstoss eingefroren) -- eval_live wertet den getippten, nicht den
    # nachtraeglich neu gerechneten Stand.
    from .tip_snapshots import update_tip_snapshots

    update_tip_snapshots(predictions)
    write_json(DATA_DIR / "predictions.json", payload)
    return payload
