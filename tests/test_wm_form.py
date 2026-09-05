"""Regression fuer T-0180: analysis/wm_form.py und die Kurzform in
manual_results.json.

``normalize_manual_results`` (role_experiment.py) erlaubt neben dem vollen
Dict {"actual":..,"penalty_winner":..,"shootout":..} ausdruecklich auch die
Kurzform {"ga-001": [1, 0]}. wm_form.py griff frueher roh auf ``r["actual"]``
zu und brach bei der Kurzform mit TypeError, weil eine Liste keine String-
Keys kennt. Fix: ueber ``normalize_manual_results`` lesen statt selbst zu
unterscheiden.

Kein Zugriff auf data/ im Repo -- eigenes Scratch-DATA_DIR, damit der Test
auch ohne die (gitignorten) Instanzdaten laeuft.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_wm_form():
    spec = importlib.util.spec_from_file_location("wm_form_t0180", ROOT / "analysis" / "wm_form.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_data_dir(tmp_path: Path, results: dict) -> None:
    (tmp_path / "predictions.json").write_text(json.dumps({
        "predictions": [
            {
                "fixture": {"match_id": "ga-001", "home_team": "Mexico", "away_team": "South Africa"},
                "xg": {"home": 2.0, "away": 0.7},
            },
            {
                "fixture": {"match_id": "ga-002", "home_team": "Mexico", "away_team": "Poland"},
                "xg": {"home": 1.5, "away": 1.0},
            },
        ]
    }))
    (tmp_path / "fixtures.json").write_text(json.dumps({
        "fixtures": [
            {"match_id": "ga-001", "home_team": "Mexico", "away_team": "South Africa", "group": "A"},
            {"match_id": "ga-002", "home_team": "Mexico", "away_team": "Poland", "group": "A"},
        ]
    }))
    (tmp_path / "manual_results.json").write_text(json.dumps({"results": results}))


class WmFormKurzformTests(unittest.TestCase):
    def setUp(self):
        self.wm_form = _load_wm_form()

    def test_kurzform_und_volldict_gemischt(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_data_dir(tmp_path, {
                "ga-001": [2, 0],  # Kurzform
                "ga-002": {"actual": [1, 1], "penalty_winner": None},  # Volldict
            })
            self.wm_form.DATA_DIR = tmp_path
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.wm_form.main()
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            # Beide Spiele muessen eingeflossen sein (Mexico aus 2 Spielen, je 1 fuer die Gegner).
            self.assertIn("Mexico", out)
            self.assertIn("South Africa", out)
            self.assertIn("Poland", out)

    def test_kurzform_allein_reicht(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_data_dir(tmp_path, {"ga-001": [2, 0]})
            self.wm_form.DATA_DIR = tmp_path
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.wm_form.main()
            self.assertEqual(rc, 0)
            self.assertIn("Mexico", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
