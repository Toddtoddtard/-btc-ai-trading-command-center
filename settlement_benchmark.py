"""Read-only chronological settlement experiments; never a promotion engine.

Three fixed market-offset logistic candidates. Select on the development prefix
only, then report the reserved latest 100 markets separately. These are reused
retained observations, not new prospective evidence or an untouched data source.
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from contract_calibration import horizon_bucket, finite
from outcome_timing import timestamp
from settlement_predictor import VERSION

KINDS = ('bias','shape','context')
MIN_TRAIN, MIN_DEVELOPMENT, HOLDOUT, LOOKBACK = 150, 100, 100, 500


def collect_observations(state, as_of):
    unique={}
    history=(state.get('research_lab') or {}).get('history',[])+(state.get('settlement_predictor') or {}).get('history',[])
    for r in history:
        p=r.get('settlement_prediction') or {}
        opened,expiry=finite(r.get('opened_at')),finite(r.get('expires_at'))
        observed=timestamp(r.get('result_observed_at'))
        quotes,reference=finite(p.get('quotes_observed_at')),finite(p.get('reference_timestamp'))
        market,base,prob=map(finite,(p.get('market_probability_yes'),p.get('base_probability_yes'),p.get('probability_yes')))
        features=p.get('features')
        if (not p.get('available') or p.get('version')!=VERSION or not r.get('ticker')
            or p.get('ticker')!=r['ticker'] or r.get('result') not in ('yes','no')
            or opened is None or expiry is None or observed is None or not opened<expiry<=observed<=as_of
            or p.get('captured_at')!=opened or p.get('expires_at')!=expiry
            or quotes is None or reference is None
            or not 0<=opened-quotes<=30 or not 0<=opened-reference<=30
            or any(v is None or not 0<=v<=1 for v in (market,base,prob))
            or not isinstance(features,list) or len(features)!=4 or any(finite(v) is None for v in features)):
            continue
        bucket=horizon_bucket(expiry-opened)
        if bucket is None:
            continue
        key=(r['ticker'],bucket)
        if key not in unique or opened<unique[key]['opened_at']:
            unique[key]=r
    return sorted(unique.values(),key=lambda r:(r['opened_at'],r['ticker']))


def logit(p):
    p=max(1e-6,min(1-1e-6,p))
    return math.log(p/(1-p))


def vector(row,kind):
    p=row['settlement_prediction'];m=p['market_probability_yes'];raw=p['base_probability_yes'];f=p['features']
    values=[1.,logit(m)/3,(logit(raw)-logit(m))/3,f[2]*10,f[3]*10]
    return np.clip(values[:{'bias':1,'shape':2,'context':5}[kind]],-4,4)


def candidate_probability(prior,row,kind):
    # Callers supply only labels already observed at this forecast's timestamp.
    prior=prior[-LOOKBACK:]
    x=np.array([vector(r,kind) for r in prior])
    y=np.array([r['result']=='yes' for r in prior],float)
    offset=np.array([logit(r['settlement_prediction']['market_probability_yes']) for r in prior])
    w=np.zeros(x.shape[1]);penalty=10.
    for _ in range(15):
        p=1/(1+np.exp(-np.clip(offset+x@w,-25,25)))
        gradient=x.T@(y-p)-penalty*w
        hessian=x.T@((p*(1-p))[:,None]*x)+penalty*np.eye(len(w))
        step=np.linalg.solve(hessian,gradient);w+=step
        if np.linalg.norm(step)<1e-7:
            break
    market=row['settlement_prediction']['market_probability_yes']
    result=1/(1+np.exp(-np.clip(logit(market)+vector(row,kind)@w,-25,25)))
    return float(np.clip(result,max(.000001,market-.10),min(.999999,market+.10)))


def summary(rows,key):
    outcomes=np.array([r['y'] for r in rows]);p=np.array([r[key] for r in rows]);market=np.array([r['market'] for r in rows])
    gains=(market-outcomes)**2-(p-outcomes)**2
    mean=float(np.mean(gains))
    width=1.96*float(np.std(gains,ddof=1))/math.sqrt(len(rows))
    return dict(samples=len(rows),accuracy=float(np.mean((p>=.5)==outcomes)),
                brier=float(np.mean((p-outcomes)**2)),market_accuracy=float(np.mean((market>=.5)==outcomes)),
                market_brier=float(np.mean((market-outcomes)**2)),brier_gain=mean,
                brier_gain_low=mean-width,brier_gain_high=mean+width)


def benchmark(state,as_of=None):
    as_of=time.time() if as_of is None else float(as_of)
    all_rows=collect_observations(state,as_of)
    # Reserve the same contracts across every timing group. A missing late
    # capture must not put a market in development at one horizon and test at
    # another. Algorithm selection never sees any reserved contract's labels.
    expiries={r['ticker']:r['expires_at'] for r in all_rows}
    reserved=set(sorted(expiries,key=lambda t:(expiries[t],t))[-HOLDOUT:])
    reports={};dev_gains={k:[] for k in KINDS}
    for bucket in ('10m+','5m+','1m+'):
        rows=[r for r in all_rows if horizon_bucket(r['expires_at']-r['opened_at'])==bucket]
        if len(rows)<MIN_TRAIN+MIN_DEVELOPMENT+2:
            continue
        evaluated=[]
        for i,row in enumerate(rows):
            prior=[r for r in rows[:i] if timestamp(r['result_observed_at'])<=row['opened_at']]
            if len(prior)<MIN_TRAIN:
                continue
            p=row['settlement_prediction']
            result=dict(y=int(row['result']=='yes'),ticker=row['ticker'],market=p['market_probability_yes'],
                        independent=p['probability_yes'])
            for kind in KINDS:
                result[kind]=candidate_probability(prior,row,kind)
            evaluated.append(result)
        dev=[r for r in evaluated if r['ticker'] not in reserved]
        test=[r for r in evaluated if r['ticker'] in reserved]
        if len(dev)<MIN_DEVELOPMENT or len(test)<2:
            continue
        reports[bucket]=dict(development={k:summary(dev,k) for k in KINDS},
                             holdout={k:summary(test,k) for k in (*KINDS,'independent')})
        for kind in KINDS:
            dev_gains[kind].append(reports[bucket]['development'][kind]['brier_gain'])
    means={k:sum(v)/len(v) for k,v in dev_gains.items() if v}
    selected=max(means,key=means.get) if means else None
    return dict(version='settlement-benchmark-v1',affects_execution=False,as_of=as_of,
                selected_on_development_only=selected,development_mean_gain=means,by_horizon=reports,
                source_updated_at=state.get('updated_at'),reserved_contracts=len(reserved),
                holdout_scope='Same latest 100 contracts reserved across all horizons; candidate parameters update only after observed prior labels.',
                limitations='Reused retained snapshot; reserved chronological test within this experiment, not virgin data or live results. Approximate paired intervals ignore serial dependence and model-selection uncertainty. No fees/fills are simulated; no promotion authority.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state');parser.add_argument('--output',required=True);parser.add_argument('--as-of',type=float)
    args=parser.parse_args();raw=Path(args.state).read_bytes()
    report=benchmark(json.loads(raw),args.as_of)
    report['source_sha256']=hashlib.sha256(raw).hexdigest()
    Path(args.output).write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(selected=report['selected_on_development_only'],horizons=list(report['by_horizon']),affects_execution=False)))
