"""T-0040+/Codex-Punkt 5: Per-Signal-Ablation der Kontext-Effekte.

Misst fuer die aktuellen Live-Predictions, wie stark jeder kleine,
geclampte Kontext-Effekt (Heat/WBGT, Hoehe, Reise, Player-Intel,
Spieler-News) den Tipp wirklich bewegt -- also "haelt es oder erklaert
es nur schoen". Nutzt den schon in `predictions.json` gespeicherten
`xg_breakdown`, entfernt je Effekt dessen xG-Delta und rechnet den Tipp
ueber denselben Pfad neu (score_matrix -> Markt-Blend -> Kalibrierung ->
best_kicktipp_tip). Reines Diagnose-Artefakt, veraendert keine Tipps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .io import read_json, write_json
from .model import (
    ENSEMBLE_MARKET_BLEND_WEIGHT,
    blend_market_probabilities,
    calibrate_score_matrix_to_market_constraints,
    market_constraints_from_outcomes,
    outcome_probabilities,
    score_matrix,
)
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import best_kicktipp_tip

# Reihenfolge = Aufbaureihenfolge im xg_breakdown.
CONTEXT_EFFECTS: list[tuple[str, str]] = [
    ("heat_effect", "Heat/WBGT"),
    ("altitude_effect", "Hoehenlage"),
    ("travel_effect", "Reise/Erholung"),
    ("player_intel_effect", "Player-Intel"),
    ("news_effect", "Spieler-News"),
]
# identisch zum Clamp in model.expected_goals.
XG_MIN = 0.25
XG_MAX = 3.75

CONTEXT_ABLATION_PATH = DATA_DIR / "context_ablation.json"
CONTEXT_ABLATION_MARKDOWN_PATH = EXPORTS_DIR / "context_ablation.md"


def _clamp(value: float) -> float:
    return max(XG_MIN, min(XG_MAX, value))


def _tip_for(
    home_xg: float,
    away_xg: float,
    odds_probs: Mapping[str, Any] | None,
    stage: str,
    round_id: str,
) -> dict[str, Any]:
    matrix = score_matrix(home_xg, away_xg)
    blended = blend_market_probabilities(
        outcome_probabilities(matrix),
        odds_probs,
        weight=ENSEMBLE_MARKET_BLEND_WEIGHT,
    )
    calibrated, _ = calibrate_score_matrix_to_market_constraints(
        matrix, market_constraints_from_outcomes(blended)
    )
    return best_kicktipp_tip(calibrated, stage, round_id=round_id)


def context_ablation(predictions: Mapping[str, Any]) -> dict[str, Any]:
    fixtures = list(predictions.get("predictions") or [])
    # round_ids stabil aus den round_tips-Keys (predictions["rounds"] sind
    # Metadaten-Dicts, keine ID-Strings).
    round_ids: list[str] = []
    for fixture in fixtures:
        for round_id in (fixture.get("round_tips") or {}):
            if round_id not in round_ids:
                round_ids.append(round_id)

    effects_out: list[dict[str, Any]] = []
    for effect_key, label in CONTEXT_EFFECTS:
        affected = 0
        abs_deltas: list[float] = []
        tip_changes = {rid: 0 for rid in round_ids}
        ep_delta = {rid: 0.0 for rid in round_ids}
        changed: list[dict[str, Any]] = []
        for fixture in fixtures:
            breakdown = fixture.get("xg_breakdown") or {}
            home_bd = breakdown.get("home") or {}
            away_bd = breakdown.get("away") or {}
            xg = fixture.get("xg") or {}
            fixture_meta = fixture.get("fixture") or {}
            stage = fixture_meta.get("stage", "group")
            odds_probs = (fixture.get("odds") or {}).get("probabilities")
            delta_home = float(home_bd.get(effect_key, 0.0) or 0.0)
            delta_away = float(away_bd.get(effect_key, 0.0) or 0.0)
            if abs(delta_home) > 1e-9 or abs(delta_away) > 1e-9:
                affected += 1
                abs_deltas.extend([abs(delta_home), abs(delta_away)])
            ablated_home = _clamp(float(xg.get("home", 0.0)) - delta_home)
            ablated_away = _clamp(float(xg.get("away", 0.0)) - delta_away)
            round_tips = fixture.get("round_tips") or {}
            for round_id in round_ids:
                current = round_tips.get(round_id) or {}
                ablated = _tip_for(ablated_home, ablated_away, odds_probs, stage, round_id)
                if (ablated.get("home"), ablated.get("away")) == (
                    current.get("home"),
                    current.get("away"),
                ):
                    continue
                tip_changes[round_id] += 1
                cur_ep = float(current.get("expected_points") or 0.0)
                abl_ep = float(ablated.get("expected_points") or 0.0)
                ep_delta[round_id] += cur_ep - abl_ep
                changed.append(
                    {
                        "match_id": fixture.get("match_id"),
                        "match": f"{fixture_meta.get('home_team')} - {fixture_meta.get('away_team')}",
                        "round_id": round_id,
                        "with_effect_tip": current.get("tip"),
                        "without_effect_tip": ablated.get("tip"),
                        "ep_with": round(cur_ep, 3),
                        "ep_without": round(abl_ep, 3),
                        "xg_delta": {"home": round(delta_home, 3), "away": round(delta_away, 3)},
                    }
                )
        nonzero = [d for d in abs_deltas if d > 0]
        effects_out.append(
            {
                "effect": effect_key,
                "label": label,
                "fixtures_affected": affected,
                "mean_abs_xg": round(sum(nonzero) / len(nonzero), 4) if nonzero else 0.0,
                "max_abs_xg": round(max(abs_deltas), 4) if abs_deltas else 0.0,
                "tip_changes": tip_changes,
                "tip_changes_total": sum(tip_changes.values()),
                "ep_delta": {rid: round(value, 3) for rid, value in ep_delta.items()},
                "changed_fixtures": changed,
            }
        )

    total_changes = sum(item["tip_changes_total"] for item in effects_out)
    fixtures_count = len(fixtures)
    conflicts = news_market_conflicts({"effects": effects_out}, predictions)
    return {
        "news_market_conflicts": conflicts,
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fixtures": fixtures_count,
            "rounds": round_ids,
            "market_blend_weight": ENSEMBLE_MARKET_BLEND_WEIGHT,
            "method": (
                "Je Effekt das xG-Delta aus xg_breakdown entfernen und den Tipp "
                "ueber denselben Pfad (score_matrix -> Markt-Blend -> Kalibrierung "
                "-> best_kicktipp_tip) neu rechnen. Diagnose, veraendert keine Tipps."
            ),
            "summary": (
                f"{total_changes} Tippwechsel ueber {len(CONTEXT_EFFECTS)} Effekte und "
                f"{fixtures_count} Spiele x {len(round_ids)} Runden -- die Kontext-Effekte "
                "sind klein und bewegen je Effekt nur wenige Tipps."
            ),
            "news_market_conflicts_note": (
                "T-0144: News dreht den Tipp gegen einen klaren Marktfavoriten (>=45%). "
                "Live gemessen kosten genau diese Flips -2.10 Pkt/Stueck (n=10, dPkt -21), "
                "News-Flips MIT dem Markt nur -0.23 (n=39). Der dPkt-Gate stuft `news` "
                "insgesamt auf `halve` (-35). Diagnose, kein Tipp wird veraendert."
            ),
        },
        "effects": effects_out,
    }


def _tip_outcome(tip: str) -> str | None:
    try:
        home, away = (int(x) for x in tip.split(":"))
    except (ValueError, AttributeError):
        return None
    if home > away:
        return "home"
    if away > home:
        return "away"
    return "draw"


def _market_favorite(prediction: Mapping[str, Any]) -> tuple[str, float] | None:
    """(Favoritenseite, entoverte Wahrscheinlichkeit) aus den 1X2-Quoten, sonst None."""
    decimal = ((prediction.get("odds") or {}).get("decimal_odds")) or {}
    try:
        implied = {side: 1.0 / float(decimal[side]) for side in ("home", "draw", "away")}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    total = sum(implied.values())
    if total <= 0:
        return None
    probs = {side: value / total for side, value in implied.items()}
    side = max(("home", "away"), key=probs.get)
    if probs["home"] == probs["away"]:
        return None
    return side, probs[side]


def news_market_conflicts(
    report: Mapping[str, Any],
    predictions: Mapping[str, Any],
    *,
    min_market_prob: float = 0.45,
) -> list[dict[str, Any]]:
    """T-0144: News dreht den Tipp GEGEN einen klaren Marktfavoriten.

    Genau diese Flips sind live teuer: auf den gespielten Spielen kosten sie
    im Schnitt **-2.10 Punkte** je Flip (n=10, dPkt -21), waehrend News-Flips MIT
    dem Markt nur -0.23 kosten (n=39). Gleiches Muster wie Brasilien-Japan
    (T-0121) und ko-099 Norway-England.

    Reine Diagnose auf vorhandenen Artefakten -- kein Tipp wird veraendert.
    Gemeldet werden nur noch nicht gespielte Spiele (dort zaehlt der Tipp noch).
    """
    by_id = {p.get("match_id"): p for p in predictions.get("predictions", [])}
    conflicts: list[dict[str, Any]] = []
    for effect in report.get("effects") or []:
        if effect.get("effect") != "news_effect":
            continue
        for change in effect.get("changed_fixtures") or []:
            prediction = by_id.get(change.get("match_id"))
            if not prediction:
                continue
            fixture = prediction.get("fixture") or {}
            if fixture.get("status") == "played":
                continue
            market = _market_favorite(prediction)
            if market is None:
                continue
            favorite, probability = market
            if probability < min_market_prob:
                continue
            with_tip = change.get("with_effect_tip")
            outcome = _tip_outcome(with_tip)
            if outcome is None or outcome == "draw" or outcome == favorite:
                continue
            conflicts.append(
                {
                    "match_id": change.get("match_id"),
                    "match": f"{fixture.get('home_team')} - {fixture.get('away_team')}",
                    "round_id": change.get("round_id"),
                    "with_news_tip": with_tip,
                    "without_news_tip": change.get("without_effect_tip"),
                    "market_favorite": favorite,
                    "market_probability": round(probability, 3),
                    "news_xg_delta": {
                        side: ((prediction.get("xg_breakdown") or {}).get(side) or {}).get("news_effect")
                        for side in ("home", "away")
                    },
                }
            )
    return conflicts


def context_ablation_markdown(report: Mapping[str, Any]) -> str:
    meta = report.get("_meta") or {}
    lines = [
        "# Kontext-Ablation: bewegen die kleinen Effekte den Tipp?",
        "",
        meta.get("summary", ""),
        "",
        (
            "Methode: je Effekt das xG-Delta entfernen und den Tipp neu rechnen "
            "(gleiche Predictions, gleicher Markt-Blend). Diagnose, keine "
            "Tippaenderung."
        ),
        "",
        "| Effekt | Spiele betroffen | mittl. |dxg| | max |dxg| | Tippwechsel |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in report.get("effects") or []:
        lines.append(
            "| {label} | {affected} | {mean} | {maxd} | {changes} |".format(
                label=item.get("label"),
                affected=item.get("fixtures_affected"),
                mean=item.get("mean_abs_xg"),
                maxd=item.get("max_abs_xg"),
                changes=item.get("tip_changes_total"),
            )
        )
    movers = [
        change
        for item in report.get("effects") or []
        for change in item.get("changed_fixtures") or []
    ]
    if movers:
        lines.extend(
            [
                "",
                "## Tatsaechliche Tippwechsel",
                "",
                "| Effekt | Spiel | Runde | mit | ohne | EP mit | EP ohne |",
                "|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for item in report.get("effects") or []:
            for change in item.get("changed_fixtures") or []:
                lines.append(
                    "| {label} | {match} | {round} | {with_tip} | {without_tip} | "
                    "{ep_with} | {ep_without} |".format(
                        label=item.get("label"),
                        match=change.get("match"),
                        round=change.get("round_id"),
                        with_tip=change.get("with_effect_tip"),
                        without_tip=change.get("without_effect_tip"),
                        ep_with=change.get("ep_with"),
                        ep_without=change.get("ep_without"),
                    )
                )
    return "\n".join(lines)


def build_context_ablation(*, write: bool = True) -> dict[str, Any]:
    predictions = read_json(DATA_DIR / "predictions.json", {})
    report = context_ablation(predictions)
    if write:
        write_json(CONTEXT_ABLATION_PATH, report)
        CONTEXT_ABLATION_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONTEXT_ABLATION_MARKDOWN_PATH.write_text(
            context_ablation_markdown(report), encoding="utf-8"
        )
    return report
