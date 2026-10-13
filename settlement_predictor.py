"""Shadow forecast of the exact KXBTC15M final-minute average event.

Arithmetic Brownian motion is an approximation, not a guaranteed settlement.
Only official post-observation labels train the bounded residual correction.
Frozen prospective predictions, one per market, supply the scorecard. Nothing
in this module approves orders or replaces the existing execution probability.
"""
import math
import time
from datetime import datetime

import numpy as np

from contract_probability import _finite, realized_minute_volatility
from kalshi_chart_data import event_ticker

VERSION = 'kalshi-final-minute-average-v1'
MIN_TRAINING = 100


def _timestamp(value):
    numeric = _finite(value)
    if numeric is not None:
        return numeric
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def _observations(state, as_of):
    earliest = {}
    for row in (state.get('research_lab') or {}).get('history') or []:
        prediction = row.get('settlement_prediction') or {}
        opened, expiry = _finite(row.get('opened_at')), _finite(row.get('expires_at'))
        observed = _timestamp(row.get('result_observed_at'))
        probability = _finite(prediction.get('probability_yes'))
        base = _finite(prediction.get('base_probability_yes'))
        market = _finite(prediction.get('market_probability_yes'))
        features = prediction.get('features')
        ticker = str(row.get('ticker') or '')
        if (prediction.get('version') != VERSION or not prediction.get('available')
                or prediction.get('ticker') != ticker or row.get('result') not in ('yes', 'no')
                or opened is None or expiry is None or observed is None
                or not opened < expiry <= observed <= as_of
                or probability is None or not 0 <= probability <= 1
                or base is None or not 0 <= base <= 1
                or market is None or not 0 <= market <= 1
                or not isinstance(features, list) or len(features) != 4
                or any(_finite(x) is None for x in features)):
            continue
        if ticker not in earliest or opened < earliest[ticker]['opened_at']:
            earliest[ticker] = row
    return sorted(earliest.values(), key=lambda row: row['opened_at'])[-1000:]


def predict(market, reference, state, now=None, council_score=0.0):
    now = time.time() if now is None else now
    unavailable = dict(available=False, version=VERSION, affects_execution=False)
    ticker = str(market.get('ticker') or '')
    expiry, target = _finite(market.get('expires_at')), _finite(market.get('target'))
    spot, timestamp = _finite(reference.get('price')), _finite(reference.get('timestamp'))
    market_probability = _finite(market.get('prob'))
    if (not reference.get('available') or not event_ticker(ticker)
            or reference.get('event_ticker') != event_ticker(ticker)
            or market.get('strike_type') != 'greater_or_equal'
            or expiry is None or not now < expiry <= (int(now // 900)+1)*900
            or target is None or target <= 1000 or spot is None or spot <= 1000
            or timestamp is None or not 0 <= now-timestamp <= 30
            or market_probability is None or not 0 <= market_probability <= 1):
        return dict(unavailable, reason='Fresh exact-contract reference, target, rule and quotes required')

    closes = []
    for candle in reference.get('candles') or []:
        ts, close = _timestamp(candle.get('time')), _finite(candle.get('close'))
        if ts is not None and ts+60 <= timestamp and close is not None and close > 1000:
            closes.append((ts, close))
    volatility = realized_minute_volatility([p for _, p in sorted(closes)])
    if volatility is None:
        return dict(unavailable, reason='Insufficient closed Kalshi reference candles')

    # One observed value per completed second. A missing elapsed second is not
    # silently filled with spot; doing so would bias the settlement average.
    start, end = int(expiry)-60, int(expiry)
    known = {}
    for tick in reference.get('ticks') or []:
        ts, price = _finite(tick.get('timestamp')), _finite(tick.get('price'))
        if ts is not None and price is not None and price > 1000 and start <= ts <= timestamp and ts < expiry:
            known[int(ts)] = price
    if start <= timestamp < expiry:
        known[int(timestamp)] = spot
    completed = range(start, min(int(now)+1, end)) if now >= start else range(0)
    if any(second not in known for second in completed):
        return dict(unavailable, reason='Missing elapsed final-minute reference samples')
    future = range(max(start, int(now)+1), end)
    delays = [max(0.001, second-timestamp) for second in future]
    mean = (sum(known[s] for s in completed) + len(delays)*spot)/60
    # Cov(B(t_i), B(t_j)) = min(t_i,t_j). The sorted increment form
    # computes variance of the 60-sample average without a covariance matrix.
    previous, variance_time = 0.0, 0.0
    for index, delay in enumerate(delays):
        variance_time += (delay-previous)*(len(delays)-index)**2
        previous = delay
    sigma = max(1e-9, spot*volatility*math.sqrt(variance_time/60)/60)
    # Cent rounding makes target-0.005 the continuous threshold. Exact tie
    # behavior is always graded by the official result, never this estimate.
    z = (mean-(target-.005))/sigma
    average_probability = .5*(1+math.erf(z/math.sqrt(2)))
    base = min(.99, max(.01, average_probability))
    book = market.get('orderbook') or {}
    pressure = min(1., max(-1., _finite(book.get('weighted_depth_imbalance'), 0.)))
    score = min(1., max(-1., _finite(council_score, 0.)))
    features = [1., market_probability-base, score*.1, pressure*.1]
    rows = _observations(state, now)
    coefficients = np.zeros(4)
    if len(rows) >= MIN_TRAINING:
        x = np.array([r['settlement_prediction']['features'] for r in rows])
        y = np.array([(1. if r['result'] == 'yes' else 0.)
                      - r['settlement_prediction']['base_probability_yes'] for r in rows])
        coefficients = np.linalg.solve(x.T@x+25*np.eye(4), x.T@y)
    correction = min(.15, max(-.15, float(np.dot(features, coefficients))))
    probability = min(.99, max(.01, base+correction))
    return dict(available=True, version=VERSION, ticker=ticker, captured_at=now,
                expires_at=expiry, target=target, reference_timestamp=timestamp,
                probability_yes=probability, probability_no=1-probability,
                outcome='YES' if probability >= .5 else 'NO',
                average_probability_yes=average_probability,
                base_probability_yes=base, market_probability_yes=market_probability,
                expected_final_average=mean, average_sigma_dollars=sigma,
                comparison='rounded final-minute average >= target',
                features=features, coefficients=coefficients.tolist(),
                training_samples=len(rows), affects_execution=False,
                status='Shadow estimate; prospective official settlement validation required')


def scorecard(state, as_of=None):
    rows = _observations(state, time.time() if as_of is None else as_of)
    if not rows:
        return dict(samples=0, accuracy=None, brier=None, market_brier=None,
                    affects_execution=False)
    p = [r['settlement_prediction']['probability_yes'] for r in rows]
    m = [r['settlement_prediction']['market_probability_yes'] for r in rows]
    y = [int(r['result'] == 'yes') for r in rows]
    n = len(rows)
    bins = []
    for low, high in ((0,.2),(.2,.4),(.4,.6),(.6,.8),(.8,1.01)):
        indices = [i for i, value in enumerate(p) if low <= value < high]
        if indices:
            bins.append(dict(samples=len(indices), mean_probability=sum(p[i] for i in indices)/len(indices),
                             observed_yes_rate=sum(y[i] for i in indices)/len(indices)))
    return dict(samples=n, accuracy=sum((v>=.5)==bool(label) for v,label in zip(p,y))/n,
                brier=sum((v-label)**2 for v,label in zip(p,y))/n,
                market_brier=sum((v-label)**2 for v,label in zip(m,y))/n,
                calibration_bins=bins, affects_execution=False)
