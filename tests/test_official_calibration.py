import copy
import unittest
from unittest.mock import patch

from contract_calibration import BASIS, apply, fit, observations
from council_accounting import MASTER_BASIS, reconcile_master_learning
from background_paper import _projected_side_value
from learner_v31 import refresh_pending_lock_focus
from council_v4 import analyze_bot_contributions


class OfficialCalibrationTests(unittest.TestCase):
    def state(self):
        return {'confidence_model': {'samples': 99, 'brier_ewma': .01},
                'regimes': {'RANGE': {'ewma_accuracy': .99}},
                'prediction_snapshots': [{'ticker': 'A', 'opened_at': 10, 'expires_at': 20,
                    'snapshot': {'master_base_score': -.8, 'master_confidence': .8,
                                 'regime': 'RANGE', 'specialists': {'Trend AI': {'score': -.8}}}}],
                'master_history': [{'ticker': 'A', 'kalshi_result': 'yes', 'direction_correct': 1}],
                'background_paper': {'cash': 515.583}, 'forecast': {'samples': 2022}}

    def test_council_loss_cannot_borrow_candle_forecast_win(self):
        state = self.state()
        before = copy.deepcopy(state)
        model = reconcile_master_learning(state)
        self.assertEqual((model['samples'], model['hits'], model['last_correct']), (1, 0, 0))
        self.assertAlmostEqual(model['brier_ewma'], .9*.25+.1*.8**2)
        self.assertEqual(state['regimes']['RANGE']['direction_hits'], 0)
        self.assertEqual(model['basis'], MASTER_BASIS)
        self.assertEqual(state['forecast'], before['forecast'])
        self.assertEqual(state['background_paper'], before['background_paper'])
        repaired = copy.deepcopy(state)
        reconcile_master_learning(state)
        self.assertEqual(state, repaired)

    def test_missing_official_result_and_neutral_council_never_train(self):
        state = self.state()
        state['master_history'][0]['kalshi_result'] = None
        self.assertEqual(reconcile_master_learning(state)['samples'], 0)
        state['master_history'][0]['kalshi_result'] = 'yes'
        state['prediction_snapshots'][0]['snapshot']['master_base_score'] = .01
        self.assertEqual(reconcile_master_learning(state)['samples'], 0)

    def test_contribution_replay_cannot_use_todays_fitted_weights(self):
        original = self.state()
        fitted = copy.deepcopy(original)
        fitted.update(specialists={'Trend AI': {'adaptive_weight': 100, 'samples': 1000}},
                      bot_intelligence_v4={'label_basis': 'official_kalshi_directional_calls_v1',
                          'evaluation_mode': 'causal_prior_only_ablation',
                          'ranking': [{'name': 'Trend AI', 'directional_calls': 1000, 'contribution_score': -.75}]})
        before = copy.deepcopy(fitted)
        self.assertEqual(analyze_bot_contributions(original), analyze_bot_contributions(fitted))
        self.assertEqual(fitted, before)

    def history(self, count=220):
        return [{'ticker': str(i), 'opened_at': i*100, 'expires_at': i*100+90,
                 'market_yes_probability': .6, 'raw_contract_probability_up': .85,
                 'result': 'yes'} for i in range(count)]

    def test_phase_duplicates_and_order_cannot_inflate_validation(self):
        rows = self.history()
        duplicate = dict(rows[1], opened_at=150, raw_contract_probability_up=.1)
        self.assertEqual(fit(rows), fit(list(reversed(rows)) + [duplicate]*100))
        self.assertEqual(len(observations(rows + rows)), 220)

    def test_future_unexpired_labels_are_purged_before_fit(self):
        rows = self.history()
        # The label exists in the offline file, but cannot be known at as_of.
        self.assertEqual(fit(rows, as_of=10000), fit(rows[:100], as_of=10000))
        with patch('contract_calibration.coefficients', wraps=__import__('contract_calibration').coefficients) as fitting:
            rows[0]['expires_at'] = 100000
            fit(rows)
            for call in fitting.call_args_list[:-1]:
                self.assertNotIn('0', {r['ticker'] for r in call.args[0]})

    def test_validation_can_promote_helpful_and_reject_harmful_correction(self):
        helpful = fit(self.history())
        self.assertTrue(helpful['active'])
        harmful = self.history()
        for i, row in enumerate(harmful):
            row['result'] = 'yes' if i % 5 < 3 else 'no'
        self.assertFalse(fit(harmful)['active'])

    def test_unproven_blend_cannot_manufacture_edge(self):
        raw = {'probability_up': .9, 'market_probability_up': .45, 'available': True}
        view = apply(raw, {})
        self.assertEqual(view['raw_probability_up'], .9)
        self.assertEqual(view['probability_up'], .45)
        self.assertEqual(view['edge_vs_market'], 0)
        self.assertEqual(raw['probability_up'], .9)
        view = apply(raw, {'contract_calibration': fit(self.history())})
        self.assertTrue(view['calibrator_active'])
        self.assertGreater(view['probability_up'], .45)

    def test_live_contract_fields_reach_paper_without_changing_snapshot(self):
        snap = {'master_base_score': -.8}
        state = {'pending': {'ticker': 'T', 'snapshot': snap, 'predicted_end': 101}}
        live = {'contract_probability_up': .81, 'raw_contract_probability_up': .9,
                'contract_probability_basis': BASIS, 'contract_calibrator_active': True,
                'master_action': 'SCALP UP'}
        refresh_pending_lock_focus(state, live, {'ticker': 'T'})
        self.assertEqual(state['pending']['snapshot'], snap)
        self.assertEqual(state['pending']['predicted_end'], 101)
        market = {'yes_bid_dollars': .48, 'yes_ask_dollars': .50}
        self.assertAlmostEqual(_projected_side_value(state['pending'], market, 'YES'), .81)
        self.assertAlmostEqual(_projected_side_value(state['pending'], market, 'NO'), .19)
        state['pending']['contract_calibrator_active'] = False
        self.assertAlmostEqual(_projected_side_value(state['pending'], market, 'YES'), .49)


if __name__ == '__main__':
    unittest.main()
