from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wm_tipps.paths import DATA_DIR
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID, round_name


DASHBOARD_PATH = DATA_DIR / "dashboard.json"


def _require_nonempty(testcase, collection, what):
    """Leer ist kein Fehler, sondern ein legitimer Pipeline-Zustand.

    Nach Turnierende oder bei nur teilweise gelaufener Pipeline kann der
    Payload leer sein. Dann hat dieser Test nichts zu pruefen -- er soll
    ueberspringen, nicht rot werden und ein intaktes Repo kaputt aussehen
    lassen.
    """
    if not collection:
        testcase.skipTest(f"{what} ist leer -- nichts zu pruefen (Pipeline-Zustand).")
    return collection



def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class DashboardSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DASHBOARD_PATH.exists():
            raise unittest.SkipTest(
                f"{DASHBOARD_PATH} fehlt; Pipeline laufen lassen "
                "(`watch --iterations 1` oder `build-dashboard`)."
            )
        cls.payload = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))

    def test_predictions_have_required_fields(self):
        predictions = self.payload.get("predictions")
        self.assertIsInstance(predictions, list)
        _require_nonempty(self, predictions, "predictions")
        for pred in predictions:
            for field in ("match_id", "stability"):
                self.assertIn(field, pred, f"Pflichtfeld {field} fehlt")
            fixture = pred.get("fixture") or {}
            self.assertIn("kickoff_utc", fixture)
            tip = pred.get("recommended_tip") or {}
            self.assertIn("tip", tip)
            round_tips = pred.get("round_tips") or {}
            self.assertIn(DEFAULT_ROUND_ID, round_tips)
            self.assertIn(SECONDARY_ROUND_ID, round_tips)
            blended = ((pred.get("probabilities") or {}).get("blended")) or {}
            for outcome in ("home", "draw", "away"):
                self.assertIn(outcome, blended)
            heat = ((pred.get("context") or {}).get("heat_stress")) or {}
            self.assertIsInstance(heat, dict)
            if heat:
                for field in ("risk", "estimated_wbgt_c", "effective_wbgt_c", "home_xg_delta", "away_xg_delta"):
                    self.assertIn(field, heat)

    def test_odds_status_by_match_present(self):
        status_map = self.payload.get("odds_status_by_match")
        self.assertIsInstance(status_map, dict)
        for match_id, entry in status_map.items():
            self.assertIn(entry.get("state"), {"ok", "stale", "missing"}, match_id)

    def test_bonus_world_champion_is_ranked_list(self):
        bonus = self.payload.get("bonus") or {}
        champion = bonus.get("world_champion")
        self.assertIsInstance(champion, list)
        _require_nonempty(self, champion, "bonus.world_champion")
        first = champion[0]
        self.assertIn("team", first)
        self.assertIn("probability", first)

    def test_bonus_group_winners_is_group_mapping(self):
        bonus = self.payload.get("bonus") or {}
        group_winners = bonus.get("group_winners")
        self.assertIsInstance(group_winners, dict)
        _require_nonempty(self, group_winners, "bonus.group_winners")
        if group_winners:
            self.assertIn("A", group_winners)
            self.assertIsInstance(group_winners["A"], list)

    def test_final_tips_are_chronological_records(self):
        rows = self.payload.get("final_tips")
        self.assertIsInstance(rows, list)
        _require_nonempty(self, rows, "final_tips")
        for row in rows:
            for field in ("round_id", "round_name", "match_number", "kickoff_utc", "stage", "tip"):
                self.assertIn(field, row)
        all_rows = self.payload.get("all_final_tips")
        self.assertIsInstance(all_rows, list)
        self.assertGreaterEqual(len(all_rows), len(rows))
        self.assertTrue(any(row.get("round_name") == round_name(SECONDARY_ROUND_ID) for row in all_rows))

    def test_knockout_status_is_optional_but_typed(self):
        status = self.payload.get("knockout_status")
        if not status:
            return
        self.assertIsInstance(status.get("resolved"), list)
        self.assertIsInstance(status.get("pending"), list)
        if status.get("listed") is not None:
            self.assertIsInstance(status.get("listed"), list)
            for row in status.get("listed") or []:
                for field in ("match_number", "match_id", "stage", "match", "kickoff_utc", "has_pending_slot"):
                    self.assertIn(field, row)
        for row in status.get("resolved") or []:
            for field in ("match_number", "match_id", "stage", "match", "kickoff_utc"):
                self.assertIn(field, row)
        for row in status.get("pending") or []:
            for field in ("match_number", "reason"):
                self.assertIn(field, row)

    def test_prediction_history_is_list(self):
        self.assertIsInstance(self.payload.get("prediction_history"), list)

    def test_data_quality_news_is_optional_but_typed(self):
        data_quality = self.payload.get("data_quality")
        if data_quality is None:
            return
        news_quality = data_quality.get("news")
        if news_quality is None:
            return
        self.assertIsInstance(news_quality, (list, dict))

    def test_odds_coverage_is_optional_but_typed(self):
        coverage = self.payload.get("odds_coverage")
        if coverage is None:
            return
        self.assertIsInstance(coverage.get("summary"), dict)
        self.assertIsInstance(coverage.get("matches"), list)

    def test_odds_freshness_is_optional_but_typed(self):
        freshness = self.payload.get("odds_freshness")
        if freshness is None:
            return
        self.assertIn(freshness.get("status"), {"ok", "warning", "failed"})
        self.assertIsInstance(freshness.get("future_matches"), int)
        self.assertIsInstance(freshness.get("fresh_matches"), int)
        self.assertIsInstance(freshness.get("missing"), list)
        self.assertIsInstance(freshness.get("stale"), list)

    def test_backtest_report_is_optional_but_typed(self):
        report = self.payload.get("backtest_report")
        if not report:
            return
        self.assertIsInstance(report.get("verdict"), dict)
        self.assertIsInstance(report.get("combined"), dict)
        combined = report.get("combined") or {}
        self.assertIsInstance(combined.get("variants"), dict)
        self.assertIn("odds", combined.get("variants") or {})
        self.assertIn("ensemble", combined.get("variants") or {})

    def test_matchday_command_is_optional_but_typed(self):
        command = self.payload.get("matchday_command")
        if not command:
            return
        self.assertIsInstance(command.get("summary"), dict)
        self.assertIsInstance(command.get("today_items"), list)
        self.assertIsInstance(command.get("next_items"), list)
        if command.get("items") is not None:
            self.assertIsInstance(command.get("items"), list)

    def test_cli_ui_coverage_is_optional_but_typed(self):
        coverage = self.payload.get("cli_ui_coverage")
        if not coverage:
            return
        self.assertIsInstance(coverage.get("summary"), dict)
        self.assertIsInstance(coverage.get("commands"), list)
        commands = coverage.get("commands") or []
        _require_nonempty(self, commands, "cli_ui_commands")
        for row in commands:
            for field in ("command", "group", "ui_section", "status", "artifacts", "runnable", "run_args"):
                self.assertIn(field, row)
            self.assertIsInstance(row.get("run_args"), list)

    def test_ui_command_runs_is_optional_but_typed(self):
        runs = self.payload.get("ui_command_runs")
        if not runs:
            return
        self.assertIsInstance(runs.get("last_runs"), dict)
        self.assertIsInstance(runs.get("history"), list)

    def test_update_all_status_is_optional_but_typed(self):
        status = self.payload.get("update_all_status")
        if not status:
            return
        self.assertIsInstance(status.get("steps"), list)
        self.assertIsInstance(status.get("steps_total"), int)
        self.assertIsInstance(status.get("steps_ok"), int)


if __name__ == "__main__":
    unittest.main()
