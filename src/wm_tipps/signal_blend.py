"""T-0136: Signal-abhaengiges Blend-Vertrauen (forward-gated, default AUS).

Befund (2026-07-06, Quoten-Analyse): der globale Markt-Blend
(`model.ENSEMBLE_MARKET_BLEND_WEIGHT=0.20`) ueberschreibt gelegentlich einen
KORREKTEN Modell-Read, wenn das Modell aus HARTEN Kontext-Signalen (bestaetigter
Ausfall/News, Hoehe, Reise) heraus eine andere Seite favorisiert als der Markt
(Bsp Brasilien-Norwegen: Modell favorisierte Norwegen wegen Brasilien-Ausfaellen,
der 20%-Blend zog den Tipp auf Brasilien -> verlor). Eine GLOBALE Blend-Aenderung
ist ausgeschlossen (Ensemble +20 vs reine Quote, Sweep-Optimum 0.20, CV-bestaetigt;
der Markt schlaegt das Modell live 3:1 bei Uneinigkeit). Dieser Hebel senkt das
Markt-Gewicht NUR fuer das einzelne Spiel, wenn die Modell-Gegenposition
SIGNAL-getrieben ist (nicht weiches Elo-Kippeln).

WICHTIGER VORBEHALT (unbewiesene Praemisse): Der Hebel unterstellt, dass der Markt
harte Signale UNTERschaetzt. Buchmacher preisen Ausfaelle aber i.d.R. effizient ein
-> das Modell koennte doppelt zaehlen. Der Motivationsfall (Brasilien-Norwegen) ist
n=1 und kann Varianz sein (Norwegen war ~24%). Das ist ein Experiment, keine
belegte Verbesserung.

NICHT backtestbar: `data/backtest_*.json` enthaelt pro Spiel nur Elo-Snapshot +
Quoten + Ergebnis, KEINE News/Ausfall/Hoehe/Reise-Signale -> kein `xg_breakdown`
rekonstruierbar. Wie LINEUP_ABSENCE (T-0113) also nur forward-validierbar, default
AUS; Aktivierung erst nach Sichtung des Live-Tipp-Diffs durch den Betreiber.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Gate (Modul-Konstante, default False; via `enabled=`-Param ueberschreibbar) ---
SIGNAL_AWARE_BLEND_ENABLED = False

# Harte Kontext-Signale, die eine Modell-Gegenposition rechtfertigen koennen
# (Betraege der xg_breakdown-Komponenten, summiert ueber beide Seiten). news/lineup
# = bestaetigte Ausfaelle (haertestes Signal); altitude/travel = physische Faktoren.
HARD_SIGNAL_KEYS = (
    "news_effect",
    "lineup_absence_effect",
    "altitude_effect",
    "travel_effect",
)
# Mindest-Signalstaerke, ab der die Uneinigkeit als signal-getrieben gilt (statt
# Elo-Rauschen). ~0.15: ein bestaetigter Ausfall (news ~0.18) triggert, ambientes
# Hoehe+Reise allein (~0.11) nicht. Konservativ gewaehlt, weil ohne Backtest.
HARD_SIGNAL_MIN = 0.15
# Reduziertes Markt-Gewicht, wenn getriggert (von 0.20 runter). NICHT 0 -- der Markt
# bleibt beigemischt, nur schwaecher. Konservativ.
SIGNAL_TRIGGERED_WEIGHT = 0.10
# Sicherheits-Deckel: bei UEBERWAELTIGENDEM Markt-Edge (Markt >> Modell) NICHT
# eingreifen -- dann preist der Markt das Signal vermutlich laengst ein.
MAX_MARKET_EDGE = 0.35

_OUTCOMES = ("home", "draw", "away")


def _favorite(probs: Mapping[str, float]) -> str:
    return max(_OUTCOMES, key=lambda k: float(probs.get(k, 0.0) or 0.0))


def hard_signal_magnitude(breakdown: Mapping[str, Any] | None) -> float:
    """Summe der Betraege harter Kontext-Effekte ueber beide Seiten."""
    if not breakdown:
        return 0.0
    total = 0.0
    for side in ("home", "away"):
        comp = breakdown.get(side) or {}
        for key in HARD_SIGNAL_KEYS:
            try:
                total += abs(float(comp.get(key, 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def resolve_blend_weight(
    model_probs: Mapping[str, float] | None,
    market_probs: Mapping[str, float] | None,
    breakdown: Mapping[str, Any] | None,
    *,
    base_weight: float,
    enabled: bool | None = None,
) -> tuple[float, dict[str, Any]]:
    """Liefert (blend_weight, info). Default == base_weight (No-Op).

    Senkt das Markt-Gewicht auf `SIGNAL_TRIGGERED_WEIGHT` NUR wenn: Flag an UND
    Modell-Favorit != Markt-Favorit UND die Modell-Gegenposition signal-getrieben
    ist (harte Signalstaerke >= `HARD_SIGNAL_MIN`) UND der Markt nicht
    ueberwaeltigend ueberzeugter ist (edge <= `MAX_MARKET_EDGE`).

    `info` dokumentiert die Entscheidung fuer den Drilldown/Diff.
    """
    if enabled is None:
        enabled = SIGNAL_AWARE_BLEND_ENABLED
    info: dict[str, Any] = {"applied": False, "base_weight": base_weight}
    if not enabled or not model_probs or not market_probs:
        return base_weight, info

    mod_fav = _favorite(model_probs)
    mkt_fav = _favorite(market_probs)
    info["model_favorite"] = mod_fav
    info["market_favorite"] = mkt_fav
    if mod_fav == mkt_fav:
        return base_weight, info

    magnitude = hard_signal_magnitude(breakdown)
    market_edge = round(
        float(market_probs.get(mkt_fav, 0.0)) - float(model_probs.get(mkt_fav, 0.0)),
        4,
    )
    info["hard_signal_magnitude"] = magnitude
    info["market_edge"] = market_edge

    if magnitude >= HARD_SIGNAL_MIN and market_edge <= MAX_MARKET_EDGE:
        info["applied"] = True
        info["blend_weight"] = SIGNAL_TRIGGERED_WEIGHT
        info["reason"] = "signal-getriebene Modell-Gegenposition -> Markt-Gewicht gesenkt"
        return SIGNAL_TRIGGERED_WEIGHT, info
    return base_weight, info


# ---------------------------------------------------------------------------
# T-0144: News-vs-Markt-Veto -- die GEGENTHESE zu T-0136 auf demselben Entscheidungspunkt.
#
# T-0136 unterstellt: der Markt UNTERschaetzt harte Signale -> Markt-Gewicht senken.
# Motivation war n=1 (Brasilien-Norwegen), die Praemisse im Doc-String oben ausdruecklich
# als "unbewiesen" markiert.
#
# Die Live-Messung (2026-07-10, T-0144) widerlegt sie fuer `news`:
#   - dPkt-Gate: news -35 ueber alle Flips -> `halve`; alle anderen Signale positiv/neutral.
#   - 51 gewertete News-Flips: die GEGEN den Marktfavoriten kosten -2.10 Pkt/Stueck (n=10,
#     dPkt -21), die MIT dem Markt nur -0.23 (n=39). Der Schaden sitzt genau dort, wo
#     T-0136 den Markt zusaetzlich schwaechen wuerde.
#   - Skalen-Sweep auf 41 gespielten Spielen: news x1.0 = 149 Pkt, x0.5 = 172, x0.0 = 186.
#
# Dieses Veto verwirft daher den News-Effekt fuer GENAU die Spiele, in denen er den
# Modell-Favoriten gegen einen klaren Marktfavoriten dreht -- gezielter als eine globale
# Skalierung (nur ~10 von 51 Flips betroffen).
#
# DIE BEIDEN HEBEL SIND KONTRAER. Nie beide gleichzeitig aktivieren; `guard_contradictory_levers`
# erzwingt das. Ebenfalls NICHT backtestbar (backtest.py kennt keine News) -> in-sample auf
# EINEM Turnier, default AUS, Aktivierung nur nach manueller Freigabe.
NEWS_MARKET_VETO_ENABLED = False
# Ab welcher (entoverten) Marktwahrscheinlichkeit gilt ein Favorit als "klar".
NEWS_MARKET_VETO_MIN_PROB = 0.45
# Mindest-Betrag des News-Effekts, damit er als Ursache der Uneinigkeit zaehlt.
NEWS_MARKET_VETO_MIN_NEWS = 0.10


def guard_contradictory_levers(
    *,
    signal_blend_enabled: bool | None = None,
    news_veto_enabled: bool | None = None,
) -> None:
    """T-0136 und T-0144 sind Gegenthesen -- beide an ergibt keinen definierten Zustand."""
    blend = SIGNAL_AWARE_BLEND_ENABLED if signal_blend_enabled is None else signal_blend_enabled
    veto = NEWS_MARKET_VETO_ENABLED if news_veto_enabled is None else news_veto_enabled
    if blend and veto:
        raise ValueError(
            "SIGNAL_AWARE_BLEND_ENABLED (T-0136: Markt-Gewicht senken) und "
            "NEWS_MARKET_VETO_ENABLED (T-0144: News verwerfen) sind kontraere Hebel "
            "auf demselben Entscheidungspunkt. Genau einen aktivieren."
        )


def news_magnitude(breakdown: Mapping[str, Any] | None) -> float:
    """Betrag des News-Effekts ueber beide Seiten."""
    if not breakdown:
        return 0.0
    total = 0.0
    for side in ("home", "away"):
        comp = breakdown.get(side) or {}
        try:
            total += abs(float(comp.get("news_effect", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return round(total, 4)


def resolve_news_veto(
    model_probs: Mapping[str, float] | None,
    model_probs_without_news: Mapping[str, float] | None,
    market_probs: Mapping[str, float] | None,
    breakdown: Mapping[str, Any] | None,
    *,
    enabled: bool | None = None,
) -> tuple[bool, dict[str, Any]]:
    """(veto, info). Default False (No-Op).

    Verwirft den News-Effekt NUR wenn: Flag an UND der Markt einen klaren Favoriten
    hat (>= `NEWS_MARKET_VETO_MIN_PROB`) UND das Modell MIT News gegen ihn steht UND
    OHNE News mit ihm -- d.h. **die News sind die Ursache der Uneinigkeit**. Steht das
    Modell auch ohne News gegen den Markt, bleibt alles unangetastet (dann ist es
    Elo/Kontext, nicht der gemessen schaedliche News-Malus).
    """
    if enabled is None:
        enabled = NEWS_MARKET_VETO_ENABLED
    info: dict[str, Any] = {"applied": False}
    if not enabled or not model_probs or not market_probs or not model_probs_without_news:
        return False, info

    guard_contradictory_levers(news_veto_enabled=enabled)

    mkt_fav = _favorite(market_probs)
    mkt_prob = float(market_probs.get(mkt_fav, 0.0) or 0.0)
    mod_fav = _favorite(model_probs)
    mod_fav_no_news = _favorite(model_probs_without_news)
    magnitude = news_magnitude(breakdown)
    info.update(
        {
            "market_favorite": mkt_fav,
            "market_probability": round(mkt_prob, 4),
            "model_favorite": mod_fav,
            "model_favorite_without_news": mod_fav_no_news,
            "news_magnitude": magnitude,
        }
    )

    if mkt_prob < NEWS_MARKET_VETO_MIN_PROB:
        return False, info
    if magnitude < NEWS_MARKET_VETO_MIN_NEWS:
        return False, info
    if mod_fav == mkt_fav:
        return False, info
    if mod_fav_no_news != mkt_fav:
        # Auch ohne News gegen den Markt -> keine News-Ursache, nicht eingreifen.
        info["reason"] = "Uneinigkeit nicht news-verursacht -> kein Veto"
        return False, info

    info["applied"] = True
    info["reason"] = "News drehte den Modell-Favoriten gegen einen klaren Marktfavoriten -> News verworfen"
    return True, info
