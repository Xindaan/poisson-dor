from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.dashboard_server import command_specs, execute_ui_command


class DashboardServerTests(unittest.TestCase):
    def test_watch_command_is_finite_from_ui(self):
        self.assertEqual(
            command_specs()["watch"]["run_args"],
            ["watch", "--iterations", "1", "--sleep-cap", "0"],
        )

    def test_execute_uses_whitelisted_args(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok": true}',
            stderr="",
        )
        with patch("wm_tipps.dashboard_server.subprocess.run", return_value=completed) as run:
            result = execute_ui_command("lint", record=False, refresh_dashboard=False)

        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertEqual(command[-1], "lint")
        self.assertIn("-m", command)
        self.assertIn("wm_tipps.cli", command)

    def test_execute_marks_json_ok_false_as_failed(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok": false, "steps_failed": 1}',
            stderr="",
        )
        with patch("wm_tipps.dashboard_server.subprocess.run", return_value=completed):
            result = execute_ui_command("lint", record=False, refresh_dashboard=False)

        self.assertFalse(result["ok"])

    def test_execute_exposes_update_all_quality_warning(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok": true, "quality_status": "warning", "quality_messages": ["Bwin 0"], "steps_ok": 28, "steps_total": 29}',
            stderr="",
        )
        with patch("wm_tipps.dashboard_server.subprocess.run", return_value=completed):
            result = execute_ui_command("lint", record=False, refresh_dashboard=False)

        self.assertTrue(result["ok"])
        self.assertEqual(result["quality_status"], "warning")
        self.assertEqual(result["quality_messages"], ["Bwin 0"])
        self.assertEqual(result["steps_summary"], "28/29")

    def test_unknown_or_disabled_command_is_rejected(self):
        with self.assertRaises(ValueError):
            execute_ui_command("does-not-exist", record=False, refresh_dashboard=False)
        with self.assertRaises(ValueError):
            execute_ui_command("serve-dashboard", record=False, refresh_dashboard=False)


if __name__ == "__main__":
    unittest.main()
