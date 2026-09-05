from pathlib import Path


def replace_once(text, old, new, label):
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Missing anchor for {label}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# ai_core.py — indicators + FVG/MACD specialist
# -----------------------------------------------------------------------------
ai_path = Path("ai_core.py")
ai = ai_path.read_text()

ai = replace_once(
    ai,
    '    "Historical Pattern AI",\n    "Political Event Watch AI",\n    "Combination AI",\n',
    '    "Historical Pattern AI",\n    "FVG / MACD AI",\n    "Political Event Watch AI",\n    "Combination AI",\n',
    "ai_core specialist names",
)

ai = replace_once(
    ai,
    '    x["macd"] = ema12 - ema26\n    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()\n    x["vol20"] = x["ret1"].rolling(20).std() * np.sqrt(20)\n',
    '    x["macd"] = ema12 - ema26\n    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()\n    x["macd_hist"] = x["macd"] - x["macd_signal"]\n\n    # Three-candle fair-value gaps (ICT-style imbalance zones).\n    # Bullish FVG: current low is above the high from two candles ago.\n    # Bearish FVG: current high is below the low from two candles ago.\n    x["bull_fvg"] = x["low"] > x["high"].shift(2)\n    x["bull_fvg_lower"] = np.where(x["bull_fvg"], x["high"].shift(2), np.nan)\n    x["bull_fvg_upper"] = np.where(x["bull_fvg"], x["low"], np.nan)\n    x["bear_fvg"] = x["high"] < x["low"].shift(2)\n    x["bear_fvg_lower"] = np.where(x["bear_fvg"], x["high"], np.nan)\n    x["bear_fvg_upper"] = np.where(x["bear_fvg"], x["low"].shift(2), np.nan)\n\n    x["vol20"] = x["ret1"].rolling(20).std() * np.sqrt(20)\n',
    "MACD histogram and FVG columns",
)

fvg_specialist = '''    # FVG / MACD Technical AI: combines price imbalance structure with\n    # momentum confirmation. It is intentionally one council member rather\n    # than a master override so live learning can raise/lower its influence.\n    macd_hist = safe_float(last.get("macd_hist"), safe_float(last["macd"] - last["macd_signal"], 0.0))\n    prev_macd = safe_float(prev["macd"], 0.0)\n    prev_signal = safe_float(prev["macd_signal"], 0.0)\n    now_macd = safe_float(last["macd"], 0.0)\n    now_signal = safe_float(last["macd_signal"], 0.0)\n    if now_macd > now_signal and prev_macd <= prev_signal:\n        macd_cross = 1.0\n        macd_state = "bullish cross"\n    elif now_macd < now_signal and prev_macd >= prev_signal:\n        macd_cross = -1.0\n        macd_state = "bearish cross"\n    elif macd_hist > 0:\n        macd_cross = 0.35\n        macd_state = "bullish histogram"\n    elif macd_hist < 0:\n        macd_cross = -0.35\n        macd_state = "bearish histogram"\n    else:\n        macd_cross = 0.0\n        macd_state = "flat"\n\n    macd_strength = math.tanh(macd_hist / max(px * 0.00035, 1e-9))\n    macd_score = clamp(0.65 * macd_strength + 0.35 * macd_cross)\n\n    fvg_score = 0.0\n    fvg_state = "no fresh FVG"\n    lookback = hist.tail(60)\n    candidates = []\n    for age, (_, row) in enumerate(reversed(list(lookback.iterrows()))):\n        decay = max(0.20, 1.0 - age / 60.0)\n        if bool(row.get("bull_fvg", False)):\n            lower = safe_float(row.get("bull_fvg_lower"))\n            upper = safe_float(row.get("bull_fvg_upper"))\n            if pd.notna(lower) and pd.notna(upper):\n                if lower <= px <= upper:\n                    state = f"inside bullish FVG ${lower:,.0f}-${upper:,.0f}"\n                    score = 0.90 * decay\n                elif px > upper:\n                    state = f"bullish FVG support ${lower:,.0f}-${upper:,.0f}"\n                    score = 0.62 * decay\n                else:\n                    state = f"bullish FVG filled ${lower:,.0f}-${upper:,.0f}"\n                    score = 0.10 * decay\n                candidates.append((age, score, state))\n        if bool(row.get("bear_fvg", False)):\n            lower = safe_float(row.get("bear_fvg_lower"))\n            upper = safe_float(row.get("bear_fvg_upper"))\n            if pd.notna(lower) and pd.notna(upper):\n                if lower <= px <= upper:\n                    state = f"inside bearish FVG ${lower:,.0f}-${upper:,.0f}"\n                    score = -0.90 * decay\n                elif px < lower:\n                    state = f"bearish FVG resistance ${lower:,.0f}-${upper:,.0f}"\n                    score = -0.62 * decay\n                else:\n                    state = f"bearish FVG filled ${lower:,.0f}-${upper:,.0f}"\n                    score = -0.10 * decay\n                candidates.append((age, score, state))\n\n    if candidates:\n        age, fvg_score, fvg_state = min(candidates, key=lambda item: item[0])\n        fvg_state += f"; age {age}m"\n\n    technical_score = clamp(0.55 * fvg_score + 0.45 * macd_score)\n    technical_reason = (\n        f"{fvg_state}; MACD {macd_state}; histogram {macd_hist:+.2f}; "\n        f"FVG score {fvg_score:+.2f}; MACD score {macd_score:+.2f}"\n    )\n    out["FVG / MACD AI"] = _specialist("FVG / MACD AI", technical_score, technical_reason)\n\n'''

if 'out["FVG / MACD AI"]' not in ai:
    anchor = '    base_names = list(out.keys())\n'
    if anchor not in ai:
        raise SystemExit("Missing ai_core combination anchor")
    ai = ai.replace(anchor, fvg_specialist + anchor, 1)

ai_path.write_text(ai)


# -----------------------------------------------------------------------------
# council_v4.py — give it a starting council weight, then let learning adapt it
# -----------------------------------------------------------------------------
council_path = Path("council_v4.py")
council = council_path.read_text()
council = replace_once(
    council,
    '    "Historical Pattern AI": 0.76,\n}',
    '    "Historical Pattern AI": 0.76,\n    "FVG / MACD AI": 0.92,\n}',
    "council FVG weight",
)
council_path.write_text(council)


# -----------------------------------------------------------------------------
# app.py — local TradingView-style technical lab + app-level weight
# -----------------------------------------------------------------------------
app_path = Path("app.py")
app = app_path.read_text()
app = replace_once(
    app,
    '    "Historical Pattern AI": 0.75,\n    "Combination AI": 1.25,\n}',
    '    "Historical Pattern AI": 0.75,\n    "FVG / MACD AI": 0.90,\n    "Combination AI": 1.25,\n}',
    "app FVG weight",
)

technical_ui = '''        st.subheader("TradingView-style FVG + MACD Technical Lab")\n        st.caption("Calculated locally from the same live BTC candles used by the bots — no TradingView scraping or paid key required.")\n\n        _tech = results.get("FVG / MACD AI", {})\n        _tech_cols = st.columns(4)\n        _tech_cols[0].metric("Technical AI", _tech.get("signal", "NEUTRAL"))\n        _tech_cols[1].metric("Confidence", f"{safe_float(_tech.get('confidence'), 0.0)*100:.1f}%")\n        _tech_cols[2].metric("MACD histogram", f"{safe_float(hist['macd_hist'].iloc[-1], 0.0):+.2f}")\n        _fresh_fvg = hist.tail(60)\n        _bull_count = int(_fresh_fvg.get("bull_fvg", pd.Series(dtype=bool)).fillna(False).sum())\n        _bear_count = int(_fresh_fvg.get("bear_fvg", pd.Series(dtype=bool)).fillna(False).sum())\n        _tech_cols[3].metric("Fresh FVGs (60m)", f"{_bull_count} bull / {_bear_count} bear")\n        st.caption(_tech.get("reason", "FVG/MACD specialist warming up"))\n\n        _tv = hist.tail(180).copy()\n        _price_fig = go.Figure()\n        _price_fig.add_trace(go.Candlestick(\n            x=_tv["time"], open=_tv["open"], high=_tv["high"],\n            low=_tv["low"], close=_tv["close"], name="BTCUSDT"\n        ))\n\n        # Highlight the most recent bullish and bearish fair-value-gap zones.\n        _zone_rows = []\n        for _idx, _row in _tv.iterrows():\n            if bool(_row.get("bull_fvg", False)):\n                _zone_rows.append((\n                    _row["time"], safe_float(_row.get("bull_fvg_lower")),\n                    safe_float(_row.get("bull_fvg_upper")), "bull"\n                ))\n            if bool(_row.get("bear_fvg", False)):\n                _zone_rows.append((\n                    _row["time"], safe_float(_row.get("bear_fvg_lower")),\n                    safe_float(_row.get("bear_fvg_upper")), "bear"\n                ))\n        for _x0, _low, _high, _kind in _zone_rows[-10:]:\n            if not (pd.notna(_low) and pd.notna(_high)):\n                continue\n            _price_fig.add_shape(\n                type="rect", x0=_x0, x1=_tv["time"].iloc[-1], y0=_low, y1=_high,\n                line=dict(width=1, color="#00d6a3" if _kind == "bull" else "#ff4d68"),\n                fillcolor="rgba(0,214,163,0.13)" if _kind == "bull" else "rgba(255,77,104,0.13)",\n                layer="below",\n            )\n        _price_fig.update_layout(\n            template="plotly_dark", height=470, margin=dict(l=10, r=10, t=35, b=10),\n            title="BTC 1-minute candles with Fair Value Gaps",\n            xaxis_rangeslider_visible=False,\n            paper_bgcolor="#080d14", plot_bgcolor="#0d141f",\n            legend=dict(orientation="h"),\n        )\n        st.plotly_chart(_price_fig, use_container_width=True, key="fvg_price_chart")\n\n        _macd_fig = go.Figure()\n        _macd_fig.add_trace(go.Scatter(\n            x=_tv["time"], y=_tv["macd"], mode="lines", name="MACD", line=dict(width=2)\n        ))\n        _macd_fig.add_trace(go.Scatter(\n            x=_tv["time"], y=_tv["macd_signal"], mode="lines", name="Signal", line=dict(width=2)\n        ))\n        _hist_colors = ["#00d6a3" if safe_float(v, 0.0) >= 0 else "#ff4d68" for v in _tv["macd_hist"]]\n        _macd_fig.add_trace(go.Bar(\n            x=_tv["time"], y=_tv["macd_hist"], name="Histogram", marker_color=_hist_colors, opacity=0.72\n        ))\n        _macd_fig.add_hline(y=0, line_width=1, line_dash="dot")\n        _macd_fig.update_layout(\n            template="plotly_dark", height=300, margin=dict(l=10, r=10, t=35, b=10),\n            title="MACD (12, 26, 9)", paper_bgcolor="#080d14", plot_bgcolor="#0d141f",\n            legend=dict(orientation="h"),\n        )\n        st.plotly_chart(_macd_fig, use_container_width=True, key="fvg_macd_chart")\n\n        st.divider()\n\n'''

ui_anchor = '    with tab_market:\n        kctx = stable_kalshi_contract(kalshi, price)\n\n        st.subheader("Kalshi BTC 15-minute target tracker")\n'
if 'TradingView-style FVG + MACD Technical Lab' not in app:
    if ui_anchor not in app:
        raise SystemExit("Missing Market-tab UI anchor")
    app = app.replace(
        ui_anchor,
        '    with tab_market:\n        kctx = stable_kalshi_contract(kalshi, price)\n\n' + technical_ui + '        st.subheader("Kalshi BTC 15-minute target tracker")\n',
        1,
    )

app_path.write_text(app)


# -----------------------------------------------------------------------------
# Historical/council backtests — FVG/MACD is replayable from candle history
# -----------------------------------------------------------------------------
cb_path = Path("council_backtest_v4.py")
cb = cb_path.read_text()
if '"FVG / MACD AI"' not in cb:
    old = '    "Whale AI", "Historical Pattern AI",\n'
    if old not in cb:
        raise SystemExit("Missing council backtest replayable anchor")
    cb = cb.replace(old, '    "Whale AI", "Historical Pattern AI", "FVG / MACD AI",\n', 1)
cb_path.write_text(cb)

hs_path = Path("historical_specialist_backtest_v7.py")
hs = hs_path.read_text()
if '"FVG / MACD AI"' not in hs.split('HORIZON_NS', 1)[0]:
    old = '    "Historical Pattern AI",\n}\n'
    if old not in hs:
        raise SystemExit("Missing historical specialist eligible anchor")
    hs = hs.replace(old, '    "Historical Pattern AI", "FVG / MACD AI",\n}\n', 1)
hs_path.write_text(hs)

print("Installed FVG / MACD Technical AI, TradingView-style charts, and replay learning support.")
