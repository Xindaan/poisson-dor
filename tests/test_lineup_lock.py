from pathlib import Path
from datetime import datetime, timezone
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.lineup_lock import lineup_lock_status


def _fx(mid, kickoff, status="scheduled", home="Aland", away="Bland"):
    return {"match_id": mid, "kickoff_utc": kickoff, "status": status, "home": home, "away": away}


class LineupLockTests(unittest.TestCase):
    def test_window_selects_only_upcoming_in_window(self):
        now = datetime(2026, 6, 14, 17, 0, tzinfo=timezone.utc)
        fixtures = [
            _fx("m1", "2026-06-14T17:30:00+00:00"),        # +30min -> im Fenster
            _fx("m2", "2026-06-14T20:00:00+00:00"),        # +3h -> raus
            _fx("m3", "2026-06-14T10:00:00+00:00", "played"),  # gespielt -> raus
        ]
        rep = lineup_lock_status([], fixtures, [], now=now, window_minutes=90)
        self.assertEqual(rep["in_window"], 1)
        self.assertEqual(rep["matches"][0]["match_id"], "m1")
        self.assertEqual(rep["matches"][0]["home_lineup"], "none")
        self.assertFalse(rep["matches"][0]["lockable"])

    def test_night_match_flag(self):
        now = datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc)
        fixtures = [_fx("m1", "2026-06-15T00:00:00+00:00")]  # 02:00 CEST -> Nachtspiel
        rep = lineup_lock_status([], fixtures, [], now=now, window_minutes=120)
        self.assertEqual(rep["in_window"], 1)
        self.assertTrue(rep["matches"][0]["is_night_match"])


if __name__ == "__main__":
    unittest.main()
