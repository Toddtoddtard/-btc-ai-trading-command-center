"""Frozen, paired prospective comparisons; monitoring never authorizes a trade."""
import math
import time

from contract_probability import _finite
from settlement_predictor import _observations

VERSION = 'paired-settlement-evidence-v1'
MIN_MARKETS = 100


def freeze(call):
    prediction = call.get('settlement_prediction') or {}
    values = dict(production=call.get('contract_probability_up'),
                  previous_execution=call.get('previous_contract_probability_up'),
                  market=prediction.get('market_probability_yes'),
                  independent=prediction.get('probability_yes'))
    return dict(trial_version=VERSION, code_revision=call.get('code_revision'),
                comparison_probabilities={key: float(value) for key, value in values.items()
                    if not isinstance(value, bool) and _finite(value) is not None and 0 <= float(value) <= 1})


def _interval(values):
    n = len(values)
    if not n:
        return None, None, None
    mean = sum(values)/n
    if n < 2:
        return mean, None, None
    standard_error = math.sqrt(sum((v-mean)**2 for v in values)/(n*(n-1)))
    return mean, mean-1.96*standard_error, mean+1.96*standard_error


def _accuracy_interval(hits, n):
    if not n:
        return None, None
    p, z2 = hits/n, 1.96**2
    center, width = p+z2/(2*n), 1.96*math.sqrt(p*(1-p)/n+z2/(4*n*n))
    return (center-width)/(1+z2/n), (center+width)/(1+z2/n)


def paired(rows, baseline):
    losses, accuracy_deltas, outcomes = [], [], []
    for row in rows:
        values = row.get('comparison_probabilities') or {}
        p, b = _finite(values.get('production')), _finite(values.get(baseline))
        if p is None or b is None or not (0 <= p <= 1 and 0 <= b <= 1):
            continue
        y = int(row['result'] == 'yes')
        correct, baseline_correct = int((p >= .5) == bool(y)), int((b >= .5) == bool(y))
        losses.append((b-y)**2-(p-y)**2)
        accuracy_deltas.append(correct-baseline_correct)
        outcomes.append((correct, baseline_correct, (p-y)**2, (b-y)**2))
    n = len(outcomes)
    gain, low, high = _interval(losses)
    delta, accuracy_low, accuracy_high = _interval(accuracy_deltas)
    hits = sum(r[0] for r in outcomes)
    lower, upper = _accuracy_interval(hits, n)
    status = 'COLLECTING'
    if n >= MIN_MARKETS:
        status = ('NOT_IMPROVED' if gain <= 0 or delta < 0 else
                  'IMPROVED_ON_OBSERVED_MARKETS' if low > 0 and accuracy_low >= 0 else 'INCONCLUSIVE')
    return dict(samples=n, accuracy=hits/n if n else None,
        baseline_accuracy=sum(r[1] for r in outcomes)/n if n else None,
        accuracy_low=lower, accuracy_high=upper, accuracy_delta=delta,
        accuracy_delta_low=accuracy_low, accuracy_delta_high=accuracy_high,
        brier=sum(r[2] for r in outcomes)/n if n else None,
        baseline_brier=sum(r[3] for r in outcomes)/n if n else None,
        brier_gain=gain, brier_gain_low=low, brier_gain_high=high,
        target_70_verified=bool(n >= MIN_MARKETS and lower >= .70), status=status)


def scorecard(state, as_of=None):
    as_of = time.time() if as_of is None else float(as_of)
    root = (state or {}).get('settlement_predictor') or {}
    history = [r for r in root.get('history') or [] if r.get('trial_version') == VERSION]
    captures = history + [r for r in root.get('pending') or [] if r.get('trial_version') == VERSION]
    captures = [r for r in captures if _finite(r.get('opened_at')) is not None
                and r['opened_at'] <= as_of and isinstance(r.get('code_revision'), str)
                and r['code_revision'].strip()]
    status = state.get('status') or {}
    revision = status.get('code_revision') if status.get('prediction_policy_version') == VERSION else None
    if not revision and captures:
        revision = max(captures, key=lambda r: r['opened_at'])['code_revision']
    history = [r for r in history if revision and r.get('code_revision') == revision]
    captures = [r for r in captures if revision and r['code_revision'] == revision]
    observed = {'settlement_predictor': {'history': history}}
    def compare(rows):
        return {name: paired(rows, name) for name in ('previous_execution', 'market', 'independent')}
    trades = [t for t in ((state.get('background_paper') or {}).get('trades') or [])
              if t.get('forecast_trial_version') == VERSION and t.get('status') == 'CLOSED'
              and revision and t.get('code_revision') == revision
              and _finite(t.get('closed_at')) is not None and t['closed_at'] <= as_of
              and _finite(t.get('pnl')) is not None]
    pnl = [float(t['pnl']) for t in trades]
    wins, losses = sum(p > 0 for p in pnl), sum(p < 0 for p in pnl)
    latest = max(captures, key=lambda r: r['opened_at']) if captures else {}
    return dict(version=VERSION, minimum_markets=MIN_MARKETS,
        interval_note='95% Wilson accuracy; approximate paired 95% Brier/accuracy-difference intervals. '
                      'One contract per row; market dependence and multiple timing comparisons limit inference. '
                      'Observed gains do not establish future profits. No automatic promotion.',
        code_revision=revision,
        cohort_scope='Exact producing revision only; missing revisions and other builds are excluded.',
        first_capture=min((r['opened_at'] for r in captures), default=None),
        latest_capture=latest.get('opened_at'),
        captured_markets=len({r['ticker'] for r in captures}),
        overall=compare(_observations(observed, as_of)),
        by_horizon={str(m)+'m': compare(_observations(observed, as_of, m*60)) for m in (10, 5, 1)},
        paper=dict(closed_trades=len(pnl), wins=wins, losses=losses,
                   net_pnl=sum(pnl), win_rate=wins/(wins+losses) if wins+losses else None,
                   scope='Actual tagged new-version paper trades only; includes recorded fees.'))


def display_forecast(prediction, decision):
    """Headline probability belongs to the actual shared production selector."""
    result = dict(prediction or {})
    p = _finite((decision or {}).get('contract_probability_up'))
    if (not result.get('available') or result.get('ticker') != (decision or {}).get('kalshi_ticker')
            or p is None or not 0 <= p <= 1):
        return dict(result, available=False, reason='Matching current production probability required')
    result.update(probability_yes=p, probability_no=1-p, outcome='YES' if p >= .5 else 'NO',
                  probability_source=decision.get('contract_probability_source'))
    return result


def publish_summary(path, as_of=None):
    import json
    from pathlib import Path
    from background_paper import save_checkpoint
    state = json.loads(Path(path).read_text())
    report = scorecard(state, as_of=as_of)
    state['improvement_evidence'] = report
    save_checkpoint(path, state)
    return report


if __name__ == '__main__':
    import json
    import os
    report = publish_summary(os.environ.get('LEARNING_STATE_OUTPUT', '/tmp/learning_state.json'))
    print(json.dumps(dict(code_revision=report['code_revision'],
                          primary_10m_comparison=report['by_horizon']['10m'], paper=report['paper'])))
