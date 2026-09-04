from pathlib import Path

p = Path('app.py')
s = p.read_text()

old = '''# Persistent browser-side Kalshi 15-minute countdown.\n# It polls Kalshi directly and ticks locally every second so the timer stays smooth\n# even when the Streamlit dashboard itself is not rerunning.\n_kalshi_timer_html = r\"\"\"'''
new = '''# Persistent Kalshi 15-minute countdown.\n# Seed the timer from Streamlit's server-side Kalshi request (avoids browser CORS issues),\n# then tick locally in the browser for smooth second-by-second updates.\n_timer_close_ms = 0\n_timer_ticker = \"\"\ntry:\n    _timer_payload = fetch_kalshi_bitcoin_markets()\n    _timer_market = (_timer_payload or {}).get(\"current\") or {}\n    _timer_close_ts = kalshi_close_timestamp(_timer_market)\n    if pd.notna(_timer_close_ts):\n        _timer_close_ms = int(float(_timer_close_ts) * 1000)\n    _timer_ticker = str(_timer_market.get(\"ticker\") or \"\")\nexcept Exception:\n    pass\n\n_kalshi_timer_html = r\"\"\"'''
if old not in s:
    raise SystemExit('timer header anchor not found')
s = s.replace(old, new, 1)

old_js = "  const API='https://external-api.kalshi.com/trade-api/v2';\n  const TOTAL=15*60;\n  let closeMs=null, ticker='';"
new_js = "  const TOTAL=15*60;\n  let closeMs=Number('__CLOSE_MS__') || null;\n  let ticker='__TICKER__';"
if old_js not in s:
    raise SystemExit('timer JS init anchor not found')
s = s.replace(old_js, new_js, 1)

start = s.find('  function closeTime(m){')
end = s.find('  render(); refreshMarket();', start)
if start < 0 or end < 0:
    raise SystemExit('browser fetch block not found')
replacement = '''  function rollWindowIfNeeded(){\n    if(closeMs && Date.now() >= closeMs){\n      // KXBTC15M markets are sequential 15-minute windows. Continue the timer\n      // immediately while Streamlit refreshes the exact active ticker in the background.\n      const step=15*60*1000;\n      while(Date.now() >= closeMs) closeMs += step;\n      ticker='';\n      status.textContent='Next Kalshi 15m market';\n    }\n  }\n'''
s = s[:start] + replacement + s[end:]
s = s.replace('  render(); refreshMarket();\n  setInterval(render,250);\n  setInterval(refreshMarket,5000);',
              "  status.textContent=ticker || (closeMs ? 'Kalshi 15m market' : 'Waiting for Kalshi market…');\n  render();\n  setInterval(()=>{rollWindowIfNeeded();render();},250);")

needle = '"""\nwith st.sidebar:\n    components.html(_kalshi_timer_html, height=205, scrolling=False)'
repl = '"""\n_kalshi_timer_html = _kalshi_timer_html.replace("__CLOSE_MS__", str(_timer_close_ms)).replace("__TICKER__", _timer_ticker.replace("\\\\", "").replace("\'", ""))\nwith st.sidebar:\n    components.html(_kalshi_timer_html, height=205, scrolling=False)'
if needle not in s:
    raise SystemExit('timer render anchor not found')
s = s.replace(needle, repl, 1)

s = s.replace('APP_VERSION = "2026.09.04-r30-kalshi-sidebar-timer"', 'APP_VERSION = "2026.09.04-r31-kalshi-timer-fixed"')
compile(s, 'app.py', 'exec')
p.write_text(s)
print('R31 Kalshi timer reliability fix applied.')
