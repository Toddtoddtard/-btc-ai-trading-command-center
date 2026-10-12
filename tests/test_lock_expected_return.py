import tempfile
import time
import unittest
from unittest.mock import patch

import background_paper as bg
import kalshi_paper_engine as engine
from contract_calibration import BASIS


class LockExpectedReturnTests(unittest.TestCase):
    def promotion(self, **updates):
        paper = bg.initial_state(now=1000)
        paper['balance_reset'] = {'id': bg.PAPER_ACCOUNT_RESET_ID}
        paper['open_position'] = dict(ticker='PROMOTE', strategy='SCALP', side='YES',
            status='OPEN', entry_price=.75, contracts=10, amount=7.64,
            entry_fee=.14, last_mark=.5, opened_at=900, expires_at=2000)
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

    def entry(self, side='YES', probability=.80, **updates):
        now = time.time()
        direction = 'UP' if side == 'YES' else 'DOWN'
        decision = dict(action='LOCK '+direction, confidence=.95,
                        kalshi_ticker='LOCK-EDGE', kalshi_close_ts=now+600,
                        contract_probability_up=probability,
                        contract_probability_basis=BASIS, contract_calibrator_active=True,
                        yes_bid_dollars=.49, yes_ask_dollars=.50,
                        no_bid_dollars=.49, no_ask_dollars=.50)
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
