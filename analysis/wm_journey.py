#!/usr/bin/env python3
"""Generator fuer das oeffentliche WM-2026-Turnier-Dashboard ("Der Weg zum Titel").

Erzeugt eine self-contained, HELLE (Apple-clean), interaktive Single-Page-Seite fuer
die Familie -- KEIN Kicktipp-/Modell-/KI-Bezug:
- Ueberblick: Live-Kennzahlen + Schlagzeilen + 12-Gruppen-Raster (rein faktisch)
- Gruppen: Tabellen + alle Spiele + Qualifikations-Status (reine Arithmetik)
- Weg zum Titel: selbst befuellbarer, symmetrischer K.o.-Baum -- jeder 16tel-Platz ist
  ein Auswahlfeld ("Sieger Gruppe A" -> Team waehlen); entschiedene Plaetze werden
  automatisch gesperrt. Sieger antippen -> bis zum Finale. Nichts wird behauptet.
- Spielplan: Ergebnisse + kommende Anstosszeiten (ohne Prognosen)

Read-only aus data/, stdlib-only, pipeline-getrennt (analysis/-Carve-out).
Ausgabe: analysis/site/index.html -> direkt auf Netlify deploybar (Ordner droppen).

Datenbasis: fixtures.json (openfootball). Optional daruebergelegt werden
lokal gepflegte Ergebnisse (manual_results.json und, falls vorhanden, die
'actuals' aus manual_pool_tips.json) -- die koennen openfootball einen
Spieltag voraus sein. Beide Overlays sind optional; fehlen sie, zaehlt allein
fixtures.json. Nichts erfunden.
"""
from __future__ import annotations

import json
import itertools
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(HERE, "site")
OUT = os.path.join(SITE, "index.html")

# --- Seiten-Branding (frei anpassbar) ----------------------------------------
# Alles, was an dieser Instanz haengt, steht hier -- nicht im Markup verstreut.
SITE_BRAND = os.environ.get("WM_SITE_BRAND", "Pokalkurs")
SITE_TITLE = os.environ.get("WM_SITE_TITLE", f"{SITE_BRAND} \u00b7 WM 2026")
SITE_HEADLINE = os.environ.get("WM_SITE_HEADLINE", "Der Weg zum Titel")
SITE_DESCRIPTION = os.environ.get(
    "WM_SITE_DESCRIPTION",
    f"{SITE_BRAND} \u2014 WM 2026: Gruppen, Ergebnisse und der Weg ins Finale. "
    "Spiel den K.-o.-Baum selbst durch.",
)
# Akzentfarbe der Seite (CSS-Variable --acc).
SITE_ACCENT = os.environ.get("WM_SITE_ACCENT", "#34c759")

# englischer Quellname -> (deutscher Anzeigename, Flaggen-Emoji)
TEAMS = {
    "Czech Republic": ("Tschechien", "\U0001F1E8\U0001F1FF"),
    "Mexico": ("Mexiko", "\U0001F1F2\U0001F1FD"),
    "South Africa": ("Südafrika", "\U0001F1FF\U0001F1E6"),
    "South Korea": ("Südkorea", "\U0001F1F0\U0001F1F7"),
    "Bosnia & Herzegovina": ("Bosnien-Herz.", "\U0001F1E7\U0001F1E6"),
    "Canada": ("Kanada", "\U0001F1E8\U0001F1E6"),
    "Qatar": ("Katar", "\U0001F1F6\U0001F1E6"),
    "Switzerland": ("Schweiz", "\U0001F1E8\U0001F1ED"),
    "Brazil": ("Brasilien", "\U0001F1E7\U0001F1F7"),
    "Haiti": ("Haiti", "\U0001F1ED\U0001F1F9"),
    "Morocco": ("Marokko", "\U0001F1F2\U0001F1E6"),
    "Scotland": ("Schottland", "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"),
    "Australia": ("Australien", "\U0001F1E6\U0001F1FA"),
    "Paraguay": ("Paraguay", "\U0001F1F5\U0001F1FE"),
    "Turkey": ("Türkei", "\U0001F1F9\U0001F1F7"),
    "USA": ("USA", "\U0001F1FA\U0001F1F8"),
    "Curaçao": ("Curaçao", "\U0001F1E8\U0001F1FC"),
    "Ecuador": ("Ecuador", "\U0001F1EA\U0001F1E8"),
    "Germany": ("Deutschland", "\U0001F1E9\U0001F1EA"),
    "Ivory Coast": ("Elfenbeinküste", "\U0001F1E8\U0001F1EE"),
    "Japan": ("Japan", "\U0001F1EF\U0001F1F5"),
    "Netherlands": ("Niederlande", "\U0001F1F3\U0001F1F1"),
    "Sweden": ("Schweden", "\U0001F1F8\U0001F1EA"),
    "Tunisia": ("Tunesien", "\U0001F1F9\U0001F1F3"),
    "Belgium": ("Belgien", "\U0001F1E7\U0001F1EA"),
    "Egypt": ("Ägypten", "\U0001F1EA\U0001F1EC"),
    "Iran": ("Iran", "\U0001F1EE\U0001F1F7"),
    "New Zealand": ("Neuseeland", "\U0001F1F3\U0001F1FF"),
    "Cape Verde": ("Kap Verde", "\U0001F1E8\U0001F1FB"),
    "Saudi Arabia": ("Saudi-Arabien", "\U0001F1F8\U0001F1E6"),
    "Spain": ("Spanien", "\U0001F1EA\U0001F1F8"),
    "Uruguay": ("Uruguay", "\U0001F1FA\U0001F1FE"),
    "France": ("Frankreich", "\U0001F1EB\U0001F1F7"),
    "Iraq": ("Irak", "\U0001F1EE\U0001F1F6"),
    "Norway": ("Norwegen", "\U0001F1F3\U0001F1F4"),
    "Senegal": ("Senegal", "\U0001F1F8\U0001F1F3"),
    "Algeria": ("Algerien", "\U0001F1E9\U0001F1FF"),
    "Argentina": ("Argentinien", "\U0001F1E6\U0001F1F7"),
    "Austria": ("Österreich", "\U0001F1E6\U0001F1F9"),
    "Jordan": ("Jordanien", "\U0001F1EF\U0001F1F4"),
    "Colombia": ("Kolumbien", "\U0001F1E8\U0001F1F4"),
    "DR Congo": ("DR Kongo", "\U0001F1E8\U0001F1E9"),
    "Portugal": ("Portugal", "\U0001F1F5\U0001F1F9"),
    "Uzbekistan": ("Usbekistan", "\U0001F1FA\U0001F1FF"),
    "Croatia": ("Kroatien", "\U0001F1ED\U0001F1F7"),
    "England": ("England", "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"),
    "Ghana": ("Ghana", "\U0001F1EC\U0001F1ED"),
    "Panama": ("Panama", "\U0001F1F5\U0001F1E6"),
}


def de(name):
    return TEAMS.get(name, (name, ""))[0]


def flag(name):
    return TEAMS.get(name, (name, "\U0001F3F3"))[1]


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        return json.load(fh)


def norm_actual(val):
    if isinstance(val, dict):
        val = val.get("actual")
    if isinstance(val, str) and ":" in val:
        a, b = val.split(":")
        return [int(a), int(b)]
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return [int(val[0]), int(val[1])]
    return None


def merge_results(fixtures, pool_actuals, manual_results=None):
    res = {}
    for f in fixtures:
        if f.get("status") == "played" and f.get("result"):
            res[f["match_id"]] = [int(f["result"][0]), int(f["result"][1])]
    for mid, val in pool_actuals.items():
        n = norm_actual(val)
        if n is not None:
            res[mid] = n
    for mid, val in (manual_results or {}).items():
        n = norm_actual(val)
        if n is not None:
            res[mid] = n
    return res


def blank_row(team):
    return dict(team=team, played=0, w=0, d=0, l=0, gf=0, ga=0, gd=0, pts=0, left=0)


def group_fixtures(fixtures, g):
    return [f for f in fixtures if f.get("group") == g]


def standings(group_games, results):
    rows = {}
    for f in group_games:
        for t in (f["home_team"], f["away_team"]):
            rows.setdefault(t, blank_row(t))
    for f in group_games:
        mid, h, a = f["match_id"], f["home_team"], f["away_team"]
        if mid in results:
            hg, ag = results[mid]
            rh, ra = rows[h], rows[a]
            rh["played"] += 1
            ra["played"] += 1
            rh["gf"] += hg
            rh["ga"] += ag
            ra["gf"] += ag
            ra["ga"] += hg
            if hg > ag:
                rh["pts"] += 3
                rh["w"] += 1
                ra["l"] += 1
            elif hg < ag:
                ra["pts"] += 3
                ra["w"] += 1
                rh["l"] += 1
            else:
                rh["pts"] += 1
                ra["pts"] += 1
                rh["d"] += 1
                ra["d"] += 1
        else:
            rows[h]["left"] += 1
            rows[a]["left"] += 1
    for r in rows.values():
        r["gd"] = r["gf"] - r["ga"]
    order = sorted(rows.values(), key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
    for i, r in enumerate(order):
        r["pos"] = i + 1
    return order


def classify_group(group_games, results):
    """Szenario-Brute-Force -> Status je Team (punktebasiert, rigoros fuer
    Top-2-Clinch/Elimination; Tordifferenz nur Anzeige-Tiebreak)."""
    teams = set()
    for f in group_games:
        teams.add(f["home_team"])
        teams.add(f["away_team"])
    base_pts = {t: 0 for t in teams}
    remaining = []
    for f in group_games:
        mid, h, a = f["match_id"], f["home_team"], f["away_team"]
        if mid in results:
            hg, ag = results[mid]
            if hg > ag:
                base_pts[h] += 3
            elif hg < ag:
                base_pts[a] += 3
            else:
                base_pts[h] += 1
                base_pts[a] += 1
        else:
            remaining.append((h, a))

    best_pos = {t: 4 for t in teams}
    worst_pos = {t: 1 for t in teams}
    for combo in itertools.product((0, 1, 2), repeat=len(remaining)):
        pts = dict(base_pts)
        for (h, a), o in zip(remaining, combo):
            if o == 0:
                pts[h] += 3
            elif o == 2:
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1
        for t in teams:
            above = sum(1 for o in teams if o != t and pts[o] > pts[t])
            ge = sum(1 for o in teams if o != t and pts[o] >= pts[t])
            best_pos[t] = min(best_pos[t], above + 1)
            worst_pos[t] = max(worst_pos[t], ge + 1)

    status = {}
    for t in teams:
        bp, wp = best_pos[t], worst_pos[t]
        if wp <= 1:
            status[t] = "winner"
        elif wp <= 2:
            status[t] = "through"
        elif bp <= 2:
            status[t] = "alive"
        elif bp == 3:
            status[t] = "brink"
        else:
            status[t] = "out"
    return status


def build_payload():
    fx = load("fixtures.json")
    fixtures = fx["fixtures"]
    # Optionale Frische-Quelle: lokal gepflegte Ergebnisse koennen dem
    # openfootball-Spielplan einen Spieltag voraus sein. Fehlt die Datei
    # (Normalfall ausserhalb der privaten Arbeitskopie), zaehlt allein
    # fixtures.json -- merge_results behandelt beides als optionales Overlay.
    try:
        pool_actuals = load("manual_pool_tips.json").get("actuals", {})
    except FileNotFoundError:
        pool_actuals = {}
    try:
        manual_results = load("manual_results.json").get("results", {})
    except FileNotFoundError:
        manual_results = {}
    bracket = load("bracket_2026.json")
    results = merge_results(fixtures, pool_actuals, manual_results)
    fixtures_by_number = {int(f["match_number"]): f for f in fixtures if f.get("match_number")}
    result_meta = {mid: val for mid, val in manual_results.items() if isinstance(val, dict)}

    # --- Gruppen + Status + Reihenfolge ---
    groups = []
    team_status = {}
    team_group = {}
    group_order = {}
    for g in "ABCDEFGHIJKL":
        gg = group_fixtures(fixtures, g)
        order = standings(gg, results)
        status = classify_group(gg, results)
        group_order[g] = order
        rows = []
        for r in order:
            t = r["team"]
            team_status[t] = status[t]
            team_group[t] = g
            r["status"] = status[t]
            rows.append({
                "team": t, "de": de(t), "flag": flag(t), "pos": r["pos"],
                "played": r["played"], "w": r["w"], "d": r["d"], "l": r["l"],
                "gf": r["gf"], "ga": r["ga"], "gd": r["gd"], "pts": r["pts"],
                "left": r["left"], "status": status[t],
            })
        games = []
        for f in sorted(gg, key=lambda x: x["match_number"]):
            mid = f["match_id"]
            games.append({
                "home_de": de(f["home_team"]), "away_de": de(f["away_team"]),
                "home_flag": flag(f["home_team"]), "away_flag": flag(f["away_team"]),
                "played": mid in results, "score": results.get(mid),
            })
        played_n = sum(1 for f in gg if f["match_id"] in results)
        groups.append({"group": g, "rows": rows, "games": games,
                       "played": played_n, "total": len(gg)})

    # --- Spielplan (rein faktisch) ---
    STAGE_BADGE = {"round_of_32": "16tel", "round_of_16": "Achtel",
                   "quarter": "Viertel", "semi": "Halb", "final": "Finale",
                   "third_place": "Platz 3"}
    STAGE_FULL = {"round_of_32": "Sechzehntelfinale", "round_of_16": "Achtelfinale",
                  "quarter": "Viertelfinale", "semi": "Halbfinale", "final": "Finale"}
    timeline = []
    for f in sorted(fixtures, key=lambda x: (x.get("kickoff_utc") or "", x["match_number"])):
        mid = f["match_id"]
        timeline.append({
            "group": f.get("group"),
            "label": f.get("group") or STAGE_BADGE.get(f.get("stage"), ""),
            "home_de": de(f["home_team"]), "away_de": de(f["away_team"]),
            "home_flag": flag(f["home_team"]), "away_flag": flag(f["away_team"]),
            "kickoff": f.get("kickoff_utc"), "played": mid in results,
            "score": results.get(mid),
        })

    # --- K.o.-Baum: Slots mit Kandidaten (gesperrt wenn entschieden, sonst waehlbar) ---
    def group_done(g):
        return all(r["left"] == 0 for r in group_order[g])

    all_groups_done = all(group_done(g) for g in "ABCDEFGHIJKL")

    # 8 beste Gruppendritte nach AKTUELLEM Stand -> FIFA-Kombinationstabelle ("as is")
    thirds = sorted(((g, group_order[g][2]) for g in "ABCDEFGHIJKL" if len(group_order[g]) >= 3),
                    key=lambda x: (-x[1]["pts"], -x[1]["gd"], -x[1]["gf"], x[0]))
    qstr = "".join(sorted(g for g, _ in thirds[:8]))
    slots_map = {}
    for combo in bracket["third_place_assignment"]["combinations"]:
        if combo["qualified_groups"] == qstr:
            slots_map = combo["slots"]
            break

    def group_slot(g, pos):
        rows = group_order[g]
        team = rows[pos - 1]["team"] if len(rows) >= pos else None
        cand = [r["team"] for r in rows if r["status"] in ("winner", "through", "alive")]
        return {"kind": "group", "group": g, "pos": pos,
                "label": ("Sieger" if pos == 1 else "Zweiter") + f" Gruppe {g}",
                "locked": group_done(g), "team": team, "candidates": cand}

    def third_slot(pool, col):
        tg = slots_map.get(col, "")[1:] if slots_map.get(col) else ""
        team = group_order[tg][2]["team"] if tg else None
        cand = [group_order[g][2]["team"] for g in pool
                if len(group_order[g]) >= 3 and group_order[g][2]["status"] in ("alive", "brink")]
        return {"kind": "third", "pool": pool,
                "label": f"Dritter Gruppe {tg}" if tg else f"3. Platz (Gr. {'/'.join(pool)})",
                "locked": all_groups_done, "team": team, "candidates": cand}

    r32 = []
    for m in bracket["round_of_32"]:
        hs, as_ = m.get("home_slot"), m.get("away_slot")
        tcol, tpool = m.get("third_place_column"), m.get("third_place_pool")
        home = group_slot(hs[1], int(hs[0])) if hs else None
        if as_:
            away = group_slot(as_[1], int(as_[0]))
        elif tpool:
            away = third_slot(tpool, tcol)
        else:
            away = None
        r32.append({"n": m["match_number"], "round": "round_of_32", "home": home, "away": away})

    ko = []
    for r in bracket["rounds"]:
        for m in r["matches"]:
            ko.append({"n": m["match_number"], "round": r["name"],
                       "home_from": m.get("home_from"), "away_from": m.get("away_from")})

    matches_by_number = {m["n"]: m for m in r32 + ko}

    def match_result(match_number):
        fixture = fixtures_by_number.get(int(match_number), {})
        match_id = fixture.get("match_id") or f"ko-{int(match_number):03d}"
        score = results.get(match_id)
        if not score:
            return {"played": False, "score": None, "actual_winner": None}
        home_goals, away_goals = int(score[0]), int(score[1])
        actual_winner = None
        if home_goals > away_goals:
            actual_winner = "home"
        elif away_goals > home_goals:
            actual_winner = "away"
        else:
            penalty_winner = (
                fixture.get("penalty_winner")
                or result_meta.get(match_id, {}).get("penalty_winner")
            )
            if penalty_winner in ("home", "away"):
                actual_winner = penalty_winner
        return {
            "played": True,
            "score": [home_goals, away_goals],
            "actual_winner": actual_winner,
        }

    for match in r32 + ko:
        match.update(match_result(match["n"]))

    def participant_name(match_number, side):
        match = matches_by_number.get(int(match_number))
        if not match:
            return None
        if match.get("round") == "round_of_32":
            slot = match.get(side)
            return slot.get("team") if isinstance(slot, dict) else None
        source = match.get("home_from") if side == "home" else match.get("away_from")
        return actual_winner_name(source) if source else None

    def actual_winner_name(match_number):
        match = matches_by_number.get(int(match_number))
        if not match or match.get("actual_winner") not in ("home", "away"):
            return None
        return participant_name(match_number, match["actual_winner"])

    # --- fehlende K.o.-Partien (z.B. Finale) in den Spielplan aufnehmen ---
    # Der Spielplan kommt aus fixtures.json; das Finale (und ggf. weitere) fehlt dort noch,
    # steht aber im Bracket. Also aus dem Bracket ergaenzen: Teams aufgeloest (oder "Sieger
    # Halbfinale N"), Datum aus Fallback.
    _fixture_nums = {f["match_number"] for f in fixtures}
    _KO_KICKOFF = {104: "2026-07-19T19:00:00+00:00"}
    _round_pos = {}
    for _km in ko:
        _round_pos.setdefault(_km["round"], []).append(_km["n"])
    for _r in _round_pos:
        _round_pos[_r].sort()

    def _feeder_label(feeder_n):
        _fm = matches_by_number.get(feeder_n)
        if not _fm:
            return "Sieger"
        _rn = STAGE_FULL.get(_fm["round"], "Sieger")
        _lst = _round_pos.get(_fm["round"], [])
        if len(_lst) > 1 and feeder_n in _lst:
            return "Sieger " + _rn + " " + str(_lst.index(feeder_n) + 1)
        return "Sieger " + _rn

    for _km in ko:
        if _km["n"] in _fixture_nums:
            continue
        _hn = participant_name(_km["n"], "home")
        _an = participant_name(_km["n"], "away")
        timeline.append({
            "group": None,
            "label": STAGE_BADGE.get(_km["round"], ""),
            "home_de": de(_hn) if _hn else _feeder_label(_km.get("home_from")),
            "away_de": de(_an) if _an else _feeder_label(_km.get("away_from")),
            "home_flag": flag(_hn) if _hn else "",
            "away_flag": flag(_an) if _an else "",
            "kickoff": _KO_KICKOFF.get(_km["n"]),
            "played": _km.get("played", False),
            "score": _km.get("score"),
        })

    # Spiel um Platz 3 (FIFA-Spiel 103): nicht im Bracket -> separat ergaenzen.
    # Teams = die beiden Halbfinal-Verlierer (loest sich auf, sobald die Halbfinals gespielt sind).
    def _loser_name(match_number):
        _lm = matches_by_number.get(match_number)
        if not _lm or _lm.get("actual_winner") not in ("home", "away"):
            return None
        _ls = "away" if _lm["actual_winner"] == "home" else "home"
        return participant_name(match_number, _ls)

    # ... aber nur, solange es dafuer kein echtes Fixture gibt (sonst doppelte Zeile).
    _semis = _round_pos.get("semi", [])
    if len(_semis) == 2 and 103 not in _fixture_nums:
        _tp_score = results.get("ko-103")
        _l1 = _loser_name(_semis[0])
        _l2 = _loser_name(_semis[1])
        timeline.append({
            "group": None,
            "label": "Platz 3",
            "home_de": de(_l1) if _l1 else "Verlierer Halbfinale 1",
            "away_de": de(_l2) if _l2 else "Verlierer Halbfinale 2",
            "home_flag": flag(_l1) if _l1 else "",
            "away_flag": flag(_l2) if _l2 else "",
            "kickoff": "2026-07-18T21:00:00+00:00",
            "played": _tp_score is not None,
            "score": _tp_score,
        })

    qualified_set = {
        team
        for match in r32
        for team in (
            (match.get("home") or {}).get("team"),
            (match.get("away") or {}).get("team"),
        )
        if team
    }
    ko_losers = set()
    ko_history = []
    round_labels = {
        "round_of_32": "Sechzehntelfinale",
        "round_of_16": "Achtelfinale",
        "quarter": "Viertelfinale",
        "semi": "Halbfinale",
        "final": "Finale",
    }
    for match in sorted(r32 + ko, key=lambda row: int(row["n"])):
        if not match.get("played"):
            continue
        home = participant_name(match["n"], "home")
        away = participant_name(match["n"], "away")
        if not home or not away:
            continue
        winner = actual_winner_name(match["n"])
        loser = None
        if winner == home:
            loser = away
        elif winner == away:
            loser = home
        if loser:
            ko_losers.add(loser)
        ko_history.append({
            "n": match["n"],
            "round": match["round"],
            "round_de": round_labels.get(match["round"], match["round"]),
            "home": home,
            "away": away,
            "home_de": de(home),
            "away_de": de(away),
            "home_flag": flag(home),
            "away_flag": flag(away),
            "score": match.get("score"),
            "winner": winner,
            "winner_de": de(winner) if winner else None,
            "winner_flag": flag(winner) if winner else None,
        })
    remaining_set = qualified_set - ko_losers
    # Ist das Finale gespielt, "verbleibt" niemand mehr: der Weltmeister ist
    # kein Verlierer und blieb sonst als "1 verbleibend" stehen, obwohl das
    # Turnier vorbei ist. (Sichtbarer Off-by-one bei 104/104.)
    _final_winner = actual_winner_name(104)
    if _final_winner:
        remaining_set = remaining_set - {_final_winner}

    if all_groups_done:
        for group in groups:
            for row in group["rows"]:
                team = row["team"]
                if team in qualified_set:
                    row["status"] = "winner" if row["pos"] == 1 else "through"
                else:
                    row["status"] = "out"
                team_status[team] = row["status"]

    # team_meta inkl. "score" = aktueller Tabellen-Rang-Proxy (Default-Weiterkommen)
    team_meta = {}
    for g in "ABCDEFGHIJKL":
        for r in group_order[g]:
            t = r["team"]
            team_meta[t] = {"de": de(t), "flag": flag(t), "group": g,
                            "score": r["pts"] * 100 + r["gd"] * 10 + r["gf"]}

    # --- faktische Kennzahlen ---
    played_total = sum(1 for f in fixtures if f["match_id"] in results)
    goals_total = sum(sum(results[f["match_id"]]) for f in fixtures if f["match_id"] in results)
    n_remaining = len(remaining_set)
    n_eliminated = len(team_status) - n_remaining
    biggest = None
    for f in fixtures:
        mid = f["match_id"]
        if mid not in results:
            continue
        hg, ag = results[mid]
        margin, tot = abs(hg - ag), hg + ag
        win, lose = ((f["home_team"], f["away_team"]) if hg >= ag else (f["away_team"], f["home_team"]))
        card = {"win_de": de(win), "win_flag": flag(win), "lose_de": de(lose),
                "lose_flag": flag(lose), "score": f"{max(hg, ag)}:{min(hg, ag)}"}
        if biggest is None or (margin, tot) > biggest[0]:
            biggest = ((margin, tot), card)

    # --- Turnier-Rekorde (nur aus Ergebnissen; Match-Statistiken wie Ecken/Abseits gibt es nicht) ---
    tgf, tga, tgames = {}, {}, {}
    most_goals = None
    for f in fixtures:
        mid = f["match_id"]
        if mid not in results:
            continue
        hg, ag = results[mid]
        h, a = f["home_team"], f["away_team"]
        for t in (h, a):
            tgames[t] = tgames.get(t, 0) + 1
        tgf[h] = tgf.get(h, 0) + hg
        tga[h] = tga.get(h, 0) + ag
        tgf[a] = tgf.get(a, 0) + ag
        tga[a] = tga.get(a, 0) + hg
        if most_goals is None or (hg + ag) > most_goals["total"]:
            most_goals = {"total": hg + ag, "score": f"{hg}:{ag}",
                          "home_de": de(h), "home_flag": flag(h),
                          "away_de": de(a), "away_flag": flag(a)}

    best_attack = None
    if tgf:
        _ba = max(tgf, key=lambda t: (tgf[t], -tgames.get(t, 0)))
        best_attack = {"de": de(_ba), "flag": flag(_ba),
                       "goals": tgf[_ba], "games": tgames.get(_ba, 0)}
    best_defense = None
    _dcand = [t for t in tgames if tgames[t] >= 4]
    if _dcand:
        _bd = min(_dcand, key=lambda t: (tga.get(t, 0) / tgames[t], tga.get(t, 0)))
        best_defense = {"de": de(_bd), "flag": flag(_bd),
                        "conceded": tga.get(_bd, 0), "games": tgames[_bd]}

    shootouts = sum(1 for v in manual_results.values()
                    if isinstance(v, dict) and v.get("penalty_winner"))

    podium = None
    _champ = actual_winner_name(104)
    if _champ:
        _fin = matches_by_number.get(104) or {}
        _ru = participant_name(104, "away" if _fin.get("actual_winner") == "home" else "home")
        _third = None
        _tp, _tpf = results.get("ko-103"), None
        for f in fixtures:
            if f["match_id"] == "ko-103":
                _tpf = f
                break
        if _tp and _tpf:
            _third = _tpf["home_team"] if _tp[0] > _tp[1] else _tpf["away_team"]
        podium = {
            "champion": {"de": de(_champ), "flag": flag(_champ)},
            "runner_up": {"de": de(_ru), "flag": flag(_ru)} if _ru else None,
            "third": {"de": de(_third), "flag": flag(_third)} if _third else None,
        }

    # Weg des Weltmeisters: alle Partien des Champions in Spielreihenfolge
    champ_path = None
    if _champ:
        champ_path = []
        for f in sorted((x for x in fixtures if x["match_id"] in results),
                        key=lambda x: x["match_number"]):
            h, a = f["home_team"], f["away_team"]
            if _champ not in (h, a):
                continue
            hg, ag = results[f["match_id"]]
            gf, ga = (hg, ag) if h == _champ else (ag, hg)
            opp = a if h == _champ else h
            lab = f.get("group") or STAGE_BADGE.get(f.get("stage"), "")
            champ_path.append({"flag": flag(opp), "de": f"{lab} · {gf}:{ga}"})

    # Statische Turnier-Fakten (Auszeichnungen/Rekorde), optional gepflegt
    try:
        facts = load("manual_tournament_facts.json")
    except Exception:
        facts = {}

    remaining_teams = sorted(
        [{"de": de(t), "flag": flag(t), "group": team_group.get(t, "")}
         for t in remaining_set],
        key=lambda x: (x["group"], x["de"]),
    )

    return {
        "groups": groups,
        "timeline": timeline,
        "bracket": {"r32": r32, "ko": ko, "all_groups_done": all_groups_done, "team_meta": team_meta},
        "ko_history": ko_history,
        "remaining_teams": remaining_teams,
        "stats": {
            "played": played_total, "total": len(fixtures),
            "goals": goals_total, "remaining": n_remaining, "eliminated": n_eliminated,
            "biggest": biggest[1] if biggest else None,
            "most_goals": most_goals, "best_attack": best_attack,
            "best_defense": best_defense, "shootouts": shootouts, "podium": podium,
            "champ_path": champ_path,
            "awards": facts.get("awards") or [],
            "records": facts.get("records") or {},
        },
    }


def render_html(payload):
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = _TEMPLATE.replace("__DATA__", blob)
    for placeholder, value in (
        ("__SITE_TITLE__", SITE_TITLE),
        ("__SITE_BRAND__", SITE_BRAND),
        ("__SITE_HEADLINE__", SITE_HEADLINE),
        ("__SITE_DESCRIPTION__", SITE_DESCRIPTION),
        ("__SITE_ACCENT__", SITE_ACCENT),
    ):
        html = html.replace(placeholder, value)
    return html


def main():
    payload = build_payload()
    os.makedirs(SITE, exist_ok=True)
    html = render_html(payload)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"geschrieben: {OUT}  ({len(html) // 1024} KB)")
    print(f"  Spiele {payload['stats']['played']}/{payload['stats']['total']}"
          f" | verbleibend {payload['stats']['remaining']} | ausgeschieden {payload['stats']['eliminated']}")
    print("  Deploy: Ordner 'analysis/site' auf app.netlify.com/drop ziehen")


# ---------------------------------------------------------------------------
# HTML-Template (Apple-clean, hell, System-Schrift, iOS-Farben) -- via __DATA__
# ---------------------------------------------------------------------------
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#ffffff">
<meta name="description" content="__SITE_DESCRIPTION__">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="__SITE_BRAND__">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<title>__SITE_TITLE__</title>
<style>
:root{
  --bg:#fbfbfd; --bg2:#f1f1f4; --card:#ffffff; --ink:#1d1d1f; --ink2:#3c3c43;
  --muted:#6e6e73; --faint:#a5a5ac; --line:#e6e6ea; --line2:#efeff2;
  --acc:__SITE_ACCENT__; --acc-d:#1f8f3c; --acc-soft:#e6f8ec;
  --blue:#007aff; --blue-soft:#e6f0ff; --blue-d:#0a62cc;
  --amber:#ff9500; --amber-soft:#fff1dc; --amber-d:#a25e00;
  --red:#ff3b30; --red-soft:#ffe6e4; --red-d:#bf271e;
  --gold:#c39214; --gold-soft:#faf1d6;
  --sh-sm:0 .5px 1.5px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.05);
  --sh:0 1px 2px rgba(0,0,0,.04),0 8px 22px rgba(0,0,0,.06);
  --sh-lg:0 2px 8px rgba(0,0,0,.05),0 22px 50px rgba(0,0,0,.1);
  --r:18px; --r2:13px; --r3:24px;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Segoe UI",system-ui,Roboto,sans-serif;
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums;-webkit-tap-highlight-color:transparent;
}
h1,h2,h3{margin:0;font-weight:800;letter-spacing:-.022em}
.wrap{max-width:1120px;margin:0 auto;padding:0 18px calc(96px + env(safe-area-inset-bottom))}

/* nav */
.topbar{position:sticky;top:0;z-index:30;background:rgba(251,251,253,.8);backdrop-filter:blur(18px) saturate(1.4);
  border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top)}
.topbar-in{max-width:1120px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:12px}
.brand{display:flex;align-items:center;gap:9px;font-weight:800;font-size:15px;letter-spacing:-.02em;flex:0 0 auto}
.brand .ball{width:26px;height:26px;border-radius:50%;background:var(--acc);display:grid;place-items:center;
  color:#fff;font-size:13px;box-shadow:0 2px 9px rgba(52,199,89,.45)}
nav{margin-left:auto;display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{font-family:inherit;border:0;background:transparent;color:var(--muted);font-weight:600;font-size:14px;
  padding:8px 13px;border-radius:980px;cursor:pointer;white-space:nowrap;transition:.16s;min-height:38px}
nav button:hover{color:var(--ink)}
nav button.on{color:#fff;background:var(--ink)}

section{display:none;animation:rise .4s cubic-bezier(.2,.7,.2,1) both}
section.on{display:block}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}

/* hero */
.hero{padding:36px 2px 22px}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:700;letter-spacing:.02em;
  color:var(--acc-d);background:var(--acc-soft);padding:6px 13px;border-radius:980px}
.hero h1{font-size:clamp(38px,8.5vw,76px);font-weight:800;line-height:.96;margin:16px 0 0;letter-spacing:-.04em}
.hero h1 .g{color:var(--acc-d)}
.hero .sub{font-size:17px;color:var(--ink2);max-width:560px;margin:14px 0 0;font-weight:450}
.hero .meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.pill{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--ink2);
  background:var(--card);border:1px solid var(--line);border-radius:980px;padding:7px 14px;box-shadow:var(--sh-sm)}
.pill .d{width:7px;height:7px;border-radius:50%;background:var(--acc)}

.sec-head{margin:8px 2px 18px}
.sec-head h2{font-size:clamp(23px,4vw,30px);letter-spacing:-.03em}
.sec-head p{color:var(--muted);font-size:14.5px;margin:7px 0 0;max-width:680px}

/* kpi */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:13px;margin:4px 0 26px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 19px;box-shadow:var(--sh-sm);
  transition:transform .16s,box-shadow .16s}
.kpi:hover{transform:translateY(-2px);box-shadow:var(--sh)}
.kpi .lab{font-size:12px;font-weight:600;letter-spacing:.01em;color:var(--muted)}
.kpi .num{font-weight:800;font-size:44px;line-height:1.02;margin-top:8px;letter-spacing:-.04em}
.kpi .num small{font-size:21px;color:var(--faint);font-weight:700}
.kpi .sub{font-size:12.5px;color:var(--muted);margin-top:4px}
.kpi.acc .num{color:var(--acc-d)} .kpi.warn .num{color:var(--red-d)}

/* headline cards */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:13px;margin-bottom:30px}
.hcard{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:17px 19px;box-shadow:var(--sh-sm)}
.hcard .t{font-size:11.5px;font-weight:700;letter-spacing:.02em;color:var(--muted);display:flex;align-items:center;gap:7px}
.hcard .t .dot{width:7px;height:7px;border-radius:50%;background:var(--acc)}
.hcard.warn .t .dot{background:var(--red)} .hcard.blue .t .dot{background:var(--blue)}
.hcard.gold .t .dot{background:var(--gold)}
.hcard.gold{background:linear-gradient(120deg,var(--gold-soft),var(--card) 68%);border-color:#eaddb0}
.hcard .m{font-size:19px;font-weight:800;line-height:1.2;margin-top:9px;letter-spacing:-.02em}
.hcard .d{font-size:13px;color:var(--muted);margin-top:7px}
.hcard .teams{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.hcard.wide{grid-column:1/-1}
.tg{display:inline-flex;align-items:center;gap:5px;font-size:13px;font-weight:600;background:var(--bg2);
  border-radius:980px;padding:4px 11px}
.ko-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin:0 0 28px}
.koh{background:var(--card);border:1px solid var(--line);border-radius:var(--r2);padding:13px 15px;box-shadow:var(--sh-sm)}
.koh .kr{font-size:11px;color:var(--muted);font-weight:700;letter-spacing:.02em;margin-bottom:8px}
.koh .km{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:9px;font-size:14px}
.koh .team{display:flex;align-items:center;gap:7px;min-width:0;font-weight:600}
.koh .team:first-child{justify-content:flex-end;text-align:right}
.koh .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.koh .score{font-weight:800;background:var(--ink);color:#fff;border-radius:8px;padding:3px 9px}
.koh .winner{color:var(--acc-d);font-weight:800}

/* mini groups */
.mini{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:11px}
.mg{background:var(--card);border:1px solid var(--line);border-radius:var(--r2);padding:13px 14px;box-shadow:var(--sh-sm)}
.mg .h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px}
.mg .h b{font-size:14px;font-weight:700;letter-spacing:-.01em} .mg .h span{font-size:11px;color:var(--faint);font-weight:600}
.mrow{display:flex;align-items:center;gap:7px;font-size:13px;padding:2.5px 0}
.mrow .fl{font-size:15px} .mrow .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mrow .pt{font-weight:700} .mrow.cut{border-bottom:1.5px solid var(--acc);padding-bottom:7px;margin-bottom:2px}
.mrow .dot{width:7px;height:7px;border-radius:50%;background:var(--c)}

/* status colors */
.st-winner{--c:var(--gold);--cs:var(--gold-soft);--ci:#8a6410}
.st-through{--c:var(--acc);--cs:var(--acc-soft);--ci:var(--acc-d)}
.st-alive{--c:var(--blue);--cs:var(--blue-soft);--ci:var(--blue-d)}
.st-brink{--c:var(--amber);--cs:var(--amber-soft);--ci:var(--amber-d)}
.st-out{--c:var(--red);--cs:var(--red-soft);--ci:var(--red-d)}

/* group cards */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.gcard{background:var(--card);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--sh-sm);overflow:hidden}
.gcard .gh{display:flex;align-items:center;justify-content:space-between;padding:15px 18px 12px}
.gcard .gh b{font-size:19px;font-weight:800;letter-spacing:-.02em} .gcard .gh .pr{font-size:11.5px;color:var(--faint);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:13.5px}
.gcard th{font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;color:var(--faint);font-weight:600;text-align:right;padding:6px 7px}
.gcard th.l{text-align:left;padding-left:18px}
.gcard td{padding:8px 7px;border-top:1px solid var(--line2);text-align:right}
.gcard td.l{text-align:left;padding-left:18px;display:flex;align-items:center;gap:9px}
.gcard tr.cut td{border-bottom:2px solid var(--acc)}
.pos{width:21px;height:21px;border-radius:7px;display:grid;place-items:center;font-size:11px;font-weight:700;background:var(--cs);color:var(--ci);flex:0 0 auto}
.gcard .fl{font-size:18px;flex:0 0 auto} .gcard .nm{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gcard td.pts{font-weight:800} .gcard .gd{color:var(--muted)}
.games{border-top:1px solid var(--line2);padding:12px 18px 15px;background:var(--bg)}
.games .gt{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);font-weight:600;margin-bottom:8px}
.gm{display:flex;align-items:center;gap:9px;font-size:13px;padding:3px 0;color:var(--ink2)}
.gm .ht{flex:1;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gm .at{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gm .sc{font-weight:700;background:var(--ink);color:#fff;border-radius:7px;padding:2px 8px;font-size:12px;min-width:40px;text-align:center}
.gm .sc.soon{background:transparent;color:var(--faint);border:1px solid var(--line);font-weight:600}

/* champion + controls */
.champ{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 19px;box-shadow:var(--sh-sm);
  display:flex;align-items:center;gap:15px;margin-bottom:14px;min-height:76px}
.champ.done{background:linear-gradient(120deg,var(--gold-soft),var(--card) 72%);border-color:#eaddb0}
.champ .trophy{font-size:34px;flex:0 0 auto}
.champ .lab{font-size:11.5px;font-weight:700;letter-spacing:.02em;color:var(--muted)}
.champ .who{font-size:25px;font-weight:800;line-height:1.05;margin-top:3px;display:flex;align-items:center;gap:11px;letter-spacing:-.03em}
.champ .who .fl{font-size:27px} .champ .hint{font-size:13.5px;color:var(--muted);margin-top:3px}
.ctrls{display:flex;gap:9px;margin-bottom:14px;flex-wrap:wrap}
.btn{font-family:inherit;font-weight:600;font-size:14px;border-radius:980px;padding:10px 17px;cursor:pointer;
  border:1px solid var(--line);background:var(--card);color:var(--ink);box-shadow:var(--sh-sm);transition:.15s;min-height:42px}
.btn:hover{transform:translateY(-1px);box-shadow:var(--sh)} .btn:active{transform:translateY(0)}
.btn.p{background:var(--ink);color:#fff;border-color:var(--ink)}
.note{font-size:12.5px;color:var(--muted);background:var(--bg2);border-radius:var(--r2);padding:12px 15px;margin-top:14px}

/* match card (shared) */
.bm{background:var(--card);border:1px solid var(--line);border-radius:var(--r2);box-shadow:var(--sh-sm);overflow:hidden;width:100%}
.bm.path{border-color:var(--gold);box-shadow:0 0 0 2px var(--gold-soft)}
.slot{display:flex;align-items:center;gap:8px;padding:8px 11px;min-height:44px;
  user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:manipulation}
.slot+.slot{border-top:1px solid var(--line2)}
.slot .ed{font-size:14px;color:var(--faint);flex:0 0 auto;opacity:.55;letter-spacing:1px}
.slot.team:active{background:var(--bg2)}
.pickwrap{position:fixed;inset:0;background:rgba(20,20,30,.34);backdrop-filter:blur(2px);
  display:flex;align-items:flex-end;justify-content:center;z-index:60;padding:0;animation:fade .15s both}
@media(min-width:560px){.pickwrap{align-items:center;padding:20px}}
@keyframes fade{from{opacity:0}to{opacity:1}}
.pickcard{background:var(--card);border-radius:22px 22px 0 0;box-shadow:var(--sh-lg);
  width:100%;max-width:440px;max-height:78vh;overflow:auto;padding:8px 8px calc(12px + env(safe-area-inset-bottom))}
@media(min-width:560px){.pickcard{border-radius:20px}}
.pickh{font-weight:700;font-size:14px;padding:14px 12px 10px;color:var(--muted)}
.pickopt{display:flex;align-items:center;gap:11px;width:100%;border:0;background:transparent;
  padding:13px 12px;border-radius:13px;font-family:inherit;font-size:16px;font-weight:600;color:var(--ink);cursor:pointer;text-align:left;min-height:50px}
.pickopt:hover,.pickopt:active{background:var(--bg2)}
.pickopt.cur{background:var(--acc-soft);color:var(--acc-d)}
.pickopt .fl{font-size:20px;flex:0 0 auto} .pickopt .nm{flex:1}
.slot .fl{font-size:16px;flex:0 0 auto} .slot .nm{flex:1;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.slot .scmini{font-size:13px;font-weight:800;color:var(--ink);background:var(--bg2);border-radius:7px;padding:2px 7px;flex:0 0 auto}
.slot .pl{font-size:10px;color:var(--faint);font-weight:700;flex:0 0 auto}
.slot .pl.prov{font-style:italic;opacity:.75}
.slot.team{cursor:pointer} .slot.team:hover{background:var(--bg2)}
.slot.locked{cursor:default}.slot.locked:hover{background:transparent}.slot.locked.win:hover{background:var(--acc-soft)}
.slot.win{background:var(--acc-soft)} .slot.win:hover{background:var(--acc-soft)}
.slot.win .nm{color:var(--acc-d);font-weight:800} .slot.win .pl{color:var(--acc-d)}
.slot.lose{opacity:.4} .slot.lose .nm{text-decoration:line-through}
.slot.tbd{color:var(--faint)} .slot.tbd .nm{font-weight:500}
.slot select{flex:1;border:1px solid var(--line);background:var(--bg2);border-radius:9px;padding:7px 8px;
  font-family:inherit;font-size:13px;font-weight:600;color:var(--ink);min-height:34px;max-width:100%}
.slot .edit{font-size:13px;color:var(--faint);cursor:pointer;padding:3px 7px;border-radius:7px;flex:0 0 auto}
.slot .edit:hover{background:var(--bg2);color:var(--ink2)}

/* round funnel rail */
.rail{display:flex;align-items:center;justify-content:center;gap:0;margin-bottom:20px;overflow-x:auto;scrollbar-width:none;padding-bottom:2px}
.rail::-webkit-scrollbar{display:none}
.rnode{flex:0 0 auto;min-width:92px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 12px;
  text-align:center;cursor:pointer;box-shadow:var(--sh-sm);transition:.15s}
.rnode:hover{transform:translateY(-1px);box-shadow:var(--sh)}
.rnode.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.rnode.done{border-color:var(--acc)}
.rnode .rn{font-size:13px;font-weight:700;letter-spacing:-.01em}
.rnode .rc{font-size:11px;color:var(--muted);margin-top:2px;font-weight:600} .rnode.on .rc{color:rgba(255,255,255,.72)}
.rnode.cup{min-width:62px;background:var(--gold-soft);border-color:#e9dcae}
.rnode.cup.done{background:var(--gold);border-color:var(--gold)}
.rnode .cupf{font-size:22px;line-height:1}
.rlink{flex:0 0 auto;width:16px;height:2px;background:var(--line);align-self:center}
.rlink.done{background:var(--acc)}
@media(max-width:560px){.rail{justify-content:flex-start} .rnode{min-width:78px;padding:9px 9px} .rlink{width:8px}}
.rgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(236px,1fr));gap:12px}
.rgrid.one{max-width:340px;margin:0 auto} .rgrid.two{max-width:600px;margin:0 auto}
.rtitle{font-size:13px;font-weight:700;color:var(--ink2);margin:2px 2px 12px;letter-spacing:-.01em}
.rtitle span{color:var(--muted);font-weight:600}

/* radialer K.o.-Baum */
.radialbox{max-width:560px;margin:4px auto 6px}
.radialsvg{width:100%;height:auto;display:block;overflow:visible;-webkit-tap-highlight-color:transparent}
.rn-node{cursor:pointer;transition:opacity .18s}
.rn-node:hover{opacity:.7}
.rn-dim{opacity:.5;filter:grayscale(1)}
.rn-fl{dominant-baseline:central;text-anchor:middle;pointer-events:none}
.rn-cap{text-align:center;font-size:12.5px;color:var(--muted);margin:0 auto 20px;max-width:460px}

/* schedule */
.sctrl{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px}
select.gsel{font-family:inherit;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:11px;
  padding:9px 13px;font-size:14px;font-weight:600;min-height:42px;box-shadow:var(--sh-sm)}
.day{margin-bottom:6px}
.dh{font-weight:800;font-size:15px;color:var(--ink2);padding:17px 2px 9px;position:sticky;top:55px;letter-spacing:-.01em;
  background:linear-gradient(180deg,var(--bg) 60%,transparent);z-index:1}
.fx{display:grid;grid-template-columns:52px 1fr auto 1fr;align-items:center;gap:11px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--r2);padding:11px 15px;margin-bottom:8px;box-shadow:var(--sh-sm)}
.fx .gp{font-size:9.5px;font-weight:700;color:var(--faint);text-align:center;background:var(--bg2);border-radius:8px;padding:5px 0}
.fx.done .gp{background:var(--acc-soft);color:var(--acc-d)}
.fx .hm{display:flex;align-items:center;gap:8px;justify-content:flex-end;font-weight:600;text-align:right;min-width:0}
.fx .aw{display:flex;align-items:center;gap:8px;font-weight:600;min-width:0}
.fx .nm{white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .fx .fl{font-size:18px;flex:0 0 auto}
.fx .mid{text-align:center;min-width:52px}
.fx .res{font-weight:800;background:var(--ink);color:#fff;border-radius:8px;padding:3px 9px;font-size:14px}
.fx .clk{font-size:12.5px;color:var(--faint);font-weight:600}

.foot{margin-top:34px;padding-top:18px;border-top:1px solid var(--line);font-size:12px;color:var(--faint);line-height:1.7}
@media(max-width:560px){.hero{padding:26px 2px 16px} .kpi .num{font-size:38px} .fx{grid-template-columns:46px 1fr auto 1fr;gap:8px;padding:10px 12px}}
</style>
</head>
<body>
<div class="topbar"><div class="topbar-in">
  <div class="brand"><span class="ball">●</span>__SITE_BRAND__</div>
  <nav id="nav"></nav>
</div></div>
<div class="wrap">
  <header class="hero">
    <span class="eyebrow">Kanada · Mexiko · USA</span>
    <h1>Der Weg zum <span class="g">Titel</span></h1>
    <p class="sub" id="sub"></p>
    <div class="meta" id="meta"></div>
  </header>
  <section id="sec-overview" class="on"></section>
  <section id="sec-groups"></section>
  <section id="sec-bracket"></section>
  <section id="sec-schedule"></section>
  <div class="foot" id="foot"></div>
</div>
<script>
const DATA=__DATA__;
const $=(s,r=document)=>r.querySelector(s);
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SMETA={winner:'st-winner',through:'st-through',alive:'st-alive',brink:'st-brink',out:'st-out'};
const MON=['Jan.','Feb.','März','Apr.','Mai','Juni','Juli','Aug.','Sep.','Okt.','Nov.','Dez.'];
// Zeiten/Datum in deutscher Ortszeit (Europe/Berlin = MESZ/UTC+2 im Turnierzeitraum)
function dparts(iso){if(!iso)return null;const d=new Date(iso);
  const p=new Intl.DateTimeFormat('de-DE',{timeZone:'Europe/Berlin',weekday:'short',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(d);
  const g=t=>(p.find(x=>x.type===t)||{}).value||'';
  return {key:`${g('year')}-${g('month')}-${g('day')}`,wd:g('weekday').replace('.',''),day:parseInt(g('day'),10),mon:MON[parseInt(g('month'),10)-1],hh:g('hour'),mm:g('minute')};}

const TABS=[['overview','Überblick'],['groups','Gruppen'],['bracket','Weg zum Titel'],['schedule','Spielplan']];
function buildNav(){const n=$('#nav');TABS.forEach(([id,l])=>{const b=el('button',null,l);b.dataset.id=id;b.onclick=()=>show(id);n.appendChild(b);});}
function show(id){document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.id===id));
  document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id==='sec-'+id));
  window.scrollTo({top:0,behavior:'instant'});}

function hero(){const s=DATA.stats;
  $('#sub').innerHTML=`Gruppen, Ergebnisse und der Weg ins Finale — aktuell: <b>${s.played} von ${s.total}</b> Turnierspielen gespielt.`;
  $('#meta').innerHTML=`<span class="pill"><span class="d"></span>Spiele ${s.played}/${s.total}</span>`+
    `<span class="pill"><span class="d"></span>${s.goals} Tore</span>`+
    `<span class="pill"><span class="d"></span>${s.remaining} verbleibend</span>`;
  $('#foot').innerHTML='WM 2026 · Kanada, Mexiko &amp; USA · 11. Juni – 19. Juli 2026. '+
    'Die Vorrunde umfasst <b>72 Spiele</b> (12 Gruppen × 6); dazu kommen 32 K.-o.-Spiele — <b>104 insgesamt</b>. '+
    'Die Zahlen oben zählen alle Spiele, die im aktuellen lokalen Spielplan enthalten sind. '+
    'Status (durch / vor dem Aus) ergibt sich rein rechnerisch aus den noch offenen Gruppenspielen. '+
    'Im „Weg zum Titel" füllst du den K.-o.-Baum selbst — dein Tipp bleibt nur lokal in deinem Browser.';}

/* overview */
function renderOverview(){const s=DATA.stats,w=$('#sec-overview');w.innerHTML='';
  const k=el('div','kpis'),fin=!!s.podium;
  (fin?[['acc',`${s.played}<small> / ${s.total}</small>`,'Turnierspiele','alle gespielt'],
   ['',s.goals,'Tore',(s.records&&s.records.goals_note)?'⌀ '+(s.goals/Math.max(1,s.played)).toFixed(1)+' pro Spiel · Rekord':'⌀ '+(s.goals/Math.max(1,s.played)).toFixed(1)+' pro Spiel'],
   ['',s.shootouts,'Elfmeterschießen','K.-o.-Partien vom Punkt entschieden'],
   (s.records&&s.records.attendance_total)
     ? ['acc',(s.records.attendance_total/1e6).toFixed(2).replace('.',',')+'<small> Mio</small>','Zuschauer',s.records.attendance_note||'']
     : ['',Object.keys(DATA.bracket.team_meta).length,'Nationen','erstmals im 48er-Format']]
  :[['acc',`${s.played}<small> / ${s.total}</small>`,'Turnierspiele','im lokalen Plan gespielt'],
   ['',s.goals,'Tore','⌀ '+(s.goals/Math.max(1,s.played)).toFixed(1)+' pro gespieltem Spiel'],
   ['acc',s.remaining,'Verbleibend','noch im Turnier'],
   ['warn',s.eliminated,'Ausgeschieden','nicht mehr im Titelrennen']]
  ).forEach(([cls,num,lab,sub])=>{const c=el('div','kpi'+(cls?' '+cls:''));
    c.innerHTML=`<div class="lab">${lab}</div><div class="num">${num}</div><div class="sub">${sub}</div>`;k.appendChild(c);});
  w.appendChild(k);
  const cs=el('div','cards'),hl=[];
  if(s.podium){const p=s.podium,rw=[['🥇',p.champion],['🥈',p.runner_up],['🥉',p.third]].filter(x=>x[1]);
    hl.push(['gold wide','Endstand',rw.map(([m,t])=>`${m} ${t.flag} ${esc(t.de)}`).join('&nbsp; · &nbsp;'),'Weltmeister, Vizeweltmeister und Platz 3.']);}
  if(s.biggest)hl.push(['','Höchster Sieg',`${s.biggest.win_flag} ${esc(s.biggest.win_de)} ${s.biggest.score} ${s.biggest.lose_flag} ${esc(s.biggest.lose_de)}`,'Größte Tordifferenz im Turnier.']);
  if(s.most_goals)hl.push(['','Torreichstes Spiel',`${s.most_goals.home_flag} ${esc(s.most_goals.home_de)} ${s.most_goals.score} ${s.most_goals.away_flag} ${esc(s.most_goals.away_de)}`,`${s.most_goals.total} Tore — kein Spiel hatte mehr.`]);
  if(s.best_attack)hl.push(['','Beste Offensive',`${s.best_attack.flag} ${esc(s.best_attack.de)} · ${s.best_attack.goals} Tore`,`Meiste Treffer aller Teams, in ${s.best_attack.games} Spielen.`]);
  if(s.best_defense)hl.push(['blue','Beste Abwehr',`${s.best_defense.flag} ${esc(s.best_defense.de)} · ${s.best_defense.conceded} Gegentor${s.best_defense.conceded===1?'':'e'}`,`Wenigste pro Spiel (ab 4 Spielen), in ${s.best_defense.games} Partien.`]);
  if(s.awards&&s.awards.length){const tm=DATA.bracket.team_meta;
    const chips=s.awards.map(a=>({flag:(tm[a.team]||{}).flag||'',de:`${a.player} · ${a.title}${a.value?' ('+a.value+')':''}`}));
    const nt=s.awards.map(a=>a.note).filter(Boolean)[0]||'';
    hl.push(['gold wide','Auszeichnungen',null,nt,chips]);}
  if(s.champ_path&&s.champ_path.length&&s.podium)
    hl.push(['wide','Der Weg des Weltmeisters',null,`${s.podium.champion.flag} ${esc(s.podium.champion.de)} — alle ${s.champ_path.length} Spiele auf dem Weg zum Titel (Gegner und Ergebnis).`,s.champ_path]);
  if(!s.podium&&DATA.remaining_teams.length)hl.push(['blue wide','Verbleibend im Turnier',null,'Alle Teams, die noch Weltmeister werden können.',DATA.remaining_teams]);
  hl.forEach(([cls,t,m,d,teams])=>{const c=el('div','hcard'+(cls?' '+cls:''));
    let h=`<div class="t"><span class="dot"></span>${t}</div>`;
    if(m)h+=`<div class="m">${m}</div>`;
    if(teams)h+=`<div class="teams">${teams.map(x=>`<span class="tg">${x.flag} ${esc(x.de)}</span>`).join('')}</div>`;
    h+=`<div class="d">${d}</div>`;c.innerHTML=h;cs.appendChild(c);});
  w.appendChild(cs);
  if(DATA.ko_history.length){
    w.appendChild(el('div','sec-head','<h2>K.-o.-Historie</h2><p>Gespielte K.-o.-Partien sind fest und schreiben den Titelbaum fort.</p>'));
    const kol=el('div','ko-list');
    DATA.ko_history.forEach(x=>{const c=el('div','koh');
      const hs=x.score?`${x.score[0]}:${x.score[1]}`:'–:–';
      c.innerHTML=`<div class="kr">Spiel ${x.n} · ${esc(x.round_de)}</div><div class="km">`+
        `<div class="team ${x.winner===x.home?'winner':''}"><span class="nm">${esc(x.home_de)}</span><span>${x.home_flag}</span></div>`+
        `<div class="score">${hs}</div>`+
        `<div class="team ${x.winner===x.away?'winner':''}"><span>${x.away_flag}</span><span class="nm">${esc(x.away_de)}</span></div>`+
        `</div>`;kol.appendChild(c);});
    w.appendChild(kol);
  }
  w.appendChild(el('div','sec-head','<h2>Alle 12 Gruppen</h2><p>Die Gruppenhistorie bleibt erhalten. Grün markiert weitergekommene Teams, Rot ausgeschiedene.</p>'));
  const mini=el('div','mini');
  DATA.groups.forEach(g=>{const c=el('div','mg');
    let h=`<div class="h"><b>Gruppe ${g.group}</b><span>${g.played}/${g.total}</span></div>`;
    g.rows.forEach((r,i)=>{h+=`<div class="mrow ${i===1?'cut':''} ${SMETA[r.status]}"><span class="dot"></span><span class="fl">${r.flag}</span><span class="nm">${esc(r.de)}</span><span class="pt">${r.pts}</span></div>`;});
    c.innerHTML=h;mini.appendChild(c);});
  w.appendChild(mini);}

/* groups */
function renderGroups(){const w=$('#sec-groups');w.innerHTML='';
  w.appendChild(el('div','sec-head','<h2>Die Gruppen</h2><p>Tabellenstand und alle Spiele. Die grüne Linie ist der Schnitt ins Sechzehntelfinale (Top 2).</p>'));
  const grid=el('div','grid');
  DATA.groups.forEach(g=>{const card=el('div','gcard');let rows='';
    g.rows.forEach((r,i)=>{rows+=`<tr class="${SMETA[r.status]} ${i===1?'cut':''}"><td class="l"><span class="pos">${r.pos}</span><span class="fl">${r.flag}</span><span class="nm">${esc(r.de)}</span></td>`+
      `<td>${r.played}</td><td class="gd">${r.gf}:${r.ga}</td><td class="gd">${r.gd>0?'+':''}${r.gd}</td><td class="pts">${r.pts}</td></tr>`;});
    let games='';
    g.games.forEach(gm=>{const sc=gm.played?`<span class="sc">${gm.score[0]}:${gm.score[1]}</span>`:`<span class="sc soon">–:–</span>`;
      games+=`<div class="gm"><span class="ht">${esc(gm.home_de)} ${gm.home_flag}</span>${sc}<span class="at">${gm.away_flag} ${esc(gm.away_de)}</span></div>`;});
    card.innerHTML=`<div class="gh"><b>Gruppe ${g.group}</b><span class="pr">${g.played}/${g.total} gespielt</span></div>`+
      `<table><thead><tr><th class="l">Team</th><th>Sp</th><th>Tore</th><th>Diff</th><th>Pkt</th></tr></thead><tbody>${rows}</tbody></table>`+
      `<div class="games"><div class="gt">Spiele</div>${games}</div>`;
    grid.appendChild(card);});
  w.appendChild(grid);}

/* ---- bracket / what-if ---- */
const RNAME={r32:'16tel',round_of_16:'Achtel',quarter:'Viertel',semi:'Halbf.',final:'Finale'};
const RORDER=['r32','round_of_16','quarter','semi','final'];
const TM=DATA.bracket.team_meta;
function TEAM(n){const m=TM[n]||{de:n,flag:'🏳️',group:''};return {team:n,de:m.de,flag:m.flag,group:m.group};}
let M={},CHILD={},ORD={},PICKS={},SLOTS={},stepRound='r32';
function lp(k){try{return JSON.parse(localStorage.getItem(k)||'{}');}catch(e){return {};}}
function saveState(){try{localStorage.setItem('wm26_picks',JSON.stringify(PICKS));localStorage.setItem('wm26_slots',JSON.stringify(SLOTS));}catch(e){}}
/* einmalige Migration: alten Tipp-Zustand frueherer Versionen verwerfen, sonst erscheint ein
   "vorausgefuellter" Champion / angenommene Sieger aus altem localStorage. Version nur bumpen,
   wenn ein Wipe gewollt ist; sonst bleiben die lokalen Tipps erhalten. */
const STATE_VER='2026-06-30-radial';
function migrateState(){try{if(localStorage.getItem('wm26_ver')!==STATE_VER){localStorage.removeItem('wm26_picks');localStorage.removeItem('wm26_slots');localStorage.setItem('wm26_ver',STATE_VER);}}catch(e){}}
function buildMatches(){M={};CHILD={};
  DATA.bracket.r32.forEach(x=>{M[x.n]={n:x.n,round:'r32',home:x.home,away:x.away};});
  DATA.bracket.r32.forEach(x=>{Object.assign(M[x.n],{played:x.played,score:x.score,actual_winner:x.actual_winner});});
  DATA.bracket.ko.forEach(x=>{M[x.n]={n:x.n,round:x.round,hf:x.home_from,af:x.away_from,played:x.played,score:x.score,actual_winner:x.actual_winner};CHILD[x.home_from]=x.n;CHILD[x.away_from]=x.n;});
  let i={v:0};ORD={};const dfs=n=>{const m=M[n];if(!m)return;if(m.round==='r32'){ORD[n]=i.v++;return;}dfs(m.hf);dfs(m.af);ORD[n]=(ORD[m.hf]+ORD[m.af])/2;};dfs(104);}
// R32-Team: User-Auswahl (Lang-Druck) > gesperrtes echtes Team > Vorbelegung nach aktuellem Stand
function slotTeamName(n,side){const slot=side==='home'?M[n].home:M[n].away;if(!slot)return null;
  if(slot.locked&&slot.team)return slot.team;return SLOTS[n+'-'+side]||slot.team||null;}
function participant(n,side){const m=M[n];if(!m)return null;
  if(m.round==='r32'){const nm=slotTeamName(n,side);return nm?TEAM(nm):null;}
  return winnerOf(side==='home'?m.hf:m.af);}
// Sieger NUR aus explizitem Tipp -- kein Auto-Default (kein ungewollter "Weltmeister")
function winnerSide(n){const m=M[n];if(!m)return null;return m.actual_winner||PICKS[n]||null;}
function winnerOf(n){const s=winnerSide(n);return s?participant(n,s):null;}
function isFixed(n){return !!(M[n]&&M[n].actual_winner);}
function clearDownstream(n){let c=CHILD[n];while(c){delete PICKS[c];c=CHILD[c];}}
function advance(n,side){if(isFixed(n)||!participant(n,side))return;if(PICKS[n]===side)delete PICKS[n];else PICKS[n]=side;clearDownstream(n);saveState();renderBracket();}
function setSlot(n,side,name){SLOTS[n+'-'+side]=name;delete PICKS[n];clearDownstream(n);saveState();closePicker();renderBracket();}
function resetAll(){PICKS={};SLOTS={};saveState();renderBracket();}
function champPath(){const set=new Set();let n=104;while(n){const s=winnerSide(n);if(!s)break;set.add(n);const m=M[n];if(m.round==='r32')break;n=s==='home'?m.hf:m.af;}return set;}
function posLabel(slot){if(!slot)return '';if(slot.kind==='group')return slot.pos+'·'+slot.group;if(slot.kind==='third')return '3.';return '';}
// Lang-Druck-Helfer (Pointer Events): kurz = Sieger, lang/Rechtsklick = Team austauschen
function press(node,onShort,onLong){let t=null,long=false,moved=false,sx=0,sy=0;
  node.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'&&e.button!==0)return;long=false;moved=false;sx=e.clientX;sy=e.clientY;t=setTimeout(()=>{long=true;onLong();},480);});
  node.addEventListener('pointermove',e=>{if(t&&(Math.abs(e.clientX-sx)>10||Math.abs(e.clientY-sy)>10)){moved=true;clearTimeout(t);t=null;}});
  node.addEventListener('pointerup',()=>{if(t){clearTimeout(t);t=null;}if(!long&&!moved)onShort();});
  node.addEventListener('pointercancel',()=>{if(t){clearTimeout(t);t=null;}});
  node.addEventListener('contextmenu',e=>{e.preventDefault();if(t){clearTimeout(t);t=null;}if(!long){long=true;onLong();}});}
function slotRow(n,side){const m=M[n],t=participant(n,side),row=el('div','slot');
  if(t){const fixed=isFixed(n),ws=winnerSide(n);row.classList.add('team');if(fixed)row.classList.add('locked');if(ws===side)row.classList.add('win');else if(ws)row.classList.add('lose');
    const slot=m.round==='r32'?(side==='home'?m.home:m.away):null;const pl=slot?posLabel(slot):'';const editable=slot&&!slot.locked;
    const score=m.score?`<span class="scmini">${side==='home'?m.score[0]:m.score[1]}</span>`:'';
    row.innerHTML=`<span class="fl">${t.flag}</span><span class="nm">${esc(t.de)}</span>${score}`+(pl?`<span class="pl${editable?' prov':''}">${pl}</span>`:'')+(editable&&!fixed?'<span class="ed" title="Lang drücken: Team ändern">⋯</span>':'');
    if(!fixed&&editable)press(row,()=>advance(n,side),()=>openPicker(n,side));else if(!fixed)row.onclick=()=>advance(n,side);
    return row;}
  row.classList.add('tbd');row.innerHTML=`<span class="nm">Sieger Sp. ${side==='home'?m.hf:m.af}</span>`;return row;}
function matchCard(n,path){const c=el('div','bm'+(path.has(n)?' path':''));c.appendChild(slotRow(n,'home'));c.appendChild(slotRow(n,'away'));return c;}
// Team-Auswahl-Overlay (Lang-Druck)
function closePicker(){const o=$('#picker');if(o)o.remove();}
function openPicker(n,side){closePicker();const slot=side==='home'?M[n].home:M[n].away;if(!slot||slot.locked)return;
  const cur=slotTeamName(n,side);
  const ov=el('div','pickwrap');ov.id='picker';ov.onclick=e=>{if(e.target===ov)closePicker();};
  const card=el('div','pickcard');card.innerHTML=`<div class="pickh">${esc(slot.label)} — Team wählen</div>`;
  (slot.candidates||[]).forEach(c=>{const tm=TEAM(c);const b=el('button','pickopt'+(c===cur?' cur':''),`<span class="fl">${tm.flag}</span><span class="nm">${esc(tm.de)}</span>`);b.onclick=()=>setSlot(n,side,c);card.appendChild(b);});
  ov.appendChild(card);document.body.appendChild(ov);}
/* radialer K.o.-Baum: zweite Ansicht ueber demselben State (winnerOf/advance/PICKS) */
function renderRadial(){
  const ANG={},SANG={};
  const lay=(n,a0,a1)=>{const m=M[n];if(!m)return;ANG[n]=(a0+a1)/2;const mid=(a0+a1)/2;
    if(m.round==='r32'){SANG[n+'-home']=(a0+mid)/2;SANG[n+'-away']=(mid+a1)/2;return;}
    lay(m.hf,a0,mid);lay(m.af,mid,a1);};
  lay(104,-Math.PI/2,-Math.PI/2+2*Math.PI);
  const CX=300,CY=312,RR=[0,52,100,146,196,250],RING={final:0,semi:1,quarter:2,round_of_16:3,r32:4},
    NR=[28,12,12,13,14,16],FS=[26,13,13,14,15,18];
  const P=(ring,a)=>[CX+RR[ring]*Math.cos(a),CY+RR[ring]*Math.sin(a)];
  const ed=(cx,cy,px,py,ca,cr,pr,act)=>{const rm=(RR[cr]+RR[pr])/2,qx=CX+rm*Math.cos(ca),qy=CY+rm*Math.sin(ca);
    return `<path d="M${cx.toFixed(1)},${cy.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${px.toFixed(1)},${py.toFixed(1)}" fill="none" stroke="${act?'var(--acc-d)':'var(--line)'}" stroke-width="${act?2.2:1}" stroke-linecap="round"/>`;};
  const dot=(x,y)=>`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="var(--faint)" opacity=".55"/>`;
  const teamN=(x,y,r,fs,t,dim,click)=>`<g class="rn-node${dim?' rn-dim':''}"${click?` onclick="${click}"`:''}><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="var(--card)" stroke="var(--line)" stroke-width="1"/><text class="rn-fl" x="${x.toFixed(1)}" y="${y.toFixed(1)}" font-size="${fs}">${t.flag}</text></g>`;
  let edges='',nodes='';
  const elim=new Set();Object.values(M).forEach(mm=>{const ws=winnerSide(mm.n);if(ws){const lo=participant(mm.n,ws==='home'?'away':'home');if(lo&&lo.team)elim.add(lo.team);}});
  Object.values(M).forEach(m=>{const pr=RING[m.round],pp=pr===0?[CX,CY]:P(pr,ANG[m.n]);
    if(m.round==='r32'){['home','away'].forEach(side=>{const sa=SANG[m.n+'-'+side],sp=P(5,sa);edges+=ed(sp[0],sp[1],pp[0],pp[1],sa,5,pr,winnerSide(m.n)===side);});}
    else{[['home',m.hf],['away',m.af]].forEach(([side,cn])=>{if(!M[cn])return;const cr=RING[M[cn].round],cp=P(cr,ANG[cn]);edges+=ed(cp[0],cp[1],pp[0],pp[1],ANG[cn],cr,pr,!!winnerSide(m.n));});}});
  Object.values(M).filter(m=>m.round==='r32').forEach(m=>{['home','away'].forEach(side=>{
    const t=participant(m.n,side),sp=P(5,SANG[m.n+'-'+side]);
    nodes+=t?teamN(sp[0],sp[1],NR[5],FS[5],t,elim.has(t.team),isFixed(m.n)?'':`advance(${m.n},'${side}')`):dot(sp[0],sp[1]);});});
  Object.values(M).forEach(m=>{if(m.round==='final')return;
    const ring=RING[m.round],p=P(ring,ANG[m.n]),wn=winnerOf(m.n),par=CHILD[m.n];let click='';
    if(par){const side=M[par].hf===m.n?'home':'away';click=`advance(${par},'${side}')`;}
    nodes+=wn?teamN(p[0],p[1],NR[ring],FS[ring],wn,elim.has(wn.team),click):dot(p[0],p[1]);});
  const champ=winnerOf(104);
  const center=champ?`<circle cx="${CX}" cy="${CY}" r="28" fill="var(--gold-soft)" stroke="var(--acc-d)" stroke-width="2.5"/><text class="rn-fl" x="${CX}" y="${CY}" font-size="26">${champ.flag}</text>`
    :`<circle cx="${CX}" cy="${CY}" r="22" fill="var(--card)" stroke="var(--gold)" stroke-width="1.6"/><text class="rn-fl" x="${CX}" y="${CY-1}" font-size="20" fill="var(--gold)">&#9733;</text>`;
  const box=el('div','radialbox');
  box.innerHTML=`<svg viewBox="0 0 600 624" class="radialsvg" role="img" aria-label="Radialer K.-o.-Baum: tippe ein Team, um es eine Runde weiterzubringen"><g>${edges}</g><g>${nodes}</g><g>${center}</g></svg>`;
  return box;}
function renderBracket(){const w=$('#sec-bracket');w.innerHTML='';
  w.appendChild(el('div','sec-head','<h2>__SITE_HEADLINE__</h2><p>Gespielte K.-o.-Partien sind fix; offene Partien kannst du weiter frei durchspielen.</p>'));
  const champ=winnerOf(104), mine=Object.keys(PICKS).length>0||Object.keys(SLOTS).length>0;
  if(champ){const cb=el('div','champ done');cb.innerHTML=`<div class="trophy">🏆</div><div><div class="lab">${isFixed(104)?'Weltmeister 2026':'Dein Weltmeister'}</div><div class="who"><span class="fl">${champ.flag}</span>${esc(champ.de)}</div></div>`;w.appendChild(cb);}
  w.appendChild(renderRadial());
  w.appendChild(el('div','rn-cap','Tippe im Kreis von außen nach innen — oder unten Runde für Runde. Im Raster tauscht langes Drücken ein Team.'));
  if(mine){const ctr=el('div','ctrls');const b2=el('button','btn','↺ Zurücksetzen');b2.onclick=resetAll;ctr.appendChild(b2);w.appendChild(ctr);}
  const path=champPath();
  const ROUNDS=[['r32','16tel'],['round_of_16','Achtel'],['quarter','Viertel'],['semi','Halbf.'],['final','Finale']];
  const rail=el('div','rail');
  ROUNDS.forEach(([r,lab])=>{
    const all=Object.values(M).filter(m=>m.round===r),dn=all.filter(m=>winnerSide(m.n)).length,full=all.length>0&&dn===all.length;
    const node=el('div','rnode'+(stepRound===r?' on':'')+(full?' done':''));
    node.innerHTML=`<div class="rn">${lab}</div><div class="rc">${dn}/${all.length}</div>`;
    node.onclick=()=>{stepRound=r;renderBracket();};
    rail.appendChild(node);rail.appendChild(el('div','rlink'+(full?' done':'')));
  });
  const cup=el('div','rnode cup'+(champ?' done':''));
  cup.innerHTML=champ?`<div class="cupf">${champ.flag}</div>`:`<div class="cupf">🏆</div>`;
  cup.onclick=()=>{stepRound='final';renderBracket();};rail.appendChild(cup);
  w.appendChild(rail);
  const LAB={r32:'Sechzehntelfinale',round_of_16:'Achtelfinale',quarter:'Viertelfinale',semi:'Halbfinale',final:'Finale'};
  const ms=Object.values(M).filter(m=>m.round===stepRound).sort((a,b)=>ORD[a.n]-ORD[b.n]);
  const dn=ms.filter(m=>winnerSide(m.n)).length;
  w.appendChild(el('div','rtitle',`${LAB[stepRound]} <span>· ${dn}/${ms.length} fest oder getippt</span>`));
  const grid=el('div','rgrid'+(ms.length===1?' one':ms.length===2?' two':''));
  ms.forEach(m=>grid.appendChild(matchCard(m.n,path)));
  w.appendChild(grid);
  w.appendChild(el('div','note','Gespielte Partien sind am Score fixiert und nicht änderbar. Offene Partien bleiben lokale Browser-Tipps; der Weltmeister erscheint, sobald das Finale feststeht oder getippt ist.'));}

/* schedule */
let fltGroup='all';
function fxRow(x){const dp=dparts(x.kickoff),fx=el('div','fx'+(x.played?' done':''));
  const mid=x.played?`<span class="res">${x.score[0]}:${x.score[1]}</span>`:`<span class="clk">${dp?dp.hh+':'+dp.mm:''}</span>`;
  fx.innerHTML=`<div class="gp">${x.label||''}</div><div class="hm"><span class="nm">${esc(x.home_de)}</span><span class="fl">${x.home_flag}</span></div>`+
    `<div class="mid">${mid}</div><div class="aw"><span class="fl">${x.away_flag}</span><span class="nm">${esc(x.away_de)}</span></div>`;
  return fx;}
function renderDays(w,items,desc){const days={},order=[];
  items.forEach(x=>{const d=dparts(x.kickoff),k=d?d.key:'zzzz';if(!days[k]){days[k]=[];order.push(k);}days[k].push(x);});
  order.sort();if(desc)order.reverse();
  order.forEach(k=>{const d=dparts(days[k][0].kickoff),dd=el('div','day');
    dd.appendChild(el('div','dh',d?`${d.wd}, ${d.day}. ${d.mon}`:'offen'));
    days[k].forEach(x=>dd.appendChild(fxRow(x)));w.appendChild(dd);});}
function renderSchedule(){const w=$('#sec-schedule');w.innerHTML='';
  w.appendChild(el('div','sec-head','<h2>Spielplan</h2><p>Die nächsten Anstöße zuerst, die gelaufenen Spiele im Block darunter. Zeiten in MESZ (deutsche Ortszeit).</p>'));
  const ctrl=el('div','sctrl'),sel=el('select','gsel');
  sel.innerHTML='<option value="all">Alle Gruppen</option>'+'ABCDEFGHIJKL'.split('').map(g=>`<option value="${g}">Gruppe ${g}</option>`).join('');
  sel.value=fltGroup;sel.onchange=()=>{fltGroup=sel.value;renderSchedule();};ctrl.appendChild(sel);w.appendChild(ctrl);
  let items=DATA.timeline.slice();if(fltGroup!=='all')items=items.filter(x=>x.group===fltGroup);
  const up=items.filter(x=>!x.played),done=items.filter(x=>x.played);
  if(up.length){w.appendChild(el('div','rtitle','Kommende Spiele'));renderDays(w,up,false);}
  else w.appendChild(el('div','note','Keine kommenden Spiele'+(fltGroup!=='all'?' in dieser Gruppe':'')+' mehr.'));
  if(done.length){const h=el('div','rtitle',`Bereits gelaufene Spiele <span>· ${done.length}</span>`);h.style.marginTop='26px';w.appendChild(h);renderDays(w,done,true);}}

/* init */
buildNav();hero();buildMatches();migrateState();SLOTS=lp('wm26_slots');PICKS=lp('wm26_picks');
renderOverview();renderGroups();renderBracket();renderSchedule();show('overview');
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
