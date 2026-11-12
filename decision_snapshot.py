"""Worker-owned settlement decisions. No orders, ledger writes or model promotion."""
import copy
import hashlib
import json
import math
import time

VERSION = 'settlement-decision-v1'
MAX_AGE = 30
NO_VALIDATED_EDGE = 'WAIT — NO VALIDATED SETTLEMENT EDGE'
CALL_FIELDS = (
    'ticker', 'expires_at', 'opened_at', 'master_action', 'master_confidence',
    'master_base_score', 'execution_approved', 'execution_reason', 'would_wait',
    'contract_probability_up', 'contract_probability_basis', 'contract_calibrator_active',
    'contract_probability_source', 'execution_probability_reason', 'decision_schema',
    'settlement_reference_price', 'settlement_reference_timestamp', 'settlement_forecast_end',
    'code_revision', 'forecast_trial_version', 'lock_focus', 'start_price', 'target',
)


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean(v) for v in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _number(value):
    try:
        return float(value) if not isinstance(value, bool) and math.isfinite(float(value)) else None
    except (TypeError, ValueError):
        return None


def _identity(snapshot):
    payload = {k: v for k, v in snapshot.items() if k != 'decision_id'}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()[:24]


def publish_decision(state, live_call, market):
    """Freeze refreshed pending evidence; never renew a timestamp on paper retries."""
    pending = state.get('pending') or {}
    live, market = live_call or {}, market or {}
    call = _clean({key: copy.deepcopy(pending.get(key)) for key in CALL_FIELDS})
    ticker = str(pending.get('ticker') or '')
    action = str(pending.get('master_action') or 'WAIT').upper()
    side = 'YES' if action == 'LOCK UP' else 'NO' if action == 'LOCK DOWN' else None
    expires = _number(pending.get('expires_at'))
    captured = _number(live.get('opened_at'))
    same_observation = (ticker and live.get('ticker') == market.get('ticker') == ticker
                        and live.get('expires_at') == expires
                        and market.get('expires_at', expires) == expires
                        and captured is not None and expires is not None and captured < expires)
    if not same_observation:
        live, captured = {}, None
    p = _number(live.get('contract_probability_up'))
    forecast_side = ('YES' if p >= .5 else 'NO') if p is not None and 0 <= p <= 1 else None
    reason = str(pending.get('execution_reason') or 'WAIT')
    approved = pending.get('execution_approved') is True and side is not None
    outlook_follow = (
        side is not None and live.get('master_action') == action
        and live.get('execution_reason') == NO_VALIDATED_EDGE
    )
    if outlook_follow:
        approved, reason = True, 'PAPER OUTLOOK FOLLOW — no validated settlement edge required'
    if not same_observation:
        approved, reason = False, 'FRESH_SAME_TICKER_EVALUATION_UNAVAILABLE'
        call.update(contract_probability_up=None, settlement_reference_timestamp=None)
    elif side and forecast_side != side:
        approved, reason = False, 'CURRENT_LOCK_DIRECTION_OR_QUALIFICATION_CHANGED'
    if not side:
        action, approved = 'WAIT', False
        if same_observation:
            reason = (live.get('execution_reason') if live.get('master_action') == 'WAIT' else
                      (live.get('lock_focus') or {}).get('reason'))
            reason = reason or 'WAIT — no qualified LOCK'
    call.update(master_action=action, execution_approved=approved, execution_reason=reason,
                would_wait=not approved)
    # Forecast geometry and the first official grading decision stay in pending.
    call['settlement_prediction'] = _clean(copy.deepcopy(live.get('settlement_prediction')))
    previous = state.get('settlement_decision') or {}
    snapshot = dict(version=VERSION, paper_only=True, ticker=ticker,
                    revision=int(previous.get('revision', 0))+1,
                    captured_at=captured, expires_at=expires,
                    master_action=action, side=side, forecast_side=forecast_side,
                    confidence=_number(pending.get('master_confidence')),
                    probability_yes=p, approved=approved, reason=reason,
                    reference_timestamp=_number(live.get('settlement_reference_timestamp')),
                    call=call)
    if outlook_follow and approved:
        snapshot['paper_outlook_follow'] = True
    snapshot['decision_id'] = _identity(snapshot)
    state['settlement_decision'] = snapshot
    return snapshot


def snapshot_blockers(snapshot, ticker, now=None):
    now = time.time() if now is None else float(now)
    if not isinstance(snapshot, dict) or snapshot.get('version') != VERSION:
        return ['SHARED_DECISION_UNAVAILABLE']
    blockers = []
    try:
        valid_id = snapshot.get('decision_id') == _identity(snapshot)
    except (TypeError, ValueError):
        valid_id = False
    if not valid_id or snapshot.get('paper_only') is not True:
        blockers.append('INVALID_DECISION_ID')
    call = snapshot.get('call') or {}
    if not ticker or snapshot.get('ticker') != ticker or call.get('ticker') != ticker:
        blockers.append('DECISION_CONTRACT_MISMATCH')
    captured, expiry = _number(snapshot.get('captured_at')), _number(snapshot.get('expires_at'))
    if captured is None or not 0 <= now-captured <= MAX_AGE:
        blockers.append('STALE_DECISION')
    if expiry is None or expiry <= now or expiry != _number(call.get('expires_at')):
        blockers.append('EXPIRED_DECISION')
    reference = _number(snapshot.get('reference_timestamp'))
    if reference is None or not 0 <= now-reference <= MAX_AGE:
        blockers.append('STALE_REFERENCE')
    action = snapshot.get('master_action')
    side = 'YES' if action == 'LOCK UP' else 'NO' if action == 'LOCK DOWN' else None
    if (action != call.get('master_action') or side != snapshot.get('side')
            or snapshot.get('approved') != call.get('execution_approved')):
        blockers.append('DECISION_ACTION_MISMATCH')
    return blockers


def dashboard_decision(preview, state, now=None):
    """Overlay only the worker decision; a local preview never authorizes a LOCK."""
    now = time.time() if now is None else float(now)
    snapshot = (state or {}).get('settlement_decision') or {}
    ticker = (preview or {}).get('kalshi_ticker')
    blockers = snapshot_blockers(snapshot, ticker, now)
    result = dict(preview or {})
    result.update(action='WAIT', execution_approved=False, locked_side=None,
                  outlook_age_seconds=None, authoritative_available=not blockers, decision_id=snapshot.get('decision_id'),
                  decision_time=snapshot.get('captured_at'), decision_blockers=blockers,
                  execution_reason='; '.join(blockers), contract_probability_up=None,
                  settlement_prediction=None, reason='; '.join(blockers),
                  score=0., projected_end=float('nan'), source_health=0.,
                  prediction_label='Worker decision unavailable')
    if snapshot.get('ticker') != ticker:
        return result
    call = snapshot.get('call') or {}
    result.update({key: copy.deepcopy(value) for key, value in call.items()
                   if key not in ('master_action', 'execution_approved', 'settlement_prediction')})
    result.update(confidence=snapshot.get('confidence') or 0.,
                  consensus=(call.get('lock_focus') or {}).get('consensus', 0.),
                  base_score=call.get('master_base_score') or 0.,
                  score=call.get('master_base_score') or 0.,
                  source_health=(call.get('lock_focus') or {}).get('source_health', 0.),
                  worker_outlook_action=snapshot.get('master_action'),
                  worker_side=snapshot.get('side'),
                  target_price=call.get('target'),
                  kalshi_close_ts=snapshot.get('expires_at'),
                  seconds_remaining=max(0., (snapshot.get('expires_at') or now)-now))
    captured = _number(snapshot.get('captured_at'))
    if (captured is not None and captured <= now and blockers
            and set(blockers) <= {'STALE_DECISION', 'STALE_REFERENCE'}):
        result['outlook_age_seconds'] = int(now - captured)
    if not blockers:
        result.update(action=snapshot.get('master_action', 'WAIT'),
                      locked_side=('UP' if snapshot.get('side') == 'YES' else 'DOWN') if snapshot.get('side') else None,
                      execution_approved=snapshot.get('approved') is True,
                      execution_reason=snapshot.get('reason'),
                      reason=snapshot.get('reason'),
                      projected_end=_number(call.get('settlement_forecast_end')) or float('nan'),
                      prediction_label='Worker forecast '+str(snapshot.get('forecast_side') or 'unavailable'),
                      settlement_prediction=copy.deepcopy(call.get('settlement_prediction')))
    else:
        result['execution_reason'] = '; '.join(blockers)
    return result
