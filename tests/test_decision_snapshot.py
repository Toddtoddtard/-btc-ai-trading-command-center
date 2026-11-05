import copy
import importlib
from pathlib import Path
import unittest

from contract_calibration import BASIS
import background_paper as bg
from learner_v31 import refresh_pending_lock_focus


class DecisionSnapshotTests(unittest.TestCase):
    def api(self):
        self.assertTrue(Path('decision_snapshot.py').exists(), 'Shared decision source is missing')
        return importlib.import_module('decision_snapshot')

    def state(self, action='LOCK UP', probability=.85):
        call = dict(ticker='T', expires_at=1600, opened_at=1000,
                    master_action=action, master_confidence=.8, execution_approved=True,
                    execution_reason='QUALIFIED', would_wait=False,
                    contract_probability_up=probability, contract_probability_basis=BASIS,
                    contract_calibrator_active=True, settlement_reference_timestamp=1000,
                    decision_schema='settlement-first-v1', start_price=50000,
                    predicted_end=50100, target=49950)
        state = {'pending': copy.deepcopy(call)}
        refresh_pending_lock_focus(state, call, {'ticker': 'T', 'expires_at': 1600})
        return state

    def market(self, now=1000):
        return dict(ticker='T', status='open', yes_bid_dollars=.49, yes_ask_dollars=.5,
                    no_bid_dollars=.49, no_ask_dollars=.5, quotes_observed_at=now,
                    execution_book=dict(available=True, yes_ask_size=100, no_ask_size=100))

    def test_refresh_publishes_immutable_same_decision_for_dashboard_and_fill(self):
        api = self.api(); state = self.state()
        snapshot = copy.deepcopy(state['settlement_decision'])
        view = api.dashboard_decision({'kalshi_ticker':'T', 'action':'LOCK DOWN'}, state, now=1000)
        self.assertEqual(view['action'], 'LOCK UP')
        self.assertEqual(view['decision_id'], snapshot['decision_id'])
        # A later mutable pending field cannot replace the published decision.
        state['pending'].update(master_action='LOCK DOWN', contract_probability_up=.1)
        paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
        self.assertEqual(paper['open_position']['side'], 'YES', paper['last_message'])
        self.assertEqual(paper['open_position']['decision_id'], view['decision_id'])
        self.assertEqual(state['settlement_decision'], snapshot)
        self.assertEqual(paper['entry_assessment']['decision_id'], view['decision_id'])
        bg.run_cycle(state, lambda _: self.market(1001), now=1001)
        self.assertEqual(sum(e['event_type']=='OPENED' for e in paper['ledger_events']), 1)

    def test_down_is_no_and_wait_or_plain_forecast_never_fills(self):
        self.api()
        for action, probability, side in [('LOCK DOWN',.15,'NO'), ('WAIT',.85,None), ('SCALP UP',.85,None)]:
            with self.subTest(action=action):
                state = self.state(action, probability)
                paper = bg.run_cycle(state, lambda _: self.market(), now=1000)
                self.assertEqual((paper['open_position'] or {}).get('side'), side)
                self.assertNotIn('Awaiting current-cycle checks', paper['entry_assessment']['blockers'])

    def test_stale_future_wrong_ticker_and_expiry_never_authorize(self):
        api = self.api()
        for now, ticker in [(1031,'T'), (999,'T'), (1600,'T'), (1000,'OTHER')]:
            state = self.state()
            self.assertTrue(api.snapshot_blockers(state['settlement_decision'], ticker, now))
        state = self.state()
        paper = bg.run_cycle(state, lambda _: self.market(1031), now=1031)
        self.assertIsNone(paper['open_position'])
        self.assertIn('STALE_DECISION', paper['last_message'])
        self.assertEqual(state['settlement_decision']['captured_at'], 1000)

    def test_conflicting_refresh_vetoes_original_lock_without_reversing(self):
        self.api(); state = self.state()
        live = dict(state['pending'], master_action='LOCK DOWN', opened_at=1001,
                    contract_probability_up=.15, settlement_reference_timestamp=1001)
        refresh_pending_lock_focus(state, live, {'ticker':'T', 'expires_at':1600})
        snapshot = state['settlement_decision']
        self.assertEqual(snapshot['master_action'], 'LOCK UP')
        self.assertEqual(snapshot['side'], 'YES')
        self.assertEqual(snapshot['forecast_side'], 'NO')
        self.assertFalse(snapshot['approved'])
        paper = bg.run_cycle(state, lambda _: self.market(1001), now=1001)
        self.assertIsNone(paper['open_position'])
        self.assertIn('CHANGED',paper['last_message'])

    def test_stale_worker_never_falls_back_to_local_lock(self):
        api=self.api(); state=self.state()
        for now in (1031,1600):
            view=api.dashboard_decision({'kalshi_ticker':'T','action':'LOCK DOWN'},state,now=now)
            self.assertEqual(view['action'],'WAIT')
            self.assertFalse(view['execution_approved'])
        view=api.dashboard_decision({'kalshi_ticker':'T','action':'LOCK UP'}, {}, now=1000)
        self.assertEqual(view['action'],'WAIT')
        self.assertFalse(view['authoritative_available'])

    def test_fee_and_reference_checks_still_veto_and_preserve_ledger(self):
        self.api(); state=self.state(probability=.51)
        before=copy.deepcopy(state.get('background_paper',{}).get('trades',[]))
        paper=bg.run_cycle(state,lambda _:self.market(),now=1000)
        self.assertIsNone(paper['open_position'])
        self.assertIn('fee-adjusted',paper['last_message'])
        self.assertEqual(paper['trades'],before)

    def test_missing_fresh_evaluation_publishes_veto_and_keeps_original_clock(self):
        self.api(); state=self.state()
        refresh_pending_lock_focus(state,None,{'ticker':'T','expires_at':1600})
        self.assertFalse(state['settlement_decision']['approved'])
        self.assertIsNone(state['settlement_decision']['captured_at'])

    def test_corrupt_snapshot_cannot_authorize_entry(self):
        self.api(); state=self.state()
        state['settlement_decision']['call']['master_action']='LOCK DOWN'
        paper=bg.run_cycle(state,lambda _:self.market(),now=1000)
        self.assertIsNone(paper['open_position'])
        self.assertIn('DECISION',paper['last_message'])

    def test_missing_legacy_reset_marker_never_rewrites_existing_ledger(self):
        self.api(); state=self.state('WAIT')
        paper=bg.initial_state(1000)
        paper.update(cash=491.,legacy_realized_pnl=0.,trades=[dict(ticker='HISTORY',
                     status='CLOSED',strategy='LOCK',pnl=-9.,result='LOSS')])
        state['background_paper']=paper
        before=copy.deepcopy(paper['trades'])
        bg.run_cycle(state,lambda _:self.market(),now=1000)
        self.assertEqual(paper['trades'],before)
        self.assertEqual(paper['cash'],491.)
        self.assertNotIn('balance_reset',paper)

    def test_execution_refresh_observes_new_data_instead_of_renewing_cached_signal(self):
        from unittest.mock import patch
        import learner_v31 as worker
        self.assertTrue(hasattr(worker,'refresh_execution_decision'))
        state=self.state()
        live=dict(state['pending'], opened_at=1020, settlement_reference_timestamp=1020)
        with patch.object(worker,'parallel_calls',return_value={'history':object(),'market':{'ticker':'T','expires_at':1600}}), \
             patch.object(worker,'current_shadow_call',return_value=live), \
             patch.object(worker,'record_observation') as record, patch.object(worker,'record_prediction'):
            worker.refresh_execution_decision(state)
        self.assertEqual(state['settlement_decision']['captured_at'],1020)
        record.assert_called_once()
        with patch.object(worker,'parallel_calls',side_effect=OSError('feed unavailable')):
            worker.refresh_execution_decision(state)
        self.assertIsNone(state['settlement_decision']['captured_at'])
        self.assertFalse(state['settlement_decision']['approved'])
        self.assertEqual(state['pending']['master_action'],'LOCK UP')

    def test_stale_snapshot_cannot_promote_existing_scalp_to_lock(self):
        self.api(); state=self.state()
        paper=bg.initial_state(1000)
        paper.update(cash=499.48,legacy_realized_pnl=0.,open_position=dict(
            ticker='T',side='YES',direction='UP',strategy='SCALP',status='OPEN',
            opened_at=1000,expires_at=1600,entry_price=.5,entry_fee=.02,
            amount=.52,contracts=1,last_mark=.49))
        state['background_paper']=paper
        bg.run_cycle(state,lambda _:self.market(1100),now=1100)
        self.assertEqual(paper['open_position']['strategy'],'SCALP')

    def test_incompatible_existing_account_is_rejected_without_replacement(self):
        self.api()
        for version in (None,2):
            state=self.state('WAIT')
            paper=dict(cash=123.,trades=[dict(ticker='HISTORY',pnl=-377.)],open_position=None)
            if version is not None: paper['version']=version
            state['background_paper']=paper
            before=copy.deepcopy(paper)
            with self.assertRaisesRegex(ValueError,'preserv'):
                bg.run_cycle(state,lambda _:self.market(),now=1000)
            self.assertIs(state['background_paper'],paper)
            self.assertEqual(paper,before)
