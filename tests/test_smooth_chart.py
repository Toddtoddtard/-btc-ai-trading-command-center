"""Execute the chart's real message handler and repeated tick updates."""
import ast
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import unittest

import pandas as pd


class SmoothChartTests(unittest.TestCase):
    def test_server_ticks_update_one_chart_and_reject_untrusted_or_expired_data(self):
        fn = next(n for n in ast.parse(Path('app.py').read_text()).body
                  if isinstance(n, ast.FunctionDef) and n.name == 'persistent_kalshi_market_chart')
        frames = []
        ns = dict(pd=pd, json=json, get_learning_state=lambda: {},
                  components=SimpleNamespace(html=lambda html, **kwargs: frames.append(html)))
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'chart', 'exec'), ns)
        ns[fn.name](pd.DataFrame(), 83000, 'KXBTC15M-26OCT141215-15',
                    initial_close='2026-10-14T12:15:00Z')
        script = re.findall(r'<script>(.*?)</script>', frames[0], re.S)[0]
        harness = """
const assert=require('assert');
let now=Date.parse('2026-10-14T12:01:10Z');Date.now=()=>now;
const chart={},status={},handlers={},sender={};let mounts=0,updates=0;
global.document={getElementById:id=>id==='persistent-market-chart'?chart:status,
 querySelectorAll:()=>[]};
global.window={location:{origin:'null'},parent:{location:{origin:'https://app.test'},
 document:{querySelectorAll:()=>[{contentWindow:sender}]}},
 addEventListener:(name,fn)=>handlers[name]=fn};
global.Plotly={newPlot:()=>{mounts++;return Promise.resolve()},
 react:(node,data)=>{assert.strictEqual(node,chart);chart.data=data;updates++;return Promise.resolve()},
 relayout:()=>Promise.resolve()};
global.setInterval=()=>0;global.setTimeout=()=>0;
global.fetch=()=>{throw Error('server ticks should not need browser network')};
"""
        checks = """
(async()=>{
 const packet={type:'btc-live-chart',available:true,ticker:'KXBTC15M-26OCT141215-15',
 target:83000,close_time:'2026-10-14T12:15:00Z',timestamp:now/1000-5,price:83104,
 candles:[{time:'2026-10-14T12:01:00Z',open:83100,high:83102,low:83099,close:83101}]};
 const send=async(data,origin='https://app.test')=>{handlers.message({data:structuredClone(data),origin,source:sender});
 await new Promise(resolve=>setImmediate(resolve));};
 await send(packet);assert.equal(chart.data[0].close.at(-1),83104);
 now+=1000;await send({...packet,price:83108,timestamp:now/1000});
 assert.equal(chart.data[0].close.at(-1),83108);assert.equal(mounts,1);
 now+=1000;await send({...packet,price:83095,timestamp:now/1000});
 assert.equal(chart.data[0].high.at(-1),83108);
 assert.equal(chart.data[0].low.at(-1),83095);
 now+=1000;await send({...packet,price:83101,timestamp:now/1000});
 assert.equal(chart.data[0].high.at(-1),83108);
 assert.equal(chart.data[0].low.at(-1),83095);assert.equal(updates,4);
 await send({...packet,price:99999,timestamp:now/1000},'https://other.test');
 await send({...packet,price:99999,timestamp:now/1000,close_time:'2026-10-14T12:00:00Z'});
 assert.equal(chart.data[0].close.at(-1),83101);assert.equal(updates,4);
})().catch(e=>{console.error(e);process.exit(1)});
"""
        result = subprocess.run(['node', '-e', harness + script + checks],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
