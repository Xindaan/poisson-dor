"""WM-2026 Spieler-Impact-Board -- coole, ehrliche Bewertungen aus FREIEN Daten.

Datenlage (2026-06-25): FBref hat fuer die WM nur ZAEHLSTATISTIK (kein xG/PSxG,
StatsBomb-Partnerschaft beendet -> Memory reference_fbref_dropped_free_advanced_stats).
Also bauen wir Bewertungen, die mit Zaehldaten ehrlich sind:

  1) FINISHER  -- Tor-Beteiligung (G+A) pro 90, aber Empirical-Bayes-SHRINKAGE
     gegen die Sample-Groesse (Minuten). Die geschrumpfte "Talent"-Rate ist
     belastbar; die LUECKE zur rohen Rate = Hot-Streak/Regressions-Signal.
  2) CLUB-OVERLAY -- Understat-Club-xGA90 (2025-26) der Top-5-Liga-Stars,
     direkt vergleichbar mit der WM-Talent-Rate (beide = (G+A bzw xG+xA)/90):
       gedeckt  = WM ~ Club  (echte Qualitaet)
       heiss    = WM >> Club (Hot Streak -> Regression wahrscheinlich)
       kalt     = WM << Club (Elite unter Wert -> Aufwaerts-Potenzial, z.B. Kane)
  3) CREATOR   -- Vorlagen (Olise/Isak: Wert kommt aus dem Auflegen).
  4) KEEPER    -- Goals-Prevented-Proxy (keeper_shotstopping.py): wer sein Team
     WIRKLICH gerettet hat (schussvolumen-bereinigt, nicht nur Zu-Null).
  5) TEAM-ATTACKE -- streikende Angriffe (0 Spielertore) -> Predictions-Watch.

Stdlib-only, read-only. Quellen: FBref WM-Standard + Understat (Browser 2026-06-25).
Lauf:  python3 analysis/wm_player_ratings.py            # Report
       python3 analysis/wm_player_ratings.py --html     # -> analysis/wm_player_board.html
       python3 analysis/wm_player_ratings.py --watch    # -> exports/player_watch.md
       python3 analysis/wm_player_ratings.py --json
"""
import json
import sys
from pathlib import Path

from keeper_shotstopping import KEEPERS  # selbes Verzeichnis

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
from wm_tipps.scoring import DEFAULT_ROUND_ID  # noqa: E402

DATA = ROOT / "data"
EXPORTS = ROOT / "exports"
# Stand der EINGEBETTETEN Zaehldaten (Browser-Capture). Bewusst getrennt vom
# Spielstand aus fixtures.json: der Turnierfortschritt laeuft weiter, die
# hier hinterlegten FBref-/Understat-Zahlen nicht. Beides zusammen anzeigen,
# sonst behauptet der Kopf eine Aktualitaet, die die Daten nicht haben.
DATEN_STAND = "2026-06-25"
BOARD_HTML = HERE / "wm_player_board.html"

# --- FBref WM-Standard, Top-40 Tor-Beteiligte (Browser-Capture 2026-06-25) ----
# (player, team, pos, minutes, G, A)
TOP = [
    ("Lionel Messi", "Argentina", "FW", 169, 5, 0),
    ("Erling Haaland", "Norway", "FW", 180, 4, 0),
    ("Kylian Mbappe", "France", "FW", 179, 4, 0),
    ("Alexander Isak", "Sweden", "FW", 179, 1, 3),
    ("Jonathan David", "Canada", "FW", 150, 3, 0),
    ("Maxi Araujo", "Uruguay", "MF,FW", 160, 2, 1),
    ("Cody Gakpo", "Netherlands", "FW", 173, 2, 1),
    ("Vinicius Junior", "Brazil", "FW", 170, 2, 1),
    ("Mikel Oyarzabal", "Spain", "FW", 135, 2, 1),
    ("Crysencio Summerville", "Netherlands", "FW", 114, 2, 1),
    ("Ayase Ueda", "Japan", "FW", 166, 2, 1),
    ("Mohamed Salah", "Egypt", "MF,FW", 159, 1, 2),
    ("Michael Olise", "France", "MF", 157, 0, 3),
    ("Yasin Ayari", "Sweden", "MF", 168, 2, 0),
    ("Folarin Balogun", "United States", "FW", 160, 2, 0),
    ("Matheus Cunha", "Brazil", "FW", 93, 2, 0),
    ("Kai Havertz", "Germany", "FW", 174, 2, 0),
    ("Elijah Just", "New Zealand", "MF", 174, 2, 0),
    ("Daichi Kamada", "Japan", "MF", 162, 2, 0),
    ("Harry Kane", "England", "FW", 180, 2, 0),
    ("Cyle Larin", "Canada", "FW", 105, 2, 0),
    ("Daniel Munoz", "Colombia", "DF", 180, 2, 0),
    ("Cristiano Ronaldo", "Portugal", "FW", 180, 2, 0),
    ("Ismael Saibari", "Morocco", "FW", 171, 2, 0),
    ("Ismaila Sarr", "Senegal", "MF", 164, 2, 0),
    ("Nathaniel Brown", "Germany", "DF", 162, 1, 1),
    ("Ousmane Dembele", "France", "MF", 146, 1, 1),
    ("Luis Diaz", "Colombia", "FW", 179, 1, 1),
    ("Breel Embolo", "Switzerland", "FW", 178, 1, 1),
    ("Alex Freeman", "United States", "DF", 180, 1, 1),
    ("Viktor Gyokeres", "Sweden", "FW", 180, 1, 1),
    ("Hwang In-beom", "Korea Republic", "MF", 173, 1, 1),
    ("Keito Nakamura", "Japan", "MF", 168, 1, 1),
    ("Felix Nmecha", "Germany", "MF", 162, 1, 1),
    ("Ramin Rezaeian", "IR Iran", "MF,DF", 180, 1, 1),
    ("Ruben Vargas", "Switzerland", "MF", 98, 1, 1),
    ("Mostafa Ziko", "Egypt", "MF", 150, 1, 1),
    ("Brahim Diaz", "Morocco", "MF", 147, 0, 2),
    ("Denzel Dumfries", "Netherlands", "DF", 180, 0, 2),
    ("Julio Enciso", "Paraguay", "FW", 179, 0, 2),
]

# Team-Tor-Beteiligung (G, A) -- FBref WM-Standard Aggregat (Browser 2026-06-25).
TEAM_GA = {
    "Germany": (9, 8), "Netherlands": (7, 7), "France": (6, 5), "Canada": (6, 2),
    "Norway": (6, 4), "Sweden": (6, 5), "Japan": (6, 6), "Argentina": (5, 3),
    "Portugal": (5, 3), "Switzerland": (5, 2), "Brazil": (4, 3), "Colombia": (4, 4),
    "Egypt": (4, 4), "England": (4, 3), "United States": (4, 3), "Mexico": (3, 2),
    "Spain": (3, 3), "Senegal": (3, 3), "New Zealand": (3, 3), "Croatia": (3, 3),
    "Uruguay": (3, 1), "Algeria": (2, 1), "Australia": (2, 1), "Austria": (2, 1),
    "Bosnia & Herz.": (2, 1), "Cote d'Ivoire": (2, 1), "Czechia": (2, 2),
    "IR Iran": (2, 1), "Jordan": (2, 2), "Korea Republic": (2, 2), "Morocco": (2, 2),
    "Paraguay": (2, 2), "Cabo Verde": (2, 0), "Congo DR": (1, 1), "Curacao": (1, 0),
    "Ghana": (1, 0), "Iraq": (1, 1), "Qatar": (1, 1), "Saudi Arabia": (1, 0),
    "Scotland": (1, 0), "South Africa": (1, 0), "Tunisia": (1, 1), "Uzbekistan": (1, 0),
    "Belgium": (0, 0), "Ecuador": (0, 0), "Haiti": (0, 0), "Panama": (0, 0),
    "Turkiye": (0, 0),
}
# Streik-Teams (0 Spielertore) -> fixtures.json-Namen.
MISFIRE_FIX = {"Belgium", "Ecuador", "Haiti", "Panama", "Turkey"}

# Understat Club (xg90, xga90), 2025-26 Top-5-Liga (Browser-Capture 2026-06-25).
# xga90 = (xG+xA)/90, direkt vergleichbar mit der WM-Talent-Rate (G+A/90).
CLUB = {
    "Erling Haaland": (0.87, 1.04), "Kylian Mbappe": (0.89, 1.13),
    "Vinicius Junior": (0.45, 0.68), "Mikel Oyarzabal": (0.53, 0.73),
    "Kai Havertz": (0.76, 0.98), "Viktor Gyokeres": (0.55, 0.66),
    "Alexander Isak": (0.41, 0.51), "Mohamed Salah": (0.37, 0.64),
    "Cody Gakpo": (0.32, 0.54), "Matheus Cunha": (0.25, 0.39),
    "Crysencio Summerville": (0.20, 0.32), "Harry Kane": (1.12, 1.40),
    "Luis Diaz": (0.54, 0.91), "Michael Olise": (0.45, 1.11),
    "Felix Nmecha": (0.14, 0.21), "Denzel Dumfries": (0.25, 0.34),
    "Ousmane Dembele": (0.57, 1.01), "Folarin Balogun": (0.56, 0.72),
    "Breel Embolo": (0.43, 0.51),
}

PRIOR_RATE, PRIOR_N90 = 0.45, 2.0
ALPHA0 = PRIOR_RATE * PRIOR_N90


def shrink(ga, n90):
    return (ALPHA0 + ga) / (PRIOR_N90 + n90)


def club_tag(talent90, club):
    if not club:
        return None, None
    base = club[1] or club[0]
    if not base:
        return None, None
    ratio = talent90 / base
    tag = "heiss" if ratio >= 1.25 else "kalt" if ratio <= 0.85 else "gedeckt"
    return tag, round(ratio, 2)


def keeper_prevented():
    tot_ga = sum(k[3] for k in KEEPERS)
    tot_sota = sum(k[4] for k in KEEPERS)
    rate = tot_ga / tot_sota
    out = []
    for name, team, n90, ga, sota, saves, sp, cs in KEEPERS:
        if n90 < 1.5:
            continue
        out.append((round(sota * rate - ga, 2), name, team, sota, ga, cs))
    out.sort(reverse=True)
    return out


def build():
    players = []
    for name, team, pos, mins, g, a in TOP:
        n90 = mins / 90.0
        ga = g + a
        sh = shrink(ga, n90)
        club = CLUB.get(name)
        tag, ratio = club_tag(sh, club)
        players.append({
            "name": name, "team": team, "pos": pos, "min": mins, "G": g, "A": a,
            "GA": ga, "raw90": round(ga / n90, 2), "talent90": round(sh, 2),
            "heat": round(ga / n90 - sh, 2),
            "club_xg90": club[0] if club else None,
            "club_xga90": club[1] if club else None,
            "club_tag": tag, "club_ratio": ratio,
        })
    finishers = sorted(players, key=lambda p: (-p["talent90"], -p["GA"]))
    creators = sorted([p for p in players if p["A"] >= 2], key=lambda p: (-p["A"], -p["talent90"]))
    hot = sorted([p for p in players if p["min"] < 170 and p["heat"] >= 0.6], key=lambda p: -p["heat"])
    cold = sorted([p for p in players if p["club_tag"] == "kalt"], key=lambda p: p["club_ratio"])
    keepers = keeper_prevented()
    teams = sorted(TEAM_GA.items(), key=lambda kv: kv[1][0] + kv[1][1])
    misfiring = [(t, g, a) for t, (g, a) in teams if g == 0]
    return {"players": players, "finishers": finishers, "creators": creators,
            "hot": hot, "cold": cold, "keepers": keepers, "teams": teams,
            "misfiring": misfiring}


# ---------------------------------------------------------------- Text-Report
def report(d):
    P = []
    pr = P.append
    pr("=" * 72)
    pr("WM 2026 -- SPIELER-IMPACT-BOARD  (freie Zaehldaten, EB-geschrumpft)")
    pr("=" * 72)
    pr(f"\n[FINISHER] Talent = G+A/90 geschrumpft; vs Club-xGA90 (Understat 25-26)")
    pr(f"   {'Spieler':<22}{'Team':<13}{'Min':>4}{'G+A':>4}{'Talent':>7}{'Club':>6}  Tag")
    for p in d["finishers"][:14]:
        cx = f"{p['club_xga90']:.2f}" if p["club_xga90"] is not None else "  - "
        tg = f"{p['club_tag']} ({p['club_ratio']}x)" if p["club_tag"] else ""
        pr(f"   {p['name']:<22}{p['team']:<13}{p['min']:>4}{p['GA']:>4}{p['talent90']:>7}{cx:>6}  {tg}")
    pr(f"\n[KREATOR] meiste Vorlagen")
    for p in d["creators"][:6]:
        pr(f"   {p['name']:<22}{p['team']:<13}  {p['A']} Vorlagen ({p['G']}G)")
    pr(f"\n[KEEPER] Goals Prevented (schussvolumen-bereinigt, >=1.5 Spiele)")
    for prev, name, team, sota, ga, cs in d["keepers"][:6]:
        pr(f"   {name:<22}{team:<16}{sota:>4} SoT, {ga} GT -> {prev:+.2f} verhindert")
    pr(f"\n[HOT-STREAK -> Regression] WM-Rate ueber Club/Talent, kleine Stichprobe")
    for p in d["hot"][:6]:
        tg = f" [{p['club_tag']} {p['club_ratio']}x Club]" if p["club_tag"] else ""
        pr(f"   {p['name']:<22}{p['team']:<13} {p['min']:>3}Min  roh {p['raw90']} -> Talent {p['talent90']}{tg}")
    pr(f"\n[KALT -> Aufwaerts-Potenzial] Elite unter Club-Niveau am Turnier")
    for p in d["cold"][:6]:
        pr(f"   {p['name']:<22}{p['team']:<13} Talent {p['talent90']} vs Club-xGA90 {p['club_xga90']} ({p['club_ratio']}x)")
    pr(f"\n[TEAM-ATTACKE streikt -> Predictions-Watch] 0 Spielertore:")
    pr("   " + ", ".join(t for t, g, a in d["misfiring"]))
    return "\n".join(P)


# ---------------------------------------------------------------- (c) Watch-MD
def _played_count():
    try:
        fx = json.loads((DATA / "fixtures.json").read_text())["fixtures"]
        return sum(1 for f in fx if f.get("status") == "played"), len(fx)
    except Exception:
        return None, None


def build_watch(d):
    preds_path = DATA / "predictions.json"
    if not preds_path.exists():
        raise SystemExit(
            "predictions.json fehlt. Erst die Pipeline laufen lassen:\n"
            "  PYTHONPATH=src python3 -m wm_tipps.cli build-predictions"
        )
    fx = json.loads((DATA / "fixtures.json").read_text())["fixtures"]
    preds = {p.get("match_id"): p for p in json.loads(preds_path.read_text())["predictions"]}
    rows = []
    for f in fx:
        if f.get("status") == "played":
            continue
        h, a = f.get("home_team"), f.get("away_team")
        team = h if h in MISFIRE_FIX else a if a in MISFIRE_FIX else None
        if not team:
            continue
        p = preds.get(f["match_id"], {})
        rt = (p.get("round_tips") or {}).get(DEFAULT_ROUND_ID) or {}
        tip = rt.get("tip", "?")
        xg = p.get("xg") or {}
        is_home = team == h
        gf = xg.get("home" if is_home else "away", 0) or 0
        # tip parse
        try:
            th, ta = (int(x) for x in str(tip).split(":"))
            tgf = th if is_home else ta
            tga = ta if is_home else th
            conflict = tgf >= 1 or tgf > tga
        except Exception:
            conflict = False
        if conflict:
            rows.append((f.get("kickoff_utc", "")[:10], f"{h} vs {a}", tip, team, round(gf, 2)))
    played, total = _played_count()
    L = ["# Spieler-Watch (advisory) -- WM 2026", ""]
    L.append(f"Stand: {played}/{total} Spiele. **Rein advisory, kein Tipp-Override.**")
    L.append(
        f"Quelle: FBref WM-Zaehldaten + Understat-Club-xG, Stand {DATEN_STAND} "
        "(analysis/wm_player_ratings.py). Die Spielerwerte sind ein Snapshot "
        "von diesem Datum und wachsen NICHT mit dem Turnierfortschritt mit."
    )
    L.append("")
    L.append("## Streikender Angriff vs Modell-Optimismus")
    L.append("")
    L.append("Teams mit **0 Spielertoren** in der Gruppenphase, die das Modell im")
    L.append("naechsten Spiel trotzdem treffen/gewinnen laesst -- hier kann das Modell")
    L.append("die Offensive ueberschaetzen (kleine Stichprobe, kein Override):")
    L.append("")
    if rows:
        L.append("| Spiel | Anpfiff | Modell-Tipp | Streik-Team | dessen xG |")
        L.append("|---|---|---|---|---|")
        for kk, match, tip, team, gf in rows:
            L.append(f"| {match} | {kk} | {tip} | {team} | {gf} |")
    else:
        L.append("_Aktuell keine offenen Spiele, in denen ein Streik-Team treffen/gewinnen soll._")
    L.append("")
    L.append("## Hot-Streak -> Regression (advisory)")
    L.append("")
    L.append("WM-Rate deutlich ueber Club-Niveau -> bei Tipps auf ihre Teams nicht auf")
    L.append("Fortsetzung der Serie wetten:")
    L.append("")
    for p in d["hot"][:6]:
        tg = f", {p['club_ratio']}x Club-Niveau" if p["club_tag"] else ""
        L.append(f"- **{p['name']}** ({p['team']}): roh {p['raw90']}/90 -> Talent {p['talent90']}/90{tg}")
    L.append("")
    L.append("## Kalt -> Aufwaerts-Potenzial (advisory)")
    L.append("")
    L.append("Elite unter Club-Niveau am Turnier -> koennte explodieren:")
    L.append("")
    for p in d["cold"][:5]:
        L.append(f"- **{p['name']}** ({p['team']}): Talent {p['talent90']} vs Club-xGA90 {p['club_xga90']} ({p['club_ratio']}x)")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- (b) HTML-Board
def render_html(d):
    """Baut die standalone Seite aus den GETEILTEN Assets.

    Die Zeilen-Erzeugung liegt seit T-0165 nicht mehr hier, sondern in
    assets/player_board.js -- dieselbe Datei speist den Dashboard-Tab
    "Analyse". CSS und JS werden hier inline eingebettet, damit die Datei
    self-contained bleibt und ohne Server per Doppelklick funktioniert.
    """
    payload = json.dumps(board_payload(d), ensure_ascii=False, default=str)
    assets = ROOT / "assets"
    tokens_css = (assets / "tokens.css").read_text(encoding="utf-8")
    board_css = (assets / "player_board.css").read_text(encoding="utf-8")
    board_js = (assets / "player_board.js").read_text(encoding="utf-8")
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>WM 2026 -- Spieler-Impact-Board</title>
<style>
{tokens_css}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  font-size:16px;line-height:1.5;padding:28px 18px 60px;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}}
.wrap{{max-width:980px;margin:0 auto}}
h1{{font-size:26px;font-weight:800;margin:0 0 4px;letter-spacing:-.03em}}
{board_css}
</style></head><body><div class="wrap">
<h1>WM 2026 &mdash; Spieler-Impact-Board</h1>
<div class="player-board" id="board"></div>
</div>
<script>
{board_js}
mountPlayerBoard({payload}, document.getElementById("board"));
</script>
</body></html>"""


def board_payload(d):
    """Nutzlast fuer beide Ziele: standalone Seite und Dashboard-Tab."""
    played, total = _played_count()
    return {
        "finishers": d["finishers"][:12],
        "keepers": d["keepers"][:6],
        "creators": d["creators"][:5],
        "hot": d["hot"][:5],
        "cold": d["cold"][:5],
        "misfiring": d["misfiring"],
        "played": played,
        "total": total,
        "daten_stand": DATEN_STAND,
    }



if __name__ == "__main__":
    d = build()
    if "--json" in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    elif "--html" in sys.argv:
        BOARD_HTML.write_text(render_html(d))
        print(f"geschrieben: {BOARD_HTML}")
        # Dieselbe Nutzlast als JSON: daraus baut der Dashboard-Tab
        # "Analyse" dasselbe Board (T-0165).
        payload = json.dumps(board_payload(d), ensure_ascii=False,
                             indent=2, default=str)
        (DATA / "player_board.json").write_text(payload, encoding="utf-8")
        print(f"geschrieben: {DATA / 'player_board.json'}")
    elif "--watch" in sys.argv:
        md = build_watch(d)
        (EXPORTS / "player_watch.md").write_text(md)
        print(f"geschrieben: {EXPORTS / 'player_watch.md'}")
        print("\n" + md)
    else:
        print(report(d))
