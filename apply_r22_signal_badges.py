from pathlib import Path

p = Path('app.py')
s = p.read_text()

old = '            table_html = council_df.to_html(index=False, border=0, classes="ai-council-table")\n'
new = '''            def _signal_badge(value):\n                label = str(value).upper()\n                if label == "BULLISH":\n                    cls = "signal-bullish"\n                elif label == "BEARISH":\n                    cls = "signal-bearish"\n                else:\n                    cls = "signal-neutral"\n                return f'<span class="signal-badge {cls}">{label}</span>'\n\n            table_html = council_df.to_html(\n                index=False,\n                border=0,\n                classes="ai-council-table",\n                escape=False,\n                formatters={"Signal": _signal_badge},\n            )\n'''

if old not in s:
    raise SystemExit('Council table_html line not found')
s = s.replace(old, new, 1)

css_anchor = '                .ai-council-table td:last-child {white-space: normal; min-width: 260px;}\n'
css_add = '''                .ai-council-table td:last-child {white-space: normal; min-width: 260px;}\n                .signal-badge {\n                    display:inline-block; min-width:92px; text-align:center;\n                    padding:4px 10px; border-radius:7px; font-weight:800;\n                    letter-spacing:.02em; line-height:1.2;\n                }\n                .signal-bullish {\n                    color:#00f0b5; background:rgba(0,240,181,.13);\n                    border:1px solid rgba(0,240,181,.80);\n                    box-shadow:0 0 12px rgba(0,240,181,.10) inset;\n                }\n                .signal-bearish {\n                    color:#ff536b; background:rgba(255,83,107,.13);\n                    border:1px solid rgba(255,83,107,.85);\n                    box-shadow:0 0 12px rgba(255,83,107,.10) inset;\n                }\n                .signal-neutral {\n                    color:#b8c6dc; background:rgba(184,198,220,.09);\n                    border:1px solid rgba(184,198,220,.42);\n                }\n'''
if css_anchor not in s:
    raise SystemExit('Council CSS anchor not found')
s = s.replace(css_anchor, css_add, 1)

s = s.replace(
    'APP_VERSION = "2026.09.04-single-file-r21-dark-council-table"',
    'APP_VERSION = "2026.09.04-single-file-r22-signal-badges"',
    1,
)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R22 signal badge visual patch applied successfully')
