from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')

old = '''    .confidence-metric-card {
        min-height:92px;
        box-sizing:border-box;
        padding:.45rem .6rem;
    }
'''
new = '''    .confidence-metric-card {
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
'''

if old not in s:
    if 'border:1px solid #1687ff;' in s and '.confidence-metric-card {' in s:
        print('Confidence card full border styling already present')
        raise SystemExit(0)
    raise SystemExit('Expected confidence card CSS block not found')

s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('Replaced confidence card CSS with full bordered card styling')
