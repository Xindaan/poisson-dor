from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.bwin_match_odds import apply_bwin_odds_to_csv, bwin_competition_events, parse_bwin_match_odds


def _market(market_type, period, options):
    return {
        "parameters": [
            {"key": "MarketType", "value": market_type},
            {"key": "Period", "value": period},
        ],
        "options": options,
    }


def _opt(name, odds):
    return {"name": {"value": name}, "price": {"odds": odds}, "status": "Visible"}


def _payload(markets):
    return {"fixture": {"optionMarkets": markets}}


class ParseMatchOddsTests(unittest.TestCase):
    def test_extracts_3way_regular_time(self):
        payload = _payload([
            _market("CorrectScore", "RegularTime", [_opt("1:0", "5.25")]),
            _market("3way", "RegularTime", [_opt("Schweden", "1.93"), _opt("X", "3.40"), _opt("Tunesien", "4.20")]),
            _market("3way", "FirstHalf", [_opt("Schweden", "2.5"), _opt("X", "2.0"), _opt("Tunesien", "5.0")]),
        ])
        odds = parse_bwin_match_odds(payload)
        self.assertEqual(odds, {"home": 1.93, "draw": 3.4, "away": 4.2})

    def test_none_without_3way(self):
        payload = _payload([_market("CorrectScore", "RegularTime", [_opt("1:0", "5.25")])])
        self.assertIsNone(parse_bwin_match_odds(payload))


class ApplyCsvTests(unittest.TestCase):
    def test_updates_existing_bwin_row_and_keeps_others(self):
        rows = [
            {"match_id": "gf-032", "source": "bet365_world_cup_2026", "home": "1.95", "draw": "3.5", "away": "4.5", "last_updated": "2026-05-11"},
            {"match_id": "gf-032", "source": "bwin_world_cup_2026", "home": "1.90", "draw": "3.40", "away": "4.33", "last_updated": "2026-05-11"},
        ]
        fresh = {"gf-032": {"home": 1.93, "draw": 3.4, "away": 4.2}}
        out, updated, added = apply_bwin_odds_to_csv(fresh, rows, "2026-06-14T16:00:00+00:00")
        self.assertEqual((updated, added), (1, 0))
        bwin = next(r for r in out if r["source"] == "bwin_world_cup_2026")
        self.assertEqual((bwin["home"], bwin["draw"], bwin["away"]), ("1.9300", "3.4000", "4.2000"))
        self.assertEqual(bwin["last_updated"], "2026-06-14T16:00:00+00:00")
        other = next(r for r in out if r["source"] == "bet365_world_cup_2026")
        self.assertEqual(other["home"], "1.95")  # unberuehrt

    def test_adds_bwin_row_when_missing(self):
        rows = [{"match_id": "gx-001", "source": "bet365_world_cup_2026", "home": "2.0", "draw": "3.3", "away": "3.8", "last_updated": "2026-05-11"}]
        fresh = {"gx-001": {"home": 1.8, "draw": 3.5, "away": 4.6}}
        out, updated, added = apply_bwin_odds_to_csv(fresh, rows, "2026-06-14T16:00:00+00:00")
        self.assertEqual((updated, added), (0, 1))
        self.assertTrue(any(r["source"] == "bwin_world_cup_2026" and r["match_id"] == "gx-001" for r in out))


class CompetitionFixturesTests(unittest.TestCase):
    def test_maps_german_bwin_team_names_to_fixture_ids(self):
        payload = {
            "fixtures": [
                {
                    "id": "2:7827168",
                    "name": {"value": "Brasilien - Norwegen"},
                    "startDate": "2026-07-05T20:00:00Z",
                    "optionMarkets": [
                        _market(
                            "3way",
                            "RegularTime",
                            [_opt("Brasilien", 1.83), _opt("X", 3.8), _opt("Norwegen", 4.1)],
                        )
                    ],
                },
                {
                    "id": "2:7827297",
                    "name": {"value": "Brasilien - Norwegen - Super Price Boost"},
                    "startDate": "2026-07-05T20:00:00Z",
                    "optionMarkets": [_market("3way", "RegularTime", [_opt("Brasilien", 1.7)])],
                },
                {
                    "id": "2:7827187",
                    "name": {"value": "Paraguay - Frankreich"},
                    "startDate": "2026-07-04T21:00:00Z",
                    "optionMarkets": [
                        _market(
                            "3way",
                            "RegularTime",
                            [_opt("Paraguay", 15), _opt("X", 6.75), _opt("Frankreich", 1.21)],
                        )
                    ],
                },
            ]
        }
        fixtures = [
            {
                "match_id": "ko-091",
                "home_team": "Brazil",
                "away_team": "Norway",
                "kickoff_utc": "2026-07-05T20:00:00+00:00",
            },
            {
                "match_id": "ko-089",
                "home_team": "Paraguay",
                "away_team": "France",
                "kickoff_utc": "2026-07-04T21:00:00+00:00",
            },
        ]

        events = sorted(bwin_competition_events(payload, fixtures), key=lambda row: row["match_id"])

        self.assertEqual([row["match_id"] for row in events], ["ko-089", "ko-091"])
        self.assertEqual(events[0]["odds"], {"home": 15.0, "draw": 6.75, "away": 1.21})
        self.assertIn("2%3A7827187", events[0]["event_url"])
        self.assertEqual(events[1]["odds"], {"home": 1.83, "draw": 3.8, "away": 4.1})


if __name__ == "__main__":
    unittest.main()
