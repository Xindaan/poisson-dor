from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.tip_snapshots import snapshot_tip, update_tip_snapshots
from wm_tipps.scoring import DEFAULT_ROUND_ID  # noqa: E402

NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
R = DEFAULT_ROUND_ID


def _pred(match_id, kickoff, tip):
    return {
        "match_id": match_id,
        "fixture": {"home_team": "A", "away_team": "B", "kickoff_utc": kickoff},
        "round_tips": {R: {"tip": tip}},
    }


class TipSnapshotTests(unittest.TestCase):
    def test_future_not_frozen_past_frozen(self):
        preds = [
            _pred("m1", "2026-06-20T19:00:00+00:00", "1:0"),  # zukunft
            _pred("m2", "2026-06-11T19:00:00+00:00", "2:1"),  # vergangen
        ]
        snaps = update_tip_snapshots(preds, existing={}, now=NOW, write=False)
        self.assertFalse(snaps["m1"]["frozen"])
        self.assertTrue(snaps["m2"]["frozen"])
        self.assertEqual(snaps["m1"]["round_tips"][R], "1:0")

    def test_frozen_not_overwritten(self):
        snaps = update_tip_snapshots([_pred("m2", "2026-06-11T19:00:00+00:00", "2:1")],
                                     existing={}, now=NOW, write=False)
        # Re-Build mit anderem Tipp -> eingefrorenes m2 bleibt 2:1.
        snaps = update_tip_snapshots([_pred("m2", "2026-06-11T19:00:00+00:00", "3:0")],
                                     existing=snaps, now=NOW, write=False)
        self.assertEqual(snaps["m2"]["round_tips"][R], "2:1")

    def test_future_updatable_until_kickoff(self):
        snaps = update_tip_snapshots([_pred("m1", "2026-06-20T19:00:00+00:00", "1:0")],
                                     existing={}, now=NOW, write=False)
        snaps = update_tip_snapshots([_pred("m1", "2026-06-20T19:00:00+00:00", "2:1")],
                                     existing=snaps, now=NOW, write=False)
        self.assertEqual(snaps["m1"]["round_tips"][R], "2:1")  # noch updatebar

    def test_snapshot_tip_helper(self):
        snaps = {"m1": {"round_tips": {"r": "1:0"}}}
        self.assertEqual(snapshot_tip(snaps, "m1", "r"), "1:0")
        self.assertIsNone(snapshot_tip(snaps, "m1", "x"))
        self.assertIsNone(snapshot_tip(snaps, "mX", "r"))


if __name__ == "__main__":
    unittest.main()
