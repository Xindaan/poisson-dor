from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.source_watch import (
    build_source_watch_status,
    parse_bwin_event_snapshot,
    parse_bwin_exact_score_snapshot,
    parse_bwin_page_snapshot,
)


class SourceWatchTests(unittest.TestCase):
    def test_parse_bwin_page_snapshot_reads_visible_counts(self):
        snapshot = parse_bwin_page_snapshot(
            "Spiele  24 KONFIGURATOR 24 Gesamtwetten  21 Spezial  1 Genaues Ergebnis",
            checked_at="2026-05-19T10:00:00+00:00",
        )
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["match_count"], 24)
        self.assertEqual(snapshot["overall_market_count"], 21)
        self.assertEqual(snapshot["special_market_count"], 1)
        self.assertTrue(snapshot["exact_score_visible"])

    def test_parse_bwin_exact_score_snapshot_reads_browser_visible_prices(self):
        snapshot = parse_bwin_exact_score_snapshot(
            """
            - generic: Genaues Ergebnis - reguläre Spielzeit
            - generic: "1"
            - generic: X
            - generic: "2"
            - generic: 1:0
            - generic: "6.25"
            - generic: 0:0
            - generic: "10.00"
            - generic: 0:1
            - generic: "13.50"
            - generic: Mehr anzeigen
            - generic: Genaues Ergebnis (mehrere Optionen)
            - generic: 1:0, 2:0 oder 3:0
            - generic: "2.60"
            """,
            checked_at="2026-05-19T11:00:00+00:00",
            home_team="Mexico",
            away_team="South Africa",
        )
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["price_count"], 3)
        self.assertTrue(snapshot["has_more_button"])
        self.assertEqual(snapshot["prices"][0], {"selection": "1:0", "decimal_odds": 6.25})
        self.assertEqual(snapshot["prices"][2], {"selection": "0:1", "decimal_odds": 13.5})

    def test_parse_bwin_event_snapshot_summarizes_exact_score_market(self):
        snapshot = parse_bwin_event_snapshot(
            """
            Mexiko Südafrika
            Alle Wetten 60
            Genaues Ergebnis - reguläre Spielzeit
            1:0 6.25 0:0 10.00 0:1 13.50
            Mehr anzeigen
            Genaues Ergebnis (mehrere Optionen)
            """,
            checked_at="2026-05-19T11:00:00+00:00",
        )
        self.assertEqual(snapshot["event_market_count"], 60)
        self.assertEqual(snapshot["exact_score_status"], "visible_partial_prices")
        self.assertEqual(snapshot["exact_score_prices_count"], 3)
        self.assertEqual(snapshot["exact_score_sample"][1]["selection"], "0:0")

    def test_parse_bwin_exact_score_snapshot_stops_before_multi_option_market(self):
        snapshot = parse_bwin_exact_score_snapshot(
            (
                "Genaues Ergebnis - reguläre Spielzeit 1:0 6.25 0:0 10.00 "
                "Genaues Ergebnis (mehrere Optionen) 1:0, 2:0 oder 3:0 2.60"
            )
        )
        self.assertEqual(snapshot["price_count"], 2)
        self.assertEqual([row["selection"] for row in snapshot["prices"]], ["1:0", "0:0"])

    def test_bwin_watch_flags_partial_coverage_and_exact_score(self):
        fixtures = [{"match_id": "ga-001"}, {"match_id": "ga-002"}]
        odds = [{"match_id": "ga-001", "source": "bwin_world_cup_2026"}]
        markets = [
            {"source": "bwin_de_gesamtwetten_2026", "category": "world_champion"},
            {"source": "bwin_de_gesamtwetten_2026", "category": "semifinalist"},
        ]
        payload = build_source_watch_status(
            fixtures,
            odds,
            markets,
            live_probe={
                "status": "ok",
                "match_count": 24,
                "overall_market_count": 21,
                "special_market_count": 1,
                "exact_score_visible": True,
            },
            now=datetime(2026, 5, 19, tzinfo=timezone.utc),
        )
        source = payload["sources"][0]
        self.assertEqual(source["status"], "watch")
        self.assertEqual(source["imported_match_odds"], 1)
        self.assertIn("partial_match_odds", source["flags"])
        self.assertIn("bwin_page_expanded", source["flags"])
        self.assertIn("exact_score_watch", source["flags"])
        self.assertEqual(source["imported_futures"]["world_champion"], 1)

    def test_bwin_watch_flags_visible_exact_score_prices(self):
        fixtures = [{"match_id": "ga-001"}]
        odds = [{"match_id": "ga-001", "source": "bwin_world_cup_2026"}]
        markets = [{"source": "bwin_de_gesamtwetten_2026", "category": "world_champion"}]
        payload = build_source_watch_status(
            fixtures,
            odds,
            markets,
            manual_observations={
                "bwin_de_world_cup_2026": {
                    "exact_score_status": "visible_partial_prices",
                    "exact_score_prices_count": 15,
                    "exact_score_has_more": True,
                }
            },
        )
        source = payload["sources"][0]
        self.assertEqual(source["status"], "watch")
        self.assertIn("exact_score_prices_visible", source["flags"])
        self.assertIn("exact_score_partial_sample", source["flags"])

    def test_bwin_watch_is_ok_when_everything_is_imported(self):
        fixtures = [{"match_id": "ga-001"}]
        odds = [{"match_id": "ga-001", "source": "bwin_world_cup_2026"}]
        markets = [{"source": "bwin_de_gesamtwetten_2026", "category": "world_champion"}]
        payload = build_source_watch_status(
            fixtures,
            odds,
            markets,
            live_probe={"status": "ok", "match_count": 1, "exact_score_visible": False},
        )
        self.assertEqual(payload["sources"][0]["status"], "ok")
        self.assertEqual(payload["sources"][0]["flags"], [])


if __name__ == "__main__":
    unittest.main()
