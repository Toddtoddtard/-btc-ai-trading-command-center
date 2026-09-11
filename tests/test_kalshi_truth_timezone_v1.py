import time
import unittest
from pathlib import Path

import background_paper as bg


class KalshiTruthTimezoneTests(unittest.TestCase):
    def test_rollover_settles_using_open_positions_own_ticker(self):
        old_ticker = "KXBTC15M-OLD"
        new_ticker = "KXBTC15M-NEW"
        state = {"pending": {"ticker": new_ticker, "would_wait": True}}
        paper = bg.initial_state(now=1000)
        paper["cash"] = 90.0
        paper["open_position"] = {
            "ticker": old_ticker,
            "side": "NO",
            "direction": "DOWN",
            "strategy": "SCALP",
            "status": "OPEN",
            "opened_at": 950.0,
            "expires_at": 5000.0,  # intentionally stale/future
            "entry_price": 0.60,
            "contracts": 10,
            "entry_fee": 0.10,
            "amount": 6.10,
            "last_mark": 0.61,
        }
        state["background_paper"] = paper
        requested = []

        def market_reader(ticker):
            requested.append(ticker)
            self.assertEqual(ticker, old_ticker)
            return {
                "ticker": old_ticker,
                "status": "settled",
                "result": "no",
                "no_bid_dollars": 1.0,
                "no_ask_dollars": 1.0,
            }

        result = bg.run_cycle(state, market_reader=market_reader, now=1100)
        self.assertEqual(requested, [old_ticker])
        self.assertIsNone(result["open_position"])
        self.assertEqual(result["trades"][-1]["result"], "WIN")
        self.assertEqual(result["trades"][-1]["exit_price"], 1.0)
        self.assertEqual(result["trades"][-1]["exit_fee"], 0.0)

    def test_bad_historical_official_settlement_is_repaired(self):
        ticker = "KXBTC15M-REPAIR"
        state = {"pending": {}}
        paper = bg.initial_state(now=1000)
        paper["trades"] = [{
            "ticker": ticker,
            "side": "NO",
            "direction": "DOWN",
            "strategy": "SCALP",
            "status": "CLOSED",
            "opened_at": 900.0,
            "closed_at": 1000.0,
            "expires_at": 980.0,
            "entry_price": 0.40,
            "entry_fee": 0.10,
            "contracts": 10,
            "amount": 4.10,
            "exit_price": 0.0,
            "exit_fee": 0.0,
            "pnl": -4.10,
            "result": "LOSS",
            "last_mark": 0.0,
            "exit_reason": "OFFICIAL_SETTLEMENT:yes",
        }]
        paper["balance_reset"] = {"id": bg.PAPER_ACCOUNT_RESET_ID}
        state["background_paper"] = paper

        def market_reader(requested):
            self.assertEqual(requested, ticker)
            return {"ticker": ticker, "status": "finalized", "result": "no"}

        result = bg.run_cycle(state, market_reader=market_reader, now=1100)
        trade = result["trades"][0]
        self.assertEqual(trade["result"], "WIN")
        self.assertEqual(trade["exit_price"], 1.0)
        self.assertAlmostEqual(trade["pnl"], 5.90)
        self.assertEqual(trade["correction_reason"], "REFETCHED_OWN_KALSHI_TICKER")

    def test_master_learning_credit_is_restored_once(self):
        ticker = "KXBTC15M-CREDIT"
        state = {
            "forecast": {"direction_hits": 10},
            "reward_system": {"master_points": 5.0},
            "master_history": [{
                "ticker": ticker,
                "direction_correct": 0,
                "time_reward": -1.5,
                "reward_magnitude": 1.5,
            }],
            "background_paper": {
                "trades": [{
                    "ticker": ticker,
                    "result": "WIN",
                    "exit_reason": "OFFICIAL_SETTLEMENT:no",
                }]
            },
        }
        repaired = bg._repair_master_learning_credit(state, [ticker])
        self.assertEqual(repaired, 1)
        self.assertEqual(state["master_history"][0]["direction_correct"], 1)
        self.assertEqual(state["master_history"][0]["time_reward"], 1.5)
        self.assertEqual(state["forecast"]["direction_hits"], 11)
        self.assertAlmostEqual(state["reward_system"]["master_points"], 8.0)
        self.assertEqual(bg._repair_master_learning_credit(state, [ticker]), 0)
        self.assertAlmostEqual(state["reward_system"]["master_points"], 8.0)

    def test_source_grades_kalshi_calls_against_target_and_displays_eastern(self):
        learner = Path("learner.py").read_text(encoding="utf-8")
        app = Path("app.py").read_text(encoding="utf-8")
        self.assertIn("actual_direction = 1 if actual >= target else -1", learner)
        self.assertIn('action in {"SCALP UP", "LOCK UP"}', app)
        self.assertIn('tz_convert("America/New_York")', app)
        self.assertIn("ZoneInfo('America/New_York')", app)


if __name__ == "__main__":
    unittest.main()
