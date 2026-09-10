import unittest

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core


class HigherTimeframeV10Tests(unittest.TestCase):
    def test_long_context_is_computed_and_used(self):
        n = 500
        close = 50000.0 + np.linspace(0.0, 2500.0, n)
        raw = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC"),
            "open": close - 2.0,
            "high": close + 8.0,
            "low": close - 8.0,
            "close": close,
            "volume": np.full(n, 10.0),
        })
        hist = enrich_history_core(raw)
        self.assertFalse(pd.isna(hist["ret240"].iloc[-1]))
        self.assertFalse(pd.isna(hist["ema200"].iloc[-1]))
        results = run_specialists_core(hist, pd.DataFrame(), {}, {"available": False})
        self.assertIn("EMA200", results["Trend AI"]["reason"])
        self.assertIn("higher-timeframe", results["Market Regime AI"]["reason"])
        self.assertIn("1h", results["Historical Pattern AI"]["reason"])
        self.assertGreater(results["Trend AI"]["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
