from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.odds import (
    consensus_odds,
    match_odds_freshness,
    match_odds_quality,
    normalize_decimal_odds,
    odds_coverage,
    odds_by_match,
    odds_overround,
    market_quality,
)


class OddsTests(unittest.TestCase):
    def test_normalize_decimal_odds_removes_overround(self):
        probabilities = normalize_decimal_odds({"home": "2.00", "draw": "3.50", "away": "4.00"})
        self.assertAlmostEqual(sum(probabilities.values()), 1.0)
        self.assertGreater(probabilities["home"], probabilities["away"])

    def test_match_odds_quality_uses_overround(self):
        self.assertGreater(odds_overround({"home": "1.50", "draw": "3.80", "away": "6.00"}), 1.0)
        self.assertEqual(
            match_odds_quality({"home": "1.50", "draw": "3.80", "away": "6.00"})["status"],
            "usable",
        )
        bad = match_odds_quality({"home": "1.10", "draw": "1.20", "away": "1.30"})
        self.assertEqual(bad["status"], "watch_only")
        self.assertIn("overround_high", bad["reasons"])

    def test_match_odds_quality_allows_best_odds_underround_sources(self):
        odds = {"home": "2.10", "draw": "3.50", "away": "5.20"}
        self.assertLess(odds_overround(odds), 1.0)
        for source in (
            "sportytrader_world_cup_2026",
            "oddschecker_us_world_cup_2026",
            "odds_school_world_cup_2026",
            "wincomparator_world_cup_2026",
        ):
            with self.subTest(source=source):
                quality = match_odds_quality(odds, source=source)
                self.assertEqual(quality["status"], "usable")

        regular = match_odds_quality(odds, source="regular_bookmaker")
        self.assertEqual(regular["status"], "watch_only")
        self.assertIn("overround_low", regular["reasons"])

    def test_consensus_odds_averages_no_vig_probabilities(self):
        rows = [
            {
                "match_id": "m1",
                "source": "a",
                "last_updated": "2026-05-11T10:00:00+00:00",
                "decimal_odds": {"home": 2.0, "draw": 3.5, "away": 4.0},
                "probabilities": normalize_decimal_odds({"home": 2.0, "draw": 3.5, "away": 4.0}),
                "overround": odds_overround({"home": 2.0, "draw": 3.5, "away": 4.0}),
                "quality": {"status": "usable", "reasons": []},
            },
            {
                "match_id": "m1",
                "source": "b",
                "last_updated": "2026-05-11T11:00:00+00:00",
                "decimal_odds": {"home": 2.2, "draw": 3.3, "away": 3.8},
                "probabilities": normalize_decimal_odds({"home": 2.2, "draw": 3.3, "away": 3.8}),
                "overround": odds_overround({"home": 2.2, "draw": 3.3, "away": 3.8}),
                "quality": {"status": "usable", "reasons": []},
            },
        ]
        result = consensus_odds("m1", rows)
        self.assertEqual(result["source"], "consensus_2_sources")
        self.assertEqual(result["source_count"], 2)
        self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0, places=3)

    def test_consensus_odds_excludes_sources_older_than_latest_cohort(self):
        rows = []
        for source, updated, home in (
            ("stale", "2026-05-11T10:00:00+00:00", 2.4),
            ("fresh_a", "2026-06-20T10:00:00+00:00", 1.8),
            ("fresh_b", "2026-06-20T12:00:00+00:00", 1.9),
        ):
            odds = {"home": home, "draw": 3.5, "away": 4.0}
            rows.append({
                "match_id": "m1",
                "source": source,
                "last_updated": updated,
                "decimal_odds": odds,
                "probabilities": normalize_decimal_odds(odds),
                "overround": odds_overround(odds),
                "quality": {"status": "usable", "reasons": []},
            })

        result = consensus_odds("m1", rows)

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["sources"], ["fresh_a", "fresh_b"])

    def test_consensus_odds_keeps_history_when_only_one_source_is_fresh(self):
        rows = []
        for source, updated, home in (
            ("older_a", "2026-05-11T10:00:00+00:00", 2.0),
            ("older_b", "2026-05-11T11:00:00+00:00", 2.1),
            ("fresh", "2026-06-20T12:00:00+00:00", 1.9),
        ):
            odds = {"home": home, "draw": 3.5, "away": 4.0}
            rows.append({
                "match_id": "m1",
                "source": source,
                "last_updated": updated,
                "decimal_odds": odds,
                "probabilities": normalize_decimal_odds(odds),
                "overround": odds_overround(odds),
                "quality": {"status": "usable", "reasons": []},
            })

        result = consensus_odds("m1", rows)

        self.assertEqual(result["source_count"], 3)

    def test_consensus_odds_drops_clear_outlier_when_two_sources_agree(self):
        rows = []
        for source, odds in (
            ("a", {"home": 1.5, "draw": 3.8, "away": 6.0}),
            ("b", {"home": 1.5, "draw": 3.8, "away": 6.0}),
            ("outlier", {"home": 3.0, "draw": 2.0, "away": 3.0}),
        ):
            rows.append({
                "match_id": "m1",
                "source": source,
                "last_updated": "2026-05-11T10:00:00+00:00",
                "decimal_odds": odds,
                "probabilities": normalize_decimal_odds(odds),
                "overround": odds_overround(odds),
                "quality": {"status": "usable", "reasons": []},
            })
        result = consensus_odds("m1", rows)
        self.assertEqual(result["source_count"], 2)
        self.assertNotIn("outlier", result["sources"])

    def test_odds_by_match_aggregates_duplicate_sources(self):
        rows = []
        for source, home in (("a", 2.0), ("b", 2.2)):
            rows.append({
                "match_id": "m1",
                "source": source,
                "last_updated": "2026-05-11T10:00:00+00:00",
                "decimal_odds": {"home": home, "draw": 3.5, "away": 4.0},
                "probabilities": normalize_decimal_odds({"home": home, "draw": 3.5, "away": 4.0}),
                "overround": odds_overround({"home": home, "draw": 3.5, "away": 4.0}),
                "quality": {"status": "usable", "reasons": []},
            })
        self.assertEqual(odds_by_match(rows)["m1"]["source_count"], 2)

    def test_consensus_odds_deduplicates_same_source(self):
        rows = []
        for updated, home in (
            ("2026-05-11T10:00:00+00:00", 1.9),
            ("2026-05-11T11:00:00+00:00", 2.1),
        ):
            rows.append({
                "match_id": "m1",
                "source": "same_source",
                "last_updated": updated,
                "decimal_odds": {"home": home, "draw": 3.5, "away": 4.0},
                "probabilities": normalize_decimal_odds({"home": home, "draw": 3.5, "away": 4.0}),
                "overround": odds_overround({"home": home, "draw": 3.5, "away": 4.0}),
                "quality": {"status": "usable", "reasons": []},
            })
        result = consensus_odds("m1", rows)
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["last_updated"], "2026-05-11T11:00:00+00:00")
        self.assertAlmostEqual(result["decimal_odds"]["home"], 2.1)

    def test_odds_by_match_ignores_incomplete_match_odds(self):
        rows = [
            {
                "match_id": "m1",
                "source": "partial",
                "last_updated": "2026-05-11T10:00:00+00:00",
                "decimal_odds": {"home": 2.0, "draw": None, "away": 4.0},
                "probabilities": normalize_decimal_odds({"home": 2.0, "draw": "", "away": 4.0}),
                "overround": None,
                "quality": {"status": "watch_only", "reasons": ["incomplete_or_invalid"]},
            }
        ]
        self.assertNotIn("m1", odds_by_match(rows))

    def test_odds_coverage_summarizes_missing_and_consensus(self):
        fixtures = [
            {"match_id": "m1", "match_number": 1, "kickoff_utc": "2026-06-11T19:00:00+00:00", "home_team": "A", "away_team": "B"},
            {"match_id": "m2", "match_number": 2, "kickoff_utc": "2026-06-12T19:00:00+00:00", "home_team": "C", "away_team": "D"},
        ]
        rows = []
        for source, home in (("a", 2.0), ("b", 2.2)):
            odds = {"home": home, "draw": 3.5, "away": 4.0}
            rows.append({
                "match_id": "m1",
                "source": source,
                "last_updated": "2026-05-11T10:00:00+00:00",
                "decimal_odds": odds,
                "probabilities": normalize_decimal_odds(odds),
                "overround": odds_overround(odds),
                "quality": {"status": "usable", "reasons": []},
            })
        coverage = odds_coverage(fixtures, rows)
        self.assertEqual(coverage["summary"]["total"], 2)
        self.assertEqual(coverage["summary"]["with_consensus"], 1)
        self.assertEqual(coverage["summary"]["missing"], 1)
        self.assertEqual(coverage["matches"][0]["status"], "ok")
        self.assertEqual(coverage["matches"][1]["status"], "missing")

    def test_market_quality_filters_bad_data(self):
        now = datetime.now(timezone.utc)
        quality = market_quality(0.12, 50, (now - timedelta(hours=30)).isoformat(), now=now)
        self.assertEqual(quality["status"], "watch_only")
        self.assertIn("spread_wide", quality["reasons"])
        self.assertIn("liquidity_thin", quality["reasons"])
        self.assertIn("stale", quality["reasons"])

    def test_market_quality_accepts_good_data(self):
        now = datetime.now(timezone.utc)
        quality = market_quality(0.03, 5000, now.isoformat(), now=now)
        self.assertEqual(quality["status"], "usable")

    def test_market_quality_accepts_bookmaker_futures_without_liquidity(self):
        now = datetime.now(timezone.utc)
        quality = market_quality(
            None,
            None,
            now.isoformat(),
            probability=0.14,
            source_type="bookmaker_futures",
            now=now,
        )
        self.assertEqual(quality["status"], "usable")

    def test_match_odds_freshness_flags_partial_bwin_coverage(self):
        now = datetime(2026, 6, 18, 20, 0, tzinfo=timezone.utc)
        fixtures = [
            {"match_id": "m1", "match_number": 1, "kickoff_utc": "2026-06-18T22:00:00+00:00", "home_team": "A", "away_team": "B"},
            {"match_id": "m2", "match_number": 2, "kickoff_utc": "2026-06-19T01:00:00+00:00", "home_team": "C", "away_team": "D"},
            {"match_id": "past", "match_number": 3, "kickoff_utc": "2026-06-18T18:00:00+00:00", "home_team": "E", "away_team": "F"},
        ]
        odds = [
            {
                "match_id": "m1",
                "source": "bwin_world_cup_2026",
                "last_updated": "2026-06-18T19:30:00+00:00",
                "decimal_odds": {"home": 1.8, "draw": 3.5, "away": 4.5},
            },
            {
                "match_id": "past",
                "source": "bwin_world_cup_2026",
                "last_updated": "2026-06-18T19:30:00+00:00",
                "decimal_odds": {"home": 1.8, "draw": 3.5, "away": 4.5},
            },
        ]

        report = match_odds_freshness(fixtures, odds, now=now)

        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["future_matches"], 2)
        self.assertEqual(report["fresh_matches"], 1)
        self.assertEqual(report["missing_matches"], 1)
        self.assertEqual(report["missing"][0]["match_id"], "m2")

    def test_match_odds_freshness_fails_when_no_future_match_is_fresh(self):
        now = datetime(2026, 6, 18, 20, 0, tzinfo=timezone.utc)
        fixtures = [
            {"match_id": "m1", "match_number": 1, "kickoff_utc": "2026-06-18T22:00:00+00:00", "home_team": "A", "away_team": "B"},
        ]
        odds = [
            {
                "match_id": "m1",
                "source": "bwin_world_cup_2026",
                "last_updated": "2026-06-17T10:00:00+00:00",
                "decimal_odds": {"home": 1.8, "draw": 3.5, "away": 4.5},
            },
        ]

        report = match_odds_freshness(fixtures, odds, now=now, max_age_hours=24)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["fresh_matches"], 0)
        self.assertEqual(report["stale_matches"], 1)


if __name__ == "__main__":
    unittest.main()
