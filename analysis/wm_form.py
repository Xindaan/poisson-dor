#!/usr/bin/env python3
"""WM-Form-Diagnose: In-Turnier Ueber-/Unter-Performance je Team gegen die
(gegner-adjustierte) Modell-xG-Erwartung, shrinkage-reguliert.

KEINE absolute Teamstaerke -- die geht aus der Gruppenphase nicht: 12 isolierte
Gruppen (0 gruppenuebergreifende Spiele) + ~1 Spiel/Team. Dies ist der RESIDUUM-
Blick: 'wer hat relativ zur Erwartung ueber-/unterperformt'. Weil die Modell-xG je
Spiel den Gegner schon einpreist, ist das Residuum (Tore - xG) global vergleichbar,
auch wenn die absolute Skala es nicht ist.

Shrinkage: shrunk = (raw pro Spiel) * n/(n+K). Bei n=1 zieht es stark auf 0 (=Erwartung).
Markt-Quoten fassen dieses Signal bereits -> Diagnose, KEIN Modell-Term (sonst Backtest-
Pflicht gegen die 405 Spiele, stehende Regel). Read-only.

Usage: python3 analysis/wm_form.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from wm_tipps.paths import DATA_DIR  # noqa: E402

K_SHRINK = 3.0  # Pseudo-Spiele. n=1 -> Gewicht 0.25, n=2 -> 0.40, n=3 -> 0.50


def main() -> int:
    preds_path = DATA_DIR / "predictions.json"
    if not preds_path.exists():
        raise SystemExit(
            "predictions.json fehlt. Erst die Pipeline laufen lassen:\n"
            "  PYTHONPATH=src python3 -m wm_tipps.cli build-predictions"
        )
    preds = {p["fixture"]["match_id"]: p for p in json.loads(preds_path.read_text())["predictions"]}
    res = json.loads((DATA_DIR / "manual_results.json").read_text())
    res = res.get("results", res) if isinstance(res, dict) else res
    fixtures = json.loads((DATA_DIR / "fixtures.json").read_text())
    fixtures = fixtures.get("fixtures", fixtures) if isinstance(fixtures, dict) else fixtures
    group = {}
    for f in fixtures:
        group[f["home_team"]] = f.get("group")
        group[f["away_team"]] = f.get("group")

    # Akkumulate je Team: n, Tore (GF/GA), erwartete Tore (xGF/xGA)
    agg = defaultdict(lambda: {"n": 0, "GF": 0.0, "GA": 0.0, "xGF": 0.0, "xGA": 0.0})
    for mid, r in res.items():
        p = preds.get(mid)
        if not p:
            continue
        xg = p.get("xg") or {}
        if xg.get("home") is None or xg.get("away") is None:
            continue
        f = p["fixture"]
        h, a = f["home_team"], f["away_team"]
        ah, aa = int(r["actual"][0]), int(r["actual"][1])
        for team, gf, ga, xgf, xga in (
            (h, ah, aa, xg["home"], xg["away"]),
            (a, aa, ah, xg["away"], xg["home"]),
        ):
            d = agg[team]
            d["n"] += 1
            d["GF"] += gf; d["GA"] += ga; d["xGF"] += xgf; d["xGA"] += xga

    rows = []
    for team, d in agg.items():
        n = d["n"]
        att_pg = (d["GF"] - d["xGF"]) / n   # >0 = mehr Tore als erwartet
        def_pg = (d["GA"] - d["xGA"]) / n   # >0 = mehr Gegentore als erwartet (schlecht)
        net_pg = att_pg - def_pg
        shrunk = net_pg * n / (n + K_SHRINK)
        rows.append((shrunk, net_pg, att_pg, -def_pg, team, group.get(team), n,
                     d["GF"], d["xGF"], d["GA"], d["xGA"]))
    rows.sort(reverse=True)

    print("WM-Form (Residuum vs. Modell-xG, shrinkage-reguliert) -- NICHT absolute Staerke.")
    print(f"Shrinkage K={K_SHRINK} (n=1 -> Gewicht {1/(1+K_SHRINK):.2f}). {len(rows)} Teams, je ~1-2 Spiele.\n")
    print(f"{'#':>2} {'Team':<16}{'Grp':<4}{'n':>2}  {'Tore':>4}/{'xGF':>4}  {'Geg':>3}/{'xGA':>4}  {'net/Sp':>7} {'shrunk':>7}")
    for i, (sh, net, att, dfn, team, grp, n, gf, xgf, ga, xga) in enumerate(rows, 1):
        print(f"{i:>2} {team[:15]:<16}{str(grp):<4}{n:>2}  {gf:>4.0f}/{xgf:>4.1f}  {ga:>3.0f}/{xga:>4.1f}  {net:>+7.2f} {sh:>+7.2f}")
    print("\nLesart: shrunk>0 = hat (gegner-adjustiert) ueber Erwartung performt; <0 darunter.")
    print("Caveat: ~1 Spiel/Team = sehr duenn; 0 gruppenuebergreifende Spiele -> kein absoluter")
    print("Quervergleich. Frische Markt-Quoten fassen dieses Form-Signal bereits (-> nur Diagnose).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
