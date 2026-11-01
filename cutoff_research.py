"""Prospective LOCK cutoff scenarios. Never read by an execution gate."""
import math
import time
from collections import Counter
from statistics import mean, stdev

from kalshi_paper_engine import (UNPROVEN_POSITION_CAP, LOCK_MIN_CONFIDENCE,
                                kalshi_taker_fee, expected_lock_net_pnl)
from lock_focus import LOCK_LATEST_SECONDS
from scalp_exit_research import quotes
from trade_assessment import assess_paper_entry, finite

VERSION = 'pr63-bounded-cutoffs-v1'
MIN_MARKETS = 100


def root(state):
    return state.setdefault('cutoff_research', dict(version=VERSION, paper_only=True,
                            affects_execution=False, pending=[], history=[]))


def observe(state, call, market, cash, lock_gate, now=None):
    """Freeze both rules on the first fresh, depth-backed observation per ticker.

    Learned reliability approval is retained in both scenarios. Only static
    focus/price/confidence cutoffs and the net margin differ. Neither result
    is a paper fill or a license to bypass a failed current assessment.
    """
    now = time.time() if now is None else float(now)
    lab = root(state)
    ticker = call.get('ticker')
    expiry = finite(call.get('expires_at'))
    revision = call.get('code_revision')
    if (not ticker or market.get('ticker') != ticker or expiry is None or now >= expiry
            or market.get('status') not in ('open', 'active')
            or not isinstance(revision, str) or not revision.strip()):
        lab['last_observation_status'] = 'MISSING_CURRENT_CONTRACT_OR_REVISION'
        return
    if any(r['ticker'] == ticker for r in lab['pending'] + lab['history']):
        return
    for value in (market.get('quotes_observed_at'), call.get('execution_checked_at'),
                  call.get('settlement_reference_timestamp')):
        at = finite(value)
        if at is None or not 0 <= now-at <= 30:
            lab['last_observation_status'] = 'STALE_QUOTE_FORECAST_OR_REFERENCE'
            return
    book = market.get('execution_book') or {}
    if not book.get('available'):
        lab['last_observation_status'] = 'DEPTH_UNAVAILABLE'
        return
    focus = call.get('lock_focus') or {}
    direction = focus.get('direction')
    action = str(call.get('master_action') or '')
    # The already-published immutable side takes priority over any new focus.
    if action.endswith(' UP'):
        direction = 'UP'
    elif action.endswith(' DOWN'):
        direction = 'DOWN'
    if direction not in ('UP', 'DOWN'):
        lab['last_observation_status'] = 'NO_DIRECTION'
        return
    side = 'YES' if direction == 'UP' else 'NO'
    bid, ask = quotes(market, side)
    depth = finite(book.get(side.lower()+'_ask_size'))
    cash = finite(cash)
    if (bid is None or ask is None or not 0 <= bid <= ask < 1 or ask <= 0
            or depth is None or depth < 1 or cash is None or cash <= 0):
        lab['last_observation_status'] = 'INVALID_QUOTE_OR_ALLOCATION'
        return
    budget = cash * UNPROVEN_POSITION_CAP
    # Bound by depth before division; even finite subnormal asks can overflow
    # budget/ask. Binary search avoids a size-dependent fee-decrement loop.
    low, high = 0, int(depth) if budget >= depth*ask else int(budget/ask)
    while low < high:
        size = (low+high+1)//2
        if size*ask + kalshi_taker_fee(size, ask) <= budget:
            low = size
        else:
            high = size-1
    contracts = low
    # Assess a hypothetical LOCK; an outlook alone is never execution approval.
    proposed = dict(call, master_action='LOCK '+direction)
    assessment = assess_paper_entry(proposed, market, contracts=contracts,
                                    now=now, lock_gate=lock_gate)
    checks = focus.get('checks') or {}
    guards = [name.upper() for name in ('source_health', 'target_confirmed', 'window')
              if checks.get(name) is not True]
    if expiry-now <= LOCK_LATEST_SECONDS and 'WINDOW' not in guards:
        guards.append('WINDOW')
    baseline = list(assessment['blockers']) + guards
    if action != 'LOCK '+direction or focus.get('eligible') is not True:
        baseline.append('CURRENT_LOCK_FOCUS')
    confidence = finite(call.get('master_confidence'))
    if confidence is None or confidence < LOCK_MIN_CONFIDENCE:
        baseline.append('CONFIDENCE_FLOOR')
    candidate = [b for b in assessment['blockers']
                 if b not in ('ENTRY_PRICE_CAP', 'INSUFFICIENT_FEE_ADJUSTED_EDGE')] + guards
    net = expected_lock_net_pnl(contracts, ask, proposed, side) if contracts else None
    if net is None or net + 1e-12 < contracts*.01:
        candidate.append('INSUFFICIENT_ONE_CENT_NET_EDGE')
    probability = call.get('contract_probability_up')
    probability = None if isinstance(probability, bool) else finite(probability)
    if probability is not None and not 0 <= probability <= 1:
        probability = None
    row = dict(version=VERSION, ticker=ticker, code_revision=revision,
               opened_at=now, expires_at=expiry, side=side, entry=ask,
               contracts=contracts, entry_fee=kalshi_taker_fee(contracts, ask),
               probability_yes=probability, expected_net_pnl=net,
               baseline=dict(eligible=not baseline, blockers=list(dict.fromkeys(baseline))),
               candidate=dict(eligible=not candidate, blockers=list(dict.fromkeys(candidate))))
    lab['pending'].append(row)
    lab['dropped_pending'] = lab.get('dropped_pending', 0) + max(0, len(lab['pending'])-200)
    lab['pending'] = lab['pending'][-200:]
    lab['last_observation_status'] = 'CAPTURED'


def resolve(state, market_reader, now=None):
    now = time.time() if now is None else float(now)
    lab = root(state)
    pending = []
    # Bound label reads, rotating failures so a permanently unknown old ticker
    # cannot starve later settlements. No new data provider or network endpoint.
    attempted = 0
    retry = []
    for row in lab['pending']:
        if row['expires_at'] > now or attempted >= 3:
            pending.append(row)
            continue
        attempted += 1
        try:
            market = market_reader(row['ticker'])
        except Exception:
            retry.append(row)
            continue
        if (market.get('ticker') != row['ticker']
                or market.get('status') not in ('settled', 'finalized')
                or market.get('result') not in ('yes', 'no')):
            retry.append(row)
            continue
        won = (row['side'] == 'YES') == (market['result'] == 'yes')
        pnl = row['contracts'] * (int(won)-row['entry']) - row['entry_fee']
        lab['history'].append(dict(row, result=market['result'], result_observed_at=now,
                                   settlement_scenario_pnl=pnl))
    lab['pending'] = pending + retry
    lab['history'] = lab['history'][-1000:]


def scorecard(state, as_of=None, revision=None):
    now = time.time() if as_of is None else float(as_of)
    lab = (state or {}).get('cutoff_research') or {}
    captures = [r for r in lab.get('history', []) + lab.get('pending', [])
                if r.get('version') == VERSION and r.get('code_revision')
                and r['opened_at'] <= now]
    if revision is None and captures:
        revision = max(captures, key=lambda r: r['opened_at'])['code_revision']
    captures = [r for r in captures if r['code_revision'] == revision]
    unique = {}
    for row in sorted(captures, key=lambda r: r['opened_at']):
        unique.setdefault(row['ticker'], row)
    rows = [r for r in unique.values() if r.get('result') in ('yes', 'no')
            and r['expires_at'] <= r.get('result_observed_at', math.inf) <= now]
    rows.sort(key=lambda r: (r['expires_at'], r['ticker']))
    def metrics(policy):
        accepted = [r for r in rows if r[policy]['eligible']]
        pnl = [r['settlement_scenario_pnl'] for r in accepted]
        equity = peak = drawdown = 0.
        for value in pnl:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak-equity)
        probabilities = [(r['probability_yes'], int(r['result'] == 'yes')) for r in accepted
                         if r['probability_yes'] is not None]
        bins = []
        for i in range(5):
            members = [(p, y) for p, y in probabilities if min(4, int(p*5)) == i]
            if members:
                bins.append(dict(low=i/5, high=(i+1)/5, markets=len(members),
                                 mean_probability=mean(p for p, _ in members),
                                 observed_yes=mean(y for _, y in members)))
        return dict(entries=len(pnl), net_pnl=sum(pnl), expectancy=mean(pnl) if pnl else None,
                    max_scenario_drawdown=drawdown,
                    brier=mean((p-y)**2 for p, y in probabilities) if probabilities else None,
                    calibration_bins=bins,
                    blockers=dict(Counter(b for r in rows for b in r[policy]['blockers'])))
    deltas = [(int(r['candidate']['eligible'])-int(r['baseline']['eligible']))
              * r['settlement_scenario_pnl'] for r in rows]
    gain = mean(deltas) if deltas else None
    radius = 1.96*stdev(deltas)/math.sqrt(len(deltas)) if len(deltas) > 1 else None
    additional = sum(r['candidate']['eligible'] and not r['baseline']['eligible'] for r in rows)
    return dict(version=VERSION, paper_only=True, affects_execution=False, code_revision=revision,
                markets=len(rows), pending_markets=len(unique)-len(rows), minimum_markets=MIN_MARKETS,
                additional_entries=additional, baseline=metrics('baseline'), candidate=metrics('candidate'),
                paired_pnl_gain=gain, paired_pnl_low=None if radius is None else gain-radius,
                paired_pnl_high=None if radius is None else gain+radius,
                status='COLLECTING' if len(rows) < MIN_MARKETS else
                       'INSUFFICIENT_ADDITIONAL_ENTRIES' if additional < MIN_MARKETS else
                       'READY_FOR_REVIEW',
                dropped_pending_all_revisions=lab.get('dropped_pending', 0),
                last_observation_status=lab.get('last_observation_status', 'NOT_OBSERVED'),
                scope='Hypothetical LOCK settlement scenarios at captured depth/size; not actual fills or portfolio replay. '
                      'Same producing revision, one first observation per contract. Reliability and quarantine retained. '
                      'Approximate paired 95% mean P/L interval; serial dependence limits inference. No automatic promotion.')
