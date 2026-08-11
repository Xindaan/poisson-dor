from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.backtest import (
    VARIANT_NAMES,
    build_backtest_report,
    run_backtest,
    tip_from_elo,
    tip_from_ensemble,
    tip_from_odds,
)
from wm_tipps.scoring import DEFAULT_ROUND_ID, SECONDARY_ROUND_ID


def _write_dataset(rows):
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(rows, handle)
    handle.close()
    return Path(handle.name)


def _replicate(row, count):
    """Zeile count-mal mit eindeutigem match-Namen -- damit die Verdict-
    Coverage-Schwelle (VERDICT_MIN_COVERAGE) erreicht wird."""
    rows = []
    for index in range(count):
        clone = dict(row)
        clone["match"] = f"{row['match']} {index}"
        rows.append(clone)
    return rows


class BacktestEngineTests(unittest.TestCase):
    def test_legacy_sample_keeps_aliases_and_counts(self):
        result = run_backtest()
        self.assertEqual(result["matches"], 7)
        # T-0097: je -1 ggue. frueher, weil ein falscher Remis-Score jetzt
        # korrekt Tendenz (2) statt Tordifferenz (3) zaehlt.
        self.assertEqual(result["favorite_points"], 13)
        self.assertEqual(result["model_points"], 15)
        self.assertEqual(result["variants"]["naive"]["points"], 13)
        self.assertEqual(result["variants"]["ensemble"]["points"], 15)
        self.assertEqual(result["variants"]["elo"]["matches"], 0)
        self.assertEqual(result["variants"]["odds"]["matches"], 0)
        self.assertEqual(set(result["variants"].keys()), set(VARIANT_NAMES))

    def test_elo_helper_picks_home_win_for_strong_home(self):
        home, away = tip_from_elo(1900, 1500, "group")
        self.assertGreater(home, away)

    def test_elo_helper_picks_away_win_for_strong_away(self):
        home, away = tip_from_elo(1500, 1900, "group")
        self.assertLess(home, away)

    def test_elo_variant_counts_when_pre_elo_present(self):
        path = _write_dataset(
            [
                {
                    "match": "Strong - Weak",
                    "stage": "group",
                    "actual": [3, 0],
                    "pre_elo": {"home": 1900, "away": 1500},
                }
            ]
        )
        try:
            result = run_backtest(path)
        finally:
            path.unlink()
        self.assertEqual(result["variants"]["elo"]["matches"], 1)
        self.assertIsNotNone(result["variants"]["elo"]["points_per_match"])
        self.assertEqual(
            result["variants"]["naive"]["points"], result["variants"]["elo"]["points"]
        )

    def test_odds_variant_counts_when_pre_odds_present(self):
        path = _write_dataset(
            [
                {
                    "match": "Favored - Underdog",
                    "stage": "group",
                    "actual": [2, 0],
                    "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
                }
            ]
        )
        try:
            result = run_backtest(path)
        finally:
            path.unlink()
        self.assertEqual(result["variants"]["odds"]["matches"], 1)
        self.assertIsNotNone(result["variants"]["odds"]["points_per_match"])

    def test_ensemble_variant_derives_from_pre_match_inputs(self):
        path = _write_dataset(
            [
                {
                    "match": "Favored - Underdog",
                    "stage": "group",
                    "actual": [2, 0],
                    "pre_elo": {"home": 1900, "away": 1500},
                    "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
                }
            ]
        )
        try:
            result = run_backtest(path)
        finally:
            path.unlink()
        self.assertEqual(result["variants"]["ensemble"]["matches"], 1)
        self.assertIsNotNone(
            tip_from_ensemble(
                {"home": 1900, "away": 1500},
                {"home": 1.40, "draw": 4.50, "away": 8.00},
                "group",
            )
        )

    def test_ensemble_keeps_elo_when_market_disagreement_is_small(self):
        # Override-LOGIK (Tendenz), nicht Scoreline-Hoehe: DC-rho (T-0104) verschiebt
        # zwar die Scoreline, nicht die Tendenz -> bei DC=0 isoliert geprueft.
        import wm_tipps.model as wm_model
        self.addCleanup(setattr, wm_model, "DRAW_DC_RHO", wm_model.DRAW_DC_RHO)
        wm_model.DRAW_DC_RHO = 0.0
        pre_elo = {"home": 1707, "away": 1719}
        pre_odds = {"home": 2.24, "draw": 3.38, "away": 3.88}
        self.assertEqual(
            tip_from_ensemble(pre_elo, pre_odds, "group"),
            tip_from_elo(pre_elo["home"], pre_elo["away"], "group"),
        )

    def test_ensemble_accepts_material_market_correction(self):
        # Override-LOGIK (Markt-Tendenz akzeptiert), DC-rho (T-0104) bei 0 isoliert.
        import wm_tipps.model as wm_model
        self.addCleanup(setattr, wm_model, "DRAW_DC_RHO", wm_model.DRAW_DC_RHO)
        wm_model.DRAW_DC_RHO = 0.0
        self.assertEqual(
            tip_from_ensemble(
                {"home": 1776, "away": 1766},
                {"home": 4.63, "draw": 3.66, "away": 1.68},
                "group",
            ),
            (0, 1),
        )

    def test_odds_helper_returns_none_for_invalid_input(self):
        self.assertIsNone(tip_from_odds({}, None, "group"))
        self.assertIsNone(tip_from_odds({"home": "1.0"}, None, "group"))

    def test_knockout_round_penalty_convention(self):
        # KO 1-1, Elfer-Sieger away. Die Elfer-Runde wertet 1:2 (nach Elfer),
        # die eskalierende Runde 1:1 (nach Verlaengerung).
        row = {
            "match": "A - B",
            "stage": "knockout",
            "actual": [1, 1],
            "penalty_winner": "away",
            "pre_elo": {"home": 1800, "away": 1800},
        }
        path = _write_dataset([row])
        try:
            r15 = run_backtest(path, round_id=DEFAULT_ROUND_ID)
            rvv = run_backtest(path, round_id=SECONDARY_ROUND_ID)
        finally:
            path.unlink()
        self.assertEqual(r15["knockout_matches"], 1)
        self.assertEqual(r15["round_id"], DEFAULT_ROUND_ID)
        # Beide Runden werten das KO-Spiel fuer elo/ensemble (kein odds).
        self.assertEqual(r15["variants"]["elo"]["matches"], 1)
        self.assertEqual(r15["variants"]["odds"]["matches"], 0)
        self.assertEqual(rvv["round_id"], SECONDARY_ROUND_ID)

    def test_empty_dataset_returns_zero_structure(self):
        path = _write_dataset([])
        try:
            result = run_backtest(path)
        finally:
            path.unlink()
        self.assertEqual(result["matches"], 0)
        self.assertEqual(result["favorite_points"], 0)
        for name in VARIANT_NAMES:
            self.assertEqual(result["variants"][name]["matches"], 0)
            self.assertIsNone(result["variants"][name]["points_per_match"])

    def test_backtest_report_aggregates_deltas_and_head_to_head(self):
        path = _write_dataset(
            [
                {
                    "match": "Market - Model",
                    "stage": "group",
                    "actual": [0, 1],
                    "model_tip": [0, 1],
                    "pre_elo": {"home": 1700, "away": 1500},
                    "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
                }
            ]
        )
        try:
            report = build_backtest_report(
                datasets=[("test", path)],
                write=False,
            )
        finally:
            path.unlink()
        combined = report["combined"]
        self.assertNotIn("evaluated_matches", combined)
        self.assertEqual(combined["variants"]["ensemble"]["points"], 4)
        self.assertEqual(combined["variants"]["odds"]["points"], 0)
        self.assertEqual(combined["best_variant"]["name"], "ensemble")
        self.assertEqual(combined["variants"]["ensemble"]["delta_vs_odds_points"], 4)
        self.assertEqual(
            combined["head_to_head"]["ensemble_vs_odds"]["left_wins"],
            1,
        )
        self.assertEqual(len(combined["ensemble_odds_differing_matches"]), 1)

    def test_blend_weight_sweep_structure_and_current_flag(self):
        # Punkt C: Sweep-Struktur auf einem Turnier (schnell).
        from wm_tipps.backtest import (
            BLEND_SWEEP_WEIGHTS,
            ENSEMBLE_MARKET_BLEND_WEIGHT,
            blend_weight_sweep,
            evaluate_backtest_dataset,
        )
        from wm_tipps.historical import historical_dataset_path
        from wm_tipps.historical_markets import load_historical_market_payload

        path = historical_dataset_path("2018")
        if not path.exists():
            self.skipTest("2018-Dataset nicht verfuegbar.")
        section = evaluate_backtest_dataset(
            "2018", path, historical_market_payload=load_historical_market_payload()
        )
        rows = [
            row for row in section["evaluated_matches"]
            if row["variants"]["odds"]["points"] is not None
        ]
        report = blend_weight_sweep(rows=rows)
        self.assertEqual(len(report["weights"]), len(BLEND_SWEEP_WEIGHTS))
        current = [w for w in report["weights"] if w["is_current"]]
        self.assertEqual(len(current), 1)
        self.assertAlmostEqual(current[0]["market_weight"], ENSEMBLE_MARKET_BLEND_WEIGHT)
        self.assertTrue(
            all(w["matches"] == report["_meta"]["matches"] for w in report["weights"] if w["matches"])
        )
        self.assertIn(
            report["_meta"]["best_weight"],
            [w["market_weight"] for w in report["weights"]],
        )

    def test_market_score_disagreement_matches_variant_delta(self):
        # T-0054c: Der Disagreement-Netto-Wert muss exakt dem
        # Variant-Delta odds_market_score_v1 vs odds_draw_total entsprechen,
        # und helped+hurt muss netto/Mover-Zahl konsistent sein.
        # Nur 2018 (hat Zusatzmaerkte + Disagreements), damit der Test
        # nicht den vollen 4-Turnier-Report neu rechnen muss.
        from wm_tipps.historical import historical_dataset_path

        dataset_path = historical_dataset_path("2018")
        if not dataset_path.exists():
            self.skipTest("2018-Dataset nicht verfuegbar.")
        report = build_backtest_report(
            datasets=[("2018", dataset_path)], write=False
        )
        sc = report.get("score_calibration") or {}
        variants = sc.get("variants") or {}
        if not variants.get("odds_market_score_v1", {}).get("matches"):
            self.skipTest("Keine historischen Quoten-Datasets verfuegbar.")
        dis = sc.get("market_score_disagreement") or {}
        delta = variants["odds_market_score_v1"]["delta_vs_draw_total_points"]
        self.assertEqual(dis["net_points"], delta)
        self.assertEqual(
            dis["net_points"], dis["helped"]["points"] + dis["hurt"]["points"]
        )
        self.assertEqual(
            len(dis["movers"]), dis["helped"]["games"] + dis["hurt"]["games"]
        )
        # Punktneutrale Tippwechsel zaehlen mit zu den abweichenden Tipps.
        self.assertEqual(
            dis["differing_tips"],
            dis["helped"]["games"] + dis["hurt"]["games"] + dis["neutral_tip_changes"],
        )

    def test_backtest_report_odds_covered_uses_same_subset(self):
        # Fairer Vergleich: odds_covered darf nur Spiele mit Quoten zaehlen,
        # und dort muessen ALLE Varianten denselben Nenner haben.
        rows = [
            {
                "match": "With - Odds",
                "stage": "group",
                "actual": [0, 1],
                "model_tip": [0, 1],
                "pre_elo": {"home": 1700, "away": 1500},
                "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
            },
            {
                "match": "No - Odds",
                "stage": "knockout",
                "actual": [1, 0],
                "model_tip": [1, 0],
                "pre_elo": {"home": 1800, "away": 1600},
            },
        ]
        path = _write_dataset(rows)
        try:
            report = build_backtest_report(datasets=[("test", path)], write=False)
        finally:
            path.unlink()
        combined = report["combined"]
        odds_covered = report["odds_covered"]
        calibration = report["score_calibration"]
        # Kombiniert deckt beide Spiele, odds nur eines.
        self.assertEqual(combined["matches"], 2)
        self.assertEqual(combined["variants"]["odds"]["matches"], 1)
        # Fairer Block: genau das eine Spiel mit Quoten, gleicher Nenner.
        self.assertEqual(odds_covered["matches"], 1)
        for name in VARIANT_NAMES:
            self.assertEqual(odds_covered["variants"][name]["matches"], 1)
        self.assertEqual(calibration["matches"], 1)
        self.assertIn("odds_draw_total", calibration["variants"])
        self.assertIn("ensemble_current_15", calibration["variants"])
        self.assertIn("Remiswahrscheinlichkeit", calibration["summary"])
        market_calibrator = calibration["market_score_calibrator"]
        self.assertEqual(market_calibrator["version"], "market_score_v1")
        self.assertEqual(market_calibrator["historical_coverage"]["1x2"], 1)
        self.assertEqual(market_calibrator["historical_coverage"]["over_under"], 0)
        self.assertIn("ready", market_calibrator["status"])

    def test_backtest_report_includes_historical_market_score_variant(self):
        rows = [
            {
                "match": "Alpha - Beta",
                "stage": "group",
                "actual": [2, 1],
                "pre_elo": {"home": 1600, "away": 1500},
                "pre_odds": {"home": 1.80, "draw": 3.60, "away": 4.80},
            }
        ]
        market_payload = {
            "items": [
                {
                    "tournament": "test",
                    "match": "Alpha - Beta",
                    "source": "checkbestodds",
                    "source_url": "https://example.test/alpha-beta",
                    "markets": {
                        "over_under": [
                            {
                                "line": 2.5,
                                "over_probability": 0.64,
                                "under_probability": 0.36,
                                "source": "checkbestodds",
                            }
                        ],
                        "btts": {
                            "yes_probability": 0.58,
                            "no_probability": 0.42,
                            "source": "checkbestodds",
                        },
                        "handicap": [],
                    },
                }
            ]
        }
        source_audit = {
            "_meta": {"updated_at": "2026-06-07T00:00:00+00:00"},
            "decision": {"status": "backtest_only"},
            "sources": [{"id": "checkbestodds_world_cup_test", "accepted": True}],
        }
        path = _write_dataset(rows)
        try:
            report = build_backtest_report(
                datasets=[("test", path)],
                write=False,
                historical_market_payload=market_payload,
                historical_market_source_audit=source_audit,
            )
        finally:
            path.unlink()
        calibration = report["score_calibration"]
        self.assertIn("odds_market_score_v1", calibration["variants"])
        self.assertEqual(
            calibration["variants"]["odds_market_score_v1"]["extra_market_matches"],
            1,
        )
        market_calibrator = calibration["market_score_calibrator"]
        self.assertEqual(market_calibrator["historical_coverage"]["over_under"], 1)
        self.assertEqual(market_calibrator["historical_coverage"]["btts"], 1)
        self.assertEqual(market_calibrator["source_audit"]["accepted_sources_count"], 1)

    def test_backtest_report_head_to_head_requires_both_variants(self):
        path = _write_dataset(
            [
                {
                    "match": "Both - Present",
                    "stage": "group",
                    "actual": [1, 0],
                    "model_tip": [1, 0],
                    "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
                },
                {
                    "match": "Odds - Missing",
                    "stage": "group",
                    "actual": [1, 0],
                    "model_tip": [1, 0],
                },
            ]
        )
        try:
            report = build_backtest_report(
                datasets=[("test", path)],
                write=False,
            )
        finally:
            path.unlink()
        self.assertEqual(
            report["combined"]["head_to_head"]["ensemble_vs_odds"]["compared"],
            1,
        )
        self.assertEqual(report["combined"]["variants"]["ensemble"]["matches"], 2)
        self.assertEqual(report["combined"]["variants"]["odds"]["matches"], 1)

    def test_backtest_report_verdict_keep_full_intelligence(self):
        # T-0058: ppm-Edge >= +0.05 UND mehr Turniere vorn als hinten, auf
        # ausreichender Coverage (>= VERDICT_MIN_COVERAGE).
        row = {
            "match": "Market - Model",
            "stage": "group",
            "actual": [0, 1],
            "model_tip": [0, 1],
            "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
        }
        first = _write_dataset(_replicate(row, 30))
        second = _write_dataset(_replicate(row, 30))
        try:
            report = build_backtest_report(
                datasets=[("a", first), ("b", second)],
                write=False,
            )
        finally:
            first.unlink()
            second.unlink()
        self.assertEqual(report["verdict"]["status"], "keep_full_intelligence")
        self.assertGreaterEqual(report["verdict"]["points_per_match_delta"], 0.05)
        self.assertGreater(
            report["verdict"]["tournaments_ahead"],
            report["verdict"]["tournaments_behind"],
        )

    def test_backtest_report_verdict_simplify_to_odds_plus_watch(self):
        row = {
            "match": "Market - Model",
            "stage": "group",
            "actual": [1, 0],
            "model_tip": [0, 1],
            "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
        }
        path = _write_dataset(_replicate(row, 60))
        try:
            report = build_backtest_report(datasets=[("test", path)], write=False)
        finally:
            path.unlink()
        self.assertEqual(report["verdict"]["status"], "simplify_to_odds_plus_watch")

    def test_backtest_report_verdict_needs_more_data_on_small_coverage(self):
        # Gleiche Konstellation wie keep_full, aber Coverage < Schwelle.
        row = {
            "match": "Market - Model",
            "stage": "group",
            "actual": [0, 1],
            "model_tip": [0, 1],
            "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
        }
        path = _write_dataset(_replicate(row, 10))
        try:
            report = build_backtest_report(datasets=[("test", path)], write=False)
        finally:
            path.unlink()
        self.assertEqual(report["verdict"]["status"], "needs_more_data")

    def test_backtest_report_verdict_needs_more_data_on_missing_odds(self):
        path = _write_dataset(
            [
                {
                    "match": "No - Odds",
                    "stage": "group",
                    "actual": [1, 0],
                    "model_tip": [1, 0],
                }
            ]
        )
        try:
            report = build_backtest_report(datasets=[("test", path)], write=False)
        finally:
            path.unlink()
        self.assertEqual(report["verdict"]["status"], "needs_more_data")

    def test_backtest_report_verdict_needs_more_data_on_empty_dataset(self):
        path = _write_dataset([])
        try:
            report = build_backtest_report(datasets=[("empty", path)], write=False)
        finally:
            path.unlink()
        self.assertEqual(report["combined"]["matches"], 0)
        self.assertEqual(report["verdict"]["status"], "needs_more_data")

    def test_backtest_report_writes_json_and_markdown(self):
        row = {
            "match": "Market - Model",
            "stage": "group",
            "actual": [0, 1],
            "model_tip": [0, 1],
            "pre_odds": {"home": 1.40, "draw": 4.50, "away": 8.00},
        }
        dataset = _write_dataset([row])
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "report.json"
            markdown_path = Path(tmpdir) / "report.md"
            try:
                report = build_backtest_report(
                    datasets=[("test", dataset)],
                    json_path=json_path,
                    markdown_path=markdown_path,
                )
            finally:
                dataset.unlink()
            self.assertEqual(
                json.loads(json_path.read_text())["verdict"],
                report["verdict"],
            )
            self.assertIn(
                "Lohnt-sich-das?-Ablation-Report",
                markdown_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Score-Kalibrierung 2.0",
                markdown_path.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "T-0054 Market-Score-Calibrator",
                markdown_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
