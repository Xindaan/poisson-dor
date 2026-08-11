from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .paths import DATA_DIR, RAW_DIR


# WM-Turniere: cup.txt (Vorrunde) + cup_finals.txt (KO) getrennt.
# EM-Turniere (openfootball/euro): EINE euro.txt mit Vorrunde + KO --
# darum zeigen beide Eintraege auf dieselbe Datei; der Gruppen-Parser
# stoppt am ersten KO-Header, der Finals-Parser greift nur die KO-Sektionen.
_WC = "https://raw.githubusercontent.com/openfootball/worldcup/master"
_EU = "https://raw.githubusercontent.com/openfootball/euro/master"

OPENFOOTBALL_TOURNAMENTS = {
    "2010": f"{_WC}/2010--south-africa/cup.txt",
    "2014": f"{_WC}/2014--brazil/cup.txt",
    "2018": f"{_WC}/2018--russia/cup.txt",
    "2022": f"{_WC}/2022--qatar/cup.txt",
    "euro-2016": f"{_EU}/2016--france/euro.txt",
    "euro-2020": f"{_EU}/2021--europe/euro.txt",
    "euro-2024": f"{_EU}/2024--germany/euro.txt",
}

OPENFOOTBALL_FINALS = {
    "2010": f"{_WC}/2010--south-africa/cup_finals.txt",
    "2014": f"{_WC}/2014--brazil/cup_finals.txt",
    "2018": f"{_WC}/2018--russia/cup_finals.txt",
    "2022": f"{_WC}/2022--qatar/cup_finals.txt",
    "euro-2016": f"{_EU}/2016--france/euro.txt",
    "euro-2020": f"{_EU}/2021--europe/euro.txt",
    "euro-2024": f"{_EU}/2024--germany/euro.txt",
}

GROUP_LINE = re.compile(r"^▪\s+Group\s+([A-H])\s*$")

# Gemeinsame Bausteine fuer die openfootball-Spielzeilen ueber alle
# Jahrgaenge (2010-2022). Drei Formatvarianten:
#   2018/2022: "[HH:MM UTC+x] Home  S-S (HT)  Away  @ Venue"
#   2014:      "Home v Away  S-S  @ Venue"            (Score nach Away)
#   2010:      "Wkd Mon DD HH:MM Home  S-S  Away  @ Venue" (inline-Datum)
# _OF_LEAD deckt optionales Datum + Uhrzeit ab, _OF_NAME erlaubt
# Akzente (z.B. Côte d'Ivoire), die der alte [A-Za-z]-Klasse fehlten.
_OF_LEAD = (
    r"(?:[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+)?"  # optional Wkd Mon DD
    r"(?:\d{1,2}:\d{2}(?:\s+UTC[+-]\d+)?"               # optional HH:MM (UTC+x)
    r"(?:\s*\(\d{1,2}:\d{2}(?:\s+UTC[+-]\d+)?\))?"       # optional sekundaere (HH:MM UTC+x), z.B. EM-2020 Baku
    r"\s+)?"
)
_OF_NAME = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ .'’\-]*?"

# KO-Sektionen in cup_finals.txt. Sektionsnamen werden normalisiert
# (Kleinschreibung ohne Sonderzeichen), weil die Jahrgaenge variieren:
# 2010 "Quarterfinals"/"Semifinals" vs. 2018+ "Quarter-finals". Spiel um
# Platz 3 ("Match for third place", "Third-place play-off") faellt damit
# automatisch raus -- kein Kicktipp-Pflicht-KO-Spiel.
FINALS_SECTION_LINE = re.compile(r"^▪\s+(.+?)\s*$")
# Singular- und Plural-Varianten (EM 2020 schreibt "Semi-final").
FINALS_KO_SECTIONS = {
    "roundof16",
    "quarterfinal",
    "quarterfinals",
    "semifinal",
    "semifinals",
    "final",
}
FINALS_MATCH_LINE = re.compile(
    r"^\s*" + _OF_LEAD
    + r"(?P<home>" + _OF_NAME + r")\s+"
    # Score-Blob: erstes Zahlpaar plus optionale a.e.t/pen/Klammer-Zusaetze,
    # bis das (gross beginnende) Auswaertsteam folgt.
    + r"(?P<scoreblob>\d+\s*-\s*\d+(?:[ \t\d.,()\-]|a\.e\.t|pen|o\.g)*?)"
    + r"\s+(?P<away>" + _OF_NAME + r")\s+@\s+(?P<venue>.+?)\s*$"
)
# Elfmeterschiessen-Paar (vor "pen") und Verlaengerungs-Scoreline (vor
# "a.e.t"). WM schreibt "1-1 a.e.t. ..., 3-4 pen.", EM "4-5 pen. 3-3 a.e.t."
# -- beide Reihenfolgen werden korrekt aufgeloest.
PENALTY_RE = re.compile(r"(\d+)\s*-\s*(\d+)\s*pen")
AET_RE = re.compile(r"(\d+)\s*-\s*(\d+)\s*a\.e\.t")
FIRST_SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _parse_finals_score(blob: str) -> tuple[int, int, str | None, list[int] | None]:
    """Liefert (home_score, away_score, penalty_winner, shootout) aus dem Blob.

    Scoreline = Ergebnis nach Verlaengerung (a.e.t), sonst regulaeres
    Ergebnis. Elfmeterschiessen entscheidet das Weiterkommen -- und geht in
    Runden mit Elfmeter-Scope zusaetzlich in die Wertungs-Scoreline ein
    (T-0155), deshalb wird die Bilanz mitgegeben und nicht mehr verworfen.
    """
    penalty_winner = None
    shootout = None
    pen = PENALTY_RE.search(blob)
    if pen:
        home_pens, away_pens = int(pen.group(1)), int(pen.group(2))
        penalty_winner = "home" if home_pens > away_pens else "away"
        shootout = [home_pens, away_pens]
    aet = AET_RE.search(blob)
    if aet:
        return int(aet.group(1)), int(aet.group(2)), penalty_winner, shootout
    first = FIRST_SCORE_RE.search(blob)
    if not first:
        raise ValueError(f"Kein Score im Blob: {blob!r}")
    return int(first.group(1)), int(first.group(2)), penalty_winner, shootout
# Standard-Gruppenzeile (Score zwischen den Teams) -- 2010/2018/2022.
MATCH_LINE = re.compile(
    r"^\s*" + _OF_LEAD
    + r"(?P<home>" + _OF_NAME + r")\s+"
    + r"(?P<home_score>\d+)-(?P<away_score>\d+)"
    + r"(?:\s+\([^)]*\))?\s+"
    + r"(?P<away>" + _OF_NAME + r")\s+@\s+(?P<venue>.+?)\s*$"
)
# "v"-Variante (Score hinter den Teams) -- 2014.
MATCH_LINE_VFORM = re.compile(
    r"^\s*" + _OF_LEAD
    + r"(?P<home>" + _OF_NAME + r")\s+v\s+"
    + r"(?P<away>" + _OF_NAME + r")\s+"
    + r"(?P<home_score>\d+)-(?P<away_score>\d+)"
    + r"(?:\s+\([^)]*\))?\s+@\s+(?P<venue>.+?)\s*$"
)


def _normalize_section(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())

CORE_RESULT_FIELDS = {"match", "stage", "group", "home", "away", "actual", "venue"}


def parse_openfootball_results(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    current_group: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        group_match = GROUP_LINE.match(line)
        if group_match:
            current_group = group_match.group(1)
            continue
        # Jeder andere ▪-Sektionsheader (z.B. KO-Phase in kombinierten
        # euro.txt-Dateien) beendet die Gruppenphase -- sonst bluten die
        # KO-Spiele in die Gruppenliste.
        if line.lstrip().startswith("▪"):
            current_group = None
            continue
        # Nur Zeilen innerhalb einer Gruppen-Sektion werten (schuetzt vor
        # versehentlichem Treffer in Schedule-/Tabellen-Bloecken).
        if current_group is None:
            continue
        match = MATCH_LINE_VFORM.match(line) or MATCH_LINE.match(line)
        if not match:
            continue
        home = " ".join(match.group("home").split())
        away = " ".join(match.group("away").split())
        venue = " ".join(match.group("venue").split())
        results.append(
            {
                "match": f"{home} - {away}",
                "stage": "group",
                "group": current_group,
                "home": home,
                "away": away,
                "actual": [int(match.group("home_score")), int(match.group("away_score"))],
                "venue": venue,
            }
        )
    return results


def parse_openfootball_finals(text: str) -> list[dict[str, Any]]:
    """KO-Spiele aus cup_finals.txt. Scoreline = Ergebnis nach Verlaengerung
    (Elfmeterschiessen entscheidet nur das Weiterkommen, zaehlt nicht zur
    Scoreline -- Kicktipp-Konvention). Spiel um Platz 3 ausgelassen.
    """
    results: list[dict[str, Any]] = []
    stage_active = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        section = FINALS_SECTION_LINE.match(line.strip())
        if section and "|" not in line:
            stage_active = _normalize_section(section.group(1)) in FINALS_KO_SECTIONS
            continue
        if not stage_active:
            continue
        match = FINALS_MATCH_LINE.match(line)
        if not match:
            continue
        home = " ".join(match.group("home").split())
        away = " ".join(match.group("away").split())
        venue = " ".join(match.group("venue").split())
        home_score, away_score, penalty_winner, shootout = _parse_finals_score(
            match.group("scoreblob")
        )
        row = {
            "match": f"{home} - {away}",
            "stage": "knockout",
            "group": None,
            "home": home,
            "away": away,
            # Scoreline nach Verlaengerung (ohne Elfmeter-Bonus-Tor).
            "actual": [home_score, away_score],
            "venue": venue,
        }
        if penalty_winner:
            row["penalty_winner"] = penalty_winner
        if shootout:
            # Reine Elferbilanz -- geht in Runden mit Elfmeter-Scope in die
            # Wertungs-Scoreline ein (T-0155).
            row["shootout"] = shootout
        results.append(row)
    return results


def fetch_openfootball_results(tournament: str, *, force: bool = False) -> str:
    url = OPENFOOTBALL_TOURNAMENTS.get(tournament)
    if not url:
        raise ValueError(f"Unbekanntes Turnier: {tournament}")
    cache_path = RAW_DIR / f"openfootball_{tournament}_results.txt"
    if not force and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    with urllib.request.urlopen(url, timeout=25) as response:
        text = response.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def fetch_openfootball_finals(tournament: str, *, force: bool = False) -> str | None:
    url = OPENFOOTBALL_FINALS.get(tournament)
    if not url:
        return None
    cache_path = RAW_DIR / f"openfootball_{tournament}_finals.txt"
    if not force and cache_path.exists():
        return cache_path.read_text(encoding="utf-8")
    try:
        with urllib.request.urlopen(url, timeout=25) as response:
            text = response.read().decode("utf-8")
    except OSError:
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


def assign_pretournament_elo(
    ko_rows: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
) -> None:
    """KO-Zeilen bekommen die Pre-Turnier-Elo ihres Teams aus den
    Gruppenspielen (Elo aendert sich im Turnier nur wenig; der Snapshot
    ist die beste freie Naeherung). pre_odds bleibt fuer KO offen.
    """
    team_elo: dict[str, float] = {}
    source = None
    for row in group_rows:
        pre = row.get("pre_elo") or {}
        source = source or row.get("pre_elo_source")
        if pre.get("home") is not None:
            team_elo.setdefault(row["home"], float(pre["home"]))
        if pre.get("away") is not None:
            team_elo.setdefault(row["away"], float(pre["away"]))
    for row in ko_rows:
        if row.get("pre_elo"):
            continue
        home_elo = team_elo.get(row["home"])
        away_elo = team_elo.get(row["away"])
        if home_elo is not None and away_elo is not None:
            row["pre_elo"] = {"home": home_elo, "away": away_elo}
            if source:
                row["pre_elo_source"] = source


def _result_key(row: dict[str, Any]) -> tuple[str, str | None]:
    return (str(row.get("match", "")), row.get("group"))


def preserve_existing_enrichment(
    results: list[dict[str, Any]],
    existing_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    existing_rows = existing_payload.get("results", [])
    if not isinstance(existing_rows, list):
        return results
    existing_by_key = {
        _result_key(row): row
        for row in existing_rows
        if isinstance(row, dict) and row.get("match")
    }
    for row in results:
        existing = existing_by_key.get(_result_key(row))
        if not existing:
            continue
        for key, value in existing.items():
            if key not in CORE_RESULT_FIELDS and value not in (None, "", [], {}):
                row[key] = value
    return results


def enrichment_status(results: list[dict[str, Any]]) -> dict[str, Any]:
    pre_elo_matches = sum(1 for row in results if row.get("pre_elo"))
    pre_odds_matches = sum(1 for row in results if row.get("pre_odds"))
    missing_data = []
    if pre_elo_matches < len(results):
        missing_data.append(
            "pre_elo: braucht historischen World-Elo-Snapshot pre-kickoff fuer fehlende Spiele"
        )
    if pre_odds_matches < len(results):
        missing_data.append(
            "pre_odds: braucht historische decimal odds fuer fehlende Spiele"
        )
    return {
        "pre_elo_matches": pre_elo_matches,
        "pre_odds_matches": pre_odds_matches,
        "missing_data": missing_data,
    }


def build_historical_dataset(tournament: str, *, write: bool = True, force_fetch: bool = False) -> dict[str, Any]:
    text = fetch_openfootball_results(tournament, force=force_fetch)
    group_results = parse_openfootball_results(text)
    finals_text = fetch_openfootball_finals(tournament, force=force_fetch)
    ko_results = parse_openfootball_finals(finals_text) if finals_text else []
    results = group_results + ko_results

    path = DATA_DIR / f"backtest_{tournament}.json"
    existing_payload = read_json(path, {}) if path.exists() else {}
    if isinstance(existing_payload, dict):
        results = preserve_existing_enrichment(results, existing_payload)
    # Erst NACH dem Enrichment-Preserve: KO bekommt Pre-Turnier-Elo aus den
    # (nun mit Elo angereicherten) Gruppenspielen, pro Team konstant.
    assign_pretournament_elo(ko_results, group_results)
    existing_meta = existing_payload.get("_meta", {}) if isinstance(existing_payload, dict) else {}
    status = enrichment_status(results)
    stages_covered = ["group"] + (["knockout"] if ko_results else [])
    ko_with_odds = sum(1 for row in ko_results if row.get("pre_odds"))
    if not ko_results:
        ko_odds_clause = ""
    elif ko_with_odds == len(ko_results):
        ko_odds_clause = " KO hat pre_odds (odds-Variante deckt auch die KO-Phase)."
    elif ko_with_odds:
        ko_odds_clause = f" pre_odds fuer KO teilweise offen ({ko_with_odds}/{len(ko_results)} mit Quoten)."
    else:
        ko_odds_clause = " pre_odds fuer KO offen (odds-Variante deckt nur die Gruppenphase)."
    payload = {
        "_meta": {
            "tournament": tournament,
            "source": OPENFOOTBALL_TOURNAMENTS[tournament],
            "finals_source": OPENFOOTBALL_FINALS.get(tournament),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "matches": len(results),
            "group_matches": len(group_results),
            "knockout_matches": len(ko_results),
            "stages_covered": stages_covered,
            "knockout_note": (
                "KO-Scoreline = Ergebnis nach Verlaengerung; Elfmeter entscheidet "
                "nur das Weiterkommen. KO-Elo = Pre-Turnier-Snapshot pro Team."
                + ko_odds_clause
            ),
            "enrichment": existing_meta.get("enrichment", {}),
            "pre_elo_matches": status["pre_elo_matches"],
            "pre_odds_matches": status["pre_odds_matches"],
            "missing_data": status["missing_data"],
        },
        "results": results,
    }
    if write:
        write_json(path, payload)
    return payload


def historical_dataset_path(tournament: str) -> Path:
    return DATA_DIR / f"backtest_{tournament}.json"
