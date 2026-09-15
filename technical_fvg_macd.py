"""TradingView-style FVG + MACD technical analysis for BTC.

This module does not scrape TradingView. It calculates the same underlying
technical concepts from the app's live candle feed so the specialist can be
backtested, learned, and used even when TradingView is unavailable.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from macd_engine import add_macd_features, score_macd


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _clamp(value, lo=-1.0, hi=1.0):
    return float(max(lo, min(hi, _safe_float(value))))


def detect_fvg_zones(hist: pd.DataFrame, lookback: int = 120):
    """Return recent 3-candle fair-value-gap zones.

    Bullish FVG: candle i low is above candle i-2 high.
    Bearish FVG: candle i high is below candle i-2 low.
    Each zone also tracks whether price has subsequently filled it.
    """
    if hist is None or len(hist) < 3:
        return []
    x = hist.tail(max(lookback, 3)).reset_index(drop=True)
    zones = []
    for i in range(2, len(x)):
        c0 = x.iloc[i - 2]
        c2 = x.iloc[i]
        if _safe_float(c2.get("low")) > _safe_float(c0.get("high")):
            low, high = float(c0["high"]), float(c2["low"])
            future = x.iloc[i + 1 :]
            filled = bool((future["low"] <= low).any()) if not future.empty else False
            zones.append({"side": "BULLISH", "low": low, "high": high, "index": i, "filled": filled})
        if _safe_float(c2.get("high")) < _safe_float(c0.get("low")):
            low, high = float(c2["high"]), float(c0["low"])
            future = x.iloc[i + 1 :]
            filled = bool((future["high"] >= high).any()) if not future.empty else False
            zones.append({"side": "BEARISH", "low": low, "high": high, "index": i, "filled": filled})
    return zones[-12:]


def fvg_macd_specialist(hist: pd.DataFrame):
    if hist is None or len(hist) < 30:
        return {
            "name": "FVG / MACD AI",
            "signal": "NEUTRAL",
            "score": 0.0,
            "confidence": 0.48,
            "reason": "Waiting for enough candle history",
            "fvg_state": "NONE",
            "macd_state": "NEUTRAL",
        }

    x = hist.copy()
    x = add_macd_features(x)

    last = x.iloc[-1]
    px = float(last["close"])
    macd_view = score_macd(x)
    hist_now = macd_view["standard_hist"]
    macd_score = macd_view["score"]
    bullish_cross = macd_view["cross"] == "bullish"
    bearish_cross = macd_view["cross"] == "bearish"

    zones = detect_fvg_zones(x)
    active = [z for z in zones if not z["filled"]]
    fvg_score = 0.0
    fvg_state = "NONE"
    nearest = None
    if active:
        nearest = min(active, key=lambda z: min(abs(px - z["low"]), abs(px - z["high"])))
        width = max(nearest["high"] - nearest["low"], px * 0.00005)
        distance = 0.0 if nearest["low"] <= px <= nearest["high"] else min(abs(px - nearest["low"]), abs(px - nearest["high"]))
        proximity = max(0.0, 1.0 - distance / max(width * 4.0, px * 0.002))
        if nearest["side"] == "BULLISH":
            fvg_score = 0.55 * proximity
            fvg_state = "BULLISH FVG" if px >= nearest["low"] else "BULLISH FVG BELOW"
        else:
            fvg_score = -0.55 * proximity
            fvg_state = "BEARISH FVG" if px <= nearest["high"] else "BEARISH FVG ABOVE"

    combined = _clamp(0.62 * macd_score + 0.38 * fvg_score)
    # Agreement earns a modest boost, disagreement reduces conviction.
    if macd_score * fvg_score > 0:
        combined = _clamp(combined * 1.15)
    elif macd_score * fvg_score < 0:
        combined = _clamp(combined * 0.72)

    if combined > 0.12:
        signal = "BULLISH"
    elif combined < -0.12:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    confidence = float(min(0.95, 0.48 + abs(combined) * 0.44))
    macd_state = macd_view["state"].upper()
    zone_text = "no active FVG" if nearest is None else f"{nearest['side'].lower()} FVG ${nearest['low']:,.0f}-${nearest['high']:,.0f}"
    reason = (
        f"Adaptive MACD {macd_state.lower()} (standard {hist_now:+.2f}, "
        f"fast {macd_view['fast_hist']:+.2f}, {macd_view['agreement']}); "
        f"{zone_text}; combined {combined:+.2f}"
    )
    return {
        "name": "FVG / MACD AI",
        "signal": signal,
        "score": combined,
        "confidence": confidence,
        "reason": reason,
        "fvg_state": fvg_state,
        "macd_state": macd_state,
        "bullish_cross": bool(bullish_cross),
        "bearish_cross": bool(bearish_cross),
        "active_fvgs": active[-6:],
    }


def _order_flow_summary(agg):
    if agg is None or getattr(agg, "empty", True):
        return 0.0
    try:
        buy = float(agg.loc[agg["aggressor"] == "BUY", "notional"].sum())
        sell = float(agg.loc[agg["aggressor"] == "SELL", "notional"].sum())
        total = buy + sell
        return (buy - sell) / total if total else 0.0
    except Exception:
        return 0.0


def render_tradingview_technical_panel(hist, agg=None, specialist_results=None):
    """Render a TradingView-style price + FVG + MACD panel in Streamlit."""
    if hist is None or len(hist) < 30:
        st.info("Technical chart is warming up.")
        return

    tech = (specialist_results or {}).get("FVG / MACD AI") or fvg_macd_specialist(hist)
    tail = hist.tail(160).copy()
    tail = add_macd_features(tail)

    st.subheader("TradingView-style BTC technicals — FVG + MACD")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Technical AI", tech.get("signal", "NEUTRAL"))
    c2.metric("Confidence", f"{_safe_float(tech.get('confidence'))*100:.1f}%")
    c3.metric("FVG", tech.get("fvg_state", "NONE"))
    c4.metric("MACD", tech.get("macd_state", "NEUTRAL"))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.70, 0.30])
    fig.add_trace(go.Candlestick(x=tail["time"], open=tail["open"], high=tail["high"], low=tail["low"], close=tail["close"], name="BTCUSDT"), row=1, col=1)
    zones = detect_fvg_zones(tail, lookback=len(tail))
    x0, x1 = tail["time"].iloc[0], tail["time"].iloc[-1]
    for zone in [z for z in zones if not z["filled"]][-6:]:
        fill = "rgba(0,210,170,0.12)" if zone["side"] == "BULLISH" else "rgba(255,80,100,0.12)"
        line = "rgba(0,210,170,0.45)" if zone["side"] == "BULLISH" else "rgba(255,80,100,0.45)"
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=zone["low"], y1=zone["high"], line=dict(color=line, width=1), fillcolor=fill, row=1, col=1)

    fig.add_trace(go.Bar(x=tail["time"], y=tail["macd_hist"], name="MACD histogram"), row=2, col=1)
    fig.add_trace(go.Scatter(x=tail["time"], y=tail["macd"], mode="lines", name="MACD"), row=2, col=1)
    fig.add_trace(go.Scatter(x=tail["time"], y=tail["macd_signal"], mode="lines", name="Signal"), row=2, col=1)
    fig.add_trace(go.Scatter(x=tail["time"], y=tail["macd_fast_hist"], mode="lines", name="Fast momentum", line=dict(dash="dot", width=1)), row=2, col=1)
    fig.update_layout(template="plotly_dark", height=620, margin=dict(l=8, r=8, t=32, b=8), xaxis_rangeslider_visible=False, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True, key="fvg_macd_tradingview_panel")

    flow = _order_flow_summary(agg)
    agreement = "AGREES" if (flow > 0 and _safe_float(tech.get("score")) > 0) or (flow < 0 and _safe_float(tech.get("score")) < 0) else "CONFLICTS" if abs(flow) > 0.05 and abs(_safe_float(tech.get("score"))) > 0.12 else "MIXED"
    st.caption(f"Aggr/order-flow pressure: {flow*100:+.1f}% — {agreement} with FVG/MACD. Technical signals are one learned council input, not an automatic trade trigger.")
