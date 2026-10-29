import json
import tempfile
import time
import unittest
from unittest.mock import patch

import background_paper as bg
import kalshi_paper_engine as engine
from contract_calibration import BASIS
from pro_trade_ticket import build_pro_trade_ticket


class LockExpectedReturnTests(unittest.TestCase):
    def test_lock_validation_policy_uses_distinct_market_thresholds(self):
        collecting = engine.lock_validation_policy(dict(
            markets=99, profit_factor=.20, expectancy=-1, max_drawdown_pct=.50))
        passing = engine.lock_validation_policy(dict(
            markets=100, profit_factor=1.15, expectancy=.01, max_drawdown_pct=.10))
        failing = engine.lock_validation_policy(dict(
            markets=100, profit_factor=1.14, expectancy=.01, max_drawdown_pct=.10))
        self.assertTrue(collecting['approved'])
        self.assertEqual(collecting['status'], 'COLLECTING EVIDENCE')
        self.assertTrue(passing['approved'])
        self.assertEqual(passing['status'], 'VALIDATED PASS')
        self.assertFalse(failing['approved'])
        self.assertEqual(failing['status'], 'VALIDATION QUARANTINE')

    def test_no_loss_mature_scorecard_passes_with_infinite_profit_factor(self):
        paper = bg.initial_state(now=1000)
        paper['trades'] = [
            dict(ticker=f'WIN-{index}', strategy='SCALP', status='CLOSED',
                 opened_at=index, closed_at=500+index, pnl=1.0,
                 entry_fee=.05, exit_fee=.05)
            for index in range(100)
        ]
        metrics, _ = bg.shared_paper_scorecard(paper)
        self.assertEqual(metrics['profit_factor'], float('inf'))
        self.assertTrue(metrics['lock_gate']['approved'])
        self.assertEqual(metrics['lock_gate']['status'], 'VALIDATED PASS')

    def promotion(self, trades=None, **updates):
        paper = bg.initial_state(now=1000)
        paper['balance_reset'] = {'id': bg.PAPER_ACCOUNT_RESET_ID}
        paper['open_position'] = dict(ticker='PROMOTE', strategy='SCALP', side='YES',
            status='OPEN', entry_price=.75, contracts=10, amount=7.64,
            entry_fee=.14, last_mark=.5, opened_at=900, expires_at=2000)
        paper['trades'] = list(trades or [])
        pending = dict(ticker='PROMOTE', master_action='LOCK UP', master_confidence=.95,
            execution_approved=True, contract_probability_up=.60,
            contract_probability_basis=BASIS, contract_calibrator_active=True)
        pending.update(updates)
        return bg.run_cycle(dict(background_paper=paper, pending=pending),
            lambda _: dict(ticker='PROMOTE', status='open', yes_bid_dollars=.5,
                           yes_ask_dollars=.51), now=1000)

    def test_rejected_promotion_retains_scalp_emergency_exit(self):
        for updates in ({'execution_approved': False}, {'execution_approved': None},
                        {'contract_probability_up': None}, {'contract_probability_up': .4},
                        {'contract_calibrator_active': False}):
            with self.subTest(updates=updates):
                paper = self.promotion(**updates)
                self.assertIsNone(paper['open_position'])
                self.assertEqual(paper['trades'][-1]['strategy'], 'SCALP')
                self.assertEqual(paper['trades'][-1]['exit_reason'], 'EMERGENCY_STOP_15_POINTS')

    def test_promotion_compares_settlement_to_liquidation_with_entry_cost_sunk(self):
        paper = self.promotion()
        self.assertEqual(paper['open_position']['strategy'], 'LOCK')

    def test_promotion_requires_five_point_edge_over_executable_liquidation(self):
        paper = self.promotion(contract_probability_up=.53)
        self.assertIsNone(paper['open_position'])
        self.assertEqual(paper['trades'][-1]['strategy'], 'SCALP')

    def test_failed_mature_scorecard_blocks_scalp_to_lock_promotion(self):
        trades = [dict(ticker=f'OLD-{index}', strategy='SCALP', status='CLOSED',
                       opened_at=index, closed_at=500+index, pnl=-1,
                       entry_fee=.05, exit_fee=.05)
                  for index in range(100)]
        paper = self.promotion(trades=trades, contract_probability_up=.90)
        self.assertIsNone(paper['open_position'])
        self.assertEqual(paper['trades'][-1]['strategy'], 'SCALP')

    def entry(self, side='YES', probability=.80, entry=.50, **updates):
        now = time.time()
        direction = 'UP' if side == 'YES' else 'DOWN'
        decision = dict(action='LOCK '+direction, confidence=.95,
                        kalshi_ticker='LOCK-EDGE', kalshi_close_ts=now+600,
                        contract_probability_up=probability,
                        contract_probability_basis=BASIS, contract_calibrator_active=True,
                        yes_bid_dollars=entry-.01, yes_ask_dollars=entry,
                        no_bid_dollars=1-entry, no_ask_dollars=1-(entry-.01))
        decision.update(updates)
        pending = dict(decision, ticker='LOCK-EDGE', expires_at=now+600,
                       master_action=decision['action'], master_confidence=.95,
                       execution_approved=decision.get('execution_approved', True), start_price=100000,
                       predicted_end=101000, target=100000)
        with tempfile.TemporaryDirectory() as tmp:
            opened = engine.open_position(tmp+'/paper.db', 500, decision,
                                          dict(approved=True, position_pct=.02), 100000)
        state = dict(pending=pending)
        paper = bg.run_cycle(state, lambda _: dict(decision, ticker='LOCK-EDGE', status='open'), now=now)
        return bool(opened), paper

    def test_weak_price_adjusted_edge_blocks_both_ledgers_and_preview(self):
        opened, paper = self.entry(probability=.77, entry=.73)
        self.assertFalse(opened)
        self.assertIsNone(paper['open_position'])
        decision = dict(action='LOCK UP', confidence=.95,
                        kalshi_ticker='LOCK-EDGE', kalshi_close_ts=time.time()+600,
                        contract_probability_up=.77,
                        contract_probability_basis=BASIS, contract_calibrator_active=True,
                        yes_bid_dollars=.72, yes_ask_dollars=.73,
                        no_bid_dollars=.27, no_ask_dollars=.28)
        ticket = build_pro_trade_ticket(
            decision, {'approved': True, 'position_pct': .02}, {'cash': 500})
        self.assertEqual(ticket['status'], 'WAIT')
        self.assertTrue(any('safety margin' in blocker for blocker in ticket['blockers']))

    def test_strong_price_adjusted_edge_remains_eligible(self):
        opened, paper = self.entry(probability=.84, entry=.73)
        self.assertTrue(opened)
        self.assertIsNotNone(paper['open_position'])

    def test_failed_mature_scorecard_quarantines_lock_but_keeps_signal(self):
        now = time.time()
        paper = bg.initial_state(now)
        paper['balance_reset'] = {'id': bg.PAPER_ACCOUNT_RESET_ID}
        paper['trades'] = [
            dict(ticker=f'SETTLED-{index}', strategy='SCALP', status='CLOSED',
                 opened_at=now-20000+index, closed_at=now-10000+index,
                 pnl=-1.0, entry_fee=.05, exit_fee=.05)
            for index in range(100)
        ]
        pending = dict(ticker='LOCK-QUARANTINE', expires_at=now+600,
                       opened_at=now, master_action='LOCK UP', master_confidence=.95,
                       execution_approved=True, contract_probability_up=.90,
                       contract_probability_basis=BASIS, contract_calibrator_active=True,
                       start_price=100000, predicted_end=101000, target=100000)
        state = dict(background_paper=paper, pending=pending)
        result = bg.run_cycle(
            state,
            lambda _: dict(ticker='LOCK-QUARANTINE', status='open',
                           yes_bid_dollars=.49, yes_ask_dollars=.50,
                           no_bid_dollars=.49, no_ask_dollars=.50),
            now=now,
        )
        self.assertIsNone(result['open_position'])
        self.assertEqual(result['last_signal']['outcome'], 'BLOCKED')
        self.assertEqual(result['last_signal']['strategy'], 'LOCK')
        self.assertIn('validation quarantine', result['last_message'])
        metrics, _ = bg.shared_paper_scorecard(result)
        self.assertEqual(metrics['lock_gate']['status'], 'VALIDATION QUARANTINE')
        json.dumps(metrics)
        ticket_decision = dict(action='LOCK UP', confidence=.95,
                               kalshi_ticker='LOCK-QUARANTINE', kalshi_close_ts=now+600,
                               contract_probability_up=.90,
                               contract_probability_basis=BASIS, contract_calibrator_active=True,
                               yes_bid_dollars=.49, yes_ask_dollars=.50,
                               no_bid_dollars=.49, no_ask_dollars=.50)
        ticket = build_pro_trade_ticket(
            ticket_decision, {'approved': True, 'position_pct': .02}, {'cash': 500},
            lock_gate=metrics['lock_gate'])
        self.assertEqual(ticket['status'], 'WAIT')
        self.assertTrue(any('validation quarantine' in blocker for blocker in ticket['blockers']))

    def test_nonpositive_expected_settlement_return_blocks_both_ledgers(self):
        for probability in (.50, .51):
            with self.subTest(probability=probability):
                opened, paper = self.entry(probability=probability)
                self.assertFalse(opened)
                self.assertIsNone(paper['open_position'])
                self.assertIn('settlement', paper['last_message'])

    def test_unvalidated_or_missing_probability_cannot_manufacture_lock_edge(self):
        for updates in ({'contract_probability_up': None},
                        {'contract_probability_up': True},
                        {'contract_probability_up': float('nan')},
                        {'contract_probability_up': float('inf')},
                        {'contract_probability_up': 1.1},
                        {'contract_probability_up': -.1},
                        {'contract_probability_basis': 'unvalidated_spot_model'},
                        {'execution_approved': False},
                        {'contract_calibrator_active': False}):
            with self.subTest(updates=updates):
                opened, paper = self.entry(**updates)
                self.assertFalse(opened)
                self.assertIsNone(paper['open_position'])

    def test_positive_validated_return_selects_correct_settlement_side(self):
        for side, probability in (('YES', .8), ('NO', .2)):
            with self.subTest(side=side):
                opened, paper = self.entry(side, probability)
                self.assertTrue(opened)
                self.assertIsNotNone(paper['open_position'])

    def test_invalid_selected_side_quotes_block_both_ledgers(self):
        for updates in ({'yes_bid_dollars': -.01},
                        {'yes_bid_dollars': .60},
                        {'yes_bid_dollars': None},
                        {'yes_ask_dollars': 0},
                        {'yes_ask_dollars': -.1}):
            with self.subTest(updates=updates):
                opened, paper = self.entry(**updates)
                self.assertFalse(opened)
                self.assertIsNone(paper['open_position'])

    def test_sqlite_rechecks_expiry_after_allocation_before_fill(self):
        now = time.time()
        decision = dict(action='LOCK UP', confidence=.95, kalshi_ticker='DELAYED',
                        kalshi_close_ts=now+1, yes_bid_dollars=.49, yes_ask_dollars=.5,
                        contract_probability_up=.8, contract_probability_basis=BASIS,
                        contract_calibrator_active=True)
        clock = [now]
        real_expected = engine.expected_lock_net_pnl

        def delayed_expected(*args):
            clock[0] = now+2
            return real_expected(*args)

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(engine.time, 'time', side_effect=lambda: clock[0]), \
                patch.object(engine, 'expected_lock_net_pnl', side_effect=delayed_expected):
            opened = engine.open_position(tmp+'/paper.db', 500, decision,
                                          dict(approved=True, position_pct=.02), 100000)
            self.assertIsNone(opened)
            summary = engine.paper_summary(tmp+'/paper.db')
            self.assertIsNone(summary['open_position'])
            self.assertEqual(summary['cash'], 500)
