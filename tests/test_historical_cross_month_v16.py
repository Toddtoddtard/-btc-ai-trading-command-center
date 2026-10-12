import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import historical_specialist_backtest_v7 as replay
import historical_backtest as archive
import council_backtest_v4 as council_replay

from historical_specialist_backtest_v7 import (
    first_fresh_index,
    historical_council_score,
    qualified_council_score,
)
from specialist_knowledge_v5 import specialist_posterior


class HistoricalCrossMonthV16Tests(unittest.TestCase):
    def test_archive_replays_share_validated_parser(self):
        for module in (replay, council_replay):
            self.assertIs(module.fetch_month, archive.fetch_month)
            self.assertIs(module.month_iter, archive.month_iter)
            self.assertIs(module.month_url, archive.month_url)

    def run_archive(self, times, split=None):
        frame = pd.DataFrame({"time": times, "open": 100., "high": 101.,
                              "low": 99., "close": range(100, 100 + len(times)), "volume": 1.})
        frames = [frame] if split is None else [frame.iloc[:split], frame.iloc[split:]]
        months = [(2026, i + 1) for i in range(len(frames))]
        results = {name: {"score": .8, "confidence": .9}
                   for name in ("Trend AI", "Momentum AI", "Volume AI")}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch.object(replay, "OUT", output), \
                    patch.object(replay, "month_iter", return_value=months), \
                    patch.object(replay, "fetch_month", side_effect=frames), \
                    patch.object(replay, "enrich_history_core", side_effect=lambda df: df.assign(
                        ema50=1., ema200=1., ret60=.1, ret240=.1, rsi=50., atr14=1.)), \
                    patch.object(replay, "detect_regime", return_value="RANGE"), \
                    patch.object(replay, "run_specialists_core", return_value=results), \
                    patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "too few windows"):
                    replay.main()
            return json.loads(output.read_text())

    def test_missing_deadline_cannot_be_replaced_by_next_minute(self):
        times = pd.date_range("2026-01-01T00:00:00Z", periods=257, freq="min").delete(255)
        report = self.run_archive(times)
        self.assertEqual(report["evaluated_windows"], 0)
        self.assertEqual(report["stale_windows_discarded"], 1)

    def test_missing_source_minute_prevents_ret240_replay(self):
        times = pd.date_range("2026-01-01T00:00:00Z", periods=271, freq="min").delete(120)
        report = self.run_archive(times)
        self.assertEqual(report["evaluated_windows"], 0)

    def test_contiguous_month_carry_preserves_one_forecast(self):
        times = pd.date_range("2026-01-31T20:00:00Z", periods=257, freq="min")
        report = self.run_archive(times, split=240)
        self.assertEqual(report["evaluated_windows"], 1)
        self.assertEqual(report["specialists"]["Trend AI"]["samples"], 1)

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
