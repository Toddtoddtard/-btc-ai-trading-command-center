import json
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from access_control import require_owner_approval
from ai_core import enrich_history_core, forecast_path_core, run_specialists_core
from multi_market_nav import MARKETS, render_market_nav


ASSET_CONFIG = {
    "gold": {
        "title": "Gold AI Trading Command Center",
        "symbol": "GC=F",
        "display_symbol": "GOLD",
        "source": "Yahoo Finance • COMEX Gold Futures",
        "unit": "USD/oz",
        "provider": "yahoo",
        "kalshi_keywords": ["gold"],
        "kalshi_prefixes": ["KXGOLD", "GOLD"],
        "accent": "#f5c542",
    },
    "gas": {
        "title": "Gas Prices AI Trading Command Center",
        "symbol": "RB=F",
        "display_symbol": "RBOB",
        "source": "Yahoo Finance • RBOB Gasoline Futures",
        "unit": "USD/gal",
        "provider": "yahoo",
        "kalshi_keywords": ["gasoline", "gas price", "gas prices", "rbob"],
        "kalshi_prefixes": ["KXGAS", "GASOLINE", "RBOB"],
        "accent": "#20c997",
    },
    "zec": {
        "title": "ZEC AI Trading Command Center",
        "symbol": "ZECUSDT",
        "display_symbol": "ZEC",
        "source": "Binance public spot market",
        "unit": "USDT",
        "provider": "binance",
        "kalshi_keywords": ["zcash", "zec"],
        "kalshi_prefixes": ["ZEC", "KXZEC"],
        "accent": "#ffd43b",
    },
    "wti": {
        "title": "WTI Oil AI Trading Command Center",
        "symbol": "CL=F",
        "display_symbol": "WTI",
        "source": "Yahoo Finance • NYMEX WTI Crude Futures",
        "unit": "USD/bbl",
        "provider": "yahoo",
        "kalshi_keywords": ["wti", "crude oil", "oil price"],
        "kalshi_prefixes": ["KXWTI15M", "KXWTI", "WTI"],
        "accent": "#ff922b",
    },
}

BASE_SPECIALISTS = [
    "Trend AI",
    "Momentum AI",
    "Volume AI",
    "Pattern AI",
    "Support/Resistance AI",
    "Volatility AI",
    "Market Regime AI",
    "Historical Pattern AI",
    "Combination AI",
]


def _safe_float(value, default=np.nan):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _http_json(url, params=None, timeout=4.0):
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Multi-Asset-AI-Command-Center/1.0",
            "Accept": "application/json",
        },
    )
    started = time.perf_counter()
    with urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.perf_counter() - started) * 1000.0


@st.cache_data(ttl=4, show_spinner=False)
def fetch_yahoo_history(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    payload, latency = _http_json(
        url,
        {
            "interval": "1m",
            "range": "1d",
            "includePrePost": "true",
            "events": "div,splits",
        },
        timeout=4.5,
    )
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError("Yahoo market history unavailable")
    node = result[0]
    timestamps = node.get("timestamp") or []
    quote_rows = ((((node.get("indicators") or {}).get("quote")) or [{}])[0]) or {}
    n = len(timestamps)
    if n < 30:
        raise RuntimeError("Not enough 1-minute history")
    df = pd.DataFrame({
        "time": pd.to_datetime(timestamps, unit="s", utc=True),
        "open": quote_rows.get("open", [None] * n),
        "high": quote_rows.get("high", [None] * n),
        "low": quote_rows.get("low", [None] * n),
        "close": quote_rows.get("close", [None] * n),
        "volume": quote_rows.get("volume", [0] * n),
    })
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0.0)
    df = df.dropna(subset=["open", "high", "low", "close"]).drop_duplicates("time").sort_values("time")
    if len(df) < 30:
        raise RuntimeError("Clean 1-minute history unavailable")
    meta = node.get("meta") or {}
    return df.tail(480).reset_index(drop=True), {
        "latency_ms": latency,
        "exchange": meta.get("exchangeName") or meta.get("fullExchangeName") or "Yahoo Finance",
        "currency": meta.get("currency") or "USD",
        "market_state": meta.get("marketState") or "UNKNOWN",
    }


@st.cache_data(ttl=3, show_spinner=False)
def fetch_binance_history(symbol):
    payload, latency = _http_json(
        "https://data-api.binance.vision/api/v3/klines",
        {"symbol": symbol, "interval": "1m", "limit": 480},
        timeout=4.0,
    )
    rows = []
    for item in payload:
        rows.append({
            "time": pd.to_datetime(int(item[0]), unit="ms", utc=True),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        })
    df = pd.DataFrame(rows)
    if len(df) < 30:
        raise RuntimeError("Binance 1-minute history unavailable")
    return df, {
        "latency_ms": latency,
        "exchange": "Binance Spot",
        "currency": "USDT",
        "market_state": "24/7",
    }


@st.cache_data(ttl=3, show_spinner=False)
def fetch_binance_flow(symbol):
    agg_payload, agg_latency = _http_json(
        "https://data-api.binance.vision/api/v3/aggTrades",
        {"symbol": symbol, "limit": 500},
        timeout=4.0,
    )
    agg_rows = []
    for item in agg_payload:
        price = float(item["p"])
        qty = float(item["q"])
        aggressor = "SELL" if bool(item.get("m")) else "BUY"
        agg_rows.append({
            "price": price,
            "qty": qty,
            "notional": price * qty,
            "aggressor": aggressor,
            "time": pd.to_datetime(int(item["T"]), unit="ms", utc=True),
        })
    agg = pd.DataFrame(agg_rows)

    depth_payload, depth_latency = _http_json(
        "https://data-api.binance.vision/api/v3/depth",
        {"symbol": symbol, "limit": 100},
        timeout=4.0,
    )
    bids = sum(float(p) * float(q) for p, q in depth_payload.get("bids", []))
    asks = sum(float(p) * float(q) for p, q in depth_payload.get("asks", []))
    total = bids + asks
    imbalance = (bids - asks) / total if total else 0.0
    return agg, {
        "book_imbalance": float(np.clip(imbalance, -1, 1)),
        "funding_rate": 0.0,
        "open_interest": 0.0,
        "flow_latency_ms": max(agg_latency, depth_latency),
        "spot_book": True,
    }


def _extract_target(text):
    text = str(text or "")
    matches = re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not matches:
        if not re.search(r"\b(above|below|over|under|higher|lower|price|settle)\b", text, re.I):
            return np.nan
        matches = re.findall(r"\b([0-9][0-9,]*(?:\.[0-9]+)?)\b", text)
    values = []
    for raw in matches:
        try:
            values.append(float(raw.replace(",", "")))
        except Exception:
            pass
    return values[-1] if values else np.nan


def _market_probability(market):
    candidates = [market.get("yes_ask"), market.get("last_price"), market.get("yes_bid")]
    for value in candidates:
        value = _safe_float(value)
        if pd.notna(value):
            if value > 1.0:
                value /= 100.0
            return float(np.clip(value, 0.0, 1.0))
    return np.nan


@st.cache_data(ttl=20, show_spinner=False)
def fetch_kalshi_context(market_key):
    cfg = ASSET_CONFIG[market_key]
    if market_key == "zec":
        return {
            "available": False,
            "reason": "No verified Kalshi ZEC market",
            "ticker": "",
            "title": "",
            "target": np.nan,
            "up_probability": np.nan,
            "latency_ms": np.nan,
        }

    payload, latency = _http_json(
        "https://api.elections.kalshi.com/trade-api/v2/markets",
        {"status": "open", "limit": 1000},
        timeout=5.0,
    )
    markets = (payload or {}).get("markets") or []

    prefixes = [x.upper() for x in cfg["kalshi_prefixes"]]
    keywords = [x.lower() for x in cfg["kalshi_keywords"]]
    ranked = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        title = str(market.get("title") or "")
        subtitle = str(market.get("subtitle") or "")
        event_ticker = str(market.get("event_ticker") or "")
        haystack = " ".join([ticker, title, subtitle, event_ticker])
        upper = haystack.upper()
        lower = haystack.lower()
        prefix_hit = any(p and p in upper for p in prefixes)
        keyword_hits = sum(1 for k in keywords if k in lower)
        if not prefix_hit and not keyword_hits:
            continue
        close_ts = pd.to_datetime(
            market.get("close_time") or market.get("expiration_time"),
            utc=True,
            errors="coerce",
        )
        future_bonus = 0
        if pd.notna(close_ts):
            seconds = (close_ts - pd.Timestamp.now(tz="UTC")).total_seconds()
            if seconds > 0:
                future_bonus = 2
                proximity = max(0.0, 1.0 - min(seconds, 86400.0) / 86400.0)
            else:
                proximity = -1.0
        else:
            proximity = 0.0
        score = (10 if prefix_hit else 0) + keyword_hits * 3 + future_bonus + proximity
        ranked.append((score, market))

    if not ranked:
        return {
            "available": False,
            "reason": "No matching open Kalshi market found",
            "ticker": "",
            "title": "",
            "target": np.nan,
            "up_probability": np.nan,
            "latency_ms": latency,
        }

    market = max(ranked, key=lambda x: x[0])[1]
    title = str(market.get("title") or "")
    subtitle = str(market.get("subtitle") or "")
    target = _extract_target(f"{title} {subtitle}")
    close_ts = pd.to_datetime(
        market.get("close_time") or market.get("expiration_time"),
        utc=True,
        errors="coerce",
    )
    return {
        "available": True,
        "reason": "Matched live Kalshi market",
        "ticker": str(market.get("ticker") or ""),
        "title": title,
        "subtitle": subtitle,
        "target": target,
        "up_probability": _market_probability(market),
        "close_time": close_ts.isoformat() if pd.notna(close_ts) else "",
        "latency_ms": latency,
    }


def _genericize_specialist_text(results, cfg, kctx):
    symbol = cfg["display_symbol"]
    for result in results.values():
        reason = str(result.get("reason") or "")
        reason = reason.replace("BTC", symbol)
        reason = reason.replace("Live KXBTC15M target unavailable", f"Live Kalshi {symbol} context unavailable")
        result["reason"] = reason

    if "Kalshi Context AI" in results and not kctx.get("available"):
        results["Kalshi Context AI"].update(
            signal="NEUTRAL",
            score=0.0,
            confidence=0.48,
            reason=kctx.get("reason") or f"Kalshi {symbol} context unavailable",
        )
    return results


def _decision(results, market_key, kctx):
    cfg = ASSET_CONFIG[market_key]
    active = list(BASE_SPECIALISTS)
    if kctx.get("available"):
        active.append("Kalshi Context AI")
    if market_key == "zec":
        active.extend(["Whale AI", "Liquidity AI"])

    rows = [results[n] for n in active if n in results]
    if not rows:
        return {"action": "WAIT", "score": 0.0, "confidence": 0.0, "consensus": 0.0}

    weights = []
    weighted_scores = []
    directional_signs = []
    for result in rows:
        conf = float(np.clip(_safe_float(result.get("confidence"), 0.48), 0.0, 1.0))
        score = float(np.clip(_safe_float(result.get("score"), 0.0), -1.0, 1.0))
        weight = max(0.15, conf)
        weights.append(weight)
        weighted_scores.append(score * weight)
        if abs(score) >= 0.12:
            directional_signs.append(np.sign(score))

    score = float(sum(weighted_scores) / max(sum(weights), 1e-9))
    direction = np.sign(score)
    if directional_signs:
        consensus = float(sum(1 for x in directional_signs if x == direction) / len(directional_signs))
    else:
        consensus = 0.0

    evidence = min(1.0, abs(score) / 0.55)
    confidence = float(np.clip(0.48 + 0.30 * evidence + 0.18 * consensus, 0.48, 0.92))

    if abs(score) < 0.14 or consensus < 0.60 or confidence < 0.66:
        action = "WAIT"
    else:
        action = "SCALP UP" if score > 0 else "SCALP DOWN"

    return {
        "action": action,
        "score": score,
        "confidence": confidence,
        "consensus": consensus,
        "active_specialists": len(rows),
        "source": cfg["source"],
    }


def _fmt_price(value, cfg):
    if pd.isna(value):
        return "N/A"
    if cfg["unit"] == "USD/gal":
        return f"${value:,.4f}"
    return f"${value:,.2f}"


def _badge(label):
    label = str(label or "WAIT").upper()
    if "UP" in label or "BULLISH" in label:
        cls, icon = "up", "▲"
    elif "DOWN" in label or "BEARISH" in label:
        cls, icon = "down", "▼"
    else:
        cls, icon = "wait", "•"
    return f'<span class="signal-badge {cls}">{icon}&nbsp;&nbsp;{label}</span>'


def _style(accent):
    st.markdown(
        f"""
        <style>
        .block-container {{padding-top:1.05rem; padding-bottom:2rem;}}
        .paper-banner {{
            padding:.72rem 1rem;border:1px solid {accent};border-radius:11px;
            background:linear-gradient(180deg,rgba(8,25,44,.96),rgba(6,18,32,.96));
            font-weight:800;margin:.2rem 0 .8rem 0;
        }}
        .asset-card {{
            border:1px solid #1687ff;border-radius:13px;padding:.75rem 1rem;
            min-height:92px;background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
            box-shadow:0 10px 28px rgba(0,0,0,.18);
        }}
        .asset-label {{color:#9fb2ce;font-size:.86rem;font-weight:650;}}
        .asset-value {{font-size:1.42rem;font-weight:850;margin-top:.48rem;color:#f4f8ff;}}
        .signal-badge {{
            display:inline-flex;align-items:center;justify-content:center;
            min-width:150px;padding:10px 18px;border-radius:9px;font-weight:850;
        }}
        .signal-badge.up {{color:#20f0bd;background:rgba(0,230,179,.12);border:1px solid rgba(0,230,179,.72);}}
        .signal-badge.down {{color:#ff5d72;background:rgba(255,73,100,.12);border:1px solid rgba(255,73,100,.78);}}
        .signal-badge.wait {{color:#c2d1e6;background:rgba(140,160,190,.11);border:1px solid rgba(140,160,190,.45);}}
        .source-ok {{color:#20f0bd;font-weight:800;}}
        .source-warn {{color:#ffd166;font-weight:800;}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _chart(hist, cfg, forecast=None, target=np.nan):
    tail = hist.tail(180)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=tail["time"], open=tail["open"], high=tail["high"],
        low=tail["low"], close=tail["close"], name=cfg["display_symbol"],
    ))
    if "ema9" in tail:
        fig.add_trace(go.Scatter(x=tail["time"], y=tail["ema9"], name="EMA 9", line=dict(width=1)))
    if "ema21" in tail:
        fig.add_trace(go.Scatter(x=tail["time"], y=tail["ema21"], name="EMA 21", line=dict(width=1)))
    if pd.notna(target):
        fig.add_hline(
            y=target, line_dash="solid", line_width=3,
            annotation_text=f"KALSHI TARGET {_fmt_price(target, cfg)}",
            annotation_position="top left",
        )
    if forecast:
        start = pd.Timestamp(tail["time"].iloc[-1])
        xs = [start + pd.Timedelta(minutes=int(row["step"])) for row in forecast]
        ys = [row["close"] for row in forecast]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", name="AI 15m forecast",
            line=dict(dash="dot", width=2),
        ))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#080d14",
        plot_bgcolor="#0d141f",
        height=430,
        margin=dict(l=8, r=8, t=20, b=8),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02),
        uirevision=f"asset-{cfg['display_symbol']}",
        transition_duration=0,
    )
    return fig


def _paper_state(key):
    state_key = f"paper_state_{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {
            "cash": 100000.0,
            "side": "NONE",
            "entry": np.nan,
            "qty": 0.0,
            "realized": 0.0,
            "trades": 0,
        }
    return st.session_state[state_key]


def _paper_panel(market_key, price, decision):
    state = _paper_state(market_key)
    side = state["side"]
    unrealized = 0.0
    if side != "NONE" and pd.notna(state["entry"]):
        move = (price - state["entry"]) * state["qty"]
        unrealized = move if side == "LONG" else -move

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Paper cash", f"${state['cash']:,.2f}")
    c2.metric("Position", side)
    c3.metric("Realized P&L", f"${state['realized']:,.2f}")
    c4.metric("Unrealized P&L", f"${unrealized:,.2f}")

    st.caption("Manual paper controls for this market. Real-money execution is not included.")
    left, mid, right = st.columns(3)
    notional = min(5000.0, state["cash"] * 0.05)
    qty = notional / max(price, 1e-9)

    if left.button("Paper LONG", key=f"paper_long_{market_key}", use_container_width=True, disabled=side != "NONE"):
        state.update(side="LONG", entry=price, qty=qty)
        st.rerun()
    if mid.button("Paper SHORT", key=f"paper_short_{market_key}", use_container_width=True, disabled=side != "NONE"):
        state.update(side="SHORT", entry=price, qty=qty)
        st.rerun()
    if right.button("Close paper position", key=f"paper_close_{market_key}", use_container_width=True, disabled=side == "NONE"):
        pnl = unrealized
        state["cash"] += pnl
        state["realized"] += pnl
        state["trades"] += 1
        state.update(side="NONE", entry=np.nan, qty=0.0)
        st.rerun()

    st.info(
        f"AI council currently says **{decision['action']}** with "
        f"{decision['confidence']:.0%} confidence and {decision['consensus']:.0%} consensus. "
        "Paper buttons remain manual so the new markets can be validated before auto-paper execution."
    )


def render_market_command_center(market_key):
    require_owner_approval()
    cfg = ASSET_CONFIG[market_key]
    _style(cfg["accent"])
    render_market_nav(market_key)

    st.title(cfg["title"])
    st.markdown(
        '<div class="paper-banner">PAPER TRADING ONLY — market-specific live data + AI council. No real-money execution.</div>',
        unsafe_allow_html=True,
    )

    try:
        if cfg["provider"] == "binance":
            raw_hist, meta = fetch_binance_history(cfg["symbol"])
            agg, futures = fetch_binance_flow(cfg["symbol"])
        else:
            raw_hist, meta = fetch_yahoo_history(cfg["symbol"])
            agg, futures = None, {}
        hist = enrich_history_core(raw_hist)
        if len(hist.dropna(subset=["ema21", "rsi", "atr14"])) < 10:
            raise RuntimeError("Indicators are still warming up")
        kctx = fetch_kalshi_context(market_key)
        results = run_specialists_core(hist, agg, futures, kctx)
        results = _genericize_specialist_text(results, cfg, kctx)
        decision = _decision(results, market_key, kctx)
        price = float(hist["close"].iloc[-1])
        target = _safe_float(kctx.get("target"))
        forecast = forecast_path_core(
            hist.tail(90)[["open", "high", "low", "close", "volume"]].to_dict("records"),
            target if pd.notna(target) else None,
            {},
        ) or {}
    except Exception as exc:
        st.error(f"{cfg['display_symbol']} live command center could not load: {exc}")
        st.caption(f"Configured resource: {cfg['source']}. The dashboard will not invent replacement prices.")
        return

    st.caption(
        f"Live source: {cfg['source']} • {meta.get('exchange', '')} • "
        f"feed {meta.get('latency_ms', 0):.0f} ms • market state {meta.get('market_state', 'UNKNOWN')}"
    )

    cols = st.columns(5)
    card_values = [
        ("LIVE PRICE", _fmt_price(price, cfg)),
        ("MASTER DECISION", _badge(decision["action"])),
        ("CONFIDENCE", f"{decision['confidence']:.1%}"),
        ("CONSENSUS", f"{decision['consensus']:.1%}"),
        ("15M PROJECTED", _fmt_price(_safe_float(forecast.get("predicted_end")), cfg)),
    ]
    for col, (label, value) in zip(cols, card_values):
        with col:
            st.markdown(
                f'<div class="asset-card"><div class="asset-label">{label}</div><div class="asset-value">{value}</div></div>',
                unsafe_allow_html=True,
            )

    if kctx.get("available"):
        prob = _safe_float(kctx.get("up_probability"))
        prob_text = f"{prob:.1%}" if pd.notna(prob) else "N/A"
        st.success(
            f"Kalshi linked: {kctx.get('title') or kctx.get('ticker')} • "
            f"UP market {prob_text} • target {_fmt_price(target, cfg) if pd.notna(target) else 'not parsed'}"
        )
    elif market_key == "zec":
        st.warning("Kalshi ZEC context: unavailable. ZEC price/flow comes from Binance; Kalshi is not fabricated.")
    else:
        st.warning(f"Kalshi context not matched right now: {kctx.get('reason', 'unavailable')}")

    market_tab, council_tab, flow_tab, paper_tab, diag_tab = st.tabs(
        ["Market", "AI Council", "Order Flow", "Paper Trading", "Diagnostics"]
    )

    with market_tab:
        st.plotly_chart(
            _chart(hist, cfg, forecast=forecast.get("forecast"), target=target),
            use_container_width=True,
            config={"displaylogo": False, "scrollZoom": True},
        )
        m1, m2, m3, m4 = st.columns(4)
        last = hist.iloc[-1]
        m1.metric("RSI 14", f"{_safe_float(last['rsi'], 50):.1f}")
        m2.metric("EMA 9", _fmt_price(_safe_float(last["ema9"]), cfg))
        m3.metric("EMA 21", _fmt_price(_safe_float(last["ema21"]), cfg))
        atr_pct = _safe_float(last["atr14"] / price, 0.0)
        m4.metric("ATR / price", f"{atr_pct:.3%}")

    with council_tab:
        rows = []
        active_names = set(BASE_SPECIALISTS)
        if kctx.get("available"):
            active_names.add("Kalshi Context AI")
        if market_key == "zec":
            active_names.update(["Whale AI", "Liquidity AI"])
        for name, result in results.items():
            enabled = name in active_names
            rows.append({
                "Specialist": name,
                "Signal": result.get("signal"),
                "Score": round(_safe_float(result.get("score"), 0.0), 3),
                "Confidence": f"{_safe_float(result.get('confidence'), 0.0):.1%}",
                "Used": "YES" if enabled else "NO — source unavailable",
                "Reason": result.get("reason"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.info(
            f"{decision['active_specialists']} specialists are contributing to the {cfg['display_symbol']} master vote. "
            "Unavailable flow/derivatives bots do not get treated as neutral evidence."
        )

    with flow_tab:
        if market_key == "zec" and agg is not None and not agg.empty:
            buy = agg.loc[agg["aggressor"] == "BUY", "notional"].sum()
            sell = agg.loc[agg["aggressor"] == "SELL", "notional"].sum()
            total = buy + sell
            c1, c2, c3 = st.columns(3)
            c1.metric("Aggressive buy", f"${buy:,.0f}")
            c2.metric("Aggressive sell", f"${sell:,.0f}")
            c3.metric("Buy pressure", f"{(buy/total if total else .5):.1%}")
            st.metric("Spot book imbalance", f"{_safe_float(futures.get('book_imbalance'), 0.0):+.1%}")
        else:
            st.info(
                f"{cfg['display_symbol']} uses its futures OHLCV feed for the council. "
                "A trustworthy real-time aggressor/order-book feed is not currently wired, so Whale/Liquidity/Derivatives "
                "are excluded rather than filled with fake zeroes."
            )

    with paper_tab:
        _paper_panel(market_key, price, decision)

    with diag_tab:
        st.json({
            "asset": cfg["display_symbol"],
            "market_source": cfg["source"],
            "market_latency_ms": round(_safe_float(meta.get("latency_ms"), 0.0), 1),
            "kalshi_available": bool(kctx.get("available")),
            "kalshi_ticker": kctx.get("ticker"),
            "kalshi_latency_ms": _safe_float(kctx.get("latency_ms")),
            "active_specialists": decision["active_specialists"],
            "master_score": round(decision["score"], 4),
            "confidence": round(decision["confidence"], 4),
            "consensus": round(decision["consensus"], 4),
            "auto_paper_trading": False,
            "real_money_execution": False,
        })
