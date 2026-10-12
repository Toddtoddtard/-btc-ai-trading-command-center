import unittest
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import council_backtest_v4 as replay
from council_backtest_v4 import flow_proxy, month_iter


class CouncilBacktestV4Tests(unittest.TestCase):
    def replay_one_forecast(self, results, gap=False, descending=False, source_gap=False):
        times = pd.date_range("2025-01-01T00:01:00Z", periods=75, freq="min")
        if source_gap:
            times = pd.date_range("2025-01-01T00:01:00Z", periods=90, freq="min").delete(29)
        if gap:
            times = times[:-1].append(pd.DatetimeIndex([times[-1] + pd.Timedelta(minutes=1)]))
        prices = [200 - i if descending else 100 + i for i in range(len(times))]
        frame = pd.DataFrame({"time": times, "open": prices, "high": prices,
                              "low": prices, "close": prices, "volume": 1., "qv": 1., "tq": .5})
        original = copy.deepcopy(results)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch.object(replay, "OUT", output), \
                    patch.object(replay, "month_iter", return_value=[(2025, 1)]), \
                    patch.object(replay, "fetch_month", return_value=frame), \
                    patch.object(replay, "enrich_history_core", side_effect=lambda df: df.assign(ema50=1., rsi=50., atr14=1.)), \
                    patch.object(replay, "regime_from_hist", return_value="RANGE"), \
                    patch.object(replay, "run_specialists_core", return_value=results), \
                    patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "too few samples"):
                    replay.main()
            report = json.loads(output.read_text())
        self.assertEqual(results, original)
        return report

    def test_gated_wait_has_no_directional_accuracy(self):
        results = {name: {"score": .08, "confidence": .9}
                   for name in ("Trend AI", "Momentum AI", "Volume AI")}
        report = self.replay_one_forecast(results)
        self.assertEqual(report["overall"]["samples"], 1)
        self.assertEqual(report["overall"]["waits"], 1)
        self.assertIsNone(report["overall"]["direction_accuracy"])
        self.assertIsNone(report["regimes"]["RANGE"]["accuracy"])
        self.assertTrue(all(row["without_bot_accuracy"] is None
                            for row in report["specialist_ablation"]))

    def test_ablation_preserves_original_specialist_confidence(self):
        results = {"Trend AI": {"score": -.8, "confidence": .99},
                   "Momentum AI": {"score": -.8, "confidence": .05},
                   "Volume AI": {"score": -.4, "confidence": .99},
                   "Pattern AI": {"score": .8, "confidence": .05}}
        report = self.replay_one_forecast(results, descending=True)
        row = next(r for r in report["specialist_ablation"] if r["name"] == "Momentum AI")
        self.assertEqual(row.get("without_bot_calls"), 1)
        self.assertEqual(row["without_bot_accuracy"], 1.)

    def test_ablation_compares_wait_using_zero_decision_utility(self):
        results = {"Trend AI": {"score": .4, "confidence": .99},
                   "Momentum AI": {"score": -.5, "confidence": .05},
                   "Volume AI": {"score": .4, "confidence": .99}}
        report = self.replay_one_forecast(results)
        row = next(r for r in report["specialist_ablation"] if r["name"] == "Momentum AI")
        self.assertIsNone(row["full_council_accuracy"])
        self.assertEqual(row["without_bot_accuracy"], 1.)
        self.assertEqual(row["paired_decisions"], 1)
        self.assertEqual(row["harmful_decisions"], 1)
        self.assertEqual(row["marginal_decision_utility"], -1.)
        self.assertIsNone(row["marginal_accuracy"])
        self.assertIn("archived_btc", report["label_basis"])
        self.assertFalse(report["actual_master_execution_replayed"])

    def test_missing_exact_deadline_does_not_borrow_later_price(self):
        results = {name: {"score": .8, "confidence": .9}
                   for name in ("Trend AI", "Momentum AI", "Volume AI")}
        report = self.replay_one_forecast(results, gap=True)
        self.assertEqual(report["overall"]["samples"], 0)
        self.assertEqual(report["missing_deadline_prices"], 1)

    def test_council_warmup_cannot_cross_a_missing_source_minute(self):
        results = {name: {"score": .8, "confidence": .9}
                   for name in ("Trend AI", "Momentum AI", "Volume AI")}
        report = self.replay_one_forecast(results, source_gap=True)
        self.assertEqual(report["overall"]["samples"], 0)

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
