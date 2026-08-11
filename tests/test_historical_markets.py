from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.historical_markets import (
    apply_historical_market_lines,
    historical_market_constraints_from_row,
    parse_checkbestodds_archive_links,
    parse_checkbestodds_match_page,
    parse_checkbestodds_more_odds_html,
)


class HistoricalMarketTests(unittest.TestCase):
    def test_parse_checkbestodds_match_page_metadata(self):
        html = """
        <span id="homeName">Argentina</span>
        <span id="awayName">Saudi Arabia</span>
        <span id="matchTime" ts="1669114800">12:00</span>
        <input type="hidden" id="matchHash" value="abc123"/>
        """
        self.assertEqual(
            parse_checkbestodds_match_page(html),
            {
                "home": "Argentina",
                "away": "Saudi Arabia",
                "match_time": "1669114800",
                "match_hash": "abc123",
            },
        )

    def test_parse_archive_links_normalises_relative_urls(self):
        html = """
        <a href="/football-odds/world-cup-2022/argentina-saudi-arabia-2022-11-22/1543436854">
          Argentina - Saudi Arabia
        </a>
        """
        links = parse_checkbestodds_archive_links(html)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["match"], "Argentina - Saudi Arabia")
        self.assertTrue(links[0]["url"].startswith("https://checkbestodds.com/"))

    def test_parse_more_odds_extracts_ou_btts_and_handicap(self):
        html = """
        <div id="3" class="tblehead"><span class="r"><i>Under/Over 2.5 odds</i></span></div>
        <div class="tblediv"><table><thead><tr><th>Bookmaker</th><th>Under</th><th>Over</th><th>Margin</th><th></th></tr></thead>
        <tr><td>Book A</td><td><span class="toSort noDsp">2.50</span></td><td><span class="toSort noDsp">1.60</span></td><td>2.50%</td><td></td></tr>
        <tr><td>Book B</td><td><span class="toSort noDsp">2.40</span></td><td><span class="toSort noDsp">1.70</span></td><td>3.00%</td><td></td></tr>
        <tfoot><tr><td>Best odds</td><td>2.50</td><td>1.70</td><td>-1.00%</td><td></td></tr></tfoot>
        </table></div>
        <div id="13" class="tblehead"><span class="r"><i>Both teams to score odds</i></span></div>
        <div class="tblediv"><table><thead><tr><th>Bookmaker</th><th>Yes</th><th>No</th><th>Margin</th><th></th></tr></thead>
        <tr><td>Book A</td><td><span class="toSort noDsp">1.80</span></td><td><span class="toSort noDsp">2.00</span></td><td>5.56%</td><td></td></tr>
        </table></div>
        <div id="8:-1.5" class="tblehead"><span class="r"><i>Asian Handicap -1.5</i></span></div>
        <div class="tblediv"><table><thead><tr><th>Bookmaker</th><th>AH1</th><th>AH2</th><th>Margin</th><th></th></tr></thead>
        <tr><td>Book A</td><td><span class="toSort noDsp">1.90</span></td><td><span class="toSort noDsp">1.95</span></td><td>3.98%</td><td></td></tr>
        </table></div>
        """
        markets = parse_checkbestodds_more_odds_html(html)
        self.assertEqual(len(markets["over_under"]), 1)
        self.assertAlmostEqual(markets["over_under"][0]["line"], 2.5)
        self.assertGreater(markets["over_under"][0]["over_probability"], 0.5)
        self.assertIsNotNone(markets["btts"])
        self.assertEqual(len(markets["handicap"]), 1)
        self.assertAlmostEqual(markets["handicap"][0]["line"], -1.5)

    def test_apply_lines_builds_backtest_constraints(self):
        payload = {
            "items": [
                {
                    "tournament": "2022",
                    "match": "Argentina - Saudi Arabia",
                    "source": "checkbestodds",
                    "source_url": "https://example.test/match",
                    "markets": {
                        "over_under": [
                            {
                                "line": 2.5,
                                "over_probability": 0.61,
                                "under_probability": 0.39,
                                "source": "checkbestodds",
                            }
                        ],
                        "btts": {
                            "yes_probability": 0.46,
                            "no_probability": 0.54,
                            "source": "checkbestodds",
                        },
                        "handicap": [],
                    },
                }
            ]
        }
        [row] = apply_historical_market_lines(
            "2022",
            [{"match": "Argentina - Saudi Arabia", "pre_odds": {"home": 1.1, "draw": 9, "away": 26}}],
            payload,
        )
        constraints = historical_market_constraints_from_row(row)
        self.assertEqual(row["pre_extra_market_source"]["source"], "checkbestodds")
        self.assertEqual([constraint["kind"] for constraint in constraints], ["total_goals", "btts"])


if __name__ == "__main__":
    unittest.main()
