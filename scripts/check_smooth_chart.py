"""Browser regression for the actual Streamlit chart and live sender."""
import ast
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright
import plotly


source = ast.parse(Path('app.py').read_text())
functions = '\n'.join(ast.unparse(node) for node in source.body
                      if isinstance(node, ast.FunctionDef) and node.name in
                      ('chart_json', 'persistent_kalshi_market_chart', 'publish_market_chart_update'))
demo = '''
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json,time
from datetime import datetime,timezone
st.set_page_config(layout='wide')
started=time.monotonic()
time.time=lambda: 1791979270+time.monotonic()-started
def get_learning_state(): return {}
''' + functions + '''
expiry=(int(time.time()//900)+1)*900
context={'ticker':'KXBTC15M-'+datetime.fromtimestamp(expiry,timezone.utc).strftime('%y%b%d%H%M').upper()+'-00',
 'target':83000,'close_time':datetime.fromtimestamp(expiry,timezone.utc).isoformat()}
persistent_kalshi_market_chart(pd.DataFrame(),83000,context['ticker'],initial_close=context['close_time'])
@st.fragment(run_every=1)
def tick():
 now=time.time();price=83100+int(now)%20
 candles=[{'time':datetime.fromtimestamp((int(now//60)-i)*60,timezone.utc).isoformat(),
 'open':83100,'high':83120,'low':83090,'close':83100} for i in range(29,-1,-1)]
 publish_market_chart_update(context,{'available':True,'price':price,'timestamp':now-5,'candles':candles},
 {'w_ret3':float('nan'), 'horizon_models':{'1':{'score':float('inf')}}})
tick()
'''

with tempfile.TemporaryDirectory() as directory:
    app = Path(directory) / 'demo.py'
    app.write_text(demo)
    process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(app),
                                '--server.port=8502', '--server.headless=true',
                                '--browser.gatherUsageStats=false'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.add_init_script("Date.now=()=>1791979270000+performance.now()")
            page.on('pageerror', lambda error: errors.append(str(error)))
            bundle = Path(plotly.__file__).parent / 'package_data' / 'plotly.min.js'
            page.route('https://cdn.plot.ly/**', lambda route: route.fulfill(
                path=str(bundle), content_type='application/javascript'))
            # Prove server updates still work when mobile browser API access fails.
            page.route('https://*kalshi.com/**', lambda route: route.abort())
            for attempt in range(30):
                try:
                    page.goto('http://127.0.0.1:8502', timeout=2000)
                    break
                except Exception:
                    page.wait_for_timeout(250)
            # Streamlit adds a hidden sender iframe as well; identify by content.
            frame = None
            for attempt in range(60):
                frame = next((f for f in page.frames if f != page.main_frame and
                              f.locator('#persistent-market-chart').count()), None)
                if frame:
                    break
                page.wait_for_timeout(250)
            assert frame is not None, 'Chart did not mount'
            frame.wait_for_function("document.querySelector('#persistent-market-chart')?.data?.[0]?.close?.length>0")
            frame.evaluate("window.retainedGraph=document.querySelector('#persistent-market-chart')")
            frame.locator('button[data-horizon="5"]').click()
            frame.evaluate("Plotly.relayout(retainedGraph, {'xaxis.range':['2026-10-14T11:40:00Z','2026-10-14T12:00:00Z'], 'xaxis.autorange':false})")
            samples = []
            for tick in range(6):
                page.wait_for_timeout(1050)
                samples.append(frame.evaluate("""({same:retainedGraph===document.querySelector('#persistent-market-chart'),
                    price:retainedGraph.data[0].close.at(-1),zoom:retainedGraph.layout.xaxis.range,
                    horizon:document.querySelector('button[data-horizon="5"]').style.background})"""))
            assert all(s['same'] for s in samples), 'Chart node was recreated'
            assert len({s['price'] for s in samples}) >= 4, 'Prices did not update each second'
            assert all(s['zoom'][0] == '2026-10-14T11:40:00Z' for s in samples), 'Zoom reset'
            assert all(s['horizon'] == 'rgb(18, 50, 82)' for s in samples), 'Horizon reset'
            assert not errors, errors
            print('Six live updates passed: same chart node, changing prices, retained zoom and horizon, no page errors.')
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
