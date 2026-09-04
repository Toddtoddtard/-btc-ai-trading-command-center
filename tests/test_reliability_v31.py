import unittest

import pandas as pd

from learner_v31 import challenger_qualifies
from reliability_v31 import (
    calibrate_confidence,
    exact_expiry_row,
    execution_cost_bps,
    learned_policy,
    learned_trade_gate,
    regime_specialist_weight,
)


class ReliabilityTests(unittest.TestCase):
    def test_execution_cost_positive(self):
        self.assertAlmostEqual(execution_cost_bps(10000), 6.5, places=6)

    def test_round_trip_cost_is_thirteen_bps(self):
        self.assertAlmostEqual(execution_cost_bps(10000) * 2, 13.0, places=6)

    def test_exact_expiry_rejects_stale(self):
        now = pd.Timestamp("2026-09-04T12:00:00Z")
        df = pd.DataFrame({"time": [now], "close": [100.0]})
        self.assertIsNone(exact_expiry_row(df, (now + pd.Timedelta(minutes=5)).timestamp(), 75))

    def test_exact_expiry_accepts_nearby(self):
        expiry = pd.Timestamp("2026-09-04T12:15:00Z")
        df = pd.DataFrame({"time": [expiry + pd.Timedelta(seconds=40)], "close": [100.0]})
        self.assertIsNotNone(exact_expiry_row(df, expiry.timestamp(), 75))

    def test_regime_weight_shrinks_small_sample(self):
        state = {"adaptive_weight": 1.2, "regimes": {"RANGE": {"samples": 2, "adaptive_weight": 0.5}}}
        w = regime_specialist_weight(1.0, state, "RANGE")
        self.assertGreater(w, 0.5)
        self.assertLess(w, 1.2)

    def test_bad_calibration_reduces_confidence(self):
        policy = learned_policy({}, "UNKNOWN")
        good = calibrate_confidence(0.75, 0.6, policy, 1.0, {"confidence_model": {"brier_ewma": 0.18}})
        bad = calibrate_confidence(0.75, 0.6, policy, 1.0, {"confidence_model": {"brier_ewma": 0.38}})
        self.assertLess(bad, good)

    def test_trade_gate_blocks_bad_feed(self):
        policy = learned_policy({}, "UNKNOWN")
        allowed, reason = learned_trade_gate("SCALP UP", 0.9, 0.5, 0.8, policy, source_health=0.5)
        self.assertFalse(allowed)
        self.assertIn("FEED", reason)

    def test_trade_gate_blocks_conflict(self):
        policy = learned_policy({}, "UNKNOWN")
        allowed, reason = learned_trade_gate("SCALP DOWN", 0.9, -0.5, 0.05, policy, source_health=1.0)
        self.assertFalse(allowed)
        self.assertIn("CONFLICT", reason)

    def test_challenger_cannot_promote_on_small_sample(self):
        champ = {"samples": 19, "accuracy": 0.50, "median_error": 100.0}
        challenger = {"samples": 19, "accuracy": 0.80, "median_error": 60.0}
        self.assertFalse(challenger_qualifies(champ, challenger))

    def test_challenger_requires_five_point_accuracy_margin(self):
        champ = {"samples": 25, "accuracy": 0.60, "median_error": 100.0}
        challenger = {"samples": 25, "accuracy": 0.64, "median_error": 80.0}
        self.assertFalse(challenger_qualifies(champ, challenger))
        challenger["accuracy"] = 0.66
        self.assertTrue(challenger_qualifies(champ, challenger))

    def test_challenger_cannot_buy_accuracy_with_bad_error(self):
        champ = {"samples": 25, "accuracy": 0.55, "median_error": 100.0}
        challenger = {"samples": 25, "accuracy": 0.70, "median_error": 111.0}
        self.assertFalse(challenger_qualifies(champ, challenger))


if __name__ == "__main__":
    unittest.main()
