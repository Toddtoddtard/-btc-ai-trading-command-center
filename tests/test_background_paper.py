import math
import sys
import types
import unittest

try:
    import kalshi_paper_engine  # noqa: F401
except ModuleNotFoundError:  # Allows this isolated test artifact to run locally.
    stub = types.ModuleType("kalshi_paper_engine")
    stub.LOCK_MIN_CONFIDENCE = .95
    stub.LOCK_TAKE_PROFIT_PRICE = .95
    stub.MAX_ENTRY_PRICE = .75
    stub.MIN_SCALP_MARKET_PROBABILITY = .20
    stub.MAX_LOCKS_PER_MARKET = 1
    stub.MAX_SCALP_LOSSES_PER_MARKET = 2
    stub.MAX_SCALPS_PER_MARKET = 10
    stub.POST_FIX_GATE_TRADES = 50
    stub.POST_FIX_MAX_DRAWDOWN_PCT = .10
    stub.POST_FIX_PROFIT_FACTOR_FLOOR = 1.15
    stub.POST_FIX_VALIDATION_TRADES = 100
    stub.SCALP_MIN_GROSS_RETURN = .10
    stub.SCALP_MIN_REMAINING_EDGE = .01
    stub.SCALP_STOP_LOSS_POINTS = .15
    stub.UNPROVEN_POSITION_CAP = .02
    stub.kalshi_taker_fee = lambda contracts, price: math.ceil(.07 * contracts * price * (1-price) * 100) / 100
    sys.modules["kalshi_paper_engine"] = stub

import background_paper as bg


class BackgroundPaperTests(unittest.TestCase):
    def pending(self, **updates):
        p = {"ticker": "KXBTC15M-TEST", "expires_at": 2000, "start_price": 100000, "predicted_end": 100300, "target": 100000, "predicted_direction": 1, "master_confidence": .70, "would_wait": False}
        p.update(updates)
        return {"pending": p}

    @staticmethod
    def market(**updates):
        m = {"ticker": "KXBTC15M-TEST", "status": "open", "yes_bid_dollars": .48, "yes_ask_dollars": .50, "no_bid_dollars": .50, "no_ask_dollars": .52}
        m.update(updates)
        return m

    def test_wait_never_opens(self):
        state = self.pending(would_wait=True)
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNone(paper["open_position"])

    def test_scalp_entry_above_75_is_rejected(self):
        state = self.pending()
        paper = bg.run_cycle(state, lambda _: self.market(yes_bid_dollars=.75, yes_ask_dollars=.76), now=1000)
        self.assertIsNone(paper["open_position"])
        self.assertIn("above the 75%", paper["last_message"])

    def test_blocked_signal_remains_visible_after_later_wait(self):
        state = self.pending()
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.75, yes_ask_dollars=.76),
            now=1000,
        )
        self.assertEqual(paper["last_signal"]["outcome"], "BLOCKED")
        self.assertIn("above the 75%", paper["last_signal_message"])
        state["pending"]["would_wait"] = True
        paper = bg.run_cycle(state, lambda _: self.market(), now=1001)
        self.assertEqual(paper["last_message"], "No paper action: learner selected WAIT.")
        self.assertIn("above the 75%", paper["last_signal_message"])
        self.assertEqual(len(paper["signal_attempts"]), 1)

    def test_final_lock_may_enter_above_75(self):
        state = self.pending(master_confidence=.95)
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.84, yes_ask_dollars=.85),
            now=1000,
        )
        self.assertIsNotNone(paper["open_position"])
        self.assertEqual(paper["open_position"]["strategy"], "LOCK")
        self.assertEqual(paper["open_position"]["entry_price"], .85)
        self.assertEqual(paper["last_signal"]["outcome"], "OPENED")

    def test_lock_rejects_fee_loss_at_95_exit(self):
        state = self.pending(master_confidence=.95)
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.94, yes_ask_dollars=.95),
            now=1000,
        )
        self.assertIsNone(paper["open_position"])
        self.assertIn("after estimated Kalshi fees", paper["last_message"])

    def test_lottery_style_low_probability_scalp_is_rejected(self):
        state = self.pending()
        paper = bg.run_cycle(
            state,
            lambda _: self.market(
                yes_bid_dollars=0.0,
                yes_ask_dollars=.001,
                no_bid_dollars=.999,
                no_ask_dollars=1.0,
            ),
            now=1000,
        )
        self.assertIsNone(paper["open_position"])
        self.assertIn("below the 20% lottery floor", paper["last_message"])
        self.assertEqual(paper["last_signal"]["outcome"], "BLOCKED")

    def test_qualifying_scalp_opens_and_takes_profit(self):
        state = self.pending()
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNotNone(paper["open_position"])
        state["pending"]["would_wait"] = True
        paper = bg.run_cycle(state, lambda _: self.market(yes_bid_dollars=.65, yes_ask_dollars=.67), now=1010)
        self.assertIsNone(paper["open_position"])
        self.assertEqual(paper["metrics"]["samples"], 1)
        self.assertGreater(paper["metrics"]["total_pnl"], 0)

    def test_profitable_scalp_holds_while_ai_sees_more_upside(self):
        state = self.pending(predicted_end=101000)
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNotNone(paper["open_position"])
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.55, yes_ask_dollars=.57),
            now=1010,
        )
        self.assertIsNotNone(paper["open_position"])
        self.assertIn("Holding PAPER SCALP", paper["last_message"])

    def test_scalp_exits_early_on_ai_confirmed_reversal(self):
        state = self.pending()
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNotNone(paper["open_position"])
        state["pending"].update(predicted_direction=-1, predicted_end=99000)
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.47, yes_ask_dollars=.49),
            now=1010,
        )
        self.assertIsNone(paper["open_position"])
        self.assertEqual(paper["trades"][-1]["exit_reason"], "AI_CONFIRMED_REVERSAL")

    def test_wide_spread_does_not_block_entry(self):
        state = self.pending()
        paper = bg.run_cycle(state, lambda _: self.market(yes_bid_dollars=.40, yes_ask_dollars=.50), now=1000)
        self.assertIsNotNone(paper["open_position"])

    def test_shared_dashboard_summary_includes_legacy_and_open_pnl(self):
        paper = bg.initial_state(now=1000)
        paper["legacy_realized_pnl"] = -10.0
        paper["trades"] = [{"status": "CLOSED", "pnl": 2.0}]
        paper["open_position"] = {
            "status": "OPEN", "ticker": "TEST", "side": "YES",
            "strategy": "SCALP", "entry_price": .50, "last_mark": .60,
            "contracts": 10, "entry_fee": .20, "amount": 5.20,
            "opened_at": 1000,
        }
        summary = bg.shared_paper_summary(paper)
        expected_open = 6.0 - bg.kalshi_taker_fee(10, .60) - 5.20
        self.assertAlmostEqual(summary["realized_pnl"], -8.0)
        self.assertAlmostEqual(summary["unrealized_pnl"], expected_open)
        self.assertAlmostEqual(summary["equity"], 500.0 - 8.0 + expected_open)
        self.assertEqual(summary["ledger_source"], "github-learning-state")

    def test_shared_dashboard_history_and_chart_use_same_ledger(self):
        paper = bg.initial_state(now=1000)
        paper["trades"] = [{
            "status": "CLOSED", "ticker": "TEST", "side": "YES",
            "direction": "UP", "strategy": "SCALP", "entry_price": .50,
            "exit_price": .65, "contracts": 10, "entry_fee": .20,
            "amount": 5.20, "pnl": 1.10, "opened_at": 1000,
            "closed_at": 1010, "spot_entry_price": 100000,
        }]
        history = bg.shared_paper_history(paper)
        markers = bg.shared_paper_chart_entries(paper, "TEST")
        self.assertEqual(history[0]["ticker"], "TEST")
        self.assertEqual(history[0]["result"], "WIN")
        self.assertEqual(markers[0]["kalshi_entry_pct"], 50.0)
        self.assertEqual(markers[0]["spot_entry_price"], 100000)


if __name__ == "__main__":
    unittest.main()
