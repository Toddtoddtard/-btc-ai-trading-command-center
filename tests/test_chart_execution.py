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
const rows = Array.from({length:30}, (_,i)=>({time:new Date(1700000000000+i*60000).toISOString(),open:100+i,close:101+i,high:102+i,low:99+i}));
console.log(JSON.stringify([1,5,15,1,5].map(h=>({h,c:predictionTrace(rows,h).x.length,p:predictionPathTrace(rows,h).x.length,label:predictionTrace(rows,h).name}))));
'''
        result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
        for item in json.loads(result.stdout):
            self.assertEqual(item['c'], item['h'])
            self.assertEqual(item['p'], item['h'])
            self.assertEqual(item['label'], 'Predicted '+str(item['h'])+'m candles')
        self.assertNotIn('predictionTrace(rows),', source)
