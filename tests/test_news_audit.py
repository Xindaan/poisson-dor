from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.news import team_news_impact
from wm_tipps.news_audit import build_news_audit, news_audit_markdown


def _injury(title, summary, teams, severity="critical"):
    return {
        "title": title,
        "summary": summary,
        "categories": ["injury"],
        "severity": severity,
        "teams": list(teams),
        "freshness": "fresh",
        "model_relevant": True,
        "relevance": "high",
    }


NEWS = [
    _injury(
        "Germany's Karl out of WC after training injury",
        "Germany midfielder Lennart Karl will miss the World Cup after a training injury.",
        ["Germany"],
    ),
    _injury(
        "Netherlands' Timber out of World Cup with injury",
        "Arsenal defender Jurrien Timber is ruled out of the Netherlands' World Cup "
        "campaign with a groin injury, while Brazil's Neymar is making good progress "
        "from injury.",
        ["Brazil", "Netherlands"],
    ),
    # Stale Item -> darf nirgends gewertet werden, aber gelistet sein.
    {
        **_injury(
            "Spain defender old injury note",
            "Spain defender was hurt long ago.",
            ["Spain"],
        ),
        "freshness": "stale",
    },
]

POOL = {
    "Brazil": [{"name": "Neymar", "goal_share": 0.4, "position": "FW", "role": "starter"}],
    "Netherlands": [{"name": "Jurrien Timber", "goal_share": 0.1, "position": "DF", "role": "starter"}],
    "Germany": [{"name": "Lennart Karl", "goal_share": 0.2, "position": "MF", "role": "rotation"}],
}

FIXTURE_TEAMS = {"Germany", "Brazil", "Netherlands", "Haiti", "Spain"}


class NewsAuditTests(unittest.TestCase):
    def setUp(self):
        self.audit = build_news_audit(
            news_items=NEWS, player_pool=POOL, fixture_teams=FIXTURE_TEAMS, write=False
        )
        self.by_team = {row["team"]: row for row in self.audit["teams"]}

    def test_counted_items_reconcile_with_team_news_impact(self):
        # Spiegel darf nicht wegdriften: counted_items == deduped_impact_items.
        for row in self.audit["teams"]:
            impact = team_news_impact(row["team"], NEWS, POOL)
            self.assertEqual(row["counted_items"], impact["deduped_impact_items"], row["team"])

    def test_recovery_only_team_has_no_effect_injured_team_does(self):
        self.assertNotIn("Brazil", self.by_team)  # nur Recovery-Nennung -> unterdrueckt
        self.assertIn("Netherlands", self.by_team)  # echter Ausfall (Timber)
        self.assertIn("Germany", self.by_team)
        self.assertNotIn("Spain", self.by_team)  # stale

    def test_multi_team_item_in_risk_with_count_suppress(self):
        timber = [r for r in self.audit["risk_items"] if "Timber" in r["title"]]
        self.assertEqual(len(timber), 1)
        decisions = {d["team"]: d["action"] for d in timber[0]["decisions"]}
        self.assertEqual(decisions["Brazil"], "suppress")
        self.assertEqual(decisions["Netherlands"], "count")

    def test_foreign_subject_and_multi_team_flagged(self):
        nl_items = self.by_team["Netherlands"]["items"]
        self.assertEqual(len(nl_items), 1)
        flags = nl_items[0]["flags"]
        self.assertIn("multi_team", flags)
        # 'neymar' im Subject gehoert laut Pool zu Brazil, nicht Niederlande.
        self.assertTrue(any(f.startswith("subject_in_other_pool") and "neymar" in f for f in flags))

    def test_single_team_item_not_flagged(self):
        germany_items = self.by_team["Germany"]["items"]
        self.assertEqual(len(germany_items), 1)
        self.assertEqual(germany_items[0]["flags"], [])

    def test_stale_impact_listed_and_counted_in_meta(self):
        self.assertEqual(self.audit["_meta"]["stale_impact_items"], 1)
        titles = [i["title"] for i in self.audit["stale_impact_items"]]
        self.assertIn("Spain defender old injury note", titles)

    def test_meta_summary_counts(self):
        meta = self.audit["_meta"]
        self.assertEqual(meta["teams_with_effect"], 2)  # Germany + Netherlands
        self.assertEqual(meta["risk_items"], 1)  # Timber
        self.assertEqual(meta["flagged_team_items"], 1)  # Netherlands/Timber

    def test_markdown_renders(self):
        text = news_audit_markdown(self.audit)
        self.assertIn("News-xG-Audit", text)
        self.assertIn("Netherlands", text)
        self.assertIn("Timber", text)


if __name__ == "__main__":
    unittest.main()
