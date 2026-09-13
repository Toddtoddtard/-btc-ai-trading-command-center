import tempfile
import time
import unittest

import kalshi_paper_engine as engine


class SettlementRolloverRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = self.tmp.name + "/paper.db"
        self.risk = {"approved": True, "position_pct": 0.1}
        self.old_ticker = "KXBTC15M-OLD"
        self.new_ticker = "KXBTC15M-NEW"
        self.decision = {
            "action": "SCALP DOWN",
            "kalshi_ticker": self.old_ticker,
            "kalshi_close_ts": time.time() + 900,
            "target_price": 100.0,
            "yes_ask_dollars": 0.35,
            "yes_bid_dollars": 0.33,
            "no_ask_dollars": 0.67,
            "no_bid_dollars": 0.65,
            "confidence": 0.80,
            "scalp_projected_exit_price": 0.80,
        }

    def _open_down_scalp(self):
        opened = engine.open_position(
            self.db, 500.0, self.decision, self.risk, 100.0
        )
        self.assertIsNotNone(opened)
        self.assertTrue(opened["event"])

    def test_rollover_settles_old_market_even_when_expiry_is_stale_future(self):
        self._open_down_scalp()

        # Reproduce the bug: the saved expiration is wrong and still in the future,
        # but the app has already selected the next 15-minute Kalshi ticker.
        with engine._connect(self.db) as conn:
            conn.execute(
                "UPDATE kalshi_paper_positions SET expires_at=? WHERE status='OPEN'",
                (time.time() + 3600,),
            )

        self.decision["kalshi_ticker"] = self.new_ticker
        calls = []

        def settlement_reader(ticker):
            calls.append(ticker)
            return "no"

        result = engine.manage_kalshi_paper_cycle(
            self.db,
            500.0,
            self.decision,
            self.risk,
            999999.0,
            settlement_reader=settlement_reader,
        )

        self.assertTrue(result["event"])
        self.assertEqual(calls, [self.old_ticker])
        summary = engine.paper_summary(self.db)
        self.assertIsNone(summary["open_position"])
        self.assertEqual(summary["samples"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertGreater(summary["realized_pnl"], 0)

        history = engine.paper_history(self.db)
        self.assertEqual(history[0]["status"], "CLOSED")
        self.assertEqual(history[0]["result"], "WIN")
        self.assertEqual(history[0]["current_or_exit_pct"], 100.0)

        with engine._connect(self.db) as conn:
            row = conn.execute(
                "SELECT exit_reason,exit_fee FROM kalshi_paper_positions "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["exit_reason"], "OFFICIAL_SETTLEMENT:no")
        self.assertEqual(row["exit_fee"], 0.0)

    def test_rollover_ends_call_and_waits_as_pending_when_result_not_ready(self):
        self._open_down_scalp()
        self.decision["kalshi_ticker"] = self.new_ticker

        result = engine.manage_kalshi_paper_cycle(
            self.db, 500.0, self.decision, self.risk, 1.0,
            settlement_reader=lambda _: None,
        )

        self.assertTrue(result["event"])
        self.assertIn("Window ended", result["message"])
        summary = engine.paper_summary(self.db)
        self.assertIsNone(summary["open_position"])
        self.assertEqual(summary["pending_settlements"], 1)
        self.assertEqual(summary["samples"], 0)
        row = engine.paper_history(self.db)[0]
        self.assertEqual(row["status"], "PENDING_SETTLEMENT")
        self.assertEqual(row["result"], "PENDING")
        self.assertIsNone(row["pnl"])

    def test_next_market_can_open_while_previous_market_is_pending(self):
        self._open_down_scalp()
        self.decision["kalshi_ticker"] = self.new_ticker
        engine.manage_kalshi_paper_cycle(
            self.db, 500.0, self.decision, self.risk, 1.0,
            settlement_reader=lambda _: None,
        )
        next_decision = dict(self.decision)
        next_decision.update({
            "action": "SCALP UP",
            "kalshi_ticker": self.new_ticker,
            "kalshi_close_ts": time.time() + 900,
            "yes_ask_dollars": 0.40,
            "yes_bid_dollars": 0.38,
            "no_ask_dollars": 0.62,
            "no_bid_dollars": 0.60,
            "scalp_projected_exit_price": 0.60,
        })
        opened = engine.manage_kalshi_paper_cycle(
            self.db, 500.0, next_decision, self.risk, 100.0,
            settlement_reader=lambda _: None,
        )
        self.assertTrue(opened["event"])
        self.assertIn("Opened PAPER SCALP", opened["message"])
        self.assertEqual(engine.paper_summary(self.db)["pending_settlements"], 1)
        self.assertIsNotNone(engine.paper_summary(self.db)["open_position"])

    def test_pending_finalizes_by_its_own_ticker_and_preserves_window_close(self):
        self._open_down_scalp()
        with engine._connect(self.db) as conn:
            expiry = time.time() - 1
            conn.execute(
                "UPDATE kalshi_paper_positions SET expires_at=? WHERE status='OPEN'",
                (expiry,),
            )
            conn.commit()
        engine.manage_kalshi_paper_cycle(
            self.db, 500.0, self.decision, self.risk, 100.0,
            settlement_reader=lambda _: None,
        )
        calls = []
        def official(ticker):
            calls.append(ticker)
            return "no" if ticker == self.old_ticker else None
        engine.manage_kalshi_paper_cycle(
            self.db, 500.0, {"action": "WAIT", "kalshi_ticker": self.new_ticker},
            self.risk, 100.0, settlement_reader=official,
        )
        self.assertIn(self.old_ticker, calls)
        row = engine.paper_history(self.db)[0]
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["result"], "WIN")
        self.assertAlmostEqual(row["closed_at"], expiry, places=3)
        self.assertIsNotNone(row["settled_at"])


if __name__ == "__main__":
    unittest.main()
