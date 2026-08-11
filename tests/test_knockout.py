from __future__ import annotations

import sys
import unittest
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import random

from wm_tipps.knockout import (
    KNOCKOUT_MATCH_SCHEDULE,
    KNOCKOUT_STAGE_BY_MATCH,
    group_standings_from_results,
    knockout_results_freshness,
    knockout_round_sizes,
    load_2026_bracket,
    qualified_from_standings,
    resolve_knockout_fixtures,
    round_of_32_matchups,
    simulate_bracket,
    simulate_group_stage,
    simulate_tournament,
)


def _strengths(values: dict[str, int]) -> dict[str, dict[str, int]]:
    return {team: {"elo": elo} for team, elo in values.items()}


class KnockoutSimulationTests(unittest.TestCase):
    def test_champion_probabilities_sum_to_one(self):
        teams = [f"T{i}" for i in range(8)]
        strengths = _strengths({team: 1500 + idx * 20 for idx, team in enumerate(teams)})
        result = simulate_bracket(teams, strengths, n_simulations=2000)
        champion_total = sum(result["champion"].values())
        self.assertAlmostEqual(champion_total, 1.0, places=6)

    def test_round_probabilities_are_monotonic_per_team(self):
        teams = [f"T{i}" for i in range(8)]
        strengths = _strengths({team: 1500 + idx * 30 for idx, team in enumerate(teams)})
        result = simulate_bracket(teams, strengths, n_simulations=2000)
        order = ["round_of_8", "quarter", "semi", "final", "champion"]
        rounds_present = [label for label in order if label in result]
        for team in teams:
            previous = 1.0
            for label in rounds_present:
                value = result[label][team]
                self.assertLessEqual(
                    value,
                    previous + 1e-9,
                    f"{team} in {label} hat Wahrscheinlichkeit > vorige Runde",
                )
                previous = value

    def test_strong_team_dominates_champion_probability(self):
        teams = ["Strong", "Mid1", "Mid2", "Weak"]
        strengths = _strengths({"Strong": 1900, "Mid1": 1550, "Mid2": 1500, "Weak": 1450})
        result = simulate_bracket(teams, strengths, n_simulations=3000)
        champion = result["champion"]
        self.assertGreater(champion["Strong"], champion["Mid1"])
        self.assertGreater(champion["Strong"], champion["Mid2"])
        self.assertGreater(champion["Strong"], champion["Weak"])

    def test_seed_makes_simulation_reproducible(self):
        teams = ["A", "B", "C", "D"]
        strengths = _strengths({"A": 1700, "B": 1650, "C": 1600, "D": 1550})
        first = simulate_bracket(teams, strengths, n_simulations=500, seed=123)
        second = simulate_bracket(teams, strengths, n_simulations=500, seed=123)
        self.assertEqual(first, second)

    def test_rejects_non_power_of_two(self):
        with self.assertRaises(ValueError):
            simulate_bracket(["A", "B", "C"], _strengths({"A": 1500, "B": 1500, "C": 1500}))


class GroupStageTests(unittest.TestCase):
    def _fixtures(self, group, teams):
        # 6 Spiele pro 4-Team-Gruppe: jedes Team gegen jedes andere.
        fixtures = []
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                fixtures.append(
                    {
                        "stage": "group",
                        "group": group,
                        "home_team": teams[i],
                        "away_team": teams[j],
                    }
                )
        return fixtures

    def _played_group(self, group, teams, *, best_third=False):
        # Deterministische Tabelle: team1 9p, team2 6p, team3 3p, team4 0p.
        scores = {
            (0, 1): (3, 1),
            (0, 2): (3, 0),
            (0, 3): (3, 0),
            (1, 2): (2, 0),
            (1, 3): (2, 0),
            (2, 3): (3, 0) if best_third else (1, 0),
        }
        fixtures = []
        match_number = (ord(group) - ord("A")) * 6
        for i in range(len(teams)):
            for j in range(i + 1, len(teams)):
                match_number += 1
                fixtures.append(
                    {
                        "match_id": f"g{group.lower()}-{match_number:03d}",
                        "match_number": match_number,
                        "stage": "group",
                        "group": group,
                        "home_team": teams[i],
                        "away_team": teams[j],
                        "status": "played",
                        "result": list(scores[(i, j)]),
                    }
                )
        return fixtures

    def _standings_with_best_thirds(self, best_third_groups):
        standings = {}
        for letter in "ABCDEFGHIJKL":
            third_points = 4 if letter in best_third_groups else 1
            standings[letter] = [
                {"team": f"{letter}1", "points": 9, "gf": 7, "ga": 1, "group": letter},
                {"team": f"{letter}2", "points": 6, "gf": 5, "ga": 3, "group": letter},
                {"team": f"{letter}3", "points": third_points, "gf": 2, "ga": 4, "group": letter},
                {"team": f"{letter}4", "points": 0, "gf": 1, "ga": 7, "group": letter},
            ]
        return standings

    def test_simulate_group_stage_returns_4_teams_ranked(self):
        teams = ["A1", "A2", "A3", "A4"]
        strengths = _strengths({"A1": 1900, "A2": 1700, "A3": 1500, "A4": 1300})
        fixtures = self._fixtures("A", teams)
        rng = random.Random(7)
        standings = simulate_group_stage({"A": fixtures}, strengths, rng)
        self.assertEqual(len(standings["A"]), 4)
        self.assertEqual({r["team"] for r in standings["A"]}, set(teams))
        # Strongest soll im Schnitt vorne sein -- ueber 6 Spiele pro Team
        # nicht garantiert deterministisch, aber bei rng=7 ist A1 vorne:
        self.assertEqual(standings["A"][0]["team"], "A1")

    def test_qualified_from_standings_picks_top2_plus_best_thirds(self):
        # 12 Gruppen mit je 4 Teams; konstante Standings konstruieren
        standings = {}
        for letter in "ABCDEFGHIJKL":
            standings[letter] = [
                {"team": f"{letter}1", "points": 9, "gf": 7, "ga": 1, "group": letter},
                {"team": f"{letter}2", "points": 6, "gf": 5, "ga": 3, "group": letter},
                {"team": f"{letter}3", "points": 3, "gf": 2, "ga": 4, "group": letter},
                {"team": f"{letter}4", "points": 0, "gf": 1, "ga": 7, "group": letter},
            ]
        qualified = qualified_from_standings(standings)
        self.assertEqual(len(qualified), 32)  # 12 Erste + 12 Zweite + 8 Dritte
        # alle Top-1 dabei
        for letter in "ABCDEFGHIJKL":
            self.assertIn(f"{letter}1", qualified)
        # genau 8 Drittplatzierte dabei
        thirds_in = [t for t in qualified if t.endswith("3")]
        self.assertEqual(len(thirds_in), 8)

    def test_2026_bracket_contains_all_best_third_combinations(self):
        bracket = load_2026_bracket()
        self.assertEqual(
            [match["match_number"] for match in bracket["round_of_32"]],
            list(range(73, 89)),
        )
        self.assertIn(103, KNOCKOUT_MATCH_SCHEDULE)
        self.assertEqual(KNOCKOUT_STAGE_BY_MATCH[103], "third_place")
        self.assertEqual(
            [
                (round_def["name"], [match["match_number"] for match in round_def["matches"]])
                for round_def in bracket["rounds"]
            ],
            [
                ("round_of_16", list(range(89, 97))),
                ("quarter", list(range(97, 101))),
                ("semi", [101, 102]),
                ("final", [104]),
            ],
        )
        assignment = bracket["third_place_assignment"]
        combination_rows = assignment["combinations"]
        self.assertEqual(len(combination_rows), 495)
        self.assertEqual(assignment["columns"], ["1A", "1B", "1D", "1E", "1G", "1I", "1K", "1L"])
        seen = set()
        for row in combination_rows:
            qualified_groups = row["qualified_groups"]
            seen.add(qualified_groups)
            self.assertEqual(set(row["slots"]), set(assignment["columns"]))
            self.assertEqual({slot[1:] for slot in row["slots"].values()}, set(qualified_groups))
        self.assertEqual(len(seen), 495)
        self.assertEqual(seen, {"".join(groups) for groups in combinations("ABCDEFGHIJKL", 8)})

    def test_all_annex_c_rows_resolve_without_same_group_round_of_32(self):
        bracket = load_2026_bracket()
        rows = bracket["third_place_assignment"]["combinations"]
        for row in rows:
            standings = self._standings_with_best_thirds(row["qualified_groups"])
            matches = round_of_32_matchups(standings, bracket)
            self.assertEqual(len(matches), 16)
            self.assertEqual(matches[0]["qualified_third_groups"], row["qualified_groups"])
            self.assertTrue(all(match["home_slot"][1:] != match["away_slot"][1:] for match in matches))

    def test_round_of_32_matchups_use_fifa_annex_c_slots(self):
        standings = self._standings_with_best_thirds("EFGHIJKL")
        by_match = {match["match_number"]: match for match in round_of_32_matchups(standings)}
        self.assertEqual((by_match[73]["home"], by_match[73]["away"]), ("A2", "B2"))
        self.assertEqual((by_match[74]["home"], by_match[74]["away"]), ("E1", "F3"))
        self.assertEqual((by_match[77]["home"], by_match[77]["away"]), ("I1", "G3"))
        self.assertEqual((by_match[79]["home"], by_match[79]["away"]), ("A1", "E3"))
        self.assertEqual((by_match[80]["home"], by_match[80]["away"]), ("L1", "K3"))
        self.assertEqual((by_match[81]["home"], by_match[81]["away"]), ("D1", "I3"))
        self.assertEqual((by_match[82]["home"], by_match[82]["away"]), ("G1", "H3"))
        self.assertEqual((by_match[85]["home"], by_match[85]["away"]), ("B1", "J3"))
        self.assertEqual((by_match[87]["home"], by_match[87]["away"]), ("K1", "L3"))
        self.assertTrue(all(match["home_slot"][1:] != match["away_slot"][1:] for match in by_match.values()))

    def test_simulate_tournament_returns_all_rounds(self):
        # 12 Gruppen × 4 Teams = 48
        teams = [f"{letter}{i}" for letter in "ABCDEFGHIJKL" for i in range(1, 5)]
        strengths = _strengths({t: 1500 + (i * 50) for i, t in enumerate(teams)})
        fixtures = []
        for letter in "ABCDEFGHIJKL":
            group_teams = [f"{letter}{i}" for i in range(1, 5)]
            fixtures.extend(self._fixtures(letter, group_teams))
        payload = {"fixtures": fixtures}
        result = simulate_tournament(payload, strengths, n_simulations=200, seed=42)
        for round_name in ("round_of_32", "round_of_16", "quarter", "semi", "final", "champion"):
            self.assertIn(round_name, result)
        self.assertIn("group_winners", result)
        self.assertEqual(set(result["group_winners"]), set("ABCDEFGHIJKL"))
        for group_probs in result["group_winners"].values():
            self.assertAlmostEqual(sum(group_probs.values()), 1.0, places=4)
        self.assertAlmostEqual(sum(result["champion"].values()), 1.0, places=4)

    def test_result_standings_rank_completed_groups(self):
        fixtures = self._played_group("A", ["A1", "A2", "A3", "A4"])
        payload = group_standings_from_results(fixtures)
        self.assertEqual(payload["complete_groups"], ["A"])
        self.assertEqual([row["team"] for row in payload["standings"]["A"]], ["A1", "A2", "A3", "A4"])
        self.assertEqual(payload["open_groups"], [])
        self.assertEqual(payload["unresolved_tiebreaks"], [])

    def test_resolves_only_safe_round_of_32_slots_before_all_groups_done(self):
        fixtures = []
        for group in "ABCDEFGHI":
            fixtures.extend(self._played_group(group, [f"{group}{i}" for i in range(1, 5)]))
        for group in "JKL":
            group_teams = [f"{group}{i}" for i in range(1, 5)]
            fixtures.extend(self._played_group(group, group_teams)[:4])

        resolved = resolve_knockout_fixtures(fixtures, manual_slots={})
        match_numbers = [fixture["match_number"] for fixture in resolved["fixtures"]]

        self.assertEqual(match_numbers, list(range(73, 89)))
        self.assertIn(73, match_numbers)  # 2A - 2B ist sicher.
        self.assertIn(88, match_numbers)  # 2D - 2G ist sicher.
        by_number = {fixture["match_number"]: fixture for fixture in resolved["fixtures"]}
        self.assertFalse(by_number[73]["has_pending_slot"])
        self.assertTrue(by_number[79]["has_pending_slot"])  # Drittplatzierten-Zuordnung offen.
        self.assertTrue(by_number[83]["has_pending_slot"])  # Gruppen K/L noch offen.
        pending_by_number = {row["match_number"]: row["reason"] for row in resolved["status"]["pending"]}
        self.assertEqual(pending_by_number[79], "third_assignment_pending")
        self.assertEqual(pending_by_number[83], "slot_pending")
        self.assertEqual([row["match_number"] for row in resolved["status"]["resolved"]], [73, 75, 76, 78, 88])
        self.assertEqual(len(resolved["status"]["listed"]), 16)

    def test_manual_slot_override_unlocks_confirmed_open_group_winner(self):
        fixtures = []
        fixtures.extend(self._played_group("H", ["H1", "H2", "H3", "H4"]))
        fixtures.extend(self._played_group("J", ["J1", "J2", "J3", "J4"])[:4])

        resolved = resolve_knockout_fixtures(
            fixtures,
            existing_knockout_fixtures=[
                {
                    "match_id": "ko-086",
                    "match_number": 86,
                    "status": "slot_pending",
                    "has_pending_slot": True,
                    "pending_slots": ["1J"],
                }
            ],
            manual_slots={
                "slots": {
                    "1J": {
                        "team": "Argentina",
                        "source": "manual",
                        "reason": "confirmed with one match left",
                    }
                }
            },
        )

        by_number = {fixture["match_number"]: fixture for fixture in resolved["fixtures"]}
        self.assertEqual(by_number[86]["home_team"], "Argentina")
        self.assertEqual(by_number[86]["away_team"], "H2")
        self.assertEqual(by_number[86]["status"], "scheduled")
        self.assertFalse(by_number[86]["has_pending_slot"])
        self.assertIn(86, [row["match_number"] for row in resolved["status"]["resolved"]])
        self.assertEqual(
            resolved["status"]["manual_slots"],
            [
                {
                    "slot": "1J",
                    "team": "Argentina",
                    "source": "manual",
                    "reason": "confirmed with one match left",
                }
            ],
        )

    def test_resolves_all_round_of_32_when_groups_are_complete(self):
        fixtures = []
        for group in "ABCDEFGHIJKL":
            fixtures.extend(
                self._played_group(
                    group,
                    [f"{group}{i}" for i in range(1, 5)],
                    best_third=group in "ABCDEFGH",
                )
            )
        resolved = resolve_knockout_fixtures(fixtures, manual_slots={})
        r32 = [fixture for fixture in resolved["fixtures"] if fixture["stage"] == "round_of_32"]
        self.assertEqual(len(r32), 16)
        self.assertEqual([fixture["match_number"] for fixture in r32], list(range(73, 89)))
        self.assertTrue(all(fixture["match_id"].startswith("ko-") for fixture in r32))
        self.assertEqual(resolved["status"]["qualified_third_groups"], "ABCDEFGH")


class KnockoutResultsFreshnessTests(unittest.TestCase):
    """T-0137: stille Bracket-Verluste erkennen."""

    def _fixture(self, match_id, stage="round_of_16", **overrides):
        fixture = {
            "match_id": match_id,
            "stage": stage,
            "home_team": "Switzerland",
            "away_team": "Colombia",
            "status": "scheduled",
            "result": None,
            "penalty_winner": None,
        }
        fixture.update(overrides)
        return fixture

    def test_round_sizes_match_bracket(self):
        self.assertEqual(
            knockout_round_sizes(),
            {"round_of_32": 16, "round_of_16": 8, "quarter": 4, "semi": 2, "third_place": 1, "final": 1},
        )

    def test_manual_result_not_in_fixtures_is_failed(self):
        # Genau der 8.7.-Fall: ko-096 in manual_results, Fixture noch scheduled.
        report = knockout_results_freshness(
            [self._fixture("ko-096")],
            {"ko-096": {"actual": [0, 0], "penalty_winner": "home"}},
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["stale_results"]), 1)
        self.assertEqual(report["stale_results"][0]["match_id"], "ko-096")
        self.assertEqual(report["stale_results"][0]["reason"], "not_played")

    def test_zero_zero_result_is_not_treated_as_missing(self):
        # [0, 0] ist truthy -- darf nicht als "kein Ergebnis" durchrutschen.
        report = knockout_results_freshness(
            [self._fixture("ko-096", status="played", result=[0, 0], penalty_winner="home")],
            {"ko-096": {"actual": [0, 0], "penalty_winner": "home"}},
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["stale_results"], [])
        self.assertEqual(report["unresolved_ties"], [])

    def test_played_tie_without_penalty_winner_is_failed(self):
        report = knockout_results_freshness(
            [self._fixture("ko-096", status="played", result=[1, 1])],
            {},
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["unresolved_ties"]), 1)
        self.assertEqual(report["unresolved_ties"][0]["match_id"], "ko-096")

    def test_partial_round_alone_is_not_a_failure(self):
        # 3 von 4 Viertelfinals, aber keine stale/unaufgeloeste Quelle:
        # das Feeder-Spiel ist schlicht noch nicht angepfiffen -> kein Fehler.
        fixtures = [self._fixture(f"ko-{n:03d}", stage="quarter") for n in (97, 98, 99)]
        report = knockout_results_freshness(fixtures, {})
        self.assertEqual(report["status"], "ok")
        quarter = next(row for row in report["stages"] if row["stage"] == "quarter")
        self.assertEqual((quarter["present"], quarter["expected"]), (3, 4))
        self.assertTrue(quarter["partial"])

    def test_group_results_are_ignored(self):
        report = knockout_results_freshness([], {"ga-001": {"actual": [2, 0]}})
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["stale_results"], [])


if __name__ == "__main__":
    unittest.main()
