"""Bestaetigte Startelfen headless aus ESPNs offener site.api (Roadmap-Fix
fuer die fehlende Lineup-Automatik).

Anlass: die Aufstellungen kamen nicht automatisch -- es gab keinen Abruf, nur den
'warte auf Lineup'-Marker. Sofascore (Cloudflare 403) und FotMob (x-mas-Token)
sind headless dicht. ESPN `site.api.espn.com` ist offen (kein Key, kein
Cloudflare) und liefert pro Spiel die Roster mit `starter`-Flag -> die
bestaetigte XI. Verifiziert an Deutschland-Curacao (deckt sich mit dem
offiziellen DFB-Tweet).

Schreibt `data/manual_lineups.json` (Format `{"lineups": {team: [names]}}`,
von lineup_roles als verlaesslichste Quelle gelesen) und meldet
'Schluesselspieler ueberraschend nicht in der Startelf' als Alert -- das
einzig wirklich tipprelevante Signal (bei Favoriten aendert die XI nichts).

Headless, read-only nach aussen (GET).
"""
from __future__ import annotations

import json
import subprocess
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .fixtures import load_fixture_payload
from .io import read_json, write_json
from .paths import DATA_DIR

ESPN_LEAGUE = "fifa.world"
ESPN_BASE = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{ESPN_LEAGUE}"
MANUAL_LINEUPS_PATH = DATA_DIR / "manual_lineups.json"
PLAYER_POOL_PATH = DATA_DIR / "player_pool.json"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# ESPN-Teamnamen -> normalisierte Fixture-Namen (nur die echten Abweichungen).
_NAME_ALIASES = {
    "turkiye": "turkey",
    "cotedivoire": "ivorycoast",
    "korearepublic": "southkorea",
    "republicofkorea": "southkorea",
    "czechia": "czechrepublic",
    "iriran": "iran",
    "unitedstates": "usa",
    "capeverdeislands": "capeverde",
}
KEY_PLAYER_MIN_SHARE = 0.15  # ab hier gilt ein Pool-Spieler als Schluesselspieler


def _norm(name: Any) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = "".join(ch for ch in s.lower() if ch.isalnum())
    return _NAME_ALIASES.get(s, s)


def _get_json(url: str, timeout: int = 20) -> dict[str, Any]:
    """urllib zuerst, curl-Fallback (wie bwin_exact_scores)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        out = subprocess.run(
            ["curl", "-sS", "-m", str(timeout), "-H", f"User-Agent: {_UA}",
             "-H", "Accept: application/json", url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return json.loads(out.stdout)


def fetch_scoreboard(date_yyyymmdd: str) -> list[dict[str, Any]]:
    data = _get_json(f"{ESPN_BASE}/scoreboard?dates={date_yyyymmdd}")
    return data.get("events") or []


def fetch_summary(event_id: str) -> dict[str, Any]:
    return _get_json(f"{ESPN_BASE}/summary?event={event_id}")


def starters_from_summary(summary: dict[str, Any]) -> dict[str, list[str]]:
    """{normalisierter Teamname: [Starter-Namen]} aus dem rosters-Block."""
    out: dict[str, list[str]] = {}
    for team in summary.get("rosters") or []:
        name = (team.get("team") or {}).get("displayName")
        starters = [
            (entry.get("athlete") or {}).get("displayName")
            for entry in (team.get("roster") or [])
            if entry.get("starter") and (entry.get("athlete") or {}).get("displayName")
        ]
        if name and starters:
            out[_norm(name)] = starters
    return out


def _event_team_norms(event: dict[str, Any]) -> set[str]:
    norms: set[str] = set()
    for comp in event.get("competitions") or []:
        for competitor in comp.get("competitors") or []:
            disp = (competitor.get("team") or {}).get("displayName")
            if disp:
                norms.add(_norm(disp))
    return norms


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def absent_key_players(
    team_name: str, xi: list[str], player_pool: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pool-Schluesselspieler-DICTS, die NICHT in der XI stehen. Schluessel-
    spieler ist, wer goal_share >= Schwelle hat ODER explizit als key_player
    markiert ist. Das key_player-Flag faengt kreativ/defensiv wertvolle Stars
    (Pulisic, Modric, van Dijk, ...), deren goal_share absichtlich 0 ist, um den
    Topscorer-Bonus neutral zu halten. Gemeinsamer Detektor fuer den Pre-Kickoff-
    Monitor (`_key_absences`) UND den xG-Malus (T-0113, lineup_absence)."""
    xi_norm = {_norm(n) for n in xi}
    absent: list[dict[str, Any]] = []
    for player in player_pool.get(team_name) or []:
        try:
            share = float(player.get("goal_share") or 0)
        except (TypeError, ValueError):
            share = 0.0
        is_key = share >= KEY_PLAYER_MIN_SHARE or bool(player.get("key_player"))
        name = player.get("name")
        if name and is_key and _norm(name) not in xi_norm:
            absent.append(player)
    return absent


def _key_absences(team_name: str, xi: list[str], player_pool: dict[str, Any]) -> list[str]:
    """Namen der Pool-Schluesselspieler, die NICHT in der XI stehen -- der
    tipprelevante Pre-Kickoff-Alarm (Wrapper um `absent_key_players`)."""
    return [
        str(p.get("name"))
        for p in absent_key_players(team_name, xi, player_pool)
        if p.get("name")
    ]


def _players_from_pool(payload: Any) -> dict[str, Any]:
    """player_pool.json ist {"_meta": ..., "players": {team: [...]}}. Die
    team->players-Map herausziehen -- sonst sieht player_pool.get(team) nichts
    und key_absences bleibt faelschlich leer (Regression nach Struktur-Umstellung;
    alle anderen Pool-Leser in model/strength/news_audit machen es ebenso)."""
    return payload.get("players", {}) if isinstance(payload, dict) else {}


def refresh_lineups(
    *,
    now: datetime | None = None,
    window_minutes: int = 75,
    lookback_minutes: int = 20,
    write: bool = True,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=window_minutes)
    start = now - timedelta(minutes=lookback_minutes)
    fixtures = load_fixture_payload().get("fixtures", [])
    player_pool = _players_from_pool(read_json(PLAYER_POOL_PATH, {"players": {}}))

    upcoming = []
    for fx in fixtures:
        if fx.get("status") == "played":
            continue
        kickoff = _parse(fx.get("kickoff_utc") or fx.get("kickoff"))
        if kickoff and start <= kickoff <= horizon:
            upcoming.append((fx, kickoff))
    if not upcoming:
        return {"_meta": {"updated_at": now.isoformat(), "in_window": 0,
                          "note": "Kein Spiel im Pre-Kickoff-Fenster."}, "items": []}

    # ESPN-Scoreboard fuer die betroffenen UTC-Tage einmalig holen + indexieren.
    dates = sorted({k.strftime("%Y%m%d") for _, k in upcoming})
    event_index: dict[frozenset[str], str] = {}
    for d in dates:
        try:
            for event in fetch_scoreboard(d):
                norms = _event_team_norms(event)
                if len(norms) == 2:
                    event_index[frozenset(norms)] = event.get("id")
        except Exception:  # pragma: no cover - live network
            continue

    existing = read_json(MANUAL_LINEUPS_PATH, {})
    lineups = dict(existing.get("lineups") or {}) if isinstance(existing, dict) else {}
    # T-0113: XI<->Spiel-Linkage. Eine bestaetigte XI gehoert zu GENAU einem
    # Spiel; der xG-Ausfall-Malus darf sie nur auf dieses Spiel anwenden (sonst
    # bestraft eine Alt-XI faelschlich das naechste Spiel desselben Teams).
    lineups_meta = (
        dict(existing.get("lineups_meta") or {}) if isinstance(existing, dict) else {}
    )
    diagnostics: list[dict[str, Any]] = []
    written = 0
    for fx, kickoff in sorted(upcoming, key=lambda t: t[1]):
        home = fx.get("home") or fx.get("home_team")
        away = fx.get("away") or fx.get("away_team")
        key = frozenset({_norm(home), _norm(away)})
        event_id = event_index.get(key)
        row: dict[str, Any] = {"match_id": fx.get("match_id"), "match": f"{home} - {away}"}
        if not event_id:
            row["status"] = "no_espn_event"
            diagnostics.append(row)
            continue
        try:
            starters = starters_from_summary(fetch_summary(event_id))
        except Exception as exc:  # pragma: no cover - live network
            row.update(status="error", error=str(exc))
            diagnostics.append(row)
            continue
        confirmed = {}
        for team_name in (home, away):
            xi = starters.get(_norm(team_name))
            if xi and len(xi) >= 9:
                lineups[team_name] = xi
                confirmed[team_name] = xi
                lineups_meta[team_name] = {
                    "match_id": fx.get("match_id"),
                    "match": f"{home} - {away}",
                    "kickoff_utc": fx.get("kickoff_utc") or fx.get("kickoff"),
                    "captured_at": now.isoformat(),
                }
                written += 1
        if not confirmed:
            row["status"] = "no_starters_yet"
            diagnostics.append(row)
            continue
        absences = {t: _key_absences(t, xi, player_pool) for t, xi in confirmed.items()}
        row.update(
            status="confirmed",
            teams_confirmed=list(confirmed),
            key_absences={t: a for t, a in absences.items() if a},
        )
        diagnostics.append(row)

    payload = {
        "_meta": {
            "updated_at": now.isoformat(),
            "source": "espn_site_api",
            "league": ESPN_LEAGUE,
            "in_window": len(upcoming),
            "teams_written": written,
            "note": "Bestaetigte XIs headless aus ESPN; key_absences = Pool-Schluesselspieler nicht in der Startelf.",
        },
        "items": diagnostics,
        "lineups": lineups,
        "lineups_meta": lineups_meta,
    }
    if write and written:
        # bestehende _meta/sonstiges bewahren, nur lineups + _meta fortschreiben
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged["lineups"] = lineups
        merged["lineups_meta"] = lineups_meta
        merged["_meta"] = payload["_meta"]
        write_json(MANUAL_LINEUPS_PATH, merged)
    return payload
