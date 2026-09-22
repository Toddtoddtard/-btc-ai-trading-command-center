import unittest

import numpy as np
import pandas as pd

from horizon_models import (
    FEATURE_NAMES,
    MIN_DIRECTIONAL_ACCURACY,
    _evaluate_promotion,
    default_model,
    ensure_horizon_state,
    feature_vector,
    register_horizon_predictions,
    resolve_horizon_predictions,
)
from kalshi_microstructure import orderbook_features


def candles(count=100, start="2026-01-01T00:00:00Z"):
    times = pd.date_range(start, periods=count, freq="min", tz="UTC")
    close = 100_000 + np.arange(count) * 2.0 + np.sin(np.arange(count) / 4) * 10
    return pd.DataFrame({
        "time": times,
        "open": close - 1,
        "high": close + 5,
        "low": close - 5,
        "close": close,
        "volume": 10 + np.arange(count) % 7,
    })


class HorizonModelTests(unittest.TestCase):
    def test_features_are_finite_and_past_only(self):
        frame = candles()
        before = feature_vector(frame.iloc[:80].to_dict("records"))
        frame.loc[90:, "close"] *= 2
        after = feature_vector(frame.iloc[:80].to_dict("records"))
        self.assertEqual(len(before), len(FEATURE_NAMES))
        self.assertTrue(np.isfinite(before).all())
        np.testing.assert_allclose(before, after)

    def test_context_adds_seven_bounded_features(self):
        frame = candles()
        plain = feature_vector(frame.to_dict("records"))
        context = {"features": {"context_30m": .75, "context_1mo": -0.4}}
        enriched = feature_vector(frame.to_dict("records"), context)
        self.assertEqual(len(enriched), 21)
        np.testing.assert_allclose(plain[:14], enriched[:14])
        self.assertAlmostEqual(enriched[14], .75)
        self.assertAlmostEqual(enriched[-1], -.4)

    def test_old_schema_is_reset_instead_of_mixed(self):
        state = {"horizon_models": {
            "version": 1, "feature_names": ["old"],
            "models": {"1": {"weights": [1.0], "enabled": True}},
            "pending": [{"features": [1.0]}],
        }}
        root = ensure_horizon_state(state)
        self.assertEqual(root["version"], 2)
        self.assertEqual(root["pending"], [])
        self.assertFalse(root["models"]["1"]["enabled"])

    def test_prediction_is_registered_then_graded_and_trained(self):
        frame = candles()
        state = {}
        ensure_horizon_state(state)
        observed = pd.Timestamp(frame.time.iloc[70]).timestamp() + 60
        rows = frame.iloc[:71].to_dict("records")
        self.assertTrue(register_horizon_predictions(state, rows, observed_at=observed))
        self.assertEqual(state["horizon_models"]["models"]["1"]["samples"], 0)
        now = observed + 16 * 60
        graded = resolve_horizon_predictions(state, frame, now=now)
        self.assertEqual(graded, 3)
        self.assertEqual(state["horizon_models"]["models"]["1"]["samples"], 1)
        self.assertNotEqual(state["horizon_models"]["models"]["1"]["weights"], [0.0] * len(FEATURE_NAMES))

    def test_unvalidated_models_never_affect_execution(self):
        state = {}
        root = ensure_horizon_state(state)
        for model in root["models"].values():
            model["samples"] = 10_000
            model["enabled"] = False
            model["historical_validated"] = False
        self.assertFalse(root["affects_execution"])

    def test_model_below_seventy_percent_accuracy_stays_shadow_only(self):
        model = default_model(15)
        model.update({
            "historical_validated": True,
            "samples": 200,
            "hits": 120,
            "baseline_hits": 100,
            "brier_sum": 40.0,
            "baseline_brier_sum": 50.0,
            "recent": [
                {"brier": .20, "baseline_brier": .25, "hit": 1, "baseline_hit": 1}
                for _ in range(50)
            ],
        })
        for _ in range(4):
            self.assertFalse(_evaluate_promotion(model))
        self.assertFalse(model["enabled"])
        self.assertEqual(model["qualification_streak"], 0)
        self.assertEqual(model["metrics"]["minimum_directional_accuracy"], .70)

    def test_model_needs_three_seventy_percent_qualifying_evaluations(self):
        model = default_model(15)
        model.update({
            "historical_validated": True,
            "samples": 200,
            "hits": int(200 * MIN_DIRECTIONAL_ACCURACY),
            "baseline_hits": 100,
            "brier_sum": 40.0,
            "baseline_brier_sum": 50.0,
            "recent": [
                {"brier": .20, "baseline_brier": .25, "hit": 1, "baseline_hit": 1}
                for _ in range(50)
            ],
        })
        self.assertTrue(_evaluate_promotion(model))
        self.assertFalse(model["enabled"])
        self.assertTrue(_evaluate_promotion(model))
        self.assertFalse(model["enabled"])
        self.assertTrue(_evaluate_promotion(model))
        self.assertTrue(model["enabled"])

    def test_enabled_model_is_disabled_below_seventy_percent_accuracy(self):
        model = default_model(15)
        model.update({
            "enabled": True,
            "historical_validated": True,
            "samples": 200,
            "hits": 139,
            "baseline_hits": 100,
            "brier_sum": 40.0,
            "baseline_brier_sum": 50.0,
            "recent": [
                {"brier": .20, "baseline_brier": .25, "hit": 1, "baseline_hit": 1}
                for _ in range(50)
            ],
        })
        self.assertFalse(_evaluate_promotion(model))
        self.assertFalse(model["enabled"])
        self.assertIn("70%", model["disabled_reason"])

    def test_kalshi_bid_only_book_is_reconstructed(self):
        features = orderbook_features({
            "orderbook_fp": {
                "yes_dollars": [["0.47", "10"], ["0.45", "20"]],
                "no_dollars": [["0.51", "12"], ["0.49", "18"]],
            }
        })
        self.assertAlmostEqual(features["yes_bid"], .47)
        self.assertAlmostEqual(features["yes_ask"], .49)
        self.assertAlmostEqual(features["spread"], .02)
        self.assertTrue(features["available"])


if __name__ == "__main__":
    unittest.main()
