import unittest

import numpy as np
import pandas as pd

from train_horizon_models import feature_frame


class HistoricalContextTests(unittest.TestCase):
    @staticmethod
    def frame(count=3_100):
        time = pd.date_range("2026-01-01", periods=count, freq="min", tz="UTC")
        close = 100_000 + np.arange(count) * .1
        return pd.DataFrame({
            "time": time,
            "open": close - .05,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 10 + np.arange(count) % 5,
        })

    def test_future_prices_cannot_change_past_context(self):
        frame = self.frame()
        before = feature_frame(frame).loc[2_000, "context_30m"]
        frame.loc[2_001:, ["open", "high", "low", "close"]] *= 2
        after = feature_frame(frame).loc[2_000, "context_30m"]
        self.assertAlmostEqual(before, after)

    def test_current_incomplete_bar_is_not_used(self):
        frame = self.frame(121)
        features = feature_frame(frame)
        # At the 01:31 observation only the bar ending 01:30 is available.
        reference = features.loc[90, "context_30m"]
        frame.loc[91:119, "close"] *= 1.5
        changed = feature_frame(frame).loc[90, "context_30m"]
        self.assertAlmostEqual(reference, changed)


if __name__ == "__main__":
    unittest.main()
