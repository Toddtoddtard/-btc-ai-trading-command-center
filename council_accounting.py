"""Rebuild specialist evidence from retained, pre-outcome snapshots and official results."""
import copy
import math
from datetime import datetime, timezone
from council_v4 import specialist_active, specialist_model_matches, _direction

BASIS = 'official_kalshi_directional_calls_v1'
MASTER_BASIS = 'official_kalshi_council_confidence_v1'


def reconcile_master_learning(state):
    """Calibrate the captured council's own direction, never the candle path.

    Rebuild from immutable pre-expiry snapshots and official Kalshi labels so
    retries are idempotent and old proxy labels cannot survive the migration.
    """
    if state.get('confidence_model', {}).get('basis') != MASTER_BASIS:
        state.setdefault('legacy_master_calibration', {
            'confidence_model': copy.deepcopy(state.get('confidence_model', {})),
            'regimes': copy.deepcopy(state.get('regimes', {})),
            'reason': 'Council confidence was scored against candle-path/proxy outcomes.'})
    model = {'basis': MASTER_BASIS, 'samples': 0, 'hits': 0, 'brier_ewma': .25}
    regimes = {}
    records = sorted(official_snapshots(state), key=lambda pair: float(pair[0].get('opened_at') or 0))
    for record, outcome in records:
        snap = record['snapshot']
        try:
            value = float(snap.get('master_base_score', 0))
            conf = float(snap.get('master_confidence', .5))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or not math.isfinite(conf) or abs(value) <= .03:
            continue
        direction = 1 if value > 0 else -1
        actual = 1 if outcome['kalshi_result'] == 'yes' else -1
        hit = int(direction == actual)
        conf = min(.99, max(.01, conf))
        model['samples'] += 1
        model['hits'] += hit
        model['brier_ewma'] = .9*model['brier_ewma'] + .1*(conf-hit)**2
        model.update(last_confidence=conf, last_base_score=value, last_correct=hit)
        regime = str(snap.get('regime') or 'UNKNOWN')
        bucket = regimes.setdefault(regime, {'samples': 0, 'direction_hits': 0,
                                             'ewma_accuracy': .5, 'basis': MASTER_BASIS})
        bucket['samples'] += 1
        bucket['direction_hits'] += hit
        bucket['ewma_accuracy'] = .88*bucket['ewma_accuracy'] + .12*hit
    state['confidence_model'], state['regimes'] = model, regimes
    penalty = min(.16, max(0., (model['brier_ewma']-.20)*.55))
    wait = state.setdefault('wait_policy', {})
    wait.update(overconfidence_penalty=penalty,
                minimum_calibrated_confidence=min(.68, max(.56, .61-min(model['samples'], 300)/3000+penalty*.6)),
                minimum_edge_score=min(.30, max(.18, .20+penalty*.65)))
    return model


def official_snapshots(state):
    outcomes = {str(r.get('ticker')): r for r in state.get('master_history', [])
                if r.get('kalshi_result') in ('yes','no')}
    # Retain the earliest valid pre-expiry observation for each market.
    # Storage order must not determine the label used for learning.
    selected = {}
    for row in state.get('prediction_snapshots', []):
        ticker = str(row.get('ticker') or '')
        if not ticker or ticker not in outcomes:
            continue
        opened_at, expires_at = row.get('opened_at'), row.get('expires_at')
        # Legacy retained snapshots can lack both timestamps; keep their
        # evidence, but prefer a dated capture whenever one exists.
        undated = opened_at is None and expires_at is None
        if undated:
            capture_order = (1, 0.0)
        else:
            try:
                opened, expires = float(opened_at), float(expires_at)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(opened) and math.isfinite(expires) and opened < expires):
                continue
            capture_order = (0, opened)
        snapshot = row.get('snapshot') or {}
        if not isinstance(snapshot, dict) or not snapshot.get('specialists'):
            continue
        previous = selected.get(ticker)
        if previous is None or capture_order < previous[0]:
            selected[ticker] = (capture_order, row)
    for ticker in sorted(selected):
        yield selected[ticker][1], outcomes[ticker]


def reconcile_specialists(state):
    """Never invent older evidence. Archive counters and label the retained scope."""
    if state.get('specialist_accounting', {}).get('basis') != BASIS:
        state['legacy_specialist_accounting'] = {
            'archived_at': datetime.now(timezone.utc).isoformat(),
            'specialists': copy.deepcopy(state.get('specialists', {})),
            'reason': 'Mixed labels and neutral penalties; retained official evidence is authoritative.'}
    names = set(state.get('specialists', {}))
    # EWMA and regime weights must follow market chronology, not storage order.
    records = sorted(official_snapshots(state),
                     key=lambda pair: (float(pair[0].get('opened_at') or 0), str(pair[0].get('ticker') or '')))
    names.update(n for s,_ in records for n in s['snapshot']['specialists'])
    for name in names:
        learned = state.setdefault('specialists', {}).setdefault(name, {})
        rows = []
        regimes = {}
        ewma, brier = .5, .25
        for record, outcome in records:
            snapshot = record['snapshot']; call = snapshot['specialists'].get(name)
            if not isinstance(call, dict) or not specialist_model_matches(state, name, call):
                continue
            active = specialist_active(name, call)
            direction = _direction(call.get('score')) if active else 0
            actual = 1 if outcome['kalshi_result']=='yes' else -1
            hit = int(direction==actual) if direction else None
            regime = str(snapshot.get('regime') or 'UNKNOWN')
            rows.append({'ticker':record['ticker'], 'regime':regime, 'directional_call':bool(direction),
                         'direction_correct':hit, 'signed_edge':0.0,
                         'time_reward':(1 if hit else -1) if direction else 0,
                         'label_basis':BASIS, 'kalshi_result':outcome['kalshi_result']})
            if not direction:
                continue
            ewma = .9*ewma+.1*hit
            conf = min(.99,max(.01,float(call.get('confidence',.5))))
            brier = .9*brier+.1*(conf-hit)**2
            rb=regimes.setdefault(regime,{'samples':0,'hits':0,'ewma_accuracy':.5,'adaptive_weight':1.})
            rb['samples']+=1; rb['hits']+=hit
            rb['ewma_accuracy']=.88*rb['ewma_accuracy']+.12*hit
            rb['adaptive_weight']=max(.45,min(1.65,1+min(1,rb['samples']/30)*.55*(rb['ewma_accuracy']-.5)*2))
        directional=[r for r in rows if r['directional_call']]
        n=len(directional); hits=sum(r['direction_correct'] for r in directional)
        learned.update(samples=n,direction_hits=hits,ewma_accuracy=ewma,brier_ewma=brier,
                       ewma_edge=0.0,ewma_calibration=0.0,regimes=regimes,
                       adaptive_weight=max(.35,min(1.85,1+min(1,n/60)*(ewma-.5)*1.2)),
                       accuracy_basis=BASIS)
        state.setdefault('specialist_history',{})[name]=rows
    state['specialist_accounting']={'basis':BASIS,'scope':'retained prediction snapshots',
                                    'official_markets':len(records),'neutral_calls_excluded':True,
                                    'updated_at':datetime.now(timezone.utc).isoformat()}
    return state['specialist_accounting']
