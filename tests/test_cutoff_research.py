import copy
import unittest
from unittest.mock import patch

from contract_calibration import BASIS


class CutoffResearchTests(unittest.TestCase):
    def inputs(self):
        call = dict(ticker='T', master_action='LOCK UP', expires_at=1600,
                    execution_approved=True, execution_checked_at=1000,
                    master_confidence=.8, contract_probability_basis=BASIS,
                    contract_calibrator_active=True, contract_probability_up=.85,
                    settlement_reference_timestamp=1000, code_revision='revision-a',
                    lock_focus={'eligible': True, 'checks': {
                        'source_health': True, 'target_confirmed': True, 'window': True}})
        market = dict(ticker='T', status='open', quotes_observed_at=1000,
                      yes_bid_dollars=.59, yes_ask_dollars=.60,
                      no_bid_dollars=.40, no_ask_dollars=.41,
                      execution_book={'available': True, 'yes_ask_size': 10, 'no_ask_size': 10})
        return call, market

    def capture(self, state=None, call=None, market=None, gate=None):
        from cutoff_research import observe
        original_call, original_market = self.inputs()
        state = {} if state is None else state
        observe(state, original_call if call is None else call,
                original_market if market is None else market, cash=500,
                lock_gate={'approved': True} if gate is None else gate, now=1000)
        return state

    def test_only_research_state_changes_and_capture_is_immutable(self):
        state = {'background_paper': {'cash': 500, 'trades': [{'id': 'old'}]}, 'pending': self.inputs()[0]}
        before = copy.deepcopy(state)
        self.capture(state)
        row = copy.deepcopy(state['cutoff_research']['pending'][0])
        call, market = self.inputs(); call['contract_probability_up'] = .2
        self.capture(state, call=call, market=market)
        self.assertEqual(state['cutoff_research']['pending'], [row])
        self.assertEqual(state['background_paper'], before['background_paper'])
        self.assertEqual(state['pending'], before['pending'])
        self.assertFalse(state['cutoff_research']['affects_execution'])

    def test_candidate_relaxes_cutoffs_and_one_cent_margin_for_both_sides(self):
        for side in ('UP', 'DOWN'):
            call, market = self.inputs()
            call.update(master_action='SCALP '+side, master_confidence=.55,
                        contract_probability_up=.98 if side == 'UP' else .02)
            call['lock_focus']['eligible'] = False
            prefix = 'yes' if side == 'UP' else 'no'
            market.update({prefix+'_bid_dollars': .93, prefix+'_ask_dollars': .94})
            row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
            self.assertFalse(row['baseline']['eligible'])
            self.assertTrue(row['candidate']['eligible'], row['candidate']['blockers'])
            self.assertEqual(row['contracts'], 10)
            self.assertGreaterEqual(row['expected_net_pnl']/row['contracts'], .01)

    def test_quarantine_validation_reliability_and_target_guards_still_block(self):
        cases = [('contract_calibrator_active', False), ('execution_approved', False),
                 ('contract_probability_up', None), ('contract_probability_up', True),
                 ('contract_probability_up', float('nan'))]
        for key, value in cases:
            call, market = self.inputs(); call[key] = value
            row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
            self.assertFalse(row['candidate']['eligible'], key)
        for check in ('source_health', 'target_confirmed', 'window'):
            call, market = self.inputs(); call['lock_focus']['checks'][check] = False
            row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
            self.assertFalse(row['candidate']['eligible'], check)
        row = self.capture(gate={'approved': False})['cutoff_research']['pending'][0]
        self.assertIn('LOCK_VALIDATION_QUARANTINE', row['candidate']['blockers'])

    def test_stale_future_or_missing_depth_and_forecast_are_not_captured(self):
        for field, value in [('quotes_observed_at', 969), ('quotes_observed_at', 1001),
                             ('execution_book', {'available': False}), ('ticker', 'OTHER')]:
            call, market = self.inputs(); market[field] = value
            self.assertEqual(self.capture(call=call, market=market)['cutoff_research']['pending'], [])
        for key in ('execution_checked_at', 'settlement_reference_timestamp'):
            call, market = self.inputs(); call[key] = 969
            self.assertEqual(self.capture(call=call, market=market)['cutoff_research']['pending'], [])

    def test_quantity_is_depth_and_fee_inclusive_budget_limited(self):
        call, market = self.inputs(); market['execution_book']['yes_ask_size'] = 2.8
        row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
        self.assertEqual(row['contracts'], 2)
        self.assertAlmostEqual(row['entry_fee'], .04)
        market['execution_book']['yes_ask_size'] = 100
        row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
        self.assertLessEqual(row['contracts']*.6+row['entry_fee'], 10)
        self.assertEqual(row['contracts'], 16)

    def test_fresh_call_cannot_reuse_old_lock_window_check_near_expiry(self):
        for remaining in (10, 30):
            call, market = self.inputs(); call['expires_at'] = 1000 + remaining
            row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
            self.assertFalse(row['baseline']['eligible'])
            self.assertFalse(row['candidate']['eligible'])
            self.assertIn('WINDOW', row['candidate']['blockers'])

    def test_only_own_official_result_after_expiry_resolves(self):
        from cutoff_research import resolve, scorecard
        state = self.capture()
        for now, market in [(1500, dict(ticker='T', status='settled', result='yes')),
                            (1700, dict(ticker='OTHER', status='settled', result='yes')),
                            (1700, dict(ticker='T', status='open', result='yes')),
                            (1700, dict(ticker='T', status='settled', result=''))]:
            resolve(state, lambda _: market, now=now)
            self.assertEqual(scorecard(state, as_of=now)['markets'], 0)
        resolve(state, lambda _: dict(ticker='T', status='settled', result='no'), now=1700)
        self.assertEqual(scorecard(state, as_of=1699)['markets'], 0)
        card = scorecard(state, as_of=1700)
        self.assertEqual(card['markets'], 1)
        self.assertLess(card['candidate']['net_pnl'], 0)
        self.assertAlmostEqual(card['candidate']['brier'], .85**2)
        self.capture(state)
        self.assertEqual(state['cutoff_research']['pending'], [])

    def test_scorecard_deduplicates_and_keeps_revisions_separate(self):
        from cutoff_research import resolve, scorecard
        state = self.capture()
        resolve(state, lambda _: dict(ticker='T', status='settled', result='yes'), now=1700)
        history = state['cutoff_research']['history']
        history.extend([copy.deepcopy(history[0]), dict(history[0], ticker='U', code_revision='other')])
        card = scorecard(state, as_of=1800, revision='revision-a')
        self.assertEqual(card['markets'], 1)
        self.assertEqual(card['status'], 'COLLECTING')
        self.assertEqual(card['additional_entries'], 0)
        self.assertFalse(card['affects_execution'])

    def test_one_hundred_blocked_markets_cannot_claim_improvement(self):
        from cutoff_research import resolve, scorecard
        state = self.capture(gate={'approved': False})
        resolve(state, lambda _: dict(ticker='T', status='settled', result='yes'), now=1700)
        row = state['cutoff_research']['history'][0]
        state['cutoff_research']['history'] = [dict(row, ticker=str(i)) for i in range(100)]
        card = scorecard(state, as_of=1800)
        self.assertEqual(card['markets'], 100)
        self.assertEqual(card['status'], 'INSUFFICIENT_ADDITIONAL_ENTRIES')
        self.assertIsNone(card['candidate']['expectancy'])

    def test_worker_calls_trial_with_existing_book_and_does_not_change_paper_entry(self):
        import background_paper as bg
        from cutoff_research import scorecard
        call, market = self.inputs()
        state = {'pending': call, 'background_paper': bg.initial_state(1000)}
        with patch.object(bg, '_post_fix_metrics', return_value={'markets': 0}):
            bg.run_cycle(state, lambda _: market, now=1000)
        self.assertEqual(scorecard(state, as_of=1000)['pending_markets'], 1)

    def test_old_trial_result_reads_never_delay_the_current_execution_cycle(self):
        import background_paper as bg
        import cutoff_research
        call, market = self.inputs()
        state = self.capture()
        state['pending'] = call
        state['background_paper'] = bg.initial_state(1700)
        # An unresolved past trial would make resolve call the old ticker.
        row = state['cutoff_research']['pending'][0]
        row.update(ticker='OLD', opened_at=0, expires_at=900)
        reads = []
        def reader(ticker):
            reads.append(ticker)
            return market
        bg.run_cycle(state, reader, now=1000)
        self.assertNotIn('OLD', reads)

    def test_unknown_results_rotate_and_label_read_budget_is_bounded(self):
        from cutoff_research import resolve
        state = self.capture()
        row = state['cutoff_research']['pending'][0]
        state['cutoff_research']['pending'] = [dict(row, ticker=str(i)) for i in range(6)]
        calls = []
        def reader(ticker):
            calls.append(ticker)
            return dict(ticker=ticker, status='closed')
        resolve(state, reader, now=1700)
        self.assertEqual(calls, ['0', '1', '2'])
        calls.clear()
        resolve(state, reader, now=1700)
        self.assertEqual(calls, ['3', '4', '5'])

    def test_subnormal_quote_cannot_crash_research_allocation(self):
        call, market = self.inputs()
        market.update(yes_bid_dollars=0, yes_ask_dollars=1e-320)
        row = self.capture(call=call, market=market)['cutoff_research']['pending'][0]
        self.assertEqual(row['contracts'], 10)

    def test_pending_retention_reports_unresolved_observations_dropped(self):
        from cutoff_research import scorecard
        state = self.capture()
        row = state['cutoff_research']['pending'][0]
        state['cutoff_research']['pending'] = [dict(row, ticker=str(i)) for i in range(200)]
        self.capture(state)
        self.assertEqual(len(state['cutoff_research']['pending']), 200)
        self.assertEqual(scorecard(state, as_of=1800)['dropped_pending_all_revisions'], 1)


if __name__ == '__main__':
    unittest.main()
