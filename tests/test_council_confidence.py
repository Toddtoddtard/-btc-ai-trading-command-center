import copy
import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from council_accounting import reconcile_master_learning
from council_v4 import council_vote
from council_confidence import BASIS, apply, fit, for_direction
from council_accounting import official_snapshots
from specialist_knowledge_v5 import knowledge_council_vote
from reliability_v31 import (learned_policy, learned_trade_gate, calibrate_confidence,
                             safe_float, source_health_from_specialists)
from contract_probability import realized_minute_volatility, terminal_above_probability
from contract_calibration import apply as apply_contract_calibration
from lock_focus import evaluate_lock_focus, specialist_consensus


class CouncilConfidenceTests(unittest.TestCase):
    def history(self, confidence=.5, count=240):
        state = {'prediction_snapshots': [], 'master_history': []}
        for i in range(count):
            state['prediction_snapshots'].append({
                'ticker': str(i), 'opened_at': i*900+1, 'expires_at': i*900+900,
                'snapshot': {'master_base_score': .3, 'master_confidence': confidence,
                             'specialists': {'Trend AI': {'score': .3}}}})
            state['master_history'].append({
                'ticker': str(i), 'kalshi_result': 'no' if i % 4 == 0 else 'yes',
                'official_observed_at': i*900+910})
        return state

    def test_official_learning_can_raise_underconfident_calls_only_after_validation(self):
        state = self.history(confidence=.65)
        reconcile_master_learning(state)
        self.assertIn('council_confidence_calibration', state)
        model = state['council_confidence_calibration']
        self.assertTrue(model['active'])
        self.assertGreater(model['validation']['brier_improvement'], 0)
        results = {name: {'score': .1, 'confidence': .7, 'reason': 'healthy'}
                   for name in ('Trend AI', 'Momentum AI', 'Volume AI')}
        results.update({name: {'score': 0., 'reason': 'healthy'} for name in
                        ('Liquidity AI', 'Derivatives AI', 'Kalshi Context AI', 'Whale AI')})
        baseline = copy.deepcopy(state)
        baseline.pop('council_confidence_calibration')
        learned, original = council_vote(results, state), council_vote(results, baseline)
        self.assertGreater(learned['confidence'], original['confidence'])
        self.assertEqual(learned['base_score'], original['base_score'])
        self.assertLessEqual(learned['confidence']-original['confidence'], .15)

    def test_insufficient_evidence_does_not_change_confidence(self):
        state = self.history(count=120)
        reconcile_master_learning(state)
        self.assertIn('council_confidence_calibration', state)
        self.assertFalse(state['council_confidence_calibration']['active'])
        self.assertEqual(apply(.5, state), .5)

    def test_overconfident_calls_can_be_lowered(self):
        state = self.history(confidence=.9)
        reconcile_master_learning(state)
        self.assertTrue(state['council_confidence_calibration']['active'])
        self.assertLess(apply(.9, state), .9)

    def test_calibrated_evidence_keeps_formula(self):
        state = self.history(confidence=.75)
        reconcile_master_learning(state)
        self.assertFalse(state['council_confidence_calibration']['active'])

    def test_duplicates_order_and_future_labels_cannot_change_prior_fit(self):
        state = self.history()
        as_of = 150*900
        original = fit(list(official_snapshots(state)), as_of=as_of)
        state['prediction_snapshots'] += copy.deepcopy(state['prediction_snapshots'])
        state['prediction_snapshots'].reverse()
        self.assertEqual(original, fit(list(official_snapshots(state)), as_of=as_of))
        for outcome in state['master_history'][150:]:
            outcome['kalshi_result'] = 'no'
        self.assertEqual(original, fit(list(official_snapshots(state)), as_of=as_of))

    def test_delayed_labels_are_not_used_at_earlier_captures(self):
        state = self.history()
        for row in state['master_history']:
            row['official_observed_at'] = 1e12
        model = fit(list(official_snapshots(state)))
        self.assertEqual(model['validation']['samples'], 0)
        self.assertFalse(model['active'])

    def test_formula_evidence_prevents_recursive_confidence_inflation(self):
        original = self.history(confidence=.65)
        corrected = copy.deepcopy(original)
        for row in corrected['prediction_snapshots']:
            row['snapshot']['council_formula_confidence'] = .65
            row['snapshot']['master_confidence'] = .8
        self.assertEqual(fit(list(official_snapshots(original))),
                         fit(list(official_snapshots(corrected))))

    def test_new_confidence_band_requires_its_own_validation(self):
        state = self.history(confidence=.65, count=270)
        for i, row in enumerate(state['prediction_snapshots'][240:]):
            row['snapshot']['master_confidence'] = .9
            state['master_history'][240+i]['kalshi_result'] = 'no'
        reconcile_master_learning(state)
        self.assertTrue(state['council_confidence_calibration']['active'])
        self.assertEqual(apply(.9, state), .9)

    def test_malformed_saved_model_keeps_formula_available(self):
        for bands in (None, {}, {'6': {'samples': 'bad'}},
                      {'6': {'samples': 100, 'validated': True}},
                      {'6': {'samples': 100, 'residual_sum': float('nan'), 'validated': True}}):
            with self.subTest(bands=bands):
                state = {'council_confidence_calibration': dict(basis=BASIS, active=True, bands=bands)}
                self.assertEqual(apply(.65, state), .65)

    def test_dashboard_uses_same_confidence_as_worker_without_second_penalty(self):
        state = self.history(confidence=.65)
        reconcile_master_learning(state)
        results = {name: dict(name=name, score=.1, confidence=.7, signal='BULLISH')
                   for name in ('Trend AI', 'Momentum AI', 'Volume AI')}
        frame = pd.DataFrame({k: [83000.]*61 for k in ('open', 'high', 'low', 'close')})
        frame['atr14'] = 50.
        for available, side in ((True, 1), (False, 1), (True, -1)):
            for item in results.values():
                item['score'] = side*.1
            council = knowledge_council_vote(results, state, 'UNKNOWN')['confidence']
            expected = council if side > 0 or not available else 1-council
            ctx = dict(available=available, target=82000., seconds_remaining=600,
                       up_probability=.8, ticker='', market={})
            namespace = dict(
                np=np, pd=pd, fetch_remote_learning_state=lambda: state,
                detect_regime=lambda _: 'UNKNOWN', learned_policy=learned_policy,
                knowledge_council_vote=knowledge_council_vote,
                confidence_for_direction=for_direction,
                clamp=lambda x: float(np.clip(x, -1., 1.)), safe_float=safe_float,
                source_health_from_specialists=source_health_from_specialists,
                stable_kalshi_contract=lambda *a: ctx, _persistent_window_lock_side=lambda _: None,
                realized_minute_volatility=realized_minute_volatility,
                terminal_above_probability=terminal_above_probability,
                apply_contract_calibration=apply_contract_calibration,
                calibrate_confidence=calibrate_confidence, specialist_consensus=specialist_consensus,
                evaluate_lock_focus=evaluate_lock_focus, learned_trade_gate=learned_trade_gate,
                AUTO_SCALPING_ENABLED=True, build_next_market_outlooks=lambda *a: [])
            node = next(n for n in ast.parse(Path('app.py').read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'master_decision')
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
            decision = namespace['master_decision'](results, frame)
            self.assertAlmostEqual(decision['confidence'], expected)


if __name__ == '__main__':
    unittest.main()
