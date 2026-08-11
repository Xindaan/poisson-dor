"""Live-Lernschleife (T-0071): bewertet die Modell-Tipps gegen die echten
WM-2026-Ergebnisse. Read-only Diagnose -- aendert das Modell nicht.

Pro Spiel mit Ergebnis:
- erzielte Kicktipp-Punkte je Runde (gegen die runden-spezifische Wertung
  inkl. Elfer-Konvention via `actual_for_round`),
- probabilistische Guete (Brier/Log-Loss + Wkt auf das tatsaechliche
  Ergebnis) der drei Quellen model / blended / market.

Aggregiert: Punkte/Spiel je Runde, EP-vs-real-Luecke, mittlerer Brier/
Log-Loss je Quelle (welche Quelle ist live am besten kalibriert?), Drift
gegen die Backtest-Erwartung, und wie viele gespielte Spiele noch ohne
Ergebnis sind.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import log
from typing import Any, Mapping

from .io import read_json, write_json
from .paths import DATA_DIR, EXPORTS_DIR
from .role_experiment import load_manual_results
from .scoring import DEFAULT_ROUND_ID, Score, actual_for_round, kicktipp_points
from .tip_snapshots import load_tip_snapshots, snapshot_tip

LIVE_EVAL_PATH = DATA_DIR / "live_eval.json"
LIVE_EVAL_MARKDOWN_PATH = EXPORTS_DIR / "live_eval.md"

_EPS = 1e-9
_OUTCOMES = ("H", "D", "A")
_PROB_SOURCES = ("model", "blended", "market")
_DEFAULT_ROUND = DEFAULT_ROUND_ID
# T-0077: Tor-Inflations-Monitor. theta = (alpha + Sum beobachtete Tore) /
# (alpha + Sum Modell-erwartete Tore). alpha = Prior-Gewicht (~40 Spiele a
# 2.56 Tore). theta>1 -> Modell unterschaetzt Tore, <1 -> ueberschaetzt.
TOTALS_PRIOR_WEIGHT = 100.0


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "H"
    if away > home:
        return "A"
    return "D"


def _triplet(probs: Mapping[str, float] | None) -> dict[str, float] | None:
    if not probs:
        return None
    return {
        "H": float(probs.get("home", 0.0)),
        "D": float(probs.get("draw", 0.0)),
        "A": float(probs.get("away", 0.0)),
    }


def _brier(probs: Mapping[str, float], outcome: str) -> float:
    return sum((probs.get(k, 0.0) - (1.0 if k == outcome else 0.0)) ** 2 for k in _OUTCOMES)


def _logloss(probs: Mapping[str, float], outcome: str) -> float:
    return -log(max(_EPS, min(1.0, probs.get(outcome, 0.0))))


def _parse_tip(label: Any) -> Score | None:
    try:
        home, away = (int(part) for part in str(label).split(":"))
    except (ValueError, AttributeError):
        return None
    return Score(home, away)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _ensemble_ppm(report: Mapping[str, Any]) -> float | None:
    """Defensiv die Ensemble-Punkte/Spiel aus dem Backtest-Report ziehen
    (Drift-Referenz). Sucht eine ensemble-points_per_match-Zahl, sonst None."""
    def walk(node: Any) -> float | None:
        if isinstance(node, Mapping):
            ens = node.get("ensemble")
            if isinstance(ens, Mapping):
                ppm = ens.get("points_per_match") or ens.get("ppm")
                if isinstance(ppm, (int, float)):
                    return float(ppm)
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        return None

    return walk(report) if isinstance(report, Mapping) else None


def _pending_results(predictions: list[dict[str, Any]], results: Mapping[str, Any], now: datetime) -> int:
    pending = 0
    for pred in predictions:
        match_id = pred.get("match_id")
        if match_id in results:
            continue
        kickoff = (pred.get("fixture") or {}).get("kickoff_utc")
        try:
            parsed = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00")) if kickoff else None
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed is not None and parsed < now:
            pending += 1
    return pending


def _results_from_fixtures(fixtures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Ergebnisse gespielter Spiele aus den openfootball-Fixtures (T-0081).
    Stabile match_id, Ergebnis direkt aus der Quelle -- kein manuelles/Web-
    Fetchen mehr noetig."""
    out: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        result = fixture.get("result")
        if fixture.get("status") == "played" and isinstance(result, list) and len(result) == 2:
            out[fixture.get("match_id")] = {
                "actual": [int(result[0]), int(result[1])],
                "penalty_winner": None,
                "source": "openfootball",
            }
    return out


def _best_source(calib: Mapping[str, Mapping[str, Any]]) -> str | None:
    scored = [(src, c.get("mean_brier")) for src, c in calib.items() if c.get("mean_brier") is not None]
    return min(scored, key=lambda pair: pair[1])[0] if scored else None


def build_live_eval(
    *,
    predictions: list[dict[str, Any]] | None = None,
    results: Mapping[str, Mapping[str, Any]] | None = None,
    snapshots: Mapping[str, Any] | None = None,
    backtest_ppm: float | None = None,
    now: datetime | None = None,
    write: bool = True,
) -> dict[str, Any]:
    if predictions is None:
        predictions = read_json(DATA_DIR / "predictions.json", {"predictions": []}).get("predictions", [])
        if snapshots is None:
            snapshots = load_tip_snapshots()
    if snapshots is None:
        snapshots = {}
    if results is None:
        # T-0081: Ergebnisse kommen aus den openfootball-Fixtures (status=
        # played + result, stabile match_id). manual_results.json ist nur noch
        # Override (Korrekturen, penalty_winner) und schlaegt die Auto-Quelle.
        auto = _results_from_fixtures(
            read_json(DATA_DIR / "fixtures.json", {"fixtures": []}).get("fixtures", [])
        )
        auto.update(load_manual_results())
        results = auto
    if backtest_ppm is None:
        backtest_ppm = _ensemble_ppm(read_json(DATA_DIR / "backtest_report.json", {}))
    now = now or datetime.now(timezone.utc)

    by_id = {p.get("match_id"): p for p in predictions}

    matches: list[dict[str, Any]] = []
    round_points: dict[str, list[float]] = {}
    round_ep: dict[str, list[float]] = {}
    brier: dict[str, list[float]] = {src: [] for src in _PROB_SOURCES}
    logloss: dict[str, list[float]] = {src: [] for src in _PROB_SOURCES}
    hit_actual: dict[str, list[float]] = {src: [] for src in _PROB_SOURCES}
    observed_goals = 0.0
    model_goals = 0.0
    totals_matches = 0

    for match_id, res in sorted(results.items()):
        pred = by_id.get(match_id)
        actual = res.get("actual") if isinstance(res, Mapping) else None
        if not pred or not actual or len(actual) != 2:
            continue
        ah, aa = int(actual[0]), int(actual[1])
        penalty_winner = res.get("penalty_winner")
        fixture = pred.get("fixture") or {}
        stage = fixture.get("stage", "group")
        outcome = _outcome(ah, aa)

        per_round: dict[str, Any] = {}
        for round_id, rt in (pred.get("round_tips") or {}).items():
            # T-0081: eingefrorenen Pre-Kickoff-Tipp werten (was getippt wurde),
            # sonst Fallback auf den aktuellen Tipp.
            frozen = snapshot_tip(snapshots, match_id, round_id)
            tip_label = frozen if frozen is not None else rt.get("tip")
            tip = _parse_tip(tip_label)
            if tip is None:
                continue
            actual_score = actual_for_round(
                [ah, aa], penalty_winner, round_id, res.get("shootout")
            )
            points = kicktipp_points(tip, actual_score, stage, round_id)
            expected = rt.get("expected_points")
            per_round[round_id] = {
                "tip": tip_label,
                "frozen": frozen is not None,
                "points": points,
                "expected_points": expected,
            }
            round_points.setdefault(round_id, []).append(points)
            if isinstance(expected, (int, float)):
                round_ep.setdefault(round_id, []).append(float(expected))

        sources = {
            "model": _triplet((pred.get("probabilities") or {}).get("model")),
            "blended": _triplet((pred.get("probabilities") or {}).get("blended")),
            "market": _triplet((pred.get("odds") or {}).get("probabilities")),
        }
        calibration: dict[str, Any] = {}
        for src, tri in sources.items():
            if tri is None:
                continue
            b, ll = _brier(tri, outcome), _logloss(tri, outcome)
            brier[src].append(b)
            logloss[src].append(ll)
            hit_actual[src].append(tri.get(outcome, 0.0))
            calibration[src] = {"brier": round(b, 4), "logloss": round(ll, 4), "p_actual": round(tri.get(outcome, 0.0), 4)}

        xg = pred.get("xg") or {}
        model_total = xg.get("home")
        if isinstance(model_total, (int, float)) and isinstance(xg.get("away"), (int, float)):
            observed_goals += ah + aa
            model_goals += xg["home"] + xg["away"]
            totals_matches += 1

        matches.append({
            "match_id": match_id,
            "match": f"{fixture.get('home_team', '?')} {ah}:{aa} {fixture.get('away_team', '?')}",
            "stage": stage,
            "outcome": outcome,
            "rounds": per_round,
            "calibration": calibration,
        })

    rounds_summary = {
        round_id: {
            "matches": len(pts),
            "points_total": sum(pts),
            "points_per_match": _mean(pts),
            "mean_expected_points": _mean(round_ep.get(round_id, [])),
        }
        for round_id, pts in sorted(round_points.items())
    }
    calib_summary = {
        src: {
            "matches": len(brier[src]),
            "mean_brier": _mean(brier[src]),
            "mean_logloss": _mean(logloss[src]),
            "mean_p_actual": _mean(hit_actual[src]),
        }
        for src in _PROB_SOURCES
    }

    n = len(matches)
    live_ppm = rounds_summary.get(_DEFAULT_ROUND, {}).get("points_per_match")
    drift = None
    if live_ppm is not None and backtest_ppm:
        drift = {
            "live_ppm": live_ppm,
            "backtest_ppm": round(backtest_ppm, 4),
            "delta": round(live_ppm - backtest_ppm, 4),
            "note": "n zu klein fuer Aussage" if n < 10 else "beobachten",
        }

    totals = None
    if totals_matches:
        theta = (TOTALS_PRIOR_WEIGHT + observed_goals) / (TOTALS_PRIOR_WEIGHT + model_goals)
        totals = {
            "matches": totals_matches,
            "observed_goals": round(observed_goals, 2),
            "model_expected_goals": round(model_goals, 2),
            "inflation_theta": round(theta, 4),
            "note": "Prior-dominiert (n klein)" if totals_matches < 20 else
                    ("Modell unterschaetzt Tore" if theta > 1.03 else
                     "Modell ueberschaetzt Tore" if theta < 0.97 else "im Rahmen"),
        }

    payload = {
        "_meta": {
            "matches_evaluated": n,
            "results_pending": _pending_results(predictions, results, now),
            "best_calibrated_source": _best_source(calib_summary),
        },
        "rounds": rounds_summary,
        "calibration": calib_summary,
        "totals": totals,
        "drift": drift,
        "matches": matches,
    }

    if write:
        write_json(LIVE_EVAL_PATH, payload)
        LIVE_EVAL_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIVE_EVAL_MARKDOWN_PATH.write_text(live_eval_markdown(payload), encoding="utf-8")

    return payload


def live_eval_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# Live-Auswertung (echte WM-2026-Ergebnisse)",
        "",
        f"- Ausgewertete Spiele: **{meta.get('matches_evaluated', 0)}**",
        f"- Gespielt, aber noch ohne Ergebnis: **{meta.get('results_pending', 0)}**",
        f"- Live am besten kalibrierte Quelle: **{meta.get('best_calibrated_source') or 'n/a'}**",
        "",
        "## Punkte je Runde",
        "",
    ]
    for round_id, row in (payload.get("rounds") or {}).items():
        lines.append(
            f"- **{round_id}**: {row['points_total']} Pkt aus {row['matches']} Spielen "
            f"= {row['points_per_match']}/Spiel (Modell erwartete {row['mean_expected_points']}/Spiel)"
        )
    if not payload.get("rounds"):
        lines.append("_Noch keine ausgewerteten Spiele._")

    lines += ["", "## Probabilistische Guete (niedriger = besser)", ""]
    for src, c in (payload.get("calibration") or {}).items():
        if c.get("matches"):
            lines.append(
                f"- **{src}**: Brier {c['mean_brier']}, Log-Loss {c['mean_logloss']}, "
                f"mittlere Wkt aufs Ergebnis {c['mean_p_actual']} ({c['matches']} Spiele)"
            )

    totals = payload.get("totals")
    if totals:
        lines += [
            "",
            "## Tor-Inflation (Modell vs real)",
            "",
            f"- beobachtet {totals['observed_goals']} vs Modell-erwartet {totals['model_expected_goals']} Tore "
            f"({totals['matches']} Spiele) -> theta {totals['inflation_theta']} -- {totals['note']}",
        ]

    drift = payload.get("drift")
    if drift:
        lines += [
            "",
            "## Drift gegen Backtest",
            "",
            f"- Live {drift['live_ppm']}/Spiel vs Backtest-Ensemble {drift['backtest_ppm']}/Spiel "
            f"(Delta {drift['delta']:+}) -- {drift['note']}",
        ]

    lines += ["", "## Spiele", ""]
    for m in payload.get("matches") or []:
        pts = ", ".join(f"{rid.split('-')[0]}:{r['tip']}={r['points']}" for rid, r in (m.get("rounds") or {}).items())
        lines.append(f"- {m['match']} ({m['outcome']}) -- {pts}")

    return "\n".join(lines).rstrip() + "\n"
