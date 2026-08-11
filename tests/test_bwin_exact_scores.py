from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.bwin_exact_scores import (
    build_bwin_fixture_view_url,
    extract_bwin_fixture_id,
    parse_bwin_exact_score_item,
)


class BwinExactScoreTests(unittest.TestCase):
    def test_extract_fixture_id_from_bwin_url(self):
        self.assertEqual(
            extract_bwin_fixture_id("https://www.bwin.de/de/sports/events/foo-2%3A7780273"),
            "2:7780273",
        )
        self.assertEqual(
            extract_bwin_fixture_id("https://www.bwin.de/de/sports/events/foo-2:7780273"),
            "2:7780273",
        )

    def test_build_fixture_view_url_includes_country_and_access_id(self):
        url = build_bwin_fixture_view_url("2:7780273", public_access_id="abc")
        self.assertIn("x-bwin-accessid=abc", url)
        self.assertIn("country=DE", url)
        self.assertIn("fixtureIds=2%3A7780273", url)

    def test_parse_regular_time_correct_score_market(self):
        payload = {
            "fixture": {
                "optionMarkets": [
                    {
                        "id": 1,
                        "name": {"value": "Spielresultat"},
                        "parameters": [
                            {"key": "MarketType", "value": "3way"},
                            {"key": "Period", "value": "RegularTime"},
                        ],
                        "options": [],
                    },
                    {
                        "id": 2,
                        "name": {"value": "Genaues Ergebnis - reguläre Spielzeit"},
                        "parameters": [
                            {"key": "MarketType", "value": "CorrectScore"},
                            {"key": "Period", "value": "RegularTime"},
                        ],
                        "options": [
                            {
                                "status": "Visible",
                                "name": {"value": "1:0"},
                                "price": {"odds": 6.25},
                            },
                            {
                                "status": "Visible",
                                "name": {"value": "Jedes andere Ergebnis"},
                                "price": {"odds": 15.0},
                            },
                            {
                                "status": "Hidden",
                                "name": {"value": "0:0"},
                                "price": {"odds": 8.0},
                            },
                        ],
                    },
                ]
            }
        }
        item = parse_bwin_exact_score_item(
            payload,
            {
                "match_id": "ga-001",
                "match": "Mexico - South Africa",
                "event_url": "https://www.bwin.de/de/sports/events/mexiko-suedafrika-2%3A7722030",
            },
            observed_at="2026-05-19T18:00:00+00:00",
        )
        self.assertEqual(item["match_id"], "ga-001")
        self.assertEqual(item["bwin_fixture_id"], "2:7722030")
        self.assertEqual(item["explicit_score_count"], 1)
        self.assertEqual(item["prices"][0], {"score": "1:0", "decimal_odds": 6.25})
        self.assertTrue(item["has_other_selection"])
        self.assertEqual(item["other_selection_odds"], 15.0)


if __name__ == "__main__":
    unittest.main()
