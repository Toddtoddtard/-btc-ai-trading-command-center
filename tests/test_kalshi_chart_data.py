import copy
import json
from pathlib import Path
import re
import subprocess
import unittest

from kalshi_chart_data import event_ticker, fetch_chart, parse_chart

NOW = 1791719894
EVENT = 'KXBTC15M-26OCT110800'


def fixture():
    return {'live_data': {'type': 'crypto', 'is_historical': False, 'details': {
        'coin': 'BTC', 'event_ticker': EVENT, 'maturity_ts_ms': 1791720000000,
        'timeseries': [{'t': NOW*1000, 'v': 83104}],
        'candlesticks': {'1M': [{'open_ts_ms': 1791719880000, 'open': 83100,
                               'high': 83105, 'low': 83099, 'close': 83104}]}}}}


class ChartDataTests(unittest.TestCase):
    def test_uses_kalshi_price_and_candles(self):
        result = fetch_chart(EVENT+'-00', lambda url: fixture(), now=NOW)
        self.assertEqual(result['price'], 83104)
        self.assertEqual(result['candles'][0]['close'], 83104)
        self.assertEqual(event_ticker(EVENT), EVENT)
        self.assertEqual(event_ticker('BTCUSDT'), '')

    def test_rejects_wrong_event_historical_stale_and_expired(self):
        for mutation in ('event', 'history', 'stale', 'future', 'expired', 'coin'):
            p = fixture(); d=p['live_data']['details']
            if mutation=='event': d['event_ticker']='OTHER'
            if mutation=='history': p['live_data']['is_historical']=True
            if mutation=='stale': d['timeseries'][0]['t']-=31000
            if mutation=='future': d['timeseries'][0]['t']+=6000
            if mutation=='expired': d['maturity_ts_ms']=NOW*1000
            if mutation=='coin': d['coin']='ETH'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_chart(p, EVENT, NOW)

    def test_failure_does_not_substitute_an_exchange(self):
        urls=[]
        def fail(url):
            urls.append(url)
            raise TimeoutError('unavailable')
        result=fetch_chart(EVENT,fail,now=NOW)
        self.assertFalse(result['available'])
        self.assertNotIn('price',result)
        self.assertTrue(all('/live_data/events/'+EVENT in url for url in urls))

    def test_browser_parser_uses_same_prices_and_rejects_stale(self):
        source=Path('app.py').read_text()
        match=re.search(r'        function parseKalshiCandles\(.*?\n        \}\}',source,re.S)
        fn=match.group().replace('{{','{').replace('}}','}')
        script='const assert=require("assert");let lastChartPrice=NaN,lastChartTimestamp=0;\n'+fn
        script+='\nconst payload='+json.dumps(fixture())+';\n'
        script+=f'''const now={NOW}*1000,event={json.dumps(EVENT)};
assert.equal(parseKalshiCandles(payload,event,now)[0].close,83104);
assert.equal(lastChartPrice,83104);
assert.equal(parseKalshiCandles(payload,event,now+31000),null);
assert.equal(parseKalshiCandles(payload,'OTHER',now),null);
payload.live_data.is_historical=true;
assert.equal(parseKalshiCandles(payload,event,now),null);
'''
        result=subprocess.run(['node','-e',script],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        chart=source[source.index('def persistent_kalshi_market_chart'):source.index('# DASHBOARD THEME')]
        self.assertNotIn('api.binance.com',chart)
        self.assertNotIn('data-api.binance.vision',chart)

    def test_rendered_chart_javascript_compiles(self):
        import ast
        from types import SimpleNamespace
        import pandas as pd
        source=Path('app.py').read_text()
        fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='persistent_kalshi_market_chart')
        output=[]
        namespace={'pd':pd,'json':json,'get_learning_state':lambda:{},
                   'components':SimpleNamespace(html=lambda html,**kwargs:output.append(html))}
        encoder=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='chart_json')
        exec(compile(ast.Module(body=[encoder,fn],type_ignores=[]),'chart','exec'),namespace)
        rows=pd.DataFrame(parse_chart(fixture(),EVENT,NOW)['candles'])
        namespace['persistent_kalshi_market_chart'](rows,83100,EVENT+'-00',initial_close='2026-10-11T12:00:00Z')
        script=re.findall(r'<script>(.*?)</script>',output[0],re.S)[0]
        result=subprocess.run(['node','--check'],input=script,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(r'/^(KXBTC15M-\d{2}[A-Z]{3}\d{6})(?:-\d+)?$/',script)
