import unittest

import numpy as np
import pandas as pd

from train_horizon_models import feature_frame, month_samples


class HistoricalContextTests(unittest.TestCase):
    def test_constant_volume_matches_live_neutral_volume_feature(self):
        from horizon_models import feature_vector
        frame = self.frame(121)
        frame['volume'] = 10.0
        offline = feature_frame(frame)
        live = feature_vector(frame.to_dict('records'))
        self.assertEqual(offline.loc[120, 'volume_z'], live[11])

    def test_samples_do_not_use_row_offsets_across_missing_minutes(self):
        from horizon_models import FEATURE_NAMES
        frame = self.frame(150)
        frame.loc[80:, 'time'] += pd.Timedelta(hours=1)
        # Supply finite higher context to isolate timestamp eligibility.
        features = pd.DataFrame(0.0, index=frame.index, columns=FEATURE_NAMES)
        features['ret1'] = frame.index
        x, _, _ = month_samples(frame, 15, features)
        self.assertFalse(any(65 <= value < 140 for value in x[:, 0]))

    def test_partial_higher_timeframe_is_not_complete_context(self):
        frame = self.frame(121)
        frame['time'] += pd.Timedelta(minutes=10)
        # Archive begins at 00:10; the 00:00-00:30 bar has only 20 minutes.
        self.assertTrue(pd.isna(feature_frame(frame).loc[20, 'context_30m']))

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

    def test_mixed_datetime_precision_is_normalized(self):
        frame = self.frame(121)
        frame["time"] = frame["time"].astype("datetime64[us, UTC]")
        features = feature_frame(frame)
        self.assertTrue(np.isfinite(features.loc[90, "context_30m"]))


if __name__ == "__main__":
    unittest.main()
