"""Frozen, paired prospective comparisons; monitoring never authorizes a trade."""
import math
import time

from contract_probability import _finite
from settlement_predictor import CHECKPOINT_TOLERANCE, _observations, official_observation_times

VERSION = 'paired-settlement-evidence-v1'
MIN_MARKETS = 100
CHECKPOINTS = (10, 8, 5, 2, 1)
# Bump only when the live forecast inputs, model or selector change.
FORECAST_POLICY = 'settlement-selector-v1'
LEGACY_POLICY_REVISIONS = {'7d194b3346884e8baebd9defaf11d666112eaa65': FORECAST_POLICY}
SHADOW = 'order_book_blend_v1'


def freeze(call):
    prediction = call.get('settlement_prediction') or {}
    values = dict(production=call.get('contract_probability_up'),
                  previous_execution=call.get('previous_contract_probability_up'),
                  market=prediction.get('market_probability_yes'),
                  independent=prediction.get('probability_yes'))
    raw = _finite(call.get('raw_contract_probability_up'))
    market = _finite(values['market'])
    if (prediction.get('available') and raw is not None and 0 <= raw <= 1
            and market is not None and 0 <= market <= 1):
        # Freeze the pre-calibration model (reference/strike, time and depth).
        values[SHADOW] = raw
    return dict(trial_version=VERSION, code_revision=call.get('code_revision'),
                forecast_policy=call.get('forecast_policy'),
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


def forecast_policy(row):
    revision = row.get('code_revision')
    return row.get('forecast_policy') or LEGACY_POLICY_REVISIONS.get(revision, revision)


def archive_checkpoints(state):
    """Keep compact official checkpoint records beyond the learner's rolling history."""
    history = (state.get('settlement_predictor') or {}).get('history') or []
    archive = state.setdefault('official_forecast_checkpoints', {})
    for row in history:
        policy = forecast_policy(row)
        ticker, opened, expiry = row.get('ticker'), _finite(row.get('opened_at')), _finite(row.get('expires_at'))
        observed = _finite(row.get('result_observed_at'))
        if (row.get('trial_version') != VERSION or not policy or not ticker
                or opened is None or expiry is None or observed is None
                or not opened < expiry <= observed or row.get('result') not in ('yes', 'no')):
            continue
        by_ticker = archive.setdefault(policy, {}).setdefault(ticker, {})
        by_ticker.setdefault('settled', expiry)
        probabilities = row.get('comparison_probabilities') or {}
        matched = [_finite(probabilities.get(name)) for name in ('production', 'market')]
        if (not official_observation_times(row, float('inf'))
                or any(value is None or not 0 <= value <= 1 for value in matched)):
            continue
        lead = expiry - opened
        eligible = ['overall'] + [f'{m}m' for m in CHECKPOINTS
                                 if m*60 <= lead <= m*60 + CHECKPOINT_TOLERANCE]
        record = dict(opened_at=opened, result_observed_at=observed, result=row['result'],
                      code_revision=row.get('code_revision'),
                      comparison_probabilities=dict(probabilities))
        for checkpoint in eligible:
            previous = by_ticker.get(checkpoint)
            if previous is None or (opened < previous['opened_at'] if checkpoint == 'overall'
                                    else opened > previous['opened_at']):
                by_ticker[checkpoint] = record


def scorecard(state, as_of=None):
    as_of = time.time() if as_of is None else float(as_of)
    root = (state or {}).get('settlement_predictor') or {}
    history = [r for r in root.get('history') or [] if r.get('trial_version') == VERSION]
    captures = history + [r for r in root.get('pending') or [] if r.get('trial_version') == VERSION]
    captures = [r for r in captures if _finite(r.get('opened_at')) is not None
                and r['opened_at'] <= as_of and forecast_policy(r)]
    status = state.get('status') or {}
    revision = status.get('code_revision') if status.get('prediction_policy_version') == VERSION else None
    newest = max(captures, key=lambda r: r['opened_at'], default={})
    revision = revision or newest.get('code_revision')
    policy = status.get('forecast_policy') or forecast_policy(dict(code_revision=revision)) or forecast_policy(newest)
    captures = [r for r in captures if policy and forecast_policy(r) == policy]
    archives = (state.get('official_forecast_checkpoints') or {}).get(policy) or {}
    observed = {'settlement_predictor': {'history': [r for r in history if policy and forecast_policy(r) == policy]}}

    def rows_at(checkpoint, seconds=None):
        records = {ticker: saved[checkpoint] for ticker, saved in archives.items()
                   if checkpoint in saved and saved[checkpoint]['result_observed_at'] <= as_of}
        for row in _observations(observed, as_of, seconds):
            old = records.get(row['ticker'])
            if old is None or (row['opened_at'] < old['opened_at'] if seconds is None
                               else row['opened_at'] > old['opened_at']):
                records[row['ticker']] = row
        return list(records.values())

    opened_times = [r['opened_at'] for r in captures]
    opened_times.extend(saved['overall']['opened_at'] for saved in archives.values()
                        if 'overall' in saved and saved['overall']['opened_at'] <= as_of)
    opened_times.extend(saved[label]['opened_at'] for saved in archives.values()
                        for label in ('10m', '8m', '5m', '2m', '1m')
                        if label in saved and saved[label]['opened_at'] <= as_of)
    settled_windows = {expiry for r in captures if (expiry := _finite(r.get('expires_at'))) is not None
                       and expiry <= as_of}
    settled_windows.update(row['settled'] for row in archives.values() if row['settled'] <= as_of)
    scheduled = 1 + int((max(settled_windows)-min(settled_windows)) // 900) if settled_windows else 0
    by_horizon, coverage, shadow = {}, {}, {}

    def compare(rows):
        return {name: paired(rows, name) for name in ('previous_execution', 'market', 'independent')}

    for minutes in CHECKPOINTS:
        label = f'{minutes}m'
        rows = rows_at(label, minutes*60)
        by_horizon[label] = compare(rows)
        coverage[label] = dict(scheduled=scheduled, forecast=by_horizon[label]['market']['samples'])
        candidate_rows = [dict(row, comparison_probabilities=dict(values, production=values[SHADOW],
                               incumbent=values['production']))
                          for row in rows if SHADOW in (values := row.get('comparison_probabilities') or {})
                          and 'production' in values]
        shadow[label] = {name: paired(candidate_rows, name) for name in ('market', 'incumbent')}

    trades = [t for t in ((state.get('background_paper') or {}).get('trades') or [])
              if t.get('forecast_trial_version') == VERSION and t.get('status') == 'CLOSED'
              and revision and t.get('code_revision') == revision
              and _finite(t.get('closed_at')) is not None and t['closed_at'] <= as_of
              and _finite(t.get('pnl')) is not None]
    pnl = [float(t['pnl']) for t in trades]
    wins, losses = sum(p > 0 for p in pnl), sum(p < 0 for p in pnl)
    return dict(version=VERSION, minimum_markets=MIN_MARKETS,
        interval_note='95% Wilson accuracy; approximate paired 95% Brier/accuracy-difference intervals. '
                      'One contract per row; market dependence and multiple timing comparisons limit inference. '
                      'Observed gains do not establish future profits. No automatic promotion.',
        code_revision=revision,
        forecast_policy=policy,
        cohort_scope='Same forecast policy across dashboard builds. Paper performance is for the current worker build.',
        checkpoint_coverage=coverage, shadow=shadow,
        first_capture=min(opened_times, default=None),
        latest_capture=max(opened_times, default=None),
        captured_markets=len(set(archives) | {r['ticker'] for r in captures}),
        overall=compare(rows_at('overall')), by_horizon=by_horizon,
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


def dashboard_forecast(decision, preview, now=None):
    """Use the current worker probability when available, with a display-only fallback."""
    result = display_forecast(decision.get('settlement_prediction'), decision)
    if result['available'] and decision.get('authoritative_available'):
        return dict(result, preview_only=False)
    if preview.get('kalshi_ticker') == decision.get('kalshi_ticker'):
        forecast = display_forecast(preview.get('settlement_prediction'), preview)
        expires = _finite(forecast.get('expires_at'))
        if forecast['available'] and expires is not None and expires > (time.time() if now is None else now):
            return dict(forecast, preview_only=True)
        reason = (preview.get('settlement_prediction') or {}).get('reason')
        if reason and not (preview.get('settlement_prediction') or {}).get('available'):
            return dict(result, available=False, reason=reason)
    return dict(result, available=False, reason='Fresh Kalshi forecast for the active market required')


def publish_summary(path, as_of=None):
    import json
    from pathlib import Path
    from background_paper import save_checkpoint
    state = json.loads(Path(path).read_text())
    if (state.get('settlement_predictor') or {}).get('history'):
        archive_checkpoints(state)
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
