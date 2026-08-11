"""T-0136: Signal-abhaengiges Blend-Vertrauen (forward-gated)."""
import unittest

from wm_tipps import signal_blend

BASE = 0.20  # entspricht model.ENSEMBLE_MARKET_BLEND_WEIGHT

# Modell favorisiert Auswaerts (Norwegen), Markt favorisiert Heim (Brasilien).
MODEL_DISAGREE = {"home": 0.34, "draw": 0.26, "away": 0.40}
MARKET_HOME = {"home": 0.57, "draw": 0.24, "away": 0.19}
# Harte Brasilien-Ausfaelle (news auf Heim), Betrag 0.18 >= HARD_SIGNAL_MIN.
BREAKDOWN_HARD = {"home": {"news_effect": -0.18}, "away": {"news_effect": 0.0}}
BREAKDOWN_WEAK = {"home": {"news_effect": -0.05}, "away": {"news_effect": 0.0}}


class ResolveBlendWeightTests(unittest.TestCase):
    def test_default_flag_is_off(self):
        self.assertFalse(signal_blend.SIGNAL_AWARE_BLEND_ENABLED)

    def test_flag_off_is_noop(self):
        weight, info = signal_blend.resolve_blend_weight(
            MODEL_DISAGREE, MARKET_HOME, BREAKDOWN_HARD, base_weight=BASE, enabled=False
        )
        self.assertEqual(weight, BASE)
        self.assertFalse(info["applied"])

    def test_agreement_is_noop(self):
        # gleicher Favorit -> nie eingreifen, auch bei starkem Signal
        weight, info = signal_blend.resolve_blend_weight(
            {"home": 0.55, "draw": 0.25, "away": 0.20},
            MARKET_HOME,
            BREAKDOWN_HARD,
            base_weight=BASE,
            enabled=True,
        )
        self.assertEqual(weight, BASE)
        self.assertFalse(info["applied"])

    def test_disagreement_with_hard_signal_applies(self):
        weight, info = signal_blend.resolve_blend_weight(
            MODEL_DISAGREE, MARKET_HOME, BREAKDOWN_HARD, base_weight=BASE, enabled=True
        )
        self.assertTrue(info["applied"])
        self.assertEqual(weight, signal_blend.SIGNAL_TRIGGERED_WEIGHT)
        self.assertLess(weight, BASE)
        self.assertEqual(info["model_favorite"], "away")
        self.assertEqual(info["market_favorite"], "home")

    def test_disagreement_weak_signal_is_noop(self):
        weight, info = signal_blend.resolve_blend_weight(
            MODEL_DISAGREE, MARKET_HOME, BREAKDOWN_WEAK, base_weight=BASE, enabled=True
        )
        self.assertEqual(weight, BASE)
        self.assertFalse(info["applied"])

    def test_overwhelming_market_edge_is_capped(self):
        # Markt >> Modell (edge > MAX_MARKET_EDGE) -> Signal vermutlich eingepreist
        market_lopsided = {"home": 0.80, "draw": 0.13, "away": 0.07}
        weight, info = signal_blend.resolve_blend_weight(
            MODEL_DISAGREE, market_lopsided, BREAKDOWN_HARD, base_weight=BASE, enabled=True
        )
        self.assertEqual(weight, BASE)
        self.assertFalse(info["applied"])

    def test_magnitude_sums_both_sides_absolute(self):
        bd = {"home": {"news_effect": -0.12}, "away": {"travel_effect": -0.08}}
        self.assertAlmostEqual(signal_blend.hard_signal_magnitude(bd), 0.20, places=4)

    def test_magnitude_empty_breakdown(self):
        self.assertEqual(signal_blend.hard_signal_magnitude(None), 0.0)
        self.assertEqual(signal_blend.hard_signal_magnitude({}), 0.0)


class GuardContradictoryLeversTests(unittest.TestCase):
    """T-0136 und T-0144 sind Gegenthesen auf demselben Entscheidungspunkt."""

    def test_both_enabled_raises(self):
        with self.assertRaises(ValueError):
            signal_blend.guard_contradictory_levers(
                signal_blend_enabled=True, news_veto_enabled=True
            )

    def test_single_lever_is_fine(self):
        signal_blend.guard_contradictory_levers(signal_blend_enabled=True, news_veto_enabled=False)
        signal_blend.guard_contradictory_levers(signal_blend_enabled=False, news_veto_enabled=True)

    def test_repo_default_is_both_off(self):
        self.assertFalse(signal_blend.SIGNAL_AWARE_BLEND_ENABLED)
        self.assertFalse(signal_blend.NEWS_MARKET_VETO_ENABLED)


class ResolveNewsVetoTests(unittest.TestCase):
    """T-0144: News verwerfen, wenn SIE den Favoriten gegen den Markt drehen."""

    # ko-099: Modell MIT News favorisiert Heim (Norwegen), OHNE News Auswaerts
    # (England) -- der Markt hat England klar bei 51%.
    WITH_NEWS = {"home": 0.373, "draw": 0.357, "away": 0.270}
    WITHOUT_NEWS = {"home": 0.245, "draw": 0.300, "away": 0.455}
    MARKET_AWAY = {"home": 0.233, "draw": 0.258, "away": 0.510}
    BREAKDOWN = {"home": {"news_effect": 0.065}, "away": {"news_effect": -0.522}}

    def _veto(self, **kw):
        args = {
            "model_probs": self.WITH_NEWS,
            "model_probs_without_news": self.WITHOUT_NEWS,
            "market_probs": self.MARKET_AWAY,
            "breakdown": self.BREAKDOWN,
            "enabled": True,
        }
        args.update(kw)
        return signal_blend.resolve_news_veto(
            args["model_probs"], args["model_probs_without_news"],
            args["market_probs"], args["breakdown"], enabled=args["enabled"],
        )

    def test_flag_off_is_noop(self):
        veto, info = self._veto(enabled=False)
        self.assertFalse(veto)
        self.assertFalse(info["applied"])

    def test_news_caused_flip_against_clear_market_is_vetoed(self):
        veto, info = self._veto()
        self.assertTrue(veto)
        self.assertEqual(info["market_favorite"], "away")
        self.assertEqual(info["model_favorite"], "home")
        self.assertEqual(info["model_favorite_without_news"], "away")

    def test_disagreement_not_caused_by_news_is_not_vetoed(self):
        # Auch ohne News steht das Modell gegen den Markt -> Elo/Kontext, nicht News.
        veto, info = self._veto(model_probs_without_news={"home": 0.40, "draw": 0.30, "away": 0.30})
        self.assertFalse(veto)
        self.assertIn("nicht news-verursacht", info["reason"])

    def test_weak_market_favorite_is_not_vetoed(self):
        veto, _ = self._veto(market_probs={"home": 0.30, "draw": 0.29, "away": 0.41})
        self.assertFalse(veto)

    def test_tiny_news_effect_is_not_vetoed(self):
        veto, _ = self._veto(breakdown={"home": {"news_effect": 0.01}, "away": {"news_effect": -0.02}})
        self.assertFalse(veto)

    def test_agreement_is_noop(self):
        veto, _ = self._veto(model_probs={"home": 0.20, "draw": 0.25, "away": 0.55})
        self.assertFalse(veto)

    def test_missing_market_is_noop(self):
        veto, _ = self._veto(market_probs=None)
        self.assertFalse(veto)


if __name__ == "__main__":
    unittest.main()
