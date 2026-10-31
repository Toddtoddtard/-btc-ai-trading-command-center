"""Horizon isolation and causal bias learning for official settlement."""
import copy
import unittest
from unittest.mock import patch

import contract_calibration as calibration
import settlement_predictor as predictor
from tests.test_settlement_predictor import EXPIRY, TICKER, market, feed


class SettlementLearningTests(unittest.TestCase):
    def history(self, count=320, lead=700):
        rows = []
        # A repeatable downward probability bias cannot be represented by a
        # correction constrained to be symmetric around 50%.
        for i in range(count):
            opened = i * 900
            p = .4 if i % 2 else .6
            rows.append(dict(ticker='T'+str(i), opened_at=opened, expires_at=opened+lead,
                result_observed_at=opened+lead+10,
                result='yes' if i % 10 < (2 if p == .4 else 4) else 'no',
                market_yes_probability=p, raw_contract_probability_up=p))
        return rows

    def test_bias_candidate_can_learn_directional_miscalibration(self):
        model = calibration.fit(self.history(), as_of=400000, learn_bias=True)
        self.assertTrue(model['active'])
        self.assertEqual(model['algorithm'], 'market_residual_bias_v2')
        self.assertLess(model['intercept'], 0)
        self.assertGreater(model['validation']['brier_edge'], .002)

    def test_delayed_outcomes_cannot_change_earlier_validation(self):
        rows = self.history()
        for row in rows[-20:]:
            row['result_observed_at'] = 999999
        a = calibration.fit(rows, as_of=400000, learn_bias=True)
        changed = copy.deepcopy(rows)
        for row in changed[-20:]:
            row['result'] = 'no' if row['result'] == 'yes' else 'yes'
        self.assertEqual(a, calibration.fit(changed, as_of=400000, learn_bias=True))
        self.assertEqual(a['training_markets'], 300)

    def test_every_walk_forward_fit_uses_only_already_observed_labels(self):
        rows = self.history(count=220)
        rows[0]['result_observed_at'] = 150*900
        original = calibration.bias_coefficients
        seen = []
        def fit(prior):
            seen.append([r['ticker'] for r in prior])
            return original(prior)
        with patch.object(calibration, 'bias_coefficients', side_effect=fit):
            calibration.fit(rows, as_of=400000, learn_bias=True)
        # T0's delayed label is unavailable at the first validated origin, but
        # joins training once genuinely observed. The last call is final fitting.
        self.assertNotIn('T0', seen[0])
        self.assertIn('T0', seen[-2])
        for prior in seen[:-1]:
            if 'T0' in prior:
                self.assertGreaterEqual(len(prior), 150)

    def test_bias_adjustment_is_bounded_and_used_by_shared_selector(self):
        # Test a genuinely qualified model, not a separate mock probability.
        model = calibration.fit(self.history(), as_of=400000, learn_bias=True)
        state = dict(contract_calibration=model)
        view = dict(probability_up=.4, market_probability_up=.4)
        result = calibration.apply(view, state, now=400000)
        self.assertTrue(result['calibrator_active'])
        self.assertLess(result['probability_up'], .4)
        self.assertLessEqual(abs(result['probability_up']-.4), .15+1e-12)
        self.assertEqual(result['probability_up'], result['previous_probability_up'])

    def test_new_candidate_does_not_replace_a_better_incumbent(self):
        incumbent = dict(active=True, validation=dict(candidate_brier=.10),
                         recent_validation=dict(candidate_brier=.10))
        challenger = dict(active=True, validation=dict(candidate_brier=.11),
                          recent_validation=dict(candidate_brier=.09))
        with patch.object(calibration, 'fit', side_effect=lambda *a, learn_bias=False, **k:
                          copy.deepcopy(challenger if learn_bias else incumbent)):
            bundle = calibration.fit_settlement({}, as_of=1000)
        selected = bundle['by_horizon']['10m+']
        self.assertEqual(selected['validation']['candidate_brier'], .10)
        self.assertFalse(selected['bias_challenger']['selected'])

    def test_better_candidate_still_needs_new_frozen_official_evidence(self):
        incumbent = dict(active=False, validation=dict(candidate_brier=.20),
                         recent_validation=dict(candidate_brier=.20))
        challenger = dict(active=True, algorithm='market_residual_bias_v2',
                          validation=dict(candidate_brier=.18),
                          recent_validation=dict(candidate_brier=.19))
        with patch.object(calibration, 'fit', side_effect=lambda *a, learn_bias=False, **k:
                          copy.deepcopy(challenger if learn_bias else incumbent)):
            selected = calibration.fit_settlement({}, as_of=1000)['by_horizon']['10m+']
        self.assertFalse(selected['bias_challenger']['selected'])

    def test_better_validated_bias_candidate_can_replace_incumbent(self):
        incumbent = dict(active=False, validation=dict(candidate_brier=.20),
                         recent_validation=dict(candidate_brier=.20))
        challenger = dict(active=True, algorithm='market_residual_bias_v2',
                          validation=dict(candidate_brier=.18),
                          recent_validation=dict(candidate_brier=.19))
        with patch.object(calibration, 'fit', side_effect=lambda *a, learn_bias=False, **k:
                          copy.deepcopy(challenger if learn_bias else incumbent)), \
             patch.object(predictor, 'bias_scorecard', return_value=self.qualified_evidence()):
            selected = calibration.fit_settlement({}, as_of=1000)['by_horizon']['10m+']
        self.assertEqual(selected['algorithm'], 'market_residual_bias_v2')
        self.assertTrue(selected['bias_challenger']['selected'])

    def test_real_settlement_bias_model_reaches_shared_execution_probability(self):
        rows = self.history()
        for row in rows:
            row['settlement_prediction'] = dict(available=True, version=predictor.VERSION,
                ticker=row['ticker'], captured_at=row['opened_at'], expires_at=row['expires_at'],
                quotes_observed_at=row['opened_at'], reference_timestamp=row['opened_at'],
                base_probability_yes=row['raw_contract_probability_up'],
                market_probability_yes=row['market_yes_probability'])
        with patch.object(predictor, 'bias_scorecard', return_value=self.qualified_evidence()):
            bundle = calibration.fit_settlement(dict(settlement_predictor=dict(history=rows)), as_of=400000)
        selected = bundle['by_horizon']['10m+']
        self.assertEqual(selected['algorithm'], calibration.BIAS_ALGORITHM)
        prediction = dict(available=True, version=predictor.VERSION, ticker='LIVE',
            captured_at=400000, expires_at=400700, base_probability_yes=.4,
            market_probability_yes=.4)
        result = calibration.apply(dict(ticker='LIVE', probability_up=.4,
            market_probability_up=.4, seconds_remaining=700),
            dict(settlement_execution_calibration=bundle), settlement=prediction, now=400000)
        self.assertTrue(result['calibrator_active'])
        self.assertLess(result['probability_up'], .4)
        self.assertEqual(result['probability_source'], predictor.VERSION)

    def qualified_evidence(self):
        return dict(by_horizon={key: dict(market=dict(samples=110,
            status='IMPROVED_ON_OBSERVED_MARKETS'), independent=dict(brier_gain=.01))
            for key in ('10m+', '5m+', '1m+', 'final1m')})

    def test_candidate_predictions_are_frozen_and_scored_without_backfill(self):
        now = EXPIRY-700
        challenger = calibration.fit(self.history(), as_of=now, learn_bias=True)
        state = dict(settlement_execution_calibration=dict(basis=calibration.SETTLEMENT_BASIS,
            source=predictor.VERSION, fitted_as_of=now,
            by_horizon={'10m+': dict(bias_challenger=challenger)}))
        prediction = predictor.predict(dict(market(), quotes_observed_at=now), feed(now), state, now=now)
        self.assertTrue(prediction['learning_candidate']['available'])
        call = dict(ticker=TICKER, opened_at=now, expires_at=EXPIRY,
                    settlement_prediction=prediction)
        predictor.record_observation(state, call, market())
        captured = copy.deepcopy(state['settlement_predictor']['pending'][0])
        prediction['learning_candidate']['probability_yes'] = .99
        self.assertEqual(state['settlement_predictor']['pending'][0], captured)
        self.assertEqual(predictor.bias_scorecard(state, EXPIRY)['by_horizon']['10m+']['market']['samples'], 0)
        predictor.resolve_observations(state, lambda _: 'yes', now=EXPIRY+10)
        report = predictor.bias_scorecard(state, EXPIRY+20)
        self.assertEqual(report['by_horizon']['10m+']['market']['samples'], 1)
        # Adding duplicate captures and old forecasts without a candidate
        # cannot manufacture more candidate validation markets.
        history = state['settlement_predictor']['history']
        history.extend(copy.deepcopy(history))
        old = copy.deepcopy(history[0]); old['ticker'] = 'OLD'
        old['settlement_prediction']['ticker'] = 'OLD'
        old['settlement_prediction'].pop('learning_candidate')
        history.append(old)
        self.assertEqual(predictor.bias_scorecard(state, EXPIRY+20), report)

    def test_late_forecast_does_not_train_on_early_only_captures(self):
        now = EXPIRY-120
        rows = []
        for i in range(110):
            opened, expires = now-100000+i*900, now-99300+i*900
            p = predictor.predict(market(), feed(EXPIRY-700), {}, now=EXPIRY-700)
            p.update(ticker='T'+str(i), captured_at=opened, expires_at=expires)
            rows.append(dict(ticker=p['ticker'], opened_at=opened, expires_at=expires,
                             result_observed_at=expires+10, result='yes', settlement_prediction=p))
        state = dict(settlement_predictor=dict(history=rows))
        late = predictor.predict(market(), feed(now), state, now=now)
        early = predictor.predict(market(), feed(EXPIRY-700), state, now=EXPIRY-700)
        self.assertEqual(late['training_samples'], 0)
        self.assertEqual(late['correction_horizon'], '1m+')
        self.assertGreater(early['training_samples'], 100)

