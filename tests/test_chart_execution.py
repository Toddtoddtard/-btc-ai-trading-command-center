"""Execute the installed chart functions, not installer string assertions."""
import json
from pathlib import Path
import re
import subprocess
import unittest

class ChartExecutionTests(unittest.TestCase):
    def test_selected_horizons_execute(self):
        source = Path('app.py').read_text()
        functions = []
        for name in ('predictedCandles', 'predictionTrace', 'predictionPathTrace'):
            match = re.search(r'        function ' + name + r'\(.*?\n        \}\}', source, re.S)
            self.assertIsNotNone(match, name)
            functions.append(match.group().replace('{{', '{').replace('}}', '}'))
        script = '''
const W_RET3=.46,W_RET8=.34,W_RET15=.20,MODEL_BIAS=0,MOMENTUM_SCALE=2.2,TARGET_INFLUENCE=.18,currentTarget=NaN;
''' + '\n'.join(functions) + '''
Date.now=()=>1800000;
const rows = Array.from({length:30}, (_,i)=>({time:new Date(60000+i*60000).toISOString(),open:100+i,close:101+i,high:102+i,low:99+i}));
const SERVER_CURVE={source:'Kalshi BTC/USD chart feed',as_of:Date.now()/1000,anchor:130,points:Array.from({length:15},(_,i)=>({timestamp:Date.now()/1000+(i+1)*60,close:130+i,lower:129+i,upper:131+i}))};
console.log(JSON.stringify([1,5,15,1,5].map(h=>({h,c:predictionTrace(rows,h).x.length,p:predictionPathTrace(rows,h).x.length,label:predictionTrace(rows,h).name}))));
'''
        result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
        for item in json.loads(result.stdout):
            self.assertEqual(item['c'], item['h'])
            self.assertEqual(item['p'], item['h'])
            self.assertEqual(item['label'], 'Projected price ranges (estimate)')
        self.assertNotIn('predictionTrace(rows),', source)

    def test_forecast_crosses_close_and_hides_stale_paths(self):
        source = Path('app.py').read_text()
        match = re.search(r'        function predictedCandles\(.*?\n        \}\}', source, re.S)
        function = match.group().replace('{{', '{').replace('}}', '}')
        script = """
const assert = require('assert');
const W_RET3=.46,W_RET8=.34,W_RET15=.20,MODEL_BIAS=0,MOMENTUM_SCALE=2.2,TARGET_INFLUENCE=.18,currentTarget=NaN;
let now=Date.parse('2026-10-10T21:54:19Z'); Date.now=()=>now;
const last=Date.parse('2026-10-10T21:54:00Z');
const rows=Array.from({length:30},(_,i)=>({time:new Date(last-(29-i)*60000).toISOString(),open:83000+i,close:83001+i,high:83003+i,low:82998+i}));
""" + function + """
const SERVER_CURVE={source:'Kalshi BTC/USD chart feed',as_of:last/1000,anchor:83030,points:Array.from({length:15},(_,i)=>({timestamp:last/1000+(i+1)*60,close:83030+i,lower:83029+i,upper:83031+i}))};
const path=predictedCandles(rows,15);
assert.equal(path.length,15);
assert.equal(path.at(-1).time,'2026-10-10T22:09:00.000Z');
assert.equal(predictedCandles(rows,1).length,1);
assert.equal(predictedCandles(rows,5).length,5);
now=Date.parse('2026-10-10T21:56:01Z');
assert.equal(predictedCandles(rows,15).length,0);
now=Date.parse('2026-10-10T22:00:01Z');
assert.equal(predictedCandles(rows,15).length,0);
"""
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
