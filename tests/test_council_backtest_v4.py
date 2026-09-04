import unittest

import pandas as pd

from council_backtest_v4 import flow_proxy, month_iter


class CouncilBacktestV4Tests(unittest.TestCase):
    def test_month_iter_crosses_year(self):
        self.assertEqual(list(month_iter(2025, 11, 2026, 2)), [(2025, 11), (2025, 12), (2026, 1), (2026, 2)])

    def test_flow_proxy_preserves_quote_volume(self):
        df = pd.DataFrame([
            {"close": 100.0, "qv": 1000.0, "tq": 600.0},
            {"close": 101.0, "qv": 500.0, "tq": 200.0},
        ])
        agg = flow_proxy(df)
        self.assertAlmostEqual(float(agg["notional"].sum()), 1500.0, places=6)
        buy = float(agg.loc[agg.aggressor == "BUY", "notional"].sum())
        sell = float(agg.loc[agg.aggressor == "SELL", "notional"].sum())
        self.assertAlmostEqual(buy, 800.0, places=6)
        self.assertAlmostEqual(sell, 700.0, places=6)


if __name__ == "__main__":
    unittest.main()
