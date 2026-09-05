from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import datetime, timezone

from wm_tipps.matchday_dry_run import build_matchday_dry_run
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID


class MatchdayDryRunTests(unittest.TestCase):
    def test_dry_run_checks_matchday_windows_and_chronology(self):
        fixtures = {
            "fixtures": [
                {
                    "match_id": "m1",
                    "match_number": 1,
                    "kickoff_utc": "2026-06-11T19:00:00+00:00",
                    "home_team": "Mexico",
                    "away_team": "South Africa",
                    "venue": "Mexico City",
                    "group": "A",
                }
            ]
        }
        predictions = {
            "predictions": [
                {
                    "match_id": "m1",
                    "fixture": fixtures["fixtures"][0],
                    "recommended_tip": {"tip": "1:0", "expected_points": 1.2},
                    "round_tips": {
                        DEFAULT_ROUND_ID: {"tip": "1:0", "expected_points": 1.2},
                        SECONDARY_ROUND_ID: {"tip": "1:0", "expected_points": 1.2},
                    },
                    "stability": "stabil",
                    "news": [],
                }
            ]
        }
        team_intel = {
            "sources": [
                {
                    "id": "global-lineups",
                    "official": True,
                    "source_type": "lineup_watch",
                    "status": "active_page",
                    "teams": ["*"],
                    "signals": ["lineup"],
                },
                {
                    "id": "mexico",
                    "official": True,
                    "source_type": "official_federation_page",
                    "status": "active_page",
                    "teams": ["Mexico"],
                },
                {
                    "id": "south-africa",
                    "official": True,
                    "source_type": "official_federation_page",
                    "status": "active_page",
                    "teams": ["South Africa"],
                },
            ]
        }

        report = build_matchday_dry_run(
            fixtures,
            predictions,
            team_intel,
            {"events": []},
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            write=False,
        )

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["target_match"]["match_id"], "m1")
        self.assertEqual(report["counts"]["final_tips"], 1)
        self.assertEqual(report["counts"]["all_round_final_tips"], 2)
        by_label = {row["label"]: row for row in report["scenarios"]}
        self.assertEqual(by_label["T-48h"]["status"], "pre_match_window")
        self.assertIn("travel_context", by_label["T-48h"]["due_checks"])
        self.assertEqual(by_label["T-90m"]["status"], "confirmed_lineup_window")
        self.assertIn("confirmed_lineup", by_label["T-90m"]["due_checks"])

    def test_dry_run_flags_same_tip_history_noise(self):
        fixtures = {
            "fixtures": [
                {
                    "match_id": "m1",
                    "match_number": 1,
                    "kickoff_utc": "2026-06-11T19:00:00+00:00",
                    "home_team": "Mexico",
                    "away_team": "South Africa",
                }
            ]
        }
        predictions = {"predictions": []}
        team_intel = {"sources": []}
        history = {"events": [{"match_id": "m1", "match": "Mexico - South Africa", "from_tip": "1:0", "to_tip": "1:0"}]}

        report = build_matchday_dry_run(
            fixtures,
            predictions,
            team_intel,
            history,
            now=datetime(2026, 5, 20, tzinfo=timezone.utc),
            write=False,
        )

        self.assertEqual(report["status"], "review")
        checks = {row["id"]: row for row in report["checks"]}
        self.assertEqual(checks["history_only_tip_changes"]["status"], "review")


if __name__ == "__main__":
    unittest.main()
