"""Risk-Dial-Backtest (T-0075): Chase vs Protect.

T-0082 hat beantwortet, ob Aggression mehr PUNKTE bringt (Antwort: nein,
EP-Max ist auf Punkten optimal). T-0075 stellt die andere Frage: Kicktipp
zahlt RANG, nicht Punkte. Wenn man D Punkte zurueckliegt und noch M Spiele
offen sind, lohnt es sich, gezielt Varianz zu kaufen -- auch zum EP-Preis --
weil ein Rueckstand sonst nicht aufzuholen ist.

Der Aggressions-Hebel ist hier exakt die Risk-Dial-Formel aus der Task-
Spezifikation: t* = argmax_c [ EP(c) + kappa * sigma(c) ], wobei sigma(c)
die Standardabweichung der Kicktipp-Punkte fuer Tipp c unter der Modell-
Score-Matrix ist. kappa=0 == EP-Max (Status quo). kappa>0 waehlt Alles-oder-nichts-Scorelines
(mehr P(exakt), weniger sichere Tendenz) -> mehr Varianz.
(Das ist NICHT die xG-Inflation aus T-0082; die verschiebt nur welche
Scoreline, nicht den Spread.)

Drei Bausteine, alle aus dem 405-Spiele-Backtest + der echten Pool-Crowd:

1. EP-Preis + Varianz je kappa (crowd-frei, voll messbar auf 405 Spielen):
   mittlere Punkte/Spiel, Std, Exakt-Rate, EP-Kosten ggue. kappa=0.

2. P(Ueberholen)-Grid: fuer (D=Rueckstand, M=Restspiele) per Bootstrap der
   gepaarten Punktedifferenz adv_i(kappa) = pts_kappa(i) - pts_leader(i) die
   Wahrscheinlichkeit P(sum_M adv >= D). Leader = EP-Max-Klon (kappa=0).
   Liefert je Zelle das beste kappa.

3. Live-Counterfactual gegen die ECHTE Crowd (manual_pool_tips): haetten
   aggressivere Tipps auf den schon gespielten Partien unseren Rang
   verbessert? Kleines n -- Realitaets-Check, kein Beweis.

Read-only Diagnose. Kein Auto-Umstellen des Live-Tipps (stehende Regel:
erst Backtest-Beleg, dann Override).
"""
from __future__ import annotations

from datetime import datetime, timezone

import random
import statistics
from math import sqrt
from typing import Any, Mapping

from .io import read_json, write_json
from .model import score_matrix
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import (
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    round_name,
    Score,
    actual_for_round,
    is_knockout_stage,
    kicktipp_points,
    resolve_extra_time,
    resolve_knockout_draw_probabilities,
    round_resolves_penalties,
)
from .tip_strategy_ab import ROUND_IDS, _backtest_samples

RISK_DIAL_PATH = DATA_DIR / "risk_dial.json"
RISK_DIAL_MARKDOWN_PATH = EXPORTS_DIR / "risk_dial.md"

# Varianz-Tilt-Gewichte. kappa=0 == EP-Max (Status quo). kappa>0 = Chase.
RISK_KAPPAS = (0.0, 0.5, 1.0, 2.0)
# Rueckstand (Punkte) und Restspiele -- die zwei Achsen des Dials.
D_GRID = (0, 1, 2, 3, 5, 8)
M_GRID = (3, 6, 10, 20, 40)
N_SIMS = 4000
SEED = 20260617  # fester Seed -> reproduzierbarer Backtest
MAX_GOALS = 6


def _resolved_probs(home_xg: float, away_xg: float, stage: str, round_id: str) -> dict[str, float]:
    """Score-Matrix wie best_kicktipp_tip: 90'-Poisson, dann fuer KO die
    ET-Transform (+ Elfer-Konvention nur fuer die Elfer-Runde)."""
    probs = score_matrix(home_xg, away_xg, MAX_GOALS)
    if is_knockout_stage(stage):
        probs = resolve_extra_time(probs)
        if round_resolves_penalties(round_id):
            probs = resolve_knockout_draw_probabilities(probs)
    return probs


def _candidate_stats(probs: Mapping[str, float], stage: str, round_id: str) -> list[dict[str, Any]]:
    """Pro Kandidaten-Scoreline EP, sigma (Std der Punkte) und P(exakt)."""
    out = []
    for home in range(MAX_GOALS + 1):
        for away in range(MAX_GOALS + 1):
            cand = Score(home, away)
            ep = 0.0
            ep2 = 0.0
            for label, p in probs.items():
                h, a = (int(x) for x in label.split(":"))
                pts = kicktipp_points(cand, Score(h, a), stage, round_id)
                ep += p * pts
                ep2 += p * pts * pts
            sigma = sqrt(max(0.0, ep2 - ep * ep))
            out.append({"score": cand, "ep": ep, "sigma": sigma, "p_exact": probs.get(cand.label, 0.0)})
    return out


def _tilt_tip(candidates: list[dict[str, Any]], kappa: float) -> Score:
    """t* = argmax EP + kappa*sigma. Tiebreak: hoeheres EP, dann wenigere Tore."""
    best = max(
        candidates,
        key=lambda c: (c["ep"] + kappa * c["sigma"], c["ep"], -(c["score"].home + c["score"].away)),
    )
    return best["score"]


def _points_by_kappa(samples, round_id: str) -> dict[float, list[int]]:
    """Pro kappa die realisierten Punkte je Spiel (index-gepaart). Die teure
    Kandidaten-Statistik wird je Spiel EINMAL gerechnet, dann je kappa nur das
    argmax gewaehlt."""
    out: dict[float, list[int]] = {k: [] for k in RISK_KAPPAS}
    for home_xg, away_xg, stage, result, penalty_winner, shootout in samples:
        if home_xg is None or not result or len(result) != 2:
            continue
        actual = actual_for_round(result, penalty_winner, round_id, shootout)
        probs = _resolved_probs(home_xg, away_xg, stage, round_id)
        cands = _candidate_stats(probs, stage, round_id)
        for kappa in RISK_KAPPAS:
            tip = _tilt_tip(cands, kappa)
            out[kappa].append(kicktipp_points(tip, actual, stage, round_id))
    return out


def _group_mask(samples) -> list[bool]:
    return [
        (home_xg is not None and bool(result) and len(result) == 2 and stage == "group")
        for home_xg, _, stage, result, _, _ in samples
    ]


def _kappa_stats(pts_by_kappa: dict[float, list[int]]) -> dict[str, Any]:
    base = pts_by_kappa[0.0]
    base_ppm = statistics.fmean(base) if base else 0.0
    out: dict[str, Any] = {}
    for kappa, pts in pts_by_kappa.items():
        n = len(pts)
        ppm = statistics.fmean(pts) if pts else 0.0
        std = statistics.pstdev(pts) if n > 1 else 0.0
        exact = sum(1 for p in pts if p in (4, 6, 8))  # exact-Punkte je Stage/Runde
        out[f"{kappa}"] = {
            "kappa": kappa,
            "matches": n,
            "points": sum(pts),
            "points_per_match": round(ppm, 4),
            "std_per_match": round(std, 4),
            "exact_hits": exact,
            "exact_rate": round(exact / n, 4) if n else None,
            # EP-Preis: wieviel Punkte/Spiel opfert dieses kappa ggue. EP-Max:
            "ep_cost_per_match": round(base_ppm - ppm, 4),
        }
    return out


def _variance_frontier(samples, round_id: str) -> dict[str, Any]:
    """Die Kernfrage direkt: wieviel Punkte-Varianz laesst sich ueberhaupt
    "kaufen"? Vergleicht den EP-Max-Tipp mit dem reinen Sigma-Max-Tipp
    (argmax sigma, EP egal) -- die Obergrenze der Aggression. Wenn die
    realisierte Std dabei kaum steigt, ist der ganze Chase-Hebel inert."""
    ep_pts, sig_pts = [], []
    ep_sum = sig_sum = 0.0
    flips = 0
    n = 0
    for home_xg, away_xg, stage, result, penalty_winner, shootout in samples:
        if home_xg is None or not result or len(result) != 2:
            continue
        actual = actual_for_round(result, penalty_winner, round_id, shootout)
        cands = _candidate_stats(_resolved_probs(home_xg, away_xg, stage, round_id), stage, round_id)
        epmax = max(cands, key=lambda c: (c["ep"], c["sigma"]))
        sigmax = max(cands, key=lambda c: (c["sigma"], c["ep"]))
        flips += int(epmax["score"].label != sigmax["score"].label)
        ep_sum += epmax["ep"]
        sig_sum += sigmax["ep"]
        ep_pts.append(kicktipp_points(epmax["score"], actual, stage, round_id))
        sig_pts.append(kicktipp_points(sigmax["score"], actual, stage, round_id))
        n += 1
    ep_std = statistics.pstdev(ep_pts) if n > 1 else 0.0
    sig_std = statistics.pstdev(sig_pts) if n > 1 else 0.0
    return {
        "matches": n,
        "ep_max": {"mean_ep": round(ep_sum / n, 4), "realized_ppm": round(statistics.fmean(ep_pts), 4),
                   "realized_std": round(ep_std, 4)},
        "sigma_max": {"mean_ep": round(sig_sum / n, 4), "realized_ppm": round(statistics.fmean(sig_pts), 4),
                      "realized_std": round(sig_std, 4)},
        "flip_rate": round(flips / n, 4) if n else None,
        "ep_cost_for_max_variance": round((ep_sum - sig_sum) / n, 4),
        "std_gain_for_max_variance": round(sig_std - ep_std, 4),
    }


def _overtake_grid(pts_by_kappa: dict[float, list[int]], group_mask: list[bool]) -> dict[str, Any]:
    """P(Ueberholen) je (D, M, kappa). adv_i = pts_kappa(i) - pts_leader(i),
    Leader = kappa=0 (EP-Max-Klon). Bootstrap aus den Gruppenphasen-Spielen
    (konsistente 2-3-4-Wertung). best_kappa = argmax P(sum_M adv >= D)."""
    rng = random.Random(SEED)
    base = pts_by_kappa[0.0]
    adv: dict[float, list[int]] = {
        kappa: [pts[i] - base[i] for i in range(len(pts)) if group_mask[i]]
        for kappa, pts in pts_by_kappa.items()
    }
    pool_n = len(adv[0.0])

    cells = []
    for d in D_GRID:
        for m in M_GRID:
            by_kappa = {}
            for kappa in RISK_KAPPAS:
                a = adv[kappa]
                hits = sum(
                    1
                    for _ in range(N_SIMS)
                    if sum(a[rng.randrange(pool_n)] for _ in range(m)) >= d
                )
                by_kappa[f"{kappa}"] = round(hits / N_SIMS, 4)
            best = max(RISK_KAPPAS, key=lambda k: (by_kappa[f"{k}"], -k))  # Gleichstand -> kleineres kappa
            cells.append({
                "deficit": d,
                "matches_left": m,
                "best_kappa": best,
                "p_overtake": by_kappa[f"{best}"],
                "by_kappa": by_kappa,
            })
    return {"pool_matches": pool_n, "n_sims": N_SIMS, "cells": cells}


def _live_counterfactual(round_id: str, predictions, pool_tips) -> dict[str, Any]:
    """Gegen die echte Crowd: Punkte je Spieler auf den gespielten Partien,
    dann unser Rang, wenn WIR mit Tilt-kappa X getippt haetten (statt EP-Max)."""
    actuals = pool_tips.get("actuals", {})
    players = (pool_tips.get("players") or {}).get(round_id, {})
    by_id = {p.get("match_id"): p for p in predictions}

    def _actual_score(value) -> Score | None:
        if isinstance(value, Mapping):
            chosen = value.get("penalty") if round_resolves_penalties(round_id) else value.get("regulation")
            if chosen is None:
                chosen = value.get("regulation") or value.get("penalty")
            return _actual_score(chosen) if chosen is not None else None
        if isinstance(value, str):
            try:
                home, away = (int(part) for part in value.split(":"))
            except ValueError:
                return None
            return Score(home, away)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            try:
                return actual_for_round(value, None, round_id)
            except (TypeError, ValueError):
                return None
        return None

    played = []
    for mid, res in actuals.items():
        pred = by_id.get(mid)
        actual = _actual_score(res)
        if not pred or actual is None:
            continue
        xg = pred.get("xg") or {}
        if xg.get("home") is None:
            continue
        stage = (pred.get("fixture") or {}).get("stage", "group")
        played.append((mid, actual, xg, stage))

    if not played:
        return {"played": 0, "note": "keine gespielten Partien mit xG+Ergebnis"}

    def _pts(tip_label, actual, stage):
        try:
            th, ta = (int(x) for x in tip_label.split(":"))
        except (ValueError, AttributeError):
            return None
        return kicktipp_points(Score(th, ta), actual, stage, round_id)

    field_totals: dict[str, int] = {}
    for name, tips in players.items():
        tot = 0
        for mid, res, _xg, stage in played:
            t = tips.get(mid)
            if t is not None:
                p = _pts(t, res, stage)
                if p is not None:
                    tot += p
        field_totals[name] = tot

    our_by_kappa = {}
    for kappa in RISK_KAPPAS:
        tot = 0
        for mid, actual, xg, stage in played:
            cands = _candidate_stats(_resolved_probs(xg["home"], xg["away"], stage, round_id), stage, round_id)
            tip = _tilt_tip(cands, kappa)
            tot += kicktipp_points(tip, actual, stage, round_id)
        rank = 1 + sum(1 for v in field_totals.values() if v > tot)
        our_by_kappa[f"{kappa}"] = {"kappa": kappa, "points": tot, "rank": rank}

    field_sorted = sorted(field_totals.values(), reverse=True)
    return {
        "played": len(played),
        "field_size": len(field_totals),
        "field_leader_points": field_sorted[0] if field_sorted else None,
        "our_by_kappa": our_by_kappa,
    }


def build_risk_dial(*, predictions=None, pool_tips=None, write: bool = True) -> dict[str, Any]:
    if predictions is None:
        predictions = read_json(DATA_DIR / "predictions.json", {"predictions": []}).get("predictions", [])
    if pool_tips is None:
        pool_tips = read_json(DATA_DIR / "manual_pool_tips.json", {})

    samples = _backtest_samples()
    group_mask = _group_mask(samples)

    backtest, grid, live, frontier = {}, {}, {}, {}
    for rid in ROUND_IDS:
        pts_by_kappa = _points_by_kappa(samples, rid)
        backtest[rid] = _kappa_stats(pts_by_kappa)
        grid[rid] = _overtake_grid(pts_by_kappa, group_mask)
        live[rid] = _live_counterfactual(rid, predictions, pool_tips)
        frontier[rid] = _variance_frontier(samples, rid)

    verdict = _verdict(frontier[DEFAULT_ROUND_ID])

    payload = {
        "_meta": {
            # Zeitstempel: stale Artefakte waren optisch nicht von frischen zu
            # unterscheiden -- genau daran ueberlebte ein kaputtes risk-dial
            # zwei Tage. Wer eine Auswertung liest, muss sehen, wann sie entstand.
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kappas": list(RISK_KAPPAS),
            "kappa_meaning": "Varianz-Tilt: t* = argmax EP + kappa*sigma. kappa=0 == EP-Max.",
            "deficit_grid": list(D_GRID),
            "matches_grid": list(M_GRID),
            "backtest_matches": backtest[DEFAULT_ROUND_ID]["0.0"]["matches"],
            "seed": SEED,
            "verdict": verdict,
            "note": (
                "Read-only. Leader im Grid = EP-Max-Klon (kappa=0): isoliert die "
                "Varianz aus EIGENER Aggression. Reales Feld ist schwaecher/diverser "
                "-> Live-Counterfactual als Realitaets-Check. Kein Auto-Override."
            ),
        },
        "backtest": backtest,
        "frontier": frontier,
        "grid": grid,
        "live": live,
    }
    if write:
        write_json(RISK_DIAL_PATH, payload)
        RISK_DIAL_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        RISK_DIAL_MARKDOWN_PATH.write_text(risk_dial_markdown(payload), encoding="utf-8")
    return payload


def _verdict(frontier: Mapping[str, Any]) -> str:
    """Das Verdikt haengt an der Varianz-Frontier: laesst sich ueberhaupt
    nutzbare Varianz kaufen? In Kicktipps 0/2/3/4-Wertung praktisch nicht --
    der EP-Max-Tipp ist schon nahe varianz-maximal."""
    std_gain = frontier["std_gain_for_max_variance"]
    ep_cost = frontier["ep_cost_for_max_variance"]
    if std_gain <= 0.1:
        return (
            f"KEIN nutzbarer Chase-Hebel: selbst maximaler Varianz-Tilt hebt die "
            f"Punkte-Std nicht (Delta {std_gain:+.3f}), kostet aber {ep_cost:.3f} Pkt/Spiel. "
            f"EP-Max ist auch rang-optimal -- NICHT chasen, auch bei Rueckstand."
        )
    return (
        f"Begrenzter Chase-Hebel: max Varianz-Tilt hebt Std um {std_gain:+.3f} zum "
        f"Preis von {ep_cost:.3f} Pkt/Spiel -- nur bei grossem Rueckstand spaet abwaegen."
    )


def risk_dial_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    bt = (payload.get("backtest") or {}).get(DEFAULT_ROUND_ID, {})
    lines = [
        "# Risk-Dial (T-0075): Chase vs Protect",
        "",
        f"- Backtest: **{meta.get('backtest_matches', 0)}** Spiele, Seed {meta.get('seed')}",
        f"- Hebel: {meta.get('kappa_meaning')}",
        f"- **Verdikt:** {meta.get('verdict')}",
        "",
        meta.get("note", ""),
        "",
        "## 0. Varianz-Frontier: wieviel Varianz ist ueberhaupt kaufbar? (Default-Runde, 405 Spiele)",
        "",
        "Kernfrage: EP-Max-Tipp vs. reiner Sigma-Max-Tipp (Aggressions-Obergrenze).",
        "",
        "| Strategie | mittl. EP/Spiel | realisierte Std | realisiert Pkt/Spiel |",
        "|---|---|---|---|",
    ]
    fr = (payload.get("frontier") or {}).get(DEFAULT_ROUND_ID, {})
    if fr:
        em, sm = fr["ep_max"], fr["sigma_max"]
        lines += [
            f"| EP-Max | {em['mean_ep']} | {em['realized_std']} | {em['realized_ppm']} |",
            f"| Sigma-Max | {sm['mean_ep']} | {sm['realized_std']} | {sm['realized_ppm']} |",
            "",
            f"- Flip-Rate (andere Scoreline): **{fr['flip_rate']:.1%}** der Spiele",
            f"- Std-Gewinn fuer max Varianz: **{fr['std_gain_for_max_variance']:+.3f}**",
            f"- EP-Preis dafuer: **{fr['ep_cost_for_max_variance']:.3f} Pkt/Spiel**",
        ]
    lines += [
        "",
        "## 1. EP-Preis & Varianz je kappa (Default-Runde, 405 Spiele)",
        "",
        "| kappa | Pkt/Spiel | EP-Kosten | Std | Exakt-Rate |",
        "|---|---|---|---|---|",
    ]
    for row in bt.values():
        lines.append(
            f"| {row['kappa']} | {row['points_per_match']} | "
            f"{row['ep_cost_per_match']:+.4f} | {row['std_per_match']} | {row['exact_rate']} |"
        )
    lines += [
        "",
        "## 2. Bestes kappa je (Rueckstand D, Restspiele M) -- P(Ueberholen)",
        "",
        "Leader = EP-Max-Klon. Zelle = bestes kappa (P).",
        "",
    ]
    grid = (payload.get("grid") or {}).get(DEFAULT_ROUND_ID, {})
    cells = {(c["deficit"], c["matches_left"]): c for c in grid.get("cells", [])}
    lines.append("| D \\ M | " + " | ".join(str(m) for m in M_GRID) + " |")
    lines.append("|" + "---|" * (len(M_GRID) + 1))
    for d in D_GRID:
        row = [f"**{d}**"]
        for m in M_GRID:
            c = cells.get((d, m))
            row.append(f"{c['best_kappa']} ({c['p_overtake']})" if c else "-")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## 3. Live-Counterfactual gegen die echte Crowd", ""]
    for rid_label, rid in ((round_name(DEFAULT_ROUND_ID), DEFAULT_ROUND_ID), (round_name(SECONDARY_ROUND_ID), SECONDARY_ROUND_ID)):
        lv = (payload.get("live") or {}).get(rid, {})
        if not lv.get("played"):
            lines.append(f"- **{rid_label}**: {lv.get('note', 'keine Daten')}")
            continue
        lines.append(
            f"- **{rid_label}** ({lv['played']} Spiele, Feld {lv['field_size']}, "
            f"Leader {lv['field_leader_points']} Pkt):"
        )
        lines += ["", "  | kappa | unsere Pkt | Rang |", "  |---|---|---|"]
        for row in lv["our_by_kappa"].values():
            lines.append(f"  | {row['kappa']} | {row['points']} | {row['rank']} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
