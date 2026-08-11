from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.history import (
    _collapse_oscillations,
    bonus_change_event,
    enrich_history_events,
    group_winner_change_events,
    prediction_change_event,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID, round_name



ROUND_NAME = round_name(DEFAULT_ROUND_ID)
ROUND_NAME_2 = round_name(SECONDARY_ROUND_ID)


def _hev(mid, ca, ft, tt, trigger="Modell", round_name=ROUND_NAME):
    return {"match_id": mid, "round_name": round_name, "changed_at": ca,
            "from_tip": ft, "to_tip": tt, "trigger": trigger}


class CollapseOscillationsTests(unittest.TestCase):
    def test_full_oscillation_back_to_start_vanishes(self):
        # Brazil-Haiti-Muster: 2:0->1:0->2:0->1:0->2:0, netto zurueck zu 2:0 (Start)
        # -> alle Hin-und-Her-Events verschwinden, auch ueber gemischte Trigger.
        evs = [_hev("gc", "2026-06-08T20:16", "2:0", "1:0", trigger="News"),
               _hev("gc", "2026-06-08T20:26", "1:0", "2:0", trigger="Teamstaerke/Kontext"),
               _hev("gc", "2026-06-11T09:21", "2:0", "1:0", trigger="News"),
               _hev("gc", "2026-06-18T16:00", "1:0", "2:0", trigger="Modell")]
        self.assertEqual(_collapse_oscillations(evs), [])

    def test_net_change_keeps_final_step_with_its_trigger(self):
        # pendelt, endet aber woanders -> EIN Netto-Event mit dem netto-wirksamen Trigger
        evs = [_hev("gc", "2026-06-08", "2:0", "1:0", trigger="News"),
               _hev("gc", "2026-06-11", "1:0", "2:0", trigger="Modell"),
               _hev("gc", "2026-06-14", "2:0", "1:0", trigger="News")]
        out = _collapse_oscillations(evs)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["from_tip"], out[0]["to_tip"], out[0]["trigger"]), ("2:0", "1:0", "News"))

    def test_genuine_progression_kept(self):
        # echte Progression A->B->C (keine Rueckkehr) bleibt vollstaendig
        evs = [_hev("ga", "2026-06-08", "1:0", "2:0"),
               _hev("ga", "2026-06-14", "2:0", "2:1", trigger="News")]
        out = _collapse_oscillations(evs)
        self.assertEqual(len(out), 2)

    def test_relog_same_state_dropped(self):
        evs = [_hev("ga", "2026-06-08", "1:0", "2:0"),
               _hev("ga", "2026-06-18", "1:0", "2:0")]  # Re-Log desselben Wechsels
        self.assertEqual(len(_collapse_oscillations(evs)), 1)

    def test_single_change_kept(self):
        self.assertEqual(len(_collapse_oscillations([_hev("ga", "2026-06-08", "1:0", "2:0")])), 1)

    def test_non_tip_events_passthrough(self):
        bonus = {"match_id": "bonus-world_champion", "round_name": None, "changed_at": "2026-06-01",
                 "trigger": "Bonus-Recalc", "from_tip": None, "to_tip": None}
        out = _collapse_oscillations([bonus])
        self.assertEqual(out, [bonus])

    def test_separate_matches_independent(self):
        evs = [_hev("ga", "2026-06-08", "1:0", "2:0"),
               _hev("gb", "2026-06-08", "0:1", "0:2")]
        self.assertEqual(len(_collapse_oscillations(evs)), 2)


def prediction(tip, expected=2.0, news=None, xg=None, stability="stabil"):
    return {
        "match_id": "ga-001",
        "fixture": {
            "home_team": "Mexico",
            "away_team": "South Africa",
            "kickoff_utc": "2026-06-11T19:00:00+00:00",
        },
        "recommended_tip": {
            "tip": tip,
            "expected_points": expected,
            "round_id": DEFAULT_ROUND_ID,
            "round_name": ROUND_NAME,
        },
        "round_tips": {
            DEFAULT_ROUND_ID: {
                "tip": tip,
                "expected_points": expected,
                "round_id": DEFAULT_ROUND_ID,
                "round_name": ROUND_NAME,
            }
        },
        "stability": stability,
        "news": news or [],
        "odds": None,
        "probabilities": {
            "blended": {"home": 0.55, "draw": 0.25, "away": 0.2},
        },
        "strength": {
            "home": {"elo": 1800, "attack": 1.4, "fifa_rank": 20, "form_adjustment": 0},
            "away": {"elo": 1600, "attack": 1.1, "fifa_rank": 60, "form_adjustment": 0},
        },
        "top_scores": [{"score": tip, "probability": 0.12}],
        "xg": xg or {"home": 1.2, "away": 0.9},
        "explanation": [],
    }


class HistoryTests(unittest.TestCase):
    def test_records_tip_change_with_news_trigger(self):
        old = prediction("1:0")
        new = prediction(
            "0:2",
            news=[{"id": "n1", "title": "Mexico captain ruled out", "severity": "critical"}],
        )
        event = prediction_change_event(old, new, changed_at="2026-06-10T10:00:00+00:00")
        self.assertIsNotNone(event)
        self.assertEqual(event["trigger"], "News")
        self.assertEqual(event["from_tip"], "1:0")
        self.assertEqual(event["to_tip"], "0:2")
        self.assertIn("Mexico captain ruled out", event["details"])
        self.assertEqual(event["snapshot"]["from"]["xg"]["home"], 1.2)
        self.assertEqual(event["snapshot"]["to"]["recommended_tip"]["tip"], "0:2")
        self.assertEqual(event["round_name"], ROUND_NAME)
        self.assertIn("2026-06-11T19:00:00+00:00", event["summary"])

    def test_ignores_expected_points_change_when_tip_stays_same(self):
        old = prediction("1:0", expected=2.0)
        new = prediction("1:0", expected=2.5)
        self.assertIsNone(prediction_change_event(old, new))

    def test_ignores_stability_change_when_tip_stays_same(self):
        old = prediction("1:0", stability="stabil")
        new = prediction("1:0", stability="volatil")
        self.assertIsNone(prediction_change_event(old, new))

    def test_records_metric_drilldown_for_xg_change(self):
        old = prediction("1:0", expected=2.0, xg={"home": 1.2, "away": 0.9})
        new = prediction("2:0", expected=2.3, xg={"home": 1.6, "away": 0.7})
        new["probabilities"]["blended"] = {"home": 0.65, "draw": 0.22, "away": 0.13}
        new["strength"]["home"]["elo"] = 1850
        event = prediction_change_event(old, new)
        self.assertIsNotNone(event)
        self.assertEqual(event["trigger"], "Teamstaerke/Kontext")
        self.assertTrue(any("Mexico" in detail and "Elo 1800 -> 1850" in detail for detail in event["details"]))
        self.assertTrue(any(detail.startswith("xG Mexico") for detail in event["details"]))
        self.assertIn("snapshot", event)

    def test_strength_change_outranks_incidental_news(self):
        # Live beobachtet: France-Senegal/Iran-NZ -- ein Elo-Refresh aenderte den
        # Staerke-Block, gleichzeitig aenderten sich News-IDs. Der Trigger
        # MUSS "Teamstaerke/Kontext" sein, nicht "News" (sonst sieht ein
        # Elo-/Staerke-Wechsel faelschlich wie eine News-Lage aus).
        old = prediction("0:1", news=[{"id": "old1", "title": "alt", "severity": "context"}])
        new = prediction("1:0", news=[{"id": "new1", "title": "Visa-News", "severity": "context"}])
        new["strength"]["home"]["elo"] = 2100  # Elo-Refresh
        new["xg"] = {"home": 1.6, "away": 1.0}
        event = prediction_change_event(old, new)
        self.assertIsNotNone(event)
        self.assertEqual(event["trigger"], "Teamstaerke/Kontext")
        self.assertTrue(any("Elo 1800 -> 2100" in detail for detail in event["details"]))

    def test_round_specific_event_uses_secondary_round_tip(self):
        old = prediction("1:0")
        new = prediction("1:0")
        old["round_tips"][SECONDARY_ROUND_ID] = {
            "tip": "1:1",
            "expected_points": 2.2,
            "round_id": SECONDARY_ROUND_ID,
            "round_name": ROUND_NAME_2,
        }
        new["round_tips"][SECONDARY_ROUND_ID] = {
            "tip": "2:1",
            "expected_points": 2.8,
            "round_id": SECONDARY_ROUND_ID,
            "round_name": ROUND_NAME_2,
        }
        event = prediction_change_event(old, new, round_id=SECONDARY_ROUND_ID)
        self.assertIsNotNone(event)
        self.assertEqual(event["round_name"], ROUND_NAME_2)
        self.assertEqual(event["from_tip"], "1:1")
        self.assertEqual(event["to_tip"], "2:1")


class BonusHistoryTests(unittest.TestCase):
    def test_bonus_event_when_champion_top1_changes(self):
        old = [{"team": "Argentina", "probability": 0.15}, {"team": "Spain", "probability": 0.14}]
        new = [{"team": "Spain", "probability": 0.16}, {"team": "Argentina", "probability": 0.13}]
        event = bonus_change_event("world_champion", old, new, changed_at="2026-06-01T00:00:00+00:00")
        self.assertIsNotNone(event)
        self.assertEqual(event["category"], "world_champion")
        self.assertIn("Argentina", event["from_tip"])
        self.assertIn("Spain", event["to_tip"])
        self.assertEqual(event["trigger"], "Bonus-Recalc")
        self.assertEqual(event["match_id"], "bonus-world_champion")
        self.assertEqual(event["snapshot"]["kind"], "bonus_ranking")
        self.assertEqual(event["snapshot"]["from_top"][0]["team"], "Argentina")
        self.assertEqual(event["snapshot"]["to_top"][0]["team"], "Spain")

    def test_bonus_event_skipped_when_top1_unchanged(self):
        old = [{"team": "Argentina", "probability": 0.15}, {"team": "Spain", "probability": 0.14}]
        new = [{"team": "Argentina", "probability": 0.17}, {"team": "Spain", "probability": 0.13}]
        self.assertIsNone(bonus_change_event("world_champion", old, new))

    def test_bonus_event_includes_trigger_reason(self):
        old = [{"team": "Argentina", "probability": 0.031}]
        new = [{"team": "England", "probability": 0.039}]
        event = bonus_change_event(
            "top_scorer_team", old, new, changed_inputs=["player_pool", "strengths"]
        )
        self.assertIsNotNone(event)
        self.assertIn("player_pool", event["trigger_reason"])
        self.assertIn("strengths", event["trigger_reason"])
        self.assertTrue(any("Ursache" in d for d in event["details"]))

    def test_bonus_event_handles_empty_old_ranking(self):
        new = [{"team": "Spain", "probability": 0.16}]
        event = bonus_change_event("top_scorer_team", [], new)
        self.assertIsNotNone(event)
        self.assertIn("n/a", event["from_tip"])
        self.assertIn("Spain", event["to_tip"])

    def test_group_winner_event_per_changed_group(self):
        old = {"A": [{"team": "Mexico", "probability": 0.32}]}
        new = {"A": [{"team": "South Africa", "probability": 0.34}]}
        events = group_winner_change_events(old, new, changed_inputs=["strengths"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["match_id"], "bonus-group_winner-A")
        self.assertEqual(events[0]["category"], "group_winners")
        self.assertIn("South Africa", events[0]["to_tip"])


class EnrichBonusHistoryTests(unittest.TestCase):
    def test_legacy_match_event_gets_round_and_kickoff_from_current_prediction(self):
        events = [
            {
                "changed_at": "now",
                "match_id": "ga-001",
                "match": "Mexico - South Africa",
                "from_tip": "1:0",
                "to_tip": "2:0",
                "trigger": "Modell",
            }
        ]
        enriched = enrich_history_events(events, [prediction("2:0")], {})
        self.assertEqual(enriched[0]["round_name"], ROUND_NAME)
        self.assertEqual(enriched[0]["kickoff_utc"], "2026-06-11T19:00:00+00:00")

    def test_legacy_bonus_event_reconstructs_from_top_from_label(self):
        events = [
            {
                "match_id": "bonus-top_scorer_team",
                "trigger": "Bonus-Recalc",
                "from_tip": "Argentina (3.1%)",
                "to_tip": "England (3.9%)",
                "category": "top_scorer_team",
            }
        ]
        current_bonus = {
            "top_scorer_team": [{"team": "England", "probability": 0.0391}]
        }
        enriched = enrich_history_events(events, [], current_bonus)
        snapshot = enriched[0]["snapshot"]
        self.assertEqual(snapshot["from_top"][0]["team"], "Argentina")
        self.assertAlmostEqual(snapshot["from_top"][0]["probability"], 0.031, places=4)

    def test_legacy_bonus_event_gets_to_top_from_current_bonus(self):
        # Bonus-Event ohne snapshot-Feld (Pre-T-0017-Fix-Stand)
        events = [
            {
                "changed_at": "2026-05-10T23:21:00+00:00",
                "match": "Bonus / Torschuetzenkoenig-Team",
                "match_id": "bonus-top_scorer_team",
                "trigger": "Bonus-Recalc",
                "from_tip": "Argentina (3.1%)",
                "to_tip": "England (3.9%)",
                "category": "top_scorer_team",
            }
        ]
        current_bonus = {
            "top_scorer_team": [
                {"team": "England", "probability": 0.0391},
                {"team": "Norway", "probability": 0.0340},
                {"team": "Portugal", "probability": 0.0327},
            ],
        }
        enriched = enrich_history_events(events, [], current_bonus)
        self.assertEqual(len(enriched), 1)
        snapshot = enriched[0]["snapshot"]
        self.assertEqual(snapshot["kind"], "bonus_ranking")
        self.assertEqual(snapshot["category"], "top_scorer_team")
        self.assertEqual(snapshot["to_top"][0]["team"], "England")
        # from_top wird jetzt aus from_tip rekonstruiert (Top-1).
        self.assertEqual(snapshot["from_top"][0]["team"], "Argentina")
        self.assertTrue(any("Vorher" in d for d in enriched[0]["details"]))

    def test_enrich_keeps_existing_snapshot(self):
        events = [
            {
                "changed_at": "now",
                "match_id": "bonus-world_champion",
                "from_tip": "A (10%)",
                "to_tip": "B (12%)",
                "trigger": "Bonus-Recalc",
                "category": "world_champion",
                "snapshot": {
                    "kind": "bonus_ranking",
                    "category": "world_champion",
                    "from_top": [{"team": "A", "probability": 0.10}],
                    "to_top": [{"team": "B", "probability": 0.12}],
                },
            }
        ]
        enriched = enrich_history_events(events, [], {"world_champion": []})
        # snapshot bleibt unveraendert -- to_top war schon da
        self.assertEqual(enriched[0]["snapshot"]["from_top"][0]["team"], "A")
        self.assertEqual(enriched[0]["snapshot"]["to_top"][0]["team"], "B")


if __name__ == "__main__":
    unittest.main()
