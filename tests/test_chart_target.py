"""Execute chart target selection with delayed and incomplete API responses."""
import re
import subprocess
import unittest
from pathlib import Path


class ChartTargetTests(unittest.TestCase):
    def test_current_contract_selection_and_rollover_race(self):
        source = Path('app.py').read_text()
        functions = []
        for name in ('parseTime', 'numericKalshiTarget', 'fetchKalshiTarget', 'updateTarget'):
            match = re.search(r'^        (?:async )?function ' + name + r'\(.*?^        \}\}', source, re.S | re.M)
            self.assertIsNotNone(match, name)
            functions.append(match.group().replace('{{', '{').replace('}}', '}').replace('\\\\', '\\'))
        script = '''
const assert=require('assert');
let now=1800000+60000; Date.now=()=>now;
let currentTicker='',currentTarget=NaN,kalshiWindowKey=2,targetRequest=0,targetBusy=false,entryMarkers=[];
const chart={},status={},Plotly={relayout:async()=>{}};
const targetShape=()=>[],targetAnnotation=()=>[];
let markets=[],exact=null;
let fetchKalshiJson=async()=>({markets});
let exactKalshiMarket=async()=>exact;
const market=(ticker,close,target)=>({ticker,close_time:new Date(close).toISOString(),floor_strike:target});
''' + '\n'.join(functions) + '''
(async()=>{
  // A current list row without a strike must still reach exact-market lookup.
  markets=[market('CURRENT',2700000,null),market('FUTURE',3600000,999)];
  exact=market('CURRENT',2700000,81000);
  assert.equal((await fetchKalshiTarget()).target,81000);
  markets=[market('FUTURE',3600000,999)];
  assert.equal(await fetchKalshiTarget(),null);
  markets=[market('CURRENT',2700000,null)]; exact=null;
  assert.equal(await fetchKalshiTarget(),null);
  exact=market('CURRENT',2700000,81000);
  await updateTarget(); assert.equal(currentTarget,81000);
  // An old in-flight reply must not restore the line after the window changes.
  let release;
  fetchKalshiTarget=()=>new Promise(r=>{release=r});
  const pending=updateTarget();
  now=2700001;
  await updateTarget(); assert.ok(Number.isNaN(currentTarget));
  release({ticker:'CURRENT',target:81000,closeMs:2700000});
  await pending; assert.ok(Number.isNaN(currentTarget));
  assert.equal(targetBusy,false);
})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
