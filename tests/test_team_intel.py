from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from datetime import datetime, timezone

from wm_tipps.team_intel import (
    build_matchday_checklist,
    refresh_team_intel_sources,
    source_reachability_rows,
    source_status_from_probe,
    team_intel_report,
)
from wm_tipps.io import read_json, write_json
from wm_tipps import team_intel as team_intel_module


class TeamIntelTests(unittest.TestCase):
    def test_report_counts_sources_and_fixture_team_coverage(self):
        fixtures = {
            "fixtures": [
                {"home_team": "Canada", "away_team": "USA"},
                {"home_team": "Mexico", "away_team": "Germany"},
            ]
        }
        payload = {
            "sources": [
                {
                    "id": "fifa",
                    "official": True,
                    "source_type": "lineup_watch",
                    "status": "active_page",
                    "reliability": "high",
                    "signals": ["lineup"],
                    "teams": ["*"],
                },
                {
                    "id": "canada",
                    "official": True,
                    "source_type": "official_federation_rss",
                    "status": "active_rss",
                    "reliability": "high",
                    "teams": ["Canada"],
                },
                {
                    "id": "weather",
                    "official": True,
                    "source_type": "host_context",
                    "status": "active_page",
                    "reliability": "high",
                    "countries": ["USA"],
                    "signals": ["weather"],
                },
                {
                    "id": "mexico-json",
                    "official": True,
                    "source_type": "official_federation_json",
                    "status": "active_json",
                    "reliability": "high",
                    "teams": ["Mexico"],
                    "signals": ["squad"],
                },
            ]
        }
        report = team_intel_report(fixtures, payload)
        self.assertEqual(report["summary"]["source_count"], 4)
        self.assertEqual(report["summary"]["active_sources"], 4)
        self.assertEqual(report["summary"]["active_json_sources"], 1)
        self.assertEqual(report["summary"]["lineup_watch_sources"], 1)
        canada = next(row for row in report["teams"] if row["team"] == "Canada")
        self.assertEqual(canada["official_watch_count"], 2)
        self.assertEqual(canada["team_specific_official_count"], 1)
        usa = next(row for row in report["teams"] if row["team"] == "USA")
        self.assertEqual(usa["team_specific_official_count"], 0)
        self.assertIn("USA", report["missing_team_specific_official"])
        self.assertEqual(report["host_context"][0]["id"], "weather")

    def test_reachability_rows_bucket_status_and_freshness(self):
        rows = source_reachability_rows(
            [
                {
                    "id": "active",
                    "status": "active_page",
                    "checked_at": "2026-05-19T00:00:00+00:00",
                },
                {
                    "id": "blocked",
                    "status": "blocked_curl_manual_watch",
                    "checked_at": "2026-05-01T00:00:00+00:00",
                },
                {
                    "id": "json",
                    "status": "active_json",
                    "checked_at": "2026-05-19T00:00:00+00:00",
                },
                {"id": "unverified", "status": "manual_watch_unverified"},
            ],
            now=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["active"]["reachability"], "machine_reachable")
        self.assertEqual(by_id["active"]["freshness"], "fresh")
        self.assertEqual(by_id["json"]["reachability"], "machine_reachable")
        self.assertEqual(by_id["blocked"]["reachability"], "browser_or_manual")
        self.assertEqual(by_id["blocked"]["freshness"], "stale")
        self.assertEqual(by_id["unverified"]["freshness"], "needs_verification")

    def test_source_status_from_probe_buckets_live_probe_results(self):
        self.assertEqual(source_status_from_probe({"http_status": 200}), "active_page")
        self.assertEqual(
            source_status_from_probe(
                {"http_status": 200, "content_type": "application/json; charset=utf-8"}
            ),
            "active_json",
        )
        self.assertEqual(source_status_from_probe({"http_status": 302}), "active_page")
        self.assertEqual(
            source_status_from_probe({"http_status": 403}),
            "blocked_curl_manual_watch",
        )
        self.assertEqual(
            source_status_from_probe({"http_status": None}),
            "manual_watch_unverified",
        )

    def test_refresh_team_intel_sources_updates_only_requested_statuses(self):
        payload = {
            "_meta": {"note": "test"},
            "sources": [
                {
                    "id": "active-me",
                    "url": "https://example.test/active",
                    "status": "manual_watch_unverified",
                    "teams": ["Team A"],
                },
                {
                    "id": "blocked-me",
                    "url": "https://example.test/blocked",
                    "status": "manual_watch_unverified",
                    "teams": ["Team B"],
                },
                {
                    "id": "leave-me",
                    "url": "https://example.test/leave",
                    "status": "active_page",
                    "teams": ["Team C"],
                },
            ],
        }

        def fake_probe(url, timeout_seconds):
            self.assertEqual(timeout_seconds, 3)
            if url.endswith("/active"):
                return {
                    "http_status": 200,
                    "effective_url": url,
                    "content_type": "text/html",
                    "error": None,
                }
            return {
                "http_status": 403,
                "effective_url": url,
                "content_type": "text/html",
                "error": None,
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "team_intel_sources.json"
            write_json(path, payload)

            result = refresh_team_intel_sources(
                timeout_seconds=3,
                workers=2,
                probe_func=fake_probe,
                path=path,
            )

            self.assertEqual(result["probed"], 2)
            self.assertEqual(result["status_counts"]["active_page"], 1)
            self.assertEqual(result["status_counts"]["blocked_curl_manual_watch"], 1)

            updated = path.read_text(encoding="utf-8")
            self.assertIn('"last_reachability_refresh"', updated)
            self.assertIn('"status": "active_page"', updated)
            self.assertIn('"status": "blocked_curl_manual_watch"', updated)

    def test_refresh_team_intel_sources_can_target_specific_ids(self):
        payload = {
            "sources": [
                {
                    "id": "probe-me",
                    "url": "https://example.test/probe",
                    "status": "manual_watch_unverified",
                },
                {
                    "id": "skip-me",
                    "url": "https://example.test/skip",
                    "status": "manual_watch_unverified",
                },
            ],
        }

        def fake_probe(url, timeout_seconds):
            return {
                "http_status": 200,
                "effective_url": url,
                "content_type": "text/html",
                "error": None,
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "team_intel_sources.json"
            write_json(path, payload)

            result = refresh_team_intel_sources(
                ids={"probe-me"},
                probe_func=fake_probe,
                path=path,
            )

            updated = {row["id"]: row for row in read_json(path, {})["sources"]}
            self.assertEqual(result["probed"], 1)
            self.assertEqual(updated["probe-me"]["status"], "active_page")
            self.assertEqual(updated["skip-me"]["status"], "manual_watch_unverified")

    def test_refresh_team_intel_sources_does_not_touch_file_without_candidates(self):
        payload = {
            "_meta": {"updated_at": "before"},
            "sources": [
                {
                    "id": "skip-me",
                    "url": "https://example.test/skip",
                    "status": "active_page",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "team_intel_sources.json"
            write_json(path, payload)

            result = refresh_team_intel_sources(
                ids={"missing-id"},
                probe_func=lambda url, timeout_seconds: {"http_status": 200},
                path=path,
            )

            self.assertEqual(result["probed"], 0)
            self.assertEqual(read_json(path, {})["_meta"]["updated_at"], "before")

    def test_matchday_checklist_adds_due_times_and_sources(self):
        fixtures = {
            "fixtures": [
                {
                    "match_id": "ga-001",
                    "match_number": 1,
                    "home_team": "Mexico",
                    "away_team": "South Africa",
                    "kickoff_utc": "2026-06-11T19:00:00+00:00",
                    "venue": "Mexico City",
                }
            ]
        }
        payload = {
            "sources": [
                {
                    "id": "fifa",
                    "official": True,
                    "source_type": "lineup_watch",
                    "status": "active_page",
                    "signals": ["confirmed_lineup"],
                    "teams": ["*"],
                },
                {
                    "id": "mexico",
                    "official": True,
                    "source_type": "official_federation_page",
                    "status": "active_page",
                    "teams": ["Mexico"],
                    "signals": ["squad"],
                },
                {
                    "id": "weather",
                    "official": True,
                    "source_type": "host_context",
                    "status": "active_page",
                    "countries": ["Mexico"],
                    "signals": ["weather"],
                },
            ]
        }
        # host_country kommt sonst aus data/context.json -- einer generierten,
        # nicht getrackten Datei. Der Test darf nicht davon abhaengen, ob die
        # Pipeline auf dieser Maschine schon mal gelaufen ist (frischer Clone).
        original_load_context = team_intel_module.load_context
        team_intel_module.load_context = lambda: {
            "fixtures": {"ga-001": {"host_country": "Mexico"}}
        }
        try:
            rows = build_matchday_checklist(
                fixtures,
                payload,
                now=datetime(2026, 5, 19, tzinfo=timezone.utc),
            )
        finally:
            team_intel_module.load_context = original_load_context
        self.assertEqual(len(rows), 1)
        row = rows[0]
        due = {check["type"]: check["due_at"] for check in row["checks"]}
        self.assertEqual(due["confirmed_lineup"], "2026-06-11T17:30:00+00:00")
        self.assertEqual(due["weather_first_pass"], "2026-06-08T19:00:00+00:00")
        self.assertIn("official_team_source:South Africa", row["missing"])
        self.assertIn("weather", row["source_ids"])


if __name__ == "__main__":
    unittest.main()
