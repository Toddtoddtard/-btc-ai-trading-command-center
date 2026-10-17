import ast
import copy
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest
from threading import Barrier
import pandas as pd
import live_feeds


class DashboardPerformanceTests(unittest.TestCase):
    def test_missing_horizon_probability_stays_missing_in_browser_packet(self):
        fn = next(n for n in ast.parse(Path('app.py').read_text()).body
                  if isinstance(n, ast.FunctionDef) and n.name == 'chart_json')
        ns = {'json': json}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'chart-json', 'exec'), ns)
        packet = json.loads(ns['chart_json']({'learning': {'horizon_models': {
            'models': {'1': {'enabled': True}}, 'last_prediction': {'1': {}}
        }}}))
        self.assertNotIn('probability_up', packet['learning']['horizon_models']['last_prediction']['1'])

    def test_chart_payload_omits_training_history_without_changing_forecast_candles(self):
        source = Path('app.py').read_text()
        tree = ast.parse(source)
        encoder = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'chart_json')
        ns = {'json': json}
        exec(compile(ast.Module(body=[encoder], type_ignores=[]), 'chart-json', 'exec'), ns)
        learning = dict(w_ret3=.46, w_ret8=.34, w_ret15=.2, momentum_scale=2.2,
                        target_influence=.18, bias=.001, horizon_models={
                            'models': {str(h): {'enabled': True, 'weights': [1]*21, 'recent': ['x'*1000]*100}
                                       for h in (1, 5, 15)},
                            'last_prediction': {str(h): {'probability_up': .65} for h in (1, 5, 15)},
                            'candle_learning': {'history': ['x'*1000]*100}})
        original = copy.deepcopy(learning)
        payload = ns['chart_json']({'learning': learning})
        self.assertLess(len(payload), 1000)
        self.assertEqual(learning, original)
        function = re.search(r'^        function predictedCandles\(.*?^        \}\}', source, re.S|re.M).group()
        function = function.replace('{{', '{').replace('}}', '}')
        script = '''
const assert=require('assert');
Date.now=()=>Date.parse('2026-10-14T12:01:10Z');
let W_RET3=.46,W_RET8=.34,W_RET15=.2,MOMENTUM_SCALE=2.2,TARGET_INFLUENCE=.18,MODEL_BIAS=.001,currentTarget=83000;
let HORIZON_MODELS={};
const SERVER_CURVE={source:'Kalshi BTC/USD chart feed',as_of:Date.now()/1000,anchor:83000,points:Array.from({length:15},(_,i)=>({timestamp:Date.now()/1000+(i+1)*60,close:83000+i,lower:82999+i,upper:83001+i}))};
const rows=Array.from({length:30},(_,i)=>({time:new Date(Date.now()-(29-i)*60000).toISOString(),open:83000+i,high:83010+i,low:82990+i,close:83002+i}));
''' + function + '\nconst original='+json.dumps(original)+';\nconst compact='+payload+''';
for(const h of [1,5,15]){
 HORIZON_MODELS=original.horizon_models;const before=predictedCandles(rows,h);
 HORIZON_MODELS=compact.learning.horizon_models;const after=predictedCandles(rows,h);
 assert.ok(before.length>0);assert.deepStrictEqual(after,before);
}
'''
        result = subprocess.run(['node'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_chart_startup_loads_only_history_and_contract_concurrently(self):
        barrier = Barrier(2, timeout=1)
        def history(interval, limit):
            barrier.wait()
            return pd.DataFrame({'close': [83000.]}), 0
        def market():
            barrier.wait()
            return {'current': {'ticker': 'CURRENT'}}
        result = live_feeds.load_chart_startup(history, market, lambda frame: frame)
        self.assertEqual(result['history']['close'].iloc[0], 83000)
        self.assertEqual(result['kalshi']['current']['ticker'], 'CURRENT')

    def test_failed_startup_feed_does_not_hide_the_other_feed(self):
        def fail(*args): raise OSError('offline')
        result = live_feeds.load_chart_startup(fail, lambda: {'ok': True}, lambda frame: frame)
        self.assertTrue(result['history'].empty)
        self.assertEqual(result['kalshi'], {'ok': True})

    def test_only_selected_tab_body_executes(self):
        tree = ast.parse(Path('app.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'live_dashboard')
        names = {'tab_market', 'tab_ai', 'tab_hourly', 'tab_flow', 'tab_paper',
                 'tab_journal', 'tab_learning', 'tab_backtest'}
        # Keep the actual selection/control flow; replace expensive panel bodies
        # with probes so this check needs neither feeds nor a Streamlit server.
        class Probe(ast.NodeTransformer):
            def visit_With(self, node):
                if isinstance(node.items[0].context_expr, ast.Name):
                    name = node.items[0].context_expr.id
                    if name in names:
                        node.body = ast.parse(f'visited.append("{name}")').body
                        return node
                return self.generic_visit(node)
        statements = []
        for node in function.body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == 'tabs'):
                statements.append(node)
            elif any(isinstance(n, ast.With) and isinstance(n.items[0].context_expr, ast.Name)
                     and n.items[0].context_expr.id in names for n in ast.walk(node)):
                statements.append(Probe().visit(node))
        class Tab:
            def __init__(self, opened): self.open = opened
            def __enter__(self): return self
            def __exit__(self, *args): return False
        for selected in names:
            visited = []
            def tabs(labels, **kwargs):
                self.assertEqual(kwargs.get('on_change'), 'rerun')
                return [Tab(name == selected) for name in
                        ('tab_market', 'tab_ai', 'tab_hourly', 'tab_flow', 'tab_paper',
                         'tab_journal', 'tab_learning', 'tab_backtest')]
            code = ast.fix_missing_locations(ast.Module(body=statements, type_ignores=[]))
            exec(compile(code, 'dashboard-tabs', 'exec'), dict(st=SimpleNamespace(tabs=tabs), visited=visited))
            self.assertEqual(visited, [selected])
