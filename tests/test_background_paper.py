import math
import sys
import types
import unittest

try:
    import kalshi_paper_engine  # noqa: F401
except ModuleNotFoundError:  # Allows this isolated test artifact to run locally.
    stub = types.ModuleType("kalshi_paper_engine")
    stub.LOCK_MIN_CONFIDENCE = .68
    stub.LOCK_TAKE_PROFIT_PRICE = .95
    stub.MAX_ENTRY_PRICE = .75
    stub.MIN_SCALP_MARKET_PROBABILITY = .15
    stub.MAX_LOCKS_PER_MARKET = 1
    stub.MAX_SCALP_LOSSES_PER_MARKET = 2
    stub.MAX_SCALPS_PER_MARKET = 10
    stub.POST_FIX_GATE_TRADES = 50
    stub.POST_FIX_MAX_DRAWDOWN_PCT = .10
    stub.POST_FIX_PROFIT_FACTOR_FLOOR = 1.15
    stub.POST_FIX_VALIDATION_TRADES = 100
    stub.SCALP_MIN_GROSS_RETURN = .05
    stub.SCALP_MIN_REMAINING_EDGE = .01
    stub.SCALP_STOP_LOSS_POINTS = .15
    stub.UNPROVEN_POSITION_CAP = .02
    stub.kalshi_taker_fee = lambda contracts, price: math.ceil(.07 * contracts * price * (1-price) * 100) / 100
    sys.modules["kalshi_paper_engine"] = stub

import background_paper as bg


class BackgroundPaperTests(unittest.TestCase):
    def test_ledger_events_are_idempotent_and_cash_reconciles(self):
        paper = bg.initial_state(now=1000)
        position = {
            "ticker": "KXBTC15M-A", "opened_at": 1000.0,
            "status": "OPEN", "amount": 10.0, "contracts": 20,
        }
        paper["open_position"] = position
        paper["cash"] -= 10.0
        self.assertTrue(bg._record_ledger_event(paper, "OPENED", position, 1000))
        self.assertFalse(bg._record_ledger_event(paper, "OPENED", position, 1001))
        result = bg.reconcile_shared_paper_ledger(paper)
        self.assertTrue(result["ok"])
        paper["cash"] += 1.0
        self.assertFalse(bg.reconcile_shared_paper_ledger(paper)["ok"])

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

    def test_directional_call_can_be_visible_without_unsafe_execution(self):
        state = self.pending(
            master_action="SCALP UP",
            execution_approved=False,
            execution_reason="WAIT — FEED HEALTH",
        )
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNone(paper["open_position"])
        self.assertEqual(paper["last_signal"]["outcome"], "BLOCKED")
        self.assertIn("Directional call published", paper["last_message"])
        self.assertIn("FEED HEALTH", paper["last_message"])

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

    def test_lock_entry_above_75_is_rejected(self):
        state = self.pending(master_confidence=.95, master_action="LOCK UP")
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.84, yes_ask_dollars=.85),
            now=1000,
        )
        self.assertIsNone(paper["open_position"])
        self.assertEqual(paper["last_signal"]["outcome"], "BLOCKED")
        self.assertIn("above the 75%", paper["last_message"])

    def test_lock_entry_at_95_is_rejected(self):
        state = self.pending(master_confidence=.95, master_action="LOCK UP")
        paper = bg.run_cycle(
            state,
            lambda _: self.market(yes_bid_dollars=.94, yes_ask_dollars=.95),
            now=1000,
        )
        self.assertIsNone(paper["open_position"])
        self.assertIn("above the 75%", paper["last_message"])

    def test_lock_first_mode_disables_new_scalps(self):
        state = self.pending()
        state["btc_execution_mode"] = {"auto_scalping_enabled": False}
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertIsNone(paper["open_position"])
        self.assertIn("execution mode", paper["last_message"])

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
        self.assertIn("below the 15% lottery floor", paper["last_message"])
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

    def test_chart_keeps_open_and_pending_entry_markers(self):
        paper = bg.initial_state(now=1000)
        paper["open_position"] = {
            "status": "OPEN", "ticker": "ACTIVE", "side": "YES",
            "strategy": "LOCK", "entry_price": .60, "last_mark": .70,
            "contracts": 10, "entry_fee": .20, "amount": 6.20,
            "opened_at": 1000, "spot_entry_price": 100000,
        }
        open_markers = bg.shared_paper_chart_entries(paper, "ACTIVE")
        self.assertEqual(len(open_markers), 1)
        self.assertEqual(open_markers[0]["spot_entry_price"], 100000)

        ended = dict(paper["open_position"])
        ended.update(
            status="PENDING_SETTLEMENT", closed_at=1100,
            exit_reason="AWAITING_OFFICIAL_SETTLEMENT",
        )
        paper["pending_settlements"] = [ended]
        paper["open_position"] = None
        pending_markers = bg.shared_paper_chart_entries(paper, "ACTIVE")
        self.assertEqual(len(pending_markers), 1)
        self.assertEqual(pending_markers[0]["spot_entry_price"], 100000)

    def test_latest_call_entry_uses_authoritative_selected_side_fill(self):
        paper = bg.initial_state(now=1000)
        paper["trades"] = [{
            "ticker": "OLD", "side": "YES", "strategy": "LOCK",
            "entry_price": .50, "opened_at": 900,
        }]
        paper["open_position"] = {
            "ticker": "NEW", "side": "NO", "strategy": "LOCK",
            "entry_price": .63, "opened_at": 1000,
        }
        entry = bg.latest_shared_call_entry(paper)
        self.assertEqual(entry["ticker"], "NEW")
        self.assertEqual(entry["side"], "NO")
        self.assertEqual(entry["direction"], "DOWN")
        self.assertEqual(entry["kalshi_entry_pct"], 63.0)

    def test_invalid_159_pm_pre_guard_trade_is_voided_without_rewriting_truth(self):
        paper = bg.initial_state(now=1000)
        paper["trades"] = [{
            "status": "CLOSED",
            "ticker": "KXBTC15M-26SEP091400-00",
            "side": "NO",
            "direction": "DOWN",
            "strategy": "SCALP",
            "entry_price": .001,
            "exit_price": 0.0,
            "contracts": 717,
            "entry_fee": .06,
            "amount": .777,
            "pnl": -.777,
            "result": "LOSS",
            "exit_reason": "OFFICIAL_SETTLEMENT:yes",
            "opened_at": 1788976788.0083666,
            "closed_at": 1788979506.8057601,
        }]
        paper["cash"] = bg.SEED_CASH - .777
        paper["signal_attempts"] = [{
            "ticker": "KXBTC15M-26SEP091400-00", "outcome": "OPENED"
        }]

        voided = bg._void_invalid_legacy_paper_trades(paper, now=2000)

        self.assertEqual(voided, ["KXBTC15M-26SEP091400-00"])
        self.assertEqual(paper["trades"][0]["status"], "VOID")
        self.assertEqual(paper["trades"][0]["result"], "VOID")
        self.assertEqual(paper["trades"][0]["pnl"], 0.0)

        self.assertEqual(
            paper["trades"][0]["exit_reason"], "OFFICIAL_SETTLEMENT:yes"
        )
        self.assertEqual(paper["trades"][0]["original_result"], "LOSS")
        self.assertEqual(paper["signal_attempts"][0]["outcome"], "VOIDED")
        self.assertAlmostEqual(paper["cash"], bg.SEED_CASH)
        self.assertEqual(bg.shared_paper_summary(paper)["samples"], 0)
        self.assertEqual(bg.shared_paper_history(paper)[0]["result"], "VOID")
        self.assertEqual(
            bg.shared_paper_chart_entries(
                paper, "KXBTC15M-26SEP091400-00"
            ),
            [],
        )

        self.assertEqual(
            bg._void_invalid_legacy_paper_trades(paper, now=3000), []
        )

        corrected = bg._repair_closed_settlements(
            paper,
            lambda _: {
                "ticker": "KXBTC15M-26SEP091400-00",
                "status": "settled",
                "result": "yes",
            },
            now=3000,
        )
        self.assertEqual(corrected, [])
        self.assertEqual(paper["trades"][0]["result"], "VOID")
        self.assertEqual(paper["trades"][0]["pnl"], 0.0)

    def test_post_fix_reset_starts_at_500_and_carries_verified_win(self):
        paper = bg.initial_state(now=1000)
        paper["legacy_realized_pnl"] = -141.31
        paper["cash"] = 361.83
        paper["trades"] = [{
            "status": "ARCHIVED", "ticker": "KXBTC15M-26SEP101845-45", "side": "NO",
            "strategy": "SCALP", "entry_price": .67, "exit_price": 1.0,
            "contracts": 10, "entry_fee": .16, "amount": 6.86,
            "pnl": 0.0, "original_pnl": 3.14, "result": "ARCHIVED", "opened_at": 1000,
            "closed_at": 1100,
        }]

        changed = bg._reset_paper_account_to_post_fix_500(paper, now=2000)

        self.assertTrue(changed)
        self.assertEqual(paper["starting_cash"], 500.0)
        self.assertEqual(paper["legacy_realized_pnl"], 0.0)
        self.assertEqual(paper["cash"], 503.14)
        self.assertEqual(paper["trades"][0]["status"], "CLOSED")
        self.assertEqual(paper["trades"][0]["result"], "WIN")
        self.assertEqual(paper["trades"][0]["pnl"], 3.14)
        self.assertEqual(paper["trades"][0]["original_pnl"], 3.14)
        self.assertEqual(paper["metrics"]["samples"], 1)
        self.assertEqual(paper["metrics"]["wins"], 1)
        summary = bg.shared_paper_summary(paper)
        self.assertEqual(summary["equity"], 503.14)
        self.assertEqual(summary["total_pnl"], 3.14)
        self.assertEqual(summary["samples"], 1)
        self.assertEqual(bg.shared_paper_history(paper)[0]["result"], "WIN")
        self.assertEqual(len(bg.shared_paper_chart_entries(
            paper, "KXBTC15M-26SEP101845-45"
        )), 1)
        self.assertFalse(bg._reset_paper_account_to_post_fix_500(paper, now=3000))
        self.assertEqual(
            bg._repair_closed_settlements(
                paper,
                lambda _: {"status": "settled", "result": "no"},
                now=5000,
            ),
            [],
        )

    def test_verified_settlement_is_not_refetched_every_cycle(self):
        paper = bg.initial_state(now=1000)
        paper["trades"] = [{
            "status": "CLOSED", "ticker": "OLD", "side": "YES",
            "strategy": "LOCK", "contracts": 10, "amount": 6.0,
            "exit_price": 1.0, "pnl": 4.0, "result": "WIN",
            "exit_reason": "OFFICIAL_SETTLEMENT:yes",
        }]
        calls = []

        def reader(ticker):
            calls.append(ticker)
            return {"ticker": ticker, "status": "settled", "result": "yes"}

        self.assertEqual(bg._repair_closed_settlements(paper, reader, 2000), [])
        self.assertTrue(paper["trades"][0]["settlement_verified"])
        self.assertEqual(bg._repair_closed_settlements(paper, reader, 3000), [])
        self.assertEqual(calls, ["OLD"])

    def test_live_market_timeout_fails_closed_without_crashing_worker(self):
        state = self.pending(master_action="SCALP UP")

        def unavailable(_ticker):
            raise TimeoutError("timed out")

        paper = bg.run_cycle(state, unavailable, now=1000)
        self.assertTrue(paper["worker_ok"])
        self.assertFalse(paper["market_feed_ok"])
        self.assertIsNone(paper["open_position"])
        self.assertIn("temporarily unavailable", paper["last_message"])


if __name__ == "__main__":
    unittest.main()
