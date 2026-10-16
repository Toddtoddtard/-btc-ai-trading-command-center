import copy
import unittest
from unittest.mock import patch
from contextlib import ExitStack
import pandas as pd

import settlement_predictor as model
from tests.test_settlement_predictor import EXPIRY, TICKER, market, feed


class SettlementEvidenceTests(unittest.TestCase):
    def test_worker_refreshes_quotes_after_slow_specialist_requests(self):
        import learner_v31 as worker
        from tests import test_reliability_v31 as fixtures
        now = EXPIRY-600
        initial = dict(market(), quotes_observed_at=now,
                       settlement_reference=feed(now))
        clock = [now]
        def slow_trades():
            clock[0] += 40
            return {}
        with ExitStack() as stack:
            fixtures.ReliabilityTests().shadow_dependencies(stack)
            stack.enter_context(patch.object(worker.time, 'time', side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(worker.legacy, 'aggregate_trades', side_effect=slow_trades))
            stack.enter_context(patch.object(worker.legacy, 'market', side_effect=lambda:
                                            dict(market(), quotes_observed_at=clock[0])))
            stack.enter_context(patch.object(worker, 'fetch_chart', side_effect=lambda _:
                                            feed(clock[0])))
            call = worker.current_shadow_call({}, pd.DataFrame({'close': [83000.]}), initial)
        self.assertTrue(call['settlement_prediction']['available'])
        self.assertEqual(call['settlement_prediction']['quotes_observed_at'], now+40)
        self.assertEqual(call['opened_at'], call['settlement_prediction']['captured_at'])

    def test_validation_can_enable_a_helpful_correction_and_excludes_delayed_labels(self):
        rows = []
        for i in range(210):
            opened = i*900
            rows.append(dict(opened_at=opened, result_observed_at=opened+650, result='yes',
                             settlement_prediction=dict(features=[1., 0., 0., 0.],
                                                        base_probability_yes=.5, market_probability_yes=.5)))
        self.assertTrue(model.correction_validation(rows)['active'])
        for row in rows:
            row['result_observed_at'] = 9999999
        self.assertEqual(model.correction_validation(rows)['samples'], 0)

    def test_live_label_timestamp_is_after_the_result_read(self):
        state = {'settlement_predictor': {'pending': [dict(ticker=TICKER, expires_at=EXPIRY)]}}
        with patch.object(model.time, 'time', side_effect=[EXPIRY+1, EXPIRY+10]):
            model.resolve_observations(state, lambda _: 'yes')
        self.assertEqual(state['settlement_predictor']['history'][0]['result_observed_at'], EXPIRY+10)

    def test_stale_quotes_do_not_pass_with_a_fresh_reference(self):
        now = EXPIRY - 600
        m = dict(market(), quotes_observed_at=now - 31)
        self.assertFalse(model.predict(m, feed(now), {}, now=now)['available'])

    def test_training_volume_alone_cannot_enable_correction(self):
        rows = []
        for i in range(210):
            opened = EXPIRY - (i + 2) * 900
            p = model.predict(market(), feed(EXPIRY-600), {}, now=EXPIRY-600)
            p.update(ticker='T'+str(i), base_probability_yes=.8,
                     probability_yes=.8, market_probability_yes=.8, features=[1., 0., 0., 0.])
            rows.append(dict(ticker=p['ticker'], opened_at=opened,
                             expires_at=opened+600, result_observed_at=opened+650,
                             result='no', settlement_prediction=p))
        result = model.predict(market(), feed(EXPIRY-600),
                               {'research_lab': {'history': rows}}, now=EXPIRY-600)
        # A fitted correction helps the base here but still loses to the market.
        for row in rows:
            row['settlement_prediction']['market_probability_yes'] = .1
        result = model.predict(market(), feed(EXPIRY-600),
                               {'research_lab': {'history': rows}}, now=EXPIRY-600)
        self.assertFalse(result['correction_validation']['active'])
        self.assertGreaterEqual(result['correction_validation']['samples'], 100)
        self.assertEqual(result['probability_yes'], result['base_probability_yes'])

    def test_capture_freezes_votes_wait_and_records_unavailable_forecasts(self):
        now = EXPIRY-600
        call = dict(ticker=TICKER, opened_at=now, expires_at=EXPIRY,
                    master_action='WAIT', specialists={'Trend': {'score': .4}},
                    settlement_prediction=model.predict(market(), feed(now), {}, now=now))
        state = {}
        self.assertTrue(model.record_observation(state, call, market()))
        self.assertFalse(model.record_observation(state, call, market()))
        call['specialists']['Trend']['score'] = -.9
        self.assertEqual(state['settlement_predictor']['pending'][0]['specialists']['Trend']['score'], .4)
        later = dict(call, opened_at=now+150, settlement_prediction=dict(available=False, reason='stale'))
        self.assertTrue(model.record_observation(state, later, market()))
        self.assertEqual(model.resolve_observations(state, lambda _: 'yes', now=EXPIRY-1), 0)
        self.assertEqual(model.resolve_observations(state, lambda _: 'yes', now=EXPIRY+30), 2)
        score = model.scorecard(state, as_of=EXPIRY+31)
        self.assertEqual(score['samples'], 1)
        self.assertEqual(score['coverage']['settled_markets'], 1)
        self.assertEqual(score['coverage']['unavailable_observations'], 1)
        self.assertEqual(score['coverage']['unavailable_reasons'], {'stale': 1})

    def test_checkpoints_do_not_use_later_or_duplicate_forecasts(self):
        history = []
        for lead, p in ((720, .6), (610, .7), (590, .99), (310, .8), (70, .9)):
            prediction = model.predict(market(), feed(EXPIRY-lead), {}, now=EXPIRY-lead)
            prediction['probability_yes'] = p
            history.append(dict(ticker=TICKER, opened_at=EXPIRY-lead, expires_at=EXPIRY,
                                result='yes', result_observed_at=EXPIRY+10,
                                settlement_prediction=prediction))
        score = model.scorecard({'settlement_predictor': {'history': history+copy.deepcopy(history)}},
                                as_of=EXPIRY+20)
        for label, expected in (('10m', .7), ('5m', .8), ('1m', .9)):
            checkpoint = score['by_horizon'][label]
            self.assertEqual(checkpoint['samples'], 1)
            self.assertAlmostEqual(checkpoint['brier'], (expected-1)**2)
            self.assertIn('log_loss', checkpoint)
            self.assertEqual(checkpoint['coin_flip_brier'], .25)

    def test_labels_not_yet_observed_cannot_enter_checkpoint_scores(self):
        state = {'settlement_predictor': {'history': []}}
        self.assertEqual(model.scorecard(state, as_of=EXPIRY)['by_horizon']['1m']['samples'], 0)
