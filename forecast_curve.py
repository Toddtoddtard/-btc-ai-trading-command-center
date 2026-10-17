"""Closed-candle, same-source 1..15 minute curves with causal baseline checks.

A small direct ridge regression predicts each minute separately. Validation
origins are 15 minutes apart and each fit sees only labels already completed
at that origin. This is a chart research model, never an execution override.
"""
from __future__ import annotations
import math
import time
import numpy as np
import pandas as pd

STEPS = np.arange(1, 16, dtype=float)
LOOKBACK = 20
MIN_TRAIN = 32
MIN_VALIDATION = 8
HISTORY_LIMIT = 360
SOURCE = 'Kalshi BTC/USD chart feed'


def closed_rows(rows, now):
    """Keep the latest contiguous closed prefix; never close a time gap by dropping it."""
    valid = {}
    for row in rows:
        try:
            stamp = pd.Timestamp(row['time'])
            stamp = stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')
            at = int(stamp.timestamp())
            vals = [float(row[k]) for k in ('open','high','low','close')]
            o,h,l,c = vals
            if (at % 60 or at+60 > now or not all(math.isfinite(v) for v in vals)
                    or l <= 0 or l > min(o,c) or h < max(o,c)):
                continue
            valid[at] = dict(time=stamp.isoformat(),open=o,high=h,low=l,close=c)
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
    keys = sorted(valid)[-HISTORY_LIMIT:]
    start = 0
    for i in range(1,len(keys)):
        if keys[i] != keys[i-1]+60:
            start = i
    return [valid[t] for t in keys[start:]]


def _design(rows):
    c = np.asarray([r['close'] for r in rows])
    ranges = np.asarray([r['high']-r['low'] for r in rows])
    features, scales = [], []
    for i in range(LOOKBACK-1,len(c)):
        scale = max(float(ranges[i-19:i+1].mean()),c[i]*1e-6)
        r = rows[i]
        span = max(r['high']-r['low'],c[i]*1e-6)
        x = [1.,(c[i]-c[i-1])/scale,(c[i]-c[i-3])/(scale*3),
             (c[i]-c[i-8])/(scale*8),(c[i]-c[i-15])/(scale*15),
             (c[i]-c[i-19:i+1].mean())/(scale*5),
             (r['close']-r['open'])/span,
             ((min(r['open'],r['close'])-r['low'])-(r['high']-max(r['open'],r['close'])))/span]
        features.append(np.clip(x,-5,5))
        scales.append(scale)
    return c,np.asarray(features),np.asarray(scales)


def _legacy(c, index, scale, config):
    cfg = dict(w_ret3=.46,w_ret8=.34,w_ret15=.20,momentum_scale=2.2,bias=0.)
    cfg.update({k:float(config[k]) for k in cfg if k in config and math.isfinite(float(config[k]))})
    directional = sum(cfg['w_ret'+str(h)]*(c[index]/c[index-h]-1) for h in (3,8,15))+cfg['bias']
    move = c[index]*np.clip(directional,-.012,.012)*cfg['momentum_scale']
    progress = STEPS/15
    # Compare the old displayed center, including its artificial minimum move.
    move = math.copysign(max(abs(move),scale*.35,c[index]*.00015),move or 1.)
    return move*progress**2*(3-2*progress)/scale


def _fit_predict(x,y,origin):
    # y[k] completes 15 minutes after x[k]. At origin, only k<=origin-15 exists.
    end = origin-15+1
    if end < MIN_TRAIN:
        return None
    train = x[:end]
    penalty = np.eye(x.shape[1])*8.
    penalty[0,0] = 2.
    weights = np.linalg.solve(train.T@train+penalty,train.T@y[:end])
    return np.clip(x[origin]@weights,-12*np.sqrt(STEPS),12*np.sqrt(STEPS))


def build_curve(rows, now=None, config=None):
    now = time.time() if now is None else float(now)
    config = config or {}
    rows = closed_rows(rows,now)
    result = dict(version=1,source=SOURCE,affects_execution=False,closed_candles=len(rows),
                  method='unavailable',points=[],as_of=0.,validation={'samples':0})
    if len(rows)<LOOKBACK:
        return result
    c,x,scale = _design(rows)
    as_of = pd.Timestamp(rows[-1]['time']).timestamp()+60
    result['as_of'] = as_of
    # For every origin, all fifteen future labels must exist. Newest origin
    # leaves a full 15-minute embargo before its outcome is used for evaluation.
    y = np.asarray([(c[i+1:i+16]-c[i])/scale[i-(LOOKBACK-1)]
                    for i in range(LOOKBACK-1,len(c)-15)])
    observations=[]
    last_origin=len(x)-16
    origins=list(range(last_origin,max(MIN_TRAIN+13,last_origin-15*MIN_VALIDATION),-15))[::-1]
    for origin in origins:
        prediction=_fit_predict(x,y,origin)
        if prediction is None:
            continue
        legacy=_legacy(c,origin+LOOKBACK-1,scale[origin],config)
        actual=y[origin]
        observations.append(dict(candidate=np.abs(prediction-actual),flat=np.abs(actual),
                                 legacy=np.abs(legacy-actual)))
    metrics={'samples':len(observations),'scope':'chronological non-overlapping 15-minute paths'}
    for method in ('candidate','flat','legacy'):
        if observations:
            metrics[method+'_mae']=float(np.mean([o[method] for o in observations]))
    candidate=_fit_predict(x,y,len(x)-1)
    qualified=(len(observations)>=MIN_VALIDATION and candidate is not None and
               metrics['candidate_mae']<.98*min(metrics['flat_mae'],metrics['legacy_mae']) and
               np.mean([o['candidate'] for o in observations[-4:]])<
               min(np.mean([o['flat'] for o in observations[-4:]]),np.mean([o['legacy'] for o in observations[-4:]])))
    method='validated_curve' if qualified else 'flat_baseline'
    offsets=candidate if qualified else np.zeros(15)
    # Without evidence there is no invented directional lean. A baseline that
    # beats flat on held-out paths is an allowed fallback, not a learned curve.
    if not qualified and len(observations)>=MIN_VALIDATION and metrics['legacy_mae']<metrics['flat_mae']*.98:
        method='momentum_baseline'
        offsets=_legacy(c,len(c)-1,scale[-1],config)
    baseline_errors=[o['candidate' if qualified else ('legacy' if method=='momentum_baseline' else 'flat')]
                     for o in observations]
    if baseline_errors:
        width=np.quantile(np.asarray(baseline_errors),.8,axis=0)*scale[-1]
    else:
        width=np.std(np.diff(c[-20:]))*np.sqrt(STEPS)*1.28
    # Empirical error envelope, not predicted candle extremes or certified coverage.
    closes=c[-1]+offsets*scale[-1]
    result.update(method=method,validation=metrics,anchor=float(c[-1]),
                  range_basis='empirical absolute-error envelope; coverage unvalidated',
                  points=[dict(timestamp=as_of+int(step)*60,close=float(max(close,c[-1]*.5)),
                               lower=float(max(close-w,c[-1]*.5)),upper=float(max(close+w,c[-1]*.5)))
                          for step,close,w in zip(STEPS,closes,width)])
    return result


def update_curve(root, rows, now=None, config=None):
    """Accumulate official bars and independently score frozen live chart paths."""
    now=time.time() if now is None else float(now)
    history=closed_rows(list(root.get('history',[]))+list(rows),now)
    prices={pd.Timestamp(r['time']).timestamp()+60:r['close'] for r in history}
    unresolved=[]
    scores=root.setdefault('live_scores',[])
    for capture in root.get('pending',[]):
        points=capture['points']
        if not all(p['timestamp'] in prices for p in points):
            # Bounded retention; never borrow a neighboring candle to fill a gap.
            if points[-1]['timestamp']>=now-HISTORY_LIMIT*60:
                unresolved.append(capture)
            continue
        actual=np.asarray([prices[p['timestamp']] for p in points])
        pred=np.asarray([p['close'] for p in points])
        anchor=capture['anchor']
        scores.append(dict(path_mae=float(np.mean(np.abs(actual-pred))),
                           flat_mae=float(np.mean(np.abs(actual-anchor))),
                           terminal_correct=int((pred[-1]>=anchor)==(actual[-1]>=anchor)),
                           method=capture['method']))
    root.update(history=history,pending=unresolved,live_scores=scores[-200:],
                affects_execution=False,source=SOURCE)
    latest=root.get('latest') or {}
    end=pd.Timestamp(history[-1]['time']).timestamp()+60 if history else 0
    if latest.get('as_of') != end or not latest:
        latest=build_curve(history,now,config)
        root['latest']=latest
    # Capture once every full horizon, only while the origin is genuinely fresh.
    if latest.get('points') and 0<=now-latest['as_of']<60 and latest['as_of']>=root.get('last_capture',0)+900:
        root['pending'].append({k:latest[k] for k in ('as_of','points','anchor','method')})
        root['last_capture']=latest['as_of']
    n=len(root['live_scores'])
    root['live_metrics']={'samples':n,'scope':'prospective non-overlapping observed 15-minute paths'}
    if n:
        for key in ('path_mae','flat_mae','terminal_correct'):
            root['live_metrics'][key]=sum(r[key] for r in root['live_scores'])/n
    return latest
