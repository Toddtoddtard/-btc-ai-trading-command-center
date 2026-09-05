import unittest
import pandas as pd

from historical_specialist_backtest_v7 import first_fresh_index


class HistoricalCrossMonthV16Tests(unittest.TestCase):
    def test_carry_rows_are_not_re_evaluated(self):
        carry = pd.date_range("2026-01-31T23:57:00Z", periods=3, freq="min")
        fresh = pd.date_range("2026-02-01T00:00:00Z", periods=4, freq="min")
        df = pd.DataFrame({"time": list(carry) + list(fresh)})
        idx = first_fresh_index(df, pd.Timestamp("2026-02-01T00:00:00Z"))
        self.assertEqual(idx, 3)
        self.assertTrue((pd.to_datetime(df.iloc[idx:]["time"], utc=True) >= pd.Timestamp("2026-02-01T00:00:00Z")).all())


if __name__ == "__main__":
    unittest.main()
