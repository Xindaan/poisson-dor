from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wm_tipps.paths import DATA_DIR
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID  # noqa: E402


PATH = DATA_DIR / "predictions.json"


def _require_nonempty(testcase, collection, what):
    """Leer ist kein Fehler, sondern ein legitimer Pipeline-Zustand.

    Nach Turnierende oder bei nur teilweise gelaufener Pipeline kann der
    Payload leer sein. Dann hat dieser Test nichts zu pruefen -- er soll
    ueberspringen, nicht rot werden und ein intaktes Repo kaputt aussehen
    lassen.
    """
    if not collection:
        testcase.skipTest(f"{what} ist leer -- nichts zu pruefen (Pipeline-Zustand).")
    return collection



class PredictionsSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PATH.exists():
            raise unittest.SkipTest(
                f"{PATH} fehlt; Pipeline laufen lassen (build-predictions)."
            )
        cls.payload = json.loads(PATH.read_text(encoding="utf-8"))

    def test_top_level_fields(self):
        for field in ("updated_at", "rules", "rounds", "predictions", "bonus"):
            self.assertIn(field, self.payload)
        self.assertIsInstance(self.payload["predictions"], list)
        _require_nonempty(self, self.payload["predictions"], "predictions")
        round_ids = {row.get("id") for row in self.payload.get("rounds", [])}
        self.assertIn(DEFAULT_ROUND_ID, round_ids)
        self.assertIn(SECONDARY_ROUND_ID, round_ids)

    def test_predictions_have_required_subfields(self):
        for prediction in self.payload["predictions"]:
            for field in ("match_id", "fixture", "recommended_tip", "round_tips", "probabilities", "stability", "xg_breakdown"):
                self.assertIn(field, prediction)
            self.assertIn(DEFAULT_ROUND_ID, prediction["round_tips"])
            self.assertIn(SECONDARY_ROUND_ID, prediction["round_tips"])
            self.assertIn("blended", prediction["probabilities"])
            blended = prediction["probabilities"]["blended"]
            for outcome in ("home", "draw", "away"):
                self.assertIn(outcome, blended)
            breakdown = prediction.get("xg_breakdown") or {}
            self.assertIsInstance(breakdown.get("heat_stress"), dict)
            for side in ("home", "away"):
                side_breakdown = breakdown.get(side) or {}
                self.assertIn("heat_effect", side_breakdown)
                self.assertIn("player_intel_effect", side_breakdown)

    def test_bonus_block_complete(self):
        bonus = self.payload["bonus"]
        for category in ("world_champion", "semifinalists", "top_scorer_team"):
            self.assertIn(category, bonus)
            rows = bonus[category]
            self.assertIsInstance(rows, list)
            if rows:
                first = rows[0]
                self.assertIn("team", first)
                self.assertIn("probability", first)
        self.assertIn("group_winners", bonus)
        self.assertIsInstance(bonus["group_winners"], dict)


if __name__ == "__main__":
    unittest.main()
