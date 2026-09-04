from pathlib import Path

p = Path('app.py')
s = p.read_text()

anchor = 'st.sidebar.header("Command Center")\n'
if anchor not in s:
    raise SystemExit('sidebar Command Center anchor not found')

if 'Kalshi 15m Timer' in s and 'kalshi-sidebar-timer' in s:
    print('Kalshi sidebar timer already present')
else:
    timer = r'''# Persistent browser-side Kalshi 15-minute countdown.
# It polls Kalshi directly and ticks locally every second so the timer stays smooth
# even when the Streamlit dashboard itself is not rerunning.
_kalshi_timer_html = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html,body{margin:0;padding:0;background:transparent;color:#f5f9ff;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
  .kalshi-sidebar-timer{box-sizing:border-box;width:100%;border:1.5px solid #1687ff;border-radius:14px;padding:14px 14px 12px;background:linear-gradient(180deg,rgba(7,26,48,.98),rgba(5,20,37,.98));box-shadow:0 10px 26px rgba(0,0,0,.22),0 0 0 1px rgba(22,135,255,.10) inset;}
  .timer-title{font-size:18px;font-weight:800;letter-spacing:.01em;margin:0 0 10px 0;}
  .timer-main{display:flex;align-items:center;gap:12px;}
  .clock{width:46px;height:46px;border:6px solid #1687ff;border-radius:50%;position:relative;box-sizing:border-box;box-shadow:0 0 18px rgba(22,135,255,.28);flex:0 0 auto;}
  .clock:before{content:"";position:absolute;left:18px;top:8px;width:4px;height:15px;background:#1687ff;border-radius:3px;transform-origin:bottom center;}
  .clock:after{content:"";position:absolute;left:18px;top:20px;width:13px;height:4px;background:#1687ff;border-radius:3px;transform:rotate(35deg);transform-origin:left center;}
  .countdown{font-size:42px;line-height:1;font-weight:850;letter-spacing:.02em;font-variant-numeric:tabular-nums;}
  .track{height:12px;border-radius:999px;background:#24496d;margin-top:13px;overflow:hidden;}
  .fill{height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,#087cff,#18a7ff);transition:width .35s linear;box-shadow:0 0 12px rgba(22,135,255,.35);}
  .meta{display:flex;justify-content:space-between;margin-top:9px;font-size:13px;color:#b9d3ef;font-variant-numeric:tabular-nums;}
  .status{margin-top:7px;font-size:11px;color:#6f8ba8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
</style>
</head>
<body>
<div class="kalshi-sidebar-timer">
  <div class="timer-title">Kalshi 15m Timer</div>
  <div class="timer-main"><div class="clock"></div><div id="countdown" class="countdown">--:--</div></div>
  <div class="track"><div id="fill" class="fill"></div></div>
  <div class="meta"><span id="elapsed">--:-- elapsed</span><span>15:00 total</span></div>
  <div id="status" class="status">Finding current KXBTC15M market…</div>
</div>
<script>
(() => {
  const API='https://external-api.kalshi.com/trade-api/v2';
  const TOTAL=15*60;
  let closeMs=null, ticker='';
  const cd=document.getElementById('countdown');
  const fill=document.getElementById('fill');
  const elapsedEl=document.getElementById('elapsed');
  const status=document.getElementById('status');
  const fmt=(sec)=>{sec=Math.max(0,Math.floor(sec));const m=Math.floor(sec/60),s=sec%60;return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');};
  function render(){
    if(!closeMs){cd.textContent='--:--';fill.style.width='0%';elapsedEl.textContent='--:-- elapsed';return;}
    const remain=Math.max(0,(closeMs-Date.now())/1000);
    const elapsed=Math.max(0,Math.min(TOTAL,TOTAL-remain));
    cd.textContent=fmt(remain);
    elapsedEl.textContent=fmt(elapsed)+' elapsed';
    fill.style.width=(Math.max(0,Math.min(1,elapsed/TOTAL))*100).toFixed(2)+'%';
    if(remain<=0){ status.textContent='Market ended — loading next 15m market…'; }
  }
  function closeTime(m){const raw=m?.close_time||m?.expiration_time||m?.expected_expiration_time;const t=Date.parse(raw||'');return Number.isFinite(t)?t:null;}
  async function refreshMarket(){
    try{
      const r=await fetch(API+'/markets?limit=100&status=open&series_ticker=KXBTC15M',{cache:'no-store'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const j=await r.json();
      const now=Date.now();
      const rows=(j.markets||[]).map(m=>({m,t:closeTime(m)})).filter(x=>x.t&&x.t>now).sort((a,b)=>a.t-b.t||String(a.m.ticker||'').localeCompare(String(b.m.ticker||'')));
      if(!rows.length){closeMs=null;ticker='';status.textContent='No open KXBTC15M market found';render();return;}
      ticker=String(rows[0].m.ticker||'');
      closeMs=rows[0].t;
      status.textContent=ticker;
      render();
    }catch(e){status.textContent='Kalshi timer reconnecting…';}
  }
  render(); refreshMarket();
  setInterval(render,250);
  setInterval(refreshMarket,5000);
})();
</script>
</body>
</html>
"""
with st.sidebar:
    components.html(_kalshi_timer_html, height=205, scrolling=False)

'''
    s = s.replace(anchor, timer + anchor, 1)

s = s.replace('APP_VERSION = "2026.09.04-single-file-r29-audit-fixed"', 'APP_VERSION = "2026.09.04-r30-kalshi-sidebar-timer"')
compile(s, 'app.py', 'exec')
p.write_text(s)
print('R30 Kalshi sidebar timer applied.')
