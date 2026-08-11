"""Aggressivitaets-A/B (T-0082): tippt das Modell zu konservativ?

Befund Spieltag 1: Modell tippt ~1.0 Tore/Tipp (meist 1:0), das Feld 3-4;
die Fuehrenden trennen sich ueber Exakt-Treffer. Hypothese: die Tipps
Richtung realistischer Tordifferenz (2:1 statt 1:0) verschieben bringt
mehr Punkte/Exakt-Treffer.

Mechanik: ein Inflations-Knopf kappa auf die xG, DANN EP-Maximierung.
kappa=1.0 = aktuell (konservativ), kappa>1 = aggressiver (hoehere
Scorelines). Gemessen wird BEIDES:
- Backtest (7 Turniere, 342+ Spiele): Punkte + Exakt-Treffer je kappa --
  die belastbare Validierung (Backtest-Regel des Projekts).
- Live (2026er Ergebnisse): dasselbe auf den bisherigen Spielen.

Read-only Diagnose. Kein Auto-Umstellen des Live-Tipps -- erst wenn der
Backtest zeigt, dass Aggression wirklich Punkte bringt (nicht nur Varianz).
"""
from __future__ import annotations

from typing import Any, Mapping

from .backtest import _xg_from_pre_match, default_report_datasets
from .historical import build_historical_dataset
from .io import read_json, write_json
from .model import score_matrix
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import (
    DEFAULT_ROUND_ID,
    round_name,
    SECONDARY_ROUND_ID,
    Score,
    actual_for_round,
    best_kicktipp_tip,
    kicktipp_points,
)

STRATEGY_AB_PATH = DATA_DIR / "strategy_ab.json"
STRATEGY_AB_MARKDOWN_PATH = EXPORTS_DIR / "strategy_ab.md"

KAPPAS = (1.0, 1.15, 1.3, 1.5)
ROUND_IDS = (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID)


def aggressive_tip(home_xg: float, away_xg: float, stage: str, round_id: str, kappa: float) -> tuple[int, int]:
    """EP-Maximum auf der kappa-inflationierten xG-Matrix."""
    tip = best_kicktipp_tip(score_matrix(home_xg * kappa, away_xg * kappa), stage, round_id=round_id)
    return int(tip["home"]), int(tip["away"])


def _aggregate(samples: list[tuple[float, float, str, list[int], Any, Any]], round_id: str) -> dict[str, Any]:
    """samples: (home_xg, away_xg, stage, result[h,a], penalty_winner, shootout).

    `shootout` ist die reine Elferbilanz (T-0155); fehlt sie, greift in
    `actual_for_round` die dokumentierte Naeherung."""
    out: dict[str, Any] = {}
    for kappa in KAPPAS:
        points = 0
        exact = 0
        matches = 0
        total_tip_goals = 0
        for home_xg, away_xg, stage, result, penalty_winner, shootout in samples:
            if home_xg is None or not result or len(result) != 2:
                continue
            th, ta = aggressive_tip(home_xg, away_xg, stage, round_id, kappa)
            actual = actual_for_round(result, penalty_winner, round_id, shootout)
            points += kicktipp_points(Score(th, ta), actual, stage, round_id)
            exact += int((th, ta) == (actual.home, actual.away))
            total_tip_goals += th + ta
            matches += 1
        out[f"{kappa}"] = {
            "kappa": kappa,
            "matches": matches,
            "points": points,
            "points_per_match": round(points / matches, 4) if matches else None,
            "exact_hits": exact,
            "mean_tip_goals": round(total_tip_goals / matches, 2) if matches else None,
        }
    return out


def _backtest_samples() -> list[tuple[float, float, str, list[int], Any, Any]]:
    samples = []
    for name, path in default_report_datasets():
        build_historical_dataset(name)
        for row in read_json(path, {}).get("results", []):
            xg = _xg_from_pre_match(row.get("pre_elo"), row.get("pre_odds"))
            actual = row.get("actual")
            if not xg or not actual or len(actual) != 2:
                continue
            samples.append(
                (
                    xg[0],
                    xg[1],
                    row.get("stage", "group"),
                    actual,
                    row.get("penalty_winner"),
                    row.get("shootout"),
                )
            )
    return samples


def _live_samples(predictions: list[dict[str, Any]], fixtures: list[dict[str, Any]]) -> list:
    results = {
        f.get("match_id"): f.get("result")
        for f in fixtures
        if f.get("status") == "played" and f.get("result")
    }
    by_id = {p.get("match_id"): p for p in predictions}
    samples = []
    for match_id, result in results.items():
        pred = by_id.get(match_id)
        if not pred:
            continue
        xg = pred.get("xg") or {}
        if xg.get("home") is None:
            continue
        stage = (pred.get("fixture") or {}).get("stage", "group")
        samples.append((xg["home"], xg["away"], stage, result, None, None))
    return samples


def _best_kappa(stats: Mapping[str, Any]) -> float | None:
    scored = [(v["kappa"], v["points"], v["exact_hits"]) for v in stats.values() if v.get("matches")]
    return max(scored, key=lambda x: (x[1], x[2]))[0] if scored else None


def build_strategy_ab(*, predictions=None, fixtures=None, write: bool = True) -> dict[str, Any]:
    if predictions is None:
        predictions = read_json(DATA_DIR / "predictions.json", {"predictions": []}).get("predictions", [])
    if fixtures is None:
        fixtures = read_json(DATA_DIR / "fixtures.json", {"fixtures": []}).get("fixtures", [])

    backtest_samples = _backtest_samples()
    live_samples = _live_samples(predictions, fixtures)

    backtest = {rid: _aggregate(backtest_samples, rid) for rid in ROUND_IDS}
    live = {rid: _aggregate(live_samples, rid) for rid in ROUND_IDS}

    best_bt = _best_kappa(backtest[DEFAULT_ROUND_ID])
    base_pts = backtest[DEFAULT_ROUND_ID]["1.0"]["points"]
    best_pts = backtest[DEFAULT_ROUND_ID][f"{best_bt}"]["points"] if best_bt is not None else base_pts
    verdict = (
        f"Aggression hilft (kappa* {best_bt}, +{best_pts - base_pts} Pkt)" if best_bt and best_bt > 1.0 and best_pts > base_pts
        else "konservativ (kappa=1.0) ist auf Punkten optimal" if best_bt == 1.0
        else "uneindeutig"
    )

    payload = {
        "_meta": {
            "kappas": list(KAPPAS),
            "backtest_matches": backtest[DEFAULT_ROUND_ID]["1.0"]["matches"],
            "live_matches": live[DEFAULT_ROUND_ID]["1.0"]["matches"],
            "backtest_best_kappa": best_bt,
            "verdict": verdict,
            "note": "Read-only. Live-Tipp nur umstellen, wenn der Backtest Aggression auf PUNKTE bestaetigt.",
        },
        "backtest": backtest,
        "live": live,
    }
    if write:
        write_json(STRATEGY_AB_PATH, payload)
        STRATEGY_AB_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        STRATEGY_AB_MARKDOWN_PATH.write_text(strategy_ab_markdown(payload), encoding="utf-8")
    return payload


def strategy_ab_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# Aggressivitaets-A/B (kappa-Tor-Inflation vor EP-Max)",
        "",
        f"- Backtest: **{meta.get('backtest_matches', 0)}** Spiele, bestes kappa **{meta.get('backtest_best_kappa')}**",
        f"- **Verdikt:** {meta.get('verdict')}",
        f"- Live: {meta.get('live_matches', 0)} Spiele",
        "",
        meta.get("note", ""),
        "",
        f"## Backtest ({round_name(DEFAULT_ROUND_ID)}), Punkte + Exakt je kappa",
        "",
        "| kappa | Pkt | Pkt/Spiel | Exakt | Tore/Tipp |",
        "|---|---|---|---|---|",
    ]
    for row in (payload.get("backtest") or {}).get(DEFAULT_ROUND_ID, {}).values():
        lines.append(
            f"| {row['kappa']} | {row['points']} | {row['points_per_match']} | {row['exact_hits']} | {row['mean_tip_goals']} |"
        )
    lines += ["", f"## Live ({round_name(DEFAULT_ROUND_ID)})", "", "| kappa | Pkt | Exakt | Tore/Tipp |", "|---|---|---|---|"]
    for row in (payload.get("live") or {}).get(DEFAULT_ROUND_ID, {}).values():
        lines.append(f"| {row['kappa']} | {row['points']} | {row['exact_hits']} | {row['mean_tip_goals']} |")
    return "\n".join(lines).rstrip() + "\n"
