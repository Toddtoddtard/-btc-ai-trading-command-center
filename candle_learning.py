"""Closed-minute candle education. Replay and genuinely live scores stay separate.

Definitions and limitations: docs/CANDLE_LEARNING.md. No trade execution here.
"""
from __future__ import annotations
import math
import time
import numpy as np
import pandas as pd

HORIZONS = (1, 5, 15)
FEATURE_NAMES = ('body', 'upper_wick', 'lower_wick', 'close_location', 'doji',
                 'engulfing', 'inside_bar', 'sweep_high', 'sweep_low',
                 'volume_relative', 'range_relative', 'return_3', 'return_15',
                 'return_60', 'wick_trend', 'wick_volume', 'taker_imbalance',
                 'taker_available', 'body_5m', 'wick_5m', 'body_15m', 'wick_15m')
COLS = ['ot', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qv', 'trades', 'tb', 'tq', 'x']


def closed_frame(rows, now=None):
    now = time.time() if now is None else float(now)
    f = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if f.empty or not {'time','open','high','low','close','volume'}.issubset(f.columns):
        return pd.DataFrame()
    f['time'] = pd.to_datetime(f['time'], utc=True, errors='coerce').dt.as_unit('ns')
    for c in ('open', 'high', 'low', 'close', 'volume'):
        f[c] = pd.to_numeric(f[c], errors='coerce')
    f = f.dropna(subset=['time', 'open', 'high', 'low', 'close', 'volume'])
    finite = np.isfinite(f[['open','high','low','close','volume']]).all(axis=1)
    valid = (finite & (f.close > 0) & (f.low > 0) & (f.volume >= 0) &
             (f.high >= f[['open', 'close', 'low']].max(axis=1)) &
             (f.low <= f[['open', 'close']].min(axis=1)))
    f = f[valid & ((f.time.astype('int64') / 1e9 + 60) <= now)]
    return f.drop_duplicates('time').sort_values('time').reset_index(drop=True)


def features(frame):
    """Only the supplied completed prefix is visible; no future context joins."""
    f = frame.tail(76)
    if len(f) < 61 or not (f.time.diff().dropna() == pd.Timedelta(minutes=1)).all():
        return None
    a, b = f.iloc[-1], f.iloc[-2]
    span = max(a.high-a.low, a.close*1e-9)
    body = (a.close-a.open)/span
    upper = (a.high-max(a.open,a.close))/span
    lower = (min(a.open,a.close)-a.low)/span
    prior = f.iloc[:-1].tail(20)
    atr = max(float((prior.high-prior.low).mean()), a.close*1e-9)
    trend = math.tanh((a.close/f.close.iloc[-16]-1)/.004)
    volume = np.clip(a.volume/max(float(prior.volume.mean()), 1e-9)-1, -1, 3)/3
    engulf = (1 if a.close > a.open and b.close < b.open and a.close >= b.open and a.open <= b.close
              else -1 if a.close < a.open and b.close > b.open and a.open >= b.close and a.close <= b.open else 0)
    tb = pd.to_numeric(pd.Series([a.get('tb', np.nan)]), errors='coerce').iloc[0]
    available = bool(np.isfinite(tb) and a.volume > 0 and 0 <= tb <= a.volume)
    values = [body, upper, lower, 2*(a.close-a.low)/span-1, float(abs(body)<.1), engulf,
              float(a.high<=b.high and a.low>=b.low),
              float(a.high>prior.high.max() and a.close<prior.high.max()),
              float(a.low<prior.low.min() and a.close>prior.low.min()), volume,
              math.tanh((a.high-a.low)/atr-1),
              math.tanh((a.close/f.close.iloc[-4]-1)/.002), trend,
              math.tanh((a.close/f.close.iloc[-61]-1)/.01),
              (lower-upper)*trend, (lower-upper)*volume,
              2*tb/a.volume-1 if available else 0, float(available)]
    # Aligned, fully closed 5m/15m candles; partial aggregation is excluded.
    cutoff = int(a.time.timestamp())+60
    for minutes in (5,15):
        end = cutoff//(minutes*60)*(minutes*60)
        group = f[(f.time.astype('int64')//10**9 >= end-minutes*60) &
                  (f.time.astype('int64')//10**9 < end)]
        if len(group) != minutes:
            values.extend([0.,0.])
            continue
        o,c = group.open.iloc[0], group.close.iloc[-1]
        h,l = group.high.max(), group.low.min()
        r = max(h-l, c*1e-9)
        values.extend([(c-o)/r, ((min(o,c)-l)-(h-max(o,c)))/r])
    return np.asarray(values, dtype=float)


def ensure(root):
    lab = root.setdefault('candle_learning', {})
    lab.setdefault('version', 1)
    lab.setdefault('feature_names', list(FEATURE_NAMES))
    lab.setdefault('cursor', None)
    lab.setdefault('pending', [])
    lab.setdefault('live_pending', [])
    lab.setdefault('minutes_observed', 0)
    lab.setdefault('windows_observed', 0)
    lab.setdefault('models', {str(h): {'weights': [0.]*len(FEATURE_NAMES), 'bias': 0.,
                                     'replay': [], 'trained': 0, 'live': [], 'enabled': False}
                              for h in HORIZONS})
    return lab


def probability(model, vector):
    z = np.clip(np.dot(model['weights'], vector)+model['bias'], -12,12)
    return float(1/(1+np.exp(-z)))


def score(p, baseline, outcome):
    return {'hit': int((p>=.5)==bool(outcome)), 'brier': (p-outcome)**2,
            'baseline_brier': (baseline-outcome)**2, 'baseline_hit': int((baseline>=.5)==bool(outcome))}


def summarize(rows):
    n = len(rows)
    return {'samples': n, **({k: sum(r[k] for r in rows)/n for k in rows[0]} if n else {})}


def update_gate(model):
    live, replay = summarize(model['live']), summarize(model['replay'])
    model['live_metrics'], model['replay_metrics'] = live, replay
    model['enabled'] = bool(live['samples'] >= 200 and replay['samples'] >= 500 and
                            live['hit'] >= .70 and live['hit'] >= live['baseline_hit'] and
                            live['brier'] < min(.245, live['baseline_brier']-.005) and
                            replay['brier'] < min(.25, replay['baseline_brier']))


def advance(root, frame, now=None):
    """Predict at each close, then train only when that prediction's deadline arrives."""
    now = time.time() if now is None else float(now)
    lab = ensure(root)
    f = closed_frame(frame, now)
    if f.empty:
        return lab
    prices = {int(r.time.timestamp())+60: float(r.close) for r in f.itertuples()}
    # Grade actual captured forecasts independently. Missing labels stay pending.
    unresolved = []
    for r in lab['live_pending']:
        if r['target'] > now or r['target'] not in prices:
            unresolved.append(r)
            continue
        m = lab['models'][r['h']]
        m['live'].append(score(r['p'], r['baseline'], int(prices[r['target']]>=r['start'])))
        m['live'] = m['live'][-500:]
    lab['live_pending'] = unresolved
    observed = 0
    lab['blocked_at'] = None
    for i, a in enumerate(f.itertuples()):
        cutoff = int(a.time.timestamp())+60
        if lab['cursor'] is not None and cutoff <= lab['cursor']:
            continue
        if lab['cursor'] is not None and cutoff != lab['cursor']+60:
            lab['blocked_at'] = lab['cursor']+60
            break
        vector = features(f.iloc[max(0,i-75):i+1])
        if vector is None:
            if lab['cursor'] is not None:
                lab['blocked_at'] = cutoff
                break
            continue
        pending = []
        for r in lab['pending']:
            if r['target'] > cutoff:
                pending.append(r)
                continue
            if r['target'] not in prices:
                pending.append(r)
                continue
            m = lab['models'][r['h']]
            outcome = int(prices[r['target']] >= r['start'])
            m['replay'].append(score(r['p'], r['baseline'], outcome))
            m['replay'] = m['replay'][-1000:]
            # SGD uses current weights; the score uses the saved pre-outcome probability.
            x = np.asarray(r['features'])
            error = outcome-probability(m,x)
            rate = .025/math.sqrt(max(1,m['trained']/2000))
            m['weights'] = np.clip(np.asarray(m['weights'])+rate*(error*x-.001*np.asarray(m['weights'])), -3,3).tolist()
            m['bias'] = float(np.clip(m['bias']+rate*error,-2,2))
            m['trained'] += 1
        lab['pending'] = pending
        baseline = .55 if vector[12] >= 0 else .45
        for h in HORIZONS:
            m = lab['models'][str(h)]
            lab['pending'].append({'h':str(h),'target':cutoff+h*60, 'start':float(a.close),
                                   'features':vector.tolist(),'p':probability(m,vector),'baseline':baseline})
        lab['cursor'] = cutoff
        observed += 1
        lab['minutes_observed'] += 1
        if cutoff % 900 == 0:
            lab['windows_observed'] += 1
    lab['minutes_this_run'] = observed
    lab['backlog_minutes'] = max(0, int(now//60*60-(lab['cursor'] or now))//60)
    lab['updated_at'] = now
    for m in lab['models'].values():
        update_gate(m)
    # Only count fresh real-time captures, at non-overlapping horizon intervals.
    last = f.iloc[-1]
    cutoff = int(last.time.timestamp())+60
    vector = features(f)
    if vector is not None and cutoff == int(now//60)*60 and lab['cursor'] == cutoff:
        baseline = .55 if vector[12]>=0 else .45
        for h in HORIZONS:
            m = lab['models'][str(h)]
            if cutoff >= m.get('last_live_origin', 0)+h*60:
                lab['live_pending'].append({'h':str(h),'target':cutoff+h*60,'start':float(last.close),
                                           'p':probability(m,vector),'baseline':baseline,'captured_at':now})
                m['last_live_origin'] = cutoff
    return lab


def fetch_catchup(get_json, base_url, root, now=None, max_pages=4):
    """Bound work without dropping a backlog. Resume from the durable cursor."""
    now = time.time() if now is None else float(now)
    cursor = ensure(root)['cursor']
    start = int((cursor-76*60) if cursor is not None else (now//60*60-2*86400)) * 1000
    end = int(now//60*60)*1000-1
    rows = []
    for _ in range(max_pages):
        if start > end:
            break
        page = get_json(base_url+'/api/v3/klines', {'symbol':'BTCUSDT','interval':'1m',
                        'startTime':start,'endTime':end,'limit':1000})
        if not isinstance(page,list) or not page:
            break
        rows.extend(page)
        next_start = max(int(r[0]) for r in page)+60000
        if next_start <= start:
            raise ValueError('Candle history pagination did not advance')
        start = next_start
        if len(page)<1000:
            break
    f = pd.DataFrame(rows,columns=COLS)
    f['time'] = pd.to_datetime(f.ot,unit='ms',utc=True)
    result = closed_frame(f,now)
    if result.empty:
        raise ValueError('No valid closed candles returned for catch-up')
    return result


def predict(rows, root, now=None):
    lab = root.get('candle_learning', {})
    if not lab.get('models'):
        return {}
    f = closed_frame(rows, now)
    if f.empty:
        return {}
    x = features(f)
    if x is None:
        return {}
    return {h: {'probability_up': probability(m,x), 'enabled': bool(m.get('enabled')),
                'samples':len(m.get('live',[])), 'source':'learned_candle_wicks'}
            for h,m in lab.get('models',{}).items()}
