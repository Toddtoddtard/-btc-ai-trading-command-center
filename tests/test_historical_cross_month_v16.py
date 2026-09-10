import unittest
import pandas as pd

from historical_specialist_backtest_v7 import (
    first_fresh_index,
    historical_council_score,
    qualified_council_score,
)
from specialist_knowledge_v5 import specialist_posterior


class HistoricalCrossMonthV16Tests(unittest.TestCase):
    def test_carry_rows_are_not_re_evaluated(self):
        carry = pd.date_range("2026-01-31T23:57:00Z", periods=3, freq="min")
        fresh = pd.date_range("2026-02-01T00:00:00Z", periods=4, freq="min")
        df = pd.DataFrame({"time": list(carry) + list(fresh)})
        idx = first_fresh_index(df, pd.Timestamp("2026-02-01T00:00:00Z"))
        self.assertEqual(idx, 3)
        self.assertTrue((pd.to_datetime(df.iloc[idx:]["time"], utc=True) >= pd.Timestamp("2026-02-01T00:00:00Z")).all())


    def test_historical_council_uses_eligible_specialists(self):
        results = {
            "Trend AI": {"score": 0.50, "confidence": 0.80},
            "Momentum AI": {"score": 0.25, "confidence": 0.70},
            "Whale AI": {"score": -1.0, "confidence": 0.99},
        }
        self.assertGreater(historical_council_score(results, "TREND_UP"), 0.0)

    def test_qualified_score_rejects_weak_research_guesses(self):
        weak = {
            "base_score": 0.08,
            "raw_confidence": 0.70,
            "policy": {"edge_floor": 0.16, "trade_confidence_floor": 0.56},
        }
        strong = {
            "base_score": -0.24,
            "raw_confidence": 0.67,
            "policy": {"edge_floor": 0.16, "trade_confidence_floor": 0.56},
        }
        self.assertEqual(qualified_council_score(weak), 0.0)
        self.assertLess(qualified_council_score(strong), 0.0)

    def test_version_nine_uses_holdout_as_learning_prior(self):
        state = {
            "historical_specialist_knowledge_v7": {
                "version": 9,
                "specialists": {"Trend AI": {"accuracy": 0.40, "directional_calls": 1000}},
                "holdout": {
                    "specialists": {
                        "Trend AI": {"accuracy": 0.61, "directional_calls": 200, "regimes": {}}
                    }
                },
            }
        }
        result = specialist_posterior(state, "Trend AI", "UNKNOWN")
        self.assertEqual(result["historical_samples"], 200)
        self.assertAlmostEqual(result["historical_accuracy"], 0.61)


if __name__ == "__main__":
    unittest.main()
