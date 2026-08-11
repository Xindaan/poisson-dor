from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.odds_history import (
    append_snapshots,
    load_snapshots,
    record_from_consensus,
    record_from_exact_score,
    summarize_movements,
)


def _consensus(match_id, home, draw, away, updated="2026-05-14T00:00:00+00:00"):
    return {
        "match_id": match_id,
        "last_updated": updated,
        "decimal_odds": {"home": home, "draw": draw, "away": away},
        "probabilities": {
            "home": round(1 / home, 4),
            "draw": round(1 / draw, 4),
            "away": round(1 / away, 4),
        },
        "overround": 1.05,
        "source_count": 5,
    }


class AppendOnChangeTests(unittest.TestCase):
    def test_unchanged_value_does_not_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.jsonl"
            rec = record_from_consensus(_consensus("gf-032", 1.92, 3.34, 4.28), observed_at="2026-06-14T10:00:00+00:00")
            first = append_snapshots([rec], path=path)
            self.assertEqual(first["appended"], 1)
            # gleicher Wert, spaeterer Zeitpunkt -> KEIN neuer Snapshot
            rec2 = record_from_consensus(_consensus("gf-032", 1.92, 3.34, 4.28), observed_at="2026-06-14T18:00:00+00:00")
            second = append_snapshots([rec2], path=path)
            self.assertEqual(second["appended"], 0)
            self.assertEqual(len(load_snapshots(path)), 1)

    def test_changed_value_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.jsonl"
            append_snapshots([record_from_consensus(_consensus("gf-032", 1.92, 3.34, 4.28), observed_at="2026-06-14T10:00:00+00:00")], path=path)
            moved = append_snapshots([record_from_consensus(_consensus("gf-032", 1.80, 3.40, 4.80), observed_at="2026-06-15T01:00:00+00:00")], path=path)
            self.assertEqual(moved["appended"], 1)
            self.assertEqual(len(load_snapshots(path)), 2)

    def test_exact_score_change_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.jsonl"
            item_a = {"match_id": "ga-001", "observed_at": "2026-06-14T10:03:00+00:00", "prices": [{"score": "1:0", "decimal_odds": 5.25}]}
            item_b = {"match_id": "ga-001", "observed_at": "2026-06-14T14:19:00+00:00", "prices": [{"score": "1:0", "decimal_odds": 5.5}]}
            append_snapshots([record_from_exact_score(item_a)], path=path)
            res = append_snapshots([record_from_exact_score(item_b)], path=path)
            self.assertEqual(res["appended"], 1)


class SummaryTests(unittest.TestCase):
    def test_movement_summary_flags_moved(self):
        snaps = [
            record_from_consensus(_consensus("gf-032", 1.92, 3.34, 4.28), observed_at="2026-06-14T10:00:00+00:00"),
            record_from_consensus(_consensus("gf-032", 1.80, 3.40, 4.80), observed_at="2026-06-15T01:00:00+00:00"),
            record_from_consensus(_consensus("ge-026", 2.9, 3.2, 2.5), observed_at="2026-06-14T10:00:00+00:00"),
        ]
        summary = summarize_movements(snaps)
        self.assertEqual(summary["snapshot_count"], 3)
        self.assertEqual(summary["keys"], 2)
        self.assertEqual(summary["moved_count"], 1)
        moved = next(m for m in summary["movements"] if m["match_id"] == "gf-032")
        self.assertTrue(moved["moved"])
        self.assertEqual(moved["snapshots"], 2)
        self.assertIsNotNone(moved["prob_drift"])
        still = next(m for m in summary["movements"] if m["match_id"] == "ge-026")
        self.assertFalse(still["moved"])


if __name__ == "__main__":
    unittest.main()
