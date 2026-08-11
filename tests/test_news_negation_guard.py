"""T-0148: Negations-Guard gegen False-Positive-Ausfaelle in der News-Klassifikation."""
import unittest

from wm_tipps import news


def classify(text, *, guard):
    old = news.NEWS_NEGATION_GUARD_ENABLED
    news.NEWS_NEGATION_GUARD_ENABLED = guard
    try:
        return news.classify_text(text)["severity"]
    finally:
        news.NEWS_NEGATION_GUARD_ENABLED = old


class NegationGuardTests(unittest.TestCase):
    def test_flag_is_active(self):
        # Bugfix nach Live-Tipp-Diff (1x besser, 0x schlechter) aktiviert.
        self.assertTrue(news.NEWS_NEGATION_GUARD_ENABLED)

    def test_not_ruled_out_downgraded_when_enabled(self):
        # Der echte ko-099-Fall.
        t = "Henderson not ruled out of World Cup despite breaking arm"
        self.assertEqual(classify(t, guard=False), "critical")  # Alt-Bug
        self.assertNotEqual(classify(t, guard=True), "critical")

    def test_genuine_ruled_out_stays_critical(self):
        t = "White ruled out of the World Cup"
        self.assertEqual(classify(t, guard=True), "critical")

    def test_negator_not_directly_before_phrase_is_not_downgraded(self):
        # KRITISCH: 'not' bezieht sich auf 'training', der Spieler IST raus.
        t = "Henderson not training and ruled out of the World Cup"
        self.assertEqual(classify(t, guard=True), "critical")

    def test_not_available_stays_critical(self):
        # 'not available' ist eine echte Absenz -- die Verneinung gehoert zur Phrase.
        t = "Kane not available for the World Cup"
        self.assertEqual(classify(t, guard=True), "critical")

    def test_wont_miss_downgraded(self):
        t = "Kane won't miss the World Cup after scan"
        self.assertEqual(classify(t, guard=False), "critical")
        self.assertNotEqual(classify(t, guard=True), "critical")

    def test_cleared_to_play_downgraded(self):
        t = "Bellingham cleared to play, ruled out fears ease"
        self.assertNotEqual(classify(t, guard=True), "critical")

    def test_plain_availability_word_alone_is_not_critical_either_way(self):
        # Ohne Ausfall-Keyword ist es ohnehin kein critical -- Guard aendert nichts.
        t = "Team news: squad in good shape"
        self.assertEqual(classify(t, guard=True), classify(t, guard=False))


if __name__ == "__main__":
    unittest.main()
