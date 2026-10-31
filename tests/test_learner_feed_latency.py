"""Real worker orchestration with synchronized, offline data sources."""
import ast
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier
import unittest
from unittest.mock import patch

import pandas as pd

import learner
import learner_v31 as worker
from tests import test_reliability_v31 as fixtures


class LearnerFeedLatencyTests(unittest.TestCase):
    def test_futures_primary_reads_overlap(self):
        barrier = Barrier(3, timeout=1)
        def read(url, params):
            barrier.wait()
            return {
                'depth': {'bids': [['99', '2']], 'asks': [['101', '1']]},
                'premiumIndex': {'lastFundingRate': '.0001'},
                'openInterest': {'openInterest': '20'},
            }[url.rsplit('/', 1)[-1]]
        with patch.object(learner, 'get', side_effect=read):
            result = learner.futures_snapshot()
        self.assertTrue(result['ok'])
        self.assertEqual(result['funding_rate'], .0001)
        self.assertEqual(result['open_interest'], 20)
        self.assertEqual(result['book_imbalance'], 97 / 299)

    def test_futures_fallback_reads_overlap_after_partial_primary_failure(self):
        barrier = Barrier(2, timeout=1)
        def read(url, params):
            if url.startswith(learner.FUTURES):
                if url.endswith('premiumIndex'):
                    return {'lastFundingRate': '.0001'}
                raise OSError('primary offline')
            barrier.wait()
            if url.endswith('tickers'):
                return {'result': {'list': [{'fundingRate': '.0002', 'openInterest': '30', 'markPrice': '100'}]}}
            return {'result': {'b': [['99', '2']], 'a': [['101', '1']]}}
        with patch.object(learner, 'get', side_effect=read):
            result = learner.futures_snapshot()
        self.assertTrue(result['ok'])
        self.assertEqual(result['funding_rate'], .0002)
        self.assertEqual(result['open_interest'], 30)

    def test_failed_optional_futures_feeds_preserve_partial_values(self):
        def read(url, params):
            if url.endswith('premiumIndex'):
                return {'lastFundingRate': '.0001'}
            raise OSError('offline')
        with patch.object(learner, 'get', side_effect=read):
            result = learner.futures_snapshot()
        self.assertFalse(result['ok'])
        self.assertEqual(result['funding_rate'], .0001)
        self.assertEqual(result['source'], 'Unavailable')

    def test_shadow_specialist_feeds_overlap(self):
        barrier = Barrier(2, timeout=1)
        def read():
            barrier.wait()
            return {}
        with ExitStack() as stack:
            fixtures.ReliabilityTests().shadow_dependencies(stack)
            stack.enter_context(patch.object(learner, 'aggregate_trades', side_effect=read))
            stack.enter_context(patch.object(learner, 'futures_snapshot', side_effect=read))
            stack.enter_context(patch.object(worker.time, 'time', return_value=1000))
            call = worker.current_shadow_call({}, pd.DataFrame({'close': [100.]}),
                                             {'ticker': 'TEST', 'expires_at': 1700, 'target': 100.})
        self.assertEqual(call['ticker'], 'TEST')

    def test_registration_specialist_feeds_overlap(self):
        barrier = Barrier(2, timeout=1)
        def read():
            barrier.wait()
            return {}
        with patch.object(learner, 'aggregate_trades', side_effect=read), \
             patch.object(learner, 'futures_snapshot', side_effect=read), \
             patch.object(learner, 'run_specialists_core', return_value={}), \
             patch.object(learner, 'kalshi_context', return_value={}), \
             patch.object(learner, 'rows_for_forecast', return_value=[]), \
             patch.object(learner, 'forecast_path_core', return_value=None), \
             patch.object(learner.time, 'time', return_value=1000):
            self.assertFalse(learner.register({'forecast': {}}, pd.DataFrame({'close': [100.]}),
                                              {'expires_at': 1700, 'target': 100.}))

    def test_initial_worker_feeds_overlap(self):
        # Execute the real startup through the first state-dependent learning
        # stage; all later grading/publication remains outside this I/O check.
        main = next(n for n in ast.parse(Path('learner_v31.py').read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'main')
        prefix = []
        for node in main.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'horizon_root' for t in node.targets):
                break
            prefix.append(node)
        barrier = Barrier(3, timeout=1)
        def read():
            barrier.wait()
            return {}
        ns = dict(vars(worker), load_previous_state=lambda: {}, ensure_v31=lambda _: {'status': {}})
        with patch.object(learner, 'history', side_effect=read), \
             patch.object(learner, 'market', side_effect=read), \
             patch.object(learner, 'market_timeframe_context', side_effect=read):
            exec(compile(ast.Module(body=prefix, type_ignores=[]), 'learner_v31.py', 'exec'), ns)
        self.assertEqual(ns['df'], {})

