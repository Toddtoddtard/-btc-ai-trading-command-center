"""Rebuild specialist evidence from retained, pre-outcome snapshots and official results."""
import copy
from datetime import datetime, timezone
from council_v4 import specialist_active, _direction

BASIS = 'official_kalshi_directional_calls_v1'


def official_snapshots(state):
    outcomes = {str(r.get('ticker')): r for r in state.get('master_history', [])
                if r.get('kalshi_result') in ('yes','no')}
    seen = set()
    for row in state.get('prediction_snapshots', []):
        ticker = str(row.get('ticker') or '')
        if not ticker or ticker in seen or ticker not in outcomes:
            continue
        if row.get("opened_at") is not None and row.get("expires_at") is not None and float(row["opened_at"]) >= float(row["expires_at"]):
            continue
        snapshot = row.get('snapshot') or {}
        if not snapshot.get('specialists'):
            continue
        seen.add(ticker)
        yield row, outcomes[ticker]


def reconcile_specialists(state):
    """Never invent older evidence. Archive counters and label the retained scope."""
    if state.get('specialist_accounting', {}).get('basis') != BASIS:
        state['legacy_specialist_accounting'] = {
            'archived_at': datetime.now(timezone.utc).isoformat(),
            'specialists': copy.deepcopy(state.get('specialists', {})),
            'reason': 'Mixed labels and neutral penalties; retained official evidence is authoritative.'}
    names = set(state.get('specialists', {}))
    records = list(official_snapshots(state))
    names.update(n for s,_ in records for n in s['snapshot']['specialists'])
    for name in names:
        learned = state.setdefault('specialists', {}).setdefault(name, {})
        rows = []
        regimes = {}
        ewma, brier = .5, .25
        for record, outcome in records:
            snapshot = record['snapshot']; call = snapshot['specialists'].get(name)
            if not isinstance(call, dict):
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
