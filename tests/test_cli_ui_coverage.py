from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.cli import build_parser
from wm_tipps.dashboard import CLI_UI_COMMANDS, build_cli_ui_coverage


def cli_command_names() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        if getattr(action, "choices", None):
            return set(action.choices)
    return set()


class CliUiCoverageTests(unittest.TestCase):
    def test_every_cli_command_has_ui_coverage_entry(self):
        self.assertEqual(cli_command_names(), {row["command"] for row in CLI_UI_COMMANDS})

    def test_coverage_rows_are_dashboard_ready(self):
        payload = {
            "fixture_count": 1,
            "news": [],
            "markets": {"odds": [], "markets": []},
            "odds_coverage": {"summary": {"with_consensus": 0, "total": 1}},
            "exact_score_odds": {"summary": {}},
            "team_intel": {"summary": {}, "matchday_checklist": []},
            "source_watch": {"sources": []},
            "predictions": [],
            "final_tips": [],
            "backtest_report": {"verdict": {"status": "needs_more_data"}},
            "matchday_dry_run": {},
            "matchday_command": {"summary": {}},
            "watch_state": {},
        }
        coverage = build_cli_ui_coverage(payload)
        self.assertEqual(coverage["summary"]["commands_total"], len(CLI_UI_COMMANDS))
        for row in coverage["commands"]:
            self.assertIn(row["status"], {"ok", "missing", "watch"})
            self.assertIsInstance(row["artifacts"], list)
            self.assertTrue(row["ui_section"])
            self.assertIn("runnable", row)
            self.assertIn("run_args", row)


if __name__ == "__main__":
    unittest.main()
