"""Klassenschutz: die Scoreline-ABLEITUNG ueber alle Implementierungen hinweg.

Der bestehende `test_scoring_drift_guard.py` vergleicht, wieviele PUNKTE ein
Tipp bei GEGEBENEM Ergebnis bekommt. Ungedeckt blieb die Stufe davor: welches
Ergebnis eine Runde ueberhaupt wertet, wenn ein K.o.-Spiel im Elfmeterschiessen
entschieden wurde. Genau dort lagen die Befunde dieser Session:

  * `rival_profiles._norm_actual` prueft(e) den Scope mit einem eigenen
    Substring-Test auf "elfmeter" -- deutschsprachige Rundenprofile trafen, eine
    englisch beschriebene Runde bekam still die falsche Scoreline.
  * `risk_dial` reichte `shootout` nicht an `actual_for_round` weiter und
    benutzte damit die in `scoring.py` als "systematisch zu optimistisch"
    dokumentierte Naeherung.
  * T-0178 (23.08.26): zwei Auswertungszweige entschieden dieselbe Frage ueber
    ein RUNDEN-ID-LITERAL (eine feste Menge bekannter Rundennamen) statt ueber
    den Scope. Das faellt nicht auf, solange die lokal konfigurierte Runde
    zufaellig so heisst wie das Literal. Unter den mitgelieferten Default-Runden
    werteten beide Zweige die Elfer-Runde `classic` mit der Scoreline nach
    Verlaengerung: 1:1 statt 3:5, jeder Tipp darauf falsch bewertet.
    Gemessen am 23.08.26.

Beide Fehler waren unsichtbar, weil jede Implementierung fuer sich konsistent
war. Dieser Test stellt sie deshalb GEGENEINANDER: dasselbe Spiel, dieselbe
Runde, alle Wege muessen zur selben Wertungs-Scoreline kommen.

Rundenagnostisch: es wird nicht auf feste Zahlen geprueft, sondern darauf, dass
`round_resolves_penalties` und die abgeleitete Scoreline zusammenpassen -- egal
ob die Runde aus den neutralen Defaults oder aus einer lokalen
`rounds_local.py` stammt.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import importlib.util  # noqa: E402
from unittest import mock  # noqa: E402

from wm_tipps import scoring  # noqa: E402
from wm_tipps.rival_profiles import _norm_actual  # noqa: E402
from wm_tipps.round_rules import TipRound  # noqa: E402
from wm_tipps.scoring import (  # noqa: E402
    DEFAULT_ROUND_ID,
    SECONDARY_ROUND_ID,
    actual_for_round,
    round_resolves_penalties,
)

# Realfall ko-088: 1:1 nach Verlaengerung, Elfmeterschiessen 2:4.
# Kicktipp zeigt und wertet in einer Elfer-Runde die volle Linie 3:5.
REGULAER = [1, 1]
ELFER = [2, 4]
# `actual_for_round` braucht den Elfer-Sieger als Signal, DASS ueberhaupt ein
# Elfmeterschiessen stattfand -- ohne ihn wertet es den Stand n.V. (hier 1:1).
ELFER_SIEGER = "away"
VOLLE_LINIE = (3, 5)

# Die Form, in der so ein Spiel in manual_pool_tips.json steht.
ACTUAL_DICT = {"regulation": REGULAER, "penalty": list(VOLLE_LINIE)}

ROOT = Path(__file__).resolve().parents[1]


def _load(pfad: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, pfad)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


try:  # analysis-Zweige = Nicht-stdlib-Carve-out (numpy/pandas)
    _RIVAL_LAB = _load(ROOT / "analysis" / "rival_lab.py", "deriv_rival_lab")
    _TIDY = _load(ROOT / "analysis" / "rival-profiles" / "tidy.py", "deriv_tidy")
    _SKIP = ""
except Exception as exc:  # noqa: BLE001
    _RIVAL_LAB = _TIDY = None
    _SKIP = f"analysis-Zweige nicht ladbar ({type(exc).__name__}: {exc})"

# Eine Runde mit Elfmeter-Scope unter einem Namen, den KEIN Literal kennt.
# Genau dafuer existiert `round_resolves_penalties` -- wer stattdessen die
# Runden-ID vergleicht, faellt hier durch.
FREMDE_ELFER_RUNDE = "guard-elferrunde-mit-fremdem-namen"


def _mit_fremder_elferrunde():
    vorlage = scoring.rules_for_round(DEFAULT_ROUND_ID)
    fremd = TipRound(
        id=FREMDE_ELFER_RUNDE,
        name="Guard-Elferrunde",
        group_points=vorlage.group_points,
        knockout_points=vorlage.knockout_points,
        bonus_questions=vorlage.bonus_questions,
        bonus_points=vorlage.bonus_points,
        result_scope="inklusive Verlaengerung/Elfmeterschiessen",
    )
    return mock.patch.dict(scoring.TIP_ROUNDS, {FREMDE_ELFER_RUNDE: fremd})


class ScorelineDerivationGuardTest(unittest.TestCase):
    def test_kern_und_rival_profiles_leiten_dieselbe_scoreline_ab(self):
        for round_id in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID):
            with self.subTest(runde=round_id):
                aus_dict = _norm_actual(ACTUAL_DICT, round_id)
                kern = actual_for_round(REGULAER, ELFER_SIEGER, round_id, ELFER)
                self.assertEqual(
                    aus_dict,
                    (kern.home, kern.away),
                    f"rival_profiles und scoring leiten fuer '{round_id}' "
                    "unterschiedliche Wertungs-Scorelines ab.",
                )

    def test_abgeleitete_scoreline_folgt_dem_scope_der_runde(self):
        """Der eigentliche Vertrag, sprachunabhaengig formuliert."""
        for round_id in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID):
            with self.subTest(runde=round_id):
                erwartet = VOLLE_LINIE if round_resolves_penalties(round_id) else tuple(REGULAER)
                self.assertEqual(
                    _norm_actual(ACTUAL_DICT, round_id),
                    erwartet,
                    f"'{round_id}' hat round_resolves_penalties="
                    f"{round_resolves_penalties(round_id)}, waehlt aber die "
                    "andere Scoreline.",
                )
                kern = actual_for_round(REGULAER, ELFER_SIEGER, round_id, ELFER)
                self.assertEqual((kern.home, kern.away), erwartet)

    def test_scope_erkennung_ist_sprachunabhaengig(self):
        """Der konkrete Bug: ein eigener Substring-Test auf 'elfmeter' traf nur
        deutsche Scope-Texte. Beide Sprachen muessen dasselbe bedeuten."""
        from wm_tipps.round_rules import scope_resolves_penalties

        for deutsch, englisch in (
            ("inklusive Verlaengerung/Elfmeterschiessen", "including extra time and penalties"),
            ("inkl. Elfmeter", "incl. penalties"),
        ):
            with self.subTest(scope=deutsch):
                self.assertTrue(scope_resolves_penalties(deutsch))
                self.assertTrue(scope_resolves_penalties(englisch))
        for scope in ("nach Verlaengerung", "after extra time"):
            with self.subTest(scope=scope):
                self.assertFalse(scope_resolves_penalties(scope))

    def test_fehlende_elferbilanz_faellt_auf_die_naeherung_zurueck(self):
        """Ohne `shootout` bleibt nur die Naeherung -- sie MUSS sich aber von
        der echten Linie unterscheiden, sonst merkt niemand den Unterschied.

        Das ist der Grund, warum `shootout` durchgereicht werden muss: der
        Rueckfallpfad ist nicht harmlos, er ist nur weniger falsch als nichts.
        """
        elfer_runde = next(
            (r for r in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID) if round_resolves_penalties(r)),
            None,
        )
        if elfer_runde is None:
            self.skipTest("Keine Runde mit Elfmeter-Scope konfiguriert.")
        mit = actual_for_round(REGULAER, ELFER_SIEGER, elfer_runde, ELFER)
        ohne = actual_for_round(REGULAER, ELFER_SIEGER, elfer_runde, None)
        self.assertEqual((mit.home, mit.away), VOLLE_LINIE)
        self.assertNotEqual(
            (ohne.home, ohne.away),
            VOLLE_LINIE,
            "Naeherung und echte Elfer-Scoreline sind identisch -- dann kann "
            "dieser Test einen fehlenden shootout-Parameter nicht mehr fangen.",
        )


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_RIVAL_LAB is not None, _SKIP or "analysis-Zweige fehlen")
class AnalysisZweigeDerivationGuardTest(unittest.TestCase):
    """T-0178: alle DREI Ableitungen gegeneinander, nicht nur der Kern.

    Der bestehende Guard oben stellt `rival_profiles` gegen `scoring`. Die
    beiden analysis-Zweige blieben aussen vor -- und genau dort steht die Frage
    noch als Runden-ID-Literal statt als Scope-Abfrage.
    """

    def _zweige(self, round_id):
        return {
            "rival_profiles": _norm_actual(ACTUAL_DICT, round_id),
            "rival_lab": _RIVAL_LAB.norm_actual(ACTUAL_DICT, round_id),
            "tidy": _TIDY.resolve_actual(ACTUAL_DICT, round_id),
        }

    def test_konfigurierte_runden_stimmen_ueberein(self):
        for round_id in (DEFAULT_ROUND_ID, SECONDARY_ROUND_ID):
            erwartet = VOLLE_LINIE if round_resolves_penalties(round_id) else tuple(REGULAER)
            for zweig, wert in self._zweige(round_id).items():
                with self.subTest(runde=round_id, zweig=zweig):
                    self.assertEqual(wert, erwartet)

    def test_scope_entscheidet_nicht_der_rundenname(self):
        """Der eigentliche Vertrag: eine Runde mit Elfmeter-Scope bekommt die
        volle Linie -- unabhaengig davon, wie sie heisst."""
        with _mit_fremder_elferrunde():
            self.assertTrue(round_resolves_penalties(FREMDE_ELFER_RUNDE))
            for zweig, wert in self._zweige(FREMDE_ELFER_RUNDE).items():
                with self.subTest(zweig=zweig):
                    self.assertEqual(
                        wert, VOLLE_LINIE,
                        f"'{zweig}' entscheidet ueber den Rundennamen statt ueber "
                        "den Scope: Runde loest Elfmeter auf, gewertet wird aber "
                        "der Stand nach Verlaengerung.",
                    )
