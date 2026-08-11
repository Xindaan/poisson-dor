"""T-0139: Spieler-Subjekt-Dedupe fuer xG-wirksame News-Items (forward-gated).

Bug: `impact_dedupe_key` joint ALLE (per Regex geratenen) Subject-Keys zu einem
String. Ein abweichendes Rausch-Token ("Can ...", "... in Mexico") sprengt den
Key -> derselbe Ausfall wird mehrfach bestraft.
"""
import unittest

from wm_tipps import news


def _item(item_id, title, *, players=None, severity="critical"):
    row = {
        "id": item_id,
        "title": title,
        "summary": "",
        "impact": "",
        "severity": severity,
        "reliability": "high",
        "teams": ["England"],
        "categories": ["injury"],
    }
    if players is not None:
        row["players"] = players
    return row


class SubjectDedupeTests(unittest.TestCase):
    def test_flag_is_active(self):
        # Bugfix (kein spekulativer Hebel): nach Live-Tipp-Diff (2x besser, 0x
        # schlechter auf gespielten Spielen) aktiviert. False = fehlerhaftes Alt-Verhalten.
        self.assertTrue(news.NEWS_SUBJECT_DEDUPE_ENABLED)

    def test_same_player_two_articles_merges_when_enabled(self):
        # Der echte ko-099-Fall: Rausch-Tokens 'can' bzw. 'mexico' unterscheiden
        # die Keys, gemeinsam ist nur 'henderson'.
        items = [
            _item("a", "Can England replace Jordan Henderson after freak injury?"),
            _item("b", "Jordan Henderson injury latest as the midfielder prepares for surgery in Mexico"),
        ]
        merged = news.dedupe_impact_items("England", items, enabled=True)
        self.assertEqual(len(merged), 1)

    def test_same_player_two_articles_double_counted_when_disabled(self):
        # Dokumentiert das Alt-Verhalten (der Bug), damit der Gate-Effekt sichtbar bleibt.
        items = [
            _item("a", "Can England replace Jordan Henderson after freak injury?"),
            _item("b", "Jordan Henderson injury latest as the midfielder prepares for surgery in Mexico"),
        ]
        self.assertEqual(len(news.dedupe_impact_items("England", items, enabled=False)), 2)

    def test_different_players_stay_separate(self):
        items = [
            _item("a", "x", players=["Jordan Henderson"]),
            _item("b", "y", players=["Ben White"]),
        ]
        merged = news.dedupe_impact_items("England", items, enabled=True)
        self.assertEqual(len(merged), 2)

    def test_strongest_item_survives_the_merge(self):
        items = [
            _item("weak", "x", players=["Jordan Henderson"], severity="important"),
            _item("strong", "y", players=["Jordan Henderson"], severity="critical"),
        ]
        merged = news.dedupe_impact_items("England", items, enabled=True)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], "strong")

    def test_stopword_only_overlap_does_not_merge(self):
        # 'can' ist Rauschen und darf kein Merge-Schluessel sein.
        items = [
            _item("a", "x", players=["Can"]),
            _item("b", "y", players=["Can"]),
        ]
        merged = news.dedupe_impact_items("England", items, enabled=True)
        self.assertEqual(len(merged), 2)

    def test_items_without_subject_are_not_merged(self):
        items = [_item("a", "squad news update"), _item("b", "another squad update")]
        merged = news.dedupe_impact_items("England", items, enabled=True)
        self.assertEqual(len(merged), 2)


if __name__ == "__main__":
    unittest.main()
