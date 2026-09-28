"""Exercise the actual dashboard fetch function without launching Streamlit."""
import ast
from pathlib import Path
from threading import Barrier

import numpy as np
import time
import unittest

from ai_core import safe_float
from live_feeds import parallel_calls
from public_futures import parse_bybit_futures_snapshot


def dashboard_fetch(request):
    tree = ast.parse(Path('app.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fetch_futures_snapshot')
    function.decorator_list = []
    namespace = dict(np=np, time=time, safe_float=safe_float,
                     parallel_calls=parallel_calls, try_bases=request,
                     parse_bybit_futures_snapshot=parse_bybit_futures_snapshot,
                     FUTURES_BASES=['binance'], BYBIT_BASES=['bybit'], SYMBOL='BTCUSDT')
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace['fetch_futures_snapshot']()


class FuturesLatencyTests(unittest.TestCase):
    def test_dashboard_primary_requests_overlap_and_preserve_values(self):
        barrier = Barrier(3, timeout=2)

        def request(bases, endpoint, params, timeout):
            assert bases == ['binance'] and timeout == 2.2
            barrier.wait()
            payload = {
                '/fapi/v1/premiumIndex': {'lastFundingRate': '0.0001', 'markPrice': '100'},
                '/fapi/v1/openInterest': {'openInterest': '20'},
                '/fapi/v1/depth': {'bids': [['99', '2']], 'asks': [['101', '1']]},
            }[endpoint]
            return payload, 1.0

        snapshot = dashboard_fetch(request)
        assert snapshot['ok']
        assert snapshot['mark_price'] == 100
        assert snapshot['funding_rate'] == 0.0001
        assert snapshot['open_interest'] == 20
        assert snapshot['book_imbalance'] == 97 / 299


    def test_dashboard_fallback_requests_overlap_after_primary_failure(self):
        barrier = Barrier(2, timeout=2)

        def request(bases, endpoint, params, timeout):
            if bases == ['binance']:
                raise OSError('primary unavailable')
            barrier.wait()
            if endpoint.endswith('tickers'):
                return {'result': {'list': [{'fundingRate': '0.0002', 'markPrice': '100', 'openInterest': '30'}]}}, 1.0
            return {'result': {'b': [['99', '2']], 'a': [['101', '1']]}}, 1.0

        snapshot = dashboard_fetch(request)
        assert snapshot['ok'] and snapshot['source'].startswith('Bybit')
        assert snapshot['open_interest'] == 30
        assert 'error' not in snapshot


    def test_dashboard_all_failures_remain_unavailable(self):
        def request(*args, **kwargs):
            raise OSError('offline')
        snapshot = dashboard_fetch(request)
        assert not snapshot['ok']
        assert np.isnan(snapshot['mark_price'])
        assert 'offline' in snapshot['error']
        assert 'offline' in snapshot['fallback_error']
