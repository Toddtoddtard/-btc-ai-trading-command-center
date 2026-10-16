import copy
import unittest

import settlement_predictor as model


EXPIRY = 1791720000
TICKER = 'KXBTC15M-26OCT110800-00'


def market():
    return dict(ticker=TICKER, expires_at=EXPIRY, target=83000,
                strike_type='greater_or_equal', prob=.5)


def feed(now, price=83000):
    return dict(available=True, event_ticker=TICKER.rsplit('-', 1)[0],
                price=price, timestamp=now,
                ticks=[dict(timestamp=s, price=price) for s in range(EXPIRY-60, int(now))],
                candles=[dict(time=s, close=83000 + (10 if i % 2 else -10))
                         for i, s in enumerate(range(EXPIRY-3600, EXPIRY-60, 60))])


class SettlementPredictorTests(unittest.TestCase):
    def test_final_average_uses_observed_prefix_instead_of_last_spot(self):
        now = EXPIRY-10
        reference = feed(now, 82900)
        for tick in reference['ticks']:
            tick['price'] = 83100
        result = model.predict(market(), reference, {}, now=now)
        self.assertTrue(result['available'])
        self.assertEqual(result['outcome'], 'YES')
        self.assertGreater(result['average_probability_yes'], .99)
        self.assertGreater(result['expected_final_average'], 83060)
        self.assertFalse(result['affects_execution'])

    def test_contract_identity_freshness_rules_and_missing_prefix_fail_closed(self):
        now = EXPIRY-10
        for problem in ('identity', 'stale', 'missing', 'rule', 'expired', 'future'):
            m, f = market(), feed(now)
            if problem == 'identity': f['event_ticker'] = 'OTHER'
            if problem == 'stale': f['timestamp'] = now-31
            if problem == 'missing': f['ticks'].pop(0)
            if problem == 'rule': m['strike_type'] = 'between'
            if problem == 'expired': m['expires_at'] = now
            if problem == 'future': f['timestamp'] = now+1
            with self.subTest(problem=problem):
                self.assertFalse(model.predict(m, f, {}, now=now)['available'])

    def test_closed_reference_candles_only_and_midpoint_is_not_model_output(self):
        now = EXPIRY-600
        f = feed(now, 83100)
        first = model.predict(market(), f, {}, now=now)
        f['candles'].append(dict(time=now, close=99999999))
        second = model.predict(market(), f, {}, now=now)
        self.assertEqual(first['probability_yes'], second['probability_yes'])
        self.assertGreater(first['probability_yes'], .5)
        self.assertEqual(first['training_samples'], 0)

    def test_frozen_independent_predictions_use_only_official_observed_labels(self):
        now = EXPIRY-600
        prediction = model.predict(market(), feed(now), {}, now=now)
        row = dict(ticker=TICKER, opened_at=now, expires_at=EXPIRY,
                   settlement_prediction=prediction, result='yes',
                   result_observed_at=EXPIRY+30)
        duplicate = copy.deepcopy(row)
        duplicate['opened_at'] += 100
        duplicate['settlement_prediction']['probability_yes'] = .01
        state = {'research_lab': {'history': [row, duplicate]}}
        self.assertEqual(model.scorecard(state, as_of=EXPIRY)['samples'], 0)
        score = model.scorecard(state, as_of=EXPIRY+31)
        self.assertEqual(score['samples'], 1)
        self.assertEqual(score['brier'], (prediction['probability_yes']-1)**2)
        self.assertEqual(model.predict(market(), feed(now), state, now=now)['training_samples'], 0)

    def test_cent_threshold_includes_equality(self):
        result = model.predict(market(), feed(EXPIRY-1), {}, now=EXPIRY-1)
        self.assertGreater(result['average_probability_yes'], .5)
        self.assertEqual(result['comparison'], 'rounded final-minute average >= target')

    def test_last_reference_sample_is_observed_not_forecast_past_expiry(self):
        result = model.predict(market(), feed(EXPIRY-1), {}, now=EXPIRY-1)
        self.assertLess(result['average_sigma_dollars'], 1e-8)
        self.assertEqual(result['expected_final_average'], 83000)

    def test_research_saves_exact_frozen_prediction(self):
        from research_lab import register_shadow
        prediction = model.predict(market(), feed(EXPIRY-600), {}, now=EXPIRY-600)
        state = {}
        pending = dict(ticker=TICKER, opened_at=EXPIRY-600, expires_at=EXPIRY,
                       settlement_prediction=prediction)
        self.assertTrue(register_shadow(state, pending, dict(yes_bid=.45, yes_ask=.55, no_ask=.55)))
        self.assertEqual(state['research_lab']['pending'][0]['settlement_prediction'], prediction)
        prediction['probability_yes'] = .99
        self.assertNotEqual(state['research_lab']['pending'][0]['settlement_prediction'], prediction)

    def test_training_survives_restart_and_cannot_use_delayed_labels(self):
        import json
        now = EXPIRY-600
        prior = model.predict(market(), feed(now), {}, now=now)
        rows = []
        for index in range(100):
            p = copy.deepcopy(prior)
            ticker = 'KXBTC15M-26OCT110800-'+str(index+1)
            p['ticker'] = ticker
            rows.append(dict(ticker=ticker, opened_at=now-3600-index*900,
                             expires_at=now-2700-index*900, result_observed_at=now-2600-index*900,
                             result='yes', settlement_prediction=p))
        state = json.loads(json.dumps({'research_lab': {'history': rows}}))
        trained = model.predict(market(), feed(now), state, now=now)
        self.assertEqual(trained['training_samples'], 100)
        self.assertFalse(trained['correction_validation']['active'])
        self.assertEqual(trained['probability_yes'], prior['probability_yes'])
        rows[-1]['result_observed_at'] = now+1
        blocked = model.predict(market(), feed(now), {'research_lab': {'history': rows}}, now=now)
        self.assertEqual(blocked['training_samples'], 99)
        self.assertEqual(blocked['probability_yes'], prior['probability_yes'])

    def test_invalid_stored_probability_cannot_crash_training_or_scorecard(self):
        now = EXPIRY-600
        for field in ('base_probability_yes', 'market_probability_yes'):
            p = model.predict(market(), feed(now), {}, now=now)
            p[field] = None
            rows = [dict(ticker='T'+str(i), opened_at=now-3600, expires_at=now-2700,
                         result_observed_at=now-2600, result='yes', settlement_prediction=dict(p, ticker='T'+str(i)))
                    for i in range(100)]
            state = {'research_lab': {'history': rows}}
            with self.subTest(field=field):
                self.assertEqual(model.scorecard(state, as_of=now)['samples'], 0)
                self.assertEqual(model.predict(market(), feed(now), state, now=now)['training_samples'], 0)
