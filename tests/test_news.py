from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.news import (
    _team_news_is_recovery_only,
    annotate_news,
    cap_news_with_manual,
    classify_text,
    dedupe_news,
    entry_disruption_severity,
    freshness_status,
    news_for_fixture,
    player_profile_from_pool,
    player_weight_from_pool,
    team_is_injury_subject,
    team_news_impact,
)


def _recent_published_at() -> str:
    """published_at relativ zu now, damit die Injury-Tests nicht
    datumsbedingt kippen. Injury-TTL ist 336h (14 Tage); ein hartkodiertes
    Datum wird nach zwei Wochen stale, team_news_impact ueberspringt das
    Item und der xG-Effekt faellt auf 0.0 (gleiche Klasse wie T-0069)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _still_effective() -> str:
    """effective_until weit in der Zukunft -- fuer Turnier-Ausfall-Items.

    ACHTUNG, andere Unterklasse als _recent_published_at(): Items, die
    `tournament_long_signal` erfuellen (Schwere >= critical, Kategorie
    injury/illness/suspension/squad, Text enthaelt "world cup" plus ein
    Ausfall-Keyword), umgehen die TTL-Logik komplett und haengen an der
    ABSOLUTEN Konstante news.WORLD_CUP_NEWS_EFFECTIVE_UNTIL (20.07.2026).
    Ein frisches published_at aendert daran nichts -- das ist empirisch am
    21.07.2026 belegt, als genau diese Tests kippten und der Umbau auf
    _recent_published_at() sie NICHT reparierte.

    freshness_status() prueft effective_until VOR tournament_long_signal,
    deshalb ist das hier der einzige Weg, der greift.
    Fehlerklasse T-0069/T-0118, aber anderer Codepfad.
    """
    return (datetime.now(timezone.utc) + timedelta(days=3650)).replace(microsecond=0).isoformat()


_ROUNDUP_TIMBER = {
    "title": "Netherlands' Timber out of World Cup with injury",
    "summary": (
        "Arsenal defender Jurrien Timber is ruled out of the Netherlands' "
        "World Cup campaign with a groin injury, while Brazil's Neymar is "
        "making good progress from injury."
    ),
    "categories": ["injury"],
    "severity": "critical",
    "teams": ["Brazil", "Netherlands"],
    "freshness": "fresh",
    "model_relevant": True,
    "relevance": "high",
}


class MultiTeamRoundupNewsTests(unittest.TestCase):
    def test_recovery_only_team_is_detected(self):
        # Brazil-Teil ist 'making good progress' -> Recovery-only -> unterdruecken.
        self.assertTrue(_team_news_is_recovery_only("Brazil", _ROUNDUP_TIMBER))
        # Netherlands-Teil ist 'ruled out' -> echter Ausfall -> NICHT unterdruecken.
        self.assertFalse(_team_news_is_recovery_only("Netherlands", _ROUNDUP_TIMBER))

    def test_negative_phrase_beats_recovery(self):
        item = {
            "title": "X blow", "summary": "Star is ruled out but making good progress on a return.",
            "categories": ["injury"], "severity": "critical", "teams": ["X"],
        }
        self.assertFalse(_team_news_is_recovery_only("X", item))

    def test_team_impact_suppresses_recovery_team_keeps_injured_team(self):
        brazil = team_news_impact("Brazil", [_ROUNDUP_TIMBER])
        netherlands = team_news_impact("Netherlands", [_ROUNDUP_TIMBER])
        # Brazil: kein Negativ-Effekt mehr (Recovery-only Nennung).
        self.assertEqual(brazil["critical"], 0)
        self.assertEqual(brazil["attack_delta"], 0.0)
        # Netherlands: echter kritischer Ausfall bleibt.
        self.assertEqual(netherlands["critical"], 1)
        self.assertLess(netherlands["attack_delta"], 0.0)


class FixtureScopedNewsTests(unittest.TestCase):
    def test_annotation_preserves_match_scope(self):
        item = annotate_news(
            [
                {
                    "title": "Pulisic ruled out for USA",
                    "teams": ["USA"],
                    "match_ids": ["gd-021"],
                }
            ],
            ["USA"],
        )[0]

        self.assertEqual(item["match_ids"], ["gd-021"])

    def test_dedupe_prefers_the_safer_scoped_copy(self):
        common = {
            "title": "Pulisic ruled out for USA",
            "url": "https://example.test/pulisic",
            "teams": ["USA"],
            "categories": ["injury"],
            "severity": "critical",
            "reliability": "high",
            "model_relevant": True,
        }

        result = dedupe_news([common, {**common, "match_ids": ["gd-021"]}])

        self.assertEqual(result[0]["match_ids"], ["gd-021"])

    def test_match_scoped_news_only_applies_to_named_fixture(self):
        item = {
            "teams": ["USA"],
            "match_ids": ["gd-021"],
            "severity": "critical",
        }
        current = {"match_id": "gd-021", "home_team": "USA", "away_team": "Australia"}
        future = {"match_id": "gd-023", "home_team": "Turkey", "away_team": "USA"}

        self.assertEqual(news_for_fixture(current, [item]), [item])
        self.assertEqual(news_for_fixture(future, [item]), [])


def _multi(title, summary, teams, severity="critical"):
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


class InjurySubjectAttributionTests(unittest.TestCase):
    """Wurzel-Attribution: ein Multi-Team-Item wird nur dem tatsaechlich
    betroffenen Team zugeordnet (T-0064 root-fix)."""

    def test_incidental_multi_team_mention_not_attributed(self):
        item = _multi(
            "Germany's Mueller ruled out",
            "Germany's Mueller is ruled out, while Brazil prepare for the match.",
            ["Germany", "Brazil"],
        )
        self.assertTrue(team_is_injury_subject("Germany", item))
        self.assertFalse(team_is_injury_subject("Brazil", item))  # nur inzidentell
        self.assertEqual(team_news_impact("Brazil", [item])["attack_delta"], 0.0)
        self.assertLess(team_news_impact("Germany", [item])["attack_delta"], 0.0)

    def test_affliction_without_explicit_absence_is_attributed(self):
        item = _multi(
            "Neymar injury scare",
            "Brazil's Neymar picks up a knock in training, while Germany rest players.",
            ["Brazil", "Germany"],
        )
        self.assertTrue(team_is_injury_subject("Brazil", item))  # 'knock'
        self.assertFalse(team_is_injury_subject("Germany", item))

    def test_single_team_injury_with_split_clauses_still_counts(self):
        # Land und Verletzungsphrase in getrennten Saetzen -> Einzel-Team
        # darf NICHT verloren gehen (kein Mehrdeutigkeitsrisiko).
        item = _multi(
            "Star striker ruled out for the tournament",
            "The forward suffered an injury. Germany face Spain next.",
            ["Germany"],
        )
        self.assertTrue(team_is_injury_subject("Germany", item))

    def test_single_team_recovery_only_suppressed(self):
        item = _multi(
            "Germany boost",
            "Germany's Mueller is fit again and back in training.",
            ["Germany"],
        )
        self.assertFalse(team_is_injury_subject("Germany", item))

    def test_pool_player_reference_attributes_without_country_word(self):
        # Klausel nennt nur den Spieler, nicht das Land -> Pool-Referenz.
        item = _multi(
            "World Cup injury news",
            "Neymar is ruled out of the tournament, while Spain rest players.",
            ["Brazil", "Spain"],
        )
        pool = {"Brazil": [{"name": "Neymar", "goal_share": 0.4}]}
        self.assertTrue(team_is_injury_subject("Brazil", item, pool))
        # Ohne Pool ist 'Brazil' in keiner Klausel referenziert -> inzidentell.
        self.assertFalse(team_is_injury_subject("Brazil", item))
        self.assertFalse(team_is_injury_subject("Spain", item, pool))


def _travel(team, title, summary=""):
    return {
        "title": title, "summary": summary, "categories": ["travel"],
        "severity": "important", "teams": [team] if isinstance(team, str) else list(team),
        "freshness": "fresh", "model_relevant": True, "relevance": "high",
    }


class EntryDisruptionNewsTests(unittest.TestCase):
    """T-0066: kuratiertes Einreise-/Prep-Stoerungs-Sub-Signal."""

    def test_strong_entry_phrase_detected(self):
        item = _travel("Iran", "Iran only allowed to enter on matchday, less than 48 hours before kickoff")
        self.assertEqual(entry_disruption_severity("Iran", item), "strong")

    def test_neutral_travel_news_not_flagged(self):
        item = _travel("Spain", "Spain complete training camp ahead of the World Cup")
        self.assertIsNone(entry_disruption_severity("Spain", item))

    def test_stale_not_flagged_low_relevance_still_caught(self):
        stale = {**_travel("Iran", "Iran denied entry"), "freshness": "stale"}
        self.assertIsNone(entry_disruption_severity("Iran", stale))
        # T-0067: KEIN model_relevant-Gate mehr -> eine klare Phrase wird
        # auch bei low-Relevanz erkannt (Einreise-News stuft der generische
        # Klassifizierer oft als noise/context ein).
        low = {**_travel("Iran", "Iran denied entry"), "model_relevant": False, "relevance": "low"}
        self.assertEqual(entry_disruption_severity("Iran", low), "mild")

    def test_host_nation_never_flagged(self):
        # T-0067: Gastgeber (USA/Mexico/Canada) sind Zielland, nicht Betroffene.
        item = _travel("USA", "Visiting teams only allowed to enter the USA on matchday")
        self.assertIsNone(entry_disruption_severity("USA", item))

    def test_multi_team_incidental_not_attributed(self):
        item = _travel(
            ["Senegal", "Iran"],
            "Travel update",
            "Senegal were refused entry to the United States, while Iran trained as planned.",
        )
        self.assertEqual(entry_disruption_severity("Senegal", item), "mild")
        self.assertIsNone(entry_disruption_severity("Iran", item))


POOL_FRANCE = {
    "France": [
        {"name": "Kylian Mbappé", "goal_share": 0.70},
        {"name": "Ousmane Dembélé", "goal_share": 0.18, "source_aliases": ["Ousmane Dembele"]},
    ]
}

# Mit position/role (T-0040): Stuermer-Starter, Verteidiger-Starter, Backup.
POOL_POS = {
    "Spain": [
        {"name": "Stuermer Star", "goal_share": 0.55, "position": "ST", "role": "starter"},
        {"name": "Abwehr Boss", "goal_share": 0.25, "position": "CB", "role": "starter"},
        {"name": "Bank Spieler", "goal_share": 0.20, "position": "ST", "role": "backup"},
    ]
}


def _impact_for_player(team, pool, player_name):
    items = annotate_news(
        [
            {
                "title": f"{player_name} ruled out with injury for {team}",
                "teams": [team],
                "players": [player_name.split()[-1]],
                "published_at": _recent_published_at(),
            }
        ],
        [team],
    )
    return team_news_impact(team, items, pool)


class NewsTests(unittest.TestCase):
    def test_classifies_critical_injury(self):
        result = classify_text("Germany striker ruled out with knee injury")
        self.assertIn("injury", result["categories"])
        self.assertEqual(result["severity"], "critical")

    def test_classifies_surgery_as_injury(self):
        result = classify_text("Netherlands defender ruled out of World Cup after back surgery")
        self.assertIn("injury", result["categories"])
        self.assertEqual(result["severity"], "critical")

    def test_out_keyword_does_not_match_about(self):
        result = classify_text("All you need to know about promotion and relegation")
        self.assertEqual(result["severity"], "noise")

    def test_out_keyword_does_not_match_month_out_context(self):
        result = classify_text(
            "Dick Advocaat makes a surprise return as Curacao head coach a month out from their World Cup debut."
        )
        self.assertIn("coach", result["categories"])
        self.assertEqual(result["severity"], "context")

    def test_omitted_squad_player_is_critical_without_standalone_out(self):
        result = classify_text("Chucky Lozano omitted from Mexico provisional World Cup squad")
        self.assertIn("squad", result["categories"])
        self.assertEqual(result["severity"], "critical")

    def test_travel_bond_story_is_not_player_suspension(self):
        rows = annotate_news(
            [
                {
                    "title": "US waives bonds of up to $15,000 for 2026 ticket holders from flagged countries",
                    "summary": (
                        "The administration has suspended a requirement that foreign visitors "
                        "from World Cup countries pay bonds to enter the United States."
                    ),
                    "published_at": "2026-05-15T10:00:00+00:00",
                }
            ],
            ["USA"],
        )
        self.assertIn("travel", rows[0]["categories"])
        self.assertNotIn("suspension", rows[0]["categories"])
        self.assertEqual(rows[0]["severity"], "context")
        self.assertTrue(rows[0]["model_relevant"])
        impact = team_news_impact("USA", rows)
        self.assertEqual(impact["attack_delta"], 0.0)

    def test_duplicate_sources_for_same_player_news_count_once(self):
        rows = annotate_news(
            [
                {
                    "source": "bbc",
                    "title": "Germany forward Lennart Karl ruled out of World Cup",
                    "summary": "Germany forward Lennart Karl is ruled out with a thigh injury.",
                    "published_at": "2026-06-06T12:00:00+00:00",
                    "effective_until": _still_effective(),
                },
                {
                    "source": "espn",
                    "title": "Germany's Karl out of WC after training injury",
                    "summary": "Germany's 18-year-old midfielder Lennart Karl will miss the World Cup after suffering an injury in training on Friday.",
                    "url": "https://www.espn.com/soccer/story/_/id/48977173/lennart-karl-injured-germany-training-miss-world-cup",
                    "published_at": "2026-06-06T13:00:00+00:00",
                    "effective_until": _still_effective(),
                },
            ],
            ["Germany"],
        )
        impact = team_news_impact("Germany", rows)
        self.assertEqual(impact["raw_impact_items"], 2)
        self.assertEqual(impact["deduped_impact_items"], 1)
        self.assertEqual(impact["critical"], 1)
        self.assertAlmostEqual(impact["attack_delta"], -0.18)
        self.assertAlmostEqual(impact["defense_delta"], 0.10)

    def test_different_players_for_same_team_news_count_separately(self):
        rows = annotate_news(
            [
                {
                    "title": "Germany forward Lennart Karl ruled out of World Cup",
                    "summary": "Germany forward Lennart Karl is ruled out with a thigh injury.",
                    "published_at": "2026-06-06T12:00:00+00:00",
                    "effective_until": _still_effective(),
                },
                {
                    "title": "Germany defender Antonio Rudiger ruled out of World Cup",
                    "summary": "Germany defender Antonio Rudiger will miss the World Cup with a knee injury.",
                    "published_at": "2026-06-06T13:00:00+00:00",
                    "effective_until": _still_effective(),
                },
            ],
            ["Germany"],
        )
        impact = team_news_impact("Germany", rows)
        self.assertEqual(impact["raw_impact_items"], 2)
        self.assertEqual(impact["deduped_impact_items"], 2)
        self.assertEqual(impact["critical"], 2)
        self.assertAlmostEqual(impact["attack_delta"], -0.36)
        self.assertAlmostEqual(impact["defense_delta"], 0.20)

    def test_training_camp_leaves_is_not_squad_omission(self):
        rows = annotate_news(
            [
                {
                    "title": "Iran edge closer to USA after positive FIFA talks as team leaves for Turkish training camp",
                    "summary": "FIFA held positive talks on the team's participation in the World Cup.",
                    "published_at": "2026-05-18T10:00:00+00:00",
                }
            ],
            ["Iran", "Turkey", "USA"],
        )
        self.assertIn("travel", rows[0]["categories"])
        self.assertNotIn("squad", rows[0]["categories"])
        self.assertEqual(rows[0]["severity"], "context")
        self.assertTrue(rows[0]["model_relevant"])

    def test_club_league_story_without_national_context_is_low_relevance(self):
        rows = annotate_news(
            [
                {
                    "title": "Ups, downs and the race for Europe",
                    "summary": "All you need to know about promotion in England and Scotland leagues.",
                    "published_at": "2026-05-10T17:00:00+00:00",
                }
            ],
            ["England", "Scotland"],
        )
        self.assertEqual(rows[0]["relevance"], "low")
        self.assertFalse(rows[0]["model_relevant"])
        self.assertEqual(rows[0]["severity"], "noise")

    def test_womens_world_cup_story_is_low_relevance_for_mens_fixture_team(self):
        rows = annotate_news(
            [
                {
                    "title": "England Women name squad for Women's World Cup qualifiers",
                    "summary": "The Lionesses prepare for Spain Women next month.",
                    "published_at": "2026-05-18T12:00:00+00:00",
                }
            ],
            ["England", "Spain"],
        )
        self.assertEqual(rows[0]["relevance"], "low")
        self.assertFalse(rows[0]["model_relevant"])
        self.assertEqual(rows[0]["relevance_reason"], "Frauen-/Nicht-Maenner-Kontext statt WM-2026-Maennerteam.")

    def test_retrospective_job_interview_is_not_model_relevant(self):
        rows = annotate_news(
            [
                {
                    "title": "I turned down Leicester thinking I was going to get the USA job",
                    "summary": "Jesse Marsch reflects on missing out on the USMNT job.",
                    "url": "https://www.fourfourtwo.com/features/jesse-marsch-missing-out-usmnt-job-canada",
                    "published_at": "2026-05-17T12:00:00+00:00",
                }
            ],
            ["Canada", "USA"],
        )
        self.assertEqual(rows[0]["relevance"], "low")
        self.assertFalse(rows[0]["model_relevant"])
        self.assertEqual(rows[0]["severity"], "noise")

    def test_team_matching_uses_word_boundaries(self):
        rows = annotate_news(
            [
                {
                    "title": "A club refusal creates late transfer noise",
                    "published_at": "2026-05-10T17:00:00+00:00",
                }
            ],
            ["USA"],
        )
        self.assertEqual(rows[0]["teams"], [])
        self.assertEqual(rows[0]["relevance"], "low")

    def test_world_cup_story_with_team_context_stays_relevant(self):
        rows = annotate_news(
            [
                {
                    "title": "France star ruled out with knee injury",
                    "summary": "Bad news for France ahead of the World Cup.",
                    "published_at": "2026-06-10T17:00:00+00:00",
                }
            ],
            ["France"],
        )
        self.assertEqual(rows[0]["relevance"], "high")
        self.assertTrue(rows[0]["model_relevant"])
        self.assertEqual(rows[0]["severity"], "critical")

    def test_world_cup_unavailable_signal_is_model_relevant_without_category_keyword(self):
        rows = annotate_news(
            [
                {
                    "title": "France captain not available for the World Cup",
                    "summary": "France must replace him before the tournament.",
                    "published_at": "2026-06-10T17:00:00+00:00",
                }
            ],
            ["France"],
        )
        self.assertEqual(rows[0]["categories"], ["general"])
        self.assertEqual(rows[0]["relevance"], "medium")
        self.assertTrue(rows[0]["model_relevant"])
        self.assertEqual(rows[0]["severity"], "critical")

    def test_url_slug_exposes_generic_world_cup_lineup_context(self):
        rows = annotate_news(
            [
                {
                    "title": "Who will start? Predicted XIs for the 2026 World C...",
                    "summary": "We're just a month away from the 2026 World Cup.",
                    "url": (
                        "https://www.espn.com/soccer/story/_/id/48677243/"
                        "2026-world-cup-rosters-predictions-starting-xis-"
                        "usa-france-mexico-england-spain-germany-brazil-argentina"
                    ),
                    "published_at": "2026-05-13T12:00:00+00:00",
                }
            ],
            ["USA", "France", "Mexico", "England", "Spain", "Germany", "Brazil", "Argentina"],
        )
        self.assertEqual(
            set(rows[0]["teams"]),
            {"USA", "France", "Mexico", "England", "Spain", "Germany", "Brazil", "Argentina"},
        )
        self.assertIn("expected_lineup", rows[0]["categories"])
        self.assertEqual(rows[0]["severity"], "context")
        self.assertEqual(rows[0]["relevance"], "high")
        self.assertTrue(rows[0]["model_relevant"])

    def test_url_slug_team_aliases_are_normalized_to_fixture_team_names(self):
        rows = annotate_news(
            [
                {
                    "title": "World Cup roster watch",
                    "url": "https://example.com/world-cup-lineup-united-states-korea-republic-curacao",
                    "published_at": "2026-05-13T12:00:00+00:00",
                }
            ],
            ["USA", "South Korea", "Curaçao"],
        )
        self.assertEqual(set(rows[0]["teams"]), {"USA", "South Korea", "Curaçao"})

    def test_existing_live_item_is_reclassified_when_rules_change(self):
        rows = annotate_news(
            [
                {
                    "source": "https://www.espn.com/espn/rss/soccer/news",
                    "title": "Who will start? Predicted XIs for the 2026 World C...",
                    "summary": "We're just a month away from the 2026 World Cup.",
                    "url": (
                        "https://www.espn.com/soccer/story/_/id/48677243/"
                        "2026-world-cup-rosters-predictions-starting-xis-usa-france"
                    ),
                    "published_at": "2026-05-13T12:00:00+00:00",
                    "teams": [],
                    "categories": ["general"],
                    "severity": "noise",
                    "relevance": "low",
                    "model_relevant": False,
                }
            ],
            ["USA", "France"],
        )
        self.assertEqual(set(rows[0]["teams"]), {"USA", "France"})
        self.assertIn("expected_lineup", rows[0]["categories"])
        self.assertEqual(rows[0]["severity"], "context")
        self.assertEqual(rows[0]["relevance"], "high")
        self.assertTrue(rows[0]["model_relevant"])

    def test_manual_source_labels_are_preserved_before_storage(self):
        rows = annotate_news(
            [
                {
                    "source": "https://example.com/manual-note",
                    "title": "Manual weather note for France",
                    "published_at": "2026-05-13T12:00:00+00:00",
                    "teams": ["France"],
                    "categories": ["weather"],
                    "severity": "important",
                }
            ],
            ["France"],
        )
        self.assertEqual(rows[0]["categories"], ["weather"])
        self.assertEqual(rows[0]["severity"], "important")

    def test_story_without_fixture_team_is_low_relevance(self):
        rows = annotate_news(
            [
                {
                    "title": "World Cup stars may be out of contract",
                    "summary": "Broad market overview without naming a 2026 fixture team.",
                    "published_at": "2026-05-10T17:00:00+00:00",
                }
            ],
            ["France"],
        )
        self.assertEqual(rows[0]["relevance"], "low")
        self.assertFalse(rows[0]["model_relevant"])

    def test_dedupes_by_url(self):
        rows = annotate_news(
            [
                {"title": "A", "url": "https://example.com/a", "published_at": "2026-06-01T10:00:00+00:00"},
                {"title": "A again", "url": "https://example.com/a", "published_at": "2026-06-01T11:00:00+00:00"},
            ],
            ["Germany"],
        )
        self.assertEqual(len(dedupe_news(rows)), 1)

    def test_dedupes_url_tracking_parameters(self):
        rows = annotate_news(
            [
                {
                    "id": "legacy-rss-id",
                    "source": "rss",
                    "title": "Zaha omitted",
                    "url": "https://www.bbc.com/sport/football/articles/c9360dwzl2lo?at_medium=RSS&at_campaign=rss",
                    "published_at": "2026-05-15T16:43:11+00:00",
                    "severity": "critical",
                    "reliability": "medium",
                },
                {
                    "source": "manual",
                    "title": "Zaha omitted canonical",
                    "url": "https://www.bbc.com/sport/football/articles/c9360dwzl2lo",
                    "published_at": "2026-05-15T16:43:11+00:00",
                    "severity": "critical",
                    "reliability": "high",
                },
            ],
            ["Ivory Coast"],
        )
        deduped = dedupe_news(rows)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["source"], "manual")

    def test_team_impact_moves_xg(self):
        items = annotate_news(
            [
                {
                    "title": "France captain ruled out with injury",
                    "teams": ["France"],
                    "published_at": _recent_published_at(),
                }
            ],
            ["France"],
        )
        impact = team_news_impact("France", items)
        self.assertLess(impact["attack_delta"], 0)
        self.assertGreater(impact["defense_delta"], 0)

    def test_player_weight_matches_pool_accent_tolerant(self):
        self.assertAlmostEqual(
            player_weight_from_pool("France", ["mbappe"], POOL_FRANCE), 0.70, places=4
        )
        # Akzent/Alias: Dembele aus News matcht Dembélé im Pool.
        self.assertAlmostEqual(
            player_weight_from_pool("France", ["dembele"], POOL_FRANCE), 0.18, places=4
        )

    def test_player_weight_none_when_no_match_or_no_pool(self):
        self.assertIsNone(player_weight_from_pool("France", ["unbekannt"], POOL_FRANCE))
        self.assertIsNone(player_weight_from_pool("France", ["mbappe"], None))
        self.assertIsNone(player_weight_from_pool("Germany", ["mbappe"], POOL_FRANCE))

    def test_top_scorer_injury_hits_harder_than_backup(self):
        def impact_for(player_title):
            items = annotate_news(
                [
                    {
                        "title": f"{player_title} ruled out with injury for France",
                        "teams": ["France"],
                        "players": [player_title.split()[-1]],
                        "published_at": _recent_published_at(),
                    }
                ],
                ["France"],
            )
            return team_news_impact("France", items, POOL_FRANCE)

        star = impact_for("Kylian Mbappé")
        backup = impact_for("Ousmane Dembélé")
        # Star (share 0.70) zieht mehr xG ab als Backup (share 0.18).
        self.assertLess(star["attack_delta"], backup["attack_delta"])
        self.assertEqual(star["individual_scaled_items"], 1)
        # Star ueber Pauschale -0.18, Backup darunter (Richtung 0).
        self.assertLess(star["attack_delta"], -0.18)
        self.assertGreater(backup["attack_delta"], -0.18)

    def test_defender_injury_routes_to_defense_not_attack(self):
        # T-0040: Verteidiger-Ausfall hebt die eigene Defensive (Gegner
        # trifft mehr), Offensive bleibt unberuehrt.
        impact = _impact_for_player("Spain", POOL_POS, "Abwehr Boss")
        self.assertEqual(impact["attack_delta"], 0.0)
        self.assertGreater(impact["defense_delta"], 0.0)
        self.assertEqual(impact["defensive_routed_items"], 1)

    def test_striker_injury_routes_to_attack_no_opponent_boost(self):
        # T-0040: bekannter Stuermer -> nur eigene Offensive, kein
        # pauschaler Gegner-Defensiv-Boost.
        impact = _impact_for_player("Spain", POOL_POS, "Stuermer Star")
        self.assertLess(impact["attack_delta"], 0.0)
        self.assertEqual(impact["defense_delta"], 0.0)

    def test_backup_role_dampens_effect(self):
        # T-0040: Backup-Ausfall wirkt schwaecher als Starter mit
        # vergleichbarem Share.
        starter = _impact_for_player("Spain", POOL_POS, "Stuermer Star")
        backup = _impact_for_player("Spain", POOL_POS, "Bank Spieler")
        self.assertLess(abs(backup["attack_delta"]), abs(starter["attack_delta"]))

    def test_drop_off_amplifies_irreplaceable_top_scorer(self):
        # T-0041: klarer Top-Scorer ohne gleichwertigen Ersatz -> Drop-Off > 1.
        prof = player_profile_from_pool("France", ["mbappe"], POOL_FRANCE)
        self.assertGreater(prof["drop_off"], 1.0)
        # Flacher Kader -> Drop-Off nahe 1.
        flat = {"X": [
            {"name": "Alpha", "goal_share": 0.34},
            {"name": "Bravo", "goal_share": 0.33},
            {"name": "Charlie", "goal_share": 0.33},
        ]}
        prof_flat = player_profile_from_pool("X", ["alpha"], flat)
        self.assertLess(prof_flat["drop_off"], 1.05)

    def test_drop_off_stays_flat_when_equal_replacement_exists(self):
        tied = {"X": [
            {"name": "Alpha", "goal_share": 0.5},
            {"name": "Bravo", "goal_share": 0.5},
            {"name": "Charlie", "goal_share": 0.0},
        ]}
        prof = player_profile_from_pool("X", ["alpha"], tied)
        self.assertEqual(prof["drop_off"], 1.0)

    def test_unknown_player_falls_back_to_flat_bucket(self):
        items = annotate_news(
            [
                {
                    "title": "France defender ruled out with injury",
                    "teams": ["France"],
                    "published_at": _recent_published_at(),
                }
            ],
            ["France"],
        )
        # Ohne erkannten Pool-Spieler bleibt die Pauschale -0.18.
        impact = team_news_impact("France", items, POOL_FRANCE)
        self.assertAlmostEqual(impact["attack_delta"], -0.18, places=4)
        self.assertEqual(impact["individual_scaled_items"], 0)

    def test_lineup_news_does_not_create_xg_penalty(self):
        # T-0069: published_at relativ zu now, sonst kippt der Test
        # datumsbedingt -- confirmed_lineup-Frische ist kurz (~Spieltag),
        # ein hartkodiertes Near-Now-Datum wird ab dem Folgetag stale.
        recent = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        items = annotate_news(
            [
                {
                    "title": "France starting XI confirmed for World Cup opener",
                    "teams": ["France"],
                    "published_at": recent,
                }
            ],
            ["France"],
        )
        impact = team_news_impact("France", items)
        self.assertEqual(impact["attack_delta"], 0.0)
        self.assertEqual(impact["defense_delta"], 0.0)
        self.assertTrue(impact["lineup_confirmed"])

    def test_squad_news_stays_fresh_beyond_default_window(self):
        now = datetime(2026, 5, 18, tzinfo=timezone.utc)
        item = {
            "categories": ["squad"],
            "severity": "critical",
            "published_at": "2026-05-13T00:19:17+00:00",
        }
        self.assertEqual(freshness_status(item, now=now), "fresh")

    def test_context_squad_news_uses_default_freshness_window(self):
        now = datetime(2026, 5, 18, tzinfo=timezone.utc)
        item = {
            "categories": ["squad"],
            "severity": "context",
            "published_at": "2026-05-13T00:19:17+00:00",
        }
        self.assertEqual(freshness_status(item, now=now), "stale")

    def test_tournament_out_injury_stays_fresh_until_world_cup_end(self):
        item = {
            "categories": ["injury"],
            "severity": "critical",
            "published_at": "2026-05-15T16:00:00+00:00",
            "title": "Netherlands defender ruled out of World Cup after back surgery",
        }
        self.assertEqual(
            freshness_status(item, now=datetime(2026, 7, 19, tzinfo=timezone.utc)),
            "fresh",
        )
        self.assertEqual(
            freshness_status(item, now=datetime(2026, 7, 22, tzinfo=timezone.utc)),
            "stale",
        )

    def test_tournament_squad_omission_stays_fresh_until_world_cup_end(self):
        item = {
            "categories": ["squad"],
            "severity": "critical",
            "published_at": "2026-05-15T16:00:00+00:00",
            "title": "Zaha omitted from Ivory Coast World Cup squad",
        }
        self.assertEqual(
            freshness_status(item, now=datetime(2026, 7, 19, tzinfo=timezone.utc)),
            "fresh",
        )

    def test_manual_effective_until_overrides_default_freshness(self):
        item = {
            "categories": ["injury"],
            "severity": "critical",
            "published_at": "2026-05-13T00:00:00+00:00",
            "effective_until": "2026-07-20T23:59:59+00:00",
        }
        self.assertEqual(
            freshness_status(item, now=datetime(2026, 7, 19, tzinfo=timezone.utc)),
            "fresh",
        )

    def test_dedupe_prefers_high_reliability_manual_signal(self):
        rows = dedupe_news(
            [
                {
                    "id": "same",
                    "source": "rss",
                    "severity": "critical",
                    "reliability": "medium",
                    "title": "RSS title",
                    "published_at": "2026-05-15T16:00:00+00:00",
                },
                {
                    "id": "same",
                    "source": "manual",
                    "severity": "critical",
                    "reliability": "high",
                    "title": "Manual title",
                    "published_at": "2026-05-15T16:00:00+00:00",
                },
            ]
        )
        self.assertEqual(rows[0]["source"], "manual")

    def test_dedupe_prefers_model_impact_classification(self):
        rows = dedupe_news(
            [
                {
                    "id": "legacy-id",
                    "source": "stored",
                    "title": "De Ligt ruled out of World Cup after back surgery",
                    "url": "https://www.espn.com/soccer/story/_/id/48783229/netherlands-defender-matthijs-de-ligt-ruled-world-cup-back-surgery",
                    "categories": ["general"],
                    "severity": "critical",
                    "reliability": "high",
                    "model_relevant": True,
                    "effective_until": "2026-07-20T23:59:59+00:00",
                    "published_at": "2026-05-16T04:29:03+00:00",
                },
                {
                    "source": "manual",
                    "title": "De Ligt ruled out of World Cup after back surgery",
                    "url": "https://www.espn.com/soccer/story/_/id/48783229/netherlands-defender-matthijs-de-ligt-ruled-world-cup-back-surgery",
                    "categories": ["injury"],
                    "severity": "critical",
                    "reliability": "high",
                    "model_relevant": True,
                    "effective_until": "2026-07-20T23:59:59+00:00",
                    "published_at": "2026-05-16T04:29:03+00:00",
                },
            ]
        )
        self.assertEqual(rows[0]["source"], "manual")
        self.assertEqual(rows[0]["categories"], ["injury"])


class MatchOfficialNewsTests(unittest.TestCase):
    """Referee-/Offiziellen-Ausfaelle duerfen keinen xG-Impact ausloesen
    (sonst trifft eine Schiedsrichter-News beide getaggten Teams als
    Pauschal-Ausfall). Regression zum Bug 'Injured referee Oliver to miss
    World Cup match' -> CIV und ECU je -0.18 attack."""

    REFEREE_ITEM = {
        "title": "Injured referee Oliver to miss World Cup match",
        "summary": (
            "English referee Michael Oliver is ruled out of the group "
            "match between Ivory Coast and Ecuador."
        ),
        "categories": ["injury"],
        "severity": "critical",
        "players": [],
        "teams": ["Ecuador", "Ivory Coast"],
        "freshness": "fresh",
        "model_relevant": True,
        "reliability": "medium",
        "published_at": "2026-06-13T08:47:19+00:00",
    }

    def test_referee_injury_no_xg_impact_for_either_team(self):
        for team in ("Ivory Coast", "Ecuador"):
            impact = team_news_impact(team, [self.REFEREE_ITEM])
            self.assertEqual(impact["attack_delta"], 0.0, team)
            self.assertEqual(impact["defense_delta"], 0.0, team)
            self.assertEqual(impact["critical"], 0, team)

    def test_named_player_injury_still_counts(self):
        # Gegenprobe: echte Spieler-News (players gesetzt) bleibt wirksam,
        # selbst wenn das Wort 'referee' beilaeufig vorkommt.
        item = {
            "title": "Striker ruled out after clash with referee's call",
            "summary": "Ivory Coast forward is ruled out with a torn muscle.",
            "categories": ["injury"],
            "severity": "critical",
            "players": ["Some Forward"],
            "teams": ["Ivory Coast"],
            "freshness": "fresh",
            "model_relevant": True,
            "reliability": "high",
        }
        impact = team_news_impact("Ivory Coast", [item])
        self.assertLess(impact["attack_delta"], 0.0)


class CapNewsWithManualTests(unittest.TestCase):
    """Regression: kuratierte manual_news duerfen nie aus dem max_items-Cap
    fallen (sonst ignoriert das Modell De Ligt/Ben White/Brasilien still)."""

    def test_manual_survives_cap(self):
        rss = [{"title": f"rss{i}", "url": f"http://r/{i}"} for i in range(5)]
        manual = [
            {"title": "Ben White out", "url": "http://m/bw"},
            {"title": "De Ligt out", "url": "http://m/dl"},
        ]
        capped = cap_news_with_manual(rss, manual, 3)
        titles = {c["title"] for c in capped}
        self.assertIn("Ben White out", titles)
        self.assertIn("De Ligt out", titles)
        self.assertEqual(len([c for c in capped if c["title"].startswith("rss")]), 3)

    def test_manual_already_in_cap_not_duplicated(self):
        manual = [{"title": "Ben White out", "url": "http://m/bw"}]
        deduped = manual + [{"title": "rss0", "url": "http://r/0"}]
        capped = cap_news_with_manual(deduped, manual, 5)
        self.assertEqual(sum(1 for c in capped if c["title"] == "Ben White out"), 1)


if __name__ == "__main__":
    unittest.main()
