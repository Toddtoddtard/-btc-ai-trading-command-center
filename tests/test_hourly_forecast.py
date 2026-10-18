import copy
import json
import unittest

import numpy as np
import pandas as pd

from hourly_forecast import predict, capture, resolve, scorecard, fetch_markets, update


NOW = pd.Timestamp('2026-10-18T17:00:00Z').timestamp()


def frame(now=NOW):
    return pd.DataFrame(dict(time=pd.date_range(end=pd.Timestamp(now-60, unit='s', tz='UTC'),
                                               periods=90, freq='min'),
                             close=np.full(90, 81000.), atr14=np.full(90, 30.)))


def context(now=NOW, remaining=3600, ticker='KXBTCD-26OCT1814-T81000'):
    market=dict(ticker=ticker, event_ticker=ticker.rsplit('-T', 1)[0],
                floor_strike=81000., strike_type='greater', status='open',
                close_time=pd.Timestamp(now+remaining, unit='s', tz='UTC').isoformat(),
                yes_bid_dollars='.49', yes_ask_dollars='.51')
    return dict(event_markets=[market], close_ts=now+remaining)


def bots():
    return {'Trend AI':dict(score=.8, confidence=.8),
            'Momentum AI':dict(score=-.8, confidence=.8),
            'Pattern AI':dict(score=.5, confidence=.7, model_version=3),
            'Political Event Watch AI':dict(score=0., confidence=0., event_status='INACTIVE'),
            'Combination AI':dict(score=1., confidence=.99)}


class HourlyForecastTests(unittest.TestCase):
    def test_every_bot_is_visible_and_combination_does_not_vote_twice(self):
        b=bots(); p=predict(frame(),b,context(),81000.,now=NOW)
        self.assertTrue(set(b).issubset(p['specialist_forecasts']))
        self.assertEqual(p['specialist_forecasts']['Combination AI']['vote_share'],0)
        self.assertIsNone(p['specialist_forecasts']['Political Event Watch AI']['predicted_yes'])
        self.assertEqual(p['confidence_basis'],'signal agreement, not measured accuracy')
        without=copy.deepcopy(b); without.pop('Combination AI')
        self.assertEqual(p['target_price'],predict(frame(),without,context(),81000.,now=NOW)['target_price'])
        self.assertAlmostEqual(sum(r['vote_share'] for r in p['specialist_forecasts'].values()),1.)

    def test_forecast_scales_to_remaining_time_and_uses_hourly_context(self):
        b={'Trend AI':dict(score=.8,confidence=.8),
           'Kalshi Context AI':dict(score=-1.,confidence=.99,reason='15-minute strike')}
        full=predict(frame(),b,context(),81000.,now=NOW)
        short=predict(frame(),b,context(remaining=900),81000.,now=NOW)
        self.assertAlmostEqual(short['projected_move'],full['projected_move']/4)
        self.assertEqual(full['specialist_forecasts']['Kalshi Context AI']['score'],0.)

    def test_capture_is_immutable_one_per_event_and_survives_json(self):
        root={}; p=predict(frame(),bots(),context(),81000.,now=NOW)
        self.assertTrue(capture(root,p,now=NOW))
        frozen=copy.deepcopy(root['pending'])
        p['specialist_forecasts']['Trend AI']['score']=-1
        self.assertFalse(capture(root,p,now=NOW+10))
        self.assertEqual(root['pending'],frozen)
        self.assertEqual(json.loads(json.dumps(root)),root)

    def test_grades_only_official_results_after_expiry_once_and_learns_separately(self):
        root={}; p=predict(frame(),bots(),context(),81000.,now=NOW)
        capture(root,p,now=NOW)
        calls=[]
        def read(ticker): calls.append(ticker); return 'yes'
        self.assertEqual(resolve(root,read,now=NOW+3599),0)
        self.assertEqual(calls,[])
        self.assertEqual(resolve(root,lambda _:None,now=NOW+3601),0)
        self.assertEqual(len(root['pending']),1)
        self.assertEqual(resolve(root,read,now=NOW+3602),1)
        self.assertEqual(resolve(root,read,now=NOW+3610),0)
        stats=scorecard(root,now=NOW+3610)
        self.assertEqual(stats['samples'],1)
        self.assertEqual(stats['specialists']['Trend AI']['accuracy'],1.)
        self.assertEqual(stats['specialists']['Momentum AI']['accuracy'],0.)
        self.assertEqual(stats['specialists']['Political Event Watch AI']['samples'],0)
        self.assertEqual(scorecard(root,now=NOW+3500)['samples'],0)

    def test_weights_require_prior_labels_and_do_not_inherit_15m_or_old_models(self):
        root={}
        for i in range(25):
            at=NOW+i*7200
            p=predict(frame(at),bots(),context(at,ticker=f'KXBTCD-E{i}-T81000'),81000.,root,now=at)
            capture(root,p,now=at); resolve(root,lambda _:'yes',now=at+3601)
        at=NOW+26*7200
        p=predict(frame(at),bots(),context(at),81000.,root,now=at)
        members=p['specialist_forecasts']
        self.assertGreater(members['Trend AI']['learned_multiplier'],1.)
        self.assertGreater(scorecard(root,now=at)['specialists']['Trend AI']['unique_saves'],0)
        self.assertLess(members['Momentum AI']['learned_multiplier'],1.)
        early=predict(frame(),bots(),context(),81000.,root,now=NOW)
        self.assertEqual(early['specialist_forecasts']['Trend AI']['learned_multiplier'],1.)
        newer=bots(); newer['Pattern AI']['model_version']=4
        p=predict(frame(at),newer,context(at),81000.,root,now=at)
        self.assertEqual(p['specialist_forecasts']['Pattern AI']['graded_samples'],0)
        unrelated={'specialists':{'Trend AI':{'samples':9999,'direction_hits':0}}}
        self.assertEqual(predict(frame(),bots(),context(),81000.,unrelated,now=NOW)['target_price'],
                         predict(frame(),bots(),context(),81000.,now=NOW)['target_price'])

    def test_expired_stale_and_unsupported_inputs_cannot_capture(self):
        for c,f in ((context(remaining=-1),frame()),(context(),frame(NOW-600)),
                    ({'event_markets':[dict(context()['event_markets'][0],strike_type='between')]},frame())):
            p=predict(f,bots(),c,81000.,now=NOW)
            self.assertFalse(capture({},p,now=NOW))

    def test_less_strike_inverts_yes_without_inverting_price_forecast(self):
        c=context(); c['event_markets'][0].update(strike_type='less',cap_strike=81000.)
        p=predict(frame(),{'Trend AI':dict(score=.8,confidence=.8)},c,81000.,now=NOW)
        self.assertFalse(p['specialist_forecasts']['Trend AI']['predicted_yes'])

    def test_fetch_uses_public_hourly_series_and_keeps_nearest_event(self):
        def read(path,params):
            self.assertEqual(path,'/markets')
            self.assertEqual(params['series_ticker'],'KXBTCD')
            return {'markets':[context()['event_markets'][0],context(remaining=7200)['event_markets'][0]]}
        c=fetch_markets(read,now=NOW)
        self.assertEqual(len(c['event_markets']),1)
        self.assertEqual(c['close_ts'],NOW+3600)

    def test_worker_cycle_retains_pending_on_restart_then_resolves_exact_contract(self):
        root={}
        def read(path,params): return {'markets':context()['event_markets']}
        update(root,frame(),bots(),read,lambda _:None,now=NOW)
        restarted=json.loads(json.dumps(root,allow_nan=False))
        self.assertEqual(len(restarted['pending']),1)
        update(restarted,frame(),bots(),read,lambda _:'yes',now=NOW+10)
        self.assertEqual(restarted['scorecard']['samples'],0)
        c=context(NOW+3601,ticker='KXBTCD-NEXT-T81000')
        calls=[]
        def result(ticker): calls.append(ticker); return 'yes'
        update(restarted,frame(NOW+3601),bots(),lambda *args:{'markets':c['event_markets']},
               result,now=NOW+3601)
        self.assertEqual(calls,['KXBTCD-26OCT1814-T81000'])
        self.assertEqual(restarted['scorecard']['samples'],1)
        self.assertEqual(restarted['scorecard']['pending_events'],1)
        self.assertNotIn('reason',restarted['history'][0]['specialist_forecasts']['Trend AI'])
        self.assertEqual(json.loads(json.dumps(restarted,allow_nan=False)),restarted)

    def test_result_reader_completion_time_is_the_label_availability_time(self):
        from unittest.mock import patch
        root={}; capture(root,predict(frame(),bots(),context(),81000.,now=NOW),now=NOW)
        with patch('hourly_forecast.time.time',side_effect=[NOW+3601,NOW+3610,NOW+3611]):
            resolve(root,lambda _:'yes')
        self.assertEqual(root['history'][0]['result_observed_at'],NOW+3610)
        self.assertEqual(scorecard(root,now=NOW+3605)['samples'],0)

    def test_multiple_strikes_cannot_count_the_same_hour_twice(self):
        root={}; p=predict(frame(),bots(),context(),81000.,now=NOW)
        capture(root,p,now=NOW)
        other=copy.deepcopy(p); other['ticker']='KXBTCD-26OCT1814-T81250'
        other['nearest_market']['ticker']=other['ticker']
        self.assertFalse(capture(root,other,now=NOW))
