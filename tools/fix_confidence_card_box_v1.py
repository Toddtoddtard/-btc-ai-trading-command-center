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
        gap:.32rem;
    }
    .confidence-metric-label {
        color:#9fb2ce;
        font-size:.90rem;
        line-height:1.15;
        font-weight:500;
        white-space:nowrap;
    }
    .confidence-metric-label span {
        font-size:.72rem;
        font-weight:800;
        margin-left:.28rem;
    }
    .confidence-metric-value {
        color:#eef3fa;
        font-size:1.55rem;
        line-height:1.4;
        font-weight:750;
    }
'''

if '.confidence-metric-card {' in s:
    print('Confidence card box CSS already present')
    raise SystemExit(0)

anchor = '    .direction-card {\n'
if anchor not in s:
    raise SystemExit('direction-card CSS anchor not found')

s = s.replace(anchor, css + '\n' + anchor, 1)
p.write_text(s, encoding='utf-8')
print('Restored Confidence card box styling')
