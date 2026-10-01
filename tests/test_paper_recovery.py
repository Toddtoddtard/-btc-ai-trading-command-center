import unittest
from unittest.mock import patch

import background_paper as bg
import kalshi_paper_engine as engine


class PaperRecoveryTests(unittest.TestCase):
    def state(self):
        paper = bg.initial_state(now=1000)
        # Isolate current fills from legacy reset/settlement repair fixtures.
        paper['trades'] = [dict(ticker=f'TEST-{i}', strategy='SCALP', status='CLOSED',
                                opened_at=100+i, closed_at=101+i, pnl=(1.08 if i % 2 else -1),
                                entry_fee=.02, exit_fee=.02) for i in range(50)]
        paper['cash'] = 502.0
        return {'background_paper': paper, 'pending': dict(
            ticker='KXBTC15M-RECOVERY', expires_at=2000, opened_at=900,
            master_action='SCALP UP', master_confidence=.65, execution_approved=True,
            start_price=100000, target=100000, predicted_end=100300)}

    def run_cycle(self, state, now=1000, market=None):
        market = market or dict(ticker='KXBTC15M-RECOVERY', status='open',
                               yes_bid_dollars=.48, yes_ask_dollars=.50)
        with patch.object(bg, '_reset_paper_account_to_post_fix_500'), patch.object(bg, '_repair_closed_settlements', return_value=[]):
            return bg.run_cycle(state, lambda _: market, now=now)

    def test_probation_opens_small_fill_and_keeps_ledger_history(self):
        state = self.state()
        paper = self.run_cycle(state)
        self.assertEqual(paper['gate']['status'], 'PAPER RECOVERY')
        self.assertEqual(len(paper['trades']), 50)
        self.assertIsNotNone(paper['open_position'])
        self.assertLessEqual(paper['open_position']['amount'], 502 * .005)
        self.assertEqual(paper['open_position']['risk_mode'], 'PAPER RECOVERY')

    def test_recovery_cannot_reenter_same_market_even_after_rearm(self):
        state = self.state()
        paper = self.run_cycle(state)
        pos = paper['open_position']
        bg._close(paper, pos, .55, 'TEST', 1001)
        paper['rearm']['KXBTC15M-RECOVERY:YES'] = True
        self.run_cycle(state, now=1002)
        self.assertIsNone(paper['open_position'])
        self.assertIn('per-market limit', paper['last_message'])

    def test_recovery_preserves_feed_approval_and_uses_net_edge(self):
        state = self.state()
        state['pending'].update(execution_approved=False, execution_reason='WAIT — CALIBRATION')
        paper = self.run_cycle(state)
        self.assertIsNone(paper['open_position'])
        self.assertIn('CALIBRATION', paper['last_message'])
        state['pending']['execution_approved'] = True
        paper = self.run_cycle(state, market=dict(ticker='KXBTC15M-RECOVERY', status='open',
                                                 yes_bid_dollars=.75, yes_ask_dollars=.76))
        self.assertIsNotNone(paper['open_position'])
        self.assertLessEqual(paper['open_position']['amount'], 502 * .005)

    def test_expired_closed_and_missing_expiry_cannot_open(self):
        for expiry, status in [(999, 'open'), (1000, 'open'), (None, 'open'), (2000, 'settled'), (2000, 'closed')]:
            with self.subTest(expiry=expiry, status=status):
                state = self.state()
                state['pending']['expires_at'] = expiry
                paper = self.run_cycle(state, market=dict(ticker='KXBTC15M-RECOVERY', status=status,
                                                         yes_bid_dollars=.48, yes_ask_dollars=.50))
                self.assertIsNone(paper['open_position'])
                self.assertIn('expiry', paper['last_message'])

    def test_fetch_crosses_expiry_and_final_fill_deadline(self):
        for clock in ([1000, 2000], [1000, 1999, 2000]):
            with patch.object(bg.time, 'time', side_effect=clock):
                paper = self.run_cycle(self.state(), now=None)
            self.assertIsNone(paper['open_position'])
            self.assertIn('expired', paper['last_message'])

    def test_small_fill_must_cover_rounded_entry_and_exit_fees(self):
        with patch.object(bg, '_projected_side_value', return_value=.53):
            paper = self.run_cycle(self.state())
        self.assertIsNone(paper['open_position'])
        self.assertIn('fees', paper['last_message'])

    def test_drawdown_still_halts_new_scalps(self):
        metrics = dict(samples=50, profit_factor=1.08, expectancy=.1, max_drawdown_pct=.11)
        gate = engine.scalp_execution_policy(metrics)
        self.assertFalse(gate['approved'])
        self.assertEqual(gate['status'], 'SCALPS PAUSED')
        state = self.state()
        for t in state['background_paper']['trades']:
            t['pnl'] = -2
        paper = self.run_cycle(state)
        self.assertIsNone(paper['open_position'])
        self.assertIn('drawdown', paper['last_message'])

    def test_locks_do_not_mask_scalp_recovery_and_recent_results_can_recover(self):
        paper = self.state()['background_paper']
        paper['trades'].append(dict(strategy='LOCK', status='CLOSED', ticker='LOCK',
                                    closed_at=200, pnl=1000))
        all_metrics, gate = bg.shared_paper_scorecard(paper)
        self.assertEqual(all_metrics['samples'], 51)
        self.assertEqual(gate['performance']['samples'], 50)
        self.assertEqual(gate['status'], 'PAPER RECOVERY')
        paper['trades'].extend(dict(strategy='SCALP', status='CLOSED', ticker=f'NEW-{i}',
                                   closed_at=300+i, pnl=.1) for i in range(50))
        _, gate = bg.shared_paper_scorecard(paper)
        self.assertFalse(gate['recovery'])
        self.assertEqual(gate['status'], 'VALIDATED PASS')
        self.assertEqual(gate['recent_performance']['samples'], 50)

    def test_policy_agrees_across_both_adapters(self):
        paper = self.state()['background_paper']
        metrics = bg._post_fix_metrics(paper, strategy='SCALP')
        self.assertEqual(bg._paper_gate(paper), engine.scalp_execution_policy(metrics, metrics))
