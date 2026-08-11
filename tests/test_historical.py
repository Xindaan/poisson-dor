from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.historical import (
    assign_pretournament_elo,
    parse_openfootball_finals,
    parse_openfootball_results,
    preserve_existing_enrichment,
)


SAMPLE_FINALS = """\
= World Cup Finals

▪ Round of 16            |  Sat Jun 30 - Tue Jul 3
▪ Final                  |  Sun Jul 15


▪ Round of 16
Sat Jun 30
 17:00 UTC+3   France   4-3 (1-1)   Argentina   @ Kazan Arena, Kazan
Sun Jul 1
 17:00 UTC+3   Spain    1-1 a.e.t. (1-1, 1-1), 3-4 pen.   Russia   @ Luzhniki, Moscow

▪ Match for third place
Sat Jul 14
 17:00 UTC+3   Belgium  2-0 (1-0)   England   @ Saint Petersburg, SPB

▪ Final
Sun Jul 15
 18:00 UTC+3   France   4-2 (2-1)   Croatia   @ Luzhniki, Moscow
"""


SAMPLE_2022 = """\
▪ Group A
Sun Nov 20
  19:00      Qatar   0-2 (0-2)   Ecuador    @ Al Bayt Stadium, Al Khor

Mon Nov 21
   19:00     Senegal  0-2 (0-0)  Netherlands  @ Al Thumama Stadium, Doha


▪ Group H
Thu Nov 24
   16:00     Uruguay   0-0   South Korea   @ Education City Stadium, Al Rayyan
"""


SAMPLE_2018 = """\
▪ Group A
Thu Jun 14
 18:00 UTC+3     Russia       5-0 (2-0)  Saudi Arabia     @ Luzhniki Stadium, Moscow
"""


# 2014: "Home v Away  S-S (HT)  @ Venue" (Score hinter den Teams),
# inklusive Akzent im Teamnamen (Côte d'Ivoire) und im Venue (São Paulo).
SAMPLE_2014 = """\
▪ Group A
  17:00 UTC-3  Brazil v Croatia   3-1 (1-1)       @ Arena de São Paulo, São Paulo
▪ Group C
  13:00 UTC-3  Côte d'Ivoire v Japan  2-1 (0-1)   @ Arena Pernambuco, Recife
"""


# 2010: Inline-Datum am Zeilenanfang ("Wkd Mon DD HH:MM ..."), Score
# zwischen den Teams, kein UTC-Suffix.
SAMPLE_2010 = """\
▪ Group A
Fri Jun 11 16:00    South Africa  1-1  Mexico      @ Soccer City, Johannesburg
Fri Jun 11 20:30    Uruguay       0-0  France      @ Cape Town Stadium, Cape Town
"""


# 2010-Finals: Sektionsnamen ohne Bindestrich ("Quarterfinals"/"Semifinals").
SAMPLE_FINALS_2010 = """\
▪ Quarterfinals
Fri Jul 2 16:00   Netherlands    2-1               Brazil        @ Nelson Mandela Bay Stadium, Port Elizabeth
Fri Jul 2 20:30   Uruguay       1-1 a.e.t. (1-1), 4-2 pen.   Ghana         @ Soccer City, Johannesburg
▪ Semifinals
Tue Jul 6 20:30   Uruguay        2-3  Netherlands          @ Cape Town Stadium, Cape Town
▪ Third-place play-off
Sat Jul 10 20:30  Uruguay  2-3  Germany         @ Nelson Mandela Bay Stadium, Port Elizabeth
"""


# EM-Format (openfootball/euro): EINE Datei mit Vorrunde + KO, sekundaere
# Klammer-Zeit (Baku), EM-Penalty-Reihenfolge ("pen" vor "a.e.t"),
# "Semi-final" im Singular.
SAMPLE_EURO = """\
▪ Matchday 1 | Jun 10 - Jun 14

▪ Group A
June 11
  21:00    Turkey   0-3 (0-0)   Italy         @ Rome
June 12
  15:00 (17:00 UTC+4)    Wales    1-1 (0-0)   Switzerland   @ Baku

▪ Round of 16
June 28
  18:00          Croatia  3-5 a.e.t. (3-3, 1-1)  Spain   @ Copenhagen
  21:00 (22:00 UTC+3)   France    4-5 pen. 3-3 a.e.t. (3-3, 0-1)   Switzerland   @ Bucharest

▪ Semi-final
July 6
  21:00   Italy   1-1 a.e.t. (1-1), 4-2 pen.   Spain   @ London

▪ Final
July 11
  21:00   England   1-1 a.e.t. (1-1), 2-3 pen.   Italy   @ London
"""


class EuroFormatTests(unittest.TestCase):
    def test_group_parser_stops_at_knockout_and_handles_secondary_time(self):
        rows = parse_openfootball_results(SAMPLE_EURO)
        # Nur die 2 Gruppenspiele -- KO darf NICHT in die Gruppenliste bluten.
        self.assertEqual(len(rows), 2)
        matches = {r["match"]: r for r in rows}
        self.assertIn("Turkey - Italy", matches)
        # Sekundaere Klammer-Zeit "15:00 (17:00 UTC+4)" darf den Teamnamen
        # nicht zerstoeren.
        wales = matches["Wales - Switzerland"]
        self.assertEqual(wales["home"], "Wales")
        self.assertEqual(wales["actual"], [1, 1])

    def test_em_penalty_order_and_aet_scoreline(self):
        rows = {r["match"]: r for r in parse_openfootball_finals(SAMPLE_EURO)}
        # Normales a.e.t ohne Elfer: erste Zahl = ET-Scoreline.
        self.assertEqual(rows["Croatia - Spain"]["actual"], [3, 5])
        self.assertNotIn("penalty_winner", rows["Croatia - Spain"])
        # EM-Reihenfolge "4-5 pen. 3-3 a.e.t.": Scoreline = 3-3 (nach ET),
        # Elfer-Sieger = away (5 > 4).
        france = rows["France - Switzerland"]
        self.assertEqual(france["actual"], [3, 3])
        self.assertEqual(france["penalty_winner"], "away")

    def test_semi_final_singular_and_wm_penalty_order(self):
        rows = {r["match"]: r for r in parse_openfootball_finals(SAMPLE_EURO)}
        # "Semi-final" (Singular) muss als KO erkannt werden.
        self.assertIn("Italy - Spain", rows)
        # WM-Reihenfolge "1-1 a.e.t. (1-1), 4-2 pen.": Scoreline 1-1, home gewinnt.
        self.assertEqual(rows["Italy - Spain"]["actual"], [1, 1])
        self.assertEqual(rows["Italy - Spain"]["penalty_winner"], "home")
        # Finale: away (Italy) gewinnt das Elfmeterschiessen 3-2.
        self.assertEqual(rows["England - Italy"]["penalty_winner"], "away")


class HistoricalParserTests(unittest.TestCase):
    def test_parses_2022_format_with_halftime(self):
        rows = parse_openfootball_results(SAMPLE_2022)
        self.assertEqual(len(rows), 3)
        first = rows[0]
        self.assertEqual(first["home"], "Qatar")
        self.assertEqual(first["away"], "Ecuador")
        self.assertEqual(first["actual"], [0, 2])
        self.assertEqual(first["group"], "A")
        self.assertEqual(first["stage"], "group")

    def test_parses_zero_zero_without_halftime_block(self):
        rows = parse_openfootball_results(SAMPLE_2022)
        nil = next(row for row in rows if row["match"] == "Uruguay - South Korea")
        self.assertEqual(nil["actual"], [0, 0])
        self.assertEqual(nil["group"], "H")

    def test_parses_2018_format_with_utc_offset(self):
        rows = parse_openfootball_results(SAMPLE_2018)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["home"], "Russia")
        self.assertEqual(row["away"], "Saudi Arabia")
        self.assertEqual(row["actual"], [5, 0])

    def test_parses_match_without_time_prefix_in_same_slot(self):
        text = """\
▪ Group H
Fri Dec 2
   18:00    Ghana  0-2   Uruguay   @ Al Janoub Stadium, Al Wakrah
            South Korea  2-1 (1-1)   Portugal  @ Lusail Iconic Stadium, Lusail
"""
        rows = parse_openfootball_results(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["home"], "South Korea")
        self.assertEqual(rows[1]["away"], "Portugal")
        self.assertEqual(rows[1]["actual"], [2, 1])
        self.assertEqual(rows[1]["group"], "H")

    def test_handles_multi_word_team_names(self):
        names_2022 = {
            row["home"] for row in parse_openfootball_results(SAMPLE_2022)
        } | {row["away"] for row in parse_openfootball_results(SAMPLE_2022)}
        self.assertIn("South Korea", names_2022)
        self.assertEqual(parse_openfootball_results(SAMPLE_2018)[0]["away"], "Saudi Arabia")

    def test_parses_v_format_with_accents_2014(self):
        rows = parse_openfootball_results(SAMPLE_2014)
        self.assertEqual(len(rows), 2)
        by_match = {row["match"]: row for row in rows}
        self.assertEqual(by_match["Brazil - Croatia"]["actual"], [3, 1])
        self.assertEqual(by_match["Brazil - Croatia"]["group"], "A")
        # Akzent im Teamnamen darf nicht abgeschnitten werden.
        ivory = by_match["Côte d'Ivoire - Japan"]
        self.assertEqual(ivory["home"], "Côte d'Ivoire")
        self.assertEqual(ivory["actual"], [2, 1])
        self.assertEqual(ivory["group"], "C")

    def test_parses_inline_weekday_format_2010(self):
        rows = parse_openfootball_results(SAMPLE_2010)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        # Inline-Datum "Fri Jun 11 16:00" darf nicht im Teamnamen landen.
        self.assertEqual(first["home"], "South Africa")
        self.assertEqual(first["away"], "Mexico")
        self.assertEqual(first["actual"], [1, 1])
        self.assertEqual(first["group"], "A")

    def test_preserves_existing_enrichment_when_dataset_is_rebuilt(self):
        rows = parse_openfootball_results(SAMPLE_2018)
        enriched = preserve_existing_enrichment(
            rows,
            {
                "results": [
                    {
                        "match": "Russia - Saudi Arabia",
                        "group": "A",
                        "pre_elo": {"home": 1678, "away": 1586},
                        "pre_odds": {"home": 1.45, "draw": 4.25, "away": 9.12},
                    }
                ]
            },
        )
        self.assertEqual(enriched[0]["pre_elo"]["home"], 1678)
        self.assertEqual(enriched[0]["pre_odds"]["away"], 9.12)


class FinalsParserTests(unittest.TestCase):
    def test_parses_ko_matches_excluding_third_place(self):
        rows = parse_openfootball_finals(SAMPLE_FINALS)
        matches = {r["match"] for r in rows}
        self.assertIn("France - Argentina", matches)
        self.assertIn("France - Croatia", matches)
        self.assertNotIn("Belgium - England", matches)  # Spiel um Platz 3 raus
        self.assertTrue(all(r["stage"] == "knockout" for r in rows))

    def test_normal_ko_result_and_penalty_winner(self):
        rows = {r["match"]: r for r in parse_openfootball_finals(SAMPLE_FINALS)}
        # Normales Ergebnis ohne Elfmeter.
        self.assertEqual(rows["France - Argentina"]["actual"], [4, 3])
        self.assertNotIn("penalty_winner", rows["France - Argentina"])
        # Elfmeter: ET 1-1, away (Russia) gewinnt 3-4.
        spain = rows["Spain - Russia"]
        self.assertEqual(spain["actual"], [1, 1])
        self.assertEqual(spain["penalty_winner"], "away")

    def test_section_names_without_hyphen_2010(self):
        # 2010 nutzt "Quarterfinals"/"Semifinals" ohne Bindestrich -- die
        # Normalisierung muss beide Sektionen als KO erkennen, das Spiel um
        # Platz 3 aber weiterhin ausschliessen.
        rows = {r["match"]: r for r in parse_openfootball_finals(SAMPLE_FINALS_2010)}
        self.assertIn("Netherlands - Brazil", rows)       # Quarterfinals
        self.assertIn("Uruguay - Netherlands", rows)      # Semifinals
        self.assertNotIn("Uruguay - Germany", rows)       # Platz 3 raus
        # Elfmeter-Sieger korrekt (Uruguay gewinnt 4-2 i.E. gegen Ghana).
        self.assertEqual(rows["Uruguay - Ghana"]["actual"], [1, 1])
        self.assertEqual(rows["Uruguay - Ghana"]["penalty_winner"], "home")

    def test_assign_pretournament_elo_reuses_group_elo(self):
        group = [
            {"home": "France", "away": "Peru", "pre_elo": {"home": 2000.0, "away": 1700.0}},
            {"home": "Argentina", "away": "Iceland", "pre_elo": {"home": 1985.0, "away": 1600.0}},
        ]
        ko = [{"home": "France", "away": "Argentina", "stage": "knockout"}]
        assign_pretournament_elo(ko, group)
        self.assertEqual(ko[0]["pre_elo"], {"home": 2000.0, "away": 1985.0})


if __name__ == "__main__":
    unittest.main()
