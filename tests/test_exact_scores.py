from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.exact_scores import (
    build_exact_score_comparison,
    exact_score_calibration_decision,
    market_probabilities,
    normalise_exact_score_items,
)


class ExactScoreTests(unittest.TestCase):
    def test_normalise_prices_and_quality(self):
        items = normalise_exact_score_items(
            [
                {
                    "match_id": "ga-001",
                    "market": "exact_score_regular_time",
                    "has_other_selection": True,
                    "prices": [
                        {"score": "1:0", "decimal_odds": "6,25"},
                        {"score": "1:0", "decimal_odds": 7.0},
                        {"score": "bad", "decimal_odds": 9.0},
                        {"score": "0:0", "decimal_odds": 10.0},
                    ],
                }
            ]
        )
        self.assertEqual(items[0]["explicit_score_count"], 2)
        self.assertEqual(items[0]["prices"][0]["decimal_odds"], 6.25)
        self.assertEqual(items[0]["quality"]["status"], "watch_only")
        self.assertIn("other_score_bucket_not_modelled", items[0]["quality"]["reasons"])

    def test_market_probabilities_normalise_explicit_prices(self):
        probs = market_probabilities(
            {"prices": [{"score": "1:0", "decimal_odds": 2.0}, {"score": "0:0", "decimal_odds": 4.0}]}
        )
        self.assertAlmostEqual(probs["1:0"], 2 / 3)
        self.assertAlmostEqual(probs["0:0"], 1 / 3)

    def test_comparison_exposes_model_vs_market(self):
        prediction = {
            "match_id": "ga-001",
            "fixture": {
                "home_team": "Mexico",
                "away_team": "South Africa",
                "match_number": 1,
                "kickoff_utc": "2026-06-11T19:00:00+00:00",
            },
            "recommended_tip": {"tip": "1:0"},
            "top_scores": [
                {"score": "2:0", "probability": 0.12},
                {"score": "1:0", "probability": 0.11},
                {"score": "1:1", "probability": 0.09},
            ],
        }
        payload = {
            "items": normalise_exact_score_items(
                [
                    {
                        "match_id": "ga-001",
                        "source": "bwin_de",
                        "market": "exact_score_regular_time",
                        "prices": [
                            {"score": "1:0", "decimal_odds": 6.25},
                            {"score": "2:0", "decimal_odds": 6.75},
                            {"score": "0:0", "decimal_odds": 10.0},
                        ],
                    }
                ]
            ),
            "visible_events": [{"match_id": "ga-001"}, {"match_id": "ga-002"}],
        }
        result = build_exact_score_comparison([prediction], payload, {"_meta": {}, "decision": {}, "sources": []})
        row = result["matches"][0]
        self.assertEqual(row["market_favorite_score"], "1:0")
        self.assertEqual(row["recommended_tip_odds"], 6.25)
        self.assertEqual(row["top_overlap"], ["1:0", "2:0"])
        self.assertEqual(result["summary"]["not_imported_visible_events"], 1)
        self.assertEqual(result["summary"]["model_market_favorite_disagreements"], 1)
        self.assertEqual(result["calibration"]["status"], "watch_only")
        self.assertEqual(
            result["calibration"]["reason"],
            "no_historical_bwin_exact_score_backtest_dataset",
        )

    def test_calibration_uses_source_audit_without_changing_watch_only_status(self):
        audit = {
            "_meta": {"updated_at": "2026-05-20T00:00:00+00:00"},
            "decision": {
                "status": "watch_only",
                "reason": "no_free_reproducible_historical_exact_score_snapshot_source",
                "recommendation": "Keep exact-score as watch-only.",
            },
            "sources": [
                {"name": "accepted", "accepted": True},
                {"name": "rejected", "accepted": False},
            ],
        }

        result = exact_score_calibration_decision([], audit)

        self.assertEqual(result["status"], "watch_only")
        self.assertEqual(
            result["reason"],
            "no_free_reproducible_historical_exact_score_snapshot_source",
        )
        self.assertEqual(result["searched_sources_count"], 2)
        self.assertEqual(result["accepted_sources_count"], 1)
        self.assertEqual(result["source_audit_updated_at"], "2026-05-20T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
