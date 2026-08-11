from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps import lint
from wm_tipps.fixtures import all_teams, load_fixture_payload
from wm_tipps.paths import DATA_DIR


def fake_read_json(payloads):
    def _impl(path, default):
        return payloads.get(path.name, default)

    return _impl


class LintTests(unittest.TestCase):
    def test_strength_flags_missing_team(self):
        payloads = {
            "team_strength_inputs.json": {
                "_meta": {"updated_at": "2026-05-10"},
                "teams": {"Argentina": {"world_elo": 2100, "fifa_rank": 2}},
            }
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_team_strength_inputs(["Argentina", "Brazil"])
        joined = [i.get("team") for i in issues if i.get("issue") == "kein Eintrag"]
        self.assertIn("Brazil", joined)

    def test_strength_flags_missing_field(self):
        payloads = {
            "team_strength_inputs.json": {
                "_meta": {"updated_at": "2026-05-10"},
                "teams": {"Argentina": {"fifa_rank": 2}},
            }
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_team_strength_inputs(["Argentina"])
        self.assertTrue(any(i.get("issue") == "world_elo fehlt" for i in issues))

    def test_player_pool_flags_unknown_team(self):
        payloads = {
            "player_pool.json": {"players": {"Atlantis": [{"name": "X", "goal_share": 0.5}]}}
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_player_pool(["Argentina"])
        self.assertTrue(any(i.get("team") == "Atlantis" for i in issues))

    def test_player_pool_flags_goal_share_oversum(self):
        payloads = {
            "player_pool.json": {
                "players": {
                    "Argentina": [
                        {"name": "A", "goal_share": 0.6},
                        {"name": "B", "goal_share": 0.6},
                    ]
                }
            }
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_player_pool(["Argentina"])
        self.assertTrue(any("> 1.0" in i.get("issue", "") for i in issues))

    def test_repo_player_pool_covers_fixture_teams(self):
        teams = set(all_teams(load_fixture_payload()))
        payload = json.loads((DATA_DIR / "player_pool.json").read_text(encoding="utf-8"))
        players = payload["players"]
        self.assertEqual(set(players), teams)
        self.assertEqual(payload["_meta"]["coverage"], f"{len(teams)}/{len(teams)} Fixture-Teams mit mindestens einem Torschuetzen seit 2024.")
        for team, rows in players.items():
            # 3 Top-Torschuetzen plus optionale key_player-Zusaetze (goal_share 0).
            scorers = [p for p in rows if float(p.get("goal_share", 0.0)) > 0.0]
            self.assertEqual(len(scorers), 3, team)
            share_sum = sum(float(player["goal_share"]) for player in rows)
            self.assertLessEqual(share_sum, 1.0 + 1e-6, team)
            self.assertGreater(max(float(player["goal_share"]) for player in rows), 0.0, team)

    def test_manual_odds_flags_unknown_match_id(self):
        odds_rows = [{"match_id": "zz-999", "home": "1.5", "draw": "3.0", "away": "5.0"}]
        with mock.patch.object(lint, "read_csv_dicts", return_value=odds_rows):
            issues = lint.lint_manual_odds({"ga-001"})
        self.assertTrue(any("nicht im Spielplan" in i.get("issue", "") for i in issues))

    def test_manual_odds_flags_duplicate_source_for_match(self):
        odds_rows = [
            {"match_id": "ga-001", "source": "book", "home": "1.5", "draw": "3.0", "away": "5.0"},
            {"match_id": "ga-001", "source": "book", "home": "1.6", "draw": "3.0", "away": "5.0"},
        ]
        with mock.patch.object(lint, "read_csv_dicts", return_value=odds_rows):
            issues = lint.lint_manual_odds({"ga-001"})
        self.assertTrue(any("doppelt" in i.get("issue", "") for i in issues))

    def test_odds_coverage_emits_info_for_missing_and_single(self):
        fixtures = {
            "fixtures": [
                {"match_id": "ga-001", "home_team": "A", "away_team": "B", "kickoff_utc": "2026-06-11T19:00:00+00:00"},
                {"match_id": "ga-002", "home_team": "C", "away_team": "D", "kickoff_utc": "2026-06-12T02:00:00+00:00"},
            ]
        }
        # ga-001: nur eine Quelle -> single_source; ga-002: keine -> missing
        single_rows = [
            {"match_id": "ga-001", "source": "book1", "home": "2.0", "draw": "3.4", "away": "4.0"},
        ]
        with mock.patch.object(lint, "load_manual_odds", return_value=[
            {"match_id": "ga-001", "source": "book1",
             "probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
             "quality": {"status": "usable"}},
        ]):
            info = lint.lint_odds_coverage(fixtures)
        joined = " ".join(i["issue"] for i in info)
        self.assertIn("ohne Quoten-Konsensus", joined)
        self.assertTrue(all(i.get("severity") == "info" for i in info))

    def test_run_lint_separates_info_from_issues(self):
        result = lint.run_lint()
        self.assertIn("info", result)
        self.assertIn("count", result)
        # info zaehlt NICHT in count rein
        self.assertEqual(result["count"], len(result["issues"]))

    def test_manual_markets_flags_unknown_outcome(self):
        payloads = {
            "manual_markets.json": [
                {"category": "world_champion", "outcome": "Atlantis", "probability": 0.1}
            ]
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_manual_markets({"Argentina"})
        self.assertTrue(any(i.get("outcome") == "Atlantis" for i in issues))

    def test_manual_exact_scores_flags_invalid_rows(self):
        payloads = {
            "manual_exact_score_odds.json": {
                "visible_events": [{"match_id": "ga-001"}],
                "items": [
                    {
                        "match_id": "ga-001",
                        "prices": [
                            {"score": "1:0", "decimal_odds": "6.25"},
                            {"score": "1:0", "decimal_odds": "7.00"},
                            {"score": "bad", "decimal_odds": "1.00"},
                        ],
                    }
                ],
            }
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_manual_exact_scores({"ga-001"})
        joined = " ".join(issue.get("issue", "") for issue in issues)
        self.assertIn("Score doppelt 1:0", joined)
        self.assertIn("ungueltiger Score bad", joined)
        self.assertIn("ungueltige Quote fuer bad", joined)

    def test_team_intel_flags_unknown_team(self):
        payloads = {
            "team_intel_sources.json": {
                "sources": [
                    {
                        "id": "x",
                        "name": "X",
                        "url": "https://example.com",
                        "source_type": "official_federation_page",
                        "status": "manual_watch",
                        "reliability": "high",
                        "teams": ["Atlantis"],
                    }
                ]
            }
        }
        with mock.patch.object(lint, "read_json", side_effect=fake_read_json(payloads)):
            issues = lint.lint_team_intel_sources({"Argentina"})
        self.assertTrue(any(issue.get("team") == "Atlantis" for issue in issues))


if __name__ == "__main__":
    unittest.main()
