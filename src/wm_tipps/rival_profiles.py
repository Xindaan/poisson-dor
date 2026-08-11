"""Per-Spieler Tipp-Profile (T-0080).

Aus `manual_pool_tips.json` (Tipps PRO SPIELER je Spieltag) ein Profil je
Rivale: Remis-Rate, mittlere Torzahl (Aggressivitaet), Heim-Neigung, Aehn-
lichkeit zum Modell-Tipp, sowie Punkte/Exakt-Rate auf den gespielten Partien.

Leitfrage (knuepft an den Risk-Dial-Befund T-0075 an): **zahlt sich
Aggressivitaet im ECHTEN Pool bisher aus?** -> Korrelation zwischen mittlerer
Tipp-Torzahl und erzielten Punkten ueber das Feld. Der Risk-Dial sagt: kaum
(EP-Max ist rang-optimal). Die Profile zeigen es am echten Feld.

Das KO-Taktik-Tool (gegen EINEN konkreten Rivalen den P(schlagen)-maximalen
Tipp waehlen) bleibt bewusst offen, bis ~4-6 Spieltage Daten da sind --
aktuell ist die Abdeckung pro Mitspieler noch duenn (Median 5 Tipps).

Read-only Diagnose.
"""
from __future__ import annotations

from datetime import datetime, timezone

import statistics
from collections import Counter
from typing import Any, Mapping

from .io import read_json, write_json
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import (
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    round_name,
    points_for_stage,
    round_resolves_penalties,
    rules_for_round,
)

RIVAL_PROFILES_PATH = DATA_DIR / "rival_profiles.json"
RIVAL_PROFILES_MARKDOWN_PATH = EXPORTS_DIR / "rival_profiles.md"

ROUND_IDS = (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID)
MIN_TIPS_RELIABLE = 8  # ab so vielen Tipps gilt ein Profil als belastbar


def _parse(label: str):
    try:
        h, a = (int(x) for x in label.split(":"))
        return h, a
    except (ValueError, AttributeError):
        return None


def _norm_actual(value, round_id: str = DEFAULT_ROUND_ID):
    """actuals sind gemischt gespeichert: '2:0' (str), [2, 0] (list) ODER -- fuer
    K.o.-Spiele mit Elfmeterentscheidung -- ein Dict
    {'regulation': [h, a], 'penalty': [h, a]} mit PRO POOL unterschiedlicher
    Wertungs-Scoreline (T-0120 Option A): Runden mit Scope 'nach Verlaengerung'
    werten die regulaere/n.V.-Scoreline, Runden 'inkl. Elfmeter' die volle Elfer-
    Scoreline (z.B. NIE-MAR 3:4, nicht 1:1+1). -> (h, a) | None.
    (String-actuals nicht ueberspringen -> T-0097.)"""
    if isinstance(value, dict):
        # Ueber die Kernfunktion, NICHT ueber einen eigenen Substring-Test:
        # `round_resolves_penalties` kennt die deutschen UND die englischen
        # Scope-Marker ("elfmeter"/"penalt"). Die frueher hier stehende Pruefung
        # auf "elfmeter" traf nur deutschsprachige Rundenprofile und lieferte
        # fuer eine englisch beschriebene Runde still die falsche Scoreline.
        chosen = (
            value.get("penalty")
            if round_resolves_penalties(round_id)
            else value.get("regulation")
        )
        if chosen is None:                          # defensiv: fehlender Key
            chosen = value.get("regulation") or value.get("penalty")
        return _norm_actual(chosen, round_id) if chosen is not None else None
    if isinstance(value, str):
        return _parse(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _pool_points(pred, act, stage, round_id):
    """Echte Pool-Regel: exakt / Tordifferenz NUR bei Nicht-Remis / Tendenz / 0.
    Falscher Remis-Score = nur Tendenz (per Kicktipp-Screenshots belegt, 2:2 auf
    1:1 = 2 Pkt); seit dem T-0097-Fix identisch im Kern `scoring.kicktipp_points`
    (Audit It.14 -- die frueher hier behauptete Kern-Abweichung ist behoben).
    Spiegelt analysis/rival_lab.py."""
    pts = points_for_stage(stage, round_id=round_id)
    ph, pa = pred
    ah, aa = act
    if (ph, pa) == (ah, aa):
        return pts["exact"]
    if ah == aa:                                   # echtes Remis
        return pts["tendency"] if ph == pa else 0
    if (ph - pa) == (ah - aa):                     # gleiche Tordifferenz (Nicht-Remis)
        return pts["difference"]
    if ((ph > pa) == (ah > aa)) and ((ph < pa) == (ah < aa)):  # gleiche Tendenz
        return pts["tendency"]
    return 0


def _model_tips(predictions, round_id: str) -> dict[str, str]:
    out = {}
    for p in predictions:
        rt = (p.get("round_tips") or {}).get(round_id) or {}
        tip = rt.get("tip")
        if tip:
            out[p.get("match_id")] = tip
    return out


def _stage_of(predictions_by_id, mid: str) -> str:
    p = predictions_by_id.get(mid) or {}
    return (p.get("fixture") or {}).get("stage", "group")


def _profile(name, tips, actuals, model_tips, predictions_by_id, round_id) -> dict[str, Any] | None:
    parsed = {mid: _parse(s) for mid, s in tips.items()}
    parsed = {mid: ha for mid, ha in parsed.items() if ha is not None}
    n = len(parsed)
    if not n:
        return None
    draws = sum(1 for h, a in parsed.values() if h == a)
    home = sum(1 for h, a in parsed.values() if h > a)
    away = sum(1 for h, a in parsed.values() if a > h)
    mean_goals = statistics.fmean([h + a for h, a in parsed.values()])
    sim = sim_n = pts = exact = played = 0
    for mid, (th, ta) in parsed.items():
        mt = model_tips.get(mid)
        if mt:
            sim_n += 1
            sim += int(tips[mid] == mt)
        act = _norm_actual(actuals.get(mid), round_id)
        if act is not None:
            stage = _stage_of(predictions_by_id, mid)
            pts += _pool_points((th, ta), act, stage, round_id)
            exact += int((th, ta) == act)
            played += 1
    top = Counter(tips[mid] for mid in parsed).most_common(3)
    return {
        "name": name,
        "tips": n,
        "draw_rate": round(draws / n, 3),
        "mean_tip_goals": round(mean_goals, 2),
        "home_lean": round((home - away) / n, 3),
        "model_similarity": round(sim / sim_n, 3) if sim_n else None,
        "played": played,
        "points": pts,
        "ppm": round(pts / played, 3) if played else None,
        "exact_rate": round(exact / played, 3) if played else None,
        "top_scorelines": [s for s, _ in top],
    }


def _pearson(xs, ys) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    return round(cov / (sx ** 0.5 * sy ** 0.5), 3)


def _round_profiles(round_id, players, actuals, predictions) -> dict[str, Any]:
    predictions_by_id = {p.get("match_id"): p for p in predictions}
    model_tips = _model_tips(predictions, round_id)
    profiles = []
    for name, tips in players.items():
        prof = _profile(name, tips, actuals, model_tips, predictions_by_id, round_id)
        if prof:
            profiles.append(prof)
    profiles.sort(key=lambda p: (p["points"], p["tips"]), reverse=True)

    reliable = [p for p in profiles if p["tips"] >= MIN_TIPS_RELIABLE and p["played"]]
    # Leitfrage: zahlt sich Aggressivitaet aus? Korr(mean_tip_goals, ppm).
    corr = _pearson([p["mean_tip_goals"] for p in reliable], [p["ppm"] for p in reliable])
    # Modell-Vergleich: die eigene EP-Max-Linie gegen den Feldschnitt.
    model_goals = statistics.fmean([p["mean_tip_goals"] for p in reliable]) if reliable else None
    field_draw = statistics.fmean([p["draw_rate"] for p in profiles]) if profiles else None
    field_goals = statistics.fmean([p["mean_tip_goals"] for p in profiles]) if profiles else None
    return {
        "players": len(profiles),
        "reliable_players": len(reliable),
        "field_draw_rate": round(field_draw, 3) if field_draw is not None else None,
        "field_mean_tip_goals": round(field_goals, 2) if field_goals is not None else None,
        "aggressiveness_points_corr": corr,
        "profiles": profiles,
    }


def build_rival_profiles(*, predictions=None, pool_tips=None, write: bool = True) -> dict[str, Any]:
    if predictions is None:
        predictions = read_json(DATA_DIR / "predictions.json", {"predictions": []}).get("predictions", [])
    if pool_tips is None:
        pool_tips = read_json(DATA_DIR / "manual_pool_tips.json", {})
    actuals = pool_tips.get("actuals", {})
    all_players = pool_tips.get("players") or {}

    rounds = {rid: _round_profiles(rid, all_players.get(rid, {}), actuals, predictions) for rid in ROUND_IDS}
    verdict = _verdict(rounds[DEFAULT_ROUND_ID])

    payload = {
        "_meta": {
            # Zeitstempel: stale Artefakte waren optisch nicht von frischen zu
            # unterscheiden -- genau daran ueberlebte ein kaputtes risk-dial
            # zwei Tage. Wer eine Auswertung liest, muss sehen, wann sie entstand.
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rounds": list(ROUND_IDS),
            "min_tips_reliable": MIN_TIPS_RELIABLE,
            "verdict": verdict,
            "note": ("Read-only. model_similarity = Anteil Tipps == unser EP-Max-Modell-Tipp. "
                     "aggressiveness_points_corr = Korr(Tore/Tipp, Pkt/Spiel) ueber Spieler mit "
                     f">={MIN_TIPS_RELIABLE} Tipps. KO-Taktik-Tool (Per-Rivale) offen bis mehr Daten."),
        },
        "rounds": rounds,
    }
    if write:
        write_json(RIVAL_PROFILES_PATH, payload)
        RIVAL_PROFILES_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        RIVAL_PROFILES_MARKDOWN_PATH.write_text(rival_profiles_markdown(payload), encoding="utf-8")
    return payload


def _verdict(round_data: Mapping[str, Any]) -> str:
    corr = round_data.get("aggressiveness_points_corr")
    n = round_data.get("reliable_players", 0)
    if corr is None:
        return f"zu wenig Daten fuer Aggressivitaets-Korrelation (n={n})"
    if corr <= 0.1:
        tag = "Aggressivitaet zahlt sich NICHT aus (deckt sich mit Risk-Dial)"
    elif corr >= 0.4:
        tag = "Aggressivitaet korreliert mit Punkten -- beobachten"
    else:
        tag = "schwache/uneindeutige Aggressivitaets-Punkte-Kopplung"
    return f"Korr(Tore/Tipp, Pkt/Spiel) = {corr} (n={n}): {tag}"


def rival_profiles_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# Per-Spieler Tipp-Profile (T-0080)",
        "",
        f"- **Verdikt:** {meta.get('verdict')}",
        "",
        meta.get("note", ""),
        "",
    ]
    for rid_label, rid in ((round_name(DEFAULT_ROUND_ID), DEFAULT_ROUND_ID), (round_name(SECONDARY_ROUND_ID), SECONDARY_ROUND_ID)):
        rd = (payload.get("rounds") or {}).get(rid, {})
        if not rd.get("profiles"):
            continue
        lines += [
            f"## {rid_label}",
            "",
            f"- Feld-Remis-Rate {rd.get('field_draw_rate')} · Feld-Tore/Tipp {rd.get('field_mean_tip_goals')} "
            f"· Korr(Aggressivitaet, Pkt) {rd.get('aggressiveness_points_corr')} (n={rd.get('reliable_players')})",
            "",
            "| Spieler | Tipps | Pkt | Pkt/Spiel | Remis% | Tore/Tipp | Modell-Aehnl. | Exakt% |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for p in rd["profiles"][:20]:
            sim = p["model_similarity"] if p["model_similarity"] is not None else "-"
            lines.append(
                f"| {p['name']} | {p['tips']} | {p['points']} | {p['ppm']} | "
                f"{p['draw_rate']} | {p['mean_tip_goals']} | {sim} | {p['exact_rate']} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
