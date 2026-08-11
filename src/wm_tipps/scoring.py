"""Kicktipp-Wertung: Punkteregeln, Rundenprofile und EP-optimale Tippwahl.

Kern des Projekts. Rechnet aus einer Score-Wahrscheinlichkeitsmatrix den Tipp
mit dem hoechsten Punkte-Erwartungswert fuer ein gegebenes Rundenregelwerk --
nicht das wahrscheinlichste Ergebnis, sondern das punktbeste.

Rundenprofile: die Defaults unten (`classic`, `escalating`) sind generische
Kicktipp-Schemata. Eigene Runden definiert man in einer lokalen
`rounds_local.py` neben diesem Modul (Vorlage: `rounds_local.example.py`);
existiert sie, ersetzt sie die Defaults vollstaendig.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from math import exp, factorial
from typing import Any, Mapping

from .round_rules import (  # noqa: F401  (Re-Export fuer bestehende Importe)
    ESCALATING_LATE_KNOCKOUT_POINTS,
    ESCALATING_LATE_KNOCKOUT_STAGES,
    GROUP_POINTS,
    GROUP_STAGES,
    KNOCKOUT_POINTS,
    TipRound,
    scope_resolves_penalties,
)


CLASSIC_ROUND_ID = "classic"
ESCALATING_ROUND_ID = "escalating"


def is_knockout_stage(stage: str) -> bool:
    """Konsistent mit TipRound.points_for_stage: alles ausser Gruppenphase
    ist KO (knockout, round_of_32, round_of_16, final, ...)."""
    return (stage or "group").lower() not in GROUP_STAGES


# --- Neutrale Default-Runden -------------------------------------------------
# Zwei gaengige Kicktipp-Konfigurationen. Wer eigene Runden fahren will, legt
# `rounds_local.py` an -- der Block darunter zieht sie dann vor.
DEFAULT_ROUND_ID = CLASSIC_ROUND_ID
SECONDARY_ROUND_ID = ESCALATING_ROUND_ID

TIP_ROUNDS: dict[str, TipRound] = {
    CLASSIC_ROUND_ID: TipRound(
        id=CLASSIC_ROUND_ID,
        name="Classic",
        group_points=GROUP_POINTS,
        knockout_points=KNOCKOUT_POINTS,
        bonus_questions=("world_champion",),
        bonus_points={"world_champion": 10},
        result_scope="including extra time and penalties",
    ),
    ESCALATING_ROUND_ID: TipRound(
        id=ESCALATING_ROUND_ID,
        name="Escalating",
        group_points=GROUP_POINTS,
        knockout_points=KNOCKOUT_POINTS,
        stage_points={
            stage: ESCALATING_LATE_KNOCKOUT_POINTS
            for stage in ESCALATING_LATE_KNOCKOUT_STAGES
        },
        bonus_questions=("world_champion",),
        bonus_points={"world_champion": 10},
        result_scope="after extra time",
    ),
}

# --- Optionales privates Overlay ---------------------------------------------
# Bewusst `find_spec` statt `try/except ImportError`: so schlaegt ein FEHLER IN
# `rounds_local` laut durch, und nur die echte ABWESENHEIT der Datei faellt auf
# die Defaults zurueck. Ein stiller Fallback wuerde mit falschen Punkteschemata
# weiterrechnen, ohne dass es jemand merkt.
if importlib.util.find_spec("wm_tipps.rounds_local") is not None:
    from .rounds_local import (  # noqa: F401
        DEFAULT_ROUND_ID,
        SECONDARY_ROUND_ID,
        TIP_ROUNDS,
    )

ROUND_ORDER = tuple(TIP_ROUNDS)


@dataclass(frozen=True)
class Score:
    home: int
    away: int

    @property
    def diff(self) -> int:
        return self.home - self.away

    @property
    def outcome(self) -> str:
        if self.home > self.away:
            return "home"
        if self.home < self.away:
            return "away"
        return "draw"

    @property
    def label(self) -> str:
        return f"{self.home}:{self.away}"


def rules_for_round(round_id: str = DEFAULT_ROUND_ID) -> TipRound:
    try:
        return TIP_ROUNDS[round_id]
    except KeyError as exc:
        raise KeyError(f"Unbekannte Kicktipp-Runde: {round_id}") from exc


def round_name(round_id: str = DEFAULT_ROUND_ID) -> str:
    return rules_for_round(round_id).name


def is_stage_tippable(stage: str, round_id: str = DEFAULT_ROUND_ID) -> bool:
    """Ob die Runde fuer diese Turnierphase eine Tippzeile anbietet."""
    return (stage or "group").lower() not in rules_for_round(round_id).non_tippable_stages


def round_rules_payload() -> list[dict[str, Any]]:
    return [TIP_ROUNDS[round_id].payload() for round_id in ROUND_ORDER]


def default_rules_payload() -> dict[str, Any]:
    default = rules_for_round(DEFAULT_ROUND_ID)
    bonuses = dict(default.bonus_points)
    if "semifinalists" in bonuses:
        bonuses.setdefault("semifinalist", bonuses["semifinalists"])
    return {
        "group": dict(default.group_points),
        "knockout": dict(default.knockout_points),
        "bonuses": bonuses,
    }


def points_for_stage(stage: str, round_id: str = DEFAULT_ROUND_ID) -> Mapping[str, int]:
    return rules_for_round(round_id).points_for_stage(stage)


def actual_for_round(
    actual: tuple[int, int] | list[int],
    penalty_winner: str | None = None,
    round_id: str = DEFAULT_ROUND_ID,
    shootout: tuple[int, int] | list[int] | None = None,
) -> Score:
    """Wertungs-Scoreline je Runde. `actual` ist der Stand nach Verlaengerung.

    Runden mit 'nach Verlaengerung'-Scope werten genau diesen Stand --
    ein Elfmeterschiessen aendert dort nichts.

    Runden mit Elfmeter-Scope (result_scope enthaelt 'elfmeter'/'penalt')
    werten die volle
    Scoreline INKLUSIVE der Elfmetertore: Stand nach Verlaengerung plus die
    Elferbilanz beider Seiten. Beispiel ko-088: 1:1 n.V., Elfer 2:4 -> 3:5.
    Genau so zeigt Kicktipp das Spiel an, und genau so wertet es.
    (T-0155, empirisch belegt: nur diese Konvention reproduziert die
    beobachteten Punktestaende einer Runde mit Elfmeter-Scope.)

    `shootout` ist die reine Elferbilanz (h, a) in Heim:Auswaerts-Reihenfolge.
    Fehlt sie, faellt die Funktion auf die alte Naeherung "+1 Tor fuer den
    Elfer-Sieger" zurueck -- das ist NICHT die echte Kicktipp-Linie, sondern
    nur eine Notloesung fuer Datensaetze ohne erfasste Elferbilanz. Sie ist
    systematisch zu optimistisch, weil sie das Spiel auf gut tippbare Linien
    (1:0, 2:1) zwingt statt auf reale (3:5, 4:5). Wer sie triggert, sollte
    die Elferbilanz nachtragen, nicht die Naeherung akzeptieren.
    """
    home, away = int(actual[0]), int(actual[1])
    if not penalty_winner or not round_resolves_penalties(round_id):
        return Score(home, away)
    if shootout is not None:
        return Score(home + int(shootout[0]), away + int(shootout[1]))
    if penalty_winner == "home":
        home += 1
    elif penalty_winner == "away":
        away += 1
    return Score(home, away)


def kicktipp_points(
    prediction: Score,
    actual: Score,
    stage: str,
    round_id: str = DEFAULT_ROUND_ID,
) -> int:
    points = points_for_stage(stage, round_id=round_id)
    if prediction == actual:
        return points["exact"]
    if actual.diff == 0:
        # Falscher Remis-Score = nur Tendenz (kein Tordifferenz-Bonus). Bei einem
        # Remis ist die "Tordifferenz" trivial 0 == 0; Kicktipp wertet einen
        # daneben liegenden Remis-Tipp als Tendenz, nicht als Tordifferenz.
        # Per Pool-Screenshots verifiziert (2:2 auf 1:1 = 2 Pkt). T-0097.
        return points["tendency"] if prediction.diff == 0 else 0
    if prediction.diff == actual.diff:
        return points["difference"]
    if prediction.outcome == actual.outcome:
        return points["tendency"]
    return 0


def expected_points(
    candidate: Score,
    score_probabilities: Mapping[str, float],
    stage: str,
    round_id: str = DEFAULT_ROUND_ID,
) -> float:
    total = 0.0
    for label, probability in score_probabilities.items():
        home, away = (int(part) for part in label.split(":"))
        total += probability * kicktipp_points(candidate, Score(home, away), stage, round_id=round_id)
    return total


def round_resolves_penalties(round_id: str = DEFAULT_ROUND_ID) -> bool:
    """True, wenn die Runde KO-Spiele nach Elfmeterschiessen wertet.
    Dann gibt es im Endergebnis nie ein Remis."""
    return scope_resolves_penalties(rules_for_round(round_id).result_scope)


# Shootout-Tilt: 0.0 = flach 50/50, 1.0 = voll nach Match-Wahrscheinlichkeit.
# Elfmeterschiessen ist empirisch nahe an einem Muenzwurf; eine milde
# Favoriten-Neigung (komprimiert) holt im Backtest +4 KO-Punkte gegen
# flach und verschlechtert kein Turnier, ohne "Starke gewinnen Shootouts"
# zu ueberzeichnen.
KO_SHOOTOUT_TILT = 0.5


def _home_shootout_prob(
    score_probabilities: Mapping[str, float],
    tilt: float = KO_SHOOTOUT_TILT,
) -> float:
    home_win = 0.0
    away_win = 0.0
    for label, probability in score_probabilities.items():
        home, away = (int(part) for part in label.split(":"))
        if home > away:
            home_win += probability
        elif away > home:
            away_win += probability
    decisive = home_win + away_win
    if decisive <= 0:
        return 0.5
    match_prob = home_win / decisive
    return 0.5 + tilt * (match_prob - 0.5)


def resolve_knockout_draw_probabilities(
    score_probabilities: Mapping[str, float],
    *,
    home_shootout_prob: float | None = None,
) -> dict[str, float]:
    """T-0061: Remis-Wahrscheinlichkeit auf entscheidende Scorelines
    umverteilen, weil ein KO-Spiel nach Elfmeterschiessen nie remis endet
    (Sieger +1). h:h -> (h+1):h bzw. h:(h+1) gemaess Shootout-Wahrschein-
    lichkeit. Default: milder Tilt nach Match-Wkt (sonst 50/50).
    """
    if home_shootout_prob is None:
        home_shootout_prob = _home_shootout_prob(score_probabilities)
    resolved: dict[str, float] = {}
    for label, probability in score_probabilities.items():
        home, away = (int(part) for part in label.split(":"))
        if home == away:
            home_label = f"{home + 1}:{away}"
            away_label = f"{home}:{away + 1}"
            resolved[home_label] = resolved.get(home_label, 0.0) + probability * home_shootout_prob
            resolved[away_label] = resolved.get(away_label, 0.0) + probability * (1.0 - home_shootout_prob)
        else:
            resolved[label] = resolved.get(label, 0.0) + probability
    return resolved


# Verlaengerungs-Tempo: ET-xG je Team = Match-xG je Team * 30/90 * ~0.9
# (Verlaengerung ist kuerzer, etwas mueder). 0.30 zielt auf ~45-50% der
# 90'-Remis in der Verlaengerung entschieden (Rest -> Elfer). T-0072.
# PRIOR -- spaeter per Beta(p_decisive_et)/Gamma(lam_et) aus echten
# ET-Spielen verfeinerbar (Ergebnis-Schema fuehrt dafuer after_90/after_120).
KO_EXTRA_TIME_FACTOR = 0.30


def _matrix_expected_goals(score_probabilities: Mapping[str, float]) -> tuple[float, float]:
    home = away = 0.0
    for label, probability in score_probabilities.items():
        h, a = (int(part) for part in label.split(":"))
        home += h * probability
        away += a * probability
    return home, away


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * lam ** k / factorial(k)


def resolve_extra_time(
    score_probabilities: Mapping[str, float],
    *,
    et_factor: float = KO_EXTRA_TIME_FACTOR,
    max_extra: int = 3,
) -> dict[str, float]:
    """T-0072: KO-Matrix von 90' auf "nach Verlaengerung" transformieren.
    Die Markt-kalibrierte Matrix bepreist 90 Minuten; in einem KO-Spiel wird
    aber die Mehrheit der 90'-Remis in der Verlaengerung entschieden.

    Entscheidende Zellen (h!=a) bleiben unveraendert. Jede Remis-Zelle (d,d)
    wird mit einer ET-Mini-Poisson gefaltet (lam_et = Match-xG je Team *
    et_factor): (d,d) -> (d+i, d+j) gemaess Pois(i)*Pois(j). Die Faltungs-
    gewichte werden je Remis-Zelle normiert -> Gesamtmasse exakt erhalten.
    Rest-Remis (kein ET-Tor) bleibt ein Remis (Pool B wertet das 120'-
    Ergebnis; Pool A loest den Rest per Elfer-Konvention nachgelagert auf).
    """
    lam_home, lam_away = _matrix_expected_goals(score_probabilities)
    lam_et_home = max(0.0, lam_home * et_factor)
    lam_et_away = max(0.0, lam_away * et_factor)
    resolved: dict[str, float] = {}
    for label, probability in score_probabilities.items():
        home, away = (int(part) for part in label.split(":"))
        if home != away:
            resolved[label] = resolved.get(label, 0.0) + probability
            continue
        weights = [
            (i, j, _poisson_pmf(i, lam_et_home) * _poisson_pmf(j, lam_et_away))
            for i in range(max_extra + 1)
            for j in range(max_extra + 1)
        ]
        total = sum(w for _, _, w in weights) or 1.0
        for i, j, w in weights:
            target = f"{home + i}:{away + j}"
            resolved[target] = resolved.get(target, 0.0) + probability * (w / total)
    return resolved


def best_kicktipp_tip(
    score_probabilities: Mapping[str, float],
    stage: str,
    max_goals: int = 6,
    round_id: str = DEFAULT_ROUND_ID,
) -> dict[str, float | str | int]:
    # KO-Spiele werten nach Verlaengerung/Elfer, nicht nach 90 Minuten:
    # T-0072 ET-Transform (Remis-Masse korrekt verkleinern) fuer BEIDE Runden,
    # danach T-0061 Elfer-Konvention nur fuer Runden mit Elfmeter-Scope auf die
    # Rest-Remis. So sieht die EP-Optimierung die echte Post-120'-Verteilung.
    if is_knockout_stage(stage):
        score_probabilities = resolve_extra_time(score_probabilities)
        if round_resolves_penalties(round_id):
            score_probabilities = resolve_knockout_draw_probabilities(score_probabilities)
    best: dict[str, float | str | int] | None = None
    best_ep = -1.0
    for home in range(max_goals + 1):
        for away in range(max_goals + 1):
            candidate = Score(home, away)
            ep = expected_points(candidate, score_probabilities, stage, round_id=round_id)
            exact_probability = score_probabilities.get(candidate.label, 0.0)
            row = {
                "home": home,
                "away": away,
                "tip": candidate.label,
                "expected_points": round(ep, 4),
                "exact_probability": round(exact_probability, 4),
                "round_id": round_id,
                "round_name": round_name(round_id),
            }
            if best is None or ep > best_ep:
                best = row
                best_ep = ep
    assert best is not None
    return best
