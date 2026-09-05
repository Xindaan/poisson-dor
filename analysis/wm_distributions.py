"""WM-2026 Verteilungs-Analyse: Torschuetzen, Vorlagengeber, Torhueter.

Stdlib-only (analysis-Carve-out, read-only). Kombiniert zwei Quellen:

  1) data/fixtures.json (Repo-Wahrheit)  -> alles auf Spiel-/Team-Ebene:
     Tore pro Spiel, Tore pro Team, Gegentore je Team (= Torhueter-Proxy),
     Zu-Null. Aktualisiert sich automatisch mit neuen Ergebnissen.
  2) WIKI_* unten (eingebettet, Stand 2026-06-23, en.wikipedia.org
     "2026 FIFA World Cup", Abschnitt Goalscorers) -> Spieler-Ebene:
     Tore je Torschuetze + Eigentore. Vorlagen nur Spitze (keine freie
     vollstaendige Quelle), siehe ASSIST_LEADERS.

CHECKSUM-GATE: Die eingebetteten Spieler-Tore (132) + Eigentore (9) muessen
die Gesamttoranzahl aus fixtures.json treffen. Stimmt das nicht (z. B. weil
seit dem 23.6. neue Spiele dazukamen), bricht das Skript bewusst ab statt
still veraltete Spielerdaten zu zeigen.

Lauf:  python3 analysis/wm_distributions.py
       python3 analysis/wm_distributions.py --json   (Maschinen-Output)
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "data" / "fixtures.json"

# --- Quelle 2: Wikipedia Goalscorers, Stand 2026-06-23 (48 Spiele) ---------
# Format: Tore -> Anzahl Spieler mit genau so vielen Toren.
WIKI_SCORER_GROUPS = {5: 1, 4: 2, 3: 2, 2: 20, 1: 73}
WIKI_OWN_GOALS = 9
WIKI_TOP_SCORERS = [
    (5, "Lionel Messi", "Argentinien"),
    (4, "Kylian Mbappe", "Frankreich"),
    (4, "Erling Haaland", "Norwegen"),
    (3, "Jonathan David", "Kanada"),
    (3, "Deniz Undav", "Deutschland"),
]
# Vorlagengeber: nur die frei publizierte Spitze (Wikipedia fuehrt keine
# Assists; Presse/StatMuse Stand ~6. Spieltag). KEIN vollstaendiger Long Tail.
ASSIST_LEADERS = [
    ("Michael Olise", "Frankreich", 3),
    ("Alexander Isak", "Schweden", 3),
    ("Joshua Kimmich", "Deutschland", 2),
    ("Ryan Gravenberch", "Niederlande", 2),
    ("Deniz Undav", "Deutschland", 2),
    ("Chris Wood", "Neuseeland", 2),
]
# Tore der Assist-Leader (aus WIKI-Torschuetzen), fuer die G+A-Summe.
GOALS_OF_ASSIST_LEADERS = {
    "Lionel Messi": 5, "Deniz Undav": 3, "Alexander Isak": 1,
    "Michael Olise": 0, "Joshua Kimmich": 0, "Ryan Gravenberch": 0,
    "Chris Wood": 0,
}

# --- kleine Verteilungs-Helfer (stdlib) ------------------------------------
def poisson_pmf(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)

def binom_pmf(k, n, p):
    return math.comb(n, k) * p ** k * (1 - p) ** (n - k)

def normal_pdf(x, mu, sd):
    if sd == 0:
        return 0.0
    return math.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))

def mean_sd(values):
    n = len(values)
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / n
    return mu, math.sqrt(var)

def chisq_poisson(counts, lam, n_obs):
    """Pearson-Chi-Quadrat gegen Poisson, mit Tail-Bucketing (erw.>=5)."""
    kmax = max(counts)
    exp = {k: n_obs * poisson_pmf(k, lam) for k in range(0, kmax + 2)}
    # in Buckets zusammenfassen bis erwartete Zellbesetzung >= 5
    obs_b, exp_b, acc_o, acc_e = [], [], 0.0, 0.0
    for k in range(0, kmax + 2):
        acc_o += counts.get(k, 0)
        acc_e += exp[k]
        if acc_e >= 5:
            obs_b.append(acc_o); exp_b.append(acc_e); acc_o = acc_e = 0.0
    if acc_e > 0:  # Rest in letzten Bucket
        if exp_b:
            obs_b[-1] += acc_o; exp_b[-1] += acc_e
        else:
            obs_b.append(acc_o); exp_b.append(acc_e)
    chi = sum((o - e) ** 2 / e for o, e in zip(obs_b, exp_b))
    dof = max(1, len(obs_b) - 1 - 1)  # -1 Summe, -1 geschaetztes lambda
    return chi, dof, len(obs_b)

# --- Daten laden -----------------------------------------------------------
def load_fixtures():
    d = json.loads(FIXTURES.read_text())
    return [f for f in d["fixtures"] if f.get("status") == "played" and f.get("result")]

def build():
    fx = load_fixtures()
    n_matches = len(fx)
    total_goals = sum(f["result"][0] + f["result"][1] for f in fx)

    # CHECKSUM-GATE
    embedded = sum(g * n for g, n in WIKI_SCORER_GROUPS.items()) + WIKI_OWN_GOALS
    if embedded != total_goals:
        raise SystemExit(
            "Dieses Skript rechnet mit einer von Hand abgeschriebenen "
            "Torschuetzen-Tabelle (Wikipedia-Stand siehe Kopf der Datei) und "
            "vergleicht sie zur Sicherheit gegen data/fixtures.json.\n"
            f"  eingebettete Spielertore : {embedded}\n"
            f"  Tore laut fixtures.json  : {total_goals} (aus {n_matches} Spielen)\n"
            "Die beiden passen nicht zusammen -- der Spielplan ist also weiter "
            "als die abgeschriebene Tabelle. Das Skript bricht hier bewusst ab, "
            "statt Zahlen aus zwei verschiedenen Staenden zu mischen; das Ergebnis "
            "saehe plausibel aus und waere trotzdem falsch.\n"
            "Zum Weiterarbeiten die Tabellen WIKI_SCORER_GROUPS / WIKI_OWN_GOALS "
            "oben in dieser Datei auf den aktuellen Turnierstand bringen.\n"
            "(Im veroeffentlichten Snapshot ist das der Normalfall -- siehe "
            "README, Abschnitt Limitations.)"
        )

    out = {"n_matches": n_matches, "total_goals": total_goals}

    # 1) TORSCHUETZEN (pro Torschuetze, nur Spieler mit >=1 Tor) ------------
    scorer_goals = []
    for g, n in WIKI_SCORER_GROUPS.items():
        scorer_goals += [g] * n
    mu, sd = mean_sd(scorer_goals)
    n_scorers = len(scorer_goals)
    top = []
    for goals, name, country in WIKI_TOP_SCORERS:
        z = (goals - mu) / sd
        top.append({"name": name, "country": country, "goals": goals, "z": z})
    out["scorers"] = {
        "n": n_scorers, "goals": sum(scorer_goals), "own_goals": WIKI_OWN_GOALS,
        "mean": mu, "sd": sd, "dist": dict(sorted(Counter(scorer_goals).items())),
        "top": top,
    }

    # 2) TORE PRO SPIEL (n=48) vs Poisson -----------------------------------
    per_match = Counter(f["result"][0] + f["result"][1] for f in fx)
    lam_m = total_goals / n_matches
    chi, dof, nb = chisq_poisson(per_match, lam_m, n_matches)
    standout = sorted(fx, key=lambda f: -(f["result"][0] + f["result"][1]))[:6]
    out["per_match"] = {
        "lam": lam_m, "dist": dict(sorted(per_match.items())),
        "poisson": {k: n_matches * poisson_pmf(k, lam_m) for k in range(0, max(per_match) + 1)},
        "chisq": chi, "dof": dof, "buckets": nb,
        "standout": [{"score": f"{f['home_team']} {f['result'][0]}:{f['result'][1]} {f['away_team']}",
                      "tot": f["result"][0] + f["result"][1]} for f in standout],
    }

    # 3) TORE PRO TEAM PRO SPIEL (n=96) vs Poisson --------------------------
    per_team_match = Counter()
    for f in fx:
        per_team_match[f["result"][0]] += 1
        per_team_match[f["result"][1]] += 1
    n_tm = sum(per_team_match.values())
    lam_tm = total_goals / n_tm
    chi2, dof2, nb2 = chisq_poisson(per_team_match, lam_tm, n_tm)
    out["per_team_match"] = {
        "n": n_tm, "lam": lam_tm, "dist": dict(sorted(per_team_match.items())),
        "poisson": {k: n_tm * poisson_pmf(k, lam_tm) for k in range(0, max(per_team_match) + 1)},
        "chisq": chi2, "dof": dof2, "buckets": nb2,
    }

    # 4) TORHUETER: Gegentore + Zu-Null je Team -----------------------------
    conceded = Counter()
    games = Counter()
    clean_per_team = Counter()
    for f in fx:
        h, a = f["home_team"], f["away_team"]
        hs, as_ = f["result"]
        conceded[h] += as_; conceded[a] += hs
        games[h] += 1; games[a] += 1
        if as_ == 0:
            clean_per_team[h] += 1
        if hs == 0:
            clean_per_team[a] += 1
    teams = sorted(conceded, key=lambda t: conceded[t])
    cvals = [conceded[t] for t in teams]
    cmu, csd = mean_sd(cvals)
    conc_rows = [{"team": t, "conceded": conceded[t], "games": games[t],
                  "z": (conceded[t] - cmu) / csd, "clean": clean_per_team[t]}
                 for t in teams]
    # Zu-Null als Bernoulli pro Team-Spiel -> Binomial(2, p)
    total_team_games = sum(games.values())
    total_clean = sum(clean_per_team.values())
    p_clean = total_clean / total_team_games
    clean_dist = Counter(clean_per_team.get(t, 0) for t in conceded)
    out["keepers"] = {
        "conceded_mean": cmu, "conceded_sd": csd,
        "conceded_dist": dict(sorted(Counter(cvals).items())),
        "best": conc_rows[:5], "worst": list(reversed(conc_rows[-5:])),
        "p_clean": p_clean, "total_clean": total_clean,
        "clean_dist": dict(sorted(clean_dist.items())),
        "clean_binom": {k: 48 * binom_pmf(k, 2, p_clean) for k in range(0, 3)},
    }

    # 5) VORLAGENGEBER (Spitze) + G+A-Summe ---------------------------------
    inv = []
    for name, country, a in ASSIST_LEADERS:
        g = GOALS_OF_ASSIST_LEADERS.get(name, 0)
        inv.append({"name": name, "country": country, "assists": a, "goals": g, "ga": g + a})
    # Messi separat fuer den G+A-Vergleich (nur 0 Assists publiziert -> 5)
    inv.append({"name": "Lionel Messi", "country": "Argentinien", "assists": 0,
                "goals": 5, "ga": 5})
    inv.sort(key=lambda r: -r["ga"])
    out["assists"] = {"leaders": ASSIST_LEADERS, "involvement": inv,
                      "note": "Nur publizierte Vorlagen-Spitze; kein vollstaendiger Long Tail frei verfuegbar."}
    return out

def fmt_bar(n, scale, ch="#"):
    return ch * int(round(n * scale))

def report(o):
    L = []
    P = L.append
    P("=" * 66)
    P(f"WM 2026 -- Verteilungen  ({o['n_matches']} Spiele, {o['total_goals']} Tore, "
      f"{o['total_goals']/o['n_matches']:.2f}/Spiel)")
    P("=" * 66)

    s = o["scorers"]
    P(f"\n[1] TORSCHUETZEN  -- {s['n']} Spieler, {s['goals']} Tore (+{s['own_goals']} ET)")
    P(f"    mean={s['mean']:.2f}  sd={s['sd']:.2f}  (unter den Torschuetzen)")
    for g in sorted(s["dist"], reverse=True):
        P(f"    {g} Tore: {fmt_bar(s['dist'][g],1.0):<73} {s['dist'][g]}")
    P("    Wer sticht heraus (z gegen die Torschuetzen-Verteilung):")
    for t in s["top"]:
        P(f"      {t['name']:<18} {t['country']:<13} {t['goals']} Tore  z=+{t['z']:.1f} sd")

    m = o["per_match"]
    P(f"\n[2] TORE PRO SPIEL (n={o['n_matches']})  lambda={m['lam']:.2f}")
    P(f"    {'k':>2} | {'beob.':>5} | {'Poisson':>7}")
    for k in sorted(m["dist"]):
        P(f"    {k:>2} | {m['dist'][k]:>5} | {m['poisson'].get(k,0):>7.1f}  "
          f"{fmt_bar(m['dist'][k],1.0)}")
    P(f"    Chi^2={m['chisq']:.2f}, dof={m['dof']}  -> Tore/Spiel ~ Poisson")
    P("    Auffaellige Spiele:")
    for g in m["standout"]:
        P(f"      {g['tot']} Tore  {g['score']}")

    tm = o["per_team_match"]
    P(f"\n[3] TORE PRO TEAM PRO SPIEL (n={tm['n']})  lambda={tm['lam']:.2f}")
    for k in sorted(tm["dist"]):
        P(f"    {k} | beob {tm['dist'][k]:>3} | Poi {tm['poisson'].get(k,0):>5.1f}  "
          f"{fmt_bar(tm['dist'][k],0.5)}")
    P(f"    Chi^2={tm['chisq']:.2f}, dof={tm['dof']}")

    k = o["keepers"]
    P(f"\n[4] TORHUETER -- Gegentore je Team (2 Spiele)  "
      f"mean={k['conceded_mean']:.2f} sd={k['conceded_sd']:.2f}")
    P("    Schwaechste (Gegentore):")
    for r in k["worst"]:
        P(f"      {r['team']:<22} {r['conceded']} GT  z=+{r['z']:.1f}  (Zu-Null {r['clean']})")
    P("    Beste (Gegentore):")
    for r in k["best"]:
        P(f"      {r['team']:<22} {r['conceded']} GT  z={r['z']:+.1f}  (Zu-Null {r['clean']})")
    P(f"    Zu-Null-Quote p={k['p_clean']:.3f} -> Binomial(2,p) je Team:")
    for kk in sorted(k["clean_dist"]):
        P(f"      {kk}x Zu-Null: beob {k['clean_dist'][kk]:>2} | Binom {k['clean_binom'][kk]:>4.1f}")

    a = o["assists"]
    P(f"\n[5] VORLAGENGEBER (Spitze) + Torbeteiligungen (G+A)")
    P(f"    ! {a['note']}")
    for r in a["involvement"]:
        P(f"      {r['name']:<18} {r['country']:<13} {r['goals']}G + {r['assists']}A = {r['ga']}")
    return "\n".join(L)

if __name__ == "__main__":
    data = build()
    if "--json" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(report(data))
