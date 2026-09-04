import json
import math
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ============================================================
# BTC AI TRADING COMMAND CENTER — PAPER TRADING ONLY
# Single-file build. No exchange keys. No live order endpoints.
# ============================================================

st.set_page_config(
    page_title="BTC AI Trading Command Center",
    page_icon="₿",
    layout="wide",
    initial_sidebar_state="expanded",
)

SYMBOL = "BTCUSDT"
SPOT_BASES = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
]
FUTURES_BASES = [
    "https://fapi.binance.com",
]
KALSHI_BASES = [
    "https://external-api.kalshi.com/trade-api/v2",
]
DB_PATH = "btc_ai_command_center.db"
STARTING_CASH = 100_000.0
PREDICTION_HORIZON_MIN = 15
APP_VERSION = "2026.09.04-single-file"

SPECIALIST_WEIGHTS = {
    "Trend AI": 1.15,
    "Momentum AI": 1.05,
    "Volume AI": 0.80,
    "Pattern AI": 0.70,
    "Support/Resistance AI": 0.85,
    "Volatility AI": 0.65,
    "Market Regime AI": 0.95,
    "Whale AI": 0.90,
    "Liquidity AI": 0.90,
    "Derivatives AI": 0.85,
    "Event AI": 0.55,
    "Historical Pattern AI": 0.75,
    "Combination AI": 1.25,
}

# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    [data-testid="stMetricValue"] {font-size: 1.55rem;}
    .paper-banner {
        padding: 0.7rem 1rem; border: 1px solid rgba(255,255,255,.15);
        border-radius: 10px; margin-bottom: 0.8rem; font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# GENERIC HELPERS
# ============================================================


def utc_now():
    return datetime.now(timezone.utc)


def clamp(x, lo=-1.0, hi=1.0):
    try:
        return float(max(lo, min(hi, x)))
    except Exception:
        return 0.0


def safe_float(x, default=np.nan):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def fmt_money(x):
    return "N/A" if pd.isna(x) else f"${x:,.2f}"


def fmt_pct(x, digits=2):
    return "N/A" if pd.isna(x) else f"{x:.{digits}f}%"


def http_json(url, params=None, timeout=2.8):
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 BTC-AI-Command-Center/1.0",
            "Accept": "application/json",
        },
    )
    started = time.perf_counter()
    with urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.perf_counter() - started) * 1000.0


def try_bases(bases, endpoint, params=None, timeout=2.8):
    last_error = None
    for base in bases:
        try:
            return http_json(base.rstrip("/") + endpoint, params=params, timeout=timeout)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(str(last_error) if last_error else "All data endpoints failed")

# ============================================================
# DATABASE
# ============================================================


def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_ts INTEGER NOT NULL,
                created_iso TEXT NOT NULL,
                target_ts INTEGER NOT NULL,
                price REAL NOT NULL,
                action TEXT NOT NULL,
                score REAL NOT NULL,
                confidence REAL NOT NULL,
                consensus REAL NOT NULL,
                target_price REAL,
                rationale TEXT,
                resolved INTEGER NOT NULL DEFAULT 0,
                resolved_price REAL,
                return_pct REAL,
                correct INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id=1),
                cash REAL NOT NULL,
                btc REAL NOT NULL,
                starting_equity REAL NOT NULL,
                updated_iso TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_iso TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL NOT NULL,
                btc_qty REAL NOT NULL,
                notional REAL NOT NULL,
                cash_after REAL NOT NULL,
                btc_after REAL NOT NULL,
                note TEXT
            )
            """
        )
        row = conn.execute("SELECT id FROM paper_account WHERE id=1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO paper_account(id,cash,btc,starting_equity,updated_iso) VALUES(1,?,?,?,?)",
                (STARTING_CASH, 0.0, STARTING_CASH, utc_now().isoformat()),
            )
        conn.commit()


def get_account(price):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
    cash = float(row["cash"])
    btc = float(row["btc"])
    start = float(row["starting_equity"])
    equity = cash + btc * price
    return {
        "cash": cash,
        "btc": btc,
        "starting_equity": start,
        "equity": equity,
        "pnl": equity - start,
        "return_pct": ((equity / start) - 1) * 100 if start else 0.0,
    }


def reset_account():
    with db_conn() as conn:
        conn.execute(
            "UPDATE paper_account SET cash=?, btc=0, starting_equity=?, updated_iso=? WHERE id=1",
            (STARTING_CASH, STARTING_CASH, utc_now().isoformat()),
        )
        conn.execute("DELETE FROM paper_trades")
        conn.commit()


def execute_paper_trade(action, price, position_pct, note=""):
    if action not in {"BUY", "SELL"}:
        return {"ok": False, "message": "No paper trade: master decision is HOLD."}
    if price <= 0 or not math.isfinite(price):
        return {"ok": False, "message": "No paper trade: invalid BTC price."}

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        cash, btc = float(row["cash"]), float(row["btc"])
        pct = max(0.0, min(0.25, float(position_pct)))

        if action == "BUY":
            notional = cash * pct
            if notional < 10:
                return {"ok": False, "message": "No paper trade: paper cash allocation is too small."}
            qty = notional / price
            cash -= notional
            btc += qty
            signed_qty = qty
        else:
            qty = btc * max(pct, 0.25)
            qty = min(qty, btc)
            if qty * price < 10:
                return {"ok": False, "message": "No paper trade: no meaningful paper BTC position to sell."}
            notional = qty * price
            cash += notional
            btc -= qty
            signed_qty = -qty

        conn.execute(
            "UPDATE paper_account SET cash=?, btc=?, updated_iso=? WHERE id=1",
            (cash, btc, utc_now().isoformat()),
        )
        conn.execute(
            """INSERT INTO paper_trades
               (created_iso,action,price,btc_qty,notional,cash_after,btc_after,note)
               VALUES(?,?,?,?,?,?,?,?)""",
            (utc_now().isoformat(), action, price, signed_qty, notional, cash, btc, note),
        )
        conn.commit()
    return {"ok": True, "message": f"Paper {action}: {abs(signed_qty):.6f} BTC at ${price:,.2f}."}

# ============================================================
# MARKET DATA — FAST CACHE
# ============================================================


@st.cache_data(ttl=1, show_spinner=False)
def fetch_spot_ticker():
    payload, ms = try_bases(SPOT_BASES, "/api/v3/ticker/24hr", {"symbol": SYMBOL}, timeout=2.2)
    return {
        "price": safe_float(payload.get("lastPrice")),
        "change_24h": safe_float(payload.get("priceChangePercent")),
        "volume_btc_24h": safe_float(payload.get("volume")),
        "quote_volume_24h": safe_float(payload.get("quoteVolume")),
        "feed_ms": ms,
        "source": "Binance Spot",
    }


@st.cache_data(ttl=2, show_spinner=False)
def fetch_klines(interval="1m", limit=500):
    rows, ms = try_bases(
        SPOT_BASES,
        "/api/v3/klines",
        {"symbol": SYMBOL, "interval": interval, "limit": int(limit)},
        timeout=3.0,
    )
    cols = [
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    for col in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base", "taker_buy_quote"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trades"] = pd.to_numeric(df["trades"], errors="coerce")
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df, ms


@st.cache_data(ttl=1, show_spinner=False)
def fetch_agg_trades(limit=600):
    rows, ms = try_bases(
        SPOT_BASES,
        "/api/v3/aggTrades",
        {"symbol": SYMBOL, "limit": int(limit)},
        timeout=2.4,
    )
    if not rows:
        return pd.DataFrame(), ms
    df = pd.DataFrame(rows)
    df["price"] = pd.to_numeric(df.get("p"), errors="coerce")
    df["qty"] = pd.to_numeric(df.get("q"), errors="coerce")
    df["notional"] = df["price"] * df["qty"]
    # Binance m=True means buyer was maker, therefore trade aggressor was seller.
    df["aggressor"] = np.where(df.get("m", False), "SELL", "BUY")
    df["time"] = pd.to_datetime(df.get("T"), unit="ms", utc=True, errors="coerce")
    return df, ms

# ============================================================
# SLOWER DATA — SEPARATE CACHE WINDOWS
# ============================================================


@st.cache_data(ttl=5, show_spinner=False)
def fetch_futures_snapshot():
    out = {
        "funding_rate": np.nan,
        "mark_price": np.nan,
        "open_interest": np.nan,
        "bid_notional": np.nan,
        "ask_notional": np.nan,
        "book_imbalance": 0.0,
        "feed_ms": np.nan,
        "ok": False,
    }
    started = time.perf_counter()
    try:
        premium, _ = try_bases(FUTURES_BASES, "/fapi/v1/premiumIndex", {"symbol": SYMBOL}, timeout=2.2)
        oi, _ = try_bases(FUTURES_BASES, "/fapi/v1/openInterest", {"symbol": SYMBOL}, timeout=2.2)
        depth, _ = try_bases(FUTURES_BASES, "/fapi/v1/depth", {"symbol": SYMBOL, "limit": 50}, timeout=2.2)
        bids = sum(float(p) * float(q) for p, q in depth.get("bids", []))
        asks = sum(float(p) * float(q) for p, q in depth.get("asks", []))
        denom = bids + asks
        out.update({
            "funding_rate": safe_float(premium.get("lastFundingRate"), 0.0),
            "mark_price": safe_float(premium.get("markPrice")),
            "open_interest": safe_float(oi.get("openInterest")),
            "bid_notional": bids,
            "ask_notional": asks,
            "book_imbalance": (bids - asks) / denom if denom else 0.0,
            "ok": True,
        })
    except Exception as exc:
        out["error"] = str(exc)
    out["feed_ms"] = (time.perf_counter() - started) * 1000.0
    return out


@st.cache_data(ttl=30, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
    """Public read-only Kalshi market lookup. Never places orders."""
    errors = []
    for base in KALSHI_BASES:
        try:
            payload, ms = http_json(
                base + "/markets",
                {"limit": 100, "status": "open", "series_ticker": "KXBTC15M"},
                timeout=3.0,
            )
            markets = payload.get("markets", []) if isinstance(payload, dict) else []
            hits = []
            for m in markets:
                text = " ".join(
                    str(m.get(k, ""))
                    for k in ["ticker", "title", "subtitle", "event_ticker", "yes_sub_title", "no_sub_title"]
                ).lower()
                if any(word in text for word in ["bitcoin", "btc"]):
                    hits.append(m)
            return {"ok": True, "markets": hits[:25], "feed_ms": ms, "error": None}
        except Exception as exc:
            errors.append(str(exc))
    return {"ok": False, "markets": [], "feed_ms": np.nan, "error": " | ".join(errors[-2:])}

# ============================================================
# INDICATORS
# ============================================================


def enrich_history(df):
    x = df.copy()
    c = x["close"]
    x["ret1"] = c.pct_change()
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema21"] = c.ewm(span=21, adjust=False).mean()
    x["ema50"] = c.ewm(span=50, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["vol20"] = x["ret1"].rolling(20).std() * np.sqrt(20)
    x["sma20"] = c.rolling(20).mean()
    x["std20"] = c.rolling(20).std()
    x["bb_upper"] = x["sma20"] + 2 * x["std20"]
    x["bb_lower"] = x["sma20"] - 2 * x["std20"]
    x["volume_ma20"] = x["volume"].rolling(20).mean()
    x["volume_z"] = (x["volume"] - x["volume_ma20"]) / x["volume"].rolling(20).std().replace(0, np.nan)
    x["high20"] = x["high"].rolling(20).max()
    x["low20"] = x["low"].rolling(20).min()
    tr = pd.concat(
        [
            x["high"] - x["low"],
            (x["high"] - c.shift()).abs(),
            (x["low"] - c.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr14"] = tr.rolling(14).mean()
    return x


def specialist(name, score, reason):
    score = clamp(score)
    if score > 0.12:
        signal = "BULLISH"
    elif score < -0.12:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    confidence = min(0.99, 0.48 + abs(score) * 0.48)
    return {"name": name, "signal": signal, "score": score, "confidence": confidence, "reason": reason}


def run_specialists(hist, agg, futures, kalshi):
    last = hist.iloc[-1]
    prev = hist.iloc[-2]
    px = float(last["close"])
    out = {}

    # Trend
    trend_score = 0.55 * np.sign(last["ema9"] - last["ema21"]) + 0.45 * np.sign(last["ema21"] - last["ema50"])
    out["Trend AI"] = specialist("Trend AI", trend_score, f"EMA9 {last['ema9']:.0f}, EMA21 {last['ema21']:.0f}, EMA50 {last['ema50']:.0f}")

    # Momentum
    rsi = safe_float(last["rsi"], 50.0)
    macd_delta = safe_float(last["macd"] - last["macd_signal"], 0.0)
    momentum = clamp(((rsi - 50) / 30) * 0.55 + np.sign(macd_delta) * min(abs(macd_delta) / max(px * 0.0005, 1), 1) * 0.45)
    out["Momentum AI"] = specialist("Momentum AI", momentum, f"RSI {rsi:.1f}; MACD spread {macd_delta:.2f}")

    # Volume
    volume_z = safe_float(last["volume_z"], 0.0)
    candle_dir = np.sign(last["close"] - last["open"])
    volume_score = clamp(candle_dir * min(abs(volume_z) / 2.5, 1.0))
    out["Volume AI"] = specialist("Volume AI", volume_score, f"Volume z-score {volume_z:.2f}")

    # Pattern
    body = last["close"] - last["open"]
    rng = max(last["high"] - last["low"], 1e-9)
    prev_body = prev["close"] - prev["open"]
    engulf = 0.0
    if body > 0 and prev_body < 0 and last["close"] >= prev["open"] and last["open"] <= prev["close"]:
        engulf = 1.0
    elif body < 0 and prev_body > 0 and last["open"] >= prev["close"] and last["close"] <= prev["open"]:
        engulf = -1.0
    pattern_score = clamp(0.55 * (body / rng) + 0.45 * engulf)
    out["Pattern AI"] = specialist("Pattern AI", pattern_score, "Candle body/engulfing structure")

    # Support / resistance
    support = safe_float(hist["low"].tail(60).min(), px)
    resistance = safe_float(hist["high"].tail(60).max(), px)
    span = max(resistance - support, px * 0.001)
    location = (px - support) / span
    sr_score = clamp((0.5 - location) * 1.4)
    out["Support/Resistance AI"] = specialist("Support/Resistance AI", sr_score, f"Support ${support:,.0f}; resistance ${resistance:,.0f}")

    # Volatility
    atr_pct = safe_float(last["atr14"] / px, 0.0)
    bb_mid = safe_float(last["sma20"], px)
    stretch = (px - bb_mid) / max(safe_float(last["std20"], px * 0.001), px * 0.001)
    vol_score = clamp(-stretch / 3.0) if atr_pct > 0.0015 else clamp(np.sign(last["ema9"] - last["ema21"]) * 0.25)
    out["Volatility AI"] = specialist("Volatility AI", vol_score, f"ATR {atr_pct*100:.3f}% of price; BB stretch {stretch:.2f}")

    # Regime
    ema_spread = abs(last["ema9"] - last["ema50"]) / px
    regime_dir = np.sign(last["ema9"] - last["ema50"])
    regime_score = clamp(regime_dir * min(ema_spread / 0.003, 1.0))
    out["Market Regime AI"] = specialist("Market Regime AI", regime_score, "Trend regime from EMA separation")

    # Whale / AGGR-style order flow
    if agg is not None and not agg.empty:
        buy = agg.loc[agg["aggressor"] == "BUY", "notional"].sum()
        sell = agg.loc[agg["aggressor"] == "SELL", "notional"].sum()
        total = buy + sell
        flow = (buy - sell) / total if total else 0.0
        med = agg["notional"].median()
        whales = agg[agg["notional"] >= max(med * 6, 50_000)]
        whale_buy = whales.loc[whales["aggressor"] == "BUY", "notional"].sum()
        whale_sell = whales.loc[whales["aggressor"] == "SELL", "notional"].sum()
        whale_total = whale_buy + whale_sell
        whale_flow = (whale_buy - whale_sell) / whale_total if whale_total else flow
        whale_score = clamp(0.55 * flow * 3 + 0.45 * whale_flow * 3)
        whale_reason = f"Aggressor flow {flow*100:+.1f}%; large-trade flow {whale_flow*100:+.1f}%"
    else:
        whale_score, whale_reason = 0.0, "Aggregate trade feed unavailable"
    out["Whale AI"] = specialist("Whale AI", whale_score, whale_reason)

    # Liquidity
    book = safe_float(futures.get("book_imbalance", 0.0), 0.0)
    out["Liquidity AI"] = specialist("Liquidity AI", clamp(book * 3), f"Futures top-book imbalance {book*100:+.1f}%")

    # Derivatives
    funding = safe_float(futures.get("funding_rate"), 0.0)
    deriv_score = clamp(book * 1.6 - np.sign(funding) * min(abs(funding) / 0.0005, 1.0) * 0.25)
    out["Derivatives AI"] = specialist("Derivatives AI", deriv_score, f"Funding {funding*100:.4f}%; OI {safe_float(futures.get('open_interest'), 0):,.0f} BTC")

    # Event / Kalshi
    km = kalshi.get("markets", []) if kalshi else []
    probs = []
    for m in km:
        yes = m.get("yes_ask_dollars", m.get("yes_bid_dollars", m.get("last_price_dollars")))
        v = safe_float(yes)
        if pd.notna(v):
            probs.append(v)
    event_score = clamp((np.mean(probs) - 0.5) * 1.2) if probs else 0.0
    out["Event AI"] = specialist("Event AI", event_score, f"{len(km)} open BTC-related Kalshi markets found")

    # Historical pattern
    rets = hist["ret1"].dropna()
    recent3 = safe_float((hist["close"].iloc[-1] / hist["close"].iloc[-4] - 1), 0.0) if len(hist) >= 4 else 0.0
    future_proxy = rets.shift(-15)
    similar = hist.loc[(hist["ret1"] - recent3 / 3).abs() < max(rets.std() * 0.35, 1e-6)]
    hist_score = clamp(np.sign(recent3) * min(abs(recent3) / 0.003, 1.0) * 0.5)
    out["Historical Pattern AI"] = specialist("Historical Pattern AI", hist_score, f"Recent 3-minute move {recent3*100:+.3f}%")

    # Combination / interaction
    base_names = [k for k in out.keys() if k not in {"Event AI"}]
    base_scores = np.array([out[k]["score"] for k in base_names], dtype=float)
    agreement = abs(np.mean(np.sign(base_scores))) if len(base_scores) else 0.0
    combo = clamp(np.mean(base_scores) * (0.8 + 0.5 * agreement)) if len(base_scores) else 0.0
    out["Combination AI"] = specialist("Combination AI", combo, f"Cross-specialist directional agreement {agreement*100:.0f}%")
    return out

# ============================================================
# MASTER AI + RISK
# ============================================================


def master_decision(results, hist):
    weighted_sum = 0.0
    total_weight = 0.0
    signs = []
    for name, result in results.items():
        weight = SPECIALIST_WEIGHTS.get(name, 1.0)
        weighted_sum += result["score"] * result["confidence"] * weight
        total_weight += result["confidence"] * weight
        signs.append(np.sign(result["score"]))
    score = clamp(weighted_sum / total_weight if total_weight else 0.0)
    directional = [s for s in signs if s != 0]
    consensus = abs(sum(directional)) / len(directional) if directional else 0.0
    confidence = min(0.97, max(0.45, 0.48 + abs(score) * 0.34 + consensus * 0.15))

    if score >= 0.16 and confidence >= 0.58:
        action = "BUY"
    elif score <= -0.16 and confidence >= 0.58:
        action = "SELL"
    else:
        action = "HOLD"

    px = float(hist["close"].iloc[-1])
    atr = safe_float(hist["atr14"].iloc[-1], px * 0.002)
    target_move = max(atr * 1.2, px * 0.0015) * score
    target_price = px + target_move
    risk_level = "LOW" if confidence > 0.78 and consensus > 0.55 else "MEDIUM" if confidence > 0.62 else "HIGH"

    strongest = sorted(results.values(), key=lambda r: abs(r["score"] * r["confidence"]), reverse=True)[:3]
    reason = "; ".join(f"{r['name']}: {r['signal']} ({r['score']:+.2f})" for r in strongest)
    return {
        "action": action,
        "score": score,
        "confidence": confidence,
        "consensus": consensus,
        "target_price": target_price,
        "risk_level": risk_level,
        "reason": reason,
    }


def risk_evaluate(decision, account, hist, futures):
    px = float(hist["close"].iloc[-1])
    atr_pct = safe_float(hist["atr14"].iloc[-1] / px, 0.003)
    confidence = decision["confidence"]
    consensus = decision["consensus"]

    if decision["action"] == "HOLD":
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "HOLD signal"}
    if confidence < 0.62:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.9, "reason": "Confidence below 62%"}
    if consensus < 0.30:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.8, "reason": "Specialist consensus too low"}

    volatility_penalty = min(0.55, max(0.0, (atr_pct - 0.002) * 100))
    base = 0.04 + (confidence - 0.60) * 0.22 + consensus * 0.04
    position_pct = max(0.02, min(0.15, base * (1 - volatility_penalty)))
    risk_score = clamp(0.6 - confidence * 0.35 - consensus * 0.15 + volatility_penalty, 0, 1)

    if decision["action"] == "SELL" and account["btc"] * px < 10:
        return {"approved": False, "position_pct": 0.0, "risk_score": risk_score, "reason": "No paper BTC position to sell"}

    return {"approved": True, "position_pct": position_pct, "risk_score": risk_score, "reason": "Paper-trade risk checks passed"}

# ============================================================
# PREDICTION JOURNAL
# ============================================================


def maybe_record_prediction(decision, price, min_seconds=60):
    now_ts = int(time.time())
    with db_conn() as conn:
        row = conn.execute("SELECT created_ts FROM predictions ORDER BY id DESC LIMIT 1").fetchone()
        if row and now_ts - int(row["created_ts"]) < min_seconds:
            return False
        conn.execute(
            """INSERT INTO predictions
               (created_ts,created_iso,target_ts,price,action,score,confidence,consensus,target_price,rationale)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                now_ts,
                utc_now().isoformat(),
                now_ts + PREDICTION_HORIZON_MIN * 60,
                price,
                decision["action"],
                decision["score"],
                decision["confidence"],
                decision["consensus"],
                decision["target_price"],
                decision["reason"],
            ),
        )
        conn.commit()
    return True


def resolve_predictions(current_price):
    now_ts = int(time.time())
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE resolved=0 AND target_ts<=? ORDER BY id ASC LIMIT 100",
            (now_ts,),
        ).fetchall()
        for row in rows:
            start_price = float(row["price"])
            ret = (current_price / start_price - 1) * 100
            action = row["action"]
            if action == "BUY":
                correct = int(current_price > start_price)
            elif action == "SELL":
                correct = int(current_price < start_price)
            else:
                correct = int(abs(ret) < 0.15)
            conn.execute(
                "UPDATE predictions SET resolved=1,resolved_price=?,return_pct=?,correct=? WHERE id=?",
                (current_price, ret, correct, int(row["id"])),
            )
        conn.commit()
    return len(rows)


def recent_predictions(limit=100):
    with db_conn() as conn:
        df = pd.read_sql_query(
            """SELECT id,created_iso,action,price,target_price,score,confidence,consensus,
                      resolved,resolved_price,return_pct,correct
               FROM predictions ORDER BY id DESC LIMIT ?""",
            conn,
            params=(int(limit),),
        )
    if not df.empty:
        df["confidence"] = (df["confidence"] * 100).round(1)
        df["consensus"] = (df["consensus"] * 100).round(1)
        df["score"] = df["score"].round(3)
        df["return_pct"] = df["return_pct"].round(3)
    return df


def prediction_stats():
    with db_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved_n,
                      SUM(CASE WHEN resolved=1 AND correct=1 THEN 1 ELSE 0 END) AS correct_n,
                      AVG(CASE WHEN resolved=1 THEN ABS(return_pct) END) AS avg_abs_move
               FROM predictions"""
        ).fetchone()
    n = int(row["n"] or 0)
    resolved_n = int(row["resolved_n"] or 0)
    correct_n = int(row["correct_n"] or 0)
    return {
        "n": n,
        "resolved": resolved_n,
        "accuracy": correct_n / resolved_n if resolved_n else np.nan,
        "avg_abs_move": safe_float(row["avg_abs_move"]),
    }

# ============================================================
# WALK-FORWARD BACKTEST
# ============================================================


def walk_forward_backtest(hist, horizon=15):
    x = hist.copy().dropna(subset=["ema9", "ema21", "rsi", "close"])
    if len(x) < 100:
        return pd.DataFrame(), {}
    x["signal"] = 0
    x.loc[(x["ema9"] > x["ema21"]) & (x["rsi"] > 52), "signal"] = 1
    x.loc[(x["ema9"] < x["ema21"]) & (x["rsi"] < 48), "signal"] = -1
    x["future_return"] = x["close"].shift(-horizon) / x["close"] - 1
    test = x.iloc[80:-horizon].copy()
    test = test[test["signal"] != 0]
    if test.empty:
        return test, {}
    test["strategy_return"] = test["signal"] * test["future_return"]
    test["correct"] = (test["strategy_return"] > 0).astype(int)
    stats = {
        "trades": len(test),
        "win_rate": test["correct"].mean(),
        "avg_return": test["strategy_return"].mean(),
        "median_return": test["strategy_return"].median(),
        "total_compound": (1 + test["strategy_return"]).prod() - 1,
    }
    return test, stats

# ============================================================
# CHARTS
# ============================================================


def candle_chart(hist):
    tail = hist.tail(180)
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=tail["time"],
            open=tail["open"],
            high=tail["high"],
            low=tail["low"],
            close=tail["close"],
            name="BTC",
        )
    )
    fig.add_trace(go.Scatter(x=tail["time"], y=tail["ema9"], name="EMA 9", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=tail["time"], y=tail["ema21"], name="EMA 21", line=dict(width=1)))
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False, legend_orientation="h")
    return fig

# ============================================================
# STARTUP
# ============================================================

init_db()

st.title("₿ BTC AI Trading Command Center")
st.markdown('<div class="paper-banner">PAPER TRADING ONLY — no real-money execution code or exchange keys are included.</div>', unsafe_allow_html=True)
st.caption(f"Single-file build {APP_VERSION} • 15-minute prediction engine • specialist council • journal • backtest • Kalshi read-only signal")

# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("Command Center")
auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
refresh_seconds = st.sidebar.select_slider("Dashboard refresh", options=[1, 2, 3, 5, 10, 15, 30, 60], value=3)
record_predictions = st.sidebar.checkbox("Auto-journal predictions", value=True)
show_raw = st.sidebar.checkbox("Show diagnostics", value=False)

st.sidebar.divider()
st.sidebar.subheader("Safety")
st.sidebar.warning("Paper trading only. This app intentionally contains no live order endpoint and asks for no exchange API key.")
if st.sidebar.button("Reset paper account", use_container_width=True):
    reset_account()
    st.sidebar.success("Paper account reset.")
    st.rerun()

# ============================================================
# FETCH DATA
# ============================================================

load_started = time.perf_counter()
errors = []

try:
    ticker = fetch_spot_ticker()
except Exception as exc:
    ticker = {"price": np.nan, "change_24h": np.nan, "quote_volume_24h": np.nan, "feed_ms": np.nan, "source": "Unavailable"}
    errors.append(f"Spot ticker: {exc}")

try:
    raw_hist, kline_ms = fetch_klines("1m", 500)
    hist = enrich_history(raw_hist)
except Exception as exc:
    hist, kline_ms = pd.DataFrame(), np.nan
    errors.append(f"Klines: {exc}")

try:
    agg, agg_ms = fetch_agg_trades(600)
except Exception as exc:
    agg, agg_ms = pd.DataFrame(), np.nan
    errors.append(f"Aggregate trades: {exc}")

futures = fetch_futures_snapshot()
kalshi = fetch_kalshi_bitcoin_markets()

if hist.empty:
    st.error("Price history is unavailable, so the AI engine cannot run safely right now.")
    if errors:
        st.code("\n".join(errors))
    st.stop()

price = safe_float(ticker.get("price"), safe_float(hist["close"].iloc[-1]))
if pd.isna(price):
    price = float(hist["close"].iloc[-1])

results = run_specialists(hist, agg, futures, kalshi)
decision = master_decision(results, hist)
account = get_account(price)
risk = risk_evaluate(decision, account, hist, futures)

if record_predictions:
    maybe_record_prediction(decision, price, min_seconds=60)
resolve_predictions(price)

full_cycle_ms = (time.perf_counter() - load_started) * 1000

# ============================================================
# TOP METRICS
# ============================================================

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("BTC", fmt_money(price))
m2.metric("24h", fmt_pct(ticker.get("change_24h")))
m3.metric("Master", decision["action"])
m4.metric("Confidence", f"{decision['confidence']*100:.1f}%")
m5.metric("Consensus", f"{decision['consensus']*100:.1f}%")
m6.metric("Spot feed", "N/A" if pd.isna(ticker.get("feed_ms")) else f"{ticker['feed_ms']:.0f} ms")

st.caption(
    f"Dashboard cycle {full_cycle_ms:.0f} ms • kline request {kline_ms:.0f} ms • agg-trade request {agg_ms:.0f} ms • "
    f"futures snapshot {futures.get('feed_ms', np.nan):.0f} ms • Kalshi cache 30s"
)

# ============================================================
# TABS
# ============================================================

tab_market, tab_ai, tab_flow, tab_paper, tab_journal, tab_backtest = st.tabs(
    ["Market", "AI Council", "Order Flow + Kalshi", "Paper Trading", "Prediction Journal", "Backtest"]
)

with tab_market:
    st.plotly_chart(candle_chart(hist), use_container_width=True)
    c1, c2, c3, c4 = st.columns(4)
    last = hist.iloc[-1]
    c1.metric("RSI 14", f"{safe_float(last['rsi'], 50):.1f}")
    c2.metric("ATR 14", f"${safe_float(last['atr14'], 0):,.2f}")
    c3.metric("24h quote volume", f"${safe_float(ticker.get('quote_volume_24h'), 0):,.0f}")
    c4.metric("Target (15m)", fmt_money(decision["target_price"]))

with tab_ai:
    st.subheader("Master 15-minute Prediction AI")
    d1, d2, d3, d4, d5 = st.columns(5)
    d1.metric("Action", decision["action"])
    d2.metric("Master score", f"{decision['score']:+.3f}")
    d3.metric("Confidence", f"{decision['confidence']*100:.1f}%")
    d4.metric("Consensus", f"{decision['consensus']*100:.1f}%")
    d5.metric("Risk level", decision["risk_level"])
    st.info(decision["reason"])

    rows = []
    for r in results.values():
        rows.append({
            "Specialist": r["name"],
            "Signal": r["signal"],
            "Score": round(r["score"], 3),
            "Confidence %": round(r["confidence"] * 100, 1),
            "Weight": SPECIALIST_WEIGHTS.get(r["name"], 1.0),
            "Reason": r["reason"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tab_flow:
    st.subheader("AGGR-style aggressor flow")
    st.caption("This uses Binance aggregate trades directly—the underlying aggressor/order-flow data—rather than scraping the AGGR.trade webpage.")
    if not agg.empty:
        buy_n = agg.loc[agg["aggressor"] == "BUY", "notional"].sum()
        sell_n = agg.loc[agg["aggressor"] == "SELL", "notional"].sum()
        total_n = buy_n + sell_n
        imbalance = (buy_n - sell_n) / total_n if total_n else 0.0
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Aggressive buys", f"${buy_n:,.0f}")
        f2.metric("Aggressive sells", f"${sell_n:,.0f}")
        f3.metric("Flow imbalance", f"{imbalance*100:+.1f}%")
        f4.metric("Trades sampled", f"{len(agg):,}")
        show = agg[["time", "aggressor", "price", "qty", "notional"]].tail(80).sort_values("time", ascending=False)
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.warning("Aggregate trade feed unavailable.")

    st.divider()
    st.subheader("Futures liquidity / derivatives")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Funding", f"{safe_float(futures.get('funding_rate'), 0)*100:.4f}%")
    q2.metric("Open interest", f"{safe_float(futures.get('open_interest'), 0):,.0f} BTC")
    q3.metric("Book imbalance", f"{safe_float(futures.get('book_imbalance'), 0)*100:+.1f}%")
    q4.metric("Futures status", "LIVE" if futures.get("ok") else "UNAVAILABLE")

    st.divider()
    st.subheader("Kalshi — read-only BTC event signal")
    if kalshi.get("ok"):
        markets = kalshi.get("markets", [])
        st.caption(f"Public market-data lookup • {len(markets)} BTC-related open markets found • cached for 30 seconds")
        if markets:
            krows = []
            for m in markets:
                krows.append({
                    "Ticker": m.get("ticker", ""),
                    "Title": m.get("title", ""),
                    "Yes bid": m.get("yes_bid_dollars", ""),
                    "Yes ask": m.get("yes_ask_dollars", ""),
                    "Last": m.get("last_price_dollars", ""),
                    "Volume": m.get("volume_fp", ""),
                    "Close": m.get("close_time", ""),
                })
            st.dataframe(pd.DataFrame(krows), use_container_width=True, hide_index=True)
        else:
            st.info("Kalshi responded, but no open market in the returned page matched Bitcoin/BTC right now.")
    else:
        st.warning("Kalshi public data is currently unavailable. The Event AI automatically falls back to neutral.")
        if show_raw:
            st.code(kalshi.get("error", "Unknown Kalshi error"))

with tab_paper:
    st.subheader("Paper Trading Account")
    account = get_account(price)
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Cash", fmt_money(account["cash"]))
    a2.metric("BTC", f"{account['btc']:.6f}")
    a3.metric("Equity", fmt_money(account["equity"]))
    a4.metric("P&L", fmt_money(account["pnl"]))
    a5.metric("Return", f"{account['return_pct']:+.2f}%")

    st.subheader("Risk Manager")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Approved", "YES" if risk["approved"] else "NO")
    r2.metric("Position size", f"{risk['position_pct']*100:.2f}%")
    r3.metric("Risk score", f"{risk['risk_score']:.2f}")
    r4.metric("Decision", decision["action"])
    st.caption(risk["reason"])

    if st.button("Execute Approved Paper Trade", type="primary", use_container_width=True):
        if risk["approved"]:
            result = execute_paper_trade(
                decision["action"],
                price,
                risk["position_pct"],
                note=f"master={decision['score']:+.3f}, confidence={decision['confidence']:.3f}",
            )
            if result["ok"]:
                st.success(result["message"])
            else:
                st.error(result["message"])
            st.rerun()
        else:
            st.error(f"Paper trade blocked: {risk['reason']}")

    with db_conn() as conn:
        trades = pd.read_sql_query("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 100", conn)
    if not trades.empty:
        st.dataframe(trades, use_container_width=True, hide_index=True)
    else:
        st.info("No paper trades yet.")

with tab_journal:
    stats = prediction_stats()
    j1, j2, j3, j4 = st.columns(4)
    j1.metric("Predictions", stats["n"])
    j2.metric("Resolved", stats["resolved"])
    j3.metric("Accuracy", "N/A" if pd.isna(stats["accuracy"]) else f"{stats['accuracy']*100:.1f}%")
    j4.metric("Avg |15m move|", "N/A" if pd.isna(stats["avg_abs_move"]) else f"{stats['avg_abs_move']:.3f}%")
    journal_df = recent_predictions(150)
    if not journal_df.empty:
        st.dataframe(journal_df, use_container_width=True, hide_index=True)
    else:
        st.info("No predictions recorded yet.")

with tab_backtest:
    st.subheader("Walk-forward Backtest")
    st.caption("This is deliberately not rerun every dashboard refresh. Press the button when you want a fresh historical check.")
    if st.button("Run backtest", use_container_width=True):
        bt, stats = walk_forward_backtest(hist, horizon=PREDICTION_HORIZON_MIN)
        if not stats:
            st.warning("Not enough qualifying historical signals in the current 1-minute window.")
        else:
            b1, b2, b3, b4, b5 = st.columns(5)
            b1.metric("Signals", stats["trades"])
            b2.metric("Win rate", f"{stats['win_rate']*100:.1f}%")
            b3.metric("Avg signal return", f"{stats['avg_return']*100:+.3f}%")
            b4.metric("Median", f"{stats['median_return']*100:+.3f}%")
            b5.metric("Compounded*", f"{stats['total_compound']*100:+.2f}%")
            st.caption("*Compounded figure is diagnostic only; overlapping 15-minute observations make it unsuitable as a live-performance estimate.")
            view = bt[["time", "close", "signal", "future_return", "strategy_return", "correct"]].tail(200).copy()
            view["future_return"] = (view["future_return"] * 100).round(3)
            view["strategy_return"] = (view["strategy_return"] * 100).round(3)
            st.dataframe(view, use_container_width=True, hide_index=True)

# ============================================================
# DIAGNOSTICS / STATUS
# ============================================================

if errors:
    with st.expander("Data warnings"):
        for error in errors:
            st.warning(error)

if show_raw:
    with st.expander("Diagnostics"):
        st.json({
            "ticker": ticker,
            "futures": futures,
            "kalshi_status": {"ok": kalshi.get("ok"), "market_count": len(kalshi.get("markets", [])), "feed_ms": kalshi.get("feed_ms")},
            "decision": decision,
            "risk": risk,
            "full_cycle_ms": full_cycle_ms,
        })

st.divider()
st.caption(
    f"Last update {utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')} • "
    "Safety: PAPER ONLY • no order API keys • no real-money exchange execution."
)

# ============================================================
# AUTO REFRESH
# Expensive sources are cached on separate TTLs, so a fast UI refresh does
# not refetch Kalshi/futures/backtest work every second.
# ============================================================

if auto_refresh:
    time.sleep(refresh_seconds)
    st.rerun()