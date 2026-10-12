import unittest

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core


def _candles(close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "open": close,
        "high": close + 5.0,
        "low": close - 5.0,
        "close": close,
        "volume": np.full(len(close), 100.0),
    })


class IndicatorBoundaryTests(unittest.TestCase):
    def test_rsi_one_way_and_flat_boundaries_preserve_first_row_warmup(self):
        for step, expected in ((10.0, 100.0), (-10.0, 0.0), (0.0, 50.0)):
            with self.subTest(step=step):
                hist = enrich_history_core(_candles(100_000 + np.arange(80) * step))
                self.assertTrue(pd.isna(hist["rsi"].iloc[0]))
                np.testing.assert_allclose(hist["rsi"].iloc[1:], expected)

    def test_momentum_uses_rising_rsi_instead_of_neutral_fallback(self):
        hist = enrich_history_core(_candles(100_000 + np.arange(80) * 10.0))
        momentum = run_specialists_core(hist, None, {}, {})["Momentum AI"]
        self.assertIn("RSI 100.0", momentum["reason"])
        self.assertEqual(momentum["signal"], "BULLISH")
        # MACD alone contributes at most 0.45; RSI must also participate.
        self.assertGreater(momentum["score"], 0.45)

    def test_momentum_uses_falling_rsi_and_keeps_flat_history_neutral(self):
        for step, expected_rsi, signal in ((-10.0, 0.0, "BEARISH"), (0.0, 50.0, "NEUTRAL")):
            with self.subTest(step=step):
                hist = enrich_history_core(_candles(100_000 + np.arange(80) * step))
                momentum = run_specialists_core(hist, None, {}, {})["Momentum AI"]
                self.assertIn(f"RSI {expected_rsi:.1f}", momentum["reason"])
                self.assertEqual(momentum["signal"], signal)
                if step < 0:
                    self.assertLess(momentum["score"], -0.45)
                else:
                    self.assertEqual(momentum["score"], 0.0)

    def test_mixed_returns_keep_wilder_ewm_rsi(self):
        hist = enrich_history_core(_candles([100_000, 100_014, 100_000]))
        self.assertAlmostEqual(hist["rsi"].iloc[-1], 100 * 13 / 14)


if __name__ == "__main__":
    unittest.main()
