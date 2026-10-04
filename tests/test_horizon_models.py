import unittest

import numpy as np
import pandas as pd

from horizon_models import (
    FEATURE_NAMES,
    MIN_DIRECTIONAL_ACCURACY,
    _closed_price_at_target,
    _evaluate_promotion,
    default_model,
    ensure_horizon_state,
    merge_offline_bundle,
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
    def test_candidate_replacement_isolates_pending_scores_and_accepts_same_month_fix(self):
        state = {}
        root = ensure_horizon_state(state)
        candidate = {'weights': [0.1] * len(FEATURE_NAMES), 'trained_through': '2026-08',
                     'promotion_eligible': True}
        bundle = {'version': 2, 'models': {'1': candidate}}
        self.assertTrue(merge_offline_bundle(state, bundle))
        root['models']['1'].update(samples=12, enabled=True, metrics={'samples': 12})
        root['affects_execution'] = True
        root['pending'] = [{'predictions': {'1': {'probability_up': .8}, '5': {'probability_up': .6}}}]
        self.assertFalse(merge_offline_bundle(state, bundle))
        self.assertEqual(root['models']['1']['samples'], 12)
        self.assertIn('1', root['pending'][0]['predictions'])
        candidate['weights'] = [0.2] * len(FEATURE_NAMES)
        self.assertTrue(merge_offline_bundle(state, bundle))
        self.assertEqual(root['models']['1']['samples'], 0)
        self.assertEqual(root['models']['1']['metrics'], {})
        self.assertFalse(root['affects_execution'])
        self.assertEqual(set(root['pending'][0]['predictions']), {'5'})
        candidate['trained_through'] = '2026-07'
        self.assertFalse(merge_offline_bundle(state, bundle))

    def test_deadline_label_excludes_future_and_forming_candles(self):
        frame = candles(3)
        frame["close"] = [99.0, 200.0, 300.0]
        target = pd.Timestamp("2026-01-01T00:01:45Z").timestamp()
        # The 00:01 bar closes at 00:02, closer to the target but too late.
        self.assertEqual(_closed_price_at_target(frame, target), 99.0)
        self.assertEqual(_closed_price_at_target(frame.iloc[::-1], target), 99.0)
        self.assertIsNone(_closed_price_at_target(frame.iloc[1:], target))
        self.assertIsNone(_closed_price_at_target(frame.iloc[:1], target + 60))
        self.assertEqual(_closed_price_at_target(frame, target + 15), 200.0)

    def test_all_horizons_train_on_deadline_outcome_only_once(self):
        for horizon in (1, 5, 15):
            with self.subTest(horizon=horizon):
                state = {}
                root = ensure_horizon_state(state)
                target = pd.Timestamp("2026-01-01T00:01:45Z").timestamp()
                root["pending"] = [{
                    "start_price": 100.0,
                    "features": [1.0] * len(FEATURE_NAMES),
                    "predictions": {str(horizon): {
                        "target_at": target, "probability_up": .8,
                        "baseline_probability_up": .5,
                    }},
                }]
                frame = candles(3)
                frame["close"] = [99.0, 200.0, 300.0]
                self.assertEqual(resolve_horizon_predictions(state, frame, now=target - 1), 0)
                self.assertEqual(resolve_horizon_predictions(state, frame.iloc[1:], now=target), 0)
                self.assertEqual(len(root["pending"]), 1)
                # A late grading run must still exclude post-deadline prices.
                self.assertEqual(resolve_horizon_predictions(state, frame, now=target + 120), 1)
                model = root["models"][str(horizon)]
                self.assertEqual(model["hits"], 0)
                self.assertAlmostEqual(model["brier_sum"], .64)
                self.assertLess(model["weights"][0], 0)
                self.assertEqual(resolve_horizon_predictions(state, frame, now=target + 120), 0)
                self.assertEqual(model["samples"], 1)

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
        self.assertIn("weighted_depth_imbalance", features)
        self.assertIn("microprice_edge", features)
        self.assertAlmostEqual(features["yes_ask_size"], 12.0)
        self.assertTrue(features["available"])


if __name__ == "__main__":
    unittest.main()
