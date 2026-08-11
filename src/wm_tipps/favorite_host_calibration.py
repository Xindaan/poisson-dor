"""Favoriten-/Gastgeber-Kalibrierung gegen den Backtest (T-0084).

Befund aus dem Live-Quotencheck (18 Spiele, 2026-06-14): das Modell ist auf
Favoriten durchgaengig konservativer als Markt/oddschecker-AI; Gastgeber USA
wird nur durch den +0.18-xG-Bonus knapp ueber 50% gehoben. Diese Diagnose
prueft das gegen die 405 historischen Spiele -- mit Backtest-Beleg, nicht
gegen ein Fremdmodell (stehende Regel).

Zwei Fragen, beide read-only:

1. FAVORITEN-KALIBRIERUNG: Spiele nach vom Modell prognostizierter Favoriten-
   Siegwahrscheinlichkeit gebinnt; je Bin die TATSAECHLICHE Favoriten-Siegrate
   vs. Modell/Ensemble/Markt-Prognose. Liegt die Realrate ueber der Modell-
   Prognose (positiver Gap), ist das Modell favoritenspezifisch under-confident.
   Markt als Referenz (besser kalibriert?).

2. GASTGEBER-KALIBRIERUNG: nur Gastgeber-Spiele (Host spielt im eigenen
   Turnier). Der Backtest rekonstruiert xG OHNE Host-Bonus -> der rohe Gap
   (Real-Siegrate minus Elo-Prognose) ist der echte Heimturnier-Effekt. Wir
   rechnen zusaetzlich den Live-Bonus +0.18 xG konkret nach: schliesst er den
   Gap (richtig dimensioniert), oder bleibt Rest (zu klein)?

Verdikt nur als Empfehlung -- KEIN Auto-Override des Modells.
"""
from __future__ import annotations

import statistics
from typing import Any, Mapping

from .backtest import _xg_from_pre_match, default_report_datasets, ensemble_calibrated_matrix
from .historical import build_historical_dataset
from .io import read_json, write_json
from .model import outcome_probabilities, score_matrix
from .odds import normalize_decimal_odds
from .paths import DATA_DIR, EXPORTS_DIR

FAV_HOST_PATH = DATA_DIR / "favorite_host_calibration.json"
FAV_HOST_MARKDOWN_PATH = EXPORTS_DIR / "favorite_host_calibration.md"

# Einzel-Gastgeber-Turniere (euro-2020 Multi-Host -> ausgenommen).
TOURNAMENT_HOSTS = {
    "2010": "South Africa", "2014": "Brazil", "2018": "Russia", "2022": "Qatar",
    "euro-2016": "France", "euro-2024": "Germany",
}
FAV_BINS = ((0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.85), (0.85, 1.01))
HOST_XG_BONUS = 0.18  # der Live-Gastgeberbonus (USA/MEX/CAN), hier nachgerechnet


def _outcome(actual) -> str:
    h, a = int(actual[0]), int(actual[1])
    return "home" if h > a else ("away" if a > h else "draw")


def _bin(p: float):
    for lo, hi in FAV_BINS:
        if lo <= p < hi:
            return (lo, hi)
    return None


def _model_probs(pre_elo) -> dict[str, float] | None:
    xg = _xg_from_pre_match(pre_elo)  # reine Elo-xG, kein Markt, kein Host-Bonus
    if xg is None:
        return None
    return outcome_probabilities(score_matrix(xg[0], xg[1]))


def _ensemble_probs(pre_elo, pre_odds) -> dict[str, float] | None:
    matrix = ensemble_calibrated_matrix(pre_elo, pre_odds)
    return outcome_probabilities(matrix) if matrix else None


def _collect(rows):
    """Pro Zeile: (model, ensemble, market, outcome, row). model immer da,
    market/ensemble ggf. None."""
    out = []
    for row in rows:
        actual = row.get("actual")
        pre_elo = row.get("pre_elo")
        if not actual or len(actual) != 2 or not pre_elo:
            continue
        model = _model_probs(pre_elo)
        if not model:
            continue
        pre_odds = row.get("pre_odds")
        ens = _ensemble_probs(pre_elo, pre_odds)
        mkt = normalize_decimal_odds(pre_odds or {}) or None
        out.append((model, ens, mkt, _outcome(actual), row))
    return out


def _favorite_calibration(samples) -> dict[str, Any]:
    bins = {f"{lo}-{hi}": {"lo": lo, "hi": hi, "n": 0, "fav_wins": 0,
                           "sum_model": 0.0, "sum_ens": 0.0, "sum_mkt": 0.0, "mkt_n": 0}
            for lo, hi in FAV_BINS}
    tot = {"n": 0, "gap_model": 0.0, "gap_ens": 0.0, "gap_mkt": 0.0, "mkt_n": 0}
    for model, ens, mkt, outcome, _row in samples:
        fav = "home" if model["home"] >= model["away"] else "away"
        p = model[fav]
        b = _bin(p)
        if b is None:
            continue
        key = f"{b[0]}-{b[1]}"
        rec = bins[key]
        won = int(outcome == fav)
        rec["n"] += 1
        rec["fav_wins"] += won
        rec["sum_model"] += p
        rec["sum_ens"] += ens[fav] if ens else p
        tot["n"] += 1
        tot["gap_model"] += won - p
        tot["gap_ens"] += won - (ens[fav] if ens else p)
        if mkt:
            rec["sum_mkt"] += mkt[fav]
            rec["mkt_n"] += 1
            tot["gap_mkt"] += won - mkt[fav]
            tot["mkt_n"] += 1
    rows = []
    for key, r in bins.items():
        if not r["n"]:
            continue
        rows.append({
            "bin": key,
            "matches": r["n"],
            "actual_fav_winrate": round(r["fav_wins"] / r["n"], 4),
            "model_pred": round(r["sum_model"] / r["n"], 4),
            "ensemble_pred": round(r["sum_ens"] / r["n"], 4),
            "market_pred": round(r["sum_mkt"] / r["mkt_n"], 4) if r["mkt_n"] else None,
        })
    n = tot["n"] or 1
    return {
        "bins": rows,
        "matches": tot["n"],
        "mean_gap_model": round(tot["gap_model"] / n, 4),  # >0 == Modell under-confident
        "mean_gap_ensemble": round(tot["gap_ens"] / n, 4),
        "mean_gap_market": round(tot["gap_mkt"] / tot["mkt_n"], 4) if tot["mkt_n"] else None,
    }


def _host_calibration(host_rows) -> dict[str, Any]:
    """host_rows: (host_side, pre_elo, pre_odds, model, ens, mkt, outcome)."""
    n = 0
    wins = 0
    sum_model = sum_ens = sum_mkt = sum_bonus = 0.0
    mkt_n = 0
    details = []
    for host_side, pre_elo, pre_odds, model, ens, mkt, outcome, label in host_rows:
        xg = _xg_from_pre_match(pre_elo)
        if xg is None:
            continue
        home_xg, away_xg = xg[0], xg[1]
        # No-Bonus und +0.18-Bonus aus DENSELBEN xG -> garantiert gleiche Basis:
        no_bonus_probs = outcome_probabilities(score_matrix(home_xg, away_xg))
        if host_side == "home":
            bonus_probs = outcome_probabilities(score_matrix(home_xg + HOST_XG_BONUS, away_xg))
        else:
            bonus_probs = outcome_probabilities(score_matrix(home_xg, away_xg + HOST_XG_BONUS))
        won = int(outcome == host_side)
        n += 1
        wins += won
        sum_model += no_bonus_probs[host_side]
        sum_ens += ens[host_side] if ens else model[host_side]
        sum_bonus += bonus_probs[host_side]
        if mkt:
            sum_mkt += mkt[host_side]
            mkt_n += 1
        details.append({"match": label, "host_won": bool(won),
                        "model": round(model[host_side], 3), "with_bonus": round(bonus_probs[host_side], 3)})
    if not n:
        return {"matches": 0}
    actual = wins / n
    return {
        "matches": n,
        "actual_host_winrate": round(actual, 4),
        "model_pred_no_bonus": round(sum_model / n, 4),
        "model_pred_with_bonus_018": round(sum_bonus / n, 4),
        "ensemble_pred": round(sum_ens / n, 4),
        "market_pred": round(sum_mkt / mkt_n, 4) if mkt_n else None,
        "raw_host_effect": round(actual - sum_model / n, 4),  # roher Heimturnier-Effekt (pp)
        "residual_after_bonus": round(actual - sum_bonus / n, 4),  # was +0.18 NICHT abdeckt
        "details": details,
    }


def build_favorite_host_calibration(*, write: bool = True) -> dict[str, Any]:
    all_samples = []
    host_rows = []
    for name, path in default_report_datasets():
        build_historical_dataset(name)
        rows = read_json(path, {}).get("results", [])
        samples = _collect(rows)
        all_samples.extend(samples)
        host = TOURNAMENT_HOSTS.get(name)
        if not host:
            continue
        for model, ens, mkt, outcome, row in samples:
            if host == row.get("home"):
                side = "home"
            elif host == row.get("away"):
                side = "away"
            else:
                continue
            label = f"{name}: {row.get('home')} - {row.get('away')} {row.get('actual')}"
            host_rows.append((side, row.get("pre_elo"), row.get("pre_odds"), model, ens, mkt, outcome, label))

    favorites = _favorite_calibration(all_samples)
    hosts = _host_calibration(host_rows)
    verdict = _verdict(favorites, hosts)

    payload = {
        "_meta": {
            "backtest_matches": len(all_samples),
            "host_matches": hosts.get("matches", 0),
            "host_bonus_tested": HOST_XG_BONUS,
            "verdict": verdict,
            "note": ("Read-only. Modell = reine Elo-xG (kein Host-Bonus, kein Markt); "
                     "Ensemble = Live-Tipp-Matrix (80/20-Blend); Markt = de-vigte pre_odds. "
                     "Gap>0 = Realrate ueber Prognose (under-confident). Kein Auto-Override."),
        },
        "favorites": favorites,
        "hosts": hosts,
    }
    if write:
        write_json(FAV_HOST_PATH, payload)
        FAV_HOST_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAV_HOST_MARKDOWN_PATH.write_text(favorite_host_markdown(payload), encoding="utf-8")
    return payload


def _verdict(favorites: Mapping[str, Any], hosts: Mapping[str, Any]) -> str:
    parts = []
    gm = favorites.get("mean_gap_model")
    gk = favorites.get("mean_gap_market")
    if gm is not None:
        if gm > 0.03:
            ref = f", Markt-Gap {gk:+.3f}" if gk is not None else ""
            parts.append(f"Favoriten: Modell under-confident (Gap {gm:+.3f}{ref}) -> Markt-Blend hilft")
        elif gm < -0.03:
            parts.append(f"Favoriten: Modell OVER-confident (Gap {gm:+.3f})")
        else:
            parts.append(f"Favoriten: gut kalibriert (Gap {gm:+.3f})")
    if hosts.get("matches"):
        raw = hosts["raw_host_effect"]
        resid = hosts["residual_after_bonus"]
        if raw <= 0.02:
            parts.append(f"Gastgeber: kein nennenswerter Roh-Effekt ({raw:+.3f}, n={hosts['matches']})")
        elif abs(resid) <= 0.05:
            parts.append(f"Gastgeber: Roh-Effekt {raw:+.3f}, +0.18 deckt ihn (~Rest {resid:+.3f}) -> adaequat")
        elif resid > 0.05:
            parts.append(f"Gastgeber: Roh-Effekt {raw:+.3f}, +0.18 zu KLEIN (Rest {resid:+.3f}, n={hosts['matches']})")
        else:
            parts.append(f"Gastgeber: +0.18 ueberzieht (Rest {resid:+.3f})")
    return " | ".join(parts) if parts else "keine Daten"


def favorite_host_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    fav = payload.get("favorites") or {}
    host = payload.get("hosts") or {}
    lines = [
        "# Favoriten-/Gastgeber-Kalibrierung (T-0084)",
        "",
        f"- Backtest: **{meta.get('backtest_matches', 0)}** Spiele, davon **{meta.get('host_matches', 0)}** Gastgeber-Spiele",
        f"- **Verdikt:** {meta.get('verdict')}",
        "",
        meta.get("note", ""),
        "",
        "## 1. Favoriten-Kalibrierung (Reliability je Modell-Prob-Bin)",
        "",
        "Real = tatsaechliche Favoriten-Siegrate. Gap = Real - Prognose (>0 = under-confident).",
        "",
        "| Bin (Modell) | Spiele | Real | Modell | Ensemble | Markt |",
        "|---|---|---|---|---|---|",
    ]
    for r in fav.get("bins", []):
        mkt = r["market_pred"] if r["market_pred"] is not None else "-"
        lines.append(
            f"| {r['bin']} | {r['matches']} | {r['actual_fav_winrate']} | "
            f"{r['model_pred']} | {r['ensemble_pred']} | {mkt} |"
        )
    lines += [
        "",
        f"- Mittlerer Gap **Modell {fav.get('mean_gap_model'):+.3f}** · "
        f"Ensemble {fav.get('mean_gap_ensemble'):+.3f} · "
        f"Markt {fav.get('mean_gap_market') if fav.get('mean_gap_market') is not None else '-'}",
        "",
        "## 2. Gastgeber-Kalibrierung (+0.18-xG-Bonus nachgerechnet)",
        "",
    ]
    if host.get("matches"):
        lines += [
            f"| Groesse | Wert |",
            "|---|---|",
            f"| Gastgeber-Spiele | {host['matches']} |",
            f"| Reale Host-Siegrate | {host['actual_host_winrate']} |",
            f"| Modell-Prognose (ohne Bonus) | {host['model_pred_no_bonus']} |",
            f"| Modell-Prognose (+0.18 xG) | {host['model_pred_with_bonus_018']} |",
            f"| Markt-Prognose | {host['market_pred'] if host['market_pred'] is not None else '-'} |",
            f"| Roher Host-Effekt (Real - ohne Bonus) | **{host['raw_host_effect']:+.3f}** |",
            f"| Rest nach +0.18 (Real - mit Bonus) | **{host['residual_after_bonus']:+.3f}** |",
        ]
    else:
        lines.append("- keine Gastgeber-Spiele gefunden")
    return "\n".join(lines).rstrip() + "\n"
