#!/usr/bin/env python3
"""Odds-Ingest-Verifikation (T-0105): prueft frisch eingepflegte Quoten auf
Plausibilitaet, BEVOR man ihnen vertraut -- das Reliabilitaets-Gate fuer den
per-Spieltag-Quoten-Workflow (Anspruch: reproduzierbar und verlaesslich).

Checks je Spiel (auf data/predictions.json -- Quoten + Modell zusammen):
- alle 3 Dezimalquoten vorhanden und > 1.0
- Overround (Buchmacher-Marge) in [1.02, 1.15]; Best-Odds-Quellen duerfen
  niedriger liegen, weil sie Buchmacher-Bestpreise statt eine einzelne
  klassische 1X2-Marge abbilden
- Markt-Favorit == Modell-Favorit -- sonst Hinweis: Markt/Modell uneinig ODER
  Fehl-Zuordnung (falsches Spiel) -> manuell pruefen
- Quelle wird mit ausgegeben

Read-only. Exit-Code 1, wenn irgendein Spiel einen Hinweis hat (CI/SOP-tauglich).
Usage:
  python3 analysis/odds_check.py                 # alle ungespielten mit Quote
  python3 analysis/odds_check.py ga-004 gb-010    # gezielt diese match_ids
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from wm_tipps.paths import DATA_DIR  # noqa: E402
from wm_tipps.odds import (  # noqa: E402
    BWIN_SOURCE,
    DEFAULT_MATCH_ODDS_FRESH_HOURS,
    LOW_OVERROUND_OK_SOURCES,
    parse_iso_datetime,
)

OVER_LO, OVER_HI = 1.02, 1.15  # plausible Buchmacher-Marge fuer 1X2


def _require(path):
    """Pipeline-Artefakte sind nicht im Repo -- mit klarer Ansage abbrechen."""
    if not path.exists():
        raise SystemExit(
            f"{path.name} fehlt. Erst die Pipeline laufen lassen:\n"
            f"  PYTHONPATH=src python3 -m wm_tipps.cli build-predictions"
        )
    return path


def _load():
    preds = json.loads(_require(DATA_DIR / "predictions.json").read_text())["predictions"]
    res = json.loads((DATA_DIR / "manual_results.json").read_text())
    res = res.get("results", res) if isinstance(res, dict) else res
    return preds, set(res)


def check(prediction) -> list[str]:
    odds = prediction.get("odds") or {}
    dec = odds.get("decimal_odds") or {}
    h, d, a = dec.get("home"), dec.get("draw"), dec.get("away")
    if not all(isinstance(x, (int, float)) and x > 1.0 for x in (h, d, a)):
        return ["keine/ungueltige Dezimalquoten"]
    flags: list[str] = []
    over = 1 / h + 1 / d + 1 / a
    source = str(odds.get("source") or "")
    if over < OVER_LO and source not in LOW_OVERROUND_OK_SOURCES:
        flags.append(f"Overround {over:.3f} ZU TIEF -> Boost/Promo oder Tippfehler, keine echte 1X2")
    elif over < 0.95:
        flags.append(f"Overround {over:.3f} extrem niedrig -> Best-Odds-Quelle oder Tippfehler pruefen")
    elif over > OVER_HI:
        flags.append(f"Overround {over:.3f} zu hoch -> unrealistisch")
    novig = {k: (1 / v) / over for k, v in (("home", h), ("draw", d), ("away", a))}
    mfav = max(novig, key=novig.get)
    model = prediction["probabilities"]["model"]
    modfav = max(model, key=model.get)
    if mfav != modfav:
        flags.append(f"Favorit Markt={mfav} != Modell={modfav} -> Markt/Modell uneinig ODER Fehl-Zuordnung pruefen")
    prediction["_over"] = over  # fuer die Ausgabe
    return flags


def list_matchday() -> int:
    """SOP-Schritt 1: ungespielte Spiele nach Anstoss sortiert + Quoten-Frische.
    Zeigt, WAS als naechstes zu holen ist (stale = Quelle alt / kein bwin)."""
    fixtures = json.loads((DATA_DIR / "fixtures.json").read_text())
    fixtures = fixtures.get("fixtures", fixtures) if isinstance(fixtures, dict) else fixtures
    preds = {p["fixture"]["match_id"]: p for p in json.loads((DATA_DIR / "predictions.json").read_text())["predictions"]}
    res = json.loads((DATA_DIR / "manual_results.json").read_text())
    played = set(res.get("results", res) if isinstance(res, dict) else res)
    upcoming = []
    for fx in fixtures:
        mid = fx["match_id"]
        if mid in played or str(fx.get("status", "")).lower() in ("finished", "played", "ft"):
            continue
        odds = (preds.get(mid) or {}).get("odds") or {}
        upcoming.append((fx.get("kickoff_utc") or "zzz", mid, fx["home_team"], fx["away_team"],
                         odds.get("source") or "KEINE", str(odds.get("last_updated") or "")))
    upcoming.sort()
    now = datetime.now(timezone.utc)
    print(f"Ungespielte Spiele nach Anstoss ({len(upcoming)}) -- 'stale' = Quelle != bwin / Quote alt:\n")
    for ko, mid, h, a, src, upd in upcoming:
        parsed = parse_iso_datetime(upd)
        age_h = (now - parsed).total_seconds() / 3600 if parsed else None
        # frisch = bwin-Quelle UND Quote innerhalb des Frische-Fensters (sonst holen).
        # src ist bei single-source-bwin "bwin_world_cup_2026", bei Mix "consensus_*".
        fresh = src.startswith(BWIN_SOURCE) and age_h is not None and age_h <= DEFAULT_MATCH_ODDS_FRESH_HOURS
        stale = "" if fresh else "  <- stale (holen)"
        print(f"  {str(ko)[:16]:<16} {mid:<7} {h[:14]:<14} v {a[:14]:<14} [{src} {upd[:10]}]{stale}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        return list_matchday()
    want = set(args)
    preds, played = _load()
    rows = []
    for p in preds:
        f = p["fixture"]
        mid = f["match_id"]
        odds = p.get("odds") or {}
        if want:
            if mid not in want:
                continue
        else:
            if mid in played or not odds.get("decimal_odds"):
                continue
        flags = check(p)
        rows.append((mid, f["home_team"], f["away_team"], odds.get("source"), p.get("_over"), flags))

    nflag = sum(1 for r in rows if r[5])
    print(f"Odds-Check: {len(rows)} Spiele geprueft, {nflag} mit Hinweis\n")
    for mid, home, away, src, over, flags in sorted(rows, key=lambda r: (bool(r[5]), r[0]), reverse=True):
        mark = "!!" if flags else "OK"
        ov = f"{over:.3f}" if over else "  -  "
        print(f"  {mark} {mid:<7} {home[:15]:<15} v {away[:15]:<15} over={ov} src={src}")
        for fl in flags:
            print(f"        -> {fl}")
    if nflag:
        print(f"\n{nflag} Spiel(e) mit Hinweis -- vor Vertrauen pruefen/korrigieren.")
    return 1 if nflag else 0


if __name__ == "__main__":
    raise SystemExit(main())
