from pathlib import Path

p = Path('app.py')
text = p.read_text()
old = '''    [data-testid="stMetricValue"] {
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
new = '''    [data-testid="stMetricValue"] {
        font-size: clamp(.84rem, 1.48vw, 1.48rem) !important;
        line-height: 1.15 !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        min-width: 0 !important;
        width: 100% !important;
        box-sizing: border-box !important;
        padding-right: .65rem !important;
    }
    [data-testid="stMetricValue"] > div,
    [data-testid="stMetricValue"] p {
        font-size: inherit !important;
        line-height: inherit !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        padding-right: .10rem !important;
    }
    [data-testid="stMetric"] {
        min-width: 0 !important;
        box-sizing: border-box !important;
        padding-right: .20rem !important;
    }
'''
if old not in text:
    raise SystemExit('Current metric style block not found; refusing partial update')
text = text.replace(old, new, 1)
text = text.replace('APP_VERSION = "2026.09.05-r49-metric-fit"', 'APP_VERSION = "2026.09.05-r50-global-metric-padding"', 1)
p.write_text(text)
