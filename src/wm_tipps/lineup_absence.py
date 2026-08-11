"""T-0113: xG-Malus fuer bestaetigte XI-Ausfaelle von Pool-Schluesselspielern.

Luecke (Befund 2026-06-22): der EINZIGE xG-Kanal fuer einen Ausfall ist eine
xG-wirksame News (severity important/critical + injury/illness/suspension). Die
bestaetigte Startelf setzt via `lineup_roles` nur `role` und moduliert den
News-Effekt -- sie erzeugt aber KEINEN eigenen xG-Effekt. Folge: faellt ein
Schluesselspieler ohne harte News aus (Beispiel Belgium: Doku, goal_share 0.26,
nicht in der bestaetigten XI, News nur severity=context), bleibt das xG und der
Tipp unveraendert, obwohl 26% der Tor-Produktion auf der Bank sitzen.

Historisch unkritisch, weil der MARKT Ausfaelle in die Pre-Match-Quoten einpreist
(der Backtest nutzt genau diese) -- die Luecke ist rein LIVE + last-minute bei
stalen Quoten. Daher: NICHT backtestbar (keine historischen XI-Daten) ->
forward-gated, default AUS (`LINEUP_ABSENCE_XG_ENABLED`).

Mechanik (spiegelt das prep_disruption-Muster: eigene, auditierbare
xG-Breakdown-Zeile, in `context_payload` injiziert):

- **Frische-Gate (zwingend):** der Malus wird nur auf das Spiel angewandt, fuer
  das die XI nachweislich erfasst wurde (`lineups_meta[team].match_id ==
  fixture.match_id`). Eine Alt-XI eines bereits gespielten Spiels darf NICHT das
  naechste Spiel desselben Teams bestrafen.
- **Malus pro Ausfall:** `ATTACK_DELTA_CRITICAL * share_factor * drop_off` mit den
  GLEICHEN News-Konstanten (keine neuen Magie-Zahlen). Ein bestaetigtes
  Startelf-Aus ist informationell ~ einem "critical"-Ausfall (Spieler spielt
  definitiv nicht). `share_factor` hat den News-Floor `PLAYER_SCALE_MIN=0.4` ->
  auch key_player-Stars mit goal_share 0 (van Dijk, Modric ...) bekommen einen
  kleinen, nicht-null Floor-Malus statt 0.
- **Positions-Routing wie News:** Offensive (FW/MF/unbekannt) -> eigene xG runter;
  Defensive (GK/DF) -> Gegner-xG hoch (* 0.45-Kreuzeffekt).
- **Doppelzaehl-Schutz:** Spieler, die ohnehin schon per xG-wirksamer News im
  Modell haengen, werden uebersprungen.

Read-only nach aussen, stdlib-only.
"""
from __future__ import annotations

from typing import Any, Mapping

from .lineups import absent_key_players
from .news import (
    ATTACK_DELTA_CRITICAL,
    ATTACKING_POSITIONS,
    DEFENSE_DELTA_CRITICAL,
    DEFENSIVE_POSITIONS,
    DROP_OFF_MAX_BONUS,
    PLAYER_NEWS_BASELINE_SHARE,
    PLAYER_SCALE_MAX,
    PLAYER_SCALE_MIN,
    normalize_player_subject,
    team_xg_news_subject_keys,
)

# Forward-gated Modell-Hebel. Nach Sichtung des Live-Tipp-Diffs wurde er
# (T-0113, 2026-06-22) AKTIVIERT. NICHT backtestbar -> nur forward-validierbar;
# Wirkung erst, wenn eine bestaetigte XI fuer das konkrete Spiel erfasst ist
# (Frische-Gate). Auf False setzen, um den Hebel komplett zu deaktivieren.
LINEUP_ABSENCE_XG_ENABLED = True

# Defensiver Cross-Effekt (eigene Defensive schwach -> Gegner trifft mehr),
# identisch zum News-Pfad in model.expected_goals.
DEFENSE_CROSS_FACTOR = 0.45
# Per-Team-Klammern (gegen Haeufung mehrerer Ausfaelle), bewusst milder als die
# News-Klammern -- ein Modell-Hebel ohne Backtest bleibt konservativ.
ABSENCE_ATTACK_FLOOR = -0.35
ABSENCE_DEFENSE_CAP = 0.20


def _goal_share(player: Mapping[str, Any]) -> float:
    try:
        return float(player.get("goal_share") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def player_absence_effect(
    player: Mapping[str, Any], roster: list[Mapping[str, Any]]
) -> tuple[float, float, dict[str, Any]]:
    """(attack_delta, defense_delta, detail) fuer EINEN ausgefallenen Spieler.

    attack_delta < 0 (eigene Offensive schwaecher), defense_delta > 0 (eigene
    Defensive schwaecher -> Gegner-Boost). Spiegelt die News-Skalierung."""
    share = _goal_share(player)
    share_factor = min(PLAYER_SCALE_MAX, max(PLAYER_SCALE_MIN, share / PLAYER_NEWS_BASELINE_SHARE))
    others = [_goal_share(p) for p in roster if p is not player]
    gap = share - (max(others) if others else 0.0)
    drop_off = 1.0 + max(0.0, min(DROP_OFF_MAX_BONUS, gap))
    scale = share_factor * drop_off
    position = str(player.get("position") or "").strip().upper() or None
    attack = defense = 0.0
    if position in DEFENSIVE_POSITIONS:
        defense = DEFENSE_DELTA_CRITICAL * scale
        routed = "defense"
    else:
        # Offensive ODER unbekannte Position -> eigene Offensive (B1-Verhalten).
        attack = ATTACK_DELTA_CRITICAL * scale
        routed = "attack"
    detail = {
        "name": player.get("name"),
        "goal_share": round(share, 4),
        "position": position,
        "key_player": bool(player.get("key_player")),
        "scale": round(scale, 4),
        "routed": routed,
        "attack_delta": round(attack, 4),
        "defense_delta": round(defense, 4),
    }
    return attack, defense, detail


def _side_effect(
    team: str,
    xi: list[str],
    player_pool: Mapping[str, list[Mapping[str, Any]]],
    news_subjects: set[str],
) -> tuple[float, float, list[dict[str, Any]]]:
    """Summierter (attack, defense, absent_details) fuer ein Team, deduped
    gegen Spieler, die schon per News im xG haengen."""
    roster = list(player_pool.get(team) or [])
    attack_total = defense_total = 0.0
    details: list[dict[str, Any]] = []
    for player in absent_key_players(team, xi, player_pool):
        subject = normalize_player_subject(str(player.get("name") or ""))
        if subject and subject in news_subjects:
            continue  # schon per News gewertet -> nicht doppelt
        attack, defense, detail = player_absence_effect(player, roster)
        attack_total += attack
        defense_total += defense
        details.append(detail)
    attack_total = max(ABSENCE_ATTACK_FLOOR, attack_total)
    defense_total = min(ABSENCE_DEFENSE_CAP, defense_total)
    return attack_total, defense_total, details


def build_lineup_absence_index(
    fixtures: list[Mapping[str, Any]],
    player_pool: Mapping[str, list[Mapping[str, Any]]],
    lineups_payload: Mapping[str, Any] | None,
    news_items: list[Mapping[str, Any]] | None = None,
    *,
    enabled: bool | None = None,
) -> dict[str, dict[str, Any]]:
    """{match_id: {home_xg_delta, away_xg_delta, absent, note}} fuer ungespielte
    Spiele, deren bestaetigte XI FUER GENAU DIESES Spiel erfasst wurde.

    `enabled=None` nutzt das Modul-Flag (default AUS -> leerer Index)."""
    if enabled is None:
        enabled = LINEUP_ABSENCE_XG_ENABLED
    if not enabled:
        return {}
    lineups = (lineups_payload or {}).get("lineups") or {}
    meta = (lineups_payload or {}).get("lineups_meta") or {}
    news_items = list(news_items or [])
    index: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        if fixture.get("status") == "played":
            continue
        match_id = fixture.get("match_id")
        home = fixture.get("home_team") or fixture.get("home")
        away = fixture.get("away_team") or fixture.get("away")
        home_delta = away_delta = 0.0
        absent: dict[str, list[dict[str, Any]]] = {}
        for side, team in (("home", home), ("away", away)):
            if not team:
                continue
            team_meta = meta.get(team) or {}
            # Frische-Gate: die gespeicherte XI muss FUER DIESES Spiel sein.
            if team_meta.get("match_id") != match_id:
                continue
            xi = lineups.get(team) or []
            if not xi:
                continue
            news_subjects = team_xg_news_subject_keys(team, news_items, player_pool)
            attack, defense, details = _side_effect(team, xi, player_pool, news_subjects)
            if not details:
                continue
            absent[team] = details
            if side == "home":
                home_delta += attack  # eigene Offensive runter
                away_delta += defense * DEFENSE_CROSS_FACTOR  # eigene Defensive schwach -> away-xG hoch
            else:
                away_delta += attack
                home_delta += defense * DEFENSE_CROSS_FACTOR
        if absent:
            index[str(match_id)] = {
                "home_xg_delta": round(home_delta, 4),
                "away_xg_delta": round(away_delta, 4),
                "absent": absent,
                "note": "T-0113 XI-Ausfall Pool-Schluesselspieler (forward-gated).",
            }
    return index
