"""Gated Live-Kalibrierung (Codex-Roadmap #3 + #4).

Beide Frameworks sind ADVISORY und GATED: sie messen, empfehlen, aber
veraendern das Modell NIE automatisch. Aktivierung erst ab genug
gespielten Spielen (aktuell zu wenig -> inert), und λ-Skalierung
zusaetzlich erst nach Backtest-Gegencheck (stehende Regel). So schuetzen
wir uns vor Overfit auf Turnier-Rauschen.

#3 signal_calibration: pro Modell-Signal (heat/altitude/travel/prep/news/
   player_intel) messen, ob Spiele, in denen das Signal feuerte, schlechter
   kalibriert sind (Brier). Bei klarer Verschlechterung ueber >=N Feuerungen
   -> Empfehlung 'halbieren/pruefen' (nicht automatisch).
#3b signal_points_calibration (T-0076, 2026-07-10): dasselbe je Signal, aber
   auf der REALISIERTEN PUNKTE-Metrik (dPkt der Tipp-Flips aus der Kontext-
   Ablation gegen die echten Ergebnisse). Noetig, weil der Brier-Gate blind
   ist: `news` hatte den BESSEREN fired_brier und trotzdem klar negatives
   dPkt. Stehende Lehre: nur die Punkt-Metrik gatet, nicht Brier/Loglik.
#4 totals_adjustment: Turnier-Torlevel (tatsaechliche vs erwartete Tore)
   -> geshrinkte λ-Multiplikator-Empfehlung (Richtung 1.0), gated.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .scoring import Score, actual_for_round, kicktipp_points

_OUTCOMES = ("home", "draw", "away")
SIGNAL_EFFECTS = {
    "heat": "heat_effect",
    "altitude": "altitude_effect",
    "travel": "travel_effect",
    "prep": "prep_disruption_effect",
    "news": "news_effect",
    "player_intel": "player_intel_effect",
}


def _outcome(actual: Any) -> str | None:
    if not actual or len(actual) < 2:
        return None
    h, a = actual[0], actual[1]
    return "home" if h > a else "away" if a > h else "draw"


def _brier(probs: Mapping[str, Any], outcome: str) -> float | None:
    if not probs or any(probs.get(o) is None for o in _OUTCOMES):
        return None
    return sum((float(probs[o]) - (1.0 if o == outcome else 0.0)) ** 2 for o in _OUTCOMES)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _fired(breakdown: Mapping[str, Any], effect_key: str) -> bool:
    for side in ("home", "away"):
        value = (breakdown.get(side) or {}).get(effect_key)
        if value not in (None, 0, 0.0):
            return True
    return False


def signal_calibration(
    predictions: Iterable[Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
    *,
    min_firings: int = 10,
    worse_ratio: float = 1.15,
) -> dict[str, Any]:
    played: list[tuple[Mapping[str, Any], str]] = []
    for pred in predictions:
        res = results.get(pred.get("match_id"))
        if not res:
            continue
        outcome = _outcome(res.get("actual"))
        blended = (pred.get("probabilities") or {}).get("blended")
        if outcome and blended:
            played.append((pred, outcome))
    overall = _mean([b for b in (_brier((p.get("probabilities") or {}).get("blended"), o) for p, o in played) if b is not None])

    signals: list[dict[str, Any]] = []
    for name, key in SIGNAL_EFFECTS.items():
        fired = [(p, o) for p, o in played if _fired(p.get("xg_breakdown") or {}, key)]
        n = len(fired)
        entry: dict[str, Any] = {"signal": name, "firings": n, "min_firings": min_firings, "multiplier": 1.0}
        if n < min_firings:
            entry.update(status="insufficient_data", recommendation="keep")
        else:
            fired_brier = _mean([b for b in (_brier((p.get("probabilities") or {}).get("blended"), o) for p, o in fired) if b is not None])
            entry["fired_brier"] = fired_brier
            entry["overall_brier"] = overall
            if overall and fired_brier and fired_brier > overall * worse_ratio:
                entry.update(status="review", recommendation="halve")
            else:
                entry.update(status="ok", recommendation="keep")
        signals.append(entry)
    return {
        "played_with_result": len(played),
        "overall_brier": overall,
        "min_firings": min_firings,
        "signals": signals,
        "note": "Advisory + gated: Empfehlungen werden NICHT automatisch angewendet (human-in-the-loop).",
    }


def _parse_tip(label: Any) -> Score | None:
    try:
        home, away = str(label).split(":")
        return Score(int(home), int(away))
    except (ValueError, AttributeError):
        return None


def signal_points_calibration(
    ablation: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    stages: Mapping[str, str],
    *,
    min_flips: int = 10,
) -> dict[str, Any]:
    """dPkt-Gate (T-0076): realisierter Punkte-Delta je Signal.

    Punktet die von der Kontext-Ablation gemeldeten Tipp-Flips
    (`with_effect_tip` vs `without_effect_tip`) gegen die echten Ergebnisse:
    ``dPkt = Punkte(mit Effekt) - Punkte(ohne Effekt)``, kumulativ je Signal
    und je Runde (Pool-Regeln via `kicktipp_points`/`actual_for_round`).

    Kumuliertes dPkt < 0 ueber >= `min_flips` gewertete Flips -> Empfehlung
    'halve'. Advisory, kein Auto-Apply.
    """
    by_key = {effect: signal for signal, effect in SIGNAL_EFFECTS.items()}
    signals: list[dict[str, Any]] = []
    for effect in ablation.get("effects") or []:
        key = str(effect.get("effect") or "")
        flips = effect.get("changed_fixtures") or []
        dpkt = 0
        scored = 0
        per_round: dict[str, int] = {}
        for flip in flips:
            match_id = flip.get("match_id")
            round_id = flip.get("round_id")
            res = results.get(match_id) or {}
            actual = res.get("actual")
            if not round_id or not actual or len(actual) < 2:
                continue
            tip_with = _parse_tip(flip.get("with_effect_tip"))
            tip_without = _parse_tip(flip.get("without_effect_tip"))
            if tip_with is None or tip_without is None:
                continue
            stage = stages.get(match_id, "group")
            scored_actual = actual_for_round(
                actual, res.get("penalty_winner"), round_id, res.get("shootout")
            )
            delta = kicktipp_points(tip_with, scored_actual, stage, round_id) - kicktipp_points(
                tip_without, scored_actual, stage, round_id
            )
            dpkt += delta
            per_round[round_id] = per_round.get(round_id, 0) + delta
            scored += 1

        entry: dict[str, Any] = {
            "signal": by_key.get(key, key),
            "flips_total": len(flips),
            "flips_scored": scored,
            "min_flips": min_flips,
            "dpkt": dpkt,
            "dpkt_per_round": per_round,
            "multiplier": 1.0,
        }
        if scored < min_flips:
            entry.update(status="insufficient_data", recommendation="keep")
        elif dpkt < 0:
            entry.update(status="review", recommendation="halve")
        else:
            entry.update(status="ok", recommendation="keep")
        signals.append(entry)

    return {
        "metric": "realized_kicktipp_points",
        "min_flips": min_flips,
        "signals": signals,
        "note": (
            "Punkte-Gate (dPkt) statt Brier -- Brier ist blind fuer den Punkte-"
            "Schaden. Advisory + gated, kein Auto-Apply."
        ),
    }


def totals_adjustment(
    predictions: Iterable[Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
    *,
    min_matches: int = 15,
    prior_weight: float = 20.0,
) -> dict[str, Any]:
    expected = 0.0
    actual = 0.0
    n = 0
    for pred in predictions:
        res = results.get(pred.get("match_id"))
        xg = pred.get("xg") or {}
        if not res or xg.get("home") is None or xg.get("away") is None:
            continue
        act = res.get("actual")
        if not act or len(act) < 2:
            continue
        expected += float(xg["home"]) + float(xg["away"])
        actual += float(act[0]) + float(act[1])
        n += 1
    ratio = round(actual / expected, 4) if expected else None
    weight = n / (n + prior_weight) if n else 0.0
    recommended = round(1 + (ratio - 1) * weight, 4) if ratio is not None else None
    status = "active" if n >= min_matches else "insufficient_data"
    return {
        "matches": n,
        "min_matches": min_matches,
        "expected_goals": round(expected, 2),
        "actual_goals": round(actual, 2),
        "ratio": ratio,
        "shrink_weight": round(weight, 3),
        "recommended_multiplier": recommended,
        "applied_multiplier": 1.0,
        "status": status,
        "note": (
            "Empfehlung NICHT angewendet. λ-Skalierung erst nach Backtest-"
            "Gegencheck (stehende Regel) UND n>=min_matches."
        ),
    }
