from pathlib import Path

p = Path('app.py')
s = p.read_text()

old1 = '''        let currentTarget = initial.target;\n        let currentTicker = initial.ticker || \"\";\n        let lastCandleSignature = \"\";'''
new1 = '''        let currentTarget = initial.target;\n        let currentTicker = initial.ticker || \"\";\n        // Track the active UTC 15-minute window in the browser. At rollover we\n        // immediately clear the old Kalshi target so a previous contract can\n        // never remain visible while the new market is publishing.\n        let kalshiWindowKey = Math.floor(Date.now() / 900000);\n        let lastCandleSignature = \"\";'''
if old1 not in s:
    raise SystemExit('currentTarget anchor not found')
s = s.replace(old1, new1, 1)

old2 = '''        async function updateTarget() {{\n            const market = await fetchKalshiTarget();\n            if (!market) return;\n\n            const changed =\n                market.ticker !== currentTicker ||\n                market.target !== currentTarget;'''
new2 = '''        async function updateTarget() {{\n            const windowKey = Math.floor(Date.now() / 900000);\n            if (windowKey !== kalshiWindowKey) {{\n                kalshiWindowKey = windowKey;\n                currentTicker = \"\";\n                currentTarget = NaN;\n                await Plotly.relayout(chart, {{\n                    shapes: [],\n                    annotations: []\n                }});\n                status.textContent = \"Loading new Kalshi 15m target…\";\n            }}\n\n            const market = await fetchKalshiTarget();\n            if (!market) return;\n\n            const changed =\n                market.ticker !== currentTicker ||\n                market.target !== currentTarget;'''
if old2 not in s:
    raise SystemExit('updateTarget anchor not found')
s = s.replace(old2, new2, 1)

s = s.replace('const kalshiTimer = setInterval(updateTarget, 3000);', 'const kalshiTimer = setInterval(updateTarget, 1000);', 1)
s = s.replace('APP_VERSION = "2026.09.04-r33-deterministic-kalshi-market"', 'APP_VERSION = "2026.09.04-r34-atomic-kalshi-rollover"', 1)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('Kalshi rollover fixed: stale target is cleared atomically at each 15m boundary.')
