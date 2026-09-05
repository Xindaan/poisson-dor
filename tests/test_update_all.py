from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.update_all import (
    POOL_ANALYTICS_AVAILABLE,
    build_update_quality_gates,
    default_update_steps,
    run_update_all,
    summarize_result,
)


class DefaultStepsTests(unittest.TestCase):
    def test_diagnostics_are_in_default_steps(self):
        # Regression T-0089/T-0090-Folge: die Diagnose-Karten lesen aus
        # eigenen JSONs -> update-all (der Button) MUSS sie neu schreiben,
        # sonst driften sie (eval-live/blend-sweep/calibrate-fit/strategy-ab
        # fehlten frueher -> stale trotz regelmaessigem update-all).
        names = [
            spec[0]
            for spec in default_update_steps(
                {},
                live_news=False,
                refresh_fixture_source=False,
                probe_live_sources=False,
                refresh_exact_scores=True,
                refresh_match_odds=True,
                refresh_team_intel=True,
                refresh_player_pool=False,
                include_backtest_report=True,
            )
        ]
        for need in ("eval-live", "blend-sweep", "calibrate-fit", "strategy-ab",
                     "favorite-calibration", "news-audit"):
            self.assertIn(need, names)
        # Pool-Analytik ist optional (fehlt in der oeffentlichen Verteilung).
        for need in ("risk-dial", "rival-profiles", "deficit-policy"):
            if POOL_ANALYTICS_AVAILABLE:
                self.assertIn(need, names)
            else:
                self.assertNotIn(need, names)
        self.assertLess(names.index("refresh-bwin-match-odds"), names.index("refresh-odds"))
        self.assertLess(names.index("refresh-odds"), names.index("source-watch"))
        self.assertLess(names.index("reconcile-knockout-results"), names.index("export-tips"))

    def test_backtest_diagnostics_gated(self):
        names = [
            spec[0]
            for spec in default_update_steps(
                {},
                live_news=False,
                refresh_fixture_source=False,
                probe_live_sources=False,
                refresh_exact_scores=False,
                refresh_match_odds=False,
                refresh_team_intel=False,
                refresh_player_pool=False,
                include_backtest_report=False,
            )
        ]
        # eval-live ist nicht backtest-gebunden -> immer; blend-sweep schon.
        self.assertIn("eval-live", names)
        self.assertNotIn("blend-sweep", names)


class UpdateAllTests(unittest.TestCase):
    def test_update_all_continues_after_step_failure(self):
        calls = []

        def ok_step():
            calls.append("ok")
            return {"items": [1, 2, 3]}

        def bad_step():
            calls.append("bad")
            raise RuntimeError("boom")

        result = run_update_all(
            write=False,
            steps=[
                ("ok", "OK", ok_step),
                ("bad", "Bad", bad_step),
                ("after", "After", ok_step),
            ],
        )

        self.assertEqual(calls, ["ok", "bad", "ok"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["steps_total"], 3)
        self.assertEqual(result["steps_ok"], 2)
        self.assertEqual(result["failed_steps"], ["bad"])
        self.assertEqual(result["steps"][0]["summary"]["items"], 3)
        self.assertEqual(result["steps"][1]["error_type"], "RuntimeError")

    def test_update_all_reports_all_ok(self):
        result = run_update_all(
            write=False,
            steps=[
                ("one", "One", lambda: {"predictions": [{}, {}]}),
                ("two", "Two", lambda: {"odds": [1], "markets": [2]}),
            ],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["steps_ok"], 2)
        self.assertEqual(result["steps"][0]["summary"]["predictions"], 2)
        self.assertEqual(result["steps"][1]["summary"]["odds"], 1)
        self.assertEqual(result["steps"][1]["summary"]["markets"], 1)

    def test_bwin_match_odds_can_run_when_exact_scores_are_skipped(self):
        names = [
            spec[0]
            for spec in default_update_steps(
                {},
                live_news=False,
                refresh_fixture_source=False,
                probe_live_sources=False,
                refresh_exact_scores=False,
                refresh_match_odds=True,
                refresh_team_intel=False,
                refresh_player_pool=False,
                include_backtest_report=False,
            )
        ]

        self.assertNotIn("refresh-bwin-exact-scores", names)
        self.assertIn("refresh-bwin-match-odds", names)
        self.assertLess(names.index("refresh-bwin-match-odds"), names.index("refresh-odds"))

    def test_reconcile_knockout_results_rebuilds_predictions_when_fixtures_change(self):
        shared = {
            "fixtures": {
                "fixtures": [
                    {"match_id": "ko-086", "match_number": 86, "stage": "round_of_32", "status": "scheduled"}
                ]
            }
        }
        refreshed = {
            "fixtures": [
                {
                    "match_id": "ko-086",
                    "match_number": 86,
                    "stage": "round_of_32",
                    "status": "played",
                    "result": [3, 2],
                },
                {
                    "match_id": "ko-095",
                    "match_number": 95,
                    "stage": "round_of_16",
                    "status": "scheduled",
                    "home_team": "Argentina",
                    "away_team": "Egypt",
                },
            ]
        }
        predictions = {"predictions": [{"match_id": "ko-095"}]}
        with patch("wm_tipps.update_all.refresh_fixtures", return_value=refreshed), patch(
            "wm_tipps.update_all.refresh_bwin_match_odds",
            return_value={"_meta": {"events_probed": 1, "matches_with_odds": 1}},
        ) as odds, patch("wm_tipps.update_all.refresh_market_data", return_value={"odds": []}) as markets, patch(
            "wm_tipps.update_all.refresh_context", return_value={}
        ) as context, patch("wm_tipps.update_all.build_predictions", return_value=predictions) as build, patch(
            "wm_tipps.update_all.build_matchday_command_center", return_value={}
        ) as command, patch("wm_tipps.update_all.build_matchday_dry_run", return_value={}) as dry_run:
            step = next(
                spec
                for spec in default_update_steps(
                    shared,
                    live_news=False,
                    refresh_fixture_source=False,
                    probe_live_sources=False,
                    refresh_exact_scores=False,
                    refresh_match_odds=True,
                    refresh_team_intel=False,
                    refresh_player_pool=False,
                    include_backtest_report=False,
                )
                if spec[0] == "reconcile-knockout-results"
            )
            result = step[2]()

        self.assertTrue(result["summary"]["fixtures_changed"])
        self.assertTrue(result["summary"]["predictions_rebuilt"])
        self.assertIs(shared["fixtures"], refreshed)
        self.assertIs(shared["predictions"], predictions)
        odds.assert_called_once()
        markets.assert_called_once()
        context.assert_called_once_with(refreshed["fixtures"])
        build.assert_called_once()
        command.assert_called_once_with(refreshed, predictions, write=True)
        dry_run.assert_called_once_with(refreshed, predictions, write=True)

    def test_update_summary_includes_bwin_csv_counts(self):
        summary = summarize_result(
            {
                "_meta": {
                    "updated_at": "2026-06-18T18:00:00+00:00",
                    "events_probed": 24,
                    "matches_with_odds": 16,
                    "csv_rows_updated": 12,
                    "csv_rows_added": 4,
                },
                "items": [{"status": "ok"}],
            }
        )

        self.assertEqual(summary["items"], 1)
        self.assertEqual(summary["events_probed"], 24)
        self.assertEqual(summary["matches_with_odds"], 16)
        self.assertEqual(summary["csv_rows_updated"], 12)
        self.assertEqual(summary["csv_rows_added"], 4)

    def test_summarize_result_keeps_payload_compact(self):
        summary = summarize_result(
            {
                "predictions": [{"match_id": "a"}],
                "bonus": {"world_champion": []},
                "very_large": [{"x": 1}] * 100,
            }
        )

        self.assertEqual(summary["predictions"], 1)
        self.assertEqual(summary["bonus_blocks"], 1)
        self.assertNotIn("very_large", summary)

    def test_quality_gate_warns_when_bwin_import_writes_no_odds(self):
        step_rows = [
            {
                "name": "refresh-bwin-match-odds",
                "ok": True,
                "summary": {
                    "events_probed": 24,
                    "matches_with_odds": 0,
                    "csv_rows_updated": 0,
                    "csv_rows_added": 0,
                },
            }
        ]
        with patch("wm_tipps.update_all.read_json", return_value={"fixtures": [], "odds": []}), patch(
            "wm_tipps.update_all.match_odds_freshness",
            return_value={
                "status": "ok",
                "status_detail": "44/44 kommende Spiele haben frische Bwin-Quoten.",
                "future_matches": 44,
                "fresh_matches": 44,
                "missing_matches": 0,
                "stale_matches": 0,
                "missing": [],
                "stale": [],
            },
        ):
            quality = build_update_quality_gates(step_rows, refresh_match_odds=True)

        self.assertEqual(quality["status"], "warning")
        self.assertIn("0 1X2-Matchquoten", quality["messages"][0])

    def test_quality_gate_fails_when_no_upcoming_bwin_odds_are_fresh(self):
        step_rows = [
            {
                "name": "refresh-bwin-match-odds",
                "ok": True,
                "summary": {
                    "events_probed": 24,
                    "matches_with_odds": 0,
                    "csv_rows_updated": 0,
                    "csv_rows_added": 0,
                },
            }
        ]
        with patch("wm_tipps.update_all.read_json", return_value={"fixtures": [], "odds": []}), patch(
            "wm_tipps.update_all.match_odds_freshness",
            return_value={
                "status": "failed",
                "status_detail": "0/46 kommende Spiele haben frische Bwin-Quoten.",
                "future_matches": 46,
                "fresh_matches": 0,
                "missing_matches": 46,
                "stale_matches": 0,
                "missing": [{"match_id": "ga-004"}],
                "stale": [],
            },
        ):
            quality = build_update_quality_gates(step_rows, refresh_match_odds=True)

        self.assertEqual(quality["status"], "failed")
        self.assertTrue(any(gate["name"] == "bwin-freshness" for gate in quality["gates"]))


if __name__ == "__main__":
    unittest.main()
