#!/usr/bin/env python3
from pathlib import Path
import re

path = Path('app.py')
s = path.read_text()

# Repair v17 so the chart keeps the proven 3-trace layout and uses
# browser-overlay buttons instead of Plotly updatemenus/extra traces.

# 1) Add a fixed bottom-right overlay inside the existing chart wrapper.
old_chart = '''        <div id="persistent-market-chart" style="width:100%;height:415px;"></div>
    </div>'''
new_chart = '''        <div style="position:relative;width:100%;height:415px;">
            <div id="persistent-market-chart" style="width:100%;height:415px;"></div>
            <div id="prediction-horizon-controls" style="
                position:absolute;
                right:14px;
                bottom:10px;
                z-index:20;
                display:flex;
                gap:4px;
                padding:4px;
                border:1px solid #1687ff;
                border-radius:8px;
                background:rgba(8,13,20,.90);
                box-shadow:0 3px 12px rgba(0,0,0,.28);
            ">
                <button type="button" data-horizon="1" style="cursor:pointer;border:0;border-radius:6px;padding:5px 9px;font:700 12px Arial;background:#0f1828;color:#c9d6e8;">1m</button>
                <button type="button" data-horizon="5" style="cursor:pointer;border:0;border-radius:6px;padding:5px 9px;font:700 12px Arial;background:#0f1828;color:#c9d6e8;">5m</button>
                <button type="button" data-horizon="15" style="cursor:pointer;border:1px solid #2ea8ff;border-radius:6px;padding:5px 9px;font:700 12px Arial;background:#123252;color:#ffffff;">15m</button>
            </div>
        </div>
    </div>'''
if old_chart not in s and 'id="prediction-horizon-controls"' not in s:
    raise SystemExit('chart wrapper anchor not found')
if old_chart in s:
    s = s.replace(old_chart, new_chart, 1)

# 2) Replace the multi-trace horizon function with one stable selected trace.
fn_re = re.compile(r'        function predictionPathTrace\(rows, horizonMinutes = 15, visible = true\) \{\{.*?\n        \}\}(?=\n\n        function targetShape)', re.S)
fn_new = '''        function predictionPathTrace(rows, horizonMinutes = 15) {{
            const forecast = predictedCandles(rows);
            const horizon = Math.max(1, Math.min(15, Number(horizonMinutes) || 15));
            const clipped = forecast.slice(0, Math.min(forecast.length, horizon));

            return {{
                type: "scatter",
                x: clipped.map(r => r.time),
                y: clipped.map(r => r.close),
                mode: "lines+markers",
                line: {{width: 3, dash: "dot", color: "#2ea8ff"}},
                marker: {{size: 5, color: "#2ea8ff"}},
                name: "Prediction " + horizon + "m",
                hovertemplate: "AI " + horizon + "m prediction: $%{{y:,.2f}}<extra></extra>"
            }};
        }}'''
s, n = fn_re.subn(fn_new, s, count=1)
if n != 1 and 'function predictionPathTrace(rows, horizonMinutes = 15)' not in s:
    raise SystemExit(f'predictionPathTrace repair failed: {n}')

# 3) Remove the Plotly update-menu block and restore normal chart margins.
menu_re = re.compile(r'''            margin: \{\{l:8,r:62,t:34,b:62\}\},\n            updatemenus: \[\{\{.*?\n            \}\}\],''', re.S)
s, n = menu_re.subn('            margin: {{l:8,r:62,t:34,b:28}},', s, count=1)
if n != 1 and 'updatemenus:' in s:
    raise SystemExit(f'updatemenu removal failed: {n}')

# 4) Make initial render and every refresh use exactly three traces.
old_initial = '''                candleTrace(rows),
                predictionTrace(rows),
                predictionPathTrace(rows)
'''
new_initial = '''                candleTrace(rows),
                predictionTrace(rows),
                predictionPathTrace(rows, selectedPredictionHorizon)
'''
if old_initial in s:
    s = s.replace(old_initial, new_initial, 1)

old_refresh = '''                        candleTrace(rows),
                        predictionTrace(rows),
                        predictionPathTrace(rows, 1, false),
                        predictionPathTrace(rows, 5, false),
                        predictionPathTrace(rows, 15, true)
'''
new_refresh = '''                        candleTrace(rows),
                        predictionTrace(rows),
                        predictionPathTrace(rows, selectedPredictionHorizon)
'''
if old_refresh not in s:
    raise SystemExit('current five-trace refresh block not found')
s = s.replace(old_refresh, new_refresh, 1)

# 5) Add selected-horizon state and click handling before first Plotly render.
anchor = '''        let rows = initial.candles || [];

        Plotly.newPlot('''
insert = '''        let rows = initial.candles || [];
        let selectedPredictionHorizon = 15;

        const horizonButtons = Array.from(
            document.querySelectorAll('#prediction-horizon-controls button[data-horizon]')
        );

        function paintHorizonButtons() {{
            horizonButtons.forEach(btn => {{
                const active = Number(btn.dataset.horizon) === selectedPredictionHorizon;
                btn.style.background = active ? '#123252' : '#0f1828';
                btn.style.color = active ? '#ffffff' : '#c9d6e8';
                btn.style.border = active ? '1px solid #2ea8ff' : '1px solid transparent';
            }});
        }}

        function setPredictionHorizon(minutes) {{
            selectedPredictionHorizon = [1, 5, 15].includes(Number(minutes)) ? Number(minutes) : 15;
            paintHorizonButtons();
            Plotly.react(
                chart,
                [
                    candleTrace(rows),
                    predictionTrace(rows),
                    predictionPathTrace(rows, selectedPredictionHorizon)
                ],
                {{
                    ...layout,
                    shapes: targetShape(),
                    annotations: targetAnnotation()
                }},
                config
            );
        }}

        horizonButtons.forEach(btn => {{
            btn.addEventListener('click', () => setPredictionHorizon(btn.dataset.horizon));
        }});
        paintHorizonButtons();

        Plotly.newPlot('''
if anchor not in s and 'let selectedPredictionHorizon = 15;' not in s:
    raise SystemExit('selected horizon insertion anchor not found')
if anchor in s:
    s = s.replace(anchor, insert, 1)

path.write_text(s)
print('Repaired BTC prediction horizon controls with stable overlay buttons')
