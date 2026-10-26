import copy
import inspect
import ast
from pathlib import Path
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import contract_calibration as calibration
import learner
from audit_scorecard_v7 import _score
from learner_v31 import refresh_pending_lock_focus
from settlement_predictor import VERSION
from kalshi_paper_engine import expected_lock_net_pnl
import numpy as np
import pandas as pd


class SettlementExecutionTests(unittest.TestCase):
    def history(self, count=220, lead=700):
        rows = []
        for i in range(count):
            opened = i * 900
            ticker = 'T' + str(i)
            prediction = dict(available=True, version=VERSION, ticker=ticker,
                              captured_at=opened, expires_at=opened+lead,
                              quotes_observed_at=opened, reference_timestamp=opened,
                              base_probability_yes=.85, probability_yes=.85,
                              market_probability_yes=.6)
            rows.append(dict(ticker=ticker, opened_at=opened, expires_at=opened+lead,
                             result_observed_at=opened+lead+20, result='yes',
                             settlement_prediction=prediction))
        return rows

    def fit(self, rows):
        function = getattr(calibration, 'fit_settlement', None)
        self.assertIsNotNone(function, 'Settlement forecasts need their own execution qualification')
        return function({'settlement_predictor': {'history': rows}}, as_of=200000)

    def prediction(self):
        return dict(available=True, version=VERSION, ticker='LIVE', captured_at=200000,
                    expires_at=200700, base_probability_yes=.85, probability_yes=.99,
                    market_probability_yes=.6)

    def apply(self, state, prediction=None):
        self.assertIn('settlement', inspect.signature(calibration.apply).parameters)
        view = dict(available=True, probability_up=.4, market_probability_up=.6,
                    seconds_remaining=700, ticker='LIVE')
        return calibration.apply(view, state, settlement=prediction or self.prediction(), now=200000)

    def test_validated_settlement_forecast_can_reach_fee_aware_execution(self):
        model = self.fit(self.history())
        view = self.apply({'settlement_execution_calibration': model})
        self.assertTrue(view['calibrator_active'])
        self.assertEqual(view['probability_source'], VERSION)
        self.assertGreater(view['probability_up'], .7)
        decision = dict(contract_probability_basis=view['probability_basis'],
                        contract_calibrator_active=view['calibrator_active'],
                        contract_probability_up=view['probability_up'])
        self.assertGreater(expected_lock_net_pnl(10, .61, decision, 'YES'), 0)

    def test_duplicate_captures_and_other_horizons_do_not_inflate_evidence(self):
        rows = self.history()
        model = self.fit(rows + copy.deepcopy(rows) + self.history(lead=350))
        self.assertEqual(model['by_horizon']['10m+']['training_markets'], 220)
        self.assertEqual(model['by_horizon']['5m+']['training_markets'], 220)
        # A model earned at 10+ minutes cannot authorize a late-window estimate.
        early_only = self.fit(rows)
        p = self.prediction()
        p['expires_at'] = 200350
        view = self.apply({'settlement_execution_calibration': early_only}, p)
        self.assertFalse(view['calibrator_active'])

    def test_delayed_labels_and_wrong_model_versions_cannot_train(self):
        rows = self.history()
        for row in rows:
            row['result_observed_at'] = 300000
        self.assertEqual(self.fit(rows)['by_horizon']['10m+']['training_markets'], 0)

        rows = self.history()
        for row in rows:
            row['settlement_prediction']['version'] = 'OLD'
        self.assertEqual(self.fit(rows)['by_horizon']['10m+']['training_markets'], 0)

    def test_unverified_legacy_quote_freshness_cannot_earn_execution_promotion(self):
        rows = self.history()
        for row in rows:
            row['settlement_prediction'].pop('quotes_observed_at')
        self.assertEqual(self.fit(rows)['by_horizon']['10m+']['training_markets'], 0)

    def test_harmful_settlement_model_remains_inactive_with_explicit_reason(self):
        rows = self.history()
        for i, row in enumerate(rows):
            row['result'] = 'yes' if i % 5 < 3 else 'no'
        view = self.apply({'settlement_execution_calibration': self.fit(rows)})
        self.assertFalse(view['calibrator_active'])
        self.assertEqual(view['probability_up'], .6)
        self.assertIn('No validated', view['execution_probability_reason'])

    def test_stale_wrong_ticker_and_wrong_market_estimates_cannot_authorize(self):
        state = {'settlement_execution_calibration': self.fit(self.history())}
        for changes in ({'captured_at': 199969}, {'ticker': 'OTHER'},
                        {'market_probability_yes': .4}, {'available': False},
                        {'expires_at': 200800},
                        {'base_probability_yes': float('nan')}):
            with self.subTest(changes=changes):
                view = self.apply(state, dict(self.prediction(), **changes))
                self.assertFalse(view['calibrator_active'])

    def test_first_decision_is_frozen_separately_from_binance_path(self):
        pending = dict(ticker='T', master_action='WAIT', predicted_end=120, target=100)
        state = {'pending': pending}
        live = dict(ticker='T', opened_at=1000, master_action='SCALP DOWN',
                    contract_probability_up=.2, contract_probability_source=VERSION)
        refresh_pending_lock_focus(state, live, {'ticker': 'T'})
        frozen = copy.deepcopy(pending.get('official_decision'))
        self.assertIsNotNone(frozen)
        self.assertFalse(frozen['predicted_yes'])
        refresh_pending_lock_focus(state, dict(live, opened_at=1100,
                                   master_action='SCALP UP', contract_probability_up=.9), {'ticker': 'T'})
        self.assertEqual(pending['official_decision'], frozen)
        self.assertEqual(pending['predicted_end'], 120)

    def test_official_scoring_uses_frozen_decision_and_preserves_legacy_outcome(self):
        decision = dict(predicted_yes=False, captured_at=1000, source=VERSION)
        row = dict(ticker='T', direction_correct=1)
        state = dict(forecast={}, master_history=[row], official_pending=[
            dict(ticker='T', predicted_end=120, target=100, official_decision=decision)])
        with patch.object(learner, 'official_result', return_value='no'):
            learner.resolve_official_results(state)
        self.assertEqual(row['kalshi_correct'], 0)  # Historical path remains a loss.
        self.assertEqual(row.get('official_decision_correct'), 1)
        self.assertEqual(state['forecast'].get('official_decision_hits'), 1)

    def test_scorecard_never_labels_proxy_settlement_as_btc_direction(self):
        rows = [dict(direction_correct=1, btc_move_correct=0, kalshi_correct=0,
                     official_decision_correct=1), dict(direction_correct=1)]
        score = _score(rows)
        self.assertEqual(score['direction_accuracy'], 0)
        self.assertEqual(score.get('proxy_settlement_accuracy'), 1)
        self.assertEqual(score.get('official_decision_accuracy'), 1)
        self.assertEqual(score.get('official_decision_samples'), 1)

    def test_dashboard_and_worker_select_same_validated_settlement_probability(self):
        import learner_v31 as worker
        import reliability_v31 as reliability
        import lock_focus
        from council_confidence import for_direction
        from tests.test_reliability_v31 import ReliabilityTests
        state = {'settlement_execution_calibration': self.fit(self.history())}
        prediction = dict(self.prediction(), expected_final_average=101.)
        ctx = dict(available=True, target=100., seconds_remaining=700,
                   up_probability=.6, ticker='LIVE', close_time='1970-01-03T07:45:00Z',
                   market=dict(yes_bid_dollars=.59, yes_ask_dollars=.61), orderbook={})
        vote = dict(confidence=.8, base_score=.5, consensus=1., precision_gate_passed=True)
        ns = dict(np=np, pd=pd, fetch_remote_learning_state=lambda: state,
            detect_regime=lambda _: 'RANGE', learned_policy=reliability.learned_policy,
            knowledge_council_vote=lambda *a, **k: vote, confidence_for_direction=for_direction,
            clamp=lambda x: float(np.clip(x, -1., 1.)), safe_float=reliability.safe_float,
            source_health_from_specialists=lambda _: 1., stable_kalshi_contract=lambda *a: ctx,
            _persistent_window_lock_side=lambda _: None, _register_window_lock=lambda *a: None,
            realized_minute_volatility=lambda _: .001,
            terminal_above_probability=lambda **k: dict(available=True, probability_up=.4,
                market_probability_up=.6, seconds_remaining=700),
            apply_contract_calibration=calibration.apply, predict_settlement=lambda *a, **k: prediction,
            specialist_consensus=lambda *a: 1., evaluate_lock_focus=lock_focus.evaluate_lock_focus,
            learned_trade_gate=reliability.learned_trade_gate, AUTO_SCALPING_ENABLED=True,
            build_next_market_outlooks=lambda *a: [])
        node = next(n for n in ast.parse(Path('app.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'master_decision')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        self.assertIn('settlement_reference', inspect.signature(ns['master_decision']).parameters)
        frame = pd.DataFrame({key: [100.]*61 for key in ('open', 'high', 'low', 'close')})
        frame['atr14'] = 1.
        with patch('contract_calibration.time.time', return_value=200000):
            dashboard = ns['master_decision']({}, frame, settlement_reference={'available': True})
        with ExitStack() as stack:
            ReliabilityTests().shadow_dependencies(stack)
            stack.enter_context(patch.object(worker.time, 'time', return_value=200000))
            stack.enter_context(patch.object(worker, 'predict_settlement', return_value=prediction))
            stack.enter_context(patch.object(worker, 'knowledge_council_vote', return_value=vote))
            stack.enter_context(patch.object(worker, 'terminal_above_probability',
                return_value=dict(available=True, probability_up=.4, market_probability_up=.6,
                                  seconds_remaining=700)))
            call = worker.current_shadow_call(state, frame,
                        dict(ticker='LIVE', expires_at=200700, target=100., prob=.6))
        self.assertEqual(dashboard['contract_probability_source'], VERSION)
        self.assertEqual(dashboard['contract_probability_up'], call['contract_probability_up'])
        self.assertTrue(call['contract_calibrator_active'])

    def test_dashboard_learning_cards_use_btc_and_official_decision_labels(self):
        remote = dict(forecast=dict(samples=2, direction_hits=2, btc_move_samples=2,
                                   btc_move_hits=0), master_history=[
            dict(direction_correct=1, official_decision_correct=0),
            dict(direction_correct=1)])
        ns = dict(np=np, pd=pd, fetch_remote_learning_state=lambda: remote)
        names = {'_remote_learning_is_usable', 'get_learning_state', 'rolling_master_accuracy'}
        for node in ast.parse(Path('app.py').read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), ns)
        self.assertEqual(ns['get_learning_state']()['direction_accuracy'], 0)
        rolling = ns['rolling_master_accuracy'](100)
        self.assertEqual(rolling['samples'], 1)
        self.assertEqual(rolling['accuracy'], 0)
        self.assertEqual(ns['rolling_master_accuracy'](1)['samples'], 1)

    def test_worker_rolling_scores_keep_proxy_separate(self):
        from learner_v3 import update_rolling
        state = dict(master_history=[dict(direction_correct=1, btc_move_correct=0,
                         official_decision_correct=0)])
        update_rolling(state)
        self.assertEqual(state['rolling']['25']['direction_accuracy'], 0)
        self.assertEqual(state['rolling']['25']['proxy_settlement_accuracy'], 1)

    def test_missing_horizon_on_expired_or_outside_window_forecast_abstains(self):
        for expiry in (199999, 200901):
            with self.subTest(expiry=expiry):
                p = dict(self.prediction(), expires_at=expiry)
                view = calibration.apply(dict(probability_up=.4, market_probability_up=.6,
                    ticker='LIVE'), {}, settlement=p, now=200000)
                self.assertFalse(view['calibrator_active'])
                self.assertEqual(view['probability_up'], .6)
