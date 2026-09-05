from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.watcher import cadence_seconds, hours_until_next_kickoff


class WatcherHelperTests(unittest.TestCase):
    def test_hours_until_next_kickoff_picks_minimum_future(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        fixtures = [
            {"kickoff_utc": "2026-06-10T18:00:00+00:00"},  # +6h
            {"kickoff_utc": "2026-06-11T12:00:00+00:00"},  # +24h
            {"kickoff_utc": "2026-06-09T18:00:00+00:00"},  # vergangen
        ]
        self.assertAlmostEqual(hours_until_next_kickoff(fixtures, now=now), 6.0, places=3)

    def test_hours_until_next_kickoff_ignores_invalid_kickoff(self):
        now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
        fixtures = [
            {"kickoff_utc": "kaputt"},
            {"kickoff_utc": "2026-06-11T12:00:00+00:00"},
        ]
        self.assertAlmostEqual(hours_until_next_kickoff(fixtures, now=now), 24.0, places=3)

    def test_hours_until_next_kickoff_returns_none_when_empty(self):
        self.assertIsNone(hours_until_next_kickoff([]))

    def test_cadence_seconds_breakpoints(self):
        self.assertEqual(cadence_seconds(None), 24 * 3600)
        self.assertEqual(cadence_seconds(72), 24 * 3600)
        self.assertEqual(cadence_seconds(36), 6 * 3600)
        self.assertEqual(cadence_seconds(12), 2 * 3600)
        self.assertEqual(cadence_seconds(1), 15 * 60)


if __name__ == "__main__":
    unittest.main()
