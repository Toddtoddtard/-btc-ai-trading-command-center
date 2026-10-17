"""Execute actual browser path handling, including rollover and provenance."""
import re
import subprocess
import unittest
from pathlib import Path


class ChartCurveIntegrationTests(unittest.TestCase):
    def test_server_curve_has_real_turns_crosses_rollover_and_ignores_target(self):
        source=Path('app.py').read_text()
        function=re.search(r'        function predictedCandles\(.*?\n        \}\}',source,re.S).group().replace('{{','{').replace('}}','}')
        script='''
const assert=require('assert');
let now=Date.parse('2026-10-17T18:13:20Z');Date.now=()=>now;
let currentTarget=99999;
const W_RET3=.46,W_RET8=.34,W_RET15=.2,MODEL_BIAS=0,MOMENTUM_SCALE=2.2,TARGET_INFLUENCE=.18;
let SERVER_CURVE={source:'Kalshi BTC/USD chart feed',as_of:Date.parse('2026-10-17T18:13:00Z')/1000,
method:'validated_curve',anchor:83000,points:Array.from({length:15},(_,i)=>({timestamp:Date.parse('2026-10-17T18:13:00Z')/1000+(i+1)*60,close:83000+(i<5?i*3:30-i*3),lower:82950,upper:83050}))};
const rows=Array.from({length:30},(_,i)=>({time:new Date(Date.parse('2026-10-17T18:13:00Z')-(29-i)*60000).toISOString(),open:83000,close:83000,high:83001,low:82999}));
''' + function + '''
const p=predictedCandles(rows,15);
assert.equal(p.length,15);assert.equal(p.at(-1).time,'2026-10-17T18:28:00.000Z');
assert.deepEqual(p.map(p=>p.close),SERVER_CURVE.points.map(p=>p.close));
currentTarget=1000;assert.deepEqual(predictedCandles(rows,15),p);
assert.equal(predictedCandles(rows,1).length,1);assert.equal(predictedCandles(rows,5).length,5);
SERVER_CURVE.source='Binance';assert.equal(predictedCandles(rows,15).length,0);
SERVER_CURVE.source='Kalshi BTC/USD chart feed';now+=121000;assert.equal(predictedCandles(rows,15).length,0);
'''
        result=subprocess.run(['node'],input=script,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
