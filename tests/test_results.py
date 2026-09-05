"""T-0188: eine Quelle fuer Spielergebnisse.

Der teure Fall ist nicht "eine Kopie zu viel", sondern was die Kopien
weggeworfen haben: den Elfmeter-Sieger. Ohne ihn wertet eine Runde mit
Elfmeter-Scope ein 1:1 n.V. als Remis -- ein Tipp "1:1" bekommt die volle
Exakt-Punktzahl statt der real erzielten 0.

Deshalb misst dieser Test nicht, ob die Felder durchgereicht werden, sondern
was am Ende an PUNKTEN herauskommt.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.eval_live import build_live_eval  # noqa: E402
from wm_tipps.results import (  # noqa: E402
    merge_manual_results,
    played_results,
    results_from_fixtures,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID  # noqa: E402


KO_FIXTURE = {
    "match_id": "ko-096",
    "stage": "round_of_16",
    "status": "played",
    "result": [1, 1],
    "penalty_winner": "away",
    "home_team": "Heim",
    "away_team": "Gast",
    "kickoff_utc": "2026-07-05T20:00:00+00:00",
}


class ResultsFromFixturesTests(unittest.TestCase):
    def test_penalty_winner_survives(self):
        rows = results_from_fixtures([KO_FIXTURE])
        self.assertEqual(rows["ko-096"]["penalty_winner"], "away")
        self.assertEqual(rows["ko-096"]["actual"], [1, 1])
        self.assertEqual(rows["ko-096"]["source"], "openfootball")

    def test_unplayed_and_malformed_rows_skipped(self):
        rows = results_from_fixtures(
            [
                {"match_id": "ga-001", "status": "scheduled", "result": None},
                {"match_id": "ga-002", "status": "played", "result": [2]},
                {"match_id": "ga-003", "status": "played", "result": ["x", "y"]},
                {"status": "played", "result": [1, 0]},  # ohne match_id
            ]
        )
        self.assertEqual(rows, {})

    def test_invalid_penalty_winner_is_dropped(self):
        rows = results_from_fixtures([{**KO_FIXTURE, "penalty_winner": "vielleicht"}])
        self.assertIsNone(rows["ko-096"]["penalty_winner"])


class MergeManualResultsTests(unittest.TestCase):
    def test_manual_shootout_enriches_fixture_result(self):
        merged = merge_manual_results(
            results_from_fixtures([KO_FIXTURE]),
            {"ko-096": {"actual": [1, 1], "penalty_winner": "away", "shootout": [2, 4]}},
        )
        self.assertEqual(merged["ko-096"]["shootout"], [2, 4])
        self.assertEqual(merged["ko-096"]["penalty_winner"], "away")

    def test_manual_row_without_penalty_does_not_erase_fixture_penalty(self):
        """Der Grund fuer feldweises Mergen: ein manueller Eintrag, der nur
        das Ergebnis korrigiert, darf den Elfer-Sieger nicht loeschen."""
        merged = merge_manual_results(
            results_from_fixtures([KO_FIXTURE]),
            {"ko-096": {"actual": [1, 1], "penalty_winner": None, "shootout": None}},
        )
        self.assertEqual(merged["ko-096"]["penalty_winner"], "away")

    def test_manual_only_match_is_added(self):
        merged = merge_manual_results({}, {"ko-099": {"actual": [0, 1], "penalty_winner": None}})
        self.assertEqual(merged["ko-099"]["actual"], [0, 1])
        self.assertIsNone(merged["ko-099"]["shootout"])


class PenaltyReachesScoringTests(unittest.TestCase):
    """Wirkungstest: derselbe Fixture-Bestand, einmal durch die Auswertung."""

    def _eval(self, results):
        predictions = [
            {
                "match_id": "ko-096",
                "fixture": KO_FIXTURE,
                "round_tips": {
                    DEFAULT_ROUND_ID: {"tip": "1:1", "expected_points": 2.0},
                    SECONDARY_ROUND_ID: {"tip": "1:1", "expected_points": 2.0},
                },
                "probabilities": {},
                "xg": {},
            }
        ]
        payload = build_live_eval(
            predictions=predictions, results=results, snapshots={}, write=False
        )
        return payload["matches"][0]["rounds"]

    def test_ko_draw_with_shootout_scores_zero_in_penalty_round(self):
        """1:1 n.V., Elfer 2:4 -> Wertungslinie 3:5. Ein Tipp 1:1 trifft nichts.
        Die Runde nach Verlaengerung wertet dagegen weiter 1:1 = exakt."""
        results = played_results(
            [KO_FIXTURE],
            {"results": {"ko-096": {"actual": [1, 1], "penalty_winner": "away", "shootout": [2, 4]}}},
        )
        rounds = self._eval(results)
        self.assertEqual(rounds[DEFAULT_ROUND_ID]["points"], 0)
        self.assertEqual(rounds[SECONDARY_ROUND_ID]["points"], 8)

    def test_penalty_winner_from_fixture_alone_still_breaks_the_draw(self):
        """Ohne manuellen Eintrag: der Elfer-Sieger aus der Fixture-Zeile
        genuegt, um den Tipp 1:1 in der Elfer-Runde NICHT als Remis zu werten.
        Genau das ging in der alten Kopie verloren (dort gab es 6 Punkte)."""
        results = played_results([KO_FIXTURE], {"results": {}})
        rounds = self._eval(results)
        self.assertEqual(rounds[DEFAULT_ROUND_ID]["points"], 0)
        self.assertEqual(rounds[SECONDARY_ROUND_ID]["points"], 8)


if __name__ == "__main__":
    unittest.main()
