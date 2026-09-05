from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.fixtures import _with_knockout_fixtures, fixture_key, parse_openfootball_cup

CUP = """Group A | Mexico        South Africa    South Korea    Czech Republic

▪ Group A
Thu June 11
  13:00 UTC-6     Mexico  2-0 (1-0)  South Africa        @ Mexico City
  20:00 UTC-6     South Korea  2-1 (0-0)  Czech Republic     @ Guadalajara (Zapopan)
Thu June 18
  12:00 UTC-4     Czech Republic    v South Africa   @ Atlanta
"""


def _played_group(group: str, teams: list[str]) -> list[dict]:
    """Vollstaendig gespielte Vierergruppe mit eindeutiger Rangfolge
    (teams[0] gewinnt alles, teams[3] verliert alles)."""
    scores = {
        (0, 1): [3, 1],
        (0, 2): [2, 0],
        (0, 3): [2, 0],
        (1, 2): [2, 1],
        (1, 3): [2, 0],
        (2, 3): [1, 0],
    }
    fixtures = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            fixtures.append(
                {
                    "stage": "group",
                    "group": group,
                    "home_team": teams[i],
                    "away_team": teams[j],
                    "status": "played",
                    "result": scores[(i, j)],
                }
            )
    return fixtures


class ParseOpenfootballTests(unittest.TestCase):
    def setUp(self):
        self.fx = parse_openfootball_cup(CUP)["fixtures"]

    def test_played_matches_captured_with_result(self):
        # T-0081: gespielte Spiele (Score statt 'v') werden erfasst, nicht gedroppt.
        self.assertEqual(len(self.fx), 3)
        self.assertEqual(self.fx[0]["status"], "played")
        self.assertEqual(self.fx[0]["result"], [2, 0])
        self.assertEqual(self.fx[0]["home_team"], "Mexico")
        self.assertEqual(self.fx[0]["away_team"], "South Africa")
        self.assertEqual(self.fx[1]["status"], "played")
        self.assertEqual(self.fx[1]["result"], [2, 1])

    def test_scheduled_match_has_no_result(self):
        self.assertEqual(self.fx[2]["status"], "scheduled")
        self.assertIsNone(self.fx[2].get("result"))
        self.assertEqual(self.fx[2]["home_team"], "Czech Republic")

    def test_numbering_counts_played_matches_stable(self):
        # Gespielte zaehlen mit -> match_ids verrutschen nicht mehr.
        self.assertEqual([f["match_id"] for f in self.fx], ["ga-001", "ga-002", "ga-003"])

    def test_stable_team_key(self):
        self.assertEqual(self.fx[0]["key"], fixture_key("A", "Mexico", "South Africa"))
        self.assertEqual(self.fx[0]["key"], "ga-mexico-v-south-africa")
        # Key haengt nur an Teams (positions-/status-unabhaengig).
        self.assertEqual(fixture_key("A", "Mexico", "South Africa"),
                         fixture_key("a", "mexico", "south africa"))

    def test_knockout_merge_preserves_existing_result_without_duplicates(self):
        def played_group(group, teams):
            fixtures = []
            scores = {
                (0, 1): [3, 1],
                (0, 2): [2, 0],
                (0, 3): [2, 0],
                (1, 2): [2, 1],
                (1, 3): [2, 0],
                (2, 3): [1, 0],
            }
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    fixtures.append(
                        {
                            "stage": "group",
                            "group": group,
                            "home_team": teams[i],
                            "away_team": teams[j],
                            "status": "played",
                            "result": scores[(i, j)],
                        }
                    )
            return fixtures

        groups = played_group("A", ["A1", "A2", "A3", "A4"])
        groups.extend(played_group("B", ["B1", "B2", "B3", "B4"]))
        existing_ko = {
            "match_id": "ko-073",
            "match_number": 73,
            "stage": "round_of_32",
            "home_team": "A2",
            "away_team": "B2",
            "status": "played",
            "result": [1, 1],
            "penalty_winner": "away",
        }
        payload = _with_knockout_fixtures(
            {"groups": {}, "fixtures": [*groups, existing_ko]},
            {"fixtures": [existing_ko]},
            manual_results={},
        )
        ko_073 = [fixture for fixture in payload["fixtures"] if fixture.get("match_id") == "ko-073"]
        self.assertEqual(len(ko_073), 1)
        self.assertEqual(ko_073[0]["status"], "played")
        self.assertEqual(ko_073[0]["result"], [1, 1])
        self.assertEqual(ko_073[0]["penalty_winner"], "away")

    def test_result_does_not_follow_a_changed_pairing(self):
        """T-0189: Ergebnisse haengen an der Paarung, nicht an der Spielnummer.

        Aufbau: ko-073 ist mit einer Paarung als gespielt erfasst; danach
        korrigiert ein manuelles Gruppenergebnis die Tabelle so, dass Spiel 73
        eine ANDERE Paarung bekommt. Das alte Ergebnis darf nicht mitwandern --
        sonst laeuft der Baum mit einem Sieger weiter, der nie gespielt hat.
        """
        groups = _played_group("A", ["A1", "A2", "A3", "A4"])
        groups.extend(_played_group("B", ["B1", "B2", "B3", "B4"]))
        # Erfasstes Ergebnis fuer eine Paarung, die es nach der Korrektur nicht gibt.
        stale_ko = {
            "match_id": "ko-073",
            "match_number": 73,
            "stage": "round_of_32",
            "home_team": "A4",
            "away_team": "B4",
            "status": "played",
            "result": [3, 0],
            "penalty_winner": None,
        }
        payload = _with_knockout_fixtures(
            {"groups": {}, "fixtures": [*groups, stale_ko]},
            {"fixtures": [stale_ko]},
            manual_results={},
        )
        ko_073 = next(f for f in payload["fixtures"] if f.get("match_id") == "ko-073")
        self.assertNotEqual(
            (ko_073["home_team"], ko_073["away_team"]), ("A4", "B4"),
            "Testaufbau kaputt: die Paarung muesste sich geaendert haben.",
        )
        self.assertNotEqual(ko_073.get("result"), [3, 0])
        self.assertNotEqual(ko_073.get("status"), "played")
        self.assertEqual(ko_073["replaced_pairing"]["previous_match"], "A4 - B4")

    def test_manual_result_corrects_a_group_match(self):
        """T-0190: manual_results ist der Korrektur-Override -- er muss auch
        auf Gruppenspiele wirken, denn Gruppentabellen entscheiden die
        K.o.-Slots. Vorher galt er nur fuer K.o.-Zeilen."""
        groups = _played_group("A", ["A1", "A2", "A3", "A4"])
        groups.extend(_played_group("B", ["B1", "B2", "B3", "B4"]))
        for index, fixture in enumerate(groups, start=1):
            fixture["match_id"] = f"g{fixture['group'].lower()}-{index:03d}"
        ziel = groups[0]["match_id"]
        payload = _with_knockout_fixtures(
            {"groups": {}, "fixtures": list(groups)},
            {"fixtures": []},
            manual_results={ziel: {"actual": [0, 4], "penalty_winner": None}},
        )
        korrigiert = next(f for f in payload["fixtures"] if f.get("match_id") == ziel)
        self.assertEqual(korrigiert["result"], [0, 4])

    def test_manual_knockout_results_unlock_follow_up_fixture(self):
        def played_group(group, teams):
            fixtures = []
            scores = {
                (0, 1): [3, 1],
                (0, 2): [2, 0],
                (0, 3): [2, 0],
                (1, 2): [2, 1],
                (1, 3): [2, 0],
                (2, 3): [1, 0],
            }
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    fixtures.append(
                        {
                            "stage": "group",
                            "group": group,
                            "home_team": teams[i],
                            "away_team": teams[j],
                            "status": "played",
                            "result": scores[(i, j)],
                        }
                    )
            return fixtures

        groups = []
        for group in ("A", "B", "C", "F"):
            groups.extend(played_group(group, [f"{group}{i}" for i in range(1, 5)]))
        existing_ko = [
            {"match_id": "ko-073", "match_number": 73, "stage": "round_of_32", "status": "scheduled"},
            {"match_id": "ko-075", "match_number": 75, "stage": "round_of_32", "status": "scheduled"},
        ]

        payload = _with_knockout_fixtures(
            {"groups": {}, "fixtures": groups},
            {"fixtures": existing_ko},
            manual_results={
                "ko-073": {"actual": [1, 0], "penalty_winner": None},
                "ko-075": {"actual": [0, 2], "penalty_winner": "away"},
            },
        )

        by_number = {
            fixture["match_number"]: fixture
            for fixture in payload["fixtures"]
            if fixture.get("match_number") is not None
        }
        self.assertEqual(by_number[73]["status"], "played")
        self.assertEqual(by_number[73]["result"], [1, 0])
        self.assertEqual(by_number[75]["status"], "played")
        self.assertEqual(by_number[75]["result"], [0, 2])
        self.assertEqual(by_number[75]["penalty_winner"], "away")
        self.assertEqual(by_number[90]["stage"], "round_of_16")
        self.assertEqual(by_number[90]["home_slot"], "W73")
        self.assertEqual(by_number[90]["away_slot"], "W75")

    def test_manual_knockout_results_chain_to_quarter_in_one_refresh(self):
        def played_group(group, teams, *, best_third=False):
            if best_third:
                scores = {
                    (0, 1): [2, 0],
                    (0, 2): [3, 0],
                    (0, 3): [2, 0],
                    (1, 2): [1, 1],
                    (1, 3): [4, 0],
                    (2, 3): [1, 0],
                }
            else:
                scores = {
                    (0, 1): [3, 1],
                    (0, 2): [2, 0],
                    (0, 3): [2, 0],
                    (1, 2): [2, 1],
                    (1, 3): [2, 0],
                    (2, 3): [1, 0],
                }
            fixtures = []
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    fixtures.append(
                        {
                            "stage": "group",
                            "group": group,
                            "home_team": teams[i],
                            "away_team": teams[j],
                            "status": "played",
                            "result": scores[(i, j)],
                        }
                    )
            return fixtures

        groups = []
        for group in "ABCDEFGHIJKL":
            groups.extend(
                played_group(
                    group,
                    [f"{group}{i}" for i in range(1, 5)],
                    best_third=group in "ABCDEFGH",
                )
            )

        payload = _with_knockout_fixtures(
            {"groups": {}, "fixtures": groups},
            {"fixtures": []},
            manual_results={
                "ko-073": {"actual": [1, 0], "penalty_winner": None},
                "ko-074": {"actual": [1, 0], "penalty_winner": None},
                "ko-075": {"actual": [0, 2], "penalty_winner": "away"},
                "ko-077": {"actual": [0, 1], "penalty_winner": None},
                "ko-089": {"actual": [2, 0], "penalty_winner": None},
                "ko-090": {"actual": [1, 1], "penalty_winner": "home"},
            },
        )

        by_number = {
            fixture["match_number"]: fixture
            for fixture in payload["fixtures"]
            if fixture.get("match_number") is not None
        }
        self.assertEqual(by_number[89]["status"], "played")
        self.assertEqual(by_number[90]["status"], "played")
        self.assertEqual(by_number[97]["stage"], "quarter")
        self.assertEqual(by_number[97]["home_slot"], "W89")
        self.assertEqual(by_number[97]["away_slot"], "W90")


if __name__ == "__main__":
    unittest.main()
