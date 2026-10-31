import unittest
from contract_calibration import BASIS


class TradeAssessmentTests(unittest.TestCase):
    def assess(self, **changes):
        from trade_assessment import assess_paper_entry
        call = dict(master_action='LOCK UP', ticker='T', expires_at=1600,
                    execution_approved=True, contract_probability_basis=BASIS,
                    contract_calibrator_active=True, contract_probability_up=.85,
                    settlement_reference_timestamp=1000, decision_schema='settlement-first-v1')
        call.update(changes.pop('call', {}))
        market = dict(ticker='T', status='open', yes_bid_dollars=.59, yes_ask_dollars=.60,
                      no_bid_dollars=.40, no_ask_dollars=.41, quotes_observed_at=1000)
        market.update(changes.pop('market', {}))
        return assess_paper_entry(call, market, contracts=10, now=1000,
                                  lock_gate=changes.pop('lock_gate', {'approved': True}))

    def test_positive_lock_has_one_fee_adjusted_assessment(self):
        a = self.assess()
        self.assertEqual(a['paper_action'], 'LOCK UP')
        self.assertAlmostEqual(a['net_edge_per_contract'], .233)
        self.assertEqual(a['outlook'], 'UP')

    def test_missing_evidence_never_turns_outlook_into_trade(self):
        a = self.assess(call={'contract_calibrator_active': False})
        self.assertEqual(a['paper_action'], 'WAIT')
        self.assertEqual(a['outlook'], 'UP')
        self.assertIn('NO_VALIDATED_SETTLEMENT_EDGE', a['blockers'])

    def test_quarantine_and_stale_or_wrong_ticker_block(self):
        for changes, reason in [({'lock_gate': {'approved': False}}, 'LOCK_VALIDATION_QUARANTINE'),
                                ({'market': {'ticker': 'OTHER'}}, 'CONTRACT_MISMATCH'),
                                ({'market': {'quotes_observed_at': 969}}, 'STALE_QUOTES'),
                                ({'call': {'settlement_reference_timestamp': 969}}, 'STALE_REFERENCE'),
                                ({'call': {'expires_at': 1000}}, 'EXPIRED_MARKET')]:
            with self.subTest(reason=reason):
                self.assertIn(reason, self.assess(**changes)['blockers'])

    def test_settlement_probability_cannot_authorize_a_scalp(self):
        a = self.assess(call={'master_action': 'SCALP UP', 'scalp_projected_exit_price': .99})
        self.assertEqual(a['paper_action'], 'WAIT')
        self.assertIn('NO_VALIDATED_SCALP_EXIT_MODEL', a['blockers'])
        self.assertIsNone(a['expected_early_exit_price'])

    def test_old_lock_side_economics_are_not_replaced_by_new_probability_direction(self):
        a = self.assess(call={'master_action': 'LOCK DOWN'})
        self.assertEqual(a['outlook'], 'DOWN')
        self.assertEqual(a['paper_action'], 'WAIT')
        self.assertLess(a['net_edge_per_contract'], 0)

    def test_nan_probability_and_noninteger_size_do_not_approve(self):
        a = self.assess(call={'contract_probability_up': float('nan')})
        self.assertEqual(a['paper_action'], 'WAIT')
