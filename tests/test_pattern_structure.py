import unittest

import numpy as np
import pandas as pd

from ai_core import candle_structure_signal, enrich_history_core
from learner import score_forecast_outcome


class PatternStructureTests(unittest.TestCase):
    @staticmethod
    def history():
        n = 40
        close = 100.0 + np.linspace(0.0, 2.0, n)
        raw = pd.DataFrame({
            "time": pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC"),
            "open": close - 0.10,
            "high": close + 0.30,
            "low": close - 0.30,
            "close": close,
            "volume": np.full(n, 10.0),
        })
        return raw

    def test_bullish_engulfing_is_recognized(self):
        raw = self.history()
        raw.loc[38, ["open", "close", "high", "low"]] = [102.0, 101.5, 102.1, 101.4]
        raw.loc[39, ["open", "close", "high", "low"]] = [101.4, 102.2, 102.3, 101.3]
        score, reason = candle_structure_signal(enrich_history_core(raw))
        self.assertGreater(score, 0.35)
        self.assertIn("bullish engulfing", reason)

    def test_rejection_wick_is_recognized(self):
        raw = self.history()
        raw.loc[39, ["open", "close", "high", "low"]] = [101.8, 102.0, 102.05, 100.7]
        score, reason = candle_structure_signal(enrich_history_core(raw))
        self.assertGreater(score, 0.20)
        self.assertIn("rejection wick", reason)

    def test_btc_move_and_kalshi_settlement_are_not_mixed(self):
        # BTC rose from 100 to 101, while still settling below a 105 strike.
        outcome = score_forecast_outcome(
            start=100, target=105, predicted_end=104,
            predicted_direction=1, actual=101,
        )
        self.assertEqual(outcome["btc_move_correct"], 1)
        self.assertEqual(outcome["settlement_correct"], 1)
        self.assertEqual(outcome["predicted_settlement_direction"], -1)


if __name__ == "__main__":
    unittest.main()
