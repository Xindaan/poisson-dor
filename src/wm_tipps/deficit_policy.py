"""Deficit-Policy fuer die Tipp-Empfehlung (T-0080).

Kicktipp zahlt RANG, nicht Punkte. Wenn man zurueckliegt, ist die EP-Max-Linie
(Status quo) zwar pro Spiel optimal, aber feld-relativ chancenlos, sobald das
Feld korreliert (alle tippen aehnlich). Die Monte-Carlo-Sim (T-0100,
`analysis/win_sim_v2.py`) hat eine robuste Politik gefunden, die den
P(Platz-1)-FLOOR hebt:

  - vorn/gleich (D<=0):  COVER  -- den Feld-Konsens spiegeln (Varianz senken).
  - weit hinten + spaet (D > 1.5*sqrt(Restspiele)):  CHASE -- vom Feld-Konsens
    dekorrelieren (den Tipp waehlen, der P(Feld schlagen) maximiert).
  - sonst:  EP-MAX (Status quo).

Stures Chasen ist die SCHLECHTESTE Klasse -- nur die selektive Politik hilft.
Dieses Modul rechnet je Runde das aktuelle Regime (D, Restspiele M) und je noch
offenem Spiel den Policy-Tipp neben dem EP-Max-Tipp. Read-only Empfehlung; die
EP-Max-Linie bleibt der Default, die Policy ist der feld-relative Overlay.

Feld-Konsens je Spiel = modaler favoriten-relativer Tipp ueber alle Rivalen
(aus ihren bisherigen Tipps), auf den Favoriten des Spiels angewandt -- spiegelt
win_sim_v2 (modal-Rivalenmodell). Cover-Tipp = dieser Konsens; Chase-Tipp =
`_chase_tip` (max P(Konsens schlagen)).
"""
from __future__ import annotations

from datetime import datetime, timezone

from collections import Counter
from math import sqrt
from typing import Any, Mapping

import random

from .io import read_json
from .knockout import (
    KNOCKOUT_STAGE_BY_MATCH,
    knockout_feeds,
    match_loser,
    match_winner,
    matchup_xg,
)
from .model import load_team_strength, outcome_probabilities, score_matrix
from .paths import DATA_DIR, EXPORTS_DIR
from .scoring import (
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    round_name,
    Score,
    is_knockout_stage,
    is_stage_tippable,
    kicktipp_points,
    resolve_extra_time,
    resolve_knockout_draw_probabilities,
    round_resolves_penalties,
)

DEFICIT_POLICY_PATH = DATA_DIR / "deficit_policy.json"
DEFICIT_POLICY_MARKDOWN_PATH = EXPORTS_DIR / "deficit_policy.md"

ROUND_IDS = (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID)
THR_C = 1.5  # Chase-Schwelle: D > THR_C * sqrt(Restspiele)
# T-0080/Codex-Gate (konservativ, sim-geerdet): NUR spaet chasen. Frueh ist jeder
# Rueckstand mit Normaltippen schliessbar; Chase kostet dann nur EP. win_sim_v2 aus
# dem unteren Tabellendrittel eines grossen Feldes, mit noch vielen bedeutenden
# Restspielen: EP-Max lag sowohl bei P(Platz 1) als auch bei Top-3 deutlich vor
# Deficit-Chase (Top-3 sogar um ein Vielfaches). Erst wenn wenige bedeutende
# Spiele bleiben, kann Varianz den Rang heben -> Chase fruehestens ab hier:
CHASE_MAX_M_LEFT = 12
# Bedeutende Restspiele MUESSEN die K.o.-Phase mitzaehlen (sie stehen anfangs noch
# nicht in fixtures.json), sonst zaehlt M nur die Gruppenphase und Chase startet zu
# frueh. Laut Kicktipp-Tippabgabe vom 14.07.2026 ist ko-103 in beiden Pools
# tippbar.
# Plausibilitaets-Gate: nur chasen, wenn der dekorrelierte Tipp mindestens diese
# Chance hat, den Feld-Tipp auf DIESEM Spiel zu schlagen. Sonst ist die
# Dekorrelation (z.B. Remis bei klarem Favoriten) zu unwahrscheinlich -> nur
# EP-Verlust, kein Rang-Nutzen -> EP-Max behalten.
CHASE_MIN_PBEAT = 0.30
MAX_GOALS = 6
# Per-Rivale-Chase (T-0080): unter dieser Tipp-Zahl ist das Profil eines Rivalen
# nicht belastbar genug, um seinen Tipp zu prognostizieren -> Feld-Konsens bleibt
# die einzige Referenz. Gleiche Schwelle wie rival_profiles._meta.min_tips_reliable.
MIN_RIVAL_TIPS = 8
# Monte-Carlo fuer catch_up (T-0142). Seed fix -> reproduzierbare Artefakte.
CATCH_UP_ITERATIONS = 20000
CATCH_UP_SEED = 20260710


def non_tippable_match_ids(round_id: str) -> frozenset[str]:
    """K.o.-Spiele ohne Tippzeile in der angegebenen Kicktipp-Runde."""
    return frozenset(
        f"ko-{number:03d}"
        for number, stage in KNOCKOUT_STAGE_BY_MATCH.items()
        if not is_stage_tippable(stage, round_id)
    )


def _matches_left(fixtures, played_ids, round_id: str) -> int:
    skip_ids = non_tippable_match_ids(round_id)
    listed_open = sum(
        1
        for fixture in fixtures
        if fixture.get("match_id") not in played_ids
        and fixture.get("match_id") not in skip_ids
    )
    listed_ko = sum(
        1
        for fixture in fixtures
        if is_knockout_stage(fixture.get("stage", "group"))
        and fixture.get("match_id") not in skip_ids
    )
    tippable_ko_total = len(KNOCKOUT_STAGE_BY_MATCH) - len(skip_ids)
    return listed_open + max(0, tippable_ko_total - listed_ko)


def _parse(label):
    try:
        h, a = (int(x) for x in label.split(":"))
        return h, a
    except (ValueError, AttributeError):
        return None


def _resolved_dist(home_xg, away_xg, stage, round_id):
    probs = score_matrix(home_xg, away_xg, MAX_GOALS)
    if is_knockout_stage(stage):
        probs = resolve_extra_time(probs)
        if round_resolves_penalties(round_id):
            probs = resolve_knockout_draw_probabilities(probs)
    return probs


def _fav_side(dist):
    home = away = 0.0
    for label, p in dist.items():
        h, a = (int(x) for x in label.split(":"))
        if h > a:
            home += p
        elif a > h:
            away += p
    return "home" if home >= away else "away"


def _rel_of(tip, fav):
    h, a = tip
    r = (h, a) if fav == "home" else (a, h)
    return (min(r[0], MAX_GOALS), min(r[1], MAX_GOALS))


def _unrel(rel, fav):
    fg, dg = rel
    return f"{fg}:{dg}" if fav == "home" else f"{dg}:{fg}"


def _ep_tip(dist, stage, round_id):
    best, bep = None, -1.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            ep = sum(p * kicktipp_points(Score(h, a), Score(*_parse(sc)), stage, round_id) for sc, p in dist.items())
            if best is None or ep > bep:
                bep, best = ep, f"{h}:{a}"
    return best


def _chase_tip(target_tip, dist, stage, round_id):
    """Tipp, der P(ich schlage target_tip) maximiert (Tiebreak: hoeheres EP)."""
    rt = Score(*_parse(target_tip))
    best, bpg, bem = None, -1.0, -1.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            cand = Score(h, a)
            pg = em = 0.0
            for sc, p in dist.items():
                act = Score(*_parse(sc))
                mp = kicktipp_points(cand, act, stage, round_id)
                if mp > kicktipp_points(rt, act, stage, round_id):
                    pg += p
                em += p * mp
            if pg > bpg + 1e-12 or (abs(pg - bpg) < 1e-12 and em > bem):
                bpg, bem, best = pg, em, f"{h}:{a}"
    return best


def _p_beat(my_tip, target_tip, dist, stage, round_id):
    """P(mein Tipp schlaegt target_tip), gewichtet mit der Modell-Verteilung --
    d.h. wie wahrscheinlich der dekorrelierte Ausgang tatsaechlich eintritt."""
    me = Score(*_parse(my_tip))
    tg = Score(*_parse(target_tip))
    pg = 0.0
    for sc, p in dist.items():
        act = Score(*_parse(sc))
        if kicktipp_points(me, act, stage, round_id) > kicktipp_points(tg, act, stage, round_id):
            pg += p
    return pg


def _ep_of(tip, dist, stage, round_id):
    """Erwartete Kicktipp-Punkte eines konkreten Tipps unter der Modell-Verteilung."""
    me = Score(*_parse(tip))
    return sum(p * kicktipp_points(me, Score(*_parse(sc)), stage, round_id) for sc, p in dist.items())


def _diff_dist(my_tip, rival_tip, dist, stage, round_id):
    """Verteilung der Punktdifferenz (ich - Rivale) auf EINEM Spiel."""
    me = Score(*_parse(my_tip))
    rv = Score(*_parse(rival_tip))
    out = Counter()
    for sc, p in dist.items():
        act = Score(*_parse(sc))
        delta = kicktipp_points(me, act, stage, round_id) - kicktipp_points(rv, act, stage, round_id)
        out[delta] += p
    return out


def _convolve(diff_dists):
    """Gesamt-Punktdifferenz ueber alle Restspiele (Spiele als unabhaengig angenommen)."""
    total = Counter({0: 1.0})
    for d in diff_dists:
        nxt = Counter()
        for a, pa in total.items():
            for b, pb in d.items():
                nxt[a + b] += pa * pb
        total = nxt
    return total


def _p_catch_up(diff_dists, deficit):
    """P(Gesamtdifferenz >= Rueckstand), d.h. P(den Rivalen tatsaechlich einholen).

    Das ist die Zielgroesse -- NICHT die per-Spiel-P(schlagen). Den Fuehrenden auf
    drei Spielen knapp zu schlagen bringt ~3 Punkte, schliesst aber keinen
    8-Punkte-Rueckstand.
    """
    if not diff_dists or deficit is None:
        return None
    total = _convolve(diff_dists)
    return round(sum(p for delta, p in total.items() if delta >= deficit), 4)


def _cumulative(dist):
    """(labels, kumulierte Gewichte) fuer schnelles Ziehen."""
    labels, cum, total = [], [], 0.0
    for label, p in dist.items():
        total += p
        labels.append(label)
        cum.append(total)
    return labels, cum, total


def _draw(labels, cum, total, rng):
    target = rng.random() * total
    for label, upper in zip(labels, cum):
        if target <= upper:
            return label
    return labels[-1]


def _winner_of(label, home, away, home_xg, away_xg, rng):
    """Wer kommt weiter? Bei Remis (Runden ohne Elfer-Aufloesung) Penalty-Proxy."""
    h, a = _parse(label)
    if h > a:
        return home
    if a > h:
        return away
    p_home = home_xg / (home_xg + away_xg) if (home_xg + away_xg) else 0.5
    return home if rng.random() < max(0.1, min(0.9, p_home)) else away


def simulate_catch_up(
    *,
    predictions_by_id,
    winners,
    losers=None,
    strengths,
    rival_rel_dist,
    deficit,
    round_id,
    skip_ids,
    iterations=CATCH_UP_ITERATIONS,
    seed=CATCH_UP_SEED,
):
    """Monte-Carlo: P(Rueckstand auf den Fuehrenden einholen) ueber ALLE Restspiele.

    Schliesst die zwei Defekte der analytischen Variante (T-0142):
    (a) Halbfinale/Finale werden ueber den Bracket mitsimuliert, statt zu fehlen;
    (b) der Rivale tippt NICHT deterministisch seinen modalen Tipp, sondern gezogen
        aus seiner empirischen favoriten-relativen Tipp-Verteilung -- er kann also
        auch danebenliegen. Ohne (b) tippen wir bei EP-Max oft identisch (Differenz 0)
        und P(einholen) wird systematisch zu klein.

    Meine Strategie wird VOR seinem Tipp gewaehlt (realistisch): EP-Max bzw. Chase
    gegen seinen MODALEN Tipp. Gemeinsame Zufallszahlen fuer beide Strategien
    (gleiche Ausgaenge, gleiche Rivalen-Tipps) -> der Vergleich ist rauschaermer.

    Rueckgabe: dict mit p_ep_max / p_rival_chase (+ 95%-Halbbreite) oder None,
    wenn nichts zu simulieren ist.
    """
    if deficit is None or not rival_rel_dist:
        return None
    feeds = knockout_feeds()
    semifinal_numbers = tuple(
        number
        for number, stage in KNOCKOUT_STAGE_BY_MATCH.items()
        if stage == "semi"
    )
    third_place_feeds = {
        number: semifinal_numbers
        for number, stage in KNOCKOUT_STAGE_BY_MATCH.items()
        if stage == "third_place"
    }
    # Restspiele = tippbare K.o.-Spiele ohne Sieger, in Bracket-Reihenfolge. Vorab pruefen,
    # dass JEDES davon aufloesbar ist -- entweder es hat schon eine Prediction (Teams
    # bekannt) oder beide Feeds sind vorher aufgeloest. Sonst lieber KEINE Zahl liefern
    # als eine, die still ueber abgebrochene Iterationen zu klein waere.
    losers = losers or {}
    resolvable_winners = set(winners)
    resolvable_losers = set(losers)
    remaining = []
    for number in sorted(KNOCKOUT_STAGE_BY_MATCH):
        if number in winners or f"ko-{number:03d}" in skip_ids:
            continue
        if predictions_by_id.get(f"ko-{number:03d}"):
            remaining.append(number)
            resolvable_winners.add(number)
            resolvable_losers.add(number)
            continue
        loser_feed = third_place_feeds.get(number)
        if loser_feed and all(source in resolvable_losers for source in loser_feed):
            remaining.append(number)
            resolvable_winners.add(number)
            resolvable_losers.add(number)
            continue
        feed = feeds.get(number)
        if feed and feed[0] in resolvable_winners and feed[1] in resolvable_winners:
            remaining.append(number)
            resolvable_winners.add(number)
            resolvable_losers.add(number)
            continue
        return None  # Bracket nicht vollstaendig modellierbar
    if not remaining:
        return None

    rel_labels, rel_cum, rel_total = _cumulative(rival_rel_dist)
    modal_rel = max(rival_rel_dist, key=rival_rel_dist.get)
    cache = {}

    def setup(home, away, stage, xg):
        """Paarung einmal aufloesen und die Punktetabellen praekompilieren.

        Die Paarungen sind wenige (Finale hoechstens ~12), die Iterationen viele --
        ohne diese Tabellen dominiert kicktipp_points die Laufzeit.
        """
        key = (home, away, stage)
        cached = cache.get(key)
        if cached is None:
            home_xg, away_xg = xg
            dist = _resolved_dist(home_xg, away_xg, stage, round_id)
            fav = _fav_side(dist)
            ep = _ep_tip(dist, stage, round_id)
            chase = _chase_tip(_unrel(modal_rel, fav), dist, stage, round_id)
            actuals = {label: Score(*_parse(label)) for label in dist}
            pts = lambda tip: {  # noqa: E731 - lokale Tabelle, bewusst kompakt
                label: kicktipp_points(Score(*_parse(tip)), act, stage, round_id)
                for label, act in actuals.items()
            }
            cached = cache[key] = {
                "cum": _cumulative(dist),
                "ep_pts": pts(ep),
                "chase_pts": pts(chase),
                "rival_pts": {rel: pts(_unrel(rel, fav)) for rel in rival_rel_dist},
                "xg": (home_xg, away_xg),
            }
        return cached

    rng = random.Random(seed)
    hits_ep = hits_chase = 0
    paired_sum = paired_sq = 0  # gepaarte Differenz (Chase - EP) je Iteration
    for _ in range(iterations):
        won = dict(winners)
        lost = dict(losers)
        diff_ep = diff_chase = 0
        for number in remaining:
            pred = predictions_by_id.get(f"ko-{number:03d}")
            stage = KNOCKOUT_STAGE_BY_MATCH[number]
            if pred and (pred.get("fixture") or {}).get("home_team"):
                fx = pred["fixture"]
                home, away = fx["home_team"], fx["away_team"]
                xg = (pred["xg"]["home"], pred["xg"]["away"])
            else:
                # Nach der Vorab-Pruefung sind beide Feeds garantiert schon entschieden.
                if number in third_place_feeds:
                    home_from, away_from = third_place_feeds[number]
                    home, away = lost[home_from], lost[away_from]
                else:
                    home_from, away_from = feeds[number]
                    home, away = won[home_from], won[away_from]
                xg = matchup_xg(home, away, strengths)
            c = setup(home, away, stage, xg)
            labels, cum, total = c["cum"]
            actual = _draw(labels, cum, total, rng)
            rival_pts = c["rival_pts"][_draw(rel_labels, rel_cum, rel_total, rng)][actual]
            diff_ep += c["ep_pts"][actual] - rival_pts
            diff_chase += c["chase_pts"][actual] - rival_pts
            winner = _winner_of(actual, home, away, c["xg"][0], c["xg"][1], rng)
            won[number] = winner
            lost[number] = away if winner == home else home

        hit_ep = diff_ep >= deficit
        hit_chase = diff_chase >= deficit
        hits_ep += hit_ep
        hits_chase += hit_chase
        delta = hit_chase - hit_ep
        paired_sum += delta
        paired_sq += delta * delta

    def summarize(hits):
        p = hits / iterations
        return round(p, 4), round(1.96 * sqrt(max(p * (1 - p), 0.0) / iterations), 4)

    p_ep, ci_ep = summarize(hits_ep)
    p_chase, ci_chase = summarize(hits_chase)
    # Gepaart auswerten: beide Strategien sahen dieselben Ausgaenge und Rivalen-Tipps.
    # Die Differenz ist dadurch viel praeziser als der Vergleich der beiden Einzel-CIs.
    mean_delta = paired_sum / iterations
    var_delta = max(paired_sq / iterations - mean_delta * mean_delta, 0.0)
    ci_delta = 1.96 * sqrt(var_delta / iterations)
    return {
        "p_ep_max": p_ep,
        "p_ep_max_ci95": ci_ep,
        "p_rival_chase": p_chase,
        "p_rival_chase_ci95": ci_chase,
        "chase_minus_ep": round(mean_delta, 4),
        "chase_minus_ep_ci95": round(ci_delta, 4),
        "chase_better": mean_delta - ci_delta > 0,
        "ep_better": mean_delta + ci_delta < 0,
        "simulated_matches": len(remaining),
        "iterations": iterations,
        "seed": seed,
    }


def _rival_modal_rel_with_n(pool_players, match_fav):
    """Je Rivale (modaler favoriten-relativer Tipp, Anzahl verwertbarer Tipps)."""
    out = {}
    for name, tips in pool_players.items():
        c = Counter()
        for mid, label in tips.items():
            fav = match_fav.get(mid)
            t = _parse(label)
            if fav is None or t is None:
                continue
            c[_rel_of(t, fav)] += 1
        out[name] = (c.most_common(1)[0][0] if c else (1, 0), sum(c.values()))
    return out


def _rival_modal_rel(pool_players, match_fav):
    """Je Rivale der modale favoriten-relative Tipp (aus seinen bisherigen Tipps).
    match_fav: dict match_id -> fav_side ('home'/'away')."""
    return {name: rel for name, (rel, _) in _rival_modal_rel_with_n(pool_players, match_fav).items()}


def _rival_rel_dist(tips, match_fav):
    """Empirische Verteilung der favoriten-relativen Tipps EINES Rivalen.

    Der Modus allein unterschlaegt, dass er auch danebenliegen kann -- genau das
    macht die deterministische Variante zu pessimistisch (T-0142).
    """
    counts = Counter()
    for mid, label in tips.items():
        fav = match_fav.get(mid)
        parsed = _parse(label)
        if fav is None or parsed is None:
            continue
        counts[_rel_of(parsed, fav)] += 1
    total = sum(counts.values())
    return {rel: n / total for rel, n in counts.items()} if total else {}


def _leader_name(standings, round_id):
    """Name des Tabellenfuehrenden aus der juengsten Beobachtung (Rang 1)."""
    obs = [o for o in standings.get("observations", []) if o.get("round_id") == round_id and o.get("entries")]
    if not obs:
        return None
    obs.sort(key=lambda o: o.get("observed_at", ""))
    for entry in obs[-1].get("entries", []):
        if entry.get("rank") == 1 and entry.get("name"):
            return str(entry["name"])
    return None


def _field_consensus(modal_rel, fav):
    """Modaler vom Feld erwarteter Tipp fuer dieses Spiel (Konsens)."""
    votes = Counter(_unrel(modal_rel[r], fav) for r in modal_rel)
    return votes.most_common(1)[0][0] if votes else "1:0"


def _regime(deficit, m_left):
    if deficit <= 0:
        return "protect"
    # T-0080/Codex-Gate: NUR spaet chasen -- wenige bedeutende Restspiele (<=CHASE_MAX_M_LEFT)
    # UND Rueckstand ueber der sqrt-Schwelle. Frueh (viele Restspiele) ist Chase reiner
    # EP-Verlust ohne Rang-Nutzen (Sim bevorzugt klar EP-Max) -> neutral/EP-Max.
    if 0 < m_left <= CHASE_MAX_M_LEFT and deficit > THR_C * sqrt(m_left):
        return "chase"
    return "neutral"


def _latest_deficit(standings, round_id):
    obs = [o for o in standings.get("observations", []) if o.get("round_id") == round_id and o.get("entries")]
    if not obs:
        return None
    obs.sort(key=lambda o: o.get("observed_at", ""))
    last = obs[-1]
    return {
        "observed_at": last.get("observed_at"),
        "deficit": last.get("deficit_to_leader"),
        "my_rank": last.get("me_rank"),
        "field_size": last.get("field_size"),
    }


def build_deficit_policy(*, predictions=None, pool_tips=None, standings=None, fixtures=None, write: bool = True) -> dict[str, Any]:
    if predictions is None:
        predictions = read_json(DATA_DIR / "predictions.json", {"predictions": []}).get("predictions", [])
    if pool_tips is None:
        pool_tips = read_json(DATA_DIR / "manual_pool_tips.json", {})
    if standings is None:
        standings = read_json(DATA_DIR / "manual_standings.json", {})
    if fixtures is None:
        fixtures = read_json(DATA_DIR / "fixtures.json", {"fixtures": []}).get("fixtures", [])

    actuals = pool_tips.get("actuals", {})
    played_ids = set(actuals) | {f.get("match_id") for f in fixtures if f.get("status") == "played"}
    by_id = {p.get("match_id"): p for p in predictions}
    # Sieger der bereits gespielten K.o.-Spiele (Elfmeter beruecksichtigt) -- Startpunkt
    # der Bracket-Simulation. Sieger-Logik kommt aus knockout, nicht dupliziert.
    ko_winners = {}
    ko_losers = {}
    for fixture in fixtures:
        mid = str(fixture.get("match_id") or "")
        if not mid.startswith("ko-") or fixture.get("status") != "played":
            continue
        winner = match_winner(fixture)
        if winner:
            try:
                ko_winners[int(mid.split("-", 1)[1])] = winner
            except (IndexError, ValueError):
                continue
        loser = match_loser(fixture)
        if loser:
            try:
                ko_losers[int(mid.split("-", 1)[1])] = loser
            except (IndexError, ValueError):
                continue
    strengths = load_team_strength()
    # Favorit + dist je Spiel vorberechnen (fuer Feld-Konsens + Tipps):
    match_dist = {}
    match_fav = {}
    for p in predictions:
        xg = p.get("xg") or {}
        if xg.get("home") is None:
            continue
        mid = p.get("match_id")
        stage = (p.get("fixture") or {}).get("stage", "group")
        dist = _resolved_dist(xg["home"], xg["away"], stage, DEFAULT_ROUND_ID)
        match_dist[mid] = (dist, stage)
        match_fav[mid] = _fav_side(dist)

    rounds_out = {}
    for rid in ROUND_IDS:
        skip_ids = non_tippable_match_ids(rid)
        m_left = _matches_left(fixtures, played_ids, rid)
        info = _latest_deficit(standings, rid)
        deficit = (info or {}).get("deficit")
        regime = _regime(deficit, m_left) if deficit is not None else "unbekannt"
        threshold = round(THR_C * sqrt(m_left), 2) if m_left else None
        modal_n = _rival_modal_rel_with_n((pool_tips.get("players") or {}).get(rid, {}), match_fav)
        modal_rel = {name: rel for name, (rel, _) in modal_n.items()}

        # Per-Rivale-Ziel (T-0080): der Tabellenfuehrende. Um Platz 1 zu holen,
        # muss genau er/sie ueberholt werden. Nur nutzen, wenn das Profil traegt.
        leader = _leader_name(standings, rid)
        leader_tips = modal_n.get(leader, (None, 0))[1] if leader else 0
        target_reliable = bool(leader) and leader in modal_n and leader_tips >= MIN_RIVAL_TIPS
        target_rival = {
            "name": leader,
            "tips": leader_tips,
            "reliable": target_reliable,
            "reason": (
                "Tabellenfuehrender; Profil belastbar."
                if target_reliable
                else (
                    f"Profil zu duenn ({leader_tips} < {MIN_RIVAL_TIPS} Tipps) -> nur Feld-Konsens."
                    if leader
                    else "Kein Tabellenfuehrender in den Standings."
                )
            ),
        }

        recs = []
        diff_ep, diff_chase = [], []  # je Restspiel die Punktdifferenz-Verteilung vs Rivale
        for p in predictions:
            mid = p.get("match_id")
            if mid in played_ids or mid in skip_ids or mid not in match_dist:
                continue
            dist, stage = match_dist[mid]
            fav = match_fav[mid]
            ep = (p.get("round_tips") or {}).get(rid, {}).get("tip") or _ep_tip(dist, stage, rid)
            cover = _field_consensus(modal_rel, fav)
            chase = _chase_tip(cover, dist, stage, rid)
            chase_pbeat = round(_p_beat(chase, cover, dist, stage, rid), 3)
            if regime == "protect":
                policy = cover
            elif regime == "chase":
                # Plausibilitaets-Gate: nur chasen, wenn der dekorrelierte Ausgang
                # wahrscheinlich genug ist, den Feld-Tipp zu schlagen. Sonst EP-Max.
                policy = chase if chase_pbeat >= CHASE_MIN_PBEAT else ep
            else:
                policy = ep

            # --- Per-Rivale-Overlay (T-0080), additiv: policy_tip bleibt feld-basiert ---
            rival_block = {}
            if target_reliable:
                rival_tip = _unrel(modal_n[leader][0], fav)
                rival_chase = _chase_tip(rival_tip, dist, stage, rid)
                rival_pbeat = round(_p_beat(rival_chase, rival_tip, dist, stage, rid), 3)
                ep_pbeat = round(_p_beat(ep, rival_tip, dist, stage, rid), 3)
                # Nur dekorrelieren, wenn (a) Chase-Regime, (b) der Gegen-Tipp die
                # Plausibilitaetsschwelle nimmt und (c) er den Rivalen echt haeufiger
                # schlaegt als EP-Max es ohnehin tut. Sonst kostet er nur EP.
                if regime == "chase" and rival_pbeat >= CHASE_MIN_PBEAT and rival_pbeat > ep_pbeat:
                    rival_policy = rival_chase
                else:
                    rival_policy = ep
                rival_block = {
                    "rival_tip": rival_tip,
                    "rival_chase_tip": rival_chase,
                    "rival_chase_pbeat": rival_pbeat,
                    "ep_pbeat_vs_rival": ep_pbeat,
                    "rival_policy_tip": rival_policy,
                    "rival_deviates_from_ep": rival_policy != ep,
                    # Was das Abweichen KOSTEN WUERDE (kontrafaktisch), nicht was die gewaehlte
                    # Policy kostet -- sonst steht hier 0.0, gerade wenn man die Zahl braucht:
                    # "X EP zahlen fuer Y% Chance, den Fuehrenden zu schlagen".
                    # Kann NEGATIV sein: `ep` ist der Pipeline-Tipp (Blend/Kalibrierung),
                    # `_ep_of` misst ihn aber unter der lokalen _resolved_dist -- die beiden
                    # haben nicht zwingend denselben Argmax. Negativ = der Chase-Tipp ist
                    # unter DIESER Verteilung sogar EP-besser.
                    "rival_chase_ep_cost": round(
                        _ep_of(ep, dist, stage, rid) - _ep_of(rival_chase, dist, stage, rid), 3
                    ),
                    # EP-Max kann den Rivalen NICHT schlagen (identischer Tipp) -> ohne
                    # Abweichung ist auf diesem Spiel kein Boden gutzumachen.
                    "no_gain_with_ep": ep_pbeat == 0.0,
                }
                diff_ep.append(_diff_dist(ep, rival_tip, dist, stage, rid))
                diff_chase.append(_diff_dist(rival_chase, rival_tip, dist, stage, rid))

            fx = p.get("fixture") or {}
            recs.append({
                "match_id": mid,
                "match": f"{fx.get('home_team','?')} - {fx.get('away_team','?')}",
                "stage": stage,
                "ep_tip": ep,
                "field_consensus": cover,
                "chase_tip": chase,
                "chase_pbeat": chase_pbeat,
                "policy_tip": policy,
                "deviates_from_ep": policy != ep,
                **rival_block,
            })
        monte_carlo = None
        if target_reliable:
            monte_carlo = simulate_catch_up(
                predictions_by_id=by_id,
                winners=ko_winners,
                losers=ko_losers,
                strengths=strengths,
                rival_rel_dist=_rival_rel_dist(
                    (pool_tips.get("players") or {}).get(rid, {}).get(leader, {}), match_fav
                ),
                deficit=deficit,
                round_id=rid,
                skip_ids=skip_ids,
            )

        rounds_out[rid] = {
            "deficit": deficit,
            "my_rank": (info or {}).get("my_rank"),
            "field_size": (info or {}).get("field_size"),
            "matches_left": m_left,
            "chase_threshold": threshold,
            "chase_max_m_left": CHASE_MAX_M_LEFT,
            "regime": regime,
            "as_of": (info or {}).get("observed_at"),
            "target_rival": target_rival,
            "catch_up": {
                "deficit": deficit,
                "matches_left": m_left,
                "monte_carlo": monte_carlo,
                "analytic_lower_bound": {
                    "remaining_scored": len(diff_ep),
                    "p_ep_max": _p_catch_up(diff_ep, deficit),
                    "p_rival_chase": _p_catch_up(diff_chase, deficit),
                    "why_lower": (
                        "Nur die aufgeloesten Fixtures; Rivale tippt deterministisch seinen "
                        "modalen Tipp (kann also nie danebenliegen) -> systematisch zu klein."
                    ),
                },
                "note": (
                    "P(Punktdifferenz gegen den Fuehrenden >= Rueckstand) ueber die "
                    "TIPPBAREN Restspiele. Per-Spiel-P(schlagen) misst das NICHT (den "
                    "Fuehrenden dreimal knapp zu schlagen bringt ~3 Punkte). PRIMAER ist "
                    "die Monte-Carlo (T-0142): simuliert den Bracket bis zum Finale UND "
                    "zieht den Rivalen-Tipp aus seiner empirischen Verteilung -- er kann "
                    "also danebenliegen. Meine Strategie wird vor seinem Tipp gewaehlt; "
                    "beide Strategien laufen auf denselben Zufallszahlen. "
                    "NICHT MIT win_sim_v2 P(Platz 1) VERGLEICHBAR: win_sim rechnet die "
                    "BONUS-Picks mit (ein Weltmeister-Bonus kann groesser sein als der "
                    "Rueckstand), catch_up kennt nur Spieltipps. Deshalb bleibt "
                    "catch_up auch nach T-0142 eine Untergrenze -- jetzt entlang der "
                    "Bonus-Dimension statt der Spielzahl (Folgekarte T-0143). "
                    "GRENZEN: gemessen wird nur das Head-to-Head gegen den Fuehrenden; im "
                    "grossen Feld ist das notwendig, nicht hinreichend, und die EP-Kosten "
                    "koennen hinter ANDERE Rivalen zurueckwerfen. win_sim_v2 (volles Feld, "
                    "inkl. Bonus) bleibt die Referenz fuer die Strategiewahl. Kein Auto-Merge."
                ),
            },
            "upcoming": recs,
            "deviations": sum(1 for r in recs if r["deviates_from_ep"]),
            "rival_deviations": sum(1 for r in recs if r.get("rival_deviates_from_ep")),
        }

    payload = {
        "_meta": {
            # Zeitstempel: stale Artefakte waren optisch nicht von frischen zu
            # unterscheiden -- genau daran ueberlebte ein kaputtes risk-dial
            # zwei Tage. Wer eine Auswertung liest, muss sehen, wann sie entstand.
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rounds": list(ROUND_IDS),
            "threshold_const": THR_C,
            "chase_min_pbeat": CHASE_MIN_PBEAT,
            "min_rival_tips": MIN_RIVAL_TIPS,
            "non_tippable_by_round": {
                rid: sorted(non_tippable_match_ids(rid)) for rid in ROUND_IDS
            },
            "matches_left_by_round": {
                rid: rounds_out[rid]["matches_left"] for rid in ROUND_IDS
            },
            "verdict": _verdict(rounds_out),
            "note": (
                "Read-only Overlay. EP-Max bleibt der Default-Tipp; policy_tip ist die "
                "feld-relative Empfehlung je Regime (protect=Cover / chase=dekorrelieren / "
                "neutral=EP-Max). Feld-Konsens = modaler favoriten-relativer Feld-Tipp. "
                "Schwelle D > 1.5*sqrt(Restspiele). Aus T-0100/win_sim_v2. "
                f"SPAET-GATE (T-0080/Codex): Chase erst ab <= {CHASE_MAX_M_LEFT} bedeutenden "
                "Restspielen -- frueh ist jeder Rueckstand mit Normaltippen schliessbar, Chase "
                "kostet dann nur EP (Sim: EP-Max schlaegt Chase bei P(Platz 1) klar, "
                "solange viele bedeutende Spiele offen sind). M zaehlt Gruppen-REST "
                "plus die pool-spezifisch tippbare "
                "K.o.-Phase (beide Pools inklusive Spiel um Platz 3); "
                "frueher wurden nur Gruppenspiele gezaehlt -> chaste viel zu frueh. "
                f"PLAUSIBILITAETS-GATE: im Chase-Regime wird nur dekorreliert, wenn der "
                f"Chase-Tipp >= {CHASE_MIN_PBEAT:.0%} Chance hat, den Feld-Tipp auf DIESEM Spiel "
                "zu schlagen (sonst bloss EP-Verlust, kein Rang-Nutzen -> EP-Max). "
                "PER-RIVALE (T-0080): target_rival = Tabellenfuehrender; rival_* zielt auf "
                "P(ihn schlagen) statt auf den Feld-Konsens. Nur belastbar ab "
                f"{MIN_RIVAL_TIPS} Tipps. CAVEAT: den Leader zu schlagen ist notwendig, aber "
                "im grossen Feld NICHT hinreichend -- vor ihm koennen weitere Rivalen liegen; "
                "rival_ep_cost zeigt, was die Dekorrelation an Erwartungspunkten kostet. "
                "Rein advisory: policy_tip bleibt feld-basiert, EP-Max bleibt der Default-Tipp."
            ),
        },
        "rounds": rounds_out,
    }
    if write:
        from .io import write_json

        write_json(DEFICIT_POLICY_PATH, payload)
        DEFICIT_POLICY_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFICIT_POLICY_MARKDOWN_PATH.write_text(deficit_policy_markdown(payload), encoding="utf-8")
    return payload


def _verdict(rounds_out: Mapping[str, Any]) -> str:
    parts = []
    # Labels aus der Rundenkonfiguration statt hartkodiert: die Kurzformen
    # gehoerten zu zwei konkreten Runden und waren hier die einzige Stelle,
    # die sich nicht mit rounds_local.py mitbewegt hat.
    labels = {rid: round_name(rid) for rid in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID)}
    for rid, rd in rounds_out.items():
        reg = rd.get("regime")
        d = rd.get("deficit")
        dev = rd.get("deviations", 0)
        tag = {"protect": "vorn -> Cover", "chase": "zurueck+spaet -> CHASE", "neutral": "EP-Max", "unbekannt": "kein Stand"}.get(reg, reg)
        extra = f", {dev} Abweichungen vom EP-Tipp" if reg in ("protect", "chase") else ""
        parts.append(f"{labels.get(rid, rid)}: D={d}, {tag}{extra}")
    return " | ".join(parts)


def deficit_policy_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("_meta") or {}
    lines = [
        "# Deficit-Policy (T-0080): feld-relative Tipp-Empfehlung",
        "",
        "- Restspiele M: "
        + ", ".join(
            f"**{rid}: {count}**"
            for rid, count in (meta.get("matches_left_by_round") or {}).items()
        )
        + f" · Chase-Schwelle D > {meta.get('threshold_const')}*sqrt(M)",
        f"- **Verdikt:** {meta.get('verdict')}",
        "",
        meta.get("note", ""),
        "",
    ]
    for rid_label, rid in ((round_name(DEFAULT_ROUND_ID), DEFAULT_ROUND_ID), (round_name(SECONDARY_ROUND_ID), SECONDARY_ROUND_ID)):
        rd = (payload.get("rounds") or {}).get(rid, {})
        lines += [
            f"## {rid_label}",
            "",
            f"- Rueckstand D={rd.get('deficit')} (Rang {rd.get('my_rank')}/{rd.get('field_size')}), "
            f"M={rd.get('matches_left')}, Schwelle {rd.get('chase_threshold')} -> **Regime: {rd.get('regime')}** "
            f"({rd.get('deviations')} Abweichungen vom EP-Tipp)",
            "",
        ]
        recs = rd.get("upcoming") or []
        if not recs:
            lines.append("- Keine offenen Spiele mit Prognose.")
            lines.append("")
            continue
        lines += ["| Spiel | EP-Tipp | Feld-Konsens | Chase (P-beat) | Policy |", "|---|---|---|---|---|"]
        for r in recs[:30]:
            mark = " *" if r["deviates_from_ep"] else ""
            lines.append(
                f"| {r['match']} | {r['ep_tip']} | {r['field_consensus']} | "
                f"{r['chase_tip']} ({r.get('chase_pbeat')}) | {r['policy_tip']}{mark} |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
