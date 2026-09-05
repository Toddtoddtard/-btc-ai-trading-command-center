from pathlib import Path


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def patch(path, replacements):
    p = Path(path)
    text = p.read_text()
    original = text
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new, 1)
        elif new in text:
            continue
        else:
            raise SystemExit(f"Anchor not found in {path}: {old[:120]!r}")
    if text != original:
        p.write_text(text)
        print(f"updated {path}")
    else:
        print(f"{path} already current")


patch("ai_core.py", [
    (
        "from political_event_watch import political_specialist_result\n",
        "from political_event_watch import political_specialist_result\nfrom technical_fvg_macd import fvg_macd_specialist\n",
    ),
    (
        '    "Historical Pattern AI",\n    "Political Event Watch AI",',
        '    "Historical Pattern AI",\n    "FVG / MACD AI",\n    "Political Event Watch AI",',
    ),
    (
        '    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()\n',
        '    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()\n    x["macd_hist"] = x["macd"] - x["macd_signal"]\n',
    ),
    (
        '    out["Historical Pattern AI"] = _specialist("Historical Pattern AI", hist_score, f"Recent 3-minute move {recent3*100:+.3f}%")\n\n    base_names = list(out.keys())',
        '    out["Historical Pattern AI"] = _specialist("Historical Pattern AI", hist_score, f"Recent 3-minute move {recent3*100:+.3f}%")\n\n    # TradingView-style technical specialist. It is calculated from our own live\n    # candles so it can be learned and backtested without scraping TradingView.\n    out["FVG / MACD AI"] = fvg_macd_specialist(hist)\n\n    base_names = list(out.keys())',
    ),
])

patch("council_v4.py", [
    (
        '    "Historical Pattern AI": 0.76,\n}',
        '    "Historical Pattern AI": 0.76,\n    "FVG / MACD AI": 0.92,\n}',
    ),
])

patch("app.py", [
    (
        "from bot_intelligence_dashboard import render_bot_intelligence_dashboard\n",
        "from bot_intelligence_dashboard import render_bot_intelligence_dashboard\nfrom technical_fvg_macd import render_tradingview_technical_panel\n",
    ),
    (
        '    "Historical Pattern AI": 0.75,\n    "Combination AI": 1.25,',
        '    "Historical Pattern AI": 0.75,\n    "FVG / MACD AI": 0.92,\n    "Combination AI": 1.25,',
    ),
    (
        '    with tab_market:\n        kctx = stable_kalshi_contract(kalshi, price)\n\n        st.subheader("Kalshi BTC 15-minute target tracker")',
        '    with tab_market:\n        kctx = stable_kalshi_contract(kalshi, price)\n\n        render_tradingview_technical_panel(hist, agg, results)\n        st.divider()\n        st.subheader("Kalshi BTC 15-minute target tracker")',
    ),
])

patch("council_backtest_v4.py", [
    (
        '    "Whale AI", "Historical Pattern AI",\n]',
        '    "Whale AI", "Historical Pattern AI", "FVG / MACD AI",\n]',
    ),
])

patch("historical_specialist_backtest_v7.py", [
    (
        '    "Historical Pattern AI",\n}',
        '    "Historical Pattern AI", "FVG / MACD AI",\n}',
    ),
])

# Documentation only when exact legacy wording is present.
readme = Path("README.md")
if readme.exists():
    text = readme.read_text()
    old = "Kalshi Context AI, Historical Pattern AI, and Combination AI"
    new = "Kalshi Context AI, Historical Pattern AI, FVG / MACD AI, and Combination AI"
    if old in text:
        readme.write_text(text.replace(old, new, 1))
        print("updated README.md")

# Static validation of the installed integration.
for path, tokens in {
    "ai_core.py": ["FVG / MACD AI", "fvg_macd_specialist", "macd_hist"],
    "council_v4.py": ["FVG / MACD AI"],
    "app.py": ["render_tradingview_technical_panel", "FVG / MACD AI"],
    "council_backtest_v4.py": ["FVG / MACD AI"],
    "historical_specialist_backtest_v7.py": ["FVG / MACD AI"],
}.items():
    content = Path(path).read_text()
    for token in tokens:
        require(token in content, f"{token!r} missing from {path}")

print("FVG/MACD v1 integration installed")
