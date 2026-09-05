from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from wm_tipps.paths import DATA_DIR


PATH = DATA_DIR / "news_items.json"


class NewsItemsSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PATH.exists():
            raise unittest.SkipTest(
                f"{PATH} fehlt; Pipeline laufen lassen (refresh-news)."
            )
        cls.payload = json.loads(PATH.read_text(encoding="utf-8"))

    def test_top_level_fields(self):
        for field in ("updated_at", "items"):
            self.assertIn(field, self.payload)
        self.assertIsInstance(self.payload["items"], list)
        # data_quality ist optional aber soll wenn vorhanden Liste sein.
        if "data_quality" in self.payload:
            self.assertIsInstance(self.payload["data_quality"], list)

    def test_items_have_minimum_fields(self):
        for item in self.payload["items"]:
            for field in ("title", "severity"):
                self.assertIn(field, item)
            self.assertIsInstance(item.get("teams", []), list)
            self.assertIsInstance(item.get("categories", []), list)
            self.assertIn(item["severity"], {"critical", "important", "context", "noise"})

    def test_data_quality_entries_have_status(self):
        for record in self.payload.get("data_quality") or []:
            self.assertIn("source", record)
            self.assertIn("status", record)
            self.assertIn(record["status"], {"ok", "empty", "error"})


if __name__ == "__main__":
    unittest.main()
