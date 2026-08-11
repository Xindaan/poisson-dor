#!/usr/bin/env python3
"""CV-Backtest-Harness (T-0102): Leave-One-Tournament-Out gegen Overfitting.

Testet eine Modell-Parameter-Hypothese als Matrix-Transform gegen den 7-Turnier-
Backtest (405 Spiele). KERNFRAGE: generalisiert das IN-SAMPLE optimale Parameter
out-of-sample, oder ist es nur Backtest-Overfit?

Fuer jede gehaltene Turnier-Auslassung: theta* = argmax aggregierte ppm auf den 6
Trainings-Turnieren, dann ppm(theta*) auf dem 7. (held-out) gemessen vs Baseline.
OOS-Delta = Mittel ueber die 7 Auslassungen. Zusaetzlich In-Sample-Delta (theta* auf
allen 7) -> Overfit-Gap = In-Sample - OOS.

KEEP-GATE (streng): OOS-Delta > 0  UND  per-Turnier ahead>behind beim Voll-Optimum
UND  OOS >= 0.5*In-Sample (kleiner Overfit-Gap). Sonst REVERT.

Read-only, analysis/. Aendert die Pipeline NICHT -- Hypothesen sind Matrix-Transforms
im Harness. Tipps werden FRISCH gerechnet (nicht der gecachte model_tip), damit der
Parameter ueberhaupt wirkt. Baseline (Identitaet, mw=0.20) wird gegen die bekannten
791 Pkt / 1.953 ppm validiert -> Spiegel zur echten Pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from wm_tipps.backtest import (  # noqa: E402
    MARKET_OVERRIDE_THRESHOLD,
    REPORT_TOURNAMENTS,
    _xg_from_pre_match,
    ensemble_calibrated_matrix,
)
from wm_tipps.calibration_fit import dixon_coles_adjust  # noqa: E402
from wm_tipps.io import read_json  # noqa: E402
from wm_tipps.model import (  # noqa: E402
    blend_market_probabilities,
    calibrate_score_matrix,
    outcome_probabilities,
    score_matrix,
)
from wm_tipps.odds import normalize_decimal_odds  # noqa: E402
from wm_tipps.paths import DATA_DIR  # noqa: E402
from wm_tipps.scoring import (  # noqa: E402
    DEFAULT_ROUND_ID,
    Score,
    actual_for_round,
    best_kicktipp_tip,
    kicktipp_points,
)

TOURNAMENTS = list(REPORT_TOURNAMENTS)
MW = 0.20  # Status-quo-Marktgewicht


def load_rows(tournament: str) -> list:
    payload = read_json(DATA_DIR / f"backtest_{tournament}.json", [])
    if isinstance(payload, dict):
        return payload.get("results", [])
    return payload if isinstance(payload, list) else []


def tournament_points(rows, transform, round_id=DEFAULT_ROUND_ID, market_weight=MW,
                      draw_override=None):
    """Frisch gerechnete EP-Max-Punkte eines Turniers unter einem Matrix-Transform.

    draw_override (optional, H9): callable(matrix)->(h,a)|None. Greift NUR wenn EP-Max
    bereits ein Remis tippt -- ersetzt dann die Remis-Scoreline (Tendenz-Entscheidung
    bleibt unberuehrt, damit der Scoreline-Effekt isoliert messbar ist)."""
    pts = n = 0
    for row in rows:
        m = ensemble_calibrated_matrix(row.get("pre_elo") or None, row.get("pre_odds"),
                                       market_weight=market_weight)
        if m is None:
            continue
        m = transform(m)
        stage = row.get("stage", "group")
        tip = best_kicktipp_tip(m, stage, round_id=round_id)
        th, ta = int(tip["home"]), int(tip["away"])
        if draw_override is not None and th == ta:
            ov = draw_override(m)
            if ov is not None:
                th, ta = ov
        actual = actual_for_round(
            row["actual"], row.get("penalty_winner"), round_id, row.get("shootout")
        )
        pts += kicktipp_points(Score(th, ta), actual, stage, round_id)
        n += 1
    return pts, n


def identity(matrix):
    return matrix


# --------------------------------------------------------------------------- #
# Hypothesen als Matrix-Transforms (theta -> transform)
# --------------------------------------------------------------------------- #
def _shift_outcome(matrix, which, delta):
    """Outcome `which` (home/draw/away) um delta anheben, Rest proportional
    senken, Matrix re-kalibrieren. delta<0 senkt entsprechend."""
    oc = outcome_probabilities(matrix)
    boosted = min(0.97, max(0.01, oc[which] + delta))
    others = [k for k in oc if k != which]
    rem = sum(oc[k] for k in others)
    target = {which: boosted}
    if rem > 1e-9:
        scale = (1 - boosted) / rem
        for k in others:
            target[k] = oc[k] * scale
    else:
        for k in others:
            target[k] = (1 - boosted) / 2
    return calibrate_score_matrix(matrix, target)


def favorite_boost(delta):
    """H1 (T-0084): Modell auf Favoriten under-confident -> Favoriten-Outcome anheben."""
    if delta == 0:
        return identity
    return lambda m: _shift_outcome(m, max(outcome_probabilities(m), key=outcome_probabilities(m).get), delta)


def draw_tilt(delta):
    """H3 (Remis-Struktur): EP-Max tippt nie Remis -> Remis-Outcome anheben,
    testen ob das Punkte bringt (T-0061 sagte nein; hier OOS-Re-Test)."""
    if delta == 0:
        return identity
    return lambda m: _shift_outcome(m, "draw", delta)


def draw_tilt_conditional(delta, tau=0.27):
    """H4: Remis-Tilt NUR auf remis-nahen Spielen (Modell-draw>=tau). Adressiert
    H3s Messer-Schneide -- gezielt statt flaechig. H8-geerdet: genau diese Spiele
    ziehen real 0.29 Remis (Modell deckelt bei 0.30, real 0.35) -> reale Luecke."""
    if delta == 0:
        return identity

    def t(m):
        return _shift_outcome(m, "draw", delta) if outcome_probabilities(m)["draw"] >= tau else m
    return t


def draw_decompress(gain, d0=0.247):
    """H10: glatte Quell-Entkompression statt H4-Stufentilt. H8 zeigt: Modell-Remis
    oben komprimiert (Gap ~+0.05 bei Modell-draw~0.30, ~0 am Mittel 0.247). Hebt die
    Remis-Masse linear mit dem Abstand ueberm Mittel an (delta = gain*(draw-d0), nur
    oberhalb d0 -- das ist die entscheidungs-relevante Haelfte, L2). gain=1.0 korrigiert
    den gemessenen Gap exakt (0.30->0.35). Prinzipientreuer als H4: kein harter tau,
    an der gemessenen Fehlkalibrierung geerdet, glatt (kein Cliff)."""
    if gain == 0:
        return identity

    def t(m):
        d = outcome_probabilities(m)["draw"]
        return _shift_outcome(m, "draw", gain * (d - d0)) if d > d0 else m
    return t


def draw_tilt_band(delta, lo=0.27, hi=0.99):
    """H12: flacher Remis-Tilt nur im Band [lo, hi) der Modell-draw-Wkt (reines
    L2-Boundary-Targeting). hi=0.99 == H4 (one-sided). Frage: schneidet ein oberer
    Cap die schaedlichen Flips weg (Spiele, die ohne Tilt richtig Nicht-Remis waeren)?"""
    if delta == 0:
        return identity

    def t(m):
        d = outcome_probabilities(m)["draw"]
        return _shift_outcome(m, "draw", delta) if lo <= d < hi else m
    return t


def _matrix_xg(matrix):
    """Erwartete Tore je Team aus der Score-Matrix (fuer Torhoehen-Banding)."""
    h = a = 0.0
    for label, p in matrix.items():
        hh, aa = (int(x) for x in label.split(":"))
        h += hh * p
        a += aa * p
    return h, a


def draw_scoreline_override(rule, lo=2.2, hi=3.0):
    """H9: Wenn EP-Max ein Remis tippt, die Remis-Scoreline per fester Regel ersetzen.
    None/'epmax' -> kein Override (modale Remis-Zelle aus EP-Max = argmax P(exact),
    weil falscher Remis nur Tendenz zaehlt, T-0097). 'k:k' -> fix. 'band' -> nach
    erwarteter Torsumme (0:0 / 1:1 / 2:2). Testet, ob die modale Remis-Zelle des
    Modells fehlkalibriert ist (H8: Modell-Remis oben komprimiert)."""
    if rule in (None, "epmax"):
        return None
    if rule == "band":
        def band(m):
            total = sum(_matrix_xg(m))
            return (0, 0) if total < lo else (1, 1) if total < hi else (2, 2)
        return band
    k = int(rule.split(":")[0])
    return lambda m: (k, k)


def count_draw_tips(rows_by_t, transform):
    """Wie viele Spiele tippt EP-Max als Remis unter diesem Transform (Tendenz-Recall)?"""
    n = 0
    for rows in rows_by_t.values():
        for row in rows:
            m = ensemble_calibrated_matrix(row.get("pre_elo") or None, row.get("pre_odds"))
            if m is None:
                continue
            tip = best_kicktipp_tip(transform(m), row.get("stage", "group"))
            if int(tip["home"]) == int(tip["away"]):
                n += 1
    return n


def diagnose_draw_scorelines(rows_by_t, delta=0.12, tau=0.27):
    """H9-Diagnose: unter dem H4-Tilt -- welche Remis-Zelle tippt EP-Max (modal),
    und wie sind die REALEN Remis-Scorelines verteilt, wenn wir Remis getippt haben?
    Wenn real 1:1 dominiert, EP-Max aber 0:0 tippt -> Override-Hebel."""
    transform = draw_tilt_conditional(delta, tau)
    tipped_cells, real_when_draw = {}, {}
    n_draw_tips = real_draws = 0
    for rows in rows_by_t.values():
        for row in rows:
            m = ensemble_calibrated_matrix(row.get("pre_elo") or None, row.get("pre_odds"))
            if m is None:
                continue
            m = transform(m)
            stage = row.get("stage", "group")
            tip = best_kicktipp_tip(m, stage)
            if int(tip["home"]) != int(tip["away"]):
                continue
            n_draw_tips += 1
            cell = f'{tip["home"]}:{tip["away"]}'
            tipped_cells[cell] = tipped_cells.get(cell, 0) + 1
            actual = actual_for_round(
                row["actual"], row.get("penalty_winner"), DEFAULT_ROUND_ID, row.get("shootout")
            )
            if actual.diff == 0:
                real_draws += 1
                real_when_draw[actual.label] = real_when_draw.get(actual.label, 0) + 1
    def fmt(d):
        return "  ".join(f"{k}:{v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))
    print(f"\n### H9-Diagnose: Remis-Tipps unter H4-Tilt (delta={delta}, tau={tau})")
    print(f"  Remis-Tipps gesamt: {n_draw_tips}  (davon real-Remis: {real_draws})")
    print(f"  EP-Max modale Tipp-Zelle: {fmt(tipped_cells)}")
    print(f"  REALE Remis-Scoreline (nur wenn Remis getippt & real Remis): {fmt(real_when_draw)}")


def _market_blend_calibrate(matrix, pre_odds, has_elo, market_weight=MW):
    """Spiegelt den Blend+Kalibrier-Teil von ensemble_calibrated_matrix: Markt-no-vig
    blenden (mit Favoriten-Override-Gate) und auf die Blend-Outcomes kalibrieren.
    Gemeinsam fuer dc_source_matrix (H13) und kappa_source_matrix (H14)."""
    model_probs = outcome_probabilities(matrix)
    market_probs = normalize_decimal_odds(pre_odds or {})
    market_for_blend = market_probs
    if has_elo and market_probs:
        mf = max(model_probs, key=model_probs.get)
        kf = max(market_probs, key=market_probs.get)
        if kf != mf and market_probs[kf] - model_probs[kf] < MARKET_OVERRIDE_THRESHOLD:
            market_for_blend = None
    if not market_for_blend:
        return dict(matrix)
    blended = blend_market_probabilities(model_probs, market_for_blend, weight=market_weight)
    return calibrate_score_matrix(matrix, blended)


def dc_source_matrix(pre_elo, pre_odds, rho, market_weight=MW):
    """H13/T-0104: Ensemble-Matrix, aber Dixon-Coles-rho auf die ROHE Poisson-Matrix
    VOR Blend+Kalibrierung. rho=0 == Baseline. WIRKT ueber Torhoehe (unterdrueckt
    1:0/0:1), nicht ueber Remis -- siehe L9."""
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, has_elo = xg
    matrix = dixon_coles_adjust(score_matrix(home_xg, away_xg), rho)
    return _market_blend_calibrate(matrix, pre_odds, has_elo, market_weight)


def kappa_source_matrix(pre_elo, pre_odds, kappa, market_weight=MW):
    """H14/T-0104: saubere Torhoehe -- xG beider Teams mit kappa skalieren (kappa>1 =
    hoehere Scorelines), dann Blend+Kalibrierung. Direkte, interpretierbare Variante des
    H13-Torhoehen-Hebels (statt rho-Seiteneffekt). kappa=1.0 == Baseline."""
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, has_elo = xg
    matrix = score_matrix(home_xg * kappa, away_xg * kappa)
    return _market_blend_calibrate(matrix, pre_odds, has_elo, market_weight)


def _source_points(rows, builder, theta, round_id=DEFAULT_ROUND_ID):
    pts = n = 0
    for row in rows:
        m = builder(row.get("pre_elo") or None, row.get("pre_odds"), theta)
        if m is None:
            continue
        stage = row.get("stage", "group")
        tip = best_kicktipp_tip(m, stage, round_id=round_id)
        actual = actual_for_round(
            row["actual"], row.get("penalty_winner"), round_id, row.get("shootout")
        )
        pts += kicktipp_points(Score(int(tip["home"]), int(tip["away"])), actual, stage, round_id)
        n += 1
    return pts, n


def lowmargin_source_matrix(pre_elo, pre_odds, gamma, market_weight=MW):
    """H15/T-0104: isoliert H13s Mechanismus -- nur 1:0 und 0:1 um (1-gamma) daempfen
    (die Zellen, die DC unterdrueckt), OHNE Remis explizit zu inflationieren. Testet, ob
    der Torhoehen-Hebel sauber ohne DCs Remis-Seiteneffekt reproduzierbar ist. gamma=0=Baseline."""
    xg = _xg_from_pre_match(pre_elo, pre_odds)
    if xg is None:
        return None
    home_xg, away_xg, has_elo = xg
    matrix = score_matrix(home_xg, away_xg)
    if gamma:
        matrix = dict(matrix)
        for lbl in ("1:0", "0:1"):
            matrix[lbl] = matrix.get(lbl, 0.0) * (1.0 - gamma)
        tot = sum(matrix.values()) or 1.0
        matrix = {k: v / tot for k, v in matrix.items()}
    return _market_blend_calibrate(matrix, pre_odds, has_elo, market_weight)


def dc_tournament_points(rows, rho, round_id=DEFAULT_ROUND_ID):
    return _source_points(rows, dc_source_matrix, rho, round_id)


def kappa_tournament_points(rows, kappa, round_id=DEFAULT_ROUND_ID):
    return _source_points(rows, kappa_source_matrix, kappa, round_id)


def lowmargin_tournament_points(rows, gamma, round_id=DEFAULT_ROUND_ID):
    return _source_points(rows, lowmargin_source_matrix, gamma, round_id)


# --------------------------------------------------------------------------- #
# Validierung + LOTO-CV
# --------------------------------------------------------------------------- #
def validate_baseline():
    rows_by_t = {t: load_rows(t) for t in TOURNAMENTS}
    pts = sum(tournament_points(rows_by_t[t], identity)[0] for t in TOURNAMENTS)
    n = sum(tournament_points(rows_by_t[t], identity)[1] for t in TOURNAMENTS)
    print(f"Baseline-Validierung (Identitaet, mw={MW}): {pts} Pkt / {n} Spiele = {pts/n:.4f} ppm")
    print(f"  Erwartet ~ ensemble 791 / 405 = 1.953  ->  {'OK' if abs(pts/n - 1.953) < 0.02 else 'ABWEICHUNG (Spiegel pruefen!)'}")
    return rows_by_t


def loto_cv(name, grid, score_fn, base, rows_by_t):
    """score_fn(rows, theta) -> (points, matches). base = Status-quo-theta."""
    tab = {t: {theta: score_fn(rows_by_t[t], theta) for theta in grid} for t in TOURNAMENTS}

    def agg(tours, theta):
        p = sum(tab[t][theta][0] for t in tours)
        m = sum(tab[t][theta][1] for t in tours)
        return p / m if m else 0.0

    def tppm(t, theta):
        return tab[t][theta][0] / tab[t][theta][1]

    full_best = max(grid, key=lambda th: agg(TOURNAMENTS, th))
    insample = agg(TOURNAMENTS, full_best) - agg(TOURNAMENTS, base)
    rows, oos_deltas = [], []
    for held in TOURNAMENTS:
        train = [t for t in TOURNAMENTS if t != held]
        th_star = max(grid, key=lambda th: agg(train, th))
        d = tppm(held, th_star) - tppm(held, base)
        oos_deltas.append(d)
        rows.append((held, th_star, d))
    oos = sum(oos_deltas) / len(oos_deltas)
    ahead = sum(1 for t in TOURNAMENTS if tppm(t, full_best) > tppm(t, base) + 1e-9)
    behind = sum(1 for t in TOURNAMENTS if tppm(t, full_best) < tppm(t, base) - 1e-9)
    keep = (oos > 1e-4) and (ahead > behind) and (insample > 0 and oos >= 0.5 * insample)

    print(f"\n### Hypothese: {name}")
    print("  ppm je theta (aggregiert ueber 405): " +
          "  ".join(f"{th}:{agg(TOURNAMENTS, th):.4f}" for th in grid))
    print(f"  In-Sample-Optimum theta*={full_best} (Status quo={base}): {insample:+.4f} ppm (kann overfitten)")
    print(f"  Per-Turnier @ theta*: ahead {ahead} / behind {behind} / neutral {7-ahead-behind}")
    print("  LOTO-CV (theta* je auf 6 trainiert, auf dem 7. gemessen):")
    for held, th, d in rows:
        print(f"    held-out {held:<10} theta*={str(th):<5} -> {d:+.4f} ppm")
    print(f"  ** OOS-Delta (Mittel): {oos:+.4f} ppm   Overfit-Gap (In-Sample - OOS): {insample-oos:+.4f}")
    print(f"  ** VERDIKT: {'KEEP (generalisiert)' if keep else 'REVERT'}  "
          f"[OOS>0:{oos>1e-4} | ahead>behind:{ahead>behind} | OOS>=0.5*InSample:"
          f"{insample>0 and oos>=0.5*insample}]")
    return keep


def main():
    print("CV-Backtest-Harness -- Leave-One-Tournament-Out (7 Turniere, 405 Spiele)\n")
    rows_by_t = validate_baseline()
    loto_cv("H1 Favoriten-Confidence-Boost (T-0084)", [0, 0.03, 0.06, 0.10],
            lambda rows, th: tournament_points(rows, favorite_boost(th)), 0, rows_by_t)
    loto_cv("H2 Markt-Blend-Gewicht (Status quo 0.20)", [0.0, 0.10, 0.20, 0.35, 0.50],
            lambda rows, th: tournament_points(rows, identity, market_weight=th), 0.20, rows_by_t)
    loto_cv("H3 Remis-Tilt uniform (T-0061 Re-Test) -- Messer-Schneide", [0, 0.04, 0.06, 0.07, 0.10],
            lambda rows, th: tournament_points(rows, draw_tilt(th)), 0, rows_by_t)
    print("  H3-Hinweis: +8 nur Band 0.04-0.06; ab 0.07 Cliff (-5 -> -45 bei 0.12). Fragil.")
    loto_cv("H4 Remis-Tilt conditional (nur draw>=0.27) -- gezielt, H8-geerdet", [0, 0.06, 0.12, 0.20],
            lambda rows, th: tournament_points(rows, draw_tilt_conditional(th)), 0, rows_by_t)
    print("  H4-Hinweis: flaches +4-Plateau ueber alle delta (kein Cliff) -> robust, aber kleiner als H3.")
    print("  H8-Befund: Modell-Remis im Schnitt kalibriert (0.246 vs real 0.247), aber oben komprimiert")
    print("  (Bin 0.30 -> real 0.35, deckelt 0.303). -> H4 ist die geerdete, robuste Version von H3.")

    # ----- H9: Remis-Scoreline-Override (auf dem H4-Tilt) ---------------------
    diagnose_draw_scorelines(rows_by_t, delta=0.12)
    loto_cv("H9 Remis-Scoreline-Override (auf H4-Tilt delta=0.12) -- 'epmax' = modaler Remis",
            [None, "0:0", "1:1", "2:2", "band"],
            lambda rows, th: tournament_points(rows, draw_tilt_conditional(0.12),
                                               draw_override=draw_scoreline_override(th)),
            None, rows_by_t)
    print("  H9-Frage: schlaegt eine feste Remis-Scoreline die modale EP-Max-Zelle?")
    print("  (EP-Max waehlt bereits argmax P(exact-Remis); Override hilft nur bei Scoreline-Fehlkalibrierung.)")

    # ----- H10: Quell-Entkompression (glatt) statt H4-Stufentilt ---------------
    for g in (0.5, 1.0, 1.5):
        print(f"  H10-Diagnose: gain={g} -> {count_draw_tips(rows_by_t, draw_decompress(g))} "
              f"Remis-Tipps  (H4-Tilt delta=0.12 -> 25)")
    loto_cv("H10 Remis-Quell-Entkompression (glatt, gain*(draw-0.247)) -- vs H4-Stufentilt",
            [0.0, 0.5, 1.0, 1.5],
            lambda rows, th: tournament_points(rows, draw_decompress(th)), 0.0, rows_by_t)
    print("  H10-Frage: erreicht der glatte, an H8 geerdete Lift H4s OOS (+0.016) ohne Cliff/harten tau?")
    print("  Direktvergleich: H4 ist Stufe (>=tau flat), H10 ist Rampe (proportional zur Kompression).")

    # ----- H11: Tau-Gate-Sweep -- vertieft H4 (Robustheit, kein neuer Hebel) ----
    loto_cv("H11 Tau-Gate-Sweep (H4 flat delta=0.06; tau=0.99 = Tilt AUS) -- Robustheit von H4",
            [0.22, 0.25, 0.27, 0.30, 0.33, 0.99],
            lambda rows, th: tournament_points(rows, draw_tilt_conditional(0.06, th)), 0.99, rows_by_t)
    print("  H11-Frage: ist H4 ein PLATEAU in tau (0.22-0.33 alle > tau=0.99/aus -> robust)")
    print("  oder ein Messer (nur 0.27 wirkt)? Bestaetigt/widerlegt den einzigen KEEP von einer 2. Achse.")

    # ----- H12: Boundary-Band-Tilt -- bringt ein oberer Cap was gegen H4? -------
    loto_cv("H12 Boundary-Band-Tilt (flat delta=0.06, lo=0.27, hi variiert; hi=0.99 == H4)",
            [0.30, 0.35, 0.45, 0.99],
            lambda rows, th: tournament_points(rows, draw_tilt_band(0.06, 0.27, th)), 0.99, rows_by_t)
    print("  H12-Frage: schneidet ein oberer Cap hi schaedliche Flips weg, oder ist H4 schon optimal?")
    print("  (Base=0.99=H4. REVERT hier heisst: kein Cap schlaegt H4 -> H4 bleibt der Kandidat.)")

    # ----- H13/T-0104: Dixon-Coles-rho an der QUELLE (Remis-Entkompression) -----
    loto_cv("H13 Dixon-Coles-rho at-source (T-0104, Remis-Entkompression vor Blend)",
            [0.0, -0.05, -0.10, -0.15, -0.20],
            lambda rows, th: dc_tournament_points(rows, th), 0.0, rows_by_t)
    print("  H13-Hinweis: in-sample steigt ppm monoton Richtung Grid-Rand (-0.15=803=+12), und")
    print("  draw>=0.30 springt 2->90 -> Verdacht uniformer Tilt (wie H3). fit_rho(loglik)=0.")
    print("  Mechanismus: 47/49 Tipp-Aenderungen sind 1:0->2:1 (TORHOEHE), nur 1 Remis -> L9.")

    # ----- H14/T-0104: saubere Torhoehe (xG-Scale kappa) statt rho-Seiteneffekt ----
    loto_cv("H14 Torhoehen-Scale kappa at-source (T-0104, saubere Variante von H13)",
            [1.0, 1.05, 1.10, 1.15, 1.20],
            lambda rows, th: kappa_tournament_points(rows, th), 1.0, rows_by_t)
    print("  H14-Frage: erreicht ein direkter, interpretierbarer xG-Scale H13s OOS (+0.030)?")
    print("  Wenn ja -> sauberer Hebel als rho=-0.15; wenn nein -> DCs spezifische Form (1:0/0:1-Cut) zaehlt.")

    # ----- H15/T-0104: nur 1:0/0:1 daempfen (DC-Mechanismus ohne Remis-Inflation) --
    loto_cv("H15 Low-Margin-Daempfung kappa (nur 1:0/0:1, T-0104, sauberer DC-Kern)",
            [0.0, 0.2, 0.4, 0.6, 0.8],
            lambda rows, th: lowmargin_tournament_points(rows, th), 0.0, rows_by_t)
    print("  H15-Frage: reproduziert reine 1:0/0:1-Daempfung H13s Gewinn OHNE Remis-Inflation?")
    print("  H15~=H13 -> Hebel ist genau die 1:0/0:1-Uebergewichtung (sauberster Adopt-Kandidat).")


if __name__ == "__main__":
    main()
