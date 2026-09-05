from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

css = '''
    .confidence-metric-card {
        width:100%;
        min-height:92px;
        box-sizing:border-box;
        padding:.72rem 1rem;
        border-radius:13px;
        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
        border:1px solid #1687ff;
        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        justify-content:flex-start;
        gap:.36rem;
    }
    .confidence-metric-label {
        color:#9fb2ce;
        font-size:.90rem;
        line-height:1.15;
        font-weight:500;
        white-space:nowrap;
    }
    .confidence-metric-label span {
        margin-left:.28rem;
        font-size:.72rem;
        font-weight:800;
    }
    .confidence-metric-value {
        color:#f4f8ff;
        font-size:1.55rem;
        line-height:1.35;
        font-weight:750;
    }
'''

if '.confidence-metric-card {' not in s:
    anchor = '''    .direction-card.metric-direction-card .direction-call {
        min-width:min(150px, 100%);
        max-width:100%;
        box-sizing:border-box;
    }
'''
    if anchor not in s:
        raise SystemExit('CSS anchor not found')
    s = s.replace(anchor, anchor + css, 1)
else:
    print('Confidence card CSS already present')

p.write_text(s, encoding='utf-8')
print('Confidence card border/background CSS installed')
