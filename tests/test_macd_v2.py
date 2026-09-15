import unittest

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core
from macd_engine import score_macd


def _candles(close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-01-01", periods=len(close), freq="min", tz="UTC"),
            "open": close - np.sign(np.diff(np.r_[close[0], close])) * 2.0,
            "high": close + 12.0,
            "low": close - 12.0,
            "close": close,
            "volume": np.full(len(close), 100.0),
        }
    )


class AdaptiveMacdTests(unittest.TestCase):
    def test_enrichment_adds_standard_and_fast_macd_features(self):
        enriched = enrich_history_core(_candles(np.linspace(100_000, 101_000, 80)))
        expected = {
            "macd",
            "macd_signal",
            "macd_hist",
            "macd_fast",
            "macd_fast_signal",
            "macd_fast_hist",
            "macd_hist_slope",
            "macd_hist_accel",
        }
        self.assertTrue(expected.issubset(enriched.columns))

    def test_adaptive_macd_tracks_clear_direction(self):
        rising = enrich_history_core(_candles(100_000 + np.r_[np.zeros(35), np.linspace(0, 900, 45)]))
        falling = enrich_history_core(_candles(100_000 - np.r_[np.zeros(35), np.linspace(0, 900, 45)]))
        self.assertGreater(score_macd(rising)["score"], 0.12)
        self.assertLess(score_macd(falling)["score"], -0.12)

    def test_flat_market_is_filtered_instead_of_promoted_by_tiny_crosses(self):
        close = 100_000 + np.sin(np.linspace(0, 10 * np.pi, 100)) * 0.20
        view = score_macd(enrich_history_core(_candles(close)))
        self.assertLess(abs(view["score"]), 0.12)
        self.assertTrue("noise filtered" in view["state"] or "neutral" in view["state"])

    def test_core_specialists_use_adaptive_macd_reasoning(self):
        hist = enrich_history_core(_candles(100_000 + np.r_[np.zeros(35), np.linspace(0, 900, 45)]))
        results = run_specialists_core(hist, None, {}, {})
        self.assertIn("adaptive MACD", results["Momentum AI"]["reason"])
        technical_reason = results["FVG / MACD AI"]["reason"]
        self.assertIn("fast hist", technical_reason)
        self.assertIn("MACD score", technical_reason)


if __name__ == "__main__":
    unittest.main()
