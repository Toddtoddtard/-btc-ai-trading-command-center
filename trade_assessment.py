"""Shared, paper-only final entry assessment. Forecasts never imply approval.

Lifecycle/depth/position limits remain additional vetoes in background_paper.
This module cannot send orders or promote research models.
"""
import math
import time
from contract_calibration import BASIS
from kalshi_paper_engine import (kalshi_taker_fee, expected_lock_net_pnl,
                                LOCK_MIN_NET_PROBABILITY_EDGE, entry_price_limit,
                                executable_entry_quote)

SCHEMA = 'settlement-first-v1'


def finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def assess_paper_entry(call, market, contracts=1, now=None, lock_gate=None):
    now = time.time() if now is None else float(now)
    action = str(call.get('master_action') or call.get('action') or 'WAIT').upper()
    side = 'YES' if action.endswith(' UP') else 'NO' if action.endswith(' DOWN') else None
    strategy = 'LOCK' if action.startswith('LOCK ') else 'SCALP' if action.startswith('SCALP ') else 'WAIT'
    ticker = call.get('ticker') or call.get('kalshi_ticker')
    expiry = finite(call.get('expires_at', call.get('kalshi_close_ts')))
    probability = finite(call.get('contract_probability_up'))
    def quote(name):
        dollars = finite(market.get(name+'_dollars'))
        cents = finite(market.get(name))
        return dollars if dollars is not None else cents/100 if cents is not None else None
    bid, ask = quote('yes_bid'), quote('yes_ask')
    if side == 'NO':
        bid, ask = quote('no_bid'), quote('no_ask')
        if bid is None:
            ya = quote('yes_ask')
            bid = 1-ya if ya is not None else None
        if ask is None:
            yb = quote('yes_bid')
            ask = 1-yb if yb is not None else None
    blockers = []
    if side is None or strategy == 'WAIT':
        blockers.append('NO_DIRECTIONAL_OUTLOOK')
    if not ticker or market.get('ticker') != ticker:
        blockers.append('CONTRACT_MISMATCH')
    if expiry is None or expiry <= now or str(market.get('status')).lower() not in ('open', 'active'):
        blockers.append('EXPIRED_MARKET')
    for field, value in [('QUOTES', market.get('quotes_observed_at')),
                         ('REFERENCE', call.get('settlement_reference_timestamp'))]:
        at = finite(value)
        if at is None or not 0 <= now-at <= 30:
            blockers.append('STALE_'+field)
    if call.get('execution_approved') is not True:
        blockers.append(str(call.get('execution_reason') or 'RELIABILITY_GATE'))
    if (call.get('contract_probability_basis') != BASIS
            or call.get('contract_calibrator_active') is not True
            or probability is None or not 0 <= probability <= 1):
        blockers.append('NO_VALIDATED_SETTLEMENT_EDGE')
    if not executable_entry_quote(bid, ask):
        blockers.append('INVALID_EXECUTABLE_QUOTE')
    elif ask > entry_price_limit(strategy):
        blockers.append('ENTRY_PRICE_CAP')
    size = finite(contracts)
    size = int(size) if size is not None and size > 0 and size.is_integer() else 0
    if not size:
        blockers.append('INVALID_SIZE')
    selected = (probability if side == 'YES' else 1-probability) if probability is not None and side else None
    fee = kalshi_taker_fee(size, ask) if size and ask is not None and 0 <= ask <= 1 else None
    net = expected_lock_net_pnl(size, ask, call, side) if fee is not None and side else None
    if strategy == 'LOCK':
        if lock_gate is None or lock_gate.get('approved') is not True:
            blockers.append('LOCK_VALIDATION_QUARANTINE')
        if net is None or net/size + 1e-12 < LOCK_MIN_NET_PROBABILITY_EDGE:
            blockers.append('INSUFFICIENT_FEE_ADJUSTED_EDGE')
    if strategy == 'SCALP':
        # A terminal fair value is NOT a forecast of an executable early exit.
        # Bid-path research currently has no promotion authority. Never trust a
        # caller-supplied `active` flag or projected price to bypass this gate.
        blockers.append('NO_VALIDATED_SCALP_EXIT_MODEL')
    blockers = list(dict.fromkeys(blockers))
    return dict(version=SCHEMA, paper_only=True, ticker=ticker,
                outlook='UP' if side == 'YES' else 'DOWN' if side == 'NO' else 'UNAVAILABLE',
                proposed_action=action, paper_action=action if not blockers else 'WAIT',
                approved=not blockers, blockers=blockers,
                selected_probability=selected, probability_source=call.get('contract_probability_source'),
                entry_price=ask, entry_fee=fee, contracts=size,
                break_even_probability=ask+fee/size if fee is not None else None,
                expected_settlement_net_pnl=net,
                net_edge_per_contract=net/size if net is not None else None,
                expected_early_exit_price=None, checked_at=now)
