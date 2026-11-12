import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import numpy as np
import pandas as pd


def load_function(name, namespace):
    fn = next(n for n in ast.parse(Path('app.py').read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]


class DashboardFreshnessTests(unittest.TestCase):
    def test_live_refresh_sends_data_without_recreating_chart(self):
        frames = []
        ns = dict(stable_kalshi_contract=lambda *a, **kw: {'ticker': 'test', 'target': 83000},
                  fetch_kalshi_bitcoin_markets=lambda: {},
                  fetch_kalshi_chart=lambda ticker: {'available': True, 'price': 83104,
                      'timestamp': 1000, 'candles': []},
                  get_learning_state=lambda: {}, np=np, pd=pd, datetime=datetime,
                  timezone=timezone, dark_mode=True,
                  publish_market_chart_update=lambda context, live, learning: frames.append(live['price']),
                  persistent_kalshi_market_chart=Mock(),
                  time=__import__("time"), st=SimpleNamespace(session_state={}, warning=Mock(), caption=Mock()))
        refresh = load_function('refresh_market_chart', ns)
        refresh(); refresh()
        self.assertEqual(frames, [83104, 83104])
        ns['persistent_kalshi_market_chart'].assert_not_called()

    def test_market_cache_key_rotates_at_the_window_boundary(self):
        from kalshi_chart_data import active_market_close, market_ticker
        boundary = datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc).timestamp()
        clock = Mock(side_effect=[boundary - 1, boundary])
        cached = Mock()
        namespace = dict(time=SimpleNamespace(time=clock), active_market_close=active_market_close,
                         market_ticker=market_ticker, _fetch_kalshi_bitcoin_markets=cached)
        fetch = load_function('fetch_kalshi_bitcoin_markets', namespace)
        fetch()
        fetch()
        self.assertEqual([call.args for call in cached.call_args_list], [
            ('KXBTC15M-26NOV010100EST-00', boundary),
            ('KXBTC15M-26NOV010115EST-15', boundary + 900),
        ])

    def test_chart_refresh_does_not_wait_for_market_depth(self):
        context = Mock(return_value={'ticker': 'test', 'target': 83000})
        ns = dict(stable_kalshi_contract=context, fetch_kalshi_bitcoin_markets=lambda: {},
                  fetch_kalshi_chart=lambda ticker: {'available': False}, np=np)
        load_function('refresh_market_chart', ns)()
        context.assert_called_once()
        self.assertFalse(context.call_args.kwargs['include_orderbook'])

    def test_expired_cached_target_is_unavailable_during_feed_outage(self):
        now = datetime(2026, 10, 11, 19, 30, tzinfo=timezone.utc).timestamp()
        session = {'kalshi_contract_snapshot': {'ticker': 'old', 'target': 83000,
                   'close_time': '2026-10-11T19:15:00Z', 'market': {}}}
        orderbook = Mock(return_value={})
        namespace = dict(st=SimpleNamespace(session_state=session), pd=pd, np=np,
                         time=SimpleNamespace(time=lambda: now),
                         current_kalshi_context=lambda *a: {'available': False},
                         kalshi_probability=lambda *a: .5, fetch_kalshi_orderbook=orderbook)
        result = load_function('stable_kalshi_contract', namespace)({}, 83104)
        self.assertFalse(result['available'])
        self.assertTrue(np.isnan(result['target']))
        self.assertTrue(np.isnan(result['distance']))
        orderbook.assert_not_called()

    def test_summary_reads_new_learning_snapshot_each_refresh(self):
        values = iter([{'samples': 1, 'avg_abs_error': 10, 'avg_path_error': 20},
                       {'samples': 2, 'avg_abs_error': 9, 'avg_path_error': 19}])
        captions = []
        ns = dict(get_learning_state=lambda: next(values), np=np,
                  fetch_remote_learning_state=lambda: {}, render_learning_freshness=lambda s: None,
                  st=SimpleNamespace(caption=captions.append))
        refresh = load_function('refresh_learning_summary', ns)
        refresh(); refresh()
        self.assertIn('1 completed windows', captions[0])
        self.assertIn('2 completed windows', captions[1])
