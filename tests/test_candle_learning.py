import copy
import unittest
import numpy as np
import pandas as pd
from candle_learning import advance, features, closed_frame, fetch_catchup, ensure, predict


def candles(n=180):
    t = pd.date_range('2026-01-01',periods=n,freq='min',tz='UTC')
    close = 100+np.sin(np.arange(n)/6)+np.arange(n)*.005
    return pd.DataFrame({'time':t,'open':close-.02,'high':close+.12,'low':close-.1,
                         'close':close,'volume':10., 'tb':6.})


def end(f):
    return f.time.iloc[-1].timestamp()+60


class CandleLearningTests(unittest.TestCase):
    def test_replay_every_minute_and_idempotence(self):
        f=candles(); root={}
        lab=advance(root,f,now=end(f)+20)
        self.assertEqual(lab['minutes_observed'],120)
        self.assertEqual(lab['models']['15']['trained'],105)
        self.assertEqual(lab['models']['1']['trained'],119)
        self.assertTrue(any(lab['models']['15']['weights']))
        self.assertEqual(lab['models']['15']['live_metrics']['samples'],0)
        self.assertFalse(lab['models']['15']['enabled'])
        old=copy.deepcopy(lab['models'])
        advance(root,f,now=end(f)+25)
        self.assertEqual(old,lab['models'])
        self.assertEqual(len(lab['live_pending']),3)

    def test_chunked_replay_identical_and_future_not_seen(self):
        f=candles(); all_root={}; chunks={}
        advance(all_root,f,now=end(f))
        advance(chunks,f.iloc[:100],now=end(f.iloc[:100]))
        advance(chunks,f,now=end(f))
        for h in ('1','5','15'):
            a,b=all_root['candle_learning']['models'][h],chunks['candle_learning']['models'][h]
            self.assertEqual(a['weights'],b['weights'])
            self.assertEqual(a['replay'],b['replay'])
        prefix={}; full={}
        advance(prefix,f.iloc[:100],now=end(f.iloc[:100]))
        advance(full,f,now=end(f.iloc[:100]))
        self.assertEqual(prefix,full)

    def test_missing_minute_stalls_and_can_recover(self):
        f=candles(); root={}
        advance(root,f.iloc[:100],now=end(f.iloc[:100]))
        advance(root,f.drop(index=100),now=end(f))
        self.assertEqual(root['candle_learning']['cursor'],end(f.iloc[:100]))
        self.assertIsNotNone(root['candle_learning']['blocked_at'])
        advance(root,f,now=end(f))
        self.assertIsNone(root['candle_learning']['blocked_at'])
        self.assertEqual(root['candle_learning']['backlog_minutes'],0)

    def test_wicks_change_features_and_partial_candles_excluded(self):
        f=candles(80); g=f.copy()
        g.loc[79,'high']+=2
        self.assertNotEqual(features(f)[1],features(g)[1])
        self.assertEqual(len(closed_frame(f,now=end(f)-1)),79)
        g.loc[79,'low']=g.loc[79,'high']+1
        self.assertEqual(len(closed_frame(g,now=end(f))),79)

    def test_live_scoring_requires_real_capture_and_exact_deadline(self):
        f=candles(120); root={}
        advance(root,f.iloc[:100],now=end(f.iloc[:100])+10)
        advance(root,f.iloc[:110],now=end(f.iloc[:110])+10)
        lab=root['candle_learning']
        self.assertEqual(lab['models']['15']['live_metrics']['samples'],0)
        self.assertEqual(lab['models']['1']['live_metrics']['samples'],1)
        advance(root,f,now=end(f)+10)
        self.assertEqual(lab['models']['15']['live_metrics']['samples'],1)
        self.assertFalse(predict(f,root,now=end(f))['15']['enabled'])

    def test_fetch_pages_preserves_old_backlog(self):
        root={}; ensure(root)['cursor']=pd.Timestamp('2026-01-01T02:00:00Z').timestamp()
        calls=[]
        def get(url,params):
            calls.append(params)
            start=params['startTime']
            return [[start+i*60000,100,101,99,100,10,start+(i+1)*60000-1,0,0,6,0,0] for i in range(1000)]
        f=fetch_catchup(get,'https://example.com',root,now=pd.Timestamp('2026-01-04',tz='UTC').timestamp(),max_pages=2)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1]['startTime'],calls[0]['startTime']+1000*60000)
        self.assertEqual(root['candle_learning']['cursor'],pd.Timestamp('2026-01-01T02:00:00Z').timestamp())
        self.assertEqual(len(f),2000)

    def test_empty_feed_fails_visibly(self):
        with self.assertRaisesRegex(ValueError, 'No valid closed candles'):
            fetch_catchup(lambda *_args: [], 'https://example.com', {})
