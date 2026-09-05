"""Umfeld-Modifikatoren je Spiel: Klima, Hoehe, Reisebelastung.

Die WM 2026 laeuft ueber drei Laender und rund 2200 Hoehenmeter Spanne.
Das schlaegt messbar auf die Torerwartung durch, und zwar asymmetrisch --
ein an Meereshoehe trainiertes Team verliert in Mexiko-Stadt mehr als
umgekehrt. Dieses Modul quantifiziert:

  * Hitze/Luftfeuchte (WBGT-Naeherung) -> weniger Intensitaet, weniger Tore
  * Hoehenlage -> Vorteil fuer das hoehenadaptierte Team
  * Reisedistanz und Zeitzonenwechsel seit dem letzten Spiel

Ausgabe: `data/context.json`, von `model` als xG-Modifikator gelesen.
HOST_CITIES ist turnierspezifisch und fuer ein anderes Turnier zu ersetzen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, atan2
from typing import Any

from .io import read_json, write_json
from .paths import DATA_DIR


CLIMATE_CONTROLLED_WBGT_C = 17.6
HEAT_STRESS_START_WBGT_C = 24.0
HEAT_COOLING_BREAK_WBGT_C = 26.0
HEAT_POSTPONE_WATCH_WBGT_C = 28.0

# Hoehenlage: ab 1500 m duennt die Luft messbar das Spieltempo aus
# (weniger Toraktionen). Konservativer, geclampter Prior. Heim-Nationen
# in ihren Hoehenstaedten sind teil-akklimatisiert.
ALTITUDE_THRESHOLD_M = 1500
ALTITUDE_XG_PER_1000M = -0.05
ALTITUDE_XG_CAP = -0.20
ALTITUDE_ACCLIM_BONUS = 0.03
ALTITUDE_HIGH_RISK_M = 2000

# Reise/Jet-Lag: erst ab ~1000 km zwischen zwei Spielorten fuehlbar,
# plus Muedigkeit bei < 72 h Erholung. Beide klein und geclampt.
TRAVEL_THRESHOLD_KM = 1000
TRAVEL_XG_PER_KM = -0.0001
TRAVEL_XG_CAP = -0.08
REST_FULL_RECOVERY_HOURS = 72
REST_PENALTY_MAX = -0.03
TRAVEL_TOTAL_CAP = -0.10

HOST_CITIES: dict[str, dict[str, Any]] = {
    "Mexico City": {"country": "Mexico", "lat": 19.4326, "lon": -99.1332, "altitude_m": 2240, "climate": "altitude"},
    "Guadalajara (Zapopan)": {"country": "Mexico", "lat": 20.6597, "lon": -103.3496, "altitude_m": 1566, "climate": "warm"},
    "Monterrey (Guadalupe)": {"country": "Mexico", "lat": 25.6866, "lon": -100.3161, "altitude_m": 540, "climate": "hot"},
    "Atlanta": {"country": "USA", "lat": 33.749, "lon": -84.388, "altitude_m": 320, "climate": "humid"},
    "Boston (Foxborough)": {"country": "USA", "lat": 42.0654, "lon": -71.2478, "altitude_m": 88, "climate": "mild"},
    "Dallas (Arlington)": {"country": "USA", "lat": 32.7357, "lon": -97.1081, "altitude_m": 184, "climate": "hot"},
    "Houston": {"country": "USA", "lat": 29.7604, "lon": -95.3698, "altitude_m": 13, "climate": "humid"},
    "Kansas City": {"country": "USA", "lat": 39.0997, "lon": -94.5786, "altitude_m": 277, "climate": "warm"},
    "Los Angeles (Inglewood)": {"country": "USA", "lat": 33.9533, "lon": -118.339, "altitude_m": 40, "climate": "mild"},
    "Miami (Miami Gardens)": {"country": "USA", "lat": 25.942, "lon": -80.2456, "altitude_m": 2, "climate": "humid"},
    "New York/New Jersey (East Rutherford)": {"country": "USA", "lat": 40.8135, "lon": -74.0745, "altitude_m": 2, "climate": "mild"},
    "Philadelphia": {"country": "USA", "lat": 39.9526, "lon": -75.1652, "altitude_m": 12, "climate": "warm"},
    "San Francisco Bay Area (Santa Clara)": {"country": "USA", "lat": 37.3541, "lon": -121.9552, "altitude_m": 22, "climate": "mild"},
    "Seattle": {"country": "USA", "lat": 47.6062, "lon": -122.3321, "altitude_m": 52, "climate": "mild"},
    "Toronto": {"country": "Canada", "lat": 43.6532, "lon": -79.3832, "altitude_m": 76, "climate": "mild"},
    "Vancouver": {"country": "Canada", "lat": 49.2827, "lon": -123.1207, "altitude_m": 2, "climate": "mild"},
}

VENUE_HEAT_PROFILE: dict[str, dict[str, Any]] = {
    # Values are a lightweight open-source prior, intentionally conservative.
    # They represent a hot-afternoon WBGT climatology before kickoff-hour and
    # stadium-control adjustments. Matchday forecasts can override this later.
    "Mexico City": {"wbgt_midday_c": 24.7, "air_conditioned": False, "note": "altitude plus warm June conditions"},
    "Guadalajara (Zapopan)": {"wbgt_midday_c": 25.4, "air_conditioned": False, "note": "warm open stadium"},
    "Monterrey (Guadalupe)": {"wbgt_midday_c": 27.2, "air_conditioned": False, "note": "northern Mexico heat-stress watch"},
    "Atlanta": {"wbgt_midday_c": 26.7, "air_conditioned": True, "note": "climate-controlled retractable-roof venue"},
    "Boston (Foxborough)": {"wbgt_midday_c": 24.8, "air_conditioned": False, "note": "open-air northeast venue"},
    "Dallas (Arlington)": {"wbgt_midday_c": 27.8, "air_conditioned": True, "note": "climate-controlled stadium; outdoor fan heat still relevant"},
    "Houston": {"wbgt_midday_c": 27.4, "air_conditioned": True, "note": "climate-controlled stadium; outdoor fan heat still relevant"},
    "Kansas City": {"wbgt_midday_c": 26.6, "air_conditioned": False, "note": "open-air Midwest heat-stress watch"},
    "Los Angeles (Inglewood)": {"wbgt_midday_c": 24.7, "air_conditioned": False, "note": "roofed/open-air hybrid treated as not fully climate-controlled"},
    "Miami (Miami Gardens)": {"wbgt_midday_c": 28.1, "air_conditioned": False, "note": "open-air humid venue, high WBGT watch"},
    "New York/New Jersey (East Rutherford)": {"wbgt_midday_c": 25.7, "air_conditioned": False, "note": "open-air final venue"},
    "Philadelphia": {"wbgt_midday_c": 26.2, "air_conditioned": False, "note": "open-air heat-stress watch"},
    "San Francisco Bay Area (Santa Clara)": {"wbgt_midday_c": 23.5, "air_conditioned": False, "note": "milder Bay Area venue"},
    "Seattle": {"wbgt_midday_c": 21.8, "air_conditioned": False, "note": "milder Pacific Northwest venue"},
    "Toronto": {"wbgt_midday_c": 23.8, "air_conditioned": False, "note": "milder Canadian venue"},
    "Vancouver": {"wbgt_midday_c": 19.8, "air_conditioned": True, "note": "roofed/climate-controlled venue"},
}

TEAM_HOME_COUNTRIES = {
    "Mexico": "Mexico",
    "USA": "USA",
    "Canada": "Canada",
}

HOT_ADAPTED_TEAMS = {
    "Algeria",
    "Argentina",
    "Brazil",
    "Cape Verde",
    "Colombia",
    "DR Congo",
    "Ecuador",
    "Egypt",
    "Ghana",
    "Haiti",
    "Iran",
    "Iraq",
    "Ivory Coast",
    "Jordan",
    "Mexico",
    "Morocco",
    "Panama",
    "Paraguay",
    "Qatar",
    "Saudi Arabia",
    "Senegal",
    "South Africa",
    "Spain",
    "Tunisia",
    "Turkey",
    "Uruguay",
    "USA",
}

COOL_ADAPTED_TEAMS = {
    "Austria",
    "Belgium",
    "Bosnia & Herzegovina",
    "Canada",
    "Croatia",
    "Czech Republic",
    "England",
    "France",
    "Germany",
    "Netherlands",
    "New Zealand",
    "Norway",
    "Scotland",
    "South Korea",
    "Sweden",
    "Switzerland",
}


def haversine_km(a: dict[str, float], b: dict[str, float]) -> float:
    radius = 6371.0
    dlat = radians(b["lat"] - a["lat"])
    dlon = radians(b["lon"] - a["lon"])
    lat1 = radians(a["lat"])
    lat2 = radians(b["lat"])
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius * atan2(sqrt(h), sqrt(1 - h))


def local_kickoff_hour(fixture: dict[str, Any]) -> int | None:
    local_time = str(fixture.get("local_time") or "")
    try:
        time_part = local_time.split()[1]
        return int(time_part.split(":", 1)[0])
    except (IndexError, ValueError):
        return None


def kickoff_hour_wbgt_adjustment(hour: int | None) -> float:
    if hour is None:
        return 0.0
    if hour < 12:
        return -1.0
    if hour < 15:
        return -0.3
    if hour < 18:
        return 0.2
    if hour < 21:
        return -0.8
    return -1.4


def heat_risk_level(effective_wbgt_c: float | None) -> str:
    if effective_wbgt_c is None:
        return "unknown"
    if effective_wbgt_c >= HEAT_POSTPONE_WATCH_WBGT_C:
        return "high"
    if effective_wbgt_c >= HEAT_COOLING_BREAK_WBGT_C:
        return "moderate"
    if effective_wbgt_c >= HEAT_STRESS_START_WBGT_C:
        return "elevated"
    return "low"


def heat_stress_factor(effective_wbgt_c: float | None) -> float:
    if effective_wbgt_c is None:
        return 0.0
    return max(0.0, min(1.0, (effective_wbgt_c - HEAT_STRESS_START_WBGT_C) / 4.0))


def team_heat_adaptation(team: str) -> float:
    if team in HOT_ADAPTED_TEAMS:
        return 0.35
    if team in COOL_ADAPTED_TEAMS:
        return -0.25
    return 0.0


def heat_context_for_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    venue = fixture.get("venue", "")
    profile = VENUE_HEAT_PROFILE.get(venue, {})
    midday_wbgt = profile.get("wbgt_midday_c")
    estimated_wbgt: float | None = None
    if isinstance(midday_wbgt, (int, float)):
        estimated_wbgt = round(float(midday_wbgt) + kickoff_hour_wbgt_adjustment(local_kickoff_hour(fixture)), 1)
    air_conditioned = bool(profile.get("air_conditioned"))
    effective_wbgt = (
        min(float(estimated_wbgt), CLIMATE_CONTROLLED_WBGT_C)
        if air_conditioned and estimated_wbgt is not None
        else estimated_wbgt
    )
    if effective_wbgt is not None:
        effective_wbgt = round(effective_wbgt, 1)
    stress_factor = heat_stress_factor(effective_wbgt)
    home_team = str(fixture.get("home_team", ""))
    away_team = str(fixture.get("away_team", ""))
    home_adaptation = team_heat_adaptation(home_team)
    away_adaptation = team_heat_adaptation(away_team)
    pace_delta = round(-0.08 * stress_factor, 3)
    adaptation_shift = round(
        max(-0.12, min(0.12, (home_adaptation - away_adaptation) * 0.12 * stress_factor)),
        3,
    )
    return {
        "estimated_wbgt_c": estimated_wbgt,
        "effective_wbgt_c": effective_wbgt,
        "risk": heat_risk_level(effective_wbgt),
        "ambient_risk": heat_risk_level(estimated_wbgt),
        "air_conditioned": air_conditioned,
        "climate_controlled_wbgt_c": CLIMATE_CONTROLLED_WBGT_C if air_conditioned else None,
        "stress_factor": round(stress_factor, 3),
        "pace_xg_delta": pace_delta,
        "home_adaptation": home_adaptation,
        "away_adaptation": away_adaptation,
        "home_adaptation_xg_delta": adaptation_shift,
        "away_adaptation_xg_delta": -adaptation_shift,
        "home_xg_delta": round(pace_delta + adaptation_shift, 3),
        "away_xg_delta": round(pace_delta - adaptation_shift, 3),
        "source": "open WBGT climatology prior from WWA/FIFPRO/SportRxiv/Bloomberg-style heat-stress reports; matchday forecast can override",
        "note": profile.get("note", ""),
    }


def altitude_context_for_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    city = fixture.get("venue", "")
    meta = HOST_CITIES.get(city, {})
    altitude = int(meta.get("altitude_m") or 0)
    if altitude < ALTITUDE_THRESHOLD_M:
        return {
            "altitude_m": altitude,
            "risk": "low",
            "pace_xg_delta": 0.0,
            "home_acclimatized": False,
            "away_acclimatized": False,
            "home_xg_delta": 0.0,
            "away_xg_delta": 0.0,
            "source": "HOST_CITIES altitude_m",
            "note": "",
        }
    pace = max(ALTITUDE_XG_CAP, ALTITUDE_XG_PER_1000M * (altitude - ALTITUDE_THRESHOLD_M) / 1000.0)
    country = meta.get("country")
    home_team = fixture.get("home_team")
    away_team = fixture.get("away_team")
    home_acclim = TEAM_HOME_COUNTRIES.get(home_team) == country
    away_acclim = TEAM_HOME_COUNTRIES.get(away_team) == country
    home_bonus = ALTITUDE_ACCLIM_BONUS if home_acclim else 0.0
    away_bonus = ALTITUDE_ACCLIM_BONUS if away_acclim else 0.0
    return {
        "altitude_m": altitude,
        "risk": "high" if altitude >= ALTITUDE_HIGH_RISK_M else "moderate",
        "pace_xg_delta": round(pace, 3),
        "home_acclimatized": home_acclim,
        "away_acclimatized": away_acclim,
        "home_xg_delta": round(pace + home_bonus, 3),
        "away_xg_delta": round(pace + away_bonus, 3),
        "source": "HOST_CITIES altitude_m; konservativer Hoehen-Tempo-Prior",
        "note": (
            f"{altitude} m -- duenne Luft senkt das Spieltempo; "
            "Heimnation teil-akklimatisiert"
        ),
    }


def _parse_kickoff(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _side_travel_effect(
    prev: dict[str, Any] | None, venue_meta: dict[str, Any], kickoff: datetime | None
) -> dict[str, Any]:
    if not prev:
        return {"travel_km": None, "rest_hours": None, "xg_delta": 0.0}
    prev_meta = HOST_CITIES.get(prev.get("venue", ""), {})
    travel_km: float | None = None
    if {"lat", "lon"} <= prev_meta.keys() and {"lat", "lon"} <= venue_meta.keys():
        travel_km = round(haversine_km(prev_meta, venue_meta), 1)
    travel_delta = 0.0
    if travel_km is not None:
        travel_delta = max(TRAVEL_XG_CAP, TRAVEL_XG_PER_KM * max(0.0, travel_km - TRAVEL_THRESHOLD_KM))
    rest_hours: float | None = None
    rest_delta = 0.0
    prev_kickoff = _parse_kickoff(prev.get("kickoff_utc"))
    if prev_kickoff and kickoff:
        rest_hours = round((kickoff - prev_kickoff).total_seconds() / 3600, 1)
        shortfall = max(0.0, REST_FULL_RECOVERY_HOURS - rest_hours) / 24.0
        rest_delta = REST_PENALTY_MAX * min(1.0, shortfall)
    xg_delta = max(TRAVEL_TOTAL_CAP, round(travel_delta + rest_delta, 3))
    return {"travel_km": travel_km, "rest_hours": rest_hours, "xg_delta": xg_delta}


def build_travel_index(fixtures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """match_id -> {home_xg_delta, away_xg_delta, ...} aus Reise seit dem
    letzten Spiel jedes Teams. Chronologisch, O(n log n).
    """
    last_by_team: dict[str, dict[str, Any]] = {}
    index: dict[str, dict[str, Any]] = {}
    ordered = sorted(
        fixtures,
        key=lambda fx: (str(fx.get("kickoff_utc") or ""), fx.get("match_number") or 0),
    )
    for fx in ordered:
        venue = fx.get("venue", "")
        venue_meta = HOST_CITIES.get(venue, {})
        kickoff = _parse_kickoff(fx.get("kickoff_utc"))
        home = str(fx.get("home_team", ""))
        away = str(fx.get("away_team", ""))
        home_eff = _side_travel_effect(last_by_team.get(home), venue_meta, kickoff)
        away_eff = _side_travel_effect(last_by_team.get(away), venue_meta, kickoff)
        index[str(fx.get("match_id") or "")] = {
            "home_km": home_eff["travel_km"],
            "away_km": away_eff["travel_km"],
            "home_rest_hours": home_eff["rest_hours"],
            "away_rest_hours": away_eff["rest_hours"],
            "home_xg_delta": home_eff["xg_delta"],
            "away_xg_delta": away_eff["xg_delta"],
            "source": "HOST_CITIES Geo-Distanz (haversine) + Erholungszeit aus Spielplan",
        }
        appearance = {"venue": venue, "kickoff_utc": fx.get("kickoff_utc")}
        last_by_team[home] = appearance
        last_by_team[away] = appearance
    return index


def context_for_fixture(
    fixture: dict[str, Any], travel_stress: dict[str, Any] | None = None
) -> dict[str, Any]:
    city = fixture.get("venue", "")
    meta = HOST_CITIES.get(city, {})
    flags = []
    if meta.get("altitude_m", 0) >= 1500:
        flags.append("altitude")
    if meta.get("climate") in {"hot", "humid"}:
        flags.append(meta["climate"])
    heat = heat_context_for_fixture(fixture)
    if heat.get("risk") in {"moderate", "high"}:
        flags.append(f"heat_{heat['risk']}")
    elif heat.get("ambient_risk") in {"moderate", "high"} and heat.get("air_conditioned"):
        flags.append("heat_mitigated")
    if heat.get("air_conditioned"):
        flags.append("climate_controlled")
    altitude_stress = altitude_context_for_fixture(fixture)
    if altitude_stress.get("risk") in {"moderate", "high"}:
        flags.append(f"altitude_{altitude_stress['risk']}")
    country = meta.get("country")
    home_advantage = 0.0
    for side in ("home_team", "away_team"):
        team = fixture.get(side)
        if TEAM_HOME_COUNTRIES.get(team) == country:
            home_advantage = 0.18 if side == "home_team" else -0.18
    return {
        "venue": city,
        "host_country": country,
        "climate": meta.get("climate", "unknown"),
        "altitude_m": meta.get("altitude_m"),
        "flags": flags,
        "home_advantage_xg": home_advantage,
        "heat_stress": heat,
        "altitude_stress": altitude_stress,
        "travel_stress": travel_stress
        or {
            "home_xg_delta": 0.0,
            "away_xg_delta": 0.0,
            "home_km": None,
            "away_km": None,
            "home_rest_hours": None,
            "away_rest_hours": None,
            "source": "no prior fixture in scope",
        },
    }


def refresh_context(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    travel_index = build_travel_index(fixtures)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "host_cities": HOST_CITIES,
        "fixtures": {
            fixture["match_id"]: context_for_fixture(
                fixture, travel_index.get(fixture["match_id"])
            )
            for fixture in fixtures
        },
    }
    write_json(DATA_DIR / "context.json", payload)
    return payload


def load_context() -> dict[str, Any]:
    return read_json(DATA_DIR / "context.json", {"fixtures": {}, "host_cities": HOST_CITIES})
