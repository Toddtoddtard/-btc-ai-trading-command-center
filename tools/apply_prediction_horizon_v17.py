#!/usr/bin/env python3
from pathlib import Path
import re

path = Path('app.py')
s = path.read_text()

old_fn = re.compile(r'        function predictionPathTrace\(rows\) \{\{.*?\n        \}\}(?=\n\n        function )', re.S)
new_fn = '''        function predictionPathTrace(rows, horizonMinutes = 15, visible = true) {{
            const forecast = predictedCandles(rows);
            const horizon = Math.max(1, Math.min(15, Number(horizonMinutes) || 15));
            const clipped = forecast.slice(0, Math.min(forecast.length, horizon + 1));

            if (!clipped.length) {{
                return {{
                    type: "scatter", x: [], y: [], mode: "lines",
                    visible: visible,
                    name: `Prediction ${{horizon}}m`
                }};
            }}

            return {{
                type: "scatter",
                x: clipped.map(r => r.time),
                y: clipped.map(r => r.close),
                mode: "lines+markers",
                line: {{width: 3, dash: "dot", color: "#2ea8ff"}},
                marker: {{size: 5, color: "#2ea8ff"}},
                visible: visible,
                name: `Prediction ${{horizon}}m`,
                hovertemplate: `AI ${{horizon}}m prediction: $%{{y:,.2f}}<extra></extra>`
            }};
        }}'''

s, n = old_fn.subn(new_fn, s, count=1)
if n != 1:
    raise SystemExit(f'predictionPathTrace patch failed: {n}')

old_call = '                        predictionPathTrace(rows)'
new_calls = '''                        predictionPathTrace(rows, 1, false),
                        predictionPathTrace(rows, 5, false),
                        predictionPathTrace(rows, 15, true)'''
count = s.count(old_call)
if count < 2:
    raise SystemExit(f'expected at least two predictionPathTrace array calls, found {count}')
s = s.replace(old_call, new_calls)

layout_anchor = '''        const layout = {{
            paper_bgcolor: paperBg,
            plot_bgcolor: plotBg,
            font: {{color: fontColor}},
            margin: {{l:8,r:62,t:34,b:28}},'''
layout_repl = '''        const layout = {{
            paper_bgcolor: paperBg,
            plot_bgcolor: plotBg,
            font: {{color: fontColor}},
            margin: {{l:8,r:62,t:34,b:62}},
            updatemenus: [{{
                type: "buttons",
                direction: "right",
                x: 1.0,
                xanchor: "right",
                y: -0.12,
                yanchor: "top",
                pad: {{r: 2, t: 4}},
                bgcolor: darkMode ? "#0f1828" : "#f3f6fa",
                bordercolor: "#1687ff",
                borderwidth: 1,
                font: {{color: fontColor, size: 12}},
                active: 2,
                buttons: [
                    {{label: "1m", method: "restyle", args: [{{visible:[true,false,false]}}, [2,3,4]]}},
                    {{label: "5m", method: "restyle", args: [{{visible:[false,true,false]}}, [2,3,4]]}},
                    {{label: "15m", method: "restyle", args: [{{visible:[false,false,true]}}, [2,3,4]]}}
                ]
            }}],'''
if layout_anchor not in s:
    raise SystemExit('layout anchor not found')
s = s.replace(layout_anchor, layout_repl, 1)

path.write_text(s)
print('Installed BTC chart horizon switcher: 1m / 5m / 15m')
