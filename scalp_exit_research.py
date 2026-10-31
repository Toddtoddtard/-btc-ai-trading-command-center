"""Prospective sampled bid-path research, never execution authorization.

One frozen one-contract episode per market. Quotes between polls are unknown;
unobserved exits are censored, not fabricated from final settlement labels.
"""
import math
import time
from trade_assessment import finite
from kalshi_paper_engine import kalshi_taker_fee, SCALP_MIN_GROSS_RETURN, SCALP_STOP_LOSS_POINTS

VERSION = 'observed-bid-path-v1'


def root(state):
    return state.setdefault('scalp_exit_research', dict(version=VERSION, paper_only=True,
                            affects_execution=False, pending=[], history=[]))


def quotes(market, side):
    def price(name):
        dollars = finite(market.get(name+'_dollars'))
        cents = finite(market.get(name))
        return dollars if dollars is not None else cents/100 if cents is not None else None
    if side == 'YES':
        return price('yes_bid'), price('yes_ask')
    bid, ask = price('no_bid'), price('no_ask')
    yes_bid, yes_ask = price('yes_bid'), price('yes_ask')
    return (bid if bid is not None else 1-yes_ask if yes_ask is not None else None,
            ask if ask is not None else 1-yes_bid if yes_bid is not None else None)


def observe(state, call, market, now=None):
    now = time.time() if now is None else float(now)
    lab = root(state)
    ticker = call.get('ticker') or call.get('kalshi_ticker')
    if not ticker or market.get('ticker') != ticker:
        return
    at = finite(market.get('quotes_observed_at'))
    book = market.get('execution_book') or {}
    if at is None or not 0 <= now-at <= 30 or not book.get('available'):
        return
    episode = next((r for r in lab['pending'] if r['ticker'] == ticker), None)
    if episode is None:
        action = str(call.get('master_action') or call.get('action') or '')
        expiry = finite(call.get('expires_at'))
        if (not action.startswith('SCALP ') or expiry is None or now >= expiry
                or any(r['ticker'] == ticker for r in lab['history'])):
            return
        side = 'YES' if action == 'SCALP UP' else 'NO' if action == 'SCALP DOWN' else None
        if side is None:
            return
        bid, ask = quotes(market, side)
        if (bid is None or ask is None or not 0 < bid <= ask <= .75
                or (finite(book.get(side.lower()+'_ask_size')) or 0) < 1):
            return
        cost = ask + kalshi_taker_fee(1, ask)
        target = next((c/100 for c in range(1,101)
                       if c/100 >= ask*(1+SCALP_MIN_GROSS_RETURN)
                       and c/100-kalshi_taker_fee(1,c/100) > cost), None)
        if target is None:
            return
        prior = [r for r in lab['history'] if r.get('path_result') in ('TARGET','STOP')]
        p = (sum(r['path_result']=='TARGET' for r in prior)+2)/(len(prior)+4)
        episode = dict(ticker=ticker,side=side,opened_at=now,expires_at=expiry,
                       entry=ask,entry_fee=kalshi_taker_fee(1,ask),target=target,
                       stop=max(.01,ask-SCALP_STOP_LOSS_POINTS), probability=p,
                       baseline_probability=.5, code_revision=call.get('code_revision'),
                       training_markets=len(prior),path_result=None, observations=0,
                       last_observed_at=at)
        lab['pending'].append(episode)
    if now >= episode['expires_at'] or episode['path_result'] is not None:
        return
    bid, _ = quotes(market, episode['side'])
    if (bid is None or not 0 <= bid <= 1
            or (finite(book.get(episode['side'].lower()+'_bid_size')) or 0) < 1
            or at < episode['last_observed_at']):
        return
    episode.update(last_observed_at=at, observations=episode['observations']+1)
    if bid >= episode['target'] or bid <= episode['stop']:
        episode.update(path_result='TARGET' if bid >= episode['target'] else 'STOP',
                       exit_bid=bid, exit_observed_at=at,
                       net_pnl=bid-kalshi_taker_fee(1,bid)-episode['entry']-episode['entry_fee'])


def resolve(state, market_reader, now=None):
    now = time.time() if now is None else float(now)
    lab = root(state)
    pending = []
    for row in lab['pending']:
        if row['expires_at'] > now:
            pending.append(row)
            continue
        try:
            m = market_reader(row['ticker'])
        except Exception:
            pending.append(row)
            continue
        if (m.get('ticker') != row['ticker'] or m.get('status') not in ('settled','finalized')
                or m.get('result') not in ('yes','no')):
            pending.append(row)
            continue
        lab['history'].append(dict(row, official_result=m['result'], result_observed_at=now,
                                   censored=row['path_result'] is None))
    lab['pending'], lab['history'] = pending, lab['history'][-1000:]
    lab['scorecard'] = scorecard(state)


def scorecard(state):
    lab = root(state)
    eligible = [r for r in lab['history'] if r.get('path_result') in ('TARGET','STOP')]
    n = len(eligible)
    return dict(version=VERSION,paper_only=True,affects_execution=False,
                eligible_official_markets=n, censored_markets=sum(r.get('censored',False) for r in lab['history']),
                pending_markets=len(lab['pending']),target_hits=sum(r['path_result']=='TARGET' for r in eligible),
                net_pnl=sum(r['net_pnl'] for r in eligible),
                brier=sum((r['probability']-(r['path_result']=='TARGET'))**2 for r in eligible)/n if n else None,
                scope='Sampled one-contract target-before-stop paths; censored windows excluded; not continuous-tick accuracy',
                promotion='RESEARCH ONLY — no paired execution-policy evidence or promotion authority')
