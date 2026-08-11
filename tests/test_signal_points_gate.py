"""T-0076: dPkt-Gate (Punkte-Metrik) des Signal-Circuit-Breakers.

Der Brier-Gate ist blind fuer den realisierten Punkte-Schaden; dieses Gate
punktet die Tipp-Flips der Kontext-Ablation gegen die echten Ergebnisse.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.live_calibration import signal_points_calibration
from wm_tipps.scoring import DEFAULT_ROUND_ID  # noqa: E402

ROUND = DEFAULT_ROUND_ID


def _ablation(n: int, with_tip: str, without_tip: str, effect: str = "news_effect") -> dict:
    return {
        "effects": [
            {
                "effect": effect,
                "changed_fixtures": [
                    {
                        "match_id": f"ga-{i:03d}",
                        "round_id": ROUND,
                        "with_effect_tip": with_tip,
                        "without_effect_tip": without_tip,
                    }
                    for i in range(n)
                ],
            }
        ]
    }


def _results(n: int, actual: list[int]) -> dict:
    return {f"ga-{i:03d}": {"actual": actual, "penalty_winner": None} for i in range(n)}


class SignalPointsGateTests(unittest.TestCase):
    def test_negative_dpkt_recommends_halve(self):
        # Real 1:0. Ohne Effekt 1:0 = exakt (4 Pkt), mit Effekt 2:1 = nur
        # Tordifferenz (3 Pkt) -> dPkt -1 je Flip.
        report = signal_points_calibration(
            _ablation(10, "2:1", "1:0"), _results(10, [1, 0]), {}, min_flips=10
        )
        signal = report["signals"][0]
        self.assertEqual(signal["signal"], "news")  # effect_key -> Signalname
        self.assertEqual(signal["flips_scored"], 10)
        self.assertEqual(signal["dpkt"], -10)
        self.assertEqual(signal["status"], "review")
        self.assertEqual(signal["recommendation"], "halve")
        self.assertEqual(signal["multiplier"], 1.0)  # kein Auto-Apply

    def test_positive_dpkt_keeps_signal(self):
        report = signal_points_calibration(
            _ablation(10, "1:0", "2:1"), _results(10, [1, 0]), {}, min_flips=10
        )
        signal = report["signals"][0]
        self.assertEqual(signal["dpkt"], 10)
        self.assertEqual(signal["recommendation"], "keep")

    def test_gated_below_min_flips(self):
        report = signal_points_calibration(
            _ablation(3, "2:1", "1:0"), _results(3, [1, 0]), {}, min_flips=10
        )
        signal = report["signals"][0]
        self.assertEqual(signal["status"], "insufficient_data")
        self.assertEqual(signal["recommendation"], "keep")

    def test_ungeplayed_flips_are_not_scored(self):
        # 10 Flips, aber nur 2 Spiele haben ein Ergebnis -> unter dem Gate.
        report = signal_points_calibration(
            _ablation(10, "2:1", "1:0"), _results(2, [1, 0]), {}, min_flips=10
        )
        signal = report["signals"][0]
        self.assertEqual(signal["flips_total"], 10)
        self.assertEqual(signal["flips_scored"], 2)
        self.assertEqual(signal["status"], "insufficient_data")

    def test_ko_stage_uses_round_scoring(self):
        # KO-Spiel: die Elfer-Runde wertet nach Elfmeter (Sieger +1). Real 1:1, Elfer
        # home -> Wertungs-Score 2:1; Tipp 2:1 exakt, 1:1 nur Remis-Tendenz.
        ablation = {
            "effects": [
                {
                    "effect": "news_effect",
                    "changed_fixtures": [
                        {
                            "match_id": "ko-090",
                            "round_id": ROUND,
                            "with_effect_tip": "2:1",
                            "without_effect_tip": "1:1",
                        }
                    ],
                }
            ]
        }
        results = {"ko-090": {"actual": [1, 1], "penalty_winner": "home"}}
        report = signal_points_calibration(
            ablation, results, {"ko-090": "round_of_16"}, min_flips=1
        )
        signal = report["signals"][0]
        self.assertEqual(signal["flips_scored"], 1)
        self.assertGreater(signal["dpkt"], 0)  # exakter Tipp schlaegt Fehl-Remis
        self.assertEqual(signal["dpkt_per_round"], {ROUND: signal["dpkt"]})


if __name__ == "__main__":
    unittest.main()
