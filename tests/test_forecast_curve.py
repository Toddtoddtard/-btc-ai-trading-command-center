"""Real chronology, baseline selection and persisted live-path regressions."""
import copy
import unittest
import numpy as np
import pandas as pd
from forecast_curve import build_curve, update_curve


def candles(n=360):
    # A deterministic turning series, not evidence of BTC predictability.
    t = pd.date_range('2026-01-01', periods=n, freq='min', tz='UTC')
    c = 83000 + 40*np.sin(np.arange(n)/8) + 10*np.sin(np.arange(n)/3)
    return [dict(time=stamp.isoformat(), open=float(v-1), high=float(v+4),
                 low=float(v-4), close=float(v)) for stamp,v in zip(t,c)]


def cutoff(rows):
    return pd.Timestamp(rows[-1]['time']).timestamp()+60


class ForecastCurveTests(unittest.TestCase):
    def test_unvalidated_model_path_is_not_replaced_with_a_flat_line(self):
        rows=candles(90)
        result=build_curve(rows,now=cutoff(rows))
        self.assertEqual(result['method'],'experimental_curve')
        self.assertFalse(result['affects_execution'])
        self.assertLess(result['validation']['samples'],8)
        self.assertEqual(len(result['points']),15)
        self.assertGreater(np.ptp([p['close'] for p in result['points']]),1)

    def test_insufficient_training_does_not_masquerade_as_a_price_forecast(self):
        rows=candles(40)
        result=build_curve(rows,now=cutoff(rows))
        self.assertEqual(result['method'],'unavailable')
        self.assertEqual(result['points'],[])

    def test_failed_baseline_comparison_keeps_research_path_and_candidate_error(self):
        rows=candles()
        values=83000+np.random.default_rng(2).normal(0,10,len(rows)).cumsum()
        for r,v in zip(rows,values):
            r.update(open=v-1,high=v+4,low=v-4,close=v)
        result=build_curve(rows,now=cutoff(rows))
        self.assertEqual(result['method'],'experimental_curve')
        self.assertEqual(result['validation']['samples'],8)
        self.assertGreater(result['validation']['candidate_mae'],result['validation']['flat_mae'])
        self.assertGreater(np.ptp([p['close'] for p in result['points']]),1)
        self.assertTrue(all(p['lower']<=p['close']<=p['upper'] for p in result['points']))
        self.assertFalse(result['affects_execution'])

    def test_future_and_forming_candles_cannot_change_a_forecast(self):
        rows=candles(); now=cutoff(rows[:260])
        a=build_curve(rows[:260], now=now)
        b=build_curve(rows, now=now)
        self.assertEqual(a,b)
        self.assertEqual(len(a['points']),15)
        self.assertEqual(a['points'][-1]['timestamp'],now+900)

    def test_learned_minute_targets_can_turn_and_beat_flat_on_unseen_prefixes(self):
        rows=candles(); result=build_curve(rows,now=cutoff(rows))
        self.assertEqual(result['method'],'validated_curve')
        self.assertGreaterEqual(result['validation']['samples'],8)
        self.assertLess(result['validation']['candidate_mae'],result['validation']['flat_mae'])
        deltas=np.diff([rows[-1]['close']]+[p['close'] for p in result['points']])
        self.assertTrue((deltas>0).any() and (deltas<0).any())

    def test_flat_market_does_not_invent_upside_waves_or_target_attraction(self):
        rows=candles(60)
        for r in rows:r.update(open=83000.,high=83000.,low=83000.,close=83000.)
        r=build_curve(rows,now=cutoff(rows))
        self.assertTrue(all(p['close']==83000 for p in r['points']))
        self.assertNotEqual(r['method'],'validated_curve')

    def test_gap_is_not_compressed_and_bad_bars_are_not_used(self):
        rows=candles()
        result=build_curve(rows[:200]+rows[201:],now=cutoff(rows))
        self.assertLessEqual(result['closed_candles'],159)
        bad=copy.deepcopy(rows); bad[-1]['high']=float('nan')
        self.assertLess(build_curve(bad,now=cutoff(rows))['as_of'],cutoff(rows))

    def test_live_scores_require_capture_then_complete_exact_labels_and_no_duplicates(self):
        rows=candles(); root={}
        update_curve(root,rows[:260],now=cutoff(rows[:260])+10)
        frozen=copy.deepcopy(root['pending'])
        update_curve(root,rows[:260],now=cutoff(rows[:260])+20)
        self.assertEqual(frozen,root['pending'])
        self.assertEqual(root['live_metrics']['samples'],0)
        update_curve(root,rows[:275],now=cutoff(rows[:275])+10)
        self.assertEqual(root['live_metrics']['samples'],1)
        update_curve(root,rows[:275],now=cutoff(rows[:275])+20)
        self.assertEqual(root['live_metrics']['samples'],1)
        self.assertFalse(root['affects_execution'])
        self.assertLessEqual(len(root['history']),360)
