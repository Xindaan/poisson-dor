from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps import news as news_module
from wm_tipps.news_sources import gdelt, rss


SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title>France star ruled out with knee injury</title>
    <link>https://example.com/article-1</link>
    <description>Bad news for France ahead of the World Cup.</description>
    <pubDate>Wed, 10 Jun 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Germany name squad for friendlies</title>
    <link>https://example.com/article-2</link>
    <description>Coach announces preliminary roster.</description>
    <pubDate>Tue, 09 Jun 2026 12:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


class GdeltAdapterTests(unittest.TestCase):
    def test_collect_returns_empty_when_network_fails(self):
        with mock.patch.object(gdelt.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(gdelt.collect(["France"]), [])

    def test_collect_query_uses_keyword_argument(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"articles":[]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_open(url, timeout):
            captured["url"] = url
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(gdelt.urllib.request, "urlopen", side_effect=fake_open):
            gdelt.collect(["France"], per_team_limit=2, keywords="injury OR lineup")
        self.assertIn("injury+OR+lineup", captured["url"].replace("%20", "+"))
        self.assertNotIn("World+Cup", captured["url"].replace("%20", "+"))
        # GDELT verlangt Klammern um die OR-Gruppe -- sonst HTTP-Error.
        self.assertIn("%28", captured["url"])
        self.assertIn("%29", captured["url"])
        self.assertLessEqual(captured["timeout"], gdelt.DEFAULT_TIMEOUT)

    def test_collect_parses_articles(self):
        payload = b'{"articles": [{"domain": "example.com", "title": "T", "url": "U", "seendate": "2026-06-01T12:00:00Z"}]}'

        class FakeResponse:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(gdelt.urllib.request, "urlopen", return_value=FakeResponse()):
            rows = gdelt.collect(["France"], per_team_limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "T")
        self.assertEqual(rows[0]["url"], "U")


class RssAdapterTests(unittest.TestCase):
    def test_parse_rss_extracts_items_and_team_mentions(self):
        rows = rss.parse_rss(SAMPLE_RSS, ["France", "Germany"], source="bbc")
        self.assertEqual(len(rows), 2)
        france_item = next(row for row in rows if "France" in row["teams"])
        self.assertIn("ruled out", france_item["title"])
        self.assertEqual(france_item["source"], "bbc")
        self.assertTrue(france_item["published_at"])
        self.assertEqual(france_item["reliability"], "medium")

    def test_parse_rss_marks_official_feeds_high_reliability(self):
        rows = rss.parse_rss(SAMPLE_RSS, ["France"], source="https://canadasoccer.com/feed/")
        self.assertEqual(rows[0]["reliability"], "high")

    def test_parse_rss_handles_invalid_xml(self):
        self.assertEqual(rss.parse_rss("not xml", ["France"]), [])

    def test_collect_skips_failing_feed(self):
        with mock.patch.object(rss.urllib.request, "urlopen", side_effect=OSError("dns fail")):
            self.assertEqual(rss.collect(["France"], feeds=("https://example.com/feed",)), [])

    def test_collect_aggregates_and_skips_failing_feed(self):
        feeds = ("https://ok.example/feed", "https://broken.example/feed")

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_opener(url, timeout):
            target = getattr(url, "full_url", url)
            if "broken" in target:
                raise OSError("dns fail")
            return FakeResponse(SAMPLE_RSS.encode("utf-8"))

        with mock.patch.object(rss.urllib.request, "urlopen", side_effect=fake_opener):
            rows = rss.collect(["France", "Germany"], feeds=feeds)

        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["source"] == "https://ok.example/feed" for row in rows))

    def test_collect_sends_user_agent_for_feeds_that_block_bare_urllib(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return SAMPLE_RSS.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_opener(request, timeout):
            captured["url"] = request.full_url
            captured["user_agent"] = request.get_header("User-agent")
            return FakeResponse()

        with mock.patch.object(rss.urllib.request, "urlopen", side_effect=fake_opener):
            rows = rss.collect(["France"], feeds=("https://www.worldsoccer.com/feed",))

        self.assertEqual(captured["url"], "https://www.worldsoccer.com/feed")
        self.assertIn("wm-tipps-rss", captured["user_agent"])
        self.assertEqual(len(rows), 2)

    def test_default_feeds_cover_multiple_domains(self):
        from urllib.parse import urlparse

        domains = {urlparse(url).netloc for url in rss.DEFAULT_FEEDS}
        self.assertGreaterEqual(len(rss.DEFAULT_FEEDS), 9)
        self.assertGreaterEqual(len(domains), 9)
        self.assertIn("https://canadasoccer.com/feed/", rss.DEFAULT_FEEDS)
        self.assertIn("https://www.insideworldfootball.com/feed/", rss.DEFAULT_FEEDS)
        self.assertIn("https://www.worldsoccer.com/feed", rss.DEFAULT_FEEDS)


class RefreshNewsIntegrationTests(unittest.TestCase):
    def test_watch_cycle_without_live_keeps_existing_items_and_quality(self):
        existing_payload = {
            "items": [
                {
                    "id": "x1",
                    "title": "France captain ruled out",
                    "url": "https://example.com/news/x1",
                    "published_at": "2026-06-10T08:00:00+00:00",
                    "teams": ["France"],
                    "severity": "critical",
                    "categories": ["injury"],
                    "freshness": "fresh",
                }
            ],
            "data_quality": [{"source": "rss", "status": "ok", "items_total": 1, "items_fresh": 1}],
        }
        with mock.patch.object(news_module, "read_json", return_value=existing_payload), mock.patch.object(
            news_module, "load_manual_news", return_value=[]
        ), mock.patch.object(news_module, "write_json"):
            payload = news_module.refresh_news(["France"], live=False)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], "x1")
        self.assertEqual(payload["data_quality"][0]["source"], "rss")

    def test_watch_cycle_reannotates_existing_relevance(self):
        existing_payload = {
            "items": [
                {
                    "id": "x-noise",
                    "title": "Ups, downs and the race for Europe",
                    "summary": "All you need to know about promotion in England and Scotland leagues.",
                    "url": "https://example.com/noise",
                    "published_at": "2026-05-10T17:00:00+00:00",
                    "teams": ["England", "Scotland"],
                    "severity": "critical",
                    "categories": ["general"],
                    "freshness": "fresh",
                }
            ],
            "data_quality": [],
        }
        with mock.patch.object(news_module, "read_json", return_value=existing_payload), mock.patch.object(
            news_module, "load_manual_news", return_value=[]
        ), mock.patch.object(news_module, "write_json"):
            payload = news_module.refresh_news(["England", "Scotland"], live=False)
        self.assertEqual(payload["items"][0]["id"], "x-noise")
        self.assertEqual(payload["items"][0]["relevance"], "low")
        self.assertEqual(payload["items"][0]["severity"], "noise")
        self.assertFalse(payload["items"][0]["model_relevant"])

    def test_live_refresh_dedupes_existing_with_new_by_url(self):
        # Bewusst ohne id -- dedupe_news generiert ueber URL einen
        # Fingerprint; neuer Eintrag mit gleicher URL bekommt denselben
        # Fingerprint und kollidiert im dedup.
        existing_payload = {
            "items": [
                {
                    "title": "Old title",
                    "url": "https://example.com/article",
                    "published_at": "2026-06-09T08:00:00+00:00",
                    "teams": ["France"],
                    "severity": "context",
                }
            ],
            "data_quality": [],
        }
        new_source = mock.Mock()
        new_source.NAME = "test"
        new_source.collect.return_value = [
            {
                "title": "Updated title",
                "url": "https://example.com/article",
                "published_at": "2026-06-10T10:00:00+00:00",
                "teams": ["France"],
            }
        ]
        with mock.patch.object(news_module, "read_json", return_value=existing_payload), mock.patch.object(
            news_module, "load_manual_news", return_value=[]
        ), mock.patch.object(news_module, "write_json"):
            payload = news_module.refresh_news(["France"], live=True, sources=[new_source])
        # Trotz zwei Eintraegen mit gleicher URL: deduplicate auf einen.
        same_url = [item for item in payload["items"] if item.get("url") == "https://example.com/article"]
        self.assertEqual(len(same_url), 1)

    def test_live_run_records_quality_per_source(self):
        ok_source = mock.Mock()
        ok_source.NAME = "ok"
        ok_source.collect.return_value = [
            {
                "source": "ok",
                "title": "France injury news",
                "url": "https://example.com/a",
                "published_at": "2026-06-10T08:00:00+00:00",
                "teams": ["France"],
            }
        ]
        bad_source = mock.Mock()
        bad_source.NAME = "bad"
        bad_source.collect.side_effect = RuntimeError("kaputt")

        with mock.patch.object(news_module, "load_manual_news", return_value=[]), mock.patch.object(
            news_module, "write_json"
        ):
            payload = news_module.refresh_news(
                ["France"], live=True, sources=[ok_source, bad_source]
            )

        quality = payload["data_quality"]
        self.assertEqual(len(quality), 2)
        ok_entry = next(q for q in quality if q["source"] == "ok")
        bad_entry = next(q for q in quality if q["source"] == "bad")
        self.assertEqual(ok_entry["status"], "ok")
        self.assertGreaterEqual(ok_entry["items_total"], 1)
        self.assertEqual(bad_entry["status"], "error")
        self.assertIn("kaputt", bad_entry.get("error", ""))

    def test_non_live_run_keeps_data_quality_empty_when_nothing_persisted(self):
        with mock.patch.object(news_module, "read_json", return_value={"items": [], "data_quality": []}), \
             mock.patch.object(news_module, "load_manual_news", return_value=[]), \
             mock.patch.object(news_module, "write_json"):
            payload = news_module.refresh_news(["France"], live=False)
        self.assertEqual(payload["data_quality"], [])


if __name__ == "__main__":
    unittest.main()
