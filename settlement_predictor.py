"""Shadow forecast of the exact KXBTC15M final-minute average event.

Arithmetic Brownian motion is an approximation, not a guaranteed settlement.
Only official post-observation labels train the bounded residual correction.
Frozen prospective predictions, one per market, supply the scorecard. Nothing
in this module approves orders or replaces the existing execution probability.
"""
import math
import time
import copy
from datetime import datetime

import numpy as np

from contract_probability import _finite, realized_minute_volatility
from kalshi_chart_data import event_ticker

VERSION = 'kalshi-final-minute-average-v1'
MIN_TRAINING = 100
MIN_VALIDATION = 100
CHECKPOINT_TOLERANCE = 150


def _timestamp(value):
    numeric = _finite(value)
    if numeric is not None:
        return numeric
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return None


def _history(state):
    return (list((state.get('research_lab') or {}).get('history') or [])
            + list((state.get('settlement_predictor') or {}).get('history') or []))


def _observations(state, as_of, lead_seconds=None):
    earliest = {}
    for row in _history(state):
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
        if lead_seconds is not None and not lead_seconds <= expiry-opened <= lead_seconds+CHECKPOINT_TOLERANCE:
            continue
        # Earliest independent forecast overall; closest BEFORE each checkpoint.
        previous = earliest.get(ticker)
        if (previous is None or (opened < previous['opened_at'] if lead_seconds is None
                                 else opened > previous['opened_at'])):
            earliest[ticker] = row
    return sorted(earliest.values(), key=lambda row: row['opened_at'])[-1000:]


def _coefficients(rows):
    if len(rows) < MIN_TRAINING:
        return np.zeros(4)
    x = np.array([r['settlement_prediction']['features'] for r in rows])
    y = np.array([(1. if r['result'] == 'yes' else 0.)
                  - r['settlement_prediction']['base_probability_yes'] for r in rows])
    return np.linalg.solve(x.T@x+25*np.eye(4), x.T@y)


def _corrected(base, features, coefficients):
    correction = min(.15, max(-.15, float(np.dot(features, coefficients))))
    return min(.99, max(.01, base+correction))


def correction_validation(rows):
    """Fit on prior available labels; require paired base AND market improvement."""
    losses = []
    for index, row in enumerate(rows):
        prior = [r for r in rows[:index]
                 if _timestamp(r['result_observed_at']) <= row['opened_at']]
        if len(prior) < MIN_TRAINING:
            continue
        p = row['settlement_prediction']
        candidate = _corrected(p['base_probability_yes'], p['features'], _coefficients(prior))
        y = int(row['result'] == 'yes')
        losses.append(((candidate-y)**2, (p['base_probability_yes']-y)**2,
                       (p['market_probability_yes']-y)**2))
    n = len(losses)
    means = [sum(r[i] for r in losses)/n if n else None for i in range(3)]
    recent = losses[-100:]
    recent_edge = (min(sum(r[i]-r[0] for r in recent)/len(recent) for i in (1, 2))
                   if recent else None)
    active = bool(n >= MIN_VALIDATION and min(means[1:])-means[0] >= .0005
                  and recent_edge >= 0)
    return dict(active=active, samples=n, candidate_brier=means[0], base_brier=means[1],
                market_brier=means[2], recent_edge=recent_edge,
                reason='Paired walk-forward improvement passed' if active else
                'Unproven correction withheld; using reference-average base model')


def record_observation(state, call, market):
    """Freeze each worker capture independently of trade gates and research phases."""
    if not market:
        return False
    if not call:
        call = dict(ticker=market.get('ticker'), opened_at=time.time(), expires_at=market.get('expires_at'),
                    settlement_prediction=dict(available=False, reason='Current technical/council forecast unavailable'))
    if call.get('ticker') != market.get('ticker'):
        return False
    opened, expiry = _finite(call.get('opened_at')), _finite(call.get('expires_at'))
    if opened is None or expiry is None or not expiry-900 <= opened < expiry:
        return False
    lab = state.setdefault('settlement_predictor', {})
    pending, history = lab.setdefault('pending', []), lab.setdefault('history', [])
    key = (call['ticker'], opened)
    if any((r.get('ticker'), r.get('opened_at')) == key for r in pending+history):
        return False
    row = {k: call.get(k) for k in ('ticker', 'opened_at', 'expires_at', 'master_action',
                                  'master_confidence', 'master_base_score', 'specialists',
                                  'settlement_prediction')}
    row.update(target=market.get('target'), strike_type=market.get('strike_type'),
               quotes_observed_at=market.get('quotes_observed_at'),
               reference_timestamp=(market.get('settlement_reference') or {}).get('timestamp'),
               seconds_remaining=expiry-opened)
    pending.append(copy.deepcopy(row))
    # Preserve unresolved outcomes; do not silently discard missing labels.
    return True


def resolve_observations(state, result_reader, now=None):
    live_clock = now is None
    now = time.time() if now is None else now
    lab = state.setdefault('settlement_predictor', {})
    history, unresolved, results = lab.setdefault('history', []), [], {}
    resolved = 0
    for row in lab.get('pending') or []:
        if row['expires_at'] > now:
            unresolved.append(row)
            continue
        ticker = row['ticker']
        if ticker not in results:
            result = str(result_reader(ticker) or '').lower()
            results[ticker] = (result, time.time() if live_clock else now)
        result, observed_at = results[ticker]
        if result not in ('yes', 'no'):
            unresolved.append(row)
            continue
        history.append(dict(row, result=result, result_observed_at=observed_at))
        resolved += 1
    lab['pending'], lab['history'] = unresolved, history[-3000:]
    return resolved


def predict(market, reference, state, now=None, council_score=0.0):
    now = time.time() if now is None else now
    unavailable = dict(available=False, version=VERSION, affects_execution=False)
    ticker = str(market.get('ticker') or '')
    expiry, target = _finite(market.get('expires_at')), _finite(market.get('target'))
    spot, timestamp = _finite(reference.get('price')), _finite(reference.get('timestamp'))
    market_probability = _finite(market.get('prob'))
    quote_time = _finite(market.get('quotes_observed_at'))
    if (not reference.get('available') or not event_ticker(ticker)
            or reference.get('event_ticker') != event_ticker(ticker)
            or market.get('strike_type') != 'greater_or_equal'
            or expiry is None or not now < expiry <= (int(now // 900)+1)*900
            or target is None or target <= 1000 or spot is None or spot <= 1000
            or timestamp is None or not 0 <= now-timestamp <= 30
            or ('quotes_observed_at' in market and
                (quote_time is None or not 0 <= now-quote_time <= 30))
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
    validation = correction_validation(rows)
    coefficients = _coefficients(rows) if validation['active'] else np.zeros(4)
    probability = _corrected(base, features, coefficients)
    return dict(available=True, version=VERSION, ticker=ticker, captured_at=now,
                expires_at=expiry, target=target, reference_timestamp=timestamp,
                probability_yes=probability, probability_no=1-probability,
                outcome='YES' if probability >= .5 else 'NO',
                average_probability_yes=average_probability,
                base_probability_yes=base, market_probability_yes=market_probability,
                expected_final_average=mean, average_sigma_dollars=sigma,
                comparison='rounded final-minute average >= target',
                features=features, coefficients=coefficients.tolist(),
                training_samples=len(rows), correction_validation=validation,
                quotes_observed_at=quote_time, affects_execution=False,
                status='Shadow estimate; prospective official settlement validation required')


def _metrics(rows):
    if not rows:
        return dict(samples=0, accuracy=None, brier=None, market_brier=None,
                    log_loss=None, coin_flip_brier=None, calibration_bins=[],
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
                log_loss=-sum(label*math.log(max(v, 1e-12))+(1-label)*math.log(max(1-v, 1e-12))
                              for v,label in zip(p,y))/n,
                coin_flip_brier=.25,
                mean_seconds_remaining=sum(r['expires_at']-r['opened_at'] for r in rows)/n,
                calibration_bins=bins, affects_execution=False)


def scorecard(state, as_of=None):
    as_of = time.time() if as_of is None else as_of
    score = _metrics(_observations(state, as_of))
    score['by_horizon'] = {f'{m}m': _metrics(_observations(state, as_of, m*60)) for m in (10, 5, 1)}
    score['checkpoint_tolerance_seconds'] = CHECKPOINT_TOLERANCE
    settled, available, unavailable, reasons, seen = set(), set(), 0, {}, set()
    for row in _history(state):
        opened, expiry = _finite(row.get('opened_at')), _finite(row.get('expires_at'))
        observed = _timestamp(row.get('result_observed_at'))
        key = (row.get('ticker'), opened)
        if (key in seen or not key[0] or opened is None or expiry is None or observed is None
                or not opened < expiry <= observed <= as_of or row.get('result') not in ('yes', 'no')):
            continue
        seen.add(key)
        settled.add(key[0])
        prediction = row.get('settlement_prediction') or {}
        if prediction.get('available'):
            available.add(key[0])
        else:
            unavailable += 1
            reason = prediction.get('reason') or 'No settlement forecast captured'
            reasons[reason] = reasons.get(reason, 0)+1
    score['coverage'] = dict(settled_markets=len(settled), forecast_markets=len(available),
                             unavailable_observations=unavailable, unavailable_reasons=reasons,
                             pending_observations=len((state.get('settlement_predictor') or {}).get('pending') or []),
                             scope='Retained observed markets; worker outages may leave unobserved windows')
    return score
