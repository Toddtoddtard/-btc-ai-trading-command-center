from pathlib import Path

p = Path("app.py")
text = p.read_text()
old = '    [data-testid="stMetricValue"] {font-size: 1.55rem;}\n'
new = '''    [data-testid="stMetricValue"] {
        font-size: clamp(.88rem, 1.55vw, 1.55rem) !important;
        line-height: 1.15 !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        min-width: 0 !important;
    }
    [data-testid="stMetricValue"] > div,
    [data-testid="stMetricValue"] p {
        font-size: inherit !important;
        line-height: inherit !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        max-width: none !important;
    }
    [data-testid="stMetric"] {
        min-width: 0 !important;
    }
'''
if old not in text:
    if 'clamp(.88rem, 1.55vw, 1.55rem)' in text:
        print('Metric overflow fix already applied.')
        raise SystemExit(0)
    raise SystemExit('Metric value style anchor not found; refusing partial update')
text = text.replace(old, new, 1)
text = text.replace('APP_VERSION = "2026.09.05-r48-paper-bet-size"', 'APP_VERSION = "2026.09.05-r49-metric-fit"', 1)
p.write_text(text)
print('Metric overflow fix applied.')
