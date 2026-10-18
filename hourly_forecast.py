"""Hourly specialist targets, frozen event captures and official-only learning.

Hourly evidence is independent of the 15-minute council. Scores are signals,
not calibrated probabilities; no orders are placed by this module.
"""
import copy
import math
import time

import pandas as pd

from ai_core import kalshi_context_result
from council_v4 import BASE_WEIGHTS, specialist_active

VERSION = 1
MIN_LEARNING = 20
HISTORY_LIMIT = 1000
RULES = {'greater', 'greater_equal', 'less', 'less_equal'}


def _number(value, default=None):
    try:
        value=float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _expiry(market):
    value=_number(market.get('_close_ts'))
    if value is not None:
        return value
    try:
        return pd.Timestamp(market.get('close_time') or market.get('expiration_time')
                            or market.get('expected_expiration_time')).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _strike(market):
    key='cap_strike' if market.get('strike_type') in {'less', 'less_equal'} else 'floor_strike'
    return _number(market.get(key), _number(market.get('_strike')))


def _markets(rows, now):
    valid=[]
    for row in rows:
        expiry, strike=_expiry(row), _strike(row)
        if (row.get('strike_type') not in RULES or expiry is None or strike is None
                or expiry<=now or strike<=0 or not str(row.get('ticker', '')).startswith('KXBTCD-')
                or row.get('status', 'open') not in {'open', 'active'}):
            continue
        valid.append(dict(row, _strike=strike, _close_ts=expiry))
    end=min((r['_close_ts'] for r in valid), default=None)
    return dict(event_markets=[r for r in valid if r['_close_ts']==end], close_ts=end)


def fetch_markets(read, now=None):
    """Use the existing public Kalshi reader; no key or new service."""
    now=time.time() if now is None else now
    rows=[]; cursor=None
    for _ in range(3):
        params=dict(series_ticker='KXBTCD', status='open', limit=200)
        if cursor:
            params['cursor']=cursor
        payload=read('/markets',params)
        rows.extend(payload.get('markets') or [])
        cursor=payload.get('cursor')
        if not cursor:
            break
    return _markets(rows,now)


def _yes(target, market):
    strike=_strike(market)
    if strike is None or target is None or target==strike:
        return None  # Exact-boundary estimates express no directional preference.
    return bool(target>strike if market['strike_type'].startswith('greater') else target<strike)


def _records(root, now):
    seen=set()
    for row in sorted(root.get('history', []),key=lambda r:r.get('opened_at',0)):
        opened, expiry, observed=(_number(row.get(k)) for k in
                                  ('opened_at','expires_at','result_observed_at'))
        event=row.get('event_ticker')
        if (row.get('version')!=VERSION or row.get('result') not in {'yes','no'}
                or not event or event in seen or None in (opened,expiry,observed)
                or not opened<expiry<=observed<=now):
            continue
        seen.add(event)
        yield row


def _evidence(records, name, model_version):
    hits=total=unique=paired=0
    for row in records:
        item=row.get('specialist_forecasts',{}).get(name,{})
        if str(item.get('model_version',1))!=str(model_version) or not item.get('active'):
            continue
        prediction=item.get('predicted_yes')
        if prediction is None:
            continue
        actual=row['result']=='yes'
        total+=1; hits+=int(prediction==actual)
        full, without=row.get('predicted_yes'), item.get('without_prediction')
        if full is not None and without is not None:
            paired+=1; unique+=int(full==actual)-int(without==actual)
    multiplier=1.
    if total>=MIN_LEARNING:
        multiplier=max(.5,min(1.5,2*(hits+10)/(total+20)+.2*unique/max(paired,1)))
    return dict(samples=total,hits=hits,accuracy=hits/total if total else None,
                unique_saves=unique,learned_multiplier=multiplier)


def predict(hist, specialist_results, hourly_kalshi, spot_price, root=None, now=None):
    now=time.time() if now is None else float(now)
    root=root or {}
    px=_number(spot_price,0.)
    context=_markets((hourly_kalshi or {}).get('event_markets',[]),now)
    markets=context['event_markets']
    market=min(markets,key=lambda r:abs(r['_strike']-px)) if markets else None
    expiry=context['close_ts']
    remaining=expiry-now if expiry else None
    output=dict(version=VERSION,opened_at=now,close_ts=expiry,seconds_remaining=remaining,
                target_price=px,projected_move=0.,projected_move_pct=0.,direction='FLAT',
                confidence=.5,confidence_basis='signal agreement, not measured accuracy',
                hourly_score=0.,nearest_strike=market['_strike'] if market else None,
                nearest_market=market,nearest_distance=None,kalshi_available=bool(market),
                available=False,specialist_forecasts={},affects_execution=False,
                price_basis='technical BTC forecast; outcomes use official Kalshi results')
    if hist is None or len(hist)<20 or px<=0:
        return output
    try:
        stamp=pd.Timestamp(hist.iloc[-1]['time']).timestamp()
    except (KeyError,TypeError,ValueError,OverflowError):
        return output
    if not now-120<=stamp<=now:
        return output
    results=copy.deepcopy(specialist_results or {})
    probability=_number((market or {}).get('_yes_probability'))
    if probability is None and market:
        bid,ask=(_number(market.get(k+'_dollars'),
                         (_number(market.get(k),0.)/100 if market.get(k) is not None else None))
                 for k in ('yes_bid','yes_ask'))
        probability=(bid+ask)/2 if bid is not None and ask is not None else None
    if probability is not None and not 0<=probability<=1:
        probability=None
    market_prediction=bool(probability>.5) if probability is not None and probability!=.5 else None
    if market and market['strike_type'].startswith('less') and probability is not None:
        probability=1-probability
    results['Kalshi Context AI']=kalshi_context_result(
        dict(available=bool(market),target=(market or {}).get('_strike'),up_probability=probability),px)
    records=list(_records(root,now))
    scale=max(_number(hist.iloc[-1].get('atr14'),px*.002)*2.35,px*.0022)
    scale*=min(1.,max(0.,remaining/3600)) if remaining is not None else 1.
    numerator=denominator=0.
    members={}
    for name,item in results.items():
        score=max(-1.,min(1.,_number(item.get('score'),0.)))
        confidence=max(0.,min(.99,_number(item.get('confidence'),0.)))
        active=specialist_active(name,item) and confidence>0
        evidence=_evidence(records,name,item.get('model_version',1))
        weight=BASE_WEIGHTS.get(name,.75)*evidence['learned_multiplier']
        effective=weight*(.45+.55*confidence) if active else 0.
        target=px+scale*score if active else None
        members[name]=dict(score=score,confidence=confidence,active=active,
                           model_version=item.get('model_version',1),target_price=target,
                           predicted_yes=_yes(target,market) if market else None,
                           weight=weight,effective_weight=effective,vote_share=0.,
                           graded_samples=evidence['samples'],accuracy=evidence['accuracy'],
                           learned_multiplier=evidence['learned_multiplier'],
                           reason=str(item.get('reason','')),
                           without_prediction=None)
        numerator+=score*effective; denominator+=effective
    base=numerator/denominator if denominator else 0.
    move=scale*base; target=px+move
    for item in members.values():
        item['vote_share']=item['effective_weight']/denominator if denominator else 0.
        without=denominator-item['effective_weight']
        if market and without>1e-9:
            item['without_prediction']=_yes(px+scale*(numerator-item['score']*item['effective_weight'])/without,market)
    agreement=abs(sum((1 if r['score']>0 else -1)*r['vote_share'] for r in members.values() if r['active']))
    output.update(available=bool(denominator),specialist_forecasts=members,hourly_score=base,
                  target_price=target,projected_move=move,projected_move_pct=move/px,
                  direction='UP' if move>px*.00025 else 'DOWN' if move<-px*.00025 else 'FLAT',
                  confidence=min(.92,.5+abs(base)*.25+agreement*.12),
                  nearest_distance=target-market['_strike'] if market else None,
                  predicted_yes=_yes(target,market) if market and denominator else None,
                  market_predicted_yes=market_prediction,
                  no_change_predicted_yes=_yes(px,market) if market else None,
                  event_ticker=(market.get('event_ticker') or market['ticker'].rsplit('-T',1)[0]) if market else None,
                  ticker=market['ticker'] if market else None)
    return output


def capture(root, forecast, now=None):
    now=time.time() if now is None else float(now)
    expiry=forecast.get('close_ts'); opened=forecast.get('opened_at')
    if (not forecast.get('available') or not forecast.get('kalshi_available')
            or expiry is None or opened is None or not opened<=now<expiry or now-opened>30):
        return False
    event=forecast.get('event_ticker')
    if not event or any(r.get('event_ticker')==event for r in
                        root.get('pending',[])+root.get('history',[])):
        return False
    row=copy.deepcopy({k:forecast[k] for k in ('version','opened_at','event_ticker','ticker',
                                              'target_price','predicted_yes','market_predicted_yes',
                                              'no_change_predicted_yes')})
    # Keep the evidence needed for replay, without repeated rationales or
    # derived statistics bloating every phone's learning-state download.
    row['specialist_forecasts']={name:{k:item[k] for k in
        ('score','confidence','model_version','target_price','predicted_yes','active',
         'vote_share','without_prediction')} for name,item in forecast['specialist_forecasts'].items()}
    row['expires_at']=expiry
    row['market']={k:forecast['nearest_market'].get(k) for k in
                   ('ticker','event_ticker','strike_type','floor_strike','cap_strike','close_time')}
    root.setdefault('pending',[]).append(row)
    root.update(version=VERSION,affects_execution=False)
    return True


def resolve(root, result_reader, now=None):
    current=time.time() if now is None else float(now)
    pending=[]; count=0
    history=root.setdefault('history',[])
    events={r.get('event_ticker') for r in history}
    for row in root.get('pending',[]):
        if row.get('event_ticker') in events:
            continue
        if not row['opened_at']<row['expires_at']<=current:
            pending.append(row); continue
        try:
            result=result_reader(row['ticker'])
        except Exception:
            pending.append(row); continue
        if result not in {'yes','no'}:
            pending.append(row); continue
        observed=time.time() if now is None else current
        history.append(dict(row,result=result,result_observed_at=observed))
        events.add(row['event_ticker']); count+=1
    root.update(pending=pending,history=history[-HISTORY_LIMIT:],version=VERSION,affects_execution=False)
    root['scorecard']=scorecard(root,now=time.time() if now is None else current)
    return count


def scorecard(root, now=None):
    now=time.time() if now is None else float(now)
    records=list(_records(root,now))
    directional=[r for r in records if r.get('predicted_yes') is not None]
    hits=sum(r['predicted_yes']==(r['result']=='yes') for r in directional)
    latest={name:item.get('model_version',1) for r in records
            for name,item in r.get('specialist_forecasts',{}).items()}
    benchmarks={}
    for key in ('market','no_change'):
        paired=[r for r in directional if r.get(key+'_predicted_yes') is not None]
        baseline_hits=sum(r[key+'_predicted_yes']==(r['result']=='yes') for r in paired)
        model_hits=sum(r['predicted_yes']==(r['result']=='yes') for r in paired)
        benchmarks[key]=dict(samples=len(paired),accuracy=baseline_hits/len(paired) if paired else None,
                             paired_accuracy_edge=(model_hits-baseline_hits)/len(paired) if paired else None)
    return dict(samples=len(directional),hits=hits,accuracy=hits/len(directional) if directional else None,
                benchmarks=benchmarks,
                settled_events=len(records),pending_events=len(root.get('pending',[])),
                specialists={name:_evidence(records,name,version) for name,version in latest.items()},
                basis='official KXBTCD result; earliest captured strike per hourly event',
                minimum_learning_samples=MIN_LEARNING,affects_execution=False)


def update(root, hist, specialists, read_markets, result_reader, now=None):
    """One worker cycle: resolve, forecast with prior labels, then freeze."""
    resolve(root,result_reader,now=now)
    markets=fetch_markets(read_markets,now=now)
    prediction=predict(hist,specialists,markets,float(hist.close.iloc[-1]),root,now=now)
    capture(root,prediction,now=now)
    root.update(latest=prediction,scorecard=scorecard(root,now=now))
    root.pop('error',None)
    return prediction
