from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .io import read_json, write_json
from .paths import DATA_DIR
from .scoring import DEFAULT_ROUND_ID, ROUND_ORDER, round_name


MAX_HISTORY_EVENTS = 500
SNAPSHOT_TOP_SCORES = 5


def _round_tips(prediction: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    tips: dict[str, Mapping[str, Any]] = {}
    raw = prediction.get("round_tips") or {}
    if isinstance(raw, Mapping):
        for round_id, tip in raw.items():
            if isinstance(tip, Mapping):
                tips[str(round_id)] = tip
    recommended = prediction.get("recommended_tip") or {}
    if isinstance(recommended, Mapping) and recommended and DEFAULT_ROUND_ID not in tips:
        tips[DEFAULT_ROUND_ID] = recommended
    return tips


def _tip(prediction: Mapping[str, Any], round_id: str = DEFAULT_ROUND_ID) -> str:
    return str((_round_tips(prediction).get(round_id) or {}).get("tip") or "")


def _expected_points(prediction: Mapping[str, Any], round_id: str = DEFAULT_ROUND_ID) -> float:
    try:
        return float((_round_tips(prediction).get(round_id) or {}).get("expected_points") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _match_label(prediction: Mapping[str, Any]) -> str:
    fixture = prediction.get("fixture") or {}
    return f"{fixture.get('home_team')} - {fixture.get('away_team')}"


def _news_ids(prediction: Mapping[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in prediction.get("news", []) if item.get("id")}


def _news_title_by_id(prediction: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item.get("id")): str(item.get("title") or item.get("summary") or "News-Update")
        for item in prediction.get("news", [])
        if item.get("id")
    }


def _odds_signature(prediction: Mapping[str, Any]) -> Any:
    odds = prediction.get("odds") or {}
    return {
        "source": odds.get("source"),
        "last_updated": odds.get("last_updated"),
        "probabilities": odds.get("probabilities"),
    }


def _explanation_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    old_rows = set(old.get("explanation") or [])
    return [str(row) for row in new.get("explanation", []) if row not in old_rows]


def _round_number(value: Any, digits: int = 3) -> float | None:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _format_value(value: Any) -> str:
    rounded = _round_number(value)
    if rounded is None:
        return "n/a"
    if rounded.is_integer():
        return str(int(rounded))
    return str(rounded)


def _format_probability(value: Any) -> str:
    rounded = _round_number(value, 4)
    if rounded is None:
        return "n/a"
    return f"{rounded * 100:.1f}%"


def _side_labels(prediction: Mapping[str, Any]) -> dict[str, str]:
    fixture = prediction.get("fixture") or {}
    return {
        "home": str(fixture.get("home_team") or "Heimteam"),
        "away": str(fixture.get("away_team") or "Auswaertsteam"),
    }


def prediction_snapshot(prediction: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "context": prediction.get("context") or {},
        "explanation": prediction.get("explanation") or [],
        "probabilities": prediction.get("probabilities") or {},
        "recommended_tip": prediction.get("recommended_tip") or {},
        "round_tips": prediction.get("round_tips") or {},
        "stability": prediction.get("stability"),
        "strength": prediction.get("strength") or {},
        "top_scores": (prediction.get("top_scores") or [])[:SNAPSHOT_TOP_SCORES],
        "xg": prediction.get("xg") or {},
    }


def _value_delta(label: str, old_value: Any, new_value: Any) -> str | None:
    if old_value == new_value:
        return None
    return f"{label} {_format_value(old_value)} -> {_format_value(new_value)}"


def _strength_deltas(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    rows = []
    labels = _side_labels(new)
    old_strength = old.get("strength") or {}
    new_strength = new.get("strength") or {}
    for side in ("home", "away"):
        old_row = old_strength.get(side) or {}
        new_row = new_strength.get(side) or {}
        changes = [
            _value_delta("Elo", old_row.get("elo"), new_row.get("elo")),
            _value_delta("Attack", old_row.get("attack"), new_row.get("attack")),
            _value_delta("FIFA-Proxy", old_row.get("fifa_rank_rating"), new_row.get("fifa_rank_rating")),
            _value_delta("Form", old_row.get("form_adjustment"), new_row.get("form_adjustment")),
        ]
        filtered = [change for change in changes if change]
        if filtered:
            rows.append(f"{labels[side]}: " + ", ".join(filtered))
    return rows


def _xg_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> str | None:
    old_xg = old.get("xg") or {}
    new_xg = new.get("xg") or {}
    if old_xg == new_xg:
        return None
    labels = _side_labels(new)
    return (
        f"xG {labels['home']} {_format_value(old_xg.get('home'))} -> {_format_value(new_xg.get('home'))}; "
        f"{labels['away']} {_format_value(old_xg.get('away'))} -> {_format_value(new_xg.get('away'))}"
    )


def _probability_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> str | None:
    old_probs = ((old.get("probabilities") or {}).get("blended") or {})
    new_probs = ((new.get("probabilities") or {}).get("blended") or {})
    if old_probs == new_probs:
        return None
    labels = _side_labels(new)
    return (
        f"Wahrscheinlichkeit {labels['home']} {_format_probability(old_probs.get('home'))} -> {_format_probability(new_probs.get('home'))}; "
        f"Remis {_format_probability(old_probs.get('draw'))} -> {_format_probability(new_probs.get('draw'))}; "
        f"{labels['away']} {_format_probability(old_probs.get('away'))} -> {_format_probability(new_probs.get('away'))}"
    )


def _top_score_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> str | None:
    old_scores = old.get("top_scores") or []
    new_scores = new.get("top_scores") or []
    old_top = old_scores[0] if old_scores else {}
    new_top = new_scores[0] if new_scores else {}
    if old_top == new_top:
        return None
    return (
        f"Top-Score {old_top.get('score', 'n/a')} ({_format_probability(old_top.get('probability'))}) "
        f"-> {new_top.get('score', 'n/a')} ({_format_probability(new_top.get('probability'))})"
    )


def _context_delta(old: Mapping[str, Any], new: Mapping[str, Any]) -> str | None:
    old_context = old.get("context") or {}
    new_context = new.get("context") or {}
    if old_context == new_context:
        return None
    return (
        "Kontext "
        f"Flags {', '.join(old_context.get('flags') or []) or '-'} -> {', '.join(new_context.get('flags') or []) or '-'}; "
        f"Heimvorteil-xG {_format_value(old_context.get('home_advantage_xg'))} -> {_format_value(new_context.get('home_advantage_xg'))}"
    )


def _metric_details(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    rows = []
    rows.extend(_strength_deltas(old, new))
    for row in (
        _xg_delta(old, new),
        _probability_delta(old, new),
        _top_score_delta(old, new),
        _context_delta(old, new),
    ):
        if row:
            rows.append(row)
    return rows


def _change_trigger(old: Mapping[str, Any], new: Mapping[str, Any]) -> tuple[str, list[str]]:
    # Staerke-Block (Elo/Attack/FIFA-Proxy/Form) hat Vorrang vor News: News
    # aendert diese Werte NIE (nur xg via news_effect). Aendern sie sich, ist
    # ein Staerke-/Elo-Refresh der echte Treiber -- sonst wuerde ein Elo-
    # Wechsel faelschlich als "News-Lage" gelabelt (live beobachtet: France-Senegal/
    # Iran-NZ sahen wie News aus, waren aber ein Elo-Refresh).
    if _strength_deltas(old, new):
        return "Teamstaerke/Kontext", _metric_details(old, new) or _strength_deltas(old, new)[:3]
    old_news = _news_ids(old)
    new_news = _news_ids(new)
    added_news = sorted(new_news - old_news)
    if added_news:
        titles = _news_title_by_id(new)
        return "News", [titles.get(news_id, "News-Update") for news_id in added_news[:3]]
    if old_news != new_news:
        return "News-Lage", ["News-Lage fuer das Spiel hat sich geaendert."]
    if _odds_signature(old) != _odds_signature(new):
        return "Quoten/Markt", ["Quoten- oder Marktdaten fuer das Spiel haben sich geaendert."]
    if old.get("xg") != new.get("xg"):
        return "Teamstaerke/Kontext", _metric_details(old, new) or ["xG-Basis hat sich durch Teamstaerke, News-Impact oder Kontext geaendert."]
    return "Modell", _metric_details(old, new) or _explanation_delta(old, new)[:3] or ["Modell- oder Rundungsupdate."]


def prediction_change_event(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    *,
    round_id: str = DEFAULT_ROUND_ID,
    changed_at: str | None = None,
) -> dict[str, Any] | None:
    old_tip = _tip(old, round_id=round_id)
    new_tip = _tip(new, round_id=round_id)
    if old_tip == new_tip:
        return None

    old_expected = _expected_points(old, round_id=round_id)
    new_expected = _expected_points(new, round_id=round_id)
    old_stability = old.get("stability")
    new_stability = new.get("stability")

    trigger, details = _change_trigger(old, new)
    fixture = new.get("fixture") or {}
    kickoff = fixture.get("kickoff_utc") or "Termin offen"
    name = round_name(round_id)
    summary = (
        f"{name} · {kickoff} · Wegen {trigger}: "
        f"{_match_label(new)} von {old_tip} auf {new_tip} geaendert."
    )
    return {
        "changed_at": changed_at or datetime.now(timezone.utc).isoformat(),
        "details": details,
        "from_expected_points": round(old_expected, 3),
        "from_stability": old_stability,
        "from_tip": old_tip,
        "kickoff_utc": fixture.get("kickoff_utc"),
        "match": _match_label(new),
        "match_id": new.get("match_id"),
        "round_id": round_id,
        "round_name": name,
        "summary": summary,
        "snapshot": {
            "from": prediction_snapshot(old),
            "to": prediction_snapshot(new),
        },
        "to_expected_points": round(new_expected, 3),
        "to_stability": new_stability,
        "to_tip": new_tip,
        "trigger": trigger,
    }


def _is_tip_change_event(event: Mapping[str, Any]) -> bool:
    return str(event.get("from_tip") or "") != str(event.get("to_tip") or "")


BONUS_CATEGORIES = ("world_champion", "semifinalists", "top_scorer_team", "group_winners")
BONUS_LABELS = {
    "world_champion": "Bonus / Weltmeister",
    "semifinalists": "Bonus / Halbfinalisten",
    "top_scorer_team": "Bonus / Torschuetzenkoenig-Team",
    "group_winners": "Bonus / Gruppensieger",
}
INPUT_LABELS = {
    "strengths": "team_strength_inputs aktualisiert",
    "player_pool": "player_pool aktualisiert",
    "markets": "manuelle Markt-Signale aktualisiert",
    "news": "News-Lage geaendert",
}


def _format_team_prob(row: Mapping[str, Any]) -> str:
    name = str(row.get("team") or "?")
    prob = row.get("probability")
    try:
        return f"{name} ({float(prob) * 100:.1f}%)"
    except (TypeError, ValueError):
        return name


_BONUS_LABEL_RE = re.compile(r"^(?P<team>.+?)\s*\((?P<prob>\d+(?:[.,]\d+)?)\s*%\)\s*$")


def _parse_bonus_label(label: str) -> dict[str, Any] | None:
    if not label:
        return None
    match = _BONUS_LABEL_RE.match(label.strip())
    if not match:
        return None
    try:
        probability = float(match.group("prob").replace(",", ".")) / 100.0
    except ValueError:
        return None
    return {"team": match.group("team").strip(), "probability": round(probability, 4)}


def _bonus_top_snapshot(ranking: list[Mapping[str, Any]] | None, limit: int = 5) -> list[dict[str, Any]]:
    if not ranking:
        return []
    snapshot = []
    for row in list(ranking)[:limit]:
        snapshot.append(
            {
                "team": row.get("team"),
                "probability": row.get("probability"),
                "market_probability": row.get("market_probability"),
            }
        )
    return snapshot


def bonus_change_event(
    category: str,
    old_ranking: list[Mapping[str, Any]] | None,
    new_ranking: list[Mapping[str, Any]] | None,
    *,
    changed_at: str | None = None,
    changed_inputs: Iterable[str] | None = None,
) -> dict[str, Any] | None:
    old_top = (old_ranking or [{}])[0] if old_ranking else {}
    new_top = (new_ranking or [{}])[0] if new_ranking else {}
    old_team = str(old_top.get("team") or "")
    new_team = str(new_top.get("team") or "")
    if not new_team or old_team == new_team:
        return None
    from_label = _format_team_prob(old_top) if old_team else "n/a"
    to_label = _format_team_prob(new_top)
    reasons = [INPUT_LABELS.get(key, key) for key in (changed_inputs or [])]
    details = [f"{BONUS_LABELS.get(category, category)}: Favorit {from_label} -> {to_label}"]
    if reasons:
        details.append("Ursache: " + ", ".join(reasons))
    return {
        "changed_at": changed_at or datetime.now(timezone.utc).isoformat(),
        "match": BONUS_LABELS.get(category, f"Bonus / {category}"),
        "match_id": f"bonus-{category}",
        "trigger": "Bonus-Recalc",
        "from_tip": from_label,
        "to_tip": to_label,
        "from_expected_points": old_top.get("probability"),
        "to_expected_points": new_top.get("probability"),
        "from_stability": None,
        "to_stability": None,
        "details": details,
        "summary": f"{BONUS_LABELS.get(category, category)}: Favorit {from_label} -> {to_label}",
        "category": category,
        "trigger_reason": list(changed_inputs or []),
        "snapshot": {
            "kind": "bonus_ranking",
            "category": category,
            "from_top": _bonus_top_snapshot(old_ranking),
            "to_top": _bonus_top_snapshot(new_ranking),
        },
    }


def group_winner_change_events(
    old_groups: Mapping[str, list[Mapping[str, Any]]] | None,
    new_groups: Mapping[str, list[Mapping[str, Any]]] | None,
    *,
    changed_at: str | None = None,
    changed_inputs: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(new_groups, Mapping):
        return []
    old_groups = old_groups if isinstance(old_groups, Mapping) else {}
    events = []
    reasons = [INPUT_LABELS.get(key, key) for key in (changed_inputs or [])]
    for group in sorted(new_groups):
        old_ranking = old_groups.get(group) if isinstance(old_groups.get(group), list) else []
        new_ranking = new_groups.get(group) if isinstance(new_groups.get(group), list) else []
        old_top = (old_ranking or [{}])[0] if old_ranking else {}
        new_top = (new_ranking or [{}])[0] if new_ranking else {}
        old_team = str(old_top.get("team") or "")
        new_team = str(new_top.get("team") or "")
        if not new_team or old_team == new_team:
            continue
        from_label = _format_team_prob(old_top) if old_team else "n/a"
        to_label = _format_team_prob(new_top)
        details = [f"Gruppe {group}: Favorit {from_label} -> {to_label}"]
        if reasons:
            details.append("Ursache: " + ", ".join(reasons))
        events.append(
            {
                "changed_at": changed_at or datetime.now(timezone.utc).isoformat(),
                "match": f"Bonus / Gruppensieger Gruppe {group}",
                "match_id": f"bonus-group_winner-{group}",
                "trigger": "Bonus-Recalc",
                "from_tip": from_label,
                "to_tip": to_label,
                "from_expected_points": old_top.get("probability"),
                "to_expected_points": new_top.get("probability"),
                "from_stability": None,
                "to_stability": None,
                "details": details,
                "summary": f"Bonus / Gruppensieger Gruppe {group}: Favorit {from_label} -> {to_label}",
                "category": "group_winners",
                "group": group,
                "trigger_reason": list(changed_inputs or []),
                "snapshot": {
                    "kind": "bonus_group_winner",
                    "category": "group_winners",
                    "group": group,
                    "from_top": _bonus_top_snapshot(old_ranking),
                    "to_top": _bonus_top_snapshot(new_ranking),
                },
            }
        )
    return events


def _collapse_oscillations(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """T-0106: Tipps koennen auf einer Kante pendeln (z.B. Brazil-Haiti 1:0 vs
    2:0 fast gleich-EP, als 'volatil' markiert) -> die History laeuft mit Hin-
    und-Her voll, obwohl sich netto nichts aendert. Auch viele Rebuilds (Accuracy-
    Loop) flippen denselben Tipp. Pro (match_id, round_name) wird die Zustands-
    folge per STACK bereinigt: ein Event, das zum unmittelbar vorigen Zustand
    zurueckkehrt, annulliert den letzten Schritt (A->B->A verschwindet, ueber
    ALLE Trigger); reine Re-Logs (gleicher Zustand) fallen raus; echte
    Progressionen (A->B->C) bleiben. Behaltene Events tragen den Trigger/Zeitpunkt
    des jeweils netto-wirksamen Schritts. Events ohne Tip (Bonus-Recalc ohne
    from/to) bleiben unangetastet. In Normalbetrieb ein No-Op."""
    from collections import defaultdict

    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    kept: list[dict[str, Any]] = []
    for event in events:
        if event.get("from_tip") is None or event.get("to_tip") is None:
            kept.append(event)  # keine Tip-Semantik -> durchreichen
            continue
        groups[(event.get("match_id"), event.get("round_name"))].append(event)

    for _key, lst in groups.items():
        chron = sorted(lst, key=lambda e: e.get("changed_at", ""))
        start = chron[0].get("from_tip")
        stack: list[tuple[Any, dict[str, Any]]] = []  # (to_state, event)
        for event in chron:
            to = event.get("to_tip")
            cur = stack[-1][0] if stack else start
            if to == cur:
                continue  # kein echter Wechsel (Re-Log)
            prev = stack[-2][0] if len(stack) >= 2 else start
            if to == prev:
                stack.pop()  # Rueckkehr zum vorigen Zustand -> Oszillation annullieren
            else:
                stack.append((to, event))
        prev_state = start
        for to, event in stack:  # from_tips entlang der bereinigten Kette nachziehen
            merged = dict(event)
            merged["from_tip"] = prev_state
            merged["to_tip"] = to
            kept.append(merged)
            prev_state = to

    kept.sort(key=lambda e: e.get("changed_at", ""), reverse=True)
    return kept


def record_prediction_history(
    previous_predictions: list[dict[str, Any]],
    current_predictions: list[dict[str, Any]],
    *,
    previous_bonus: Mapping[str, Any] | None = None,
    current_bonus: Mapping[str, Any] | None = None,
    changed_inputs: Iterable[str] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    changed_at = datetime.now(timezone.utc).isoformat()
    previous_by_id = {item.get("match_id"): item for item in previous_predictions if item.get("match_id")}
    events = []
    for current in current_predictions:
        previous = previous_by_id.get(current.get("match_id"))
        if not previous:
            continue
        current_round_tips = _round_tips(current)
        previous_round_tips = _round_tips(previous)
        comparable_rounds = [DEFAULT_ROUND_ID]
        comparable_rounds.extend(
            round_id
            for round_id in ROUND_ORDER
            if round_id != DEFAULT_ROUND_ID
            and round_id in current_round_tips
            and round_id in previous_round_tips
        )
        comparable_rounds.extend(
            sorted(
                (set(current_round_tips) & set(previous_round_tips))
                - set(comparable_rounds)
            )
        )
        for round_id in comparable_rounds:
            event = prediction_change_event(previous, current, round_id=round_id, changed_at=changed_at)
            if event:
                events.append(event)

    if previous_bonus is not None and current_bonus is not None:
        for category in BONUS_CATEGORIES:
            if category == "group_winners":
                if category in previous_bonus and category in current_bonus:
                    events.extend(
                        group_winner_change_events(
                            previous_bonus.get(category),
                            current_bonus.get(category),
                            changed_at=changed_at,
                            changed_inputs=list(changed_inputs or []),
                        )
                    )
            else:
                event = bonus_change_event(
                    category,
                    previous_bonus.get(category),
                    current_bonus.get(category),
                    changed_at=changed_at,
                    changed_inputs=list(changed_inputs or []),
                )
                if event:
                    events.append(event)

    existing = read_json(DATA_DIR / "prediction_history.json", {"events": []})
    existing_events = [event for event in existing.get("events", []) if _is_tip_change_event(event)]
    history = {
        "updated_at": changed_at,
        "events": _collapse_oscillations(events + existing_events)[:MAX_HISTORY_EVENTS],
    }
    if write:
        write_json(DATA_DIR / "prediction_history.json", history)
    return history


def enrich_history_events(
    events: list[dict[str, Any]],
    current_predictions: list[dict[str, Any]],
    current_bonus: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    current_by_id = {
        prediction.get("match_id"): prediction
        for prediction in current_predictions
        if prediction.get("match_id")
    }
    bonus_payload = current_bonus or {}
    enriched = []
    for event in events:
        if not _is_tip_change_event(event):
            continue
        row = dict(event)
        snapshot = dict(row.get("snapshot") or {})
        match_id = str(row.get("match_id", ""))
        is_bonus = match_id.startswith("bonus-") or row.get("category") in BONUS_CATEGORIES

        if is_bonus:
            category = row.get("category") or match_id[len("bonus-") :]
            if category == "group_winners":
                group = row.get("group")
                current_groups = bonus_payload.get("group_winners") or {}
                current_ranking = (
                    current_groups.get(group)
                    if isinstance(current_groups, Mapping) and group
                    else None
                )
            else:
                current_ranking = bonus_payload.get(category)
            if current_ranking and not snapshot.get("to_top"):
                snapshot["kind"] = "bonus_ranking"
                snapshot["category"] = category
                if category == "group_winners":
                    snapshot["kind"] = "bonus_group_winner"
                    snapshot["group"] = row.get("group")
                snapshot["to_top"] = _bonus_top_snapshot(current_ranking)
                row["details"] = list(row.get("details") or []) + [
                    "Alter Bonus-Snapshot fehlt; 'Nachher' aus aktuellem Bonus-Block, 'Vorher' aus from_tip rekonstruiert (nur Top-1)."
                ]
            # Vorher: aus from_tip-Label nur den Top-1 rekonstruieren -- volles
            # Top-5-Vorher gibt's nur fuer Events, die nach T-0017 erzeugt wurden.
            if not snapshot.get("from_top"):
                parsed = _parse_bonus_label(str(row.get("from_tip", "")))
                snapshot["from_top"] = [parsed] if parsed else []
        else:
            current = current_by_id.get(match_id)
            if current:
                fixture = current.get("fixture") or {}
                row.setdefault("kickoff_utc", fixture.get("kickoff_utc"))
                row.setdefault("round_id", DEFAULT_ROUND_ID)
                row.setdefault("round_name", round_name(DEFAULT_ROUND_ID))
                if not snapshot.get("to"):
                    snapshot["to"] = prediction_snapshot(current)
                    row["details"] = list(row.get("details") or []) + [
                        "Alter Detail-Snapshot fehlt, weil dieser History-Eintrag vor dem Drilldown-Upgrade erzeugt wurde."
                    ]
        if snapshot:
            row["snapshot"] = snapshot
        enriched.append(row)
    return enriched
