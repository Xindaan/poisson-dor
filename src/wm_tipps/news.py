from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from .io import read_json, write_json
from .news_sources import gdelt, rss
from .paths import DATA_DIR


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "injury": [
        "injury",
        "injured",
        "verletzung",
        "verletzt",
        "hamstring",
        "knee",
        "ankle",
        "muscle",
        "surgery",
    ],
    "illness": ["illness", "krank", "erkrank", "flu", "virus", "fever", "fieber"],
    "suspension": ["suspension", "suspended", "gesperrt", "ban", "yellow cards", "red card"],
    "form": ["form", "confidence", "scored", "goals", "winless", "serie", "lauf"],
    "coach": ["coach", "trainer", "manager", "tactics", "formation", "rotation"],
    "squad": ["squad", "kader", "call-up", "called up", "omitted", "nominiert", "roster", "rosters"],
    "expected_lineup": [
        "expected lineup",
        "probable lineup",
        "projected lineup",
        "predicted lineup",
        "predicted xi",
        "predicted xis",
        "starting xis",
        "who will start",
        "voraussichtliche aufstellung",
    ],
    "confirmed_lineup": ["confirmed lineup", "starting xi", "lineup confirmed", "startelf"],
    "weather": ["weather", "heat", "humidity", "rain", "wind", "wetter", "hitze"],
    "travel": [
        "travel",
        "journey",
        "flight",
        "reise",
        "jet lag",
        "travel distance",
        "visa",
        "ticket holders",
        "entry bond",
        "training camp",
    ],
    "pitch": ["pitch", "surface", "turf", "grass", "rasen", "platz"],
}

CRITICAL_KEYWORDS = [
    "ruled out",
    "out for season",
    "season-ending",
    "set to miss",
    "missing out",
    "left out",
    "omitted",
    "misses",
    "miss world cup",
    "miss the world cup",
    "verpasst",
    "faellt aus",
    "fällt aus",
    "not available",
    "hospital",
    "suspended",
    "gesperrt",
    "confirmed lineup",
    "starting xi",
]

IMPORTANT_KEYWORDS = [
    "doubt",
    "doubtful",
    "questionable",
    "fraglich",
    "training alone",
    "minor injury",
    "rotation",
    "rested",
]

CATEGORY_TTL_HOURS = {
    "confirmed_lineup": 4,
    "expected_lineup": 18,
    "weather": 18,
    "travel": 72,
    "injury": 336,
    "illness": 168,
    "suspension": 336,
}

WORLD_CUP_NEWS_EFFECTIVE_UNTIL = datetime(2026, 7, 20, 23, 59, 59, tzinfo=timezone.utc)

TOURNAMENT_OUT_KEYWORDS = [
    "ruled out of world cup",
    "ruled out of the world cup",
    "will miss the world cup",
    "miss the world cup",
    "miss world cup",
    "misses world cup",
    "missing out on the world cup",
    "world cup campaign",
    "out of world cup",
    "out of the world cup",
    "not available for the world cup",
    "miss out due to injury",
]

SQUAD_OMISSION_KEYWORDS = [
    "omitted",
    "left out",
    "does not include",
    "not include",
    "no room for",
    "misses out",
    "miss out",
]

NON_PLAYER_SUSPENSION_CONTEXT_KEYWORDS = [
    "suspended a requirement",
    "suspended requirement",
    "suspended visa",
    "suspended entry",
    "waives bonds",
    "ticket holders",
]

POSITIVE_PARTICIPATION_CONTEXT_KEYWORDS = [
    "positive fifa talks",
    "new assurance",
    "will feature",
    "edge closer",
]

NATIONAL_CONTEXT_KEYWORDS = [
    "world cup",
    "fifa",
    "national team",
    "international",
    "qualifier",
    "qualifying",
    "squad",
    "call-up",
    "called up",
    "roster",
    "rosters",
    "tournament",
    "friendly",
    "nations league",
    "wm",
    "weltmeisterschaft",
    "nationalmannschaft",
    "laenderteam",
    "länderteams",
    "kader",
    "nominiert",
]

CLUB_OR_LEAGUE_NOISE_KEYWORDS = [
    "premier league",
    "women's super league",
    "champions league",
    "europa league",
    "bundesliga",
    "la liga",
    "serie a",
    "promotion",
    "relegation",
    "race for europe",
    "club",
    "league title",
    "transfer",
    "contract",
]

NON_MENS_COMPETITION_NOISE_KEYWORDS = [
    "women's world cup",
    "womens world cup",
    "women's world cup qualifiers",
    "women's qualifier",
    "women's qualifiers",
    "women squad",
    "women's squad",
    "england women",
    "spain women",
    "lionesses",
    "women's super league",
    "uwcl",
]

RETROSPECTIVE_INTERVIEW_NOISE_KEYWORDS = [
    "i turned down",
    "i'd have done",
    "missing out on the usmnt job",
    "missing out on the job",
    "on missing out on",
    "people still abuse me",
    "reflects on",
    "looking back",
    "former boss",
    "former manager",
]

MODEL_RELEVANT_CATEGORIES = {
    "injury",
    "illness",
    "suspension",
    "squad",
    "expected_lineup",
    "confirmed_lineup",
    "weather",
    "travel",
    "pitch",
    "coach",
}

XG_IMPACT_CATEGORIES = {"injury", "illness", "suspension"}

PLAYER_NAME_STOPWORDS = {
    "coach",
    "cup",
    "fifa",
    "forward",
    "goalkeeper",
    "midfielder",
    "defender",
    "manager",
    "national",
    "squad",
    "team",
    "training",
    "wc",
    "world",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}

TEAM_MATCH_ALIASES: dict[str, list[str]] = {
    "Bosnia & Herzegovina": ["Bosnia and Herzegovina"],
    "Cape Verde": ["Cabo Verde"],
    "Curaçao": ["Curacao"],
    "Czech Republic": ["Czechia"],
    "DR Congo": ["Congo DR", "Democratic Republic of Congo", "DRC"],
    "Ivory Coast": ["Cote d Ivoire", "Cote d'Ivoire", "Côte d'Ivoire"],
    "Netherlands": ["Holland"],
    "South Korea": ["Korea Republic", "Republic of Korea"],
    "USA": ["United States", "USMNT"],
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def keyword_in_text(text: str, keyword: str) -> bool:
    normalized_keyword = normalize_text(keyword)
    if not normalized_keyword:
        return False
    if re.fullmatch(r"[\w\s-]+", normalized_keyword):
        pattern = r"(?<!\w)" + re.escape(normalized_keyword) + r"(?!\w)"
        return re.search(pattern, text) is not None
    return normalized_keyword in text


def any_keyword(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword_in_text(text, keyword) for keyword in keywords)


def url_context_text(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(str(url))
    decoded = unquote(
        " ".join(part for part in (parsed.netloc, parsed.path, parsed.query) if part)
    )
    return re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", " ", decoded)


def team_match_terms(team: str) -> list[str]:
    return [team, *TEAM_MATCH_ALIASES.get(team, [])]


def mentioned_teams(text: str, teams: Iterable[str]) -> list[str]:
    normalized = normalize_text(text)
    return [
        team
        for team in teams
        if any(keyword_in_text(normalized, term) for term in team_match_terms(team))
    ]


def is_stored_annotation(raw: dict[str, Any]) -> bool:
    return any(field in raw for field in ("relevance", "model_relevant", "freshness"))


# T-0148 (Folge von T-0139, forward-gated): Negations-Guard gegen False-Positive-
# Ausfaelle. "Henderson not ruled out despite breaking arm" (= Spieler VERFUEGBAR)
# matcht sonst das CRITICAL-Keyword "ruled out" und wird als Ausfall gewertet.
# WICHTIG: Der Negator muss DIREKT vor der Ausfall-Phrase stehen -- "X not training
# and ruled out" ist ein ECHTER Ausfall und darf NICHT herabgestuft werden. Und
# "not available" bleibt Ausfall (die Verneinung ist Teil der Absenz-Phrase, nicht
# ihre Umkehrung). NICHT backtestbar -> forward.
#
# AKTIV (11.7.): Bugfix (kein spekulativer Hebel). Isolierter Flag-Effekt = genau 1
# News-Item (Henderson "not ruled out" critical->context). Live-Tipp-Diff 2: gl-067
# England-Kroatien 0:1->1:0 (Erg 4:2 -> BESSER) und ko-099 Norwegen-England 1:0->0:1
# England (Markt 48%). Retrospektiv 1x BESSER, 0x SCHLECHTER. False = altes Verhalten.
NEWS_NEGATION_GUARD_ENABLED = True

# Ausfall-Phrasen, die sich unter DIREKTER Verneinung zu Verfuegbarkeit umkehren.
_NEGATED_ABSENCE_RE = re.compile(
    r"\b(?:not|no longer|never|nicht)\s+(?:been\s+|yet\s+|be\s+|going to\s+)?"
    r"(?:ruled out|out of (?:the )?world cup|out of the tournament|set to miss|"
    r"sidelined|missing out)\b"
    r"|\b(?:won't|will not|wont|does not|doesn't)\s+miss\b"
)
# Klare Verfuegbarkeits-Aussagen (ohne Negation).
AVAILABILITY_POSITIVE_KEYWORDS = [
    "avoids injury",
    "avoids a ban",
    "avoids ban",
    "avoids suspension",
    "cleared to play",
    "passed fit",
    "declared fit",
    "fit to play",
    "back in training",
    "returns to training",
    "in contention",
]


def availability_positive(normalized: str) -> bool:
    """True, wenn der (normalisierte) Text den Spieler als VERFUEGBAR meldet."""
    if _NEGATED_ABSENCE_RE.search(normalized):
        return True
    return any_keyword(normalized, AVAILABILITY_POSITIVE_KEYWORDS)


def classify_text(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    categories = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any_keyword(normalized, keywords):
            categories.append(category)
    non_player_suspension = any_keyword(
        normalized,
        NON_PLAYER_SUSPENSION_CONTEXT_KEYWORDS,
    )
    if non_player_suspension:
        categories = [category for category in categories if category != "suspension"]
    if any_keyword(normalized, CRITICAL_KEYWORDS):
        severity = "critical"
    elif any_keyword(normalized, IMPORTANT_KEYWORDS):
        severity = "important"
    elif categories:
        severity = "context"
    else:
        severity = "noise"
    if non_player_suspension and severity == "critical":
        severity = "context" if categories else "noise"
    if (
        severity == "important"
        and any_keyword(normalized, POSITIVE_PARTICIPATION_CONTEXT_KEYWORDS)
        and not set(categories) & XG_IMPACT_CATEGORIES
    ):
        severity = "context"
    # T-0148: eine Verfuegbarkeits-Meldung ("not ruled out", "cleared to play") ist
    # KEIN Ausfall -- vom xG-wirksamen critical/important auf context herabstufen.
    if (
        NEWS_NEGATION_GUARD_ENABLED
        and severity in ("critical", "important")
        and availability_positive(normalized)
    ):
        severity = "context"
    return {"categories": categories or ["general"], "severity": severity}


def assess_relevance(
    text: str,
    *,
    categories: list[str],
    severity: str,
    teams: list[str],
) -> dict[str, Any]:
    normalized = normalize_text(text)
    has_team = bool(teams)
    has_national_context = any_keyword(normalized, NATIONAL_CONTEXT_KEYWORDS)
    has_model_category = bool(set(categories) & MODEL_RELEVANT_CATEGORIES)
    has_hard_tournament_status = severity_rank(severity) >= 2 and any_keyword(
        normalized,
        [*TOURNAMENT_OUT_KEYWORDS, *SQUAD_OMISSION_KEYWORDS],
    )
    is_action_signal = severity_rank(severity) >= 2 and has_model_category
    if not has_team:
        return {
            "relevance": "low",
            "relevance_reason": "Kein WM-2026-Fixture-Team erkannt.",
            "model_relevant": False,
        }
    is_club_or_league_noise = (
        any_keyword(normalized, CLUB_OR_LEAGUE_NOISE_KEYWORDS)
        and not has_national_context
        and not is_action_signal
    )
    if is_club_or_league_noise:
        return {
            "relevance": "low",
            "relevance_reason": "Club-/Ligakontext ohne WM- oder Nationalteam-Bezug.",
            "model_relevant": False,
        }
    if any_keyword(normalized, NON_MENS_COMPETITION_NOISE_KEYWORDS):
        return {
            "relevance": "low",
            "relevance_reason": "Frauen-/Nicht-Maenner-Kontext statt WM-2026-Maennerteam.",
            "model_relevant": False,
        }
    if not has_model_category and any_keyword(normalized, RETROSPECTIVE_INTERVIEW_NOISE_KEYWORDS):
        return {
            "relevance": "low",
            "relevance_reason": "Retrospektives Interview ohne aktuellen Team-Impact.",
            "model_relevant": False,
        }
    if has_national_context and has_team:
        return {
            "relevance": "high" if has_model_category else "medium",
            "relevance_reason": "Nationalteam-/WM-Kontext erkannt.",
            "model_relevant": has_model_category or has_hard_tournament_status,
        }
    if is_action_signal and has_team:
        return {
            "relevance": "medium",
            "relevance_reason": "Harte Team-News ohne expliziten WM-Kontext.",
            "model_relevant": True,
        }
    return {
        "relevance": "low" if severity == "noise" else "medium",
        "relevance_reason": "Nur schwacher oder indirekter Teambezug.",
        "model_relevant": severity != "noise" and has_model_category and has_team,
    }


def normalized_url_key(url: Any) -> str:
    parsed = urlparse(str(url))
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.startswith("utm_") and not key.startswith("at_")
    ]
    return urlunparse(parsed._replace(query=urlencode(kept_query), fragment=""))


def fingerprint(item: dict[str, Any]) -> str:
    source = (
        normalized_url_key(item.get("url"))
        if item.get("url")
        else f"{item.get('title', '')}|{item.get('published_at', '')}"
    )
    return hashlib.sha1(normalize_text(source).encode("utf-8")).hexdigest()[:16]


def dedupe_key(item: dict[str, Any]) -> str:
    if item.get("url"):
        return fingerprint(item)
    return str(item.get("id") or fingerprint(item))


def dedupe_news(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for raw in items:
        item = dict(raw)
        item["id"] = item.get("id") or fingerprint(item)
        key = dedupe_key(item)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
        else:
            if dedupe_rank(item) > dedupe_rank(existing):
                by_key[key] = item
    return sorted(by_key.values(), key=lambda row: row.get("published_at", ""), reverse=True)


def severity_rank(severity: str) -> int:
    return {"critical": 3, "important": 2, "context": 1, "noise": 0}.get(severity, 0)


def reliability_rank(reliability: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(reliability), 0)


def model_signal_rank(item: dict[str, Any]) -> int:
    categories = set(item.get("categories") or [])
    score = 0
    if categories & {"injury", "illness", "suspension"}:
        score += 4
    if categories & MODEL_RELEVANT_CATEGORIES:
        score += 2
    if item.get("model_relevant"):
        score += 1
    if item.get("effective_until"):
        score += 1
    if item.get("match_ids"):
        score += 1
    return score


def dedupe_rank(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        severity_rank(str(item.get("severity", "noise"))),
        reliability_rank(str(item.get("reliability", "medium"))),
        model_signal_rank(item),
    )


def annotate_news(items: Iterable[dict[str, Any]], teams: Iterable[str] = ()) -> list[dict[str, Any]]:
    team_list = list(teams)
    annotated = []
    for raw in items:
        visible_text = " ".join(str(raw.get(field, "")) for field in ("title", "summary", "text"))
        context_text = " ".join(
            part for part in (visible_text, url_context_text(str(raw.get("url", "")))) if part
        )
        classified = classify_text(context_text)
        mentioned = mentioned_teams(context_text, team_list)
        preserve_explicit_classification = not is_stored_annotation(raw) or bool(
            raw.get("effective_until")
        )
        item = {
            "source": raw.get("source", "manual"),
            "title": raw.get("title", ""),
            "summary": raw.get("summary", ""),
            "url": raw.get("url", ""),
            "published_at": raw.get("published_at", ""),
            "teams": raw.get("teams") or mentioned,
            "players": raw.get("players", []),
            "categories": (
                raw.get("categories")
                if preserve_explicit_classification and raw.get("categories")
                else classified["categories"]
            ),
            "severity": (
                raw.get("severity")
                if preserve_explicit_classification and raw.get("severity")
                else classified["severity"]
            ),
            "reliability": raw.get("reliability", "medium"),
            "impact": raw.get("impact", ""),
        }
        if raw.get("effective_until"):
            item["effective_until"] = raw.get("effective_until")
        if raw.get("match_ids"):
            item["match_ids"] = list(raw.get("match_ids") or [])
        relevance = assess_relevance(
            context_text,
            categories=list(item["categories"]),
            severity=str(item["severity"]),
            teams=list(item["teams"] or []),
        )
        if relevance["relevance"] == "low" and item["severity"] in {"critical", "important"}:
            item["severity"] = "noise"
            item["categories"] = ["general"]
        item.update(relevance)
        item["id"] = raw.get("id") or fingerprint(item)
        item["freshness"] = freshness_status(item)
        annotated.append(item)
    return dedupe_news(annotated)


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def tournament_long_signal(item: dict[str, Any]) -> bool:
    if severity_rank(str(item.get("severity", "noise"))) < 2:
        return False
    categories = set(item.get("categories") or [])
    if not categories & {"injury", "illness", "suspension", "squad"}:
        return False
    text = normalize_text(
        " ".join(str(item.get(field, "")) for field in ("title", "summary", "impact", "url"))
    )
    if not keyword_in_text(text, "world cup"):
        return False
    if categories & {"injury", "illness", "suspension"} and any_keyword(
        text, TOURNAMENT_OUT_KEYWORDS
    ):
        return True
    return "squad" in categories and any_keyword(text, SQUAD_OMISSION_KEYWORDS)


def freshness_status(item: dict[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    published = item.get("published_at")
    if not published:
        return "unknown"
    parsed = parse_timestamp(published)
    if parsed is None:
        return "unknown"
    effective_until = parse_timestamp(item.get("effective_until"))
    if effective_until is not None:
        return "fresh" if now <= effective_until else "stale"
    if tournament_long_signal(item):
        return "fresh" if now <= WORLD_CUP_NEWS_EFFECTIVE_UNTIL else "stale"
    categories = item.get("categories") or ["general"]
    ttl_values = [CATEGORY_TTL_HOURS.get(category, 72) for category in categories]
    if "squad" in categories and severity_rank(str(item.get("severity", "noise"))) >= 2:
        ttl_values = [
            336 if category == "squad" else ttl for category, ttl in zip(categories, ttl_values)
        ]
    ttl = min(ttl_values)
    if now - parsed > timedelta(hours=ttl):
        return "stale"
    return "fresh"


def load_manual_news(teams: Iterable[str]) -> list[dict[str, Any]]:
    return annotate_news(read_json(DATA_DIR / "manual_news.json", []), teams)


# GDELT bewusst weggelassen: lieferte beim Test-Lauf 2026-05-10 fuer alle
# 48 Teams 0 Items und brauchte 7+ Min wegen sequenzieller Calls. Aufnehmen
# via sources=[..., gdelt] sobald Query oder Rate-Limit-Behandlung steht
# (T-0011). RSS bleibt schnell und liefert.
DEFAULT_LIVE_SOURCES = (rss,)


def _collect_from_source(
    source: Any,
    teams: list[str],
    items: list[dict[str, Any]],
    *,
    per_team_limit: int,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source": getattr(source, "NAME", None) or getattr(source, "__name__", "unknown"),
        "last_seen_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        raw = source.collect(teams, per_team_limit=per_team_limit)
        annotated = annotate_news(raw, teams)
        items.extend(annotated)
        record.update(
            items_total=len(annotated),
            items_fresh=sum(1 for item in annotated if item.get("freshness") == "fresh"),
            status="ok" if annotated else "empty",
        )
    except Exception as exc:  # noqa: BLE001 - explizit alles fangen, damit Live-Refresh nicht crashed.
        record.update(
            items_total=0,
            items_fresh=0,
            status="error",
            error=str(exc),
        )
    return record


MAX_PERSISTED_ITEMS = 500


def cap_news_with_manual(
    deduped: list[dict[str, Any]],
    manual: Iterable[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    """Begrenzt die News-Liste auf max_items, garantiert aber, dass die
    kuratierten manual_news-Items NIE aus dem Cap fallen. Sonst verdraengen
    >=max_items RSS-Items die persistierten Ausfaelle (De Ligt, Ben White,
    Brasilien-Trio ...) und das Modell ignoriert sie still."""
    capped = list(deduped[:max_items])
    present = {dedupe_key(item) for item in capped}
    for manual_item in manual:
        key = dedupe_key(manual_item)
        if key not in present:
            capped.append(manual_item)
            present.add(key)
    return capped


def refresh_news(
    teams: Iterable[str],
    *,
    live: bool = False,
    per_team_limit: int = 6,
    sources: Iterable[Any] | None = None,
    keep_existing: bool = True,
    max_items: int = MAX_PERSISTED_ITEMS,
) -> dict[str, Any]:
    teams_list = list(teams)
    existing = read_json(DATA_DIR / "news_items.json", {"items": [], "data_quality": []})
    # Existing News wiederverwenden -- sonst killt jeder watch-Cycle ohne
    # --live-news die ueber Tage gesammelten Items. Freshness wird neu
    # berechnet und Relevanz neu annotiert, weil Filterregeln sich aendern.
    if keep_existing:
        items: list[dict[str, Any]] = annotate_news(
            [item for item in existing.get("items", []) if isinstance(item, dict)],
            teams_list,
        )
    else:
        items = []
    items.extend(load_manual_news(teams_list))

    quality: list[dict[str, Any]]
    if live:
        quality = []
        active_sources = sources if sources is not None else DEFAULT_LIVE_SOURCES
        for source in active_sources:
            quality.append(
                _collect_from_source(source, teams_list, items, per_team_limit=per_team_limit)
            )
    else:
        # Bei watch-Cycles ohne --live-news behalten wir den letzten
        # Quality-Snapshot, damit das Dashboard nicht flackert.
        quality = list(existing.get("data_quality", []) or [])

    deduped = cap_news_with_manual(
        dedupe_news(items), load_manual_news(teams_list), max_items
    )
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": deduped,
        "data_quality": quality,
    }
    write_json(DATA_DIR / "news_items.json", payload)
    return payload


def news_for_fixture(fixture: dict[str, Any], news_items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    teams = {fixture.get("home_team"), fixture.get("away_team")}
    fixture_match_id = fixture.get("match_id")
    rows = []
    for item in news_items:
        scoped_match_ids = item.get("match_ids") or []
        if scoped_match_ids and fixture_match_id not in scoped_match_ids:
            continue
        if teams.intersection(set(item.get("teams") or [])):
            rows.append(item)
    return sorted(rows, key=lambda item: severity_rank(item.get("severity", "noise")), reverse=True)


def is_model_relevant_news(item: dict[str, Any]) -> bool:
    return bool(item.get("model_relevant", item.get("relevance") != "low"))


# Pauschale xG-Buckets pro Impact-News (Fallback ohne Player-Pool-Match).
ATTACK_DELTA_CRITICAL = -0.18
ATTACK_DELTA_IMPORTANT = -0.07
DEFENSE_DELTA_CRITICAL = 0.10
DEFENSE_DELTA_IMPORTANT = 0.04
# Baseline-goal_share, gegen die individuell skaliert wird (entspricht dem
# player_pool-Default fuer Teams ohne Coverage). Top-Scorer wie Kane (0.70)
# wirken staerker, Backups (0.15) schwaecher als die Pauschale.
PLAYER_NEWS_BASELINE_SHARE = 0.4
# Skalierungsfaktor wird geklammert, damit die Severity-Proportion
# (critical : important) erhalten bleibt -- statt den absoluten Wert zu
# klammern, was important-News fuer Backups faelschlich verstaerken wuerde.
PLAYER_SCALE_MIN = 0.4
PLAYER_SCALE_MAX = 1.75

# T-0040: optionale position/role-Felder pro player_pool-Eintrag.
# Verteidiger/Torwart lenken den Ausfall auf die eigene Defensive (Gegner
# trifft mehr) statt auf die eigene Offensive. Backups wirken kaum.
DEFENSIVE_POSITIONS = {"GK", "DF", "CB", "LB", "RB", "LWB", "RWB", "WB", "SW"}
ATTACKING_POSITIONS = {
    "ST", "CF", "FW", "SS", "LW", "RW", "AM", "CAM", "MF", "CM", "DM", "LM", "RM", "W",
}
ROLE_FACTORS = {"starter": 1.0, "rotation": 0.6, "backup": 0.3}
# T-0041: Drop-Off zur Ersatzbank -- ein klarer Top-Scorer ohne
# gleichwertigen Ersatz wiegt schwerer. Bonus bis +0.3 auf den Faktor.
DROP_OFF_MAX_BONUS = 0.3


def _ascii_name_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


def _player_name_tokens(player: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for source in [player.get("name", ""), *player.get("source_aliases", [])]:
        for part in re.split(r"[\s'’-]+", str(source)):
            token = _ascii_name_token(part)
            if len(token) >= 3:
                tokens.add(token)
    return tokens


def player_profile_from_pool(
    team: str,
    subject_keys: Iterable[str],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None,
) -> dict[str, Any] | None:
    """Profil des in der News genannten Spielers: goal_share + optional
    position/role + Drop-Off-Faktor (T-0040/T-0041).

    Liefert None, wenn kein Pool/Team/Namensmatch -> Pauschale greift.
    """
    if not player_pool:
        return None
    roster = player_pool.get(team) or []
    if not roster:
        return None
    subjects = {_ascii_name_token(key) for key in subject_keys}
    subjects = {token for token in subjects if len(token) >= 3}
    if not subjects:
        return None
    matched: Mapping[str, Any] | None = None
    matched_share = -1.0
    for player in roster:
        if subjects & _player_name_tokens(player):
            try:
                share = float(player.get("goal_share", 0.0))
            except (TypeError, ValueError):
                continue
            if share > matched_share:
                matched_share = share
                matched = player
    if matched is None:
        return None
    # T-0041: Drop-Off aus dem Abstand zur naechstbesten Option im Kader.
    other_shares = []
    for player in roster:
        if player is matched:
            continue
        try:
            other_shares.append(float(player.get("goal_share", 0.0)))
        except (TypeError, ValueError):
            continue
    gap = matched_share - (max(other_shares) if other_shares else 0.0)
    drop_off = 1.0 + max(0.0, min(DROP_OFF_MAX_BONUS, gap))
    position = str(matched.get("position") or "").strip().upper() or None
    role = str(matched.get("role") or "").strip().lower() or None
    return {
        "goal_share": matched_share,
        "position": position,
        "role": role,
        "drop_off": round(drop_off, 4),
    }


def player_weight_from_pool(
    team: str,
    subject_keys: Iterable[str],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None,
) -> float | None:
    """goal_share des genannten Spielers (Kompat-Wrapper um das Profil)."""
    profile = player_profile_from_pool(team, subject_keys, player_pool)
    return profile["goal_share"] if profile else None


# Multi-Team-Sammelartikel ("Timber out ... while Brazil's Neymar making
# good progress"): die item-weite kritische Severity darf nicht auf ein
# Team angewandt werden, dessen Nennung nur positive Recovery-Sprache hat.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?:,\s+)?(?:\bwhile\b|\bwhilst\b|\bbut\b|\bhowever\b|\bmeanwhile\b|;|—|–)\s+|\.\s+",
    re.IGNORECASE,
)
INJURY_NEGATIVE_PHRASES = (
    "ruled out", "out of", "out for", "sidelined", "will miss", "set to miss",
    "miss the", "out injured", "injury blow", "blow for", "withdraw",
    "withdrawn", "withdraws", "pulls out", "pulled out", "won't play",
    "will not play", "season over", "tournament over", "season-ending",
    "out with", "doubt for", "axed", "dropped",
)
INJURY_RECOVERY_PHRASES = (
    "good progress", "making progress", "make progress", "makes progress",
    "back in training", "return to training", "set to return",
    "nearing a return", "in contention", "fit again", "passed fit",
    "declared fit", "available again", "on the mend", "fitness boost",
    "stepped up his recovery", "step up his recovery",
)
# Affirmative Verletzungs-/Ausfall-Marker OHNE das nackte Wort "injury"
# (das steht auch in Recovery-Saetzen wie "progress from injury"). Faengt
# echte Verletzungen, die keine explizite Ausfall-Phrase haben (z.B.
# "picks up a knock"). Recovery-only-Klauseln werden vorher ausgesiebt.
INJURY_AFFLICTION_KEYWORDS = (
    "injured", "knock", "strain", "strained", "hamstring", "groin", "calf",
    "ankle", "acl", "torn", "tear", "fracture", "fractured", "broken",
    "sidelined", "limped", "limp off", "in doubt", "a doubt", "doubtful",
    "stretchered", "surgery", "operation", "suspended", "suspension",
    "banned", "red card", "ill ", "illness",
)


def _team_news_is_recovery_only(team: str, item: Mapping[str, Any]) -> bool:
    """True, wenn die Nennung DIESES Teams im News-Text nur positive
    Recovery-Sprache hat und KEINE starke Negativ-/Ausfall-Phrase --
    dann ist der kritische Ausfall nicht der dieses Teams (z.B.
    'Brazil's Neymar making good progress' im Timber-Out-Sammelartikel).
    Negativ schlaegt Recovery (echter Ausfall mit Reha-Kontext bleibt).
    """
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    team_lower = str(team).lower()
    clauses = [clause for clause in _CLAUSE_SPLIT_RE.split(text) if team_lower in clause.lower()]
    if not clauses:
        return False  # Team nicht im Text gefunden -> nicht unterdruecken (kein Risiko).
    joined = " ".join(clauses).lower()
    has_negative = any(phrase in joined for phrase in INJURY_NEGATIVE_PHRASES)
    has_recovery = any(phrase in joined for phrase in INJURY_RECOVERY_PHRASES)
    return has_recovery and not has_negative


def _team_reference_terms(team: str, player_pool: Mapping[str, Any] | None = None) -> set[str]:
    """Begriffe, an denen eine Klausel als 'ueber dieses Team' erkannt
    wird: Teamname + Aliasse, plus Pool-Spielernamen (Token >= 4 Zeichen).
    """
    terms = {str(term).lower() for term in team_match_terms(team)}
    if player_pool:
        for player in player_pool.get(team, []) or []:
            names = [str(player.get("name", ""))]
            names.extend(str(alias) for alias in (player.get("source_aliases") or []))
            for name in names:
                for token in name.lower().replace("-", " ").replace("'", " ").split():
                    if len(token) >= 4:
                        terms.add(token)
    return {term for term in terms if term}


def _clauses_referencing_team(
    team: str,
    item: Mapping[str, Any],
    player_pool: Mapping[str, Any] | None = None,
) -> list[str]:
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    terms = _team_reference_terms(team, player_pool)
    patterns = [re.compile(r"\b" + re.escape(term) + r"\b") for term in terms]
    return [
        clause
        for clause in _CLAUSE_SPLIT_RE.split(text)
        if any(pattern.search(clause.lower()) for pattern in patterns)
    ]


def _clause_has_injury_signal(clause: str) -> bool:
    """True, wenn die Klausel einen echten Verletzungs-/Ausfall-Bezug
    traegt. Negativ-Phrase schlaegt alles; reine Recovery-Klausel zaehlt
    NICHT; sonst greifen die Affliction-Keywords.
    """
    low = clause.lower()
    if any(phrase in low for phrase in INJURY_NEGATIVE_PHRASES):
        return True
    if any(phrase in low for phrase in INJURY_RECOVERY_PHRASES):
        return False
    return any(keyword in low for keyword in INJURY_AFFLICTION_KEYWORDS)


def team_is_injury_subject(
    team: str,
    item: Mapping[str, Any],
    player_pool: Mapping[str, Any] | None = None,
) -> bool:
    """Wurzel-Attribution: ist DIESES Team das tatsaechlich negativ
    betroffene Team dieses Impact-Items?

    - Einzel-Team-Item (genau ein genanntes Team): eindeutig -> wie T-0063
      nur reine Recovery-Items aussieben (kein Mehrdeutigkeitsrisiko, daher
      keine strengere Klausel-Pruefung, um echte Ausfaelle nicht zu
      verlieren, wenn Land und Verletzungsphrase in getrennten Saetzen
      stehen).
    - Multi-Team-Sammelartikel (Risikoklasse): nur werten, wenn eine das
      Team referenzierende Klausel ein Verletzungssignal traegt. Recovery-
      only ('Neymar making good progress') und rein inzidentelle Nennungen
      (Team getaggt, aber in keiner Text-Klausel) werden nicht zugeordnet.
    """
    teams = item.get("teams") or []
    if len(teams) <= 1:
        return not _team_news_is_recovery_only(team, item)
    clauses = _clauses_referencing_team(team, item, player_pool)
    if not clauses:
        return False  # inzidentell im Sammelartikel -> nicht diesem Team
    return any(_clause_has_injury_signal(clause) for clause in clauses)


# Spieloffizielle (Schiedsrichter/Assistent/VAR) sind keine Teamspieler.
# Eine 'injury'/'suspension'-News ueber einen Offiziellen darf keinen
# xG-Impact ausloesen -- sonst trifft sie BEIDE getaggten Teams als
# Pauschal-Ausfall (Bug: 'Injured referee Oliver to miss World Cup match'
# zog Elfenbeinkueste UND Ecuador je -0.18 Attack). Schiedsrichter-Tendenz
# ist ein separates, noch offenes Signal (T-0042).
MATCH_OFFICIAL_TERMS = (
    "referee", "linesman", "assistant referee", "fourth official",
    "var official", "match official", "officiating", "officials",
    "schiedsrichter", "linienrichter", "unparteiische", "unparteiischer",
)


def _is_match_official_news(item: Mapping[str, Any]) -> bool:
    """True, wenn das Ausfall-Subjekt ein Spieloffizieller ist und kein
    benannter Teamspieler -- dann kein xG-Impact. Konservativ: nur wenn
    KEIN konkreter Spieler genannt ist (players leer), damit echte
    Spielerausfaelle, die einen Offiziellen nur beilaeufig erwaehnen, nicht
    faelschlich gefiltert werden."""
    if item.get("players"):
        return False  # konkreter Spieler benannt -> echter Spielerbezug
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(term in text for term in MATCH_OFFICIAL_TERMS)


# Einreise-/Vorbereitungs-Stoerungs-Phrasen (T-0066/T-0067), zwei Stufen.
# STRONG = eindeutige team-weite Anreise-/<48h-Stoerung. MILD = belegte
# Visa-/Einreise-Friktion (auch Staff), die die Vorbereitung stoert, aber
# nicht klar die ganze Anreise. Hochpraezise; Fan-/Ticket-/Presse-Kontext
# wird ausgeschlossen (siehe _clause_is_fan_context), damit neutrale
# Reise-News keinen xG-Malus ausloesen.
ENTRY_DISRUPTION_STRONG_PHRASES = (
    "arrive on matchday", "arriving on matchday", "matchday arrival",
    "arrive on the day of", "arriving on the day of",
    "only allowed to enter", "allowed to enter on matchday",
    "enter on the day", "only enter on match", "enter only on match",
    "less than 48 hours", "fewer than 48 hours", "under 48 hours before",
    "without the 48", "denied the 48", "stripped of the 48",
    # Deutsch
    "nur an spieltagen", "nur an den spieltagen", "nur am spieltag",
    "darf erst am spieltag", "erst am spieltag ein",
)
ENTRY_DISRUPTION_MILD_PHRASES = (
    "denied entry", "refused entry", "barred from entering",
    "blocked from entering", "turned away at", "detained at",
    "held at the border", "stranded at the",
    "denied visas", "refused visas", "visas denied", "visa denied",
    "visas refused", "visa refused", "visa rejected", "denied a visa",
    "refused a visa", "visa was denied", "without visas", "without a visa",
    "staff blocked", "officials denied", "support staff",
    # Deutsch
    "visum verweigert", "visa verweigert", "kein visum",
    "einreise verweigert", "ohne visum", "visa abgelehnt",
)
# Kontext, der eine Einreise-Phrase NICHT zum Team-Signal macht (Fans,
# Tickets, Presse). Nur ausschliessen, wenn KEIN Team-/Kader-Bezug daneben.
ENTRY_FAN_CONTEXT_TERMS = (
    "fans", "supporters", "ticket holder", "ticket-holder", "ticketholders",
    "ticket holders", "journalist", "reporter", "spectator", "tourist",
    "away support", "travelling support", "zuschauer", "anhaenger",
)
ENTRY_SQUAD_CONTEXT_TERMS = (
    "team", "squad", "players", "player", "delegation", "staff", "official",
    "officials", "coach", "manager", "national team", "federation",
    "mannschaft", "kader", "spieler", "betreuer", "nationalteam",
)
# Gastgeber 2026: koennen kein US-Einreiseproblem haben (Ziel/Akteur, nicht
# Betroffene). Ihr Name taucht in Einreise-Artikeln ueber Gastteams als
# Zielland auf ("Iran denied visas to enter the US") -> sonst Falsch-Positiv.
HOST_NATION_TEAMS = frozenset({"USA", "United States", "Mexico", "Canada"})


def _clause_is_fan_context(clause_low: str) -> bool:
    return any(term in clause_low for term in ENTRY_FAN_CONTEXT_TERMS) and not any(
        term in clause_low for term in ENTRY_SQUAD_CONTEXT_TERMS
    )


def entry_disruption_severity(
    team: str,
    item: Mapping[str, Any],
    player_pool: Mapping[str, Any] | None = None,
) -> str | None:
    """Erkennt eine Einreise-/Vorbereitungs-Stoerung fuer DIESES Team in
    einer News (T-0066/T-0067). Nutzt dieselbe Klausel-Attribution wie
    `team_is_injury_subject` (Multi-Team-Sammelartikel werden nicht falsch
    zugeordnet) und schliesst Fan-/Ticket-/Presse-Klauseln aus.

    Bewusst KEIN `is_model_relevant_news`-Gate: Einreise-Meldungen stuft der
    generische Klassifizierer oft als noise/context ein -- die hochpraezise
    Phrase selbst (in einer team-referenzierenden, nicht-Fan-Klausel) ist das
    Relevanzsignal. Liefert 'strong' bei klarer Anreise-/<48h-Phrase, 'mild'
    bei Visa-/Einreise-Friktion, sonst None.
    """
    if team in HOST_NATION_TEAMS:
        return None  # Gastgeber: Zielland, nicht Betroffene -> kein Signal.
    if item.get("freshness") == "stale":
        return None
    teams = item.get("teams") or []
    clauses = _clauses_referencing_team(team, item, player_pool)
    if not clauses:
        if len(teams) > 1:
            return None  # inzidentell im Sammelartikel
        clauses = [f"{item.get('title', '')} {item.get('summary', '')}"]
    found_strong = False
    found_mild = False
    for clause in clauses:
        low = clause.lower()
        if _clause_is_fan_context(low):
            continue
        if any(phrase in low for phrase in ENTRY_DISRUPTION_STRONG_PHRASES):
            found_strong = True
        elif any(phrase in low for phrase in ENTRY_DISRUPTION_MILD_PHRASES):
            found_mild = True
    if found_strong:
        return "strong"
    if found_mild:
        return "mild"
    return None


def relevant_impact_items(
    team: str,
    items: Iterable[dict[str, Any]],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Die xG-wirksamen News-Items fuer ein Team: frisch, modellrelevant,
    Impact-Kategorie (injury/illness/suspension), severity >= important,
    kein Schiedsrichter-Item, dedupliziert und auf das wirklich betroffene
    Team wurzel-attribuiert (siebt Recovery-only-/inzidentelle Nennungen).

    Liefert (deduped_impact_items, raw_impact_items). Gemeinsamer Pfad fuer
    `team_news_impact` und `team_xg_news_subject_keys` (kein Drift)."""
    relevant = [
        item
        for item in items
        if team in (item.get("teams") or [])
        and item.get("freshness") != "stale"
        and is_model_relevant_news(item)
    ]
    impact_items = [
        item
        for item in relevant
        if set(item.get("categories") or []) & XG_IMPACT_CATEGORIES
        and severity_rank(item.get("severity", "noise")) >= 2
        and not _is_match_official_news(item)
    ]
    deduped = dedupe_impact_items(team, impact_items)
    deduped = [
        item for item in deduped
        if team_is_injury_subject(team, item, player_pool)
    ]
    return deduped, impact_items


def team_xg_news_subject_keys(
    team: str,
    items: Iterable[dict[str, Any]],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> set[str]:
    """Normalisierte Subjekt-Keys (Nachnamen) der Spieler, die bereits einen
    xG-wirksamen News-Effekt fuer das Team ausloesen. T-0113 nutzt das, um
    einen XI-Ausfall NICHT doppelt zu werten, wenn der Spieler ohnehin schon
    per News im xG haengt."""
    deduped, _ = relevant_impact_items(team, items, player_pool)
    keys: set[str] = set()
    for item in deduped:
        keys.update(player_subject_keys(team, item))
    return keys


def team_news_impact(
    team: str,
    items: Iterable[dict[str, Any]],
    player_pool: Mapping[str, list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    deduped_impact_items, impact_items = relevant_impact_items(team, items, player_pool)
    relevant = [
        item
        for item in items
        if team in (item.get("teams") or [])
        and item.get("freshness") != "stale"
        and is_model_relevant_news(item)
    ]
    critical = sum(1 for item in deduped_impact_items if item.get("severity") == "critical")
    important = sum(1 for item in deduped_impact_items if item.get("severity") == "important")
    lineup = any("confirmed_lineup" in (item.get("categories") or []) for item in relevant)

    attack_delta = 0.0
    defense_delta = 0.0
    individual_hits = 0
    defensive_routed = 0
    for item in deduped_impact_items:
        severity = item.get("severity")
        if severity == "critical":
            base_attack = ATTACK_DELTA_CRITICAL
            base_defense = DEFENSE_DELTA_CRITICAL
        elif severity == "important":
            base_attack = ATTACK_DELTA_IMPORTANT
            base_defense = DEFENSE_DELTA_IMPORTANT
        else:
            continue
        profile = player_profile_from_pool(team, player_subject_keys(team, item), player_pool)
        if profile is None:
            # Kein Pool-Match -> unveraenderte Pauschale (kein Regressionsrisiko).
            attack_delta += base_attack
            defense_delta += base_defense
            continue
        individual_hits += 1
        share_factor = min(PLAYER_SCALE_MAX, max(PLAYER_SCALE_MIN, profile["goal_share"] / PLAYER_NEWS_BASELINE_SHARE))
        role_factor = ROLE_FACTORS.get(profile["role"], 1.0)
        scale = share_factor * role_factor * profile["drop_off"]
        position = profile["position"]
        if position in DEFENSIVE_POSITIONS:
            # Verteidiger/Torwart aus -> eigene Defensive schwaecher,
            # Offensive kaum betroffen.
            defense_delta += base_defense * scale
            defensive_routed += 1
        elif position in ATTACKING_POSITIONS:
            # Bekannter Offensivspieler -> nur Offensive, kein Gegner-Boost.
            attack_delta += base_attack * scale
        else:
            # Position unbekannt -> B1-Verhalten: Offensive skaliert,
            # Defensive pauschal.
            attack_delta += base_attack * scale
            defense_delta += base_defense
    return {
        "critical": critical,
        "important": important,
        "raw_impact_items": len(impact_items),
        "deduped_impact_items": len(deduped_impact_items),
        "individual_scaled_items": individual_hits,
        "defensive_routed_items": defensive_routed,
        "lineup_confirmed": lineup,
        "attack_delta": max(-0.55, round(attack_delta, 4)),
        "defense_delta": min(0.35, round(defense_delta, 4)),
    }


# T-0139 (forward-gated, default AUS): Der bestehende `impact_dedupe_key` WOLLTE
# pro Spieler-Subjekt deduplizieren, joint aber ALLE Subject-Keys zu einem String.
# `player_subject_keys` raet Namen per Grossbuchstaben-Regex und liefert Rauschen
# ("Can England replace Jordan Henderson" -> ['can','henderson']; "... surgery in
# Mexico" -> ['henderson','mexico']). Ein einziges abweichendes Rausch-Token
# sprengt den Key -> derselbe Ausfall wird mehrfach bestraft (8.7., ko-099:
# Henderson doppelt, England attack_delta 3x-0.18=-0.54 statt -0.36).
# Fix: Items mergen, die sich mindestens EIN nicht-triviales Subjekt-Token teilen.
# Fehl-Merges durch Rauschen wirken konservativ (weniger Malus) -- die sichere
# Richtung gegenueber der bisherigen Ueberbestrafung. NICHT backtestbar (keine
# historischen News) -> forward-validiert.
#
# AKTIV (8.7.): Anders als der spekulative Hebel T-0136 ist das ein BUGFIX. Der
# gemessene Live-Tipp-Diff (5 Tipps) ist retrospektiv auf gespielten Spielen
# **2x BESSER, 0x SCHLECHTER, 2x neutral** (gl-067 England-Kroatien und ko-094
# USA-Belgien werden korrekt, beide vorher durch aufgeblaehten Malus gefadet);
# offen ko-099 Norwegen-England 1:0 -> 0:1 (deckt sich mit dem Markt: England 51%).
# Auf False setzen stellt das (fehlerhafte) Alt-Verhalten wieder her.
NEWS_SUBJECT_DEDUPE_ENABLED = True

# Tokens, die die Namens-Heuristik faelschlich als Nachnamen liefert und die
# deshalb NICHT als Merge-Schluessel taugen.
SUBJECT_DEDUPE_STOPWORDS = frozenset(
    {
        "can", "will", "how", "why", "what", "who", "when", "where",
        "the", "a", "an", "is", "are", "was", "were", "out", "in",
        "new", "latest", "world", "cup", "league", "united", "city",
    }
)


def _subject_merge_tokens(team: str, item: dict[str, Any]) -> set[str]:
    """Subjekt-Tokens, die als Merge-Schluessel taugen (ohne Rausch-Stopwords)."""
    return {
        key
        for key in player_subject_keys(team, item)
        if key and key not in SUBJECT_DEDUPE_STOPWORDS
    }


def _merge_impact_items_by_subject(
    team: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union-Find: Items, die sich ein Subjekt-Token teilen, sind DERSELBE Ausfall.
    Pro Gruppe ueberlebt das staerkste Item (`dedupe_rank`). Items ohne verwertbares
    Subjekt bleiben eigenstaendig (Team-Level-News duerfen sich summieren)."""
    parent = list(range(len(items)))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    tokens_of = [_subject_merge_tokens(team, item) for item in items]
    by_token: dict[str, list[int]] = {}
    for index, tokens in enumerate(tokens_of):
        for token in tokens:
            by_token.setdefault(token, []).append(index)
    for indices in by_token.values():
        for other in indices[1:]:
            union(indices[0], other)

    groups: dict[Any, list[dict[str, Any]]] = {}
    for index, item in enumerate(items):
        key: Any = f"_solo_{index}" if not tokens_of[index] else find(index)
        groups.setdefault(key, []).append(item)
    return [max(group, key=dedupe_rank) for group in groups.values()]


def dedupe_impact_items(
    team: str,
    items: Iterable[dict[str, Any]],
    *,
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    if enabled is None:
        enabled = NEWS_SUBJECT_DEDUPE_ENABLED
    item_list = list(items)
    if enabled:
        return _merge_impact_items_by_subject(team, item_list)
    by_key: dict[str, dict[str, Any]] = {}
    for item in item_list:
        key = impact_dedupe_key(team, item)
        existing = by_key.get(key)
        if existing is None or dedupe_rank(item) > dedupe_rank(existing):
            by_key[key] = item
    return list(by_key.values())


def dedupe_model_relevant_news(teams: Iterable[str], items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    team_list = list(teams)
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = model_news_dedupe_key(team_list, item)
        existing = by_key.get(key)
        if existing is None or model_news_dedupe_rank(item) > model_news_dedupe_rank(existing):
            by_key[key] = item
    return list(by_key.values())


def model_news_dedupe_key(teams: Iterable[str], item: dict[str, Any]) -> str:
    categories = set(item.get("categories") or [])
    if categories & XG_IMPACT_CATEGORIES and severity_rank(item.get("severity", "noise")) >= 2:
        affected = sorted(team for team in teams if team in (item.get("teams") or []))
        if affected:
            return "impact|" + "|".join(impact_dedupe_key(team, item) for team in affected)
    return "item|" + str(item.get("id") or fingerprint(item))


def model_news_dedupe_rank(item: dict[str, Any]) -> tuple[tuple[int, int, int], str]:
    return (dedupe_rank(item), str(item.get("published_at") or ""))


def impact_dedupe_key(team: str, item: dict[str, Any]) -> str:
    categories = sorted(set(item.get("categories") or []) & XG_IMPACT_CATEGORIES)
    subject_keys = player_subject_keys(team, item)
    if subject_keys:
        return "|".join(["player", team, ",".join(categories), ",".join(subject_keys)])
    return "item|" + str(item.get("id") or fingerprint(item))


def player_subject_keys(team: str, item: dict[str, Any]) -> list[str]:
    explicit = [normalize_player_subject(player) for player in item.get("players") or []]
    explicit = [player for player in explicit if player]
    if explicit:
        return sorted(set(explicit))
    text = " ".join(str(item.get(field, "")) for field in ("title", "summary", "impact"))
    return infer_player_subject_keys(team, text)


def normalize_player_subject(value: Any) -> str:
    normalized = normalize_text(re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ' -]+", " ", str(value)))
    tokens = [token.strip("' -") for token in normalized.split() if token.strip("' -")]
    if not tokens:
        return ""
    token = tokens[-1]
    if token.endswith("'s"):
        token = token[:-2]
    return token


def infer_player_subject_keys(team: str, text: str) -> list[str]:
    team_terms = {normalize_player_subject(term) for term in team_match_terms(team)}
    candidates = re.findall(
        r"\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+){0,2}",
        text,
    )
    subjects: list[str] = []
    for candidate in candidates:
        tokens = [
            normalize_player_subject(token)
            for token in re.split(r"\s+", candidate.replace("’", "'"))
        ]
        useful_tokens = [
            token
            for token in tokens
            if token
            and token not in PLAYER_NAME_STOPWORDS
            and token not in team_terms
        ]
        if useful_tokens:
            subjects.append(useful_tokens[-1])
    return sorted(set(subjects))
