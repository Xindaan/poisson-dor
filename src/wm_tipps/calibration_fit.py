"""Within-class Recalibration -- Offline-Fit (T-0073, Teil 1).

Read-only Diagnose: Der Markt pinnt die Klassenmassen (Heimsieg/Remis/
Auswaerts via 1X2 x O/U). Was die realisierten Scorelines zusaetzlich
lehren, ist die *bedingte* Form P(s | Klasse) -- genau dort, wo die
Exaktpunkte (4/6/8) fallen. Eine globale Temperatur T reskaliert die Form
innerhalb der Klasse, OHNE die (markt-kalibrierten) Klassenmassen zu
veraendern:

    P'(s) = q_c * P(s)^(1/T) / sum_{s' in c} P(s')^(1/T)

T > 1  -> Modell ist innerhalb der Klasse zu scharf (Form abflachen),
T < 1  -> zu unscharf (Form zuspitzen).

Gefittet per penalisierter Profil-Likelihood ueber den 7-Turnier-Backtest
(realisierte Scorelines), mit quadratischem Prior auf ln T (N0 Pseudo-
Spiele) gegen Overfit. NUR Diagnose -- die Live-Anwendung (Wiring in die
Kalibrierung) folgt separat MIT Backtest-on/off-Validierung, plus der
Dixon-Coles-rho-Teil.
"""
from __future__ import annotations

from math import log
from typing import Any

from .backtest import default_report_datasets, ensemble_calibrated_matrix
from .historical import build_historical_dataset
from .io import read_json, write_json
from .model import ENSEMBLE_MARKET_BLEND_WEIGHT, dixon_coles_adjust  # dixon_coles_adjust: re-export (T-0104)
from .paths import DATA_DIR, EXPORTS_DIR

CALIBRATION_FIT_PATH = DATA_DIR / "calibration_fit.json"
CALIBRATION_FIT_MARKDOWN_PATH = EXPORTS_DIR / "calibration_fit.md"

# Grid 0.70..1.40 Schritt 0.05.
TEMPERATURE_GRID = tuple(round(0.70 + 0.05 * i, 2) for i in range(15))
# Prior: N0 Pseudo-Spiele zentriert auf T=1 (ln T = 0), SD auf ln-Skala.
TEMPERATURE_PRIOR_PSEUDO = 25.0
TEMPERATURE_PRIOR_LOG_SD = 0.15
# Dixon-Coles rho: niedrige Zellen {0:0,0:1,1:0,1:1}. rho<0 -> Remis (0:0/1:1)
# haeufiger als unabhaengiges Poisson, 1:0/0:1 seltener. Grid -0.15..0.10.
RHO_GRID = tuple(round(-0.15 + 0.01 * i, 2) for i in range(26))
RHO_PRIOR_PSEUDO = 25.0
RHO_PRIOR_SD = 0.08
# T-0078: Markt-Blend-Gewicht w per Scoreline-Likelihood (statt Punkte wie
# blend-sweep -- variaermer). Empfehlung nur, wenn der Gewinn vs Live-0.15
# substanziell ist.
BLEND_WEIGHT_GRID = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
_EPS = 1e-12


def _outcome_class(label: str) -> str:
    home, away = (int(part) for part in label.split(":"))
    return "H" if home > away else ("A" if away > home else "D")


def temper_within_class(matrix: dict[str, float], temperature: float) -> dict[str, float]:
    """Form innerhalb jeder Ergebnis-Klasse mit Temperatur T reskalieren,
    Klassenmasse exakt erhalten."""
    if temperature == 1.0:
        return dict(matrix)
    classes: dict[str, list[tuple[str, float]]] = {}
    for label, probability in matrix.items():
        classes.setdefault(_outcome_class(label), []).append((label, probability))
    out: dict[str, float] = {}
    for cells in classes.values():
        mass = sum(p for _, p in cells)
        powered = [(label, p ** (1.0 / temperature)) for label, p in cells]
        norm = sum(p for _, p in powered) or 1.0
        for label, p in powered:
            out[label] = mass * p / norm
    return out


def _loglik(matches: list[tuple[dict[str, float], str]], temperature: float) -> float:
    total = 0.0
    for matrix, actual in matches:
        tempered = temper_within_class(matrix, temperature)
        total += log(max(_EPS, tempered.get(actual, 0.0)))
    return total


def fit_temperature(matches: list[tuple[dict[str, float], str]]) -> dict[str, Any]:
    rows = []
    best_T, best_obj = 1.0, None
    base_ll = None
    for temperature in TEMPERATURE_GRID:
        ll = _loglik(matches, temperature)
        prior = -(TEMPERATURE_PRIOR_PSEUDO / 2.0) * (log(temperature) / TEMPERATURE_PRIOR_LOG_SD) ** 2
        obj = ll + prior
        rows.append({"T": temperature, "loglik": round(ll, 3), "penalized": round(obj, 3)})
        if temperature == 1.0:
            base_ll = ll
        if best_obj is None or obj > best_obj:
            best_obj, best_T = obj, temperature
    return {"best_T": best_T, "base_loglik": round(base_ll, 3) if base_ll is not None else None,
            "best_loglik": round(_loglik(matches, best_T), 3), "grid": rows}


def assemble_backtest_rows() -> list[tuple[Any, Any, str]]:
    """(pre_elo, pre_odds, realisierte Scoreline) je odds-gedecktem Spiel --
    Rohinputs, damit die Matrix fuer verschiedene Blend-Gewichte neu gebaut
    werden kann (T-0078)."""
    rows: list[tuple[Any, Any, str]] = []
    for name, path in default_report_datasets():
        build_historical_dataset(name)
        for row in read_json(path, {}).get("results", []):
            actual = row.get("actual")
            if not row.get("pre_odds") or not actual or len(actual) != 2:
                continue
            rows.append((row.get("pre_elo"), row.get("pre_odds"), f"{int(actual[0])}:{int(actual[1])}"))
    return rows


def fit_blend_weight(rows: list[tuple[Any, Any, str]]) -> dict[str, Any]:
    live = round(ENSEMBLE_MARKET_BLEND_WEIGHT, 4)
    grid_weights = sorted(set(BLEND_WEIGHT_GRID) | {live})
    logliks: dict[float, float] = {}
    for weight in grid_weights:
        total = 0.0
        for pre_elo, pre_odds, actual in rows:
            matrix = ensemble_calibrated_matrix(pre_elo, pre_odds, market_weight=weight)
            if matrix:
                total += log(max(_EPS, matrix.get(actual, 0.0)))
        logliks[weight] = total
    best_w = max(logliks, key=lambda w: logliks[w])
    gain = round(logliks[best_w] - logliks.get(live, logliks[best_w]), 3)
    return {
        "best_weight": best_w,
        "live_weight": live,
        "loglik_gain_vs_live": gain,
        "grid": [{"weight": w, "loglik": round(logliks[w], 3)} for w in grid_weights],
    }


def _rho_loglik(matches: list[tuple[dict[str, float], str]], rho: float) -> float:
    total = 0.0
    for matrix, actual in matches:
        adjusted = dixon_coles_adjust(matrix, rho)
        total += log(max(_EPS, adjusted.get(actual, 0.0)))
    return total


def fit_rho(matches: list[tuple[dict[str, float], str]]) -> dict[str, Any]:
    rows = []
    best_rho, best_obj, base_ll = 0.0, None, None
    for rho in RHO_GRID:
        ll = _rho_loglik(matches, rho)
        prior = -(RHO_PRIOR_PSEUDO / 2.0) * (rho / RHO_PRIOR_SD) ** 2
        obj = ll + prior
        rows.append({"rho": rho, "loglik": round(ll, 3), "penalized": round(obj, 3)})
        if rho == 0.0:
            base_ll = ll
        if best_obj is None or obj > best_obj:
            best_obj, best_rho = obj, rho
    return {"best_rho": best_rho, "base_loglik": round(base_ll, 3) if base_ll is not None else None,
            "best_loglik": round(_rho_loglik(matches, best_rho), 3), "grid": rows}


def build_calibration_fit(*, matches: list[tuple[dict[str, float], str]] | None = None,
                          write: bool = True) -> dict[str, Any]:
    rows: list[tuple[Any, Any, str]] | None = None
    if matches is None:
        rows = assemble_backtest_rows()
        matches = [(ensemble_calibrated_matrix(elo, odds), actual) for elo, odds, actual in rows]
        matches = [(matrix, actual) for matrix, actual in matches if matrix]
    fit = fit_temperature(matches)
    best_T = fit["best_T"]
    sharpness = ("zu scharf (Form abflachen)" if best_T > 1.0 else
                 "zu unscharf (Form zuspitzen)" if best_T < 1.0 else "gut kalibriert")
    delta = (round(fit["best_loglik"] - fit["base_loglik"], 3)
             if fit["base_loglik"] is not None else None)
    rho_fit = fit_rho(matches)
    best_rho = rho_fit["best_rho"]
    rho_delta = (round(rho_fit["best_loglik"] - rho_fit["base_loglik"], 3)
                 if rho_fit["base_loglik"] is not None else None)
    rho_reading = ("Remis (0:0/1:1) untergewichtet -> rho<0 wuerde sie anheben" if best_rho < 0 else
                   "Remis ueberbewertet -> rho>0" if best_rho > 0 else "niedrige Zellen gut kalibriert")
    blend_fit = fit_blend_weight(rows) if rows is not None else None
    meta = {
        "matches": len(matches),
        "best_temperature": best_T,
        "within_class_sharpness": sharpness,
        "loglik_gain_vs_T1": delta,
        "best_rho": best_rho,
        "rho_reading": rho_reading,
        "loglik_gain_vs_rho0": rho_delta,
        "note": "Read-only Diagnose. Eine Live-Anwendung nur, wenn T!=1 / rho!=0 / "
                "w abweicht UND der Backtest-on/off-Vergleich es bestaetigt.",
    }
    if blend_fit:
        meta["best_blend_weight"] = blend_fit["best_weight"]
        meta["live_blend_weight"] = blend_fit["live_weight"]
        meta["blend_loglik_gain_vs_live"] = blend_fit["loglik_gain_vs_live"]
    payload = {"_meta": meta, "temperature": fit, "rho": rho_fit, "blend": blend_fit}
    if write:
        write_json(CALIBRATION_FIT_PATH, payload)
        CALIBRATION_FIT_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_FIT_MARKDOWN_PATH.write_text(calibration_fit_markdown(payload), encoding="utf-8")
    return payload


def calibration_fit_markdown(payload: dict[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# Within-class Kalibrier-Fit (Offline, Backtest)",
        "",
        f"- Spiele (odds-gedeckt): **{meta.get('matches', 0)}**",
        f"- bestes T: **{meta.get('best_temperature')}** -- {meta.get('within_class_sharpness')}",
        f"- Log-Likelihood-Gewinn vs T=1: **{meta.get('loglik_gain_vs_T1')}**",
        f"- bestes rho (Dixon-Coles): **{meta.get('best_rho')}** -- {meta.get('rho_reading')}",
        f"- Log-Likelihood-Gewinn vs rho=0: **{meta.get('loglik_gain_vs_rho0')}**",
        f"- bestes Markt-Blend-Gewicht w: **{meta.get('best_blend_weight')}** "
        f"(live {meta.get('live_blend_weight')}, Gewinn {meta.get('blend_loglik_gain_vs_live')})",
        "",
        meta.get("note", ""),
        "",
        "## Grid",
        "",
        "| T | logLik | penalized |",
        "|---|---|---|",
    ]
    for row in (payload.get("temperature") or {}).get("grid", []):
        lines.append(f"| {row['T']} | {row['loglik']} | {row['penalized']} |")
    return "\n".join(lines).rstrip() + "\n"
