import copy
import unittest
from unittest.mock import patch

import pandas as pd

from ai_core import candle_structure_signal, enrich_history_core, run_specialists_core
from candle_learning import FEATURE_NAMES, features
from council_accounting import reconcile_specialists
from council_v4 import analyze_bot_contributions, _contribution_multiplier
from signal_education import detect_signals, summarize_signals


class LiquiditySweepTests(unittest.TestCase):
    def bars(self, side='low'):
        frame = pd.DataFrame(dict(
            time=pd.date_range('2026-01-01', periods=70, freq='min', tz='UTC'),
            open=100., high=101., low=99., close=100., volume=10.))
        values = {'low': [100., 100.7, 98., 100.2],
                  'high': [100., 102., 99.3, 99.8],
                  'both': [100., 102., 98., 100.],
                  'breakout': [100., 102., 99.8, 101.5],
                  'touch': [100., 101., 99., 100.]}
        frame.loc[69, ['open', 'high', 'low', 'close']] = values[side]
        return frame, frame.time.iloc[-1].timestamp() + 60

    def test_shared_pattern_and_learned_features_recognize_both_reclaims(self):
        for side, direction, name in [('low', 1, 'Bullish liquidity sweep'),
                                       ('high', -1, 'Bearish liquidity sweep')]:
            frame, now = self.bars(side)
            with self.subTest(side=side):
                score, reason = candle_structure_signal(enrich_history_core(frame))
                self.assertGreater(direction * score, .3)
                self.assertIn(name.lower(), reason)
                signals = {s['name']: s for s in detect_signals(frame, now)}
                self.assertEqual(signals[name]['direction'], 'YES' if direction > 0 else 'NO')
                self.assertEqual(signals[name]['invalidation'], 98. if direction > 0 else 102.)
                self.assertEqual(features(frame)[FEATURE_NAMES.index('sweep_' + side)], 1.)

    def test_breakout_touch_and_two_sided_bar_are_not_directional_sweeps(self):
        for side in ('breakout', 'touch', 'both'):
            frame, now = self.bars(side)
            with self.subTest(side=side):
                self.assertFalse(any('liquidity sweep' in s['name'].lower()
                                     for s in detect_signals(frame, now)))
                self.assertNotIn('liquidity sweep', candle_structure_signal(enrich_history_core(frame))[1])

    def test_unfinished_sweep_is_not_seen_and_future_candles_cannot_change_capture(self):
        frame, now = self.bars()
        self.assertFalse(any('liquidity sweep' in s['name'].lower()
                             for s in detect_signals(frame, now - 1)))
        first = detect_signals(frame, now)
        future = frame.iloc[[-1]].copy()
        future['time'] += pd.Timedelta(minutes=1)
        future[['open', 'high', 'low', 'close']] = [100., 500., 1., 400.]
        self.assertEqual(first, detect_signals(pd.concat([frame, future]), now))

    def test_live_pattern_cannot_use_forming_sweep_candle(self):
        frame, now = self.bars()
        with patch('candle_learning.time.time', return_value=now-1):
            result = run_specialists_core(enrich_history_core(frame), None, {}, {})['Pattern AI']
        self.assertNotIn('liquidity sweep', result['reason'])
        with patch('candle_learning.time.time', return_value=now):
            result = run_specialists_core(enrich_history_core(frame), None, {}, {})['Pattern AI']
        self.assertIn('bullish liquidity sweep', result['reason'])

    def test_sweep_is_graded_against_strike_outcome_not_bounce(self):
        frame, now = self.bars()
        signals = {s['name']: s for s in detect_signals(frame, now)}
        self.assertIn('Bullish liquidity sweep', signals)
        signal = signals['Bullish liquidity sweep']
        row = dict(ticker='A', opened_at=now, expires_at=now+300, result='no',
                   phase='OPEN', yes_ask=.4, no_ask=.6, named_signals=[signal])
        total = next(r for r in summarize_signals([row])['ranking'] if r['context'] == 'ALL')
        self.assertEqual((total['samples'], total['wins']), (1, 0))
        self.assertLess(total['net_pnl'], -.4)

    def evidence(self, version):
        call = dict(score=.5, confidence=.7)
        if version is not None:
            call['model_version'] = version
        return dict(pattern_structure_version=3, prediction_snapshots=[dict(
            ticker='A', opened_at=10, expires_at=900,
            snapshot=dict(specialists={'Pattern AI': call, 'Trend AI': dict(score=.5)}))],
            master_history=[dict(ticker='A', kalshi_result='yes')])

    def test_old_pattern_scores_do_not_return_after_learning_reconciliation(self):
        for version in (None, 2, 3):
            state = self.evidence(version)
            original = copy.deepcopy(state['prediction_snapshots'])
            reconcile_specialists(state)
            with self.subTest(version=version):
                self.assertEqual(state['specialists']['Pattern AI']['samples'], int(version == 3))
                self.assertEqual(state['specialists']['Trend AI']['samples'], 1)
                self.assertEqual(state['prediction_snapshots'], original)

    def test_old_pattern_contributions_cannot_weight_new_model(self):
        for version in (None, 2, 3):
            result = analyze_bot_contributions(self.evidence(version))
            rows = [r for r in result['ranking'] if r['name'] == 'Pattern AI']
            with self.subTest(version=version):
                self.assertEqual(sum(r['active_samples'] for r in rows), int(version == 3))
        state = self.evidence(3)
        state['bot_intelligence_v4'] = dict(
            evidence_version=2, label_basis='official_kalshi_directional_calls_v1',
            evaluation_mode='causal_prior_only_ablation', ranking=[dict(
                name='Pattern AI', evidence_passed=True, evidence_streak=3, stable_multiplier=1.3)])
        self.assertEqual(_contribution_multiplier(state, 'Pattern AI'), 1.)

    def test_live_specialist_carries_new_model_identity(self):
        frame, _ = self.bars()
        results = run_specialists_core(enrich_history_core(frame), None, {}, {})
        self.assertEqual(results['Pattern AI'].get('model_version'), 3)


if __name__ == '__main__':
    unittest.main()
