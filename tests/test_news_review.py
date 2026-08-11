from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.news_review import apply_decision, build_review_queue, load_decisions


def _item(iid, title, players, url, cats=("injury",), sev="critical", teams=("England",)):
    return {
        "id": iid, "title": title, "summary": title, "url": url,
        "teams": list(teams), "players": list(players), "categories": list(cats),
        "severity": sev, "model_relevant": True, "relevance": "high", "freshness": "fresh",
    }


class ReviewQueueTests(unittest.TestCase):
    def test_candidate_with_player_suggested_promote(self):
        q = build_review_queue([_item("a1", "Kane out", ["Kane"], "http://x/1")])
        self.assertEqual(q["count"], 1)
        self.assertEqual(q["queue"][0]["suggested"], "promote")

    def test_no_player_item_surfaced_as_watch(self):
        # Referee-Klasse (T-0083): kein benannter Spieler -> watch, markiert.
        q = build_review_queue([_item("ref", "Injured referee out", [], "http://x/ref")])
        row = q["queue"][0]
        self.assertEqual(row["suggested"], "watch")
        self.assertTrue(row["no_player_subject"])

    def test_already_in_manual_excluded(self):
        item = _item("a1", "Kane out", ["Kane"], "http://x/1")
        q = build_review_queue([item], manual_news=[{"url": "http://x/1", "title": "Kane out"}])
        self.assertEqual(q["count"], 0)

    def test_non_relevant_excluded(self):
        item = _item("a1", "x", ["Kane"], "http://x/1")
        item["model_relevant"] = False
        item["relevance"] = "low"
        self.assertEqual(build_review_queue([item])["count"], 0)

    def test_promote_then_dismiss_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            dpath = Path(tmp) / "dec.json"
            mpath = Path(tmp) / "manual.json"
            mpath.write_text("[]", encoding="utf-8")
            items = [_item("a1", "Kane out", ["Kane"], "http://x/1")]
            res = apply_decision("a1", "promote", items, decisions_path=dpath, manual_path=mpath)
            self.assertTrue(res["ok"] and res["promoted"])
            self.assertEqual(len(json.loads(mpath.read_text(encoding="utf-8"))), 1)
            self.assertIn("a1", load_decisions(dpath))
            # nach Entscheidung faellt das Item aus der Queue
            q = build_review_queue(items, decisions=load_decisions(dpath))
            self.assertEqual(q["count"], 0)


if __name__ == "__main__":
    unittest.main()
