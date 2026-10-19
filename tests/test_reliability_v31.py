import unittest
from contextlib import ExitStack
from unittest.mock import patch

import pandas as pd
import learner
import background_paper
from contract_calibration import BASIS

from learner_v3 import ensure_v3
from learner_v31 import _historical_expiry_frame, challenger_qualifies, current_shadow_call, refresh_pending_lock_focus
from reliability_v31 import (
    calibrate_confidence,
    exact_expiry_row,
    execution_cost_bps,
    learned_policy,
    learned_trade_gate,
    regime_specialist_weight,
)


class ReliabilityTests(unittest.TestCase):
    def test_locked_veto_marks_pending_waiting_without_rewriting_original_call(self):
        pending = self.locked_pending()
        pending['would_wait'] = False
        live = dict(ticker='X', opened_at=1500, master_action='LOCK DOWN',
                    execution_approved=True, execution_reason='LOCK DOWN')
        refresh_pending_lock_focus({'pending': pending}, live, {'ticker': 'X'})
        self.assertTrue(pending['would_wait'])
        self.assertFalse(pending['execution_approved'])
        self.assertEqual(pending['master_action'], 'LOCK UP')
        # Independent current evidence must not be relabeled as the old LOCK.
        self.assertEqual(live['master_action'], 'LOCK DOWN')

    def locked_pending(self):
        return dict(ticker="X", expires_at=2000, opened_at=1000,
                    master_action="LOCK UP", predicted_direction=1,
                    lock_called_at=1100, lock_called_seconds_remaining=900,
                    start_price=100, predicted_end=102, target=100,
                    forecast_path=[{"close": 102}], master_confidence=.95,
                    master_base_score=.5, execution_approved=True,
                    contract_probability_up=.9, contract_probability_basis=BASIS,
                    contract_calibrator_active=True)

    def test_locked_call_refreshes_current_veto_and_probability_before_paper_entry(self):
        pending = self.locked_pending()
        state = {"pending": pending}
        live = dict(ticker="X", opened_at=1500, master_action="WAIT",
                    execution_approved=False, execution_reason="CURRENT_VETO",
                    contract_probability_up=.2, contract_probability_basis=BASIS,
                    contract_calibrator_active=True)
        refresh_pending_lock_focus(state, live, {"ticker": "X"})
        self.assertEqual(pending["contract_probability_up"], .2)
        self.assertFalse(pending["execution_approved"])
        self.assertEqual(pending["execution_checked_at"], 1500)
        self.assertEqual(pending["execution_reason"], "CURRENT_VETO")
        paper = background_paper.run_cycle(state, lambda _: {
            "ticker": "X", "status": "open", "yes_bid": .59, "yes_ask": .60,
            "no_bid": .39, "no_ask": .40,
        }, now=1500)
        self.assertIsNone(paper["open_position"])

    def test_opposite_fresh_approval_cannot_authorize_original_lock_side(self):
        pending = self.locked_pending()
        before = dict(pending)
        live = dict(ticker="X", opened_at=1500, master_action="LOCK DOWN",
                    execution_approved=True, execution_reason="APPROVED_DOWN",
                    master_confidence=.99, master_base_score=-.9,
                    contract_probability_up=.2, contract_probability_basis=BASIS,
                    contract_calibrator_active=True)
        refresh_pending_lock_focus({"pending": pending}, live, {"ticker": "X"})
        self.assertFalse(pending["execution_approved"])
        self.assertIn("DIRECTION", pending["execution_reason"])
        for key in ("master_action", "predicted_direction", "opened_at", "expires_at",
                    "lock_called_at", "lock_called_seconds_remaining", "start_price",
                    "predicted_end", "target", "forecast_path", "master_confidence", "master_base_score"):
            self.assertEqual(pending[key], before[key], key)

    def test_unavailable_fresh_evaluation_cannot_fill_old_unfilled_lock(self):
        for live, market in ((None, None), (None, {"ticker": "X"}),
                             ({"ticker": "OTHER", "execution_approved": True}, {"ticker": "X"}),
                             ({"ticker": "OTHER", "execution_approved": True}, {"ticker": "OTHER"})):
            with self.subTest(live=live, market=market):
                pending = self.locked_pending()
                original = dict(pending)
                state = {"pending": pending}
                with patch("learner_v31.time.time", return_value=1500):
                    self.assertFalse(refresh_pending_lock_focus(state, live, market))
                self.assertFalse(pending["execution_approved"])
                self.assertEqual(pending["execution_checked_at"], 1500)
                self.assertIn("UNAVAILABLE", pending["execution_reason"])
                for key in ("master_action", "opened_at", "lock_called_at", "forecast_path",
                            "predicted_end", "contract_probability_up"):
                    self.assertEqual(pending[key], original[key], key)
                paper = background_paper.run_cycle(state, lambda _: {
                    "ticker": "X", "status": "open", "yes_bid": .59, "yes_ask": .60,
                    "no_bid": .39, "no_ask": .40,
                }, now=1500)
                self.assertIsNone(paper["open_position"])

    def shadow_dependencies(self, stack):
        for name in ("aggregate_trades", "futures_snapshot", "kalshi_context", "run_specialists_core"):
            stack.enter_context(patch("learner_v31.legacy." + name, return_value={}))
        stack.enter_context(patch("learner_v31.legacy.rows_for_forecast", return_value=[]))
        stack.enter_context(patch("learner_v31.forecast_path_core", return_value={"predicted_end": 102, "predicted_direction": 1}))
        stack.enter_context(patch("learner_v31.knowledge_council_vote", return_value={
            "confidence": .8, "base_score": .5, "precision_gate_passed": True,
        }))

    def test_shadow_unavailable_probability_is_not_zero_percent_yes(self):
        frame = pd.DataFrame({"close": [100.0]})
        market = {"ticker": "TEST", "target": 100.0, "expires_at": 2000, "prob": None}
        with ExitStack() as stack:
            self.shadow_dependencies(stack)
            stack.enter_context(patch("learner_v31.time.time", return_value=1000))
            terminal = stack.enter_context(patch("learner_v31.terminal_above_probability", return_value={"probability_up": None}))
            call = current_shadow_call({"forecast": {}}, frame, market)
        self.assertIsNone(terminal.call_args.kwargs["market_probability"])
        self.assertIsNone(call["contract_probability_up"])
        self.assertIsNone(call["contract_probability_edge"])
        self.assertIsNone(call["strike_distance_sigma"])
        self.assertEqual(call["lock_focus"]["direction"], "UP")

    def test_shadow_rejects_expired_market_before_fetching(self):
        with ExitStack() as stack:
            self.shadow_dependencies(stack)
            stack.enter_context(patch("learner_v31.time.time", return_value=1000))
            fetch = stack.enter_context(patch("learner_v31.legacy.aggregate_trades", return_value={}))
            self.assertIsNone(current_shadow_call({}, pd.DataFrame({"close": [100.0]}), {"expires_at": 1000}))
        fetch.assert_not_called()

    def test_shadow_rechecks_expiry_after_fetching(self):
        with ExitStack() as stack:
            self.shadow_dependencies(stack)
            stack.enter_context(patch("learner_v31.time.time", side_effect=[990.0, 1000.0, 1000.0]))
            call = current_shadow_call({}, pd.DataFrame({"close": [100.0]}), {"expires_at": 1000})
        self.assertIsNone(call)

    def test_registration_rejects_expired_market_before_fetching(self):
        with patch.object(learner.time, "time", return_value=1000), patch.object(learner, "aggregate_trades") as fetch:
            self.assertFalse(learner.register({}, None, {"expires_at": 1000}))
            fetch.assert_not_called()

    def test_registration_rechecks_deadline_after_fetching(self):
        for finished_at in (999.0, 1000.0, 1000.947662):
            with self.subTest(finished_at=finished_at):
                state = {"forecast": {}}
                frame = pd.DataFrame({"close": [100.0]})
                market = {"ticker": "TEST", "target": 100.0, "expires_at": 1000.0}
                forecast = {"inputs": {"ret3": 0, "ret8": 0, "ret15": 0}, "predicted_end": 101, "predicted_direction": 1, "forecast": []}
                with patch.object(learner.time, "time", side_effect=[990.0, finished_at]), patch.object(learner, "aggregate_trades", return_value={}), patch.object(learner, "futures_snapshot", return_value={}), patch.object(learner, "run_specialists_core", return_value={}), patch.object(learner, "kalshi_context", return_value={}), patch.object(learner, "rows_for_forecast", return_value=[]), patch.object(learner, "forecast_path_core", return_value=forecast):
                    self.assertEqual(learner.register(state, frame, market), finished_at < 1000.0)
                if finished_at < 1000.0:
                    self.assertEqual(state["pending"]["opened_at"], finished_at)
                else:
                    self.assertNotIn("pending", state)

    def test_execution_cost_positive(self):
        self.assertAlmostEqual(execution_cost_bps(10000), 6.5, places=6)

    def test_round_trip_cost_is_thirteen_bps(self):
        self.assertAlmostEqual(execution_cost_bps(10000) * 2, 13.0, places=6)

    def test_exact_expiry_rejects_stale(self):
        now = pd.Timestamp("2026-09-04T12:00:00Z")
        df = pd.DataFrame({"time": [now], "close": [100.0]})
        self.assertIsNone(exact_expiry_row(df, (now + pd.Timedelta(minutes=5)).timestamp(), 75))

    def test_exact_expiry_uses_candle_that_closed_at_expiry(self):
        expiry = pd.Timestamp("2026-09-04T12:15:00Z")
        df = pd.DataFrame({
            "time": [expiry - pd.Timedelta(minutes=1), expiry],
            "close": [100.0, 999.0],
        })
        row = exact_expiry_row(df, expiry.timestamp(), 75)
        self.assertEqual(float(row["close"]), 100.0)

    def test_exact_expiry_rejects_future_candle(self):
        expiry = pd.Timestamp("2026-09-04T12:15:00Z")
        df = pd.DataFrame({"time": [expiry + pd.Timedelta(seconds=40)], "close": [999.0]})
        self.assertIsNone(exact_expiry_row(df, expiry.timestamp(), 75))

    def test_stale_expiry_fetches_the_candle_ending_at_expiry(self):
        expiry = pd.Timestamp("2026-09-04T12:15:00Z")
        open_ms = int((expiry - pd.Timedelta(minutes=1)).timestamp() * 1000)
        kline = [open_ms, "99", "102", "98", "101", "1", open_ms + 59999, "1", 1, "1", "1", "0"]
        with patch("learner_v31.legacy.get", return_value=[kline]) as mocked:
            frame = _historical_expiry_frame(expiry.timestamp())
        self.assertEqual(float(exact_expiry_row(frame, expiry.timestamp(), 75)["close"]), 101.0)
        params = mocked.call_args.args[1]
        self.assertEqual(params["startTime"], open_ms)
        self.assertEqual(params["endTime"], int(expiry.timestamp() * 1000) - 1)

    def test_old_state_gets_history_for_every_current_specialist(self):
        state = {"forecast": {}, "specialists": {}, "specialist_history": {}}
        ensure_v3(state)
        self.assertIn("Political Event Watch AI", state["specialist_history"])
        self.assertEqual(state["specialist_history"]["Political Event Watch AI"], [])
        self.assertIn("Cross-Market Research AI", state["specialist_history"])
        self.assertEqual(state["specialist_history"]["Cross-Market Research AI"], [])

    def test_regime_weight_shrinks_small_sample(self):
        state = {"adaptive_weight": 1.2, "regimes": {"RANGE": {"samples": 2, "adaptive_weight": 0.5}}}
        w = regime_specialist_weight(1.0, state, "RANGE")
        self.assertGreater(w, 0.5)
        self.assertLess(w, 1.2)

    def test_bad_calibration_reduces_confidence(self):
        policy = learned_policy({}, "UNKNOWN")
        good = calibrate_confidence(0.75, 0.6, policy, 1.0, {"confidence_model": {"brier_ewma": 0.18}})
        bad = calibrate_confidence(0.75, 0.6, policy, 1.0, {"confidence_model": {"brier_ewma": 0.38}})
        self.assertLess(bad, good)

    def test_trade_gate_blocks_bad_feed(self):
        policy = learned_policy({}, "UNKNOWN")
        allowed, reason = learned_trade_gate("SCALP UP", 0.9, 0.5, 0.8, policy, source_health=0.5)
        self.assertFalse(allowed)
        self.assertIn("FEED", reason)

    def test_trade_gate_blocks_conflict(self):
        policy = learned_policy({}, "UNKNOWN")
        allowed, reason = learned_trade_gate("SCALP DOWN", 0.9, -0.5, 0.05, policy, source_health=1.0)
        self.assertFalse(allowed)
        self.assertIn("CONFLICT", reason)

    def test_lock_gate_uses_shared_sixty_eight_percent_confidence_floor(self):
        policy = learned_policy({}, "UNKNOWN")
        self.assertEqual(policy["lock_confidence_floor"], .68)
        denied, _ = learned_trade_gate("LOCK UP", .679, .5, .8, policy, source_health=1.0)
        allowed, action = learned_trade_gate("LOCK UP", .68, .5, .8, policy, source_health=1.0)
        self.assertFalse(denied)
        self.assertTrue(allowed)
        self.assertEqual(action, "LOCK UP")

    def test_challenger_cannot_promote_on_small_sample(self):
        champ = {"samples": 19, "accuracy": 0.50, "median_error": 100.0}
        challenger = {"samples": 19, "accuracy": 0.80, "median_error": 60.0}
        self.assertFalse(challenger_qualifies(champ, challenger))

    def test_challenger_requires_five_point_accuracy_margin(self):
        champ = {"samples": 25, "accuracy": 0.60, "median_error": 100.0}
        challenger = {"samples": 25, "accuracy": 0.64, "median_error": 80.0}
        self.assertFalse(challenger_qualifies(champ, challenger))
        challenger["accuracy"] = 0.66
        self.assertTrue(challenger_qualifies(champ, challenger))

    def test_challenger_cannot_buy_accuracy_with_bad_error(self):
        champ = {"samples": 25, "accuracy": 0.55, "median_error": 100.0}
        challenger = {"samples": 25, "accuracy": 0.70, "median_error": 111.0}
        self.assertFalse(challenger_qualifies(champ, challenger))


if __name__ == "__main__":
    unittest.main()
