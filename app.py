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
import streamlit.components.v1 as components

from ai_core import enrich_history_core, forecast_path_core, run_specialists_core

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
APP_VERSION = "2026.09.04-r30-kalshi-sidebar-timer"

REMOTE_LEARNING_URL = (
    "https://raw.githubusercontent.com/"
    "Toddtoddtard/-btc-ai-trading-command-center/"
    "learning-state/learning_state.json"
)
_REMOTE_LEARNING_CACHE = {"ts": 0.0, "data": None}

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
    "Kalshi Context AI": 0.55,
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
    .direction-call {
        display:inline-flex; align-items:center; justify-content:center;
        min-width:116px; padding:7px 13px; border-radius:9px;
        font-weight:800; letter-spacing:.02em; line-height:1;
        border:1px solid transparent; box-shadow:0 0 18px rgba(0,0,0,.12);
        white-space:nowrap;
    }
    .direction-call.compact {min-width:92px; padding:5px 10px; font-size:.9rem;}
    .direction-call.call-up {
        color:#20f0bd; background:rgba(0,230,179,.12);
        border-color:rgba(0,230,179,.72); box-shadow:0 0 14px rgba(0,230,179,.13);
    }
    .direction-call.call-down {
        color:#ff5d72; background:rgba(255,73,100,.12);
        border-color:rgba(255,73,100,.78); box-shadow:0 0 14px rgba(255,73,100,.12);
    }
    .direction-call.call-neutral {
        color:#c2d1e6; background:rgba(140,160,190,.11);
        border-color:rgba(140,160,190,.45);
    }
    .direction-card {
        width:100%; min-height:92px; box-sizing:border-box;
        display:flex; align-items:center; justify-content:center;
        padding:14px 16px; border-radius:13px;
        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
        border:1px solid #1687ff;
        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;
    }
    .direction-card .direction-call {
        min-width:150px; padding:10px 18px; font-size:1.08rem;
    }
    
    .direction-card.metric-direction-card {
        min-height:92px;
        padding:.72rem 1rem;
        flex-direction:column;
        align-items:flex-start;
        justify-content:flex-start;
        gap:.48rem;
    }
    .direction-card-label {
        color:#9fb2ce;
        font-size:.90rem;
        line-height:1.15;
        font-weight:500;
    }
    .direction-card-value {
        width:100%;
        display:flex;
        align-items:center;
        justify-content:center;
        flex:1;
    }
    .direction-card.metric-direction-card .direction-call {
        min-width:min(150px, 100%);
        max-width:100%;
        box-sizing:border-box;
    }
.direction-card.verdict-card {
        width:min(100%, 330px); min-height:82px; justify-content:flex-start;
    }
    .direction-card.verdict-card .direction-call {min-width:165px;}

    /* Prevent Streamlit's "stale" rerun state from dimming live numbers.
       Old values stay fully visible until the new values replace them. */
    [data-stale="true"],
    [data-stale="true"] *,
    .element-container,
    [data-testid="element-container"],
    [data-testid="stMetric"],
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricDelta"] {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
        animation: none !important;
    }

    /* Keep the Market / AI Council / Order Flow / Paper Trading tab bar
       visually frozen while the live fragment updates underneath it. */
    [data-testid="stTabs"],
    [data-testid="stTabs"] *,
    [data-baseweb="tab-list"],
    [data-baseweb="tab-list"] *,
    [data-baseweb="tab"],
    [data-baseweb="tab"] *,
    [role="tablist"],
    [role="tablist"] *,
    [role="tab"],
    [role="tab"] * {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
        animation: none !important;
        -webkit-transition: none !important;
        -webkit-animation: none !important;
    }

    /* Prevent the active-tab underline itself from fading/sliding. */
    [data-baseweb="tab-highlight"],
    [data-baseweb="tab-border"],
    [data-testid="stTabs"] div[role="tablist"] > div {
        transition: none !important;
        animation: none !important;
        opacity: 1 !important;
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


def directional_badge_html(label, compact=False):
    """Visual-only badge for directional calls; does not change decision logic."""
    text = str(label or "HOLD").upper().strip()
    if any(k in text for k in ("LOCK UP", "SCALP UP", "BULLISH")) or text == "UP":
        cls, icon = "call-up", "▲"
    elif any(k in text for k in ("LOCK DOWN", "SCALP DOWN", "BEARISH")) or text == "DOWN":
        cls, icon = "call-down", "▼"
    else:
        cls, icon = "call-neutral", "•"
    size_cls = " compact" if compact else ""
    return f'<span class="direction-call {cls}{size_cls}">{icon}&nbsp;&nbsp;{text}</span>'


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


def fetch_remote_learning_state(ttl=20.0):
    now = time.monotonic()
    cached = _REMOTE_LEARNING_CACHE.get("data")

    if (
        cached is not None
        and now - float(_REMOTE_LEARNING_CACHE.get("ts", 0.0)) < ttl
    ):
        return cached

    try:
        req = Request(
            REMOTE_LEARNING_URL,
            headers={
                "User-Agent": "BTC-AI-Command-Center/24x7-learning",
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
        )
        with urlopen(req, timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if isinstance(payload, dict):
            _REMOTE_LEARNING_CACHE["ts"] = now
            _REMOTE_LEARNING_CACHE["data"] = payload
            return payload
    except Exception:
        pass

    _REMOTE_LEARNING_CACHE["ts"] = now
    return cached if isinstance(cached, dict) else None

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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_paper_state (
                id INTEGER PRIMARY KEY CHECK (id=1),
                enabled INTEGER NOT NULL DEFAULT 0,
                side TEXT NOT NULL DEFAULT 'NONE',
                entry_price REAL,
                entry_ts INTEGER,
                entry_qty REAL,
                stop_loss REAL,
                take_profit REAL,
                last_exit_ts INTEGER NOT NULL DEFAULT 0,
                last_message TEXT NOT NULL DEFAULT ''
            )
            """
        )
        auto_row = conn.execute("SELECT id FROM auto_paper_state WHERE id=1").fetchone()
        if auto_row is None:
            conn.execute(
                """INSERT INTO auto_paper_state
                   (id,enabled,side,entry_price,entry_ts,entry_qty,stop_loss,take_profit,last_exit_ts,last_message)
                   VALUES(1,0,'NONE',NULL,NULL,NULL,NULL,NULL,0,'Auto paper trading ready.')"""
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
        conn.execute(
            """UPDATE auto_paper_state
               SET side='NONE',entry_price=NULL,entry_ts=NULL,entry_qty=NULL,
                   stop_loss=NULL,take_profit=NULL,last_exit_ts=0,
                   last_message='Paper account reset.'
               WHERE id=1"""
        )
        conn.commit()


def get_auto_state():
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM auto_paper_state WHERE id=1").fetchone()
    return dict(row)


def set_auto_enabled(enabled):
    with db_conn() as conn:
        conn.execute(
            "UPDATE auto_paper_state SET enabled=?, last_message=? WHERE id=1",
            (1 if enabled else 0,
             "AUTO PAPER TRADING enabled." if enabled else "AUTO PAPER TRADING disabled."),
        )
        conn.commit()


def _paper_log(conn, action, price, signed_qty, notional, cash, btc, note):
    conn.execute(
        """INSERT INTO paper_trades
           (created_iso,action,price,btc_qty,notional,cash_after,btc_after,note)
           VALUES(?,?,?,?,?,?,?,?)""",
        (utc_now().isoformat(), action, price, signed_qty, notional, cash, btc, note),
    )


def open_paper_position(action, price, position_pct, hist, note=""):
    """Open one paper-only long or short position.

    BUY opens a long. SELL opens a simulated short. No exchange order is sent.
    """
    if action not in {"BUY", "SELL"}:
        return {"ok": False, "message": "No paper trade: master decision is HOLD."}
    if price <= 0 or not math.isfinite(price):
        return {"ok": False, "message": "No paper trade: invalid BTC price."}

    state = get_auto_state()
    if state["side"] != "NONE":
        return {"ok": False, "message": f"Paper position already open: {state['side']}."}

    account = get_account(price)
    pct = max(0.0, min(0.15, float(position_pct)))
    notional = account["equity"] * pct
    if notional < 10:
        return {"ok": False, "message": "No paper trade: paper allocation is too small."}

    qty = notional / price
    atr = safe_float(hist["atr14"].iloc[-1], price * 0.0025)
    stop_distance = max(atr * 1.10, price * 0.0025)
    target_distance = max(atr * 1.55, price * 0.0035)

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        cash, btc = float(row["cash"]), float(row["btc"])

        if abs(btc) * price >= 1.0:
            return {"ok": False, "message": "Paper account already has BTC exposure; reset or close it first."}

        if action == "BUY":
            if cash < notional:
                return {"ok": False, "message": "Not enough paper cash for the approved long."}
            cash -= notional
            btc += qty
            side = "LONG"
            stop_loss = price - stop_distance
            take_profit = price + target_distance
            signed_qty = qty
        else:
            # Simulated short: sale proceeds are credited to paper cash and the
            # BTC balance becomes negative. Equity remains cash + BTC*price.
            cash += notional
            btc -= qty
            side = "SHORT"
            stop_loss = price + stop_distance
            take_profit = price - target_distance
            signed_qty = -qty

        now_ts = int(time.time())
        conn.execute(
            "UPDATE paper_account SET cash=?, btc=?, updated_iso=? WHERE id=1",
            (cash, btc, utc_now().isoformat()),
        )
        _paper_log(
            conn,
            f"OPEN_{side}",
            price,
            signed_qty,
            notional,
            cash,
            btc,
            note,
        )
        conn.execute(
            """UPDATE auto_paper_state
               SET side=?,entry_price=?,entry_ts=?,entry_qty=?,stop_loss=?,take_profit=?,
                   last_message=?
               WHERE id=1""",
            (
                side, price, now_ts, qty, stop_loss, take_profit,
                f"Opened automatic paper {side} at ${price:,.2f}.",
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "message": f"Opened paper {side}: {qty:.6f} BTC at ${price:,.2f}.",
        "side": side,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
    }


def close_paper_position(price, reason="Exit rule"):
    state = get_auto_state()
    side = state["side"]
    if side not in {"LONG", "SHORT"}:
        return {"ok": False, "message": "No open paper position to close."}

    entry_price = safe_float(state["entry_price"])
    entry_qty = abs(safe_float(state["entry_qty"], 0.0))
    if entry_qty <= 0 or pd.isna(entry_price):
        return {"ok": False, "message": "Open paper position state is invalid."}

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
        cash, btc = float(row["cash"]), float(row["btc"])

        if side == "LONG":
            qty = min(entry_qty, max(0.0, btc))
            notional = qty * price
            cash += notional
            btc -= qty
            realized = (price - entry_price) * qty
            signed_qty = -qty
        else:
            qty = min(entry_qty, abs(min(0.0, btc)))
            notional = qty * price
            cash -= notional
            btc += qty
            realized = (entry_price - price) * qty
            signed_qty = qty

        # Remove tiny floating-point leftovers.
        if abs(btc) < 1e-12:
            btc = 0.0

        conn.execute(
            "UPDATE paper_account SET cash=?, btc=?, updated_iso=? WHERE id=1",
            (cash, btc, utc_now().isoformat()),
        )
        _paper_log(
            conn,
            f"CLOSE_{side}",
            price,
            signed_qty,
            notional,
            cash,
            btc,
            f"{reason} | realized_pnl=${realized:,.2f}",
        )
        conn.execute(
            """UPDATE auto_paper_state
               SET side='NONE',entry_price=NULL,entry_ts=NULL,entry_qty=NULL,
                   stop_loss=NULL,take_profit=NULL,last_exit_ts=?,last_message=?
               WHERE id=1""",
            (
                int(time.time()),
                f"Closed paper {side} at ${price:,.2f}: {reason}; realized P&L ${realized:,.2f}.",
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "message": f"Closed paper {side} at ${price:,.2f} — {reason}. Realized P&L ${realized:,.2f}.",
        "realized_pnl": realized,
    }


def manage_auto_paper(decision, risk, price, hist):
    """One automatic paper-trading cycle.

    Opens only approved BUY/SELL signals. An open position is exited by
    take-profit, stop-loss, 15-minute horizon, or a strong reversal.
    """
    state = get_auto_state()
    if not bool(state["enabled"]):
        return {"event": False, "message": state.get("last_message", "Auto paper trading is off.")}

    now_ts = int(time.time())
    side = state["side"]

    if side in {"LONG", "SHORT"}:
        entry = safe_float(state["entry_price"])
        stop = safe_float(state["stop_loss"])
        target = safe_float(state["take_profit"])
        entry_ts = int(state["entry_ts"] or now_ts)
        elapsed = now_ts - entry_ts

        exit_reason = None

        if decision["action"] in {"LOCK UP", "LOCK DOWN"}:
            if (
                pd.notna(decision.get("seconds_remaining"))
                and decision["seconds_remaining"] <= 0
            ):
                exit_reason = "Kalshi market expiration"
        else:
            if side == "LONG":
                if price <= stop:
                    exit_reason = "stop-loss"
                elif price >= target:
                    exit_reason = "take-profit"
                elif (
                    decision["action"] == "SCALP DOWN"
                    and decision["confidence"] >= 0.68
                    and decision["consensus"] >= 0.35
                ):
                    exit_reason = "strong master reversal"
            else:
                if price >= stop:
                    exit_reason = "stop-loss"
                elif price <= target:
                    exit_reason = "take-profit"
                elif (
                    decision["action"] == "SCALP UP"
                    and decision["confidence"] >= 0.68
                    and decision["consensus"] >= 0.35
                ):
                    exit_reason = "strong master reversal"

            if (
                exit_reason is None
                and pd.notna(decision.get("seconds_remaining"))
                and decision["seconds_remaining"] <= 0
            ):
                exit_reason = "Kalshi market expiration"
            elif (
                exit_reason is None
                and elapsed >= PREDICTION_HORIZON_MIN * 60
            ):
                exit_reason = f"{PREDICTION_HORIZON_MIN}-minute horizon"

        if exit_reason:
            result = close_paper_position(price, exit_reason)
            return {"event": result["ok"], "message": result["message"]}

        unrealized = ((price / entry) - 1.0) * 100 if side == "LONG" else ((entry / price) - 1.0) * 100
        msg = (
            f"AUTO {side} open • {elapsed//60:02d}:{elapsed%60:02d} elapsed • "
            f"unrealized {unrealized:+.3f}% • stop ${stop:,.2f} • target ${target:,.2f}"
        )
        return {"event": False, "message": msg}

    # 60-second cooldown prevents an immediate re-entry after an exit.
    last_exit_ts = int(state.get("last_exit_ts") or 0)
    if now_ts - last_exit_ts < 60:
        return {"event": False, "message": f"Auto paper cooldown: {60 - (now_ts-last_exit_ts)}s."}

    if risk["approved"] and decision["action"] in {"SCALP UP", "SCALP DOWN"}:
        internal_action = "BUY" if decision["action"] == "SCALP UP" else "SELL"
        result = open_paper_position(
            internal_action,
            price,
            risk["position_pct"],
            hist,
            note=(
                f"AUTO master={decision['score']:+.3f}, "
                f"confidence={decision['confidence']:.3f}, consensus={decision['consensus']:.3f}"
            ),
        )
        return {"event": result["ok"], "message": result["message"]}

    return {"event": False, "message": f"Waiting: {risk['reason']}."}


def execute_paper_trade(action, price, position_pct, hist, note=""):
    """Manual fallback using the same position engine as AUTO PAPER TRADING."""
    return open_paper_position(action, price, position_pct, hist, note=note)

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


def kalshi_numeric_target(market):
    """Return the displayed KXBTC15M Target Price, with strike fields as fallback."""
    if not isinstance(market, dict):
        return np.nan
    # KXBTC15M is an up/down contract. Kalshi exposes the user-facing opening
    # reference as `Target Price: $xx,xxx.xx` in the subtitle fields. That is
    # the number the dashboard must match. Do not substitute a threshold field
    # when the explicit target label is present.
    for key in ("yes_sub_title", "subtitle", "title"):
        text = str(market.get(key) or "")
        match = re.search(r"Target\s*Price\s*:\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)", text, re.I)
        if match:
            value = safe_float(match.group(1).replace(",", ""))
            if pd.notna(value) and value > 0:
                return float(value)
    strike_type = str(market.get("strike_type") or "").lower()
    preferred = (("cap_strike", "floor_strike") if strike_type in {"less", "less_equal", "less-than", "less_than"} else ("floor_strike", "cap_strike"))
    for key in preferred:
        value = safe_float(market.get(key))
        if pd.notna(value) and value > 0:
            return float(value)
    return np.nan


def kalshi_close_timestamp(market):
    if not isinstance(market, dict):
        return np.nan
    raw_close = (
        market.get("close_time")
        or market.get("expiration_time")
        or market.get("expected_expiration_time")
    )
    if not raw_close:
        return np.nan
    try:
        return float(pd.Timestamp(raw_close).timestamp())
    except Exception:
        return np.nan


def fetch_exact_kalshi_market(ticker):
    """Read one exact Kalshi market by ticker to canonicalize its strike."""
    if not ticker:
        return None
    for base in KALSHI_BASES:
        try:
            payload, _ = http_json(base + "/markets/" + str(ticker), timeout=3.0)
            market = payload.get("market") if isinstance(payload, dict) else None
            if isinstance(market, dict):
                return market
        except Exception:
            continue
    return None


@st.cache_data(ttl=3, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
    """Read-only lookup for the live Kalshi KXBTC15M market."""
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
            now_ts = time.time()

            for market in markets:
                blob = " ".join(
                    str(market.get(k, ""))
                    for k in [
                        "ticker", "title", "subtitle", "event_ticker",
                        "yes_sub_title", "no_sub_title"
                    ]
                ).lower()
                if not any(word in blob for word in ["bitcoin", "btc"]):
                    continue

                target = kalshi_numeric_target(market)
                if pd.isna(target) or target <= 0:
                    continue

                close_ts = kalshi_close_timestamp(market)

                row = dict(market)
                row["_target"] = target
                row["_close_ts"] = close_ts
                row["_seconds_remaining"] = (
                    max(0, int(close_ts - now_ts))
                    if pd.notna(close_ts) else np.nan
                )
                hits.append(row)

            future = [
                row for row in hits
                if pd.notna(row["_close_ts"]) and row["_close_ts"] > now_ts
            ]
            current = (
                min(future, key=lambda row: (row["_close_ts"], str(row.get("ticker", ""))))
                if future else (hits[0] if hits else None)
            )

            if current:
                exact = fetch_exact_kalshi_market(current.get("ticker", ""))
                if exact:
                    exact_target = kalshi_numeric_target(exact)
                    exact_close_ts = kalshi_close_timestamp(exact)
                    merged = dict(current)
                    merged.update(exact)
                    if pd.notna(exact_target):
                        merged["_target"] = exact_target
                    if pd.notna(exact_close_ts):
                        merged["_close_ts"] = exact_close_ts
                        merged["_seconds_remaining"] = max(0, int(exact_close_ts - now_ts))
                    current = merged

            return {
                "ok": True,
                "markets": hits[:25],
                "current": current,
                "feed_ms": ms,
                "error": None,
            }
        except Exception as exc:
            errors.append(str(exc))

    return {
        "ok": False,
        "markets": [],
        "current": None,
        "feed_ms": np.nan,
        "error": " | ".join(errors[-2:]),
    }


def kalshi_probability(market):
    if not market:
        return np.nan

    bid = safe_float(market.get("yes_bid_dollars"))
    ask = safe_float(market.get("yes_ask_dollars"))
    last = safe_float(market.get("last_price_dollars"))

    if pd.notna(bid) and pd.notna(ask):
        return clamp((bid + ask) / 2.0, 0.0, 1.0)
    if pd.notna(last):
        return clamp(last, 0.0, 1.0)
    if pd.notna(ask):
        return clamp(ask, 0.0, 1.0)
    if pd.notna(bid):
        return clamp(bid, 0.0, 1.0)
    return np.nan


def current_kalshi_context(kalshi, spot_price):
    market = kalshi.get("current") if kalshi else None
    if not market:
        return {
            "available": False,
            "ticker": "",
            "target": np.nan,
            "seconds_remaining": np.nan,
            "up_probability": np.nan,
            "distance": np.nan,
            "distance_pct": np.nan,
        }

    target = safe_float(market.get("_target"))
    remaining = safe_float(market.get("_seconds_remaining"))
    probability = kalshi_probability(market)

    distance = spot_price - target if pd.notna(target) else np.nan
    distance_pct = distance / target if pd.notna(distance) and target else np.nan

    return {
        "available": True,
        "ticker": market.get("ticker", ""),
        "title": market.get("title", "BTC 15 min"),
        "target": target,
        "seconds_remaining": remaining,
        "close_time": (
            market.get("close_time")
            or market.get("expiration_time")
            or market.get("expected_expiration_time")
        ),
        "up_probability": probability,
        "distance": distance,
        "distance_pct": distance_pct,
        "market": market,
    }


def stable_kalshi_contract(kalshi, spot_price):
    """Return one canonical Kalshi 15-minute contract for the whole app.

    Exact ticker + strike stay paired until expiry so chart, metrics,
    LOCK/SCALP decisions, paper trading and learning cannot drift apart.
    """
    live = current_kalshi_context(kalshi, spot_price)
    cached = st.session_state.get("kalshi_contract_snapshot")
    now_ts = time.time()

    def cache_expired(snapshot):
        if not snapshot:
            return True
        raw = snapshot.get("close_time")
        if not raw:
            return False
        try:
            return pd.Timestamp(raw).timestamp() <= now_ts
        except Exception:
            return False

    should_replace = (
        cached is None
        or pd.isna(cached.get("target", np.nan))
        or cache_expired(cached)
    )

    if live.get("available") and should_replace:
        cached = {
            "available": True,
            "ticker": live.get("ticker", ""),
            "title": live.get("title", "BTC 15 min"),
            "target": live.get("target", np.nan),
            "close_time": live.get("close_time"),
            "market": live.get("market"),
        }
        st.session_state["kalshi_contract_snapshot"] = cached

    if cached:
        result = dict(cached)
        if live.get("available") and live.get("ticker") == result.get("ticker"):
            result["up_probability"] = live.get("up_probability", np.nan)
            result["market"] = live.get("market", result.get("market"))
        else:
            result["up_probability"] = kalshi_probability(result.get("market"))

        try:
            close_ts = pd.Timestamp(result.get("close_time")).timestamp()
            result["seconds_remaining"] = max(0, int(close_ts - now_ts))
        except Exception:
            result["seconds_remaining"] = np.nan

        result["distance"] = (
            spot_price - result["target"]
            if pd.notna(result.get("target", np.nan)) else np.nan
        )
        result["distance_pct"] = (
            result["distance"] / result["target"]
            if pd.notna(result.get("distance", np.nan)) and result.get("target")
            else np.nan
        )
        result["available"] = True
        return result

    return live


@st.cache_data(ttl=10, show_spinner=False)
def fetch_kalshi_hourly_bitcoin_markets():
    """
    Public/read-only lookup for Kalshi's hourly BTC series (KXBTCD).
    Returns active strike markets for the nearest hourly event.
    """
    errors = []

    for base in KALSHI_BASES:
        try:
            payload, ms = http_json(
                base + "/markets",
                {
                    "limit": 200,
                    "status": "open",
                    "series_ticker": "KXBTCD",
                },
                timeout=3.0,
            )

            markets = payload.get("markets", []) if isinstance(payload, dict) else []
            now_ts = time.time()
            rows = []

            for market in markets:
                raw_close = (
                    market.get("close_time")
                    or market.get("expiration_time")
                    or market.get("expected_expiration_time")
                )

                close_ts = np.nan
                if raw_close:
                    try:
                        close_ts = pd.Timestamp(raw_close).timestamp()
                    except Exception:
                        pass

                if pd.notna(close_ts) and close_ts <= now_ts:
                    continue

                strike = safe_float(market.get("floor_strike"))
                if pd.isna(strike) or strike <= 0:
                    strike = safe_float(market.get("cap_strike"))

                # Some hourly BTC markets expose strike through functional_strike/title.
                if pd.isna(strike) or strike <= 0:
                    functional = str(market.get("functional_strike", ""))
                    match = re.search(r'(\d[\d,]*\.?\d*)', functional)
                    if match:
                        try:
                            strike = float(match.group(1).replace(",", ""))
                        except Exception:
                            pass

                if pd.isna(strike) or strike <= 0:
                    blob = " ".join(
                        str(market.get(k, ""))
                        for k in ["title", "subtitle", "yes_sub_title", "ticker"]
                    )
                    nums = re.findall(r'\$?(\d{2,3}(?:,\d{3})+(?:\.\d+)?)', blob)
                    if nums:
                        try:
                            strike = float(nums[-1].replace(",", ""))
                        except Exception:
                            pass

                if pd.isna(strike) or strike <= 0:
                    continue

                yes_bid = safe_float(market.get("yes_bid_dollars"))
                yes_ask = safe_float(market.get("yes_ask_dollars"))
                last = safe_float(market.get("last_price_dollars"))

                if pd.notna(yes_bid) and pd.notna(yes_ask):
                    yes_prob = clamp((yes_bid + yes_ask) / 2.0, 0.0, 1.0)
                elif pd.notna(last):
                    yes_prob = clamp(last, 0.0, 1.0)
                elif pd.notna(yes_ask):
                    yes_prob = clamp(yes_ask, 0.0, 1.0)
                elif pd.notna(yes_bid):
                    yes_prob = clamp(yes_bid, 0.0, 1.0)
                else:
                    yes_prob = np.nan

                row = dict(market)
                row["_strike"] = strike
                row["_close_ts"] = close_ts
                row["_seconds_remaining"] = (
                    max(0, int(close_ts - now_ts))
                    if pd.notna(close_ts)
                    else np.nan
                )
                row["_yes_probability"] = yes_prob
                rows.append(row)

            if not rows:
                return {
                    "ok": True,
                    "markets": [],
                    "event_markets": [],
                    "close_ts": np.nan,
                    "feed_ms": ms,
                    "error": None,
                }

            future_closes = sorted(
                {
                    row["_close_ts"]
                    for row in rows
                    if pd.notna(row["_close_ts"])
                }
            )

            nearest_close = future_closes[0] if future_closes else np.nan

            event_markets = [
                row
                for row in rows
                if (
                    pd.isna(nearest_close)
                    or pd.isna(row["_close_ts"])
                    or abs(row["_close_ts"] - nearest_close) <= 5
                )
            ]

            event_markets = sorted(
                event_markets,
                key=lambda row: row["_strike"],
            )

            return {
                "ok": True,
                "markets": rows,
                "event_markets": event_markets,
                "close_ts": nearest_close,
                "feed_ms": ms,
                "error": None,
            }

        except Exception as exc:
            errors.append(str(exc))

    return {
        "ok": False,
        "markets": [],
        "event_markets": [],
        "close_ts": np.nan,
        "feed_ms": np.nan,
        "error": " | ".join(errors[-2:]),
    }


def hourly_kalshi_target_ai(hist, specialist_results, hourly_kalshi, spot_price):
    """
    Separate 60-minute forecast model.

    Output:
    - estimated BTC price at next hourly Kalshi settlement
    - expected move in dollars / percent
    - confidence
    - nearest active Kalshi hourly strike
    - model-vs-Kalshi comparison
    """
    px = float(spot_price)
    last = hist.iloc[-1]

    atr = safe_float(last.get("atr14"), px * 0.002)
    ema9 = safe_float(last.get("ema9"), px)
    ema21 = safe_float(last.get("ema21"), px)
    rsi = safe_float(last.get("rsi"), 50.0)

    # Multi-window returns from 1-minute candles.
    closes = hist["close"].astype(float)
    ret5 = (px / float(closes.iloc[-6]) - 1.0) if len(closes) >= 6 else 0.0
    ret15 = (px / float(closes.iloc[-16]) - 1.0) if len(closes) >= 16 else 0.0
    ret30 = (px / float(closes.iloc[-31]) - 1.0) if len(closes) >= 31 else ret15
    ret60 = (px / float(closes.iloc[-61]) - 1.0) if len(closes) >= 61 else ret30

    # Specialist council, but smoother than the 15-minute bot.
    weighted = 0.0
    weight_total = 0.0
    for name, result in specialist_results.items():
        weight = SPECIALIST_WEIGHTS.get(name, 1.0)
        conf = safe_float(result.get("confidence"), 0.5)
        score = safe_float(result.get("score"), 0.0)
        weighted += score * conf * weight
        weight_total += conf * weight

    council_score = clamp(weighted / weight_total if weight_total else 0.0)

    trend_score = clamp((ema9 - ema21) / max(px * 0.0015, 1.0))
    momentum_score = clamp(
        0.20 * (ret5 / 0.003)
        + 0.30 * (ret15 / 0.006)
        + 0.25 * (ret30 / 0.009)
        + 0.25 * (ret60 / 0.014)
    )
    rsi_score = clamp((rsi - 50.0) / 25.0)

    hourly_score = clamp(
        0.45 * council_score
        + 0.25 * trend_score
        + 0.23 * momentum_score
        + 0.07 * rsi_score
    )

    # Scale expected movement to a 60-minute horizon.
    base_hour_move = max(
        atr * 2.35,
        px * 0.0022,
    )

    projected_move = base_hour_move * hourly_score
    ai_target = px + projected_move

    # Confidence increases with directional agreement and signal magnitude,
    # but remains bounded because this is still a probabilistic forecast.
    direction_votes = []
    for result in specialist_results.values():
        score = safe_float(result.get("score"), 0.0)
        if abs(score) >= 0.05:
            direction_votes.append(1 if score > 0 else -1)

    agreement = (
        abs(sum(direction_votes)) / len(direction_votes)
        if direction_votes else 0.0
    )

    confidence = min(
        0.92,
        max(
            0.45,
            0.50
            + abs(hourly_score) * 0.25
            + agreement * 0.12,
        ),
    )

    markets = hourly_kalshi.get("event_markets", []) if hourly_kalshi else []
    nearest_market = None
    nearest_strike = np.nan
    nearest_distance = np.nan

    if markets:
        nearest_market = min(
            markets,
            key=lambda row: abs(row["_strike"] - ai_target),
        )
        nearest_strike = safe_float(nearest_market.get("_strike"))
        nearest_distance = (
            ai_target - nearest_strike
            if pd.notna(nearest_strike)
            else np.nan
        )

    close_ts = hourly_kalshi.get("close_ts", np.nan) if hourly_kalshi else np.nan
    seconds_remaining = (
        max(0, int(close_ts - time.time()))
        if pd.notna(close_ts)
        else np.nan
    )

    direction = (
        "UP" if projected_move > px * 0.00025
        else "DOWN" if projected_move < -px * 0.00025
        else "FLAT"
    )

    return {
        "target_price": ai_target,
        "projected_move": projected_move,
        "projected_move_pct": projected_move / px if px else 0.0,
        "direction": direction,
        "confidence": confidence,
        "hourly_score": hourly_score,
        "nearest_strike": nearest_strike,
        "nearest_distance": nearest_distance,
        "nearest_market": nearest_market,
        "seconds_remaining": seconds_remaining,
        "close_ts": close_ts,
        "kalshi_available": bool(markets),
    }


def hourly_target_chart(hist, spot_price, hourly_ai):
    tail = hist.tail(90).copy()
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=tail["time"],
            open=tail["open"],
            high=tail["high"],
            low=tail["low"],
            close=tail["close"],
            name="BTC 1m",
            increasing_line_width=1.6,
            decreasing_line_width=1.6,
            increasing_fillcolor="#12b886",
            increasing_line_color="#12b886",
            decreasing_fillcolor="#fa5252",
            decreasing_line_color="#fa5252",
        )
    )

    target = hourly_ai["target_price"]

    fig.add_hline(
        y=target,
        line_dash="solid",
        line_width=4,
        line_color="#4dabf7",
        annotation_text=f"HOURLY AI TARGET  ${target:,.2f}",
        annotation_position="top left",
        annotation_bgcolor="rgba(8,13,20,0.92)",
        annotation_bordercolor="#4dabf7",
        annotation_borderwidth=1,
        annotation_font=dict(size=14, color="#d0ebff"),
    )

    nearest = hourly_ai.get("nearest_strike", np.nan)
    if pd.notna(nearest):
        fig.add_hline(
            y=nearest,
            line_dash="dash",
            line_width=2,
            line_color="#ffd43b",
            annotation_text=f"NEAREST KALSHI HOURLY STRIKE  ${nearest:,.2f}",
            annotation_position="bottom left",
        )

    fig.update_layout(
        uirevision="hourly-kalshi-ai",
        height=430,
        margin=dict(l=8, r=8, t=18, b=8),
        xaxis_rangeslider_visible=False,
        transition_duration=0,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
        ),
    )

    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(side="right", tickformat="$,.0f")

    apply_plotly_theme(fig)
    return fig


# ============================================================
# INDICATORS
# ============================================================


def enrich_history(df):
    return enrich_history_core(df)


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
    px = float(hist["close"].iloc[-1])
    kctx = stable_kalshi_contract(kalshi, px)
    return run_specialists_core(hist, agg, futures, kctx)

# ============================================================
# MASTER AI + RISK
# ============================================================


def master_decision(results, hist, kalshi=None):
    weighted_sum = 0.0
    total_weight = 0.0
    signs = []

    for name, result in results.items():
        weight = adaptive_specialist_weight(name)
        weighted_sum += result["score"] * result["confidence"] * weight
        total_weight += result["confidence"] * weight
        signs.append(np.sign(result["score"]))

    base_score = clamp(weighted_sum / total_weight if total_weight else 0.0)
    directional = [s for s in signs if s != 0]
    consensus = abs(sum(directional)) / len(directional) if directional else 0.0

    px = float(hist["close"].iloc[-1])
    atr = safe_float(hist["atr14"].iloc[-1], px * 0.002)
    kctx = stable_kalshi_contract(kalshi or {}, px)

    # Expected short-term move from the specialist council.
    forecast_move = max(atr * 1.35, px * 0.00125) * base_score
    projected_end = px + forecast_move

    target = kctx["target"]
    remaining = kctx["seconds_remaining"]
    up_prob = kctx["up_probability"]
    down_prob = (1.0 - up_prob) if pd.notna(up_prob) else np.nan

    if kctx["available"] and pd.notna(target):
        # Core settlement question: finish above or below the Kalshi target.
        projected_edge = projected_end - target
        current_edge = px - target

        target_scale = max(atr * 0.80, px * 0.0008)
        projected_target_score = clamp(projected_edge / target_scale)
        current_target_score = clamp(current_edge / max(atr * 0.65, px * 0.0006))

        market_score = (
            clamp((up_prob - 0.5) * 2.0)
            if pd.notna(up_prob) else 0.0
        )

        score = clamp(
            0.48 * base_score
            + 0.30 * projected_target_score
            + 0.14 * current_target_score
            + 0.08 * market_score
        )

        raw_side = "UP" if projected_end >= target else "DOWN"

        distance_strength = min(
            1.0,
            abs(projected_edge) / max(target_scale, 1.0),
        )

        confidence = min(
            0.97,
            max(
                0.45,
                0.49
                + abs(score) * 0.28
                + consensus * 0.13
                + distance_strength * 0.10,
            ),
        )

        # -----------------------------------------------------------
        # LOCK semantics
        # LOCK UP   = expected to FINISH ABOVE the Kalshi target.
        # LOCK DOWN = expected to FINISH BELOW the Kalshi target.
        # -----------------------------------------------------------
        lock_up = (
            raw_side == "UP"
            and confidence >= 0.68
            and projected_edge >= max(atr * 0.35, px * 0.00035)
            and (
                (pd.notna(remaining) and remaining <= 300)
                or abs(score) >= 0.30
            )
        )

        lock_down = (
            raw_side == "DOWN"
            and confidence >= 0.68
            and projected_edge <= -max(atr * 0.35, px * 0.00035)
            and (
                (pd.notna(remaining) and remaining <= 300)
                or abs(score) >= 0.30
            )
        )

        # -----------------------------------------------------------
        # SCALP semantics
        # Requires BOTH:
        # 1) a strong expected move before expiry
        # 2) Kalshi side price still favorable enough for paper-profit
        #
        # A lower probability means cheaper contracts and more upside,
        # but we avoid extremely low-probability lottery-style entries.
        # -----------------------------------------------------------
        strong_move_up = (
            base_score >= 0.30
            and forecast_move >= max(atr * 0.50, px * 0.0007)
            and consensus >= 0.30
        )
        strong_move_down = (
            base_score <= -0.30
            and forecast_move <= -max(atr * 0.50, px * 0.0007)
            and consensus >= 0.30
        )

        up_price_favorable = (
            pd.notna(up_prob)
            and 0.18 <= up_prob <= 0.72
        )
        down_price_favorable = (
            pd.notna(down_prob)
            and 0.18 <= down_prob <= 0.72
        )

        # Persistent lock state for the current Kalshi contract.
        lock_ticker = st.session_state.get("kalshi_lock_ticker", "")
        lock_side = st.session_state.get("kalshi_lock_side")
        current_ticker = kctx.get("ticker", "")

        if lock_ticker and (
            lock_ticker != current_ticker
            or (pd.notna(remaining) and remaining <= 0)
        ):
            st.session_state.pop("kalshi_lock_ticker", None)
            st.session_state.pop("kalshi_lock_side", None)
            lock_ticker = ""
            lock_side = None

        if lock_ticker == current_ticker and lock_side in {"UP", "DOWN"}:
            action = f"LOCK {lock_side}"
            locked_side = lock_side

        elif lock_up:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "UP"
            action = "LOCK UP"
            locked_side = "UP"

        elif lock_down:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "DOWN"
            action = "LOCK DOWN"
            locked_side = "DOWN"

        elif strong_move_up and up_price_favorable and confidence >= 0.58:
            action = "SCALP UP"
            locked_side = None

        elif strong_move_down and down_price_favorable and confidence >= 0.58:
            action = "SCALP DOWN"
            locked_side = None

        else:
            action = "HOLD"
            locked_side = None

        target_price = target
        prediction_label = (
            f"Finish ABOVE ${target:,.2f}"
            if raw_side == "UP"
            else f"Finish BELOW ${target:,.2f}"
        )

    else:
        # Fallback if Kalshi is temporarily unavailable.
        score = base_score
        confidence = min(
            0.97,
            max(0.45, 0.48 + abs(score) * 0.34 + consensus * 0.15),
        )
        projected_end = px + forecast_move
        target_price = projected_end
        locked_side = None
        up_prob = np.nan
        down_prob = np.nan

        if base_score >= 0.32 and confidence >= 0.60:
            action = "SCALP UP"
        elif base_score <= -0.32 and confidence >= 0.60:
            action = "SCALP DOWN"
        else:
            action = "HOLD"

        prediction_label = "Kalshi target unavailable"

    risk_level = (
        "LOW"
        if confidence > 0.78 and consensus > 0.55
        else "MEDIUM"
        if confidence > 0.62
        else "HIGH"
    )

    strongest = sorted(
        results.values(),
        key=lambda result: abs(result["score"] * result["confidence"]),
        reverse=True,
    )[:3]

    reason_parts = [
        "; ".join(
            f"{result['name']}: {result['signal']} ({result['score']:+.2f})"
            for result in strongest
        )
    ]

    if kctx["available"]:
        odds_text = ""
        if pd.notna(up_prob):
            odds_text = (
                f"; Kalshi UP {up_prob*100:.1f}% / "
                f"DOWN {down_prob*100:.1f}%"
            )

        reason_parts.append(
            f"Target ${target:,.2f}; projected end ${projected_end:,.2f}"
            + odds_text
        )

    return {
        "action": action,
        "locked_side": locked_side,
        "score": score,
        "base_score": base_score,
        "confidence": confidence,
        "consensus": consensus,
        "target_price": target_price,
        "projected_end": projected_end,
        "prediction_label": prediction_label,
        "risk_level": risk_level,
        "reason": " • ".join(reason_parts),
        "kalshi_ticker": kctx.get("ticker", ""),
        "seconds_remaining": remaining,
        "up_probability": up_prob,
        "down_probability": down_prob,
        "kalshi_available": kctx["available"],
    }


def risk_evaluate(decision, account, hist, futures):
    px = float(hist["close"].iloc[-1])
    atr_pct = safe_float(hist["atr14"].iloc[-1] / px, 0.003)
    confidence = decision["confidence"]
    consensus = decision["consensus"]

    if decision["action"] in {"HOLD", "LOCK UP", "LOCK DOWN"}:
        reason = "LOCK: hold current Kalshi call to expiration" if decision["action"].startswith("LOCK") else "HOLD signal"
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": reason}
    if confidence < 0.62:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.9, "reason": "Confidence below 62%"}
    if consensus < 0.30:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.8, "reason": "Specialist consensus too low"}

    volatility_penalty = min(0.55, max(0.0, (atr_pct - 0.002) * 100))
    base = 0.04 + (confidence - 0.60) * 0.22 + consensus * 0.04
    position_pct = max(0.02, min(0.15, base * (1 - volatility_penalty)))
    risk_score = clamp(0.6 - confidence * 0.35 - consensus * 0.15 + volatility_penalty, 0, 1)

    state = get_auto_state()
    if state["side"] != "NONE":
        return {
            "approved": False,
            "position_pct": 0.0,
            "risk_score": risk_score,
            "reason": f"Paper {state['side']} already open",
        }

    return {"approved": True, "position_pct": position_pct, "risk_score": risk_score, "reason": "Paper-trade risk checks passed"}


# ============================================================
# SELF-LEARNING 15-MINUTE FORECAST MODEL
# ============================================================

LEARNING_DB = "btc_ai.db"

def learning_db():
    conn = sqlite3.connect(LEARNING_DB, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_learning_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            w_ret3 REAL NOT NULL DEFAULT 0.46,
            w_ret8 REAL NOT NULL DEFAULT 0.34,
            w_ret15 REAL NOT NULL DEFAULT 0.20,
            momentum_scale REAL NOT NULL DEFAULT 2.20,
            target_influence REAL NOT NULL DEFAULT 0.18,
            bias REAL NOT NULL DEFAULT 0.0,
            learning_rate REAL NOT NULL DEFAULT 0.08,
            samples INTEGER NOT NULL DEFAULT 0,
            direction_hits INTEGER NOT NULL DEFAULT 0,
            avg_abs_error REAL NOT NULL DEFAULT 0.0,
            avg_path_error REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_windows (
            ticker TEXT PRIMARY KEY,
            opened_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            start_price REAL NOT NULL,
            target_price REAL,
            predicted_end REAL NOT NULL,
            predicted_direction INTEGER NOT NULL,
            ret3 REAL NOT NULL,
            ret8 REAL NOT NULL,
            ret15 REAL NOT NULL,
            avg_range REAL NOT NULL,
            prediction_json TEXT,
            resolved INTEGER NOT NULL DEFAULT 0,
            actual_end REAL,
            direction_correct INTEGER,
            abs_error REAL,
            path_error REAL,
            resolved_at TEXT
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO forecast_learning_state (id, updated_at) VALUES (1, ?)",
        (datetime.now(timezone.utc).isoformat(),)
    )
    conn.commit()
    return conn


def get_learning_state():
    remote = fetch_remote_learning_state()
    if isinstance(remote, dict):
        r = remote.get("forecast")
        if isinstance(r, dict):
            defaults = {
                "w_ret3": 0.46,
                "w_ret8": 0.34,
                "w_ret15": 0.20,
                "momentum_scale": 2.20,
                "target_influence": 0.18,
                "bias": 0.0,
                "learning_rate": 0.08,
                "samples": 0,
                "direction_hits": 0,
                "avg_abs_error": 0.0,
                "avg_path_error": 0.0,
                "kalshi_samples": 0,
                "kalshi_hits": 0,
            }
            state = {k: r.get(k, v) for k, v in defaults.items()}
            state["samples"] = int(state["samples"])
            state["direction_hits"] = int(state["direction_hits"])
            state["direction_accuracy"] = (
                state["direction_hits"] / state["samples"]
                if state["samples"] else np.nan
            )
            return state

    conn = learning_db()
    row = conn.execute("""
        SELECT
            w_ret3, w_ret8, w_ret15, momentum_scale,
            target_influence, bias, learning_rate,
            samples, direction_hits, avg_abs_error, avg_path_error
        FROM forecast_learning_state
        WHERE id = 1
    """).fetchone()
    conn.close()

    keys = [
        "w_ret3", "w_ret8", "w_ret15", "momentum_scale",
        "target_influence", "bias", "learning_rate",
        "samples", "direction_hits", "avg_abs_error", "avg_path_error"
    ]
    state = dict(zip(keys, row))
    state["direction_accuracy"] = (
        state["direction_hits"] / state["samples"]
        if state["samples"] else np.nan
    )
    return state

def save_learning_state(state):
    conn = learning_db()
    conn.execute("""
        UPDATE forecast_learning_state
        SET
            w_ret3 = ?,
            w_ret8 = ?,
            w_ret15 = ?,
            momentum_scale = ?,
            target_influence = ?,
            bias = ?,
            learning_rate = ?,
            samples = ?,
            direction_hits = ?,
            avg_abs_error = ?,
            avg_path_error = ?,
            updated_at = ?
        WHERE id = 1
    """, (
        float(state["w_ret3"]),
        float(state["w_ret8"]),
        float(state["w_ret15"]),
        float(state["momentum_scale"]),
        float(state["target_influence"]),
        float(state["bias"]),
        float(state["learning_rate"]),
        int(state["samples"]),
        int(state["direction_hits"]),
        float(state["avg_abs_error"]),
        float(state["avg_path_error"]),
        datetime.now(timezone.utc).isoformat(),
    ))
    conn.commit()
    conn.close()


def normalize_learning_weights(state):
    vals = np.array(
        [state["w_ret3"], state["w_ret8"], state["w_ret15"]],
        dtype=float
    )
    vals = np.clip(vals, 0.05, 0.90)
    vals /= float(vals.sum()) or 1.0
    state["w_ret3"], state["w_ret8"], state["w_ret15"] = vals.tolist()
    state["momentum_scale"] = float(np.clip(state["momentum_scale"], 0.60, 4.50))
    state["target_influence"] = float(np.clip(state["target_influence"], 0.00, 0.50))
    state["bias"] = float(np.clip(state["bias"], -0.004, 0.004))
    return state


def model_inputs_from_rows(rows, target=None):
    closes = np.asarray([float(r["close"]) for r in rows], dtype=float)
    if len(closes) < 16:
        return None

    last = float(closes[-1])
    ret3 = last / float(closes[-4]) - 1.0
    ret8 = last / float(closes[-9]) - 1.0
    ret15 = last / float(closes[-16]) - 1.0

    recent = rows[-20:]
    ranges = [
        max(0.0, float(r["high"]) - float(r["low"]))
        for r in recent
    ]
    avg_range = float(np.mean(ranges)) if ranges else max(last * 0.0005, 1.0)

    return {
        "last": last,
        "ret3": ret3,
        "ret8": ret8,
        "ret15": ret15,
        "avg_range": avg_range,
        "target": safe_float(target),
    }


def python_forecast_path(rows, target=None, state=None):
    return forecast_path_core(rows, target, state or get_learning_state())


def register_forecast_window(ticker, expires_at, rows, target):
    if not ticker or pd.isna(expires_at):
        return

    conn = learning_db()
    if conn.execute(
        "SELECT 1 FROM forecast_windows WHERE ticker = ?",
        (ticker,)
    ).fetchone():
        conn.close()
        return

    state = get_learning_state()
    result = python_forecast_path(rows, target, state)
    if not result:
        conn.close()
        return

    import json as _json
    inputs = result["inputs"]

    conn.execute("""
        INSERT OR IGNORE INTO forecast_windows (
            ticker, opened_at, expires_at, start_price, target_price,
            predicted_end, predicted_direction,
            ret3, ret8, ret15, avg_range, prediction_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker,
        time.time(),
        float(expires_at),
        float(inputs["last"]),
        float(target) if pd.notna(target) else None,
        float(result["predicted_end"]),
        int(result["predicted_direction"]),
        float(inputs["ret3"]),
        float(inputs["ret8"]),
        float(inputs["ret15"]),
        float(inputs["avg_range"]),
        _json.dumps(result["forecast"]),
    ))
    conn.commit()
    conn.close()


def resolve_forecast_windows(hist):
    if hist is None or hist.empty:
        return 0

    now_ts = time.time()
    conn = learning_db()
    pending = conn.execute("""
        SELECT
            ticker, expires_at, start_price, target_price,
            predicted_end, predicted_direction,
            ret3, ret8, ret15, avg_range, prediction_json
        FROM forecast_windows
        WHERE resolved = 0 AND expires_at <= ?
        ORDER BY expires_at ASC
        LIMIT 20
    """, (now_ts,)).fetchall()

    if not pending:
        conn.close()
        return 0

    state = get_learning_state()
    resolved_count = 0

    hist2 = hist.copy()
    hist2["_ts"] = pd.to_datetime(hist2["time"], utc=True, errors="coerce")
    hist2 = hist2.dropna(subset=["_ts"])

    import json as _json

    for row in pending:
        (
            ticker, expires_at, start_price, target_price,
            predicted_end, predicted_direction,
            ret3, ret8, ret15, avg_range, prediction_json
        ) = row

        expiry_dt = pd.to_datetime(expires_at, unit="s", utc=True)
        near = hist2.iloc[(hist2["_ts"] - expiry_dt).abs().argsort()[:1]]
        if near.empty:
            continue

        actual_end = float(near.iloc[0]["close"])
        actual_direction = 1 if actual_end >= start_price else -1
        direction_correct = int(actual_direction == predicted_direction)
        abs_error = abs(actual_end - predicted_end)

        path_error = abs_error
        try:
            pred_path = _json.loads(prediction_json or "[]")
            actual_window = hist2.loc[
                (hist2["_ts"] > expiry_dt - pd.Timedelta(minutes=15))
                & (hist2["_ts"] <= expiry_dt)
            ].tail(15)

            if pred_path and len(actual_window) >= 5:
                pred_closes = np.array(
                    [float(p["close"]) for p in pred_path],
                    dtype=float
                )
                actual_closes = actual_window["close"].astype(float).to_numpy()
                n = min(len(pred_closes), len(actual_closes))
                path_error = float(
                    np.mean(np.abs(pred_closes[-n:] - actual_closes[-n:]))
                )
        except Exception:
            pass

        actual_return = actual_end / start_price - 1.0
        predicted_return = predicted_end / start_price - 1.0
        error = actual_return - predicted_return
        lr = float(state["learning_rate"])

        features = np.array([ret3, ret8, ret15], dtype=float)
        feature_scale = max(float(np.abs(features).sum()), 1e-6)
        adjustments = lr * error * (features / feature_scale) * 8.0

        state["w_ret3"] += float(adjustments[0])
        state["w_ret8"] += float(adjustments[1])
        state["w_ret15"] += float(adjustments[2])

        if abs(predicted_return) > 1e-5:
            ratio = actual_return / predicted_return
            state["momentum_scale"] *= float(
                np.clip(1.0 + lr * (ratio - 1.0) * 0.20, 0.94, 1.06)
            )

        state["bias"] += float(
            np.clip(lr * error * 0.12, -0.00015, 0.00015)
        )

        if target_price is not None:
            target_dir = np.sign(target_price - start_price)
            actual_dir = np.sign(actual_end - start_price)
            if target_dir != 0:
                state["target_influence"] += (
                    lr * 0.008 if target_dir == actual_dir else -lr * 0.012
                )

        state["samples"] += 1
        state["direction_hits"] += direction_correct
        n_samples = state["samples"]

        state["avg_abs_error"] = (
            abs_error
            if n_samples == 1
            else state["avg_abs_error"]
            + (abs_error - state["avg_abs_error"]) / n_samples
        )
        state["avg_path_error"] = (
            path_error
            if n_samples == 1
            else state["avg_path_error"]
            + (path_error - state["avg_path_error"]) / n_samples
        )

        state = normalize_learning_weights(state)

        conn.execute("""
            UPDATE forecast_windows
            SET
                resolved = 1,
                actual_end = ?,
                direction_correct = ?,
                abs_error = ?,
                path_error = ?,
                resolved_at = ?
            WHERE ticker = ?
        """, (
            actual_end,
            direction_correct,
            abs_error,
            path_error,
            datetime.now(timezone.utc).isoformat(),
            ticker,
        ))
        resolved_count += 1

    conn.commit()
    conn.close()

    if resolved_count:
        save_learning_state(state)

    return resolved_count


def recent_learning_windows(limit=50):
    conn = learning_db()
    df = pd.read_sql_query("""
        SELECT
            ticker,
            datetime(expires_at, 'unixepoch') AS expires_utc,
            start_price,
            predicted_end,
            actual_end,
            direction_correct,
            abs_error,
            path_error
        FROM forecast_windows
        WHERE resolved = 1
        ORDER BY expires_at DESC
        LIMIT ?
    """, conn, params=(int(limit),))
    conn.close()
    return df



# ============================================================
# SELF-LEARNING SPECIALIST AIS
# ============================================================

SPECIALIST_LEARNING_DB = "btc_ai.db"

def specialist_learning_db():
    conn = sqlite3.connect(SPECIALIST_LEARNING_DB, check_same_thread=False)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS specialist_learning_state (
            specialist TEXT PRIMARY KEY,
            adaptive_weight REAL NOT NULL DEFAULT 1.0,
            samples INTEGER NOT NULL DEFAULT 0,
            direction_hits INTEGER NOT NULL DEFAULT 0,
            ewma_accuracy REAL NOT NULL DEFAULT 0.50,
            ewma_edge REAL NOT NULL DEFAULT 0.0,
            ewma_calibration REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS specialist_window_predictions (
            ticker TEXT NOT NULL,
            specialist TEXT NOT NULL,
            opened_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            start_price REAL NOT NULL,
            target_price REAL,
            score REAL NOT NULL,
            confidence REAL NOT NULL,
            predicted_direction INTEGER NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            actual_end REAL,
            actual_direction INTEGER,
            direction_correct INTEGER,
            realized_return REAL,
            signed_edge REAL,
            resolved_at TEXT,
            PRIMARY KEY (ticker, specialist)
        )
    """)

    # Migrate the old misleading Event AI label without discarding learned state.
    old_event = conn.execute(
        "SELECT adaptive_weight,samples,direction_hits,ewma_accuracy,ewma_edge,ewma_calibration,updated_at "
        "FROM specialist_learning_state WHERE specialist='Event AI'"
    ).fetchone()
    if old_event is not None:
        conn.execute(
            "INSERT OR IGNORE INTO specialist_learning_state "
            "(specialist,adaptive_weight,samples,direction_hits,ewma_accuracy,ewma_edge,ewma_calibration,updated_at) "
            "VALUES ('Kalshi Context AI',?,?,?,?,?,?,?)",
            tuple(old_event),
        )

    # Ensure each known specialist has a persistent learning row.
    for name in SPECIALIST_WEIGHTS.keys():
        conn.execute("""
            INSERT OR IGNORE INTO specialist_learning_state (
                specialist, adaptive_weight, updated_at
            )
            VALUES (?, 1.0, ?)
        """, (
            name,
            datetime.now(timezone.utc).isoformat(),
        ))

    conn.commit()
    return conn


def get_specialist_learning_state():
    remote = fetch_remote_learning_state()
    if isinstance(remote, dict):
        specialists = remote.get("specialists")
        if isinstance(specialists, dict) and specialists:
            state = {}
            for name in SPECIALIST_WEIGHTS.keys():
                item = specialists.get(name, specialists.get("Event AI", {}) if name == "Kalshi Context AI" else {})
                samples = int(item.get("samples", 0))
                direction_hits = int(item.get("direction_hits", 0))
                state[name] = {
                    "adaptive_weight": float(item.get("adaptive_weight", 1.0)),
                    "samples": samples,
                    "direction_hits": direction_hits,
                    "accuracy": (
                        direction_hits / samples if samples else np.nan
                    ),
                    "ewma_accuracy": float(item.get("ewma_accuracy", 0.50)),
                    "ewma_edge": float(item.get("ewma_edge", 0.0)),
                    "ewma_calibration": float(item.get("ewma_calibration", 0.0)),
                }
            return state

    conn = specialist_learning_db()
    rows = conn.execute("""
        SELECT
            specialist,
            adaptive_weight,
            samples,
            direction_hits,
            ewma_accuracy,
            ewma_edge,
            ewma_calibration
        FROM specialist_learning_state
    """).fetchall()
    conn.close()

    state = {}
    for row in rows:
        (
            specialist,
            adaptive_weight,
            samples,
            direction_hits,
            ewma_accuracy,
            ewma_edge,
            ewma_calibration,
        ) = row

        state[specialist] = {
            "adaptive_weight": float(adaptive_weight),
            "samples": int(samples),
            "direction_hits": int(direction_hits),
            "accuracy": (
                direction_hits / samples if samples else np.nan
            ),
            "ewma_accuracy": float(ewma_accuracy),
            "ewma_edge": float(ewma_edge),
            "ewma_calibration": float(ewma_calibration),
        }

    return state

def adaptive_specialist_weight(name):
    state = get_specialist_learning_state().get(name, {})
    learned = safe_float(state.get("adaptive_weight"), 1.0)
    base = safe_float(SPECIALIST_WEIGHTS.get(name), 1.0)
    return base * learned


def register_specialist_window_predictions(
    ticker,
    expires_at,
    start_price,
    target_price,
    specialist_results,
):
    if (
        not ticker
        or pd.isna(expires_at)
        or not specialist_results
        or pd.isna(start_price)
    ):
        return

    conn = specialist_learning_db()
    now_ts = time.time()

    for name, result in specialist_results.items():
        score = safe_float(result.get("score"), 0.0)
        confidence = safe_float(result.get("confidence"), 0.50)

        predicted_direction = (
            1 if score > 0.03
            else -1 if score < -0.03
            else 0
        )

        conn.execute("""
            INSERT OR IGNORE INTO specialist_window_predictions (
                ticker,
                specialist,
                opened_at,
                expires_at,
                start_price,
                target_price,
                score,
                confidence,
                predicted_direction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker,
            name,
            now_ts,
            float(expires_at),
            float(start_price),
            float(target_price) if pd.notna(target_price) else None,
            float(score),
            float(confidence),
            int(predicted_direction),
        ))

    conn.commit()
    conn.close()


def resolve_specialist_learning(hist):
    if hist is None or hist.empty:
        return 0

    now_ts = time.time()
    conn = specialist_learning_db()

    pending = conn.execute("""
        SELECT
            ticker,
            specialist,
            expires_at,
            start_price,
            target_price,
            score,
            confidence,
            predicted_direction
        FROM specialist_window_predictions
        WHERE resolved = 0 AND expires_at <= ?
        ORDER BY expires_at ASC
        LIMIT 500
    """, (now_ts,)).fetchall()

    if not pending:
        conn.close()
        return 0

    hist2 = hist.copy()
    hist2["_ts"] = pd.to_datetime(
        hist2["time"],
        utc=True,
        errors="coerce",
    )
    hist2 = hist2.dropna(subset=["_ts"])

    updates = {}

    for row in pending:
        (
            ticker,
            specialist,
            expires_at,
            start_price,
            target_price,
            score,
            confidence,
            predicted_direction,
        ) = row

        expiry_dt = pd.to_datetime(
            expires_at,
            unit="s",
            utc=True,
        )

        near = hist2.iloc[
            (hist2["_ts"] - expiry_dt).abs().argsort()[:1]
        ]

        if near.empty:
            continue

        actual_end = float(near.iloc[0]["close"])
        realized_return = actual_end / float(start_price) - 1.0

        # Primary specialist grading is market direction over the window.
        actual_direction = (
            1 if actual_end > start_price
            else -1 if actual_end < start_price
            else 0
        )

        if predicted_direction == 0:
            direction_correct = 0
            signed_edge = 0.0
        else:
            direction_correct = int(
                predicted_direction == actual_direction
            )

            # Signed edge rewards correct directional conviction and
            # penalizes wrong directional conviction.
            signed_edge = (
                float(score)
                * float(realized_return)
                * 100.0
            )

        # Confidence calibration:
        # correct confident calls help; wrong confident calls hurt.
        calibration = (
            confidence
            if direction_correct
            else -confidence
        )

        current = conn.execute("""
            SELECT
                adaptive_weight,
                samples,
                direction_hits,
                ewma_accuracy,
                ewma_edge,
                ewma_calibration
            FROM specialist_learning_state
            WHERE specialist = ?
        """, (specialist,)).fetchone()

        if current is None:
            current = (1.0, 0, 0, 0.50, 0.0, 0.0)

        (
            adaptive_weight,
            samples,
            direction_hits,
            ewma_accuracy,
            ewma_edge,
            ewma_calibration,
        ) = current

        alpha = 0.10

        ewma_accuracy = (
            (1 - alpha) * float(ewma_accuracy)
            + alpha * float(direction_correct)
        )

        ewma_edge = (
            (1 - alpha) * float(ewma_edge)
            + alpha * float(signed_edge)
        )

        ewma_calibration = (
            (1 - alpha) * float(ewma_calibration)
            + alpha * float(calibration)
        )

        samples = int(samples) + 1
        direction_hits = int(direction_hits) + int(direction_correct)

        # Adaptive influence:
        # accuracy + realized edge + confidence calibration.
        quality = (
            0.55 * (ewma_accuracy - 0.50) * 2.0
            + 0.25 * np.tanh(ewma_edge * 4.0)
            + 0.20 * ewma_calibration
        )

        target_weight = float(
            np.clip(
                1.0 + quality,
                0.35,
                1.85,
            )
        )

        # Smooth changes so one bad window cannot destroy a specialist.
        adaptive_weight = (
            0.90 * float(adaptive_weight)
            + 0.10 * target_weight
        )
        adaptive_weight = float(
            np.clip(adaptive_weight, 0.35, 1.85)
        )

        conn.execute("""
            UPDATE specialist_learning_state
            SET
                adaptive_weight = ?,
                samples = ?,
                direction_hits = ?,
                ewma_accuracy = ?,
                ewma_edge = ?,
                ewma_calibration = ?,
                updated_at = ?
            WHERE specialist = ?
        """, (
            adaptive_weight,
            samples,
            direction_hits,
            ewma_accuracy,
            ewma_edge,
            ewma_calibration,
            datetime.now(timezone.utc).isoformat(),
            specialist,
        ))

        conn.execute("""
            UPDATE specialist_window_predictions
            SET
                resolved = 1,
                actual_end = ?,
                actual_direction = ?,
                direction_correct = ?,
                realized_return = ?,
                signed_edge = ?,
                resolved_at = ?
            WHERE ticker = ? AND specialist = ?
        """, (
            actual_end,
            actual_direction,
            direction_correct,
            realized_return,
            signed_edge,
            datetime.now(timezone.utc).isoformat(),
            ticker,
            specialist,
        ))

        updates[specialist] = adaptive_weight

    conn.commit()
    conn.close()
    return len(updates)


def specialist_learning_dataframe():
    state = get_specialist_learning_state()

    rows = []
    for name in sorted(state.keys()):
        item = state[name]
        rows.append({
            "Specialist": name,
            "Learned weight": item["adaptive_weight"],
            "Samples": item["samples"],
            "Accuracy %": (
                np.nan
                if pd.isna(item["accuracy"])
                else item["accuracy"] * 100.0
            ),
            "Recent accuracy %": item["ewma_accuracy"] * 100.0,
            "Recent edge": item["ewma_edge"],
            "Calibration": item["ewma_calibration"],
        })

    return pd.DataFrame(rows)



# ============================================================
# ROLLING LEARNING ACCURACY
# ============================================================

def rolling_master_accuracy(window):
    remote = fetch_remote_learning_state()
    if isinstance(remote, dict):
        history = remote.get("master_history")
        if isinstance(history, list) and history:
            rows = history[-int(window):]
            correct = pd.to_numeric(
                pd.Series([r.get("direction_correct") for r in rows]),
                errors="coerce",
            ).dropna()
            abs_error = pd.to_numeric(
                pd.Series([r.get("abs_error") for r in rows]),
                errors="coerce",
            )
            path_error = pd.to_numeric(
                pd.Series([r.get("path_error") for r in rows]),
                errors="coerce",
            )
            return {
                "samples": int(len(correct)),
                "accuracy": float(correct.mean()) if len(correct) else np.nan,
                "avg_abs_error": float(abs_error.mean()) if abs_error.notna().any() else np.nan,
                "avg_path_error": float(path_error.mean()) if path_error.notna().any() else np.nan,
            }

    conn = learning_db()
    df = pd.read_sql_query("""
        SELECT direction_correct, abs_error, path_error, expires_at
        FROM forecast_windows
        WHERE resolved = 1
        ORDER BY expires_at DESC
        LIMIT ?
    """, conn, params=(int(window),))
    conn.close()

    if df.empty:
        return {
            "samples": 0,
            "accuracy": np.nan,
            "avg_abs_error": np.nan,
            "avg_path_error": np.nan,
        }

    df["direction_correct"] = pd.to_numeric(df["direction_correct"], errors="coerce")
    df["abs_error"] = pd.to_numeric(df["abs_error"], errors="coerce")
    df["path_error"] = pd.to_numeric(df["path_error"], errors="coerce")
    valid = df["direction_correct"].dropna()

    return {
        "samples": int(len(valid)),
        "accuracy": float(valid.mean()) if len(valid) else np.nan,
        "avg_abs_error": float(df["abs_error"].mean()),
        "avg_path_error": float(df["path_error"].mean()),
    }

def rolling_master_accuracy_table():
    rows = []

    for window in (100, 500, 1000):
        stats = rolling_master_accuracy(window)

        rows.append({
            "Window": f"Last {window}",
            "Samples": stats["samples"],
            "Direction Accuracy %": (
                np.nan
                if pd.isna(stats["accuracy"])
                else stats["accuracy"] * 100.0
            ),
            "Avg Final Error $": stats["avg_abs_error"],
            "Avg Path Error $": stats["avg_path_error"],
        })

    return pd.DataFrame(rows)


def rolling_specialist_accuracy(window):
    remote = fetch_remote_learning_state()
    if isinstance(remote, dict):
        histories = remote.get("specialist_history")
        if isinstance(histories, dict) and histories:
            out = []
            for specialist, history in histories.items():
                if not isinstance(history, list):
                    continue
                rows = history[-int(window):]
                correct = pd.to_numeric(
                    pd.Series([r.get("direction_correct") for r in rows]),
                    errors="coerce",
                ).dropna()
                edge = pd.to_numeric(
                    pd.Series([r.get("signed_edge") for r in rows]),
                    errors="coerce",
                )
                out.append({
                    "Specialist": specialist,
                    "Samples": int(len(correct)),
                    "Accuracy %": (
                        np.nan if len(correct) == 0
                        else float(correct.mean() * 100.0)
                    ),
                    "Avg Signed Edge": (
                        float(edge.mean()) if edge.notna().any() else np.nan
                    ),
                })
            return pd.DataFrame(out)

    conn = specialist_learning_db()
    df = pd.read_sql_query("""
        SELECT specialist, direction_correct, signed_edge, resolved_at
        FROM specialist_window_predictions
        WHERE resolved = 1
        ORDER BY resolved_at DESC
    """, conn)
    conn.close()

    if df.empty:
        return pd.DataFrame(
            columns=["Specialist", "Samples", "Accuracy %", "Avg Signed Edge"]
        )

    df["direction_correct"] = pd.to_numeric(df["direction_correct"], errors="coerce")
    df["signed_edge"] = pd.to_numeric(df["signed_edge"], errors="coerce")

    out = []
    for specialist, group in df.groupby("specialist"):
        g = group.head(int(window)).copy()
        valid = g["direction_correct"].dropna()
        out.append({
            "Specialist": specialist,
            "Samples": int(len(valid)),
            "Accuracy %": (
                np.nan if len(valid) == 0 else float(valid.mean() * 100.0)
            ),
            "Avg Signed Edge": float(g["signed_edge"].mean()) if len(g) else np.nan,
        })

    return pd.DataFrame(out)

def specialist_multiwindow_accuracy():
    merged = None

    for window in (100, 500, 1000):
        df = rolling_specialist_accuracy(window)

        rename = {
            "Samples": f"N{window}",
            "Accuracy %": f"Acc {window} %",
            "Avg Signed Edge": f"Edge {window}",
        }

        df = df.rename(columns=rename)

        cols = [
            "Specialist",
            f"N{window}",
            f"Acc {window} %",
            f"Edge {window}",
        ]

        df = df[cols]

        merged = (
            df if merged is None
            else merged.merge(
                df,
                on="Specialist",
                how="outer",
            )
        )

    return (
        merged
        if merged is not None
        else pd.DataFrame()
    )


def learning_trend_label(short_acc, long_acc):
    if pd.isna(short_acc) or pd.isna(long_acc):
        return "Not enough data"

    diff = float(short_acc) - float(long_acc)

    if diff >= 5.0:
        return "Improving ↑"
    if diff <= -5.0:
        return "Slipping ↓"
    return "Stable →"


def add_specialist_learning_trends(df):
    if df is None or df.empty:
        return df

    out = df.copy()

    out["Trend"] = out.apply(
        lambda r: learning_trend_label(
            r.get("Acc 100 %"),
            r.get("Acc 1000 %"),
        ),
        axis=1,
    )

    return out


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
            strike = safe_float(row["target_price"])

            if action == "SCALP UP":
                correct = (
                    int(current_price >= strike)
                    if pd.notna(strike)
                    else int(current_price > start_price)
                )
            elif action == "SCALP DOWN":
                correct = (
                    int(current_price < strike)
                    if pd.notna(strike)
                    else int(current_price < start_price)
                )
            elif action == "LOCK UP":
                correct = (
                    int(current_price >= strike)
                    if pd.notna(strike)
                    else int(current_price > start_price)
                )
            elif action == "LOCK DOWN":
                correct = (
                    int(current_price < strike)
                    if pd.notna(strike)
                    else int(current_price < start_price)
                )
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
        # Existing Streamlit Cloud databases can contain values written by an
        # older build as strings/objects. Coerce display columns back to
        # numeric before arithmetic/rounding so legacy rows cannot crash the UI.
        numeric_cols = ["confidence", "consensus", "score", "price",
                        "target_price", "resolved_price", "return_pct", "correct"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["confidence"] = (df["confidence"] * 100.0).round(1)
        df["consensus"] = (df["consensus"] * 100.0).round(1)
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


def apply_plotly_theme(fig):
    if st.session_state.get("dashboard_dark_mode", True):
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#080d14",
            plot_bgcolor="#0d141f",
            font=dict(color="#eef3fa"),
            xaxis=dict(
                gridcolor="rgba(255,255,255,0.10)",
                zerolinecolor="rgba(255,255,255,0.16)",
            ),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.10)",
                zerolinecolor="rgba(255,255,255,0.16)",
            ),
        )
    else:
        fig.update_layout(
            template="plotly_white",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(color="#111827"),
            xaxis=dict(
                gridcolor="rgba(0,0,0,0.08)",
                zerolinecolor="rgba(0,0,0,0.14)",
            ),
            yaxis=dict(
                gridcolor="rgba(0,0,0,0.08)",
                zerolinecolor="rgba(0,0,0,0.14)",
            ),
        )
    return fig


def candle_chart(hist, kalshi_target=np.nan):
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
    fig.add_trace(
        go.Scatter(
            x=tail["time"], y=tail["ema9"],
            name="EMA 9", line=dict(width=1)
        )
    )
    fig.add_trace(
        go.Scatter(
            x=tail["time"], y=tail["ema21"],
            name="EMA 21", line=dict(width=1)
        )
    )

    if pd.notna(kalshi_target):
        fig.add_hline(
            y=kalshi_target,
            line_dash="solid",
            line_width=4,
            opacity=1.0,
            annotation_text=f"KALSHI TARGET  ${kalshi_target:,.2f}",
            annotation_position="top left",
            annotation_bgcolor="rgba(0,0,0,0.75)",
            annotation_font=dict(size=14),
        )

    fig.update_layout(
        height=430,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend_orientation="h",
        uirevision="btc-broader-market",
        transition_duration=0,
    )
    apply_plotly_theme(fig)
    return fig


def kalshi_15m_chart(hist, spot_price, kctx, projected_end=np.nan):
    """
    AGGR-style Kalshi view:
    - 1-minute BTC candles
    - fixed Kalshi target for the current contract
    - stable uirevision so refreshes do not reset the chart
    - no rangeslider / minimal chrome
    """
    tail = hist.tail(32).copy()

    # Keep only a useful window around the active 15-minute contract,
    # while retaining a little context before it opened.
    if kctx.get("close_time"):
        try:
            close_ts = pd.Timestamp(kctx["close_time"])
            if close_ts.tzinfo is None:
                close_ts = close_ts.tz_localize("UTC")
            open_ts = close_ts - pd.Timedelta(minutes=15)
            context_start = open_ts - pd.Timedelta(minutes=5)
            filtered = tail[tail["time"] >= context_start]
            if len(filtered) >= 6:
                tail = filtered
        except Exception:
            pass

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=tail["time"],
            open=tail["open"],
            high=tail["high"],
            low=tail["low"],
            close=tail["close"],
            name="BTC 1m",
            increasing_line_width=1.8,
            decreasing_line_width=1.8,
            increasing_fillcolor="#12b886",
            increasing_line_color="#12b886",
            decreasing_fillcolor="#fa5252",
            decreasing_line_color="#fa5252",
            whiskerwidth=0.35,
        )
    )

    target = kctx.get("target", np.nan)
    ticker = kctx.get("ticker", "KXBTC15M")

    if pd.notna(target):
        fig.add_hline(
            y=target,
            line_dash="solid",
            line_width=4,
            line_color="#ffd43b",
            opacity=1.0,
            annotation_text=f"KALSHI TARGET  ${target:,.2f}",
            annotation_position="top left",
            annotation_bgcolor="rgba(8,13,20,0.92)",
            annotation_bordercolor="#ffd43b",
            annotation_borderwidth=1,
            annotation_font=dict(size=14, color="#fff3bf"),
        )

    # Current live BTC marker: updates without changing the target.
    now = pd.Timestamp.now(tz="UTC")
    fig.add_trace(
        go.Scatter(
            x=[now],
            y=[spot_price],
            mode="markers",
            marker=dict(size=8, symbol="circle"),
            name="BTC now",
            hovertemplate="BTC now: $%{y:,.2f}<extra></extra>",
        )
    )

    if pd.notna(projected_end):
        fig.add_trace(
            go.Scatter(
                x=[now],
                y=[projected_end],
                mode="markers",
                marker=dict(size=9, symbol="diamond"),
                name="AI projected end",
                hovertemplate="AI projected end: $%{y:,.2f}<extra></extra>",
            )
        )

    # Preserve zoom/pan and avoid a full visual reset every Streamlit refresh.
    fig.update_layout(
        uirevision=f"kalshi-{ticker}",
        height=430,
        margin=dict(l=8, r=8, t=18, b=8),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        dragmode="pan",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="left",
            x=0,
        ),
        transition_duration=0,
    )

    # AGGR-like minimal chart chrome.
    fig.update_xaxes(
        showgrid=False,
        showline=False,
        zeroline=False,
        fixedrange=False,
    )
    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        side="right",
        fixedrange=False,
        tickformat="$,.0f",
    )

    apply_plotly_theme(fig)
    return fig

# ============================================================
# STARTUP
# ============================================================

init_db()

st.title("₿ BTC AI Trading Command Center")
st.markdown('<div class="paper-banner">PAPER TRADING ONLY — no real-money execution code or exchange keys are included.</div>', unsafe_allow_html=True)
st.caption(f"Single-file build {APP_VERSION} • Kalshi BTC multi-AI self-learning engine • 24/7 remote learner • rolling 100/500/1000-window accuracy • paper-only")

# ============================================================
# SIDEBAR
# ============================================================

# Persistent browser-side Kalshi 15-minute countdown.
# It polls Kalshi directly and ticks locally every second so the timer stays smooth
# even when the Streamlit dashboard itself is not rerunning.
_kalshi_timer_html = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html,body{margin:0;padding:0;background:transparent;color:#f5f9ff;font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
  .kalshi-sidebar-timer{box-sizing:border-box;width:100%;border:1.5px solid #1687ff;border-radius:14px;padding:14px 14px 12px;background:linear-gradient(180deg,rgba(7,26,48,.98),rgba(5,20,37,.98));box-shadow:0 10px 26px rgba(0,0,0,.22),0 0 0 1px rgba(22,135,255,.10) inset;}
  .timer-title{font-size:18px;font-weight:800;letter-spacing:.01em;margin:0 0 10px 0;}
  .timer-main{display:flex;align-items:center;gap:12px;}
  .clock{width:46px;height:46px;border:6px solid #1687ff;border-radius:50%;position:relative;box-sizing:border-box;box-shadow:0 0 18px rgba(22,135,255,.28);flex:0 0 auto;}
  .clock:before{content:"";position:absolute;left:18px;top:8px;width:4px;height:15px;background:#1687ff;border-radius:3px;transform-origin:bottom center;}
  .clock:after{content:"";position:absolute;left:18px;top:20px;width:13px;height:4px;background:#1687ff;border-radius:3px;transform:rotate(35deg);transform-origin:left center;}
  .countdown{font-size:42px;line-height:1;font-weight:850;letter-spacing:.02em;font-variant-numeric:tabular-nums;}
  .track{height:12px;border-radius:999px;background:#24496d;margin-top:13px;overflow:hidden;}
  .fill{height:100%;width:0%;border-radius:999px;background:linear-gradient(90deg,#087cff,#18a7ff);transition:width .35s linear;box-shadow:0 0 12px rgba(22,135,255,.35);}
  .meta{display:flex;justify-content:space-between;margin-top:9px;font-size:13px;color:#b9d3ef;font-variant-numeric:tabular-nums;}
  .status{margin-top:7px;font-size:11px;color:#6f8ba8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
</style>
</head>
<body>
<div class="kalshi-sidebar-timer">
  <div class="timer-title">Kalshi 15m Timer</div>
  <div class="timer-main"><div class="clock"></div><div id="countdown" class="countdown">--:--</div></div>
  <div class="track"><div id="fill" class="fill"></div></div>
  <div class="meta"><span id="elapsed">--:-- elapsed</span><span>15:00 total</span></div>
  <div id="status" class="status">Finding current KXBTC15M market…</div>
</div>
<script>
(() => {
  const API='https://external-api.kalshi.com/trade-api/v2';
  const TOTAL=15*60;
  let closeMs=null, ticker='';
  const cd=document.getElementById('countdown');
  const fill=document.getElementById('fill');
  const elapsedEl=document.getElementById('elapsed');
  const status=document.getElementById('status');
  const fmt=(sec)=>{sec=Math.max(0,Math.floor(sec));const m=Math.floor(sec/60),s=sec%60;return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');};
  function render(){
    if(!closeMs){cd.textContent='--:--';fill.style.width='0%';elapsedEl.textContent='--:-- elapsed';return;}
    const remain=Math.max(0,(closeMs-Date.now())/1000);
    const elapsed=Math.max(0,Math.min(TOTAL,TOTAL-remain));
    cd.textContent=fmt(remain);
    elapsedEl.textContent=fmt(elapsed)+' elapsed';
    fill.style.width=(Math.max(0,Math.min(1,elapsed/TOTAL))*100).toFixed(2)+'%';
    if(remain<=0){ status.textContent='Market ended — loading next 15m market…'; }
  }
  function closeTime(m){const raw=m?.close_time||m?.expiration_time||m?.expected_expiration_time;const t=Date.parse(raw||'');return Number.isFinite(t)?t:null;}
  async function refreshMarket(){
    try{
      const r=await fetch(API+'/markets?limit=100&status=open&series_ticker=KXBTC15M',{cache:'no-store'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const j=await r.json();
      const now=Date.now();
      const rows=(j.markets||[]).map(m=>({m,t:closeTime(m)})).filter(x=>x.t&&x.t>now).sort((a,b)=>a.t-b.t||String(a.m.ticker||'').localeCompare(String(b.m.ticker||'')));
      if(!rows.length){closeMs=null;ticker='';status.textContent='No open KXBTC15M market found';render();return;}
      ticker=String(rows[0].m.ticker||'');
      closeMs=rows[0].t;
      status.textContent=ticker;
      render();
    }catch(e){status.textContent='Kalshi timer reconnecting…';}
  }
  render(); refreshMarket();
  setInterval(render,250);
  setInterval(refreshMarket,5000);
})();
</script>
</body>
</html>
"""
with st.sidebar:
    components.html(_kalshi_timer_html, height=205, scrolling=False)

st.sidebar.header("Command Center")

dark_mode = st.sidebar.toggle(
    "🌙 Dark Mode",
    value=True,
    key="dashboard_dark_mode",
    help="Switch the command center and charts between dark and light mode.",
)

# ============================================================
# VISUAL APP SHELL — R21
# Keeps all trading/learning logic intact; changes presentation only.
# ============================================================
if dark_mode:
    st.markdown(
        """
        <style>
        :root {
            --cc-bg:#050b14;
            --cc-panel:#081525;
            --cc-panel2:#0b1a2d;
            --cc-border:#18324f;
            --cc-text:#f4f8ff;
            --cc-muted:#94a8c6;
            --cc-blue:#1687ff;
            --cc-green:#00e6b3;
            --cc-red:#ff4964;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: radial-gradient(circle at 65% -10%, #0b213b 0%, #050b14 38%, #030811 100%) !important;
            color: var(--cc-text) !important;
        }
        [data-testid="stHeader"] {background: rgba(3,8,17,.72) !important;}
        [data-testid="stToolbar"] {background: transparent !important;}
        .block-container {max-width: 1500px; padding-top: 1rem !important;}

        /* Sidebar */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg,#071321 0%,#06101c 100%) !important;
            border-right: 1px solid var(--cc-border) !important;
        }
        [data-testid="stSidebar"] > div:first-child {background: transparent !important;}
        [data-testid="stSidebar"] * {color: var(--cc-text);}
        [data-testid="stSidebar"] h2 {
            font-size: 1.45rem !important;
            letter-spacing: -.02em;
            margin-bottom: .7rem !important;
        }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p {color:#d9e5f5 !important;}
        [data-testid="stSidebar"] [data-baseweb="slider"] {padding-top:.15rem;}
        [data-testid="stSidebar"] [role="switch"][aria-checked="true"] {background:var(--cc-blue) !important;}

        /* Tabs as compact navigation */
        [data-testid="stTabs"] [role="tablist"] {
            gap:.35rem !important;
            background:#071322 !important;
            border:1px solid var(--cc-border) !important;
            border-radius:12px !important;
            padding:.35rem !important;
            overflow-x:auto !important;
        }
        [data-testid="stTabs"] [role="tab"] {
            border-radius:8px !important;
            padding:.55rem .78rem !important;
            color:#9fb2ce !important;
            background:transparent !important;
        }
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
            background:linear-gradient(180deg,#0f64c7,#0a4fa8) !important;
            color:#fff !important;
            box-shadow:0 0 0 1px rgba(72,159,255,.24) inset !important;
        }
        [data-baseweb="tab-highlight"] {display:none !important;}

        /* Cards / metrics */
        [data-testid="stMetric"] {
            background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96)) !important;
            border:1px solid #1687ff !important;
            border-radius:13px !important;
            padding:.85rem 1rem !important;
            min-height:92px !important;
            box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.08) inset !important;
        }
        [data-testid="stMetric"]:hover {border-color:#4aa3ff !important;}
        [data-testid="stTabs"] [data-testid="stVerticalBlock"] > div {
            border-radius:12px;
        }
        [data-testid="stTabs"] h2, [data-testid="stTabs"] h3 {
            padding-bottom:.35rem;
            border-bottom:1px solid rgba(22,135,255,.24);
        }
        [data-testid="stMetricLabel"] {color:var(--cc-muted) !important;}
        [data-testid="stMetricValue"] {color:var(--cc-text) !important; font-weight:750 !important;}
        [data-testid="stMetricDelta"] {font-weight:650 !important;}

        /* Dataframes/tables */
        [data-testid="stDataFrame"], [data-testid="stTable"] {
            background:#071321 !important;
            border:1px solid var(--cc-border) !important;
            border-radius:13px !important;
            overflow:hidden !important;
            box-shadow:0 10px 28px rgba(0,0,0,.16) !important;
        }
        [data-testid="stDataFrame"] * {color:#dbe7f7 !important;}
        [data-testid="stDataFrame"] canvas {filter:none !important;}

        /* Expanders, forms, inputs */
        [data-testid="stExpander"], [data-testid="stForm"] {
            background:rgba(8,21,37,.95) !important;
            border:1px solid var(--cc-border) !important;
            border-radius:12px !important;
        }
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div,
        input, textarea {
            background:#081626 !important;
            color:#f4f8ff !important;
            border-color:#274564 !important;
        }

        /* Alerts and banners */
        [data-testid="stAlert"] {
            background:linear-gradient(180deg,#0a1a2d,#081522) !important;
            border:1px solid #1687ff !important;
            border-radius:12px !important;
            color:#eaf2ff !important;
            box-shadow:0 8px 22px rgba(0,0,0,.14) !important;
        }
        .paper-banner {
            background:linear-gradient(90deg,rgba(0,230,179,.12),rgba(22,135,255,.08)) !important;
            border:1px solid rgba(0,230,179,.35) !important;
            color:#dffcf5 !important;
        }

        /* Typography */
        h1,h2,h3,h4 {color:#f7fbff !important; letter-spacing:-.018em;}
        p, li, span {text-rendering:optimizeLegibility;}
        hr {border-color:#17314d !important;}

        /* Buttons */
        .stButton > button, .stDownloadButton > button {
            background:linear-gradient(180deg,#0e5fbd,#0a4a98) !important;
            color:white !important;
            border:1px solid #237ad1 !important;
            border-radius:9px !important;
            box-shadow:none !important;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color:#50a5ff !important;
            transform:translateY(-1px);
        }

        /* Make the AI Council feel like the mockup */
        div[data-testid="stVerticalBlock"] > div:has(h3) {
            border-color:transparent;
        }

        /* Mobile/tablet fit */
        @media (max-width:900px) {
            .block-container {padding-left:.7rem !important; padding-right:.7rem !important;}
            [data-testid="stMetric"] {padding:.7rem .75rem !important;}
            [data-testid="stTabs"] [role="tab"] {white-space:nowrap !important;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
        html, body, [data-testid="stAppViewContainer"], .stApp {background:#f4f7fb !important; color:#142033 !important;}
        [data-testid="stSidebar"] {background:#ffffff !important; border-right:1px solid #dfe7f0 !important;}
        [data-testid="stMetric"], [data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stExpander"] {
            background:#ffffff !important; border:1px solid #dfe7f0 !important; border-radius:12px !important;
        }
        [data-testid="stTabs"] [role="tablist"] {background:#fff !important; border:1px solid #dfe7f0 !important; border-radius:12px !important; padding:.3rem !important;}
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {background:#e9f3ff !important; color:#075eb5 !important; border-radius:8px !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )


auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
refresh_seconds = st.sidebar.select_slider("Dashboard refresh", options=[1, 2, 3, 5, 10, 15, 30, 60], value=3)
record_predictions = st.sidebar.checkbox("Auto-journal predictions", value=True)
show_raw = st.sidebar.checkbox("Show diagnostics", value=False)

db_auto_state = get_auto_state()
if "auto_paper_enabled" not in st.session_state:
    st.session_state.auto_paper_enabled = bool(db_auto_state["enabled"])
auto_paper_enabled = st.sidebar.toggle(
    "AUTO PAPER TRADING",
    key="auto_paper_enabled",
    help="Automatically opens and manages simulated long/short BTC positions. PAPER ONLY.",
)
if bool(db_auto_state["enabled"]) != bool(auto_paper_enabled):
    set_auto_enabled(auto_paper_enabled)
    db_auto_state = get_auto_state()

if auto_paper_enabled:
    st.sidebar.success("AUTO PAPER: ON")
    st.sidebar.caption("Approved signals execute automatically. Stops, targets, reversals and the 15-minute horizon can close positions.")
    # Automatic execution requires the Streamlit session to keep rerunning.
    auto_refresh = True
else:
    st.sidebar.info("AUTO PAPER: OFF")

st.sidebar.divider()
st.sidebar.subheader("Safety")
st.sidebar.warning("Paper trading only. This app intentionally contains no live order endpoint and asks for no exchange API key.")
if st.sidebar.button("Reset paper account", use_container_width=True):
    reset_account()
    st.sidebar.success("Paper account reset.")
    st.rerun()

# ============================================================
# SMOOTH LIVE DASHBOARD
# ============================================================
# A fragment reruns independently from the rest of the Streamlit app.
# This avoids the full-page rebuild/flash caused by time.sleep()+st.rerun().
live_run_every = refresh_seconds if auto_refresh else None

# ============================================================
# LIVE CHART ANTI-FLASH
# ============================================================

st.markdown(
    """
    <style>
    /* Streamlit marks old fragment elements as stale while the replacement
       is being computed. Keep the market chart fully visible instead of
       dimming/fading during that short interval. */
    [data-testid="stPlotlyChart"],
    [data-testid="stPlotlyChart"] *,
    [data-stale="true"] [data-testid="stPlotlyChart"],
    [data-stale="true"] [data-testid="stPlotlyChart"] *,
    [data-testid="stPlotlyChart"][data-stale="true"],
    [data-testid="stPlotlyChart"][data-stale="true"] *,
    .js-plotly-plot,
    .js-plotly-plot *,
    .plot-container,
    .plot-container *,
    .svg-container,
    .svg-container * {
        opacity: 1 !important;
        filter: none !important;
        transition: none !important;
        animation: none !important;
        -webkit-transition: none !important;
        -webkit-animation: none !important;
    }

    /* Keep the old canvas/SVG visible until the new candle data replaces it. */
    [data-stale="true"] .js-plotly-plot,
    [data-stale="true"] .plot-container,
    [data-stale="true"] .svg-container {
        visibility: visible !important;
        opacity: 1 !important;
    }

    /* Plotly trace layers should snap to the new values rather than fade. */
    .js-plotly-plot .trace,
    .js-plotly-plot .scatterlayer,
    .js-plotly-plot .candlesticklayer,
    .js-plotly-plot .overplot,
    .js-plotly-plot .cartesianlayer,
    .js-plotly-plot .modebar {
        transition: none !important;
        animation: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# PERSISTENT LIVE MARKET CHART
# ============================================================

def persistent_kalshi_market_chart(initial_hist, initial_target, initial_ticker, dark_mode=True, learning_state=None):
    """
    Browser-side Plotly chart.

    Unlike st.plotly_chart inside a Streamlit fragment, this iframe is mounted
    outside the live dashboard fragment. JavaScript updates the existing Plotly
    graph in place, so Streamlit does not remove/recreate the chart each refresh.
    """

    tail = initial_hist.tail(60).copy() if initial_hist is not None else pd.DataFrame()

    initial_rows = []
    if not tail.empty:
        for _, row in tail.iterrows():
            try:
                ts = pd.Timestamp(row["time"]).isoformat()
                initial_rows.append(
                    {
                        "time": ts,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    }
                )
            except Exception:
                continue

    payload = json.dumps(
        {
            "candles": initial_rows,
            "target": (
                float(initial_target)
                if pd.notna(initial_target)
                else None
            ),
            "ticker": initial_ticker or "",
            "dark": bool(dark_mode),
            "learning": learning_state or get_learning_state(),
        }
    ).replace("</", "<\\/")

    bg = "#0d141f" if dark_mode else "#ffffff"
    paper = "#080d14" if dark_mode else "#ffffff"
    fg = "#eef3fa" if dark_mode else "#111827"
    grid = "rgba(255,255,255,0.10)" if dark_mode else "rgba(0,0,0,0.09)"

    html = f"""
    <div id="market-wrap" style="
        width:100%;
        background:{bg};
        border-radius:10px;
        overflow:hidden;
        min-height:445px;
    ">
        <div id="market-status" style="
            height:26px;
            padding:5px 10px 0 10px;
            color:{fg};
            font-family:Arial,sans-serif;
            font-size:12px;
            opacity:.82;
            box-sizing:border-box;
        ">Live BTC 1m candles • predicted 15m candle path • Kalshi target</div>
        <div id="persistent-market-chart" style="width:100%;height:415px;"></div>
    </div>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
    (() => {{
        const initial = {payload};
        const chart = document.getElementById("persistent-market-chart");
        const status = document.getElementById("market-status");

        let currentTarget = initial.target;
        let currentTicker = initial.ticker || "";
        let lastCandleSignature = "";
        let busy = false;

        const learning = initial.learning || {{}};
        const W_RET3 = Number(learning.w_ret3 ?? 0.46);
        const W_RET8 = Number(learning.w_ret8 ?? 0.34);
        const W_RET15 = Number(learning.w_ret15 ?? 0.20);
        const MOMENTUM_SCALE = Number(learning.momentum_scale ?? 2.20);
        const TARGET_INFLUENCE = Number(learning.target_influence ?? 0.18);
        const MODEL_BIAS = Number(learning.bias ?? 0.0);

        const paperBg = "{paper}";
        const plotBg = "{bg}";
        const fontColor = "{fg}";
        const gridColor = "{grid}";

        function candleTrace(rows) {{
            return {{
                type: "candlestick",
                x: rows.map(r => r.time),
                open: rows.map(r => r.open),
                high: rows.map(r => r.high),
                low: rows.map(r => r.low),
                close: rows.map(r => r.close),
                name: "BTC 1m",
                increasing: {{
                    line: {{color:"#12b886", width:1.7}},
                    fillcolor:"#12b886"
                }},
                decreasing: {{
                    line: {{color:"#fa5252", width:1.7}},
                    fillcolor:"#fa5252"
                }},
                whiskerwidth: 0.35,
                hoverinfo: "x+open+high+low+close"
            }};
        }}

        function predictedCandles(rows) {{
            if (!rows || rows.length < 12) return [];

            const closes = rows.map(r => Number(r.close)).filter(Number.isFinite);
            if (closes.length < 12) return [];

            const n = closes.length;
            const last = closes[n - 1];

            const ret3 = n >= 4 ? (last / closes[n - 4] - 1) : 0;
            const ret8 = n >= 9 ? (last / closes[n - 9] - 1) : 0;
            const ret15 = n >= 16 ? (last / closes[n - 16] - 1) : ret8;

            const recent = rows.slice(-20);
            const avgRange = recent.reduce((sum, r) => {{
                const hi = Number(r.high);
                const lo = Number(r.low);
                return sum + (
                    Number.isFinite(hi) && Number.isFinite(lo)
                    ? Math.max(0, hi - lo)
                    : 0
                );
            }}, 0) / Math.max(1, recent.length);

            let directional =
                W_RET3 * ret3 +
                W_RET8 * ret8 +
                W_RET15 * ret15 +
                MODEL_BIAS;

            directional = Math.max(-0.012, Math.min(0.012, directional));

            let projectedMove = last * directional * MOMENTUM_SCALE;

            if (Number.isFinite(currentTarget)) {{
                const gap = currentTarget - last;
                const maxInfluence = Math.max(
                    avgRange * 2.0,
                    last * 0.0015
                );
                const targetInfluence = Math.max(
                    -maxInfluence,
                    Math.min(maxInfluence, gap * TARGET_INFLUENCE)
                );
                projectedMove += targetInfluence;
            }}

            const minVisible = Math.max(
                avgRange * 0.35,
                last * 0.00015
            );

            if (Math.abs(projectedMove) < minVisible) {{
                projectedMove =
                    Math.sign(projectedMove || directional || 1) * minVisible;
            }}

            const forecast = [];
            let prevClose = last;
            const lastTime = new Date(
                rows[rows.length - 1].time
            ).getTime();

            for (let i = 1; i <= 15; i++) {{
                const progress = i / 15;
                const eased = progress * progress * (3 - 2 * progress);
                const center = last + projectedMove * eased;

                const wave =
                    Math.sin(i * 1.35) * avgRange * 0.16 +
                    Math.cos(i * 0.72) * avgRange * 0.08;

                const close = center + wave;
                const open = prevClose;

                const body = Math.abs(close - open);
                const wickBase = Math.max(
                    avgRange * (0.18 + 0.08 * progress),
                    body * 0.35
                );

                const high = Math.max(open, close) + wickBase;
                const low = Math.min(open, close) - wickBase;

                forecast.push({{
                    time: new Date(
                        lastTime + i * 60000
                    ).toISOString(),
                    open,
                    high,
                    low,
                    close
                }});

                prevClose = close;
            }}

            return forecast;
        }}

        function predictionTrace(rows) {{
            const forecast = predictedCandles(rows);

            return {{
                type: "candlestick",
                x: forecast.map(r => r.time),
                open: forecast.map(r => r.open),
                high: forecast.map(r => r.high),
                low: forecast.map(r => r.low),
                close: forecast.map(r => r.close),
                name: "Predicted 15m candles",
                increasing: {{
                    line: {{
                        color:"rgba(77,171,247,0.88)",
                        width:1.5
                    }},
                    fillcolor:"rgba(77,171,247,0.28)"
                }},
                decreasing: {{
                    line: {{
                        color:"rgba(186,104,200,0.88)",
                        width:1.5
                    }},
                    fillcolor:"rgba(186,104,200,0.25)"
                }},
                whiskerwidth: 0.28,
                hoverinfo: "x+open+high+low+close",
                opacity: 0.78
            }};
        }}

        function predictionPathTrace(rows) {{
            const forecast = predictedCandles(rows);

            if (!forecast.length) {{
                return {{
                    type: "scatter",
                    mode: "lines",
                    x: [],
                    y: [],
                    name: "Prediction path"
                }};
            }}

            const lastReal = rows[rows.length - 1];

            return {{
                type: "scatter",
                mode: "lines",
                x: [
                    lastReal.time,
                    ...forecast.map(r => r.time)
                ],
                y: [
                    lastReal.close,
                    ...forecast.map(r => r.close)
                ],
                name: "Prediction path",
                line: {{
                    color: "#4dabf7",
                    width: 2,
                    dash: "dot"
                }},
                hovertemplate:
                    "Predicted $%{{y:,.2f}}<extra></extra>"
            }};
        }}

        function targetShape() {{
            if (!Number.isFinite(currentTarget)) return [];
            return [{{
                type: "line",
                xref: "paper",
                x0: 0,
                x1: 1,
                yref: "y",
                y0: currentTarget,
                y1: currentTarget,
                line: {{
                    color: "#ffd43b",
                    width: 4
                }}
            }}];
        }}

        function targetAnnotation() {{
            if (!Number.isFinite(currentTarget)) return [];
            return [{{
                xref: "paper",
                x: 0.01,
                yref: "y",
                y: currentTarget,
                text: "KALSHI TARGET  $" + currentTarget.toLocaleString(undefined, {{
                    minimumFractionDigits:2,
                    maximumFractionDigits:2
                }}),
                showarrow: false,
                xanchor: "left",
                yanchor: "bottom",
                bgcolor: "rgba(8,13,20,0.90)",
                bordercolor: "#ffd43b",
                borderwidth: 1,
                font: {{size: 13, color:"#fff3bf"}}
            }}];
        }}

        const layout = {{
            paper_bgcolor: paperBg,
            plot_bgcolor: plotBg,
            font: {{color: fontColor}},
            margin: {{l:8,r:62,t:34,b:28}},
            xaxis: {{
                rangeslider: {{visible:false}},
                showgrid:false,
                zeroline:false,
                fixedrange:false
            }},
            yaxis: {{
                side:"right",
                gridcolor:gridColor,
                zeroline:false,
                tickprefix:"$",
                tickformat:",.0f",
                fixedrange:false
            }},
            hovermode:"x unified",
            dragmode:"pan",
            showlegend:true,
            legend:{{
                orientation:"h",
                x:0,
                y:1.04,
                bgcolor:"rgba(0,0,0,0)"
            }},
            uirevision:"persistent-kalshi-market",
            shapes: targetShape(),
            annotations: targetAnnotation(),
            transition: {{duration:0}}
        }};

        const config = {{
            displaylogo:false,
            responsive:true,
            scrollZoom:true,
            doubleClick:"reset",
            displayModeBar:"hover"
        }};

        let rows = initial.candles || [];

        Plotly.newPlot(
            chart,
            [
                candleTrace(rows),
                predictionTrace(rows),
                predictionPathTrace(rows)
            ],
            layout,
            config
        );

        function signature(data) {{
            if (!data || !data.length) return "";
            const last = data[data.length - 1];
            return [
                data.length,
                last.time,
                last.open,
                last.high,
                last.low,
                last.close
            ].join("|");
        }}

        async function fetchCandles() {{
            const urls = [
                "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60",
                "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60"
            ];

            let payload = null;
            for (const url of urls) {{
                try {{
                    const resp = await fetch(url, {{cache:"no-store"}});
                    if (!resp.ok) continue;
                    payload = await resp.json();
                    if (Array.isArray(payload)) break;
                }} catch (e) {{}}
            }}

            if (!Array.isArray(payload)) return null;

            return payload.map(k => ({{
                time: new Date(k[0]).toISOString(),
                open: Number(k[1]),
                high: Number(k[2]),
                low: Number(k[3]),
                close: Number(k[4])
            }}));
        }}

        function parseTime(value) {{
            if (!value) return NaN;
            const ms = Date.parse(value);
            return Number.isFinite(ms) ? ms : NaN;
        }}

        function numericKalshiTarget(m) {{
            if (!m) return NaN;
            for (const key of ["yes_sub_title", "subtitle", "title"]) {{
                const text = String(m[key] || "");
                const hit = text.match(/Target\s*Price\s*:\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)/i);
                if (hit) {{
                    const explicitTarget = Number(hit[1].replace(/,/g, ""));
                    if (Number.isFinite(explicitTarget) && explicitTarget > 0) return explicitTarget;
                }}
            }}
            const strikeType = String(m.strike_type || "").toLowerCase();
            const preferCap = ["less", "less_equal", "less-than", "less_than"].includes(strikeType);
            const first = Number(preferCap ? m.cap_strike : m.floor_strike);
            const second = Number(preferCap ? m.floor_strike : m.cap_strike);
            if (Number.isFinite(first) && first > 0) return first;
            if (Number.isFinite(second) && second > 0) return second;
            return NaN;
        }}

        async function exactKalshiMarket(ticker) {{
            if (!ticker) return null;
            try {{
                const url = "https://external-api.kalshi.com/trade-api/v2/markets/" + encodeURIComponent(ticker);
                const resp = await fetch(url, {{cache:"no-store"}});
                if (!resp.ok) return null;
                const payload = await resp.json();
                return payload && payload.market ? payload.market : null;
            }} catch (e) {{ return null; }}
        }}

        async function fetchKalshiTarget() {{
            const url =
                "https://external-api.kalshi.com/trade-api/v2/markets" +
                "?limit=100&status=open&series_ticker=KXBTC15M";

            try {{
                const resp = await fetch(url, {{cache:"no-store"}});
                if (!resp.ok) return null;
                const payload = await resp.json();
                const markets = Array.isArray(payload.markets) ? payload.markets : [];
                const now = Date.now();

                const parsed = markets.map(m => {{
                    const closeRaw = m.close_time || m.expiration_time || m.expected_expiration_time;
                    return {{
                        raw: m,
                        ticker: String(m.ticker || ""),
                        target: numericKalshiTarget(m),
                        closeMs: parseTime(closeRaw)
                    }};
                }}).filter(m =>
                    Number.isFinite(m.target) && m.target > 0 &&
                    Number.isFinite(m.closeMs) && m.closeMs > now
                );

                const pinned = parsed.find(m => m.ticker === currentTicker);
                let selected = pinned || null;
                if (!selected) {{
                    parsed.sort((a,b) => (a.closeMs - b.closeMs) || a.ticker.localeCompare(b.ticker));
                    selected = parsed.length ? parsed[0] : null;
                }}
                if (!selected) return null;

                const exact = await exactKalshiMarket(selected.ticker);
                if (exact) {{
                    const exactTarget = numericKalshiTarget(exact);
                    const exactClose = parseTime(exact.close_time || exact.expiration_time || exact.expected_expiration_time);
                    if (Number.isFinite(exactTarget) && exactTarget > 0) selected.target = exactTarget;
                    if (Number.isFinite(exactClose)) selected.closeMs = exactClose;
                }}
                return selected;
            }} catch (e) {{ return null; }}
        }}

        async function updateCandles() {{
            if (busy) return;
            busy = true;

            try {{
                const fresh = await fetchCandles();
                if (!fresh || !fresh.length) return;

                const sig = signature(fresh);
                if (sig === lastCandleSignature) return;
                lastCandleSignature = sig;
                rows = fresh;

                // Plotly.react updates the already-mounted graph rather than
                // allowing Streamlit to delete/recreate the chart container.
                await Plotly.react(
                    chart,
                    [
                        candleTrace(rows),
                        predictionTrace(rows),
                        predictionPathTrace(rows)
                    ],
                    {{
                        ...layout,
                        shapes: targetShape(),
                        annotations: targetAnnotation()
                    }},
                    config
                );

                status.textContent =
                    "Live BTC 1m candles • " +
                    (currentTicker ? currentTicker + " • " : "") +
                    "updated " + new Date().toLocaleTimeString();
            }} finally {{
                busy = false;
            }}
        }}

        async function updateTarget() {{
            const market = await fetchKalshiTarget();
            if (!market) return;

            const changed =
                market.ticker !== currentTicker ||
                market.target !== currentTarget;

            if (!changed) return;

            currentTicker = market.ticker;
            currentTarget = market.target;

            // Relayout only the horizontal target + label. Candles remain mounted.
            await Plotly.relayout(chart, {{
                shapes: targetShape(),
                annotations: targetAnnotation()
            }});

            status.textContent =
                "New Kalshi 15m market • " +
                currentTicker +
                " • target $" +
                currentTarget.toLocaleString(undefined, {{
                    minimumFractionDigits:2,
                    maximumFractionDigits:2
                }});
        }}

        // Candle updates are quick but do not rebuild the iframe.
        const candleTimer = setInterval(updateCandles, 1500);

        // Kalshi target only changes when a new 15-minute contract becomes active.
        const kalshiTimer = setInterval(updateTarget, 3000);

        // Prime once after load.
        setTimeout(updateCandles, 250);
        setTimeout(updateTarget, 500);

        window.addEventListener("beforeunload", () => {{
            clearInterval(candleTimer);
            clearInterval(kalshiTimer);
        }});
    }})();
    </script>
    """

    components.html(
        html,
        height=445,
        scrolling=False,
    )


# ============================================================
# DASHBOARD THEME
# ============================================================

if dark_mode:
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #080d14;
            color: #eef3fa;
        }

        [data-testid="stSidebar"] {
            background-color: #0d141f;
            border-right: 1px solid #263244;
        }

        [data-testid="stSidebar"] * {
            color: #eef3fa;
        }

        [data-testid="stHeader"] {
            background-color: rgba(8, 13, 20, 0.92);
        }

        [data-testid="stMetric"] {
            background-color: #0f1825;
            border: 1px solid #2a374a;
            border-radius: 10px;
            padding: 0.45rem 0.6rem;
        }

        [data-testid="stMetricValue"] {
            color: #ffffff;
            font-weight: 750;
        }

        [data-testid="stMetricLabel"] {
            color: #c8d2df;
        }

        [data-testid="stTabs"] button,
        [data-baseweb="tab"] {
            color: #dbe4f0 !important;
            font-weight: 650 !important;
        }

        [data-testid="stTabs"] button[aria-selected="true"],
        [data-baseweb="tab"][aria-selected="true"] {
            color: #ffffff !important;
        }

        [data-testid="stDataFrame"],
        div[data-testid="stExpander"] {
            border-color: #2a374a !important;
        }

        .stButton > button,
        .stDownloadButton > button {
            border-color: #39485d;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #f7f9fc;
            color: #111827;
        }

        [data-testid="stSidebar"] {
            background-color: #ffffff;
            border-right: 1px solid #d8dee9;
        }

        [data-testid="stHeader"] {
            background-color: rgba(255, 255, 255, 0.94);
        }

        [data-testid="stMetric"] {
            background-color: #ffffff;
            border: 1px solid #d8dee9;
            border-radius: 10px;
            padding: 0.45rem 0.6rem;
        }

        [data-testid="stMetricValue"] {
            color: #111827;
            font-weight: 750;
        }

        [data-testid="stMetricLabel"] {
            color: #4b5563;
        }

        [data-testid="stTabs"] button,
        [data-baseweb="tab"] {
            color: #374151 !important;
            font-weight: 650 !important;
        }

        [data-testid="stTabs"] button[aria-selected="true"],
        [data-baseweb="tab"][aria-selected="true"] {
            color: #111827 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )



# ============================================================
# PERSISTENT MARKET PANEL
# This is intentionally OUTSIDE the auto-refreshing fragment.
# ============================================================

try:
    _persistent_raw_hist, _ = fetch_klines("1m", 90)
    _persistent_hist = enrich_history(_persistent_raw_hist)
except Exception:
    _persistent_hist = pd.DataFrame()

try:
    _persistent_ticker = fetch_spot_ticker()
    _persistent_px = safe_float(
        _persistent_ticker.get("price"),
        safe_float(_persistent_hist["close"].iloc[-1])
        if not _persistent_hist.empty else np.nan,
    )
except Exception:
    _persistent_px = (
        safe_float(_persistent_hist["close"].iloc[-1])
        if not _persistent_hist.empty else np.nan
    )

try:
    _persistent_kalshi = fetch_kalshi_bitcoin_markets()
    _persistent_ctx = stable_kalshi_contract(
        _persistent_kalshi,
        _persistent_px,
    )
except Exception:
    _persistent_ctx = {
        "available": False,
        "target": np.nan,
        "ticker": "",
    }

st.subheader("Live Kalshi BTC Market")
st.caption(
    "Persistent AGGR-style candle chart — this chart updates in place "
    "and is not rebuilt by the dashboard refresh."
)

# Grade completed windows and learn before drawing the next forecast.
try:
    _learning_resolved = resolve_forecast_windows(_persistent_hist)
except Exception:
    _learning_resolved = 0

try:
    _specialist_learning_resolved = resolve_specialist_learning(_persistent_hist)
except Exception:
    _specialist_learning_resolved = 0

try:
    _close_raw = _persistent_ctx.get("close_time")
    _active_close_ts = (
        pd.Timestamp(_close_raw).timestamp()
        if _close_raw else np.nan
    )

    register_forecast_window(
        _persistent_ctx.get("ticker", ""),
        _active_close_ts,
        _persistent_hist.tail(60).to_dict("records"),
        _persistent_ctx.get("target", np.nan),
    )
except Exception:
    pass

_learning_state = get_learning_state()

persistent_kalshi_market_chart(
    _persistent_hist,
    _persistent_ctx.get("target", np.nan),
    _persistent_ctx.get("ticker", ""),
    dark_mode=dark_mode,
    learning_state=_learning_state,
)

if _learning_state["samples"] > 0:
    _acc = _learning_state["direction_accuracy"] * 100
    st.caption(
        f"Self-learning model: {_learning_state['samples']} completed windows • "
        f"direction accuracy {_acc:.1f}% • "
        f"avg final-price error ${_learning_state['avg_abs_error']:,.2f} • "
        f"avg path error ${_learning_state['avg_path_error']:,.2f}"
        + (
            f" • official Kalshi accuracy {_learning_state.get('kalshi_hits', 0) / _learning_state.get('kalshi_samples', 1) * 100:.1f}% "
            f"({_learning_state.get('kalshi_samples', 0)} settled)"
            if _learning_state.get('kalshi_samples', 0) else ""
        )
    )
else:
    st.caption(
        "Self-learning model is active. Accuracy statistics will appear after "
        "the first completed 15-minute Kalshi window is graded."
    )

@st.fragment(run_every=live_run_every)
def live_dashboard():

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
    hourly_kalshi = fetch_kalshi_hourly_bitcoin_markets()

    if hist.empty:
        st.error("Price history is unavailable, so the AI engine cannot run safely right now.")
        if errors:
            st.code("\n".join(errors))
        st.stop()

    price = safe_float(ticker.get("price"), safe_float(hist["close"].iloc[-1]))
    if pd.isna(price):
        price = float(hist["close"].iloc[-1])

    results = run_specialists(hist, agg, futures, kalshi)
    # Let every specialist learn independently from this Kalshi window.
    try:
        _learn_ctx = stable_kalshi_contract(kalshi, price)
        _learn_close_raw = _learn_ctx.get("close_time")
        _learn_close_ts = (
            pd.Timestamp(_learn_close_raw).timestamp()
            if _learn_close_raw else np.nan
        )

        register_specialist_window_predictions(
            _learn_ctx.get("ticker", ""),
            _learn_close_ts,
            price,
            _learn_ctx.get("target", np.nan),
            results,
        )
    except Exception:
        pass

    decision = master_decision(results, hist, kalshi)
    hourly_ai = hourly_kalshi_target_ai(hist, results, hourly_kalshi, price)
    account = get_account(price)
    risk = risk_evaluate(decision, account, hist, futures)

    auto_result = manage_auto_paper(decision, risk, price, hist)
    if auto_result.get("event"):
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
    with m3:
        st.markdown(
            f'<div class="direction-card metric-direction-card"><div class="direction-card-label">Master</div><div class="direction-card-value">{directional_badge_html(decision["action"])}</div></div>',
            unsafe_allow_html=True,
        )
    m4.metric("Confidence", f"{decision['confidence']*100:.1f}%")
    m5.metric("Consensus", f"{decision['consensus']*100:.1f}%")
    m6.metric("Spot feed", "N/A" if pd.isna(ticker.get("feed_ms")) else f"{ticker['feed_ms']:.0f} ms")

    st.caption(
        f"Dashboard cycle {full_cycle_ms:.0f} ms • kline request {kline_ms:.0f} ms • agg-trade request {agg_ms:.0f} ms • "
        f"futures snapshot {futures.get('feed_ms', np.nan):.0f} ms • Kalshi target cache 3s"
    )

    # ============================================================
    # TABS
    # ============================================================

    tab_market, tab_ai, tab_hourly, tab_flow, tab_paper, tab_journal, tab_learning, tab_backtest = st.tabs(
        [
            "Market",
            "AI Council",
            "Hourly Kalshi AI",
            "Order Flow + Kalshi",
            "Paper Trading",
            "Prediction Journal",
            "Learning",
            "Backtest",
        ]
    )

    with tab_market:
        kctx = stable_kalshi_contract(kalshi, price)

        st.subheader("Kalshi BTC 15-minute target tracker")

        if kctx["available"]:
            rem = (
                int(kctx["seconds_remaining"])
                if pd.notna(kctx["seconds_remaining"]) else 0
            )
            minutes, seconds = divmod(max(0, rem), 60)

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Kalshi target", fmt_money(kctx["target"]))
            k2.metric("BTC now", fmt_money(price))
            k3.metric("Vs target", f"${kctx['distance']:+,.2f}")
            k4.metric("Time left", f"{minutes:02d}:{seconds:02d}")
            k5.metric(
                "UP price",
                (
                    "N/A"
                    if pd.isna(kctx["up_probability"])
                    else f"{kctx['up_probability']*100:.1f}%"
                ),
            )
            k6.metric(
                "DOWN price",
                (
                    "N/A"
                    if pd.isna(kctx["up_probability"])
                    else f"{(1.0-kctx['up_probability'])*100:.1f}%"
                ),
            )

            st.caption(
                "The live candlestick chart is pinned above the tabs so it can "
                "update continuously without Streamlit rebuilding it."
            )

            side_text = (
                "UP"
                if decision["action"] in {"SCALP UP", "LOCK UP"}
                else "DOWN"
                if decision["action"] in {"SCALP DOWN", "LOCK DOWN"}
                else "WAIT"
            )

            call1, call2, call3, call4 = st.columns(4)
            with call1:
                st.markdown(
                    f'<div class="direction-card metric-direction-card"><div class="direction-card-label">CALL</div><div class="direction-card-value">{directional_badge_html(decision["action"])}</div></div>',
                    unsafe_allow_html=True,
                )
            call2.metric("Side", side_text)
            call3.metric(
                "AI projected end", fmt_money(decision["projected_end"])
            )
            call4.metric(
                "Confidence", f"{decision['confidence']*100:.1f}%"
            )

            if decision["action"] == "SCALP UP":
                st.success("SCALP UP → paper signal is to BUY UP.")
            elif decision["action"] == "SCALP DOWN":
                st.error("SCALP DOWN → paper signal is to BUY DOWN.")
            elif decision["action"] in {"LOCK UP", "LOCK DOWN"}:
                st.warning(
                    f"LOCK {decision['locked_side']} → hold this call "
                    "to the end of the current Kalshi 15-minute market."
                )
            else:
                st.info("HOLD → no Kalshi side has enough edge yet.")

            st.caption(
                f"Live Kalshi market: {kctx['ticker']} • target is fetched from "
                "that exact Kalshi ticker and shared by the chart, LOCK/SCALP engine, "
                "paper signals, and learner. The candles use this app's Binance 1-minute feed "
                "as a real-time proxy; official Kalshi settlement follows "
                "Kalshi's stated reference methodology. "
                "The target line stays fixed for this contract and changes only "
                "when Kalshi rolls to the next 15-minute market."
            )
        else:
            st.warning(
                "Live Kalshi KXBTC15M target is temporarily unavailable."
            )
            st.plotly_chart(
                candle_chart(hist),
                use_container_width=True,
                key="fallback_market_chart",
            )

        st.divider()
        st.subheader("Broader BTC market chart")

        st.plotly_chart(
            candle_chart(
                hist,
                kctx["target"] if kctx["available"] else np.nan
            ),
            use_container_width=True,
            key="btc_market_chart",
            config={
                "displaylogo": False,
                "scrollZoom": True,
                "responsive": True,
            },
        )

        c1, c2, c3, c4 = st.columns(4)
        last = hist.iloc[-1]
        c1.metric("RSI 14", f"{safe_float(last['rsi'], 50):.1f}")
        c2.metric("ATR 14", f"${safe_float(last['atr14'], 0):,.2f}")
        c3.metric(
            "24h quote volume",
            f"${safe_float(ticker.get('quote_volume_24h'), 0):,.0f}",
        )
        c4.metric(
            "Kalshi target",
            fmt_money(kctx["target"]) if kctx["available"] else "N/A",
        )

    with tab_ai:
        st.subheader("Master Kalshi 15-minute Prediction AI")
        d1, d2, d3, d4, d5 = st.columns(5)
        with d1:
            st.markdown(
                f'<div class="direction-card metric-direction-card"><div class="direction-card-label">Call</div><div class="direction-card-value">{directional_badge_html(decision["action"])}</div></div>',
                unsafe_allow_html=True,
            )
        d2.metric("Master score", f"{decision['score']:+.3f}")
        d3.metric("Confidence", f"{decision['confidence']*100:.1f}%")
        d4.metric("Consensus", f"{decision['consensus']*100:.1f}%")
        d5.metric("Risk level", decision["risk_level"])

        # User-friendly AI Council summary
        action = str(decision.get("action", "HOLD"))
        confidence_pct = float(decision.get("confidence", 0.0)) * 100.0
        consensus_pct = float(decision.get("consensus", 0.0)) * 100.0
        score = float(decision.get("score", 0.0))

        if action == "LOCK UP":
            plain_call = "The council expects BTC to finish ABOVE the Kalshi target at expiration."
            call_icon = "🔒⬆️"
        elif action == "LOCK DOWN":
            plain_call = "The council expects BTC to finish BELOW the Kalshi target at expiration."
            call_icon = "🔒⬇️"
        elif action == "SCALP UP":
            plain_call = "The council sees a short-term UP move with enough edge for a paper scalp."
            call_icon = "⚡⬆️"
        elif action == "SCALP DOWN":
            plain_call = "The council sees a short-term DOWN move with enough edge for a paper scalp."
            call_icon = "⚡⬇️"
        else:
            plain_call = "The council does not see a strong enough edge right now. Waiting is the preferred move."
            call_icon = "⏸️"

        if confidence_pct >= 75:
            confidence_word = "Strong"
        elif confidence_pct >= 60:
            confidence_word = "Moderate"
        else:
            confidence_word = "Low"

        if consensus_pct >= 75:
            agreement_word = "Most specialists agree"
        elif consensus_pct >= 55:
            agreement_word = "Council is somewhat split"
        else:
            agreement_word = "Council is heavily divided"

        st.markdown("### Council verdict")
        st.markdown(
            f'<div class="direction-card verdict-card">{directional_badge_html(action)}</div>',
            unsafe_allow_html=True,
        )
        st.write(plain_call)
        s1, s2, s3 = st.columns(3)
        s1.metric("How sure?", f"{confidence_pct:.0f}%", confidence_word)
        s2.metric("How much agreement?", f"{consensus_pct:.0f}%", agreement_word)
        direction_label = "UP" if score > 0.05 else "DOWN" if score < -0.05 else "NEUTRAL"
        s3.metric("Overall lean", direction_label, f"Score {score:+.2f}")

        st.caption(
            "Confidence = how strong the combined signal is. Consensus = how much the specialist AIs agree. "
            "A strong call with low consensus means the council still has meaningful disagreement."
        )
        if decision["action"] in {"LOCK UP", "LOCK DOWN"}:
            st.markdown(directional_badge_html(decision["action"]), unsafe_allow_html=True)
            st.warning(
                f"LOCKED SIDE: {decision['locked_side']} — "
                "hold call until Kalshi market expiration."
            )
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
        council_df = pd.DataFrame(rows)
        if dark_mode:
            # Streamlit's native dataframe canvas stays light even when our custom
            # dashboard dark-mode toggle is enabled, so render the council table
            # as a responsive HTML table in dark mode. Light mode keeps the native table.
            def _signal_badge(value):
                label = str(value).upper()
                if label == "BULLISH":
                    cls = "signal-bullish"
                elif label == "BEARISH":
                    cls = "signal-bearish"
                else:
                    cls = "signal-neutral"
                return f'<span class="signal-badge {cls}">{label}</span>'

            table_html = council_df.to_html(
                index=False,
                border=0,
                classes="ai-council-table",
                escape=False,
                formatters={"Signal": _signal_badge},
            )
            st.markdown(
                """
                <style>
                .ai-council-wrap {
                    width: 100%; overflow-x: auto; border: 1px solid #1687ff;
                    border-radius: 12px; background: #0b1220;
                }
                .ai-council-table {
                    width: 100%; border-collapse: collapse; color: #e8eef8;
                    background: #0b1220; font-size: 0.93rem; margin: 0;
                }
                .ai-council-table thead th {
                    position: sticky; top: 0; z-index: 1; text-align: left;
                    color: #b8cff7; background: #111c2e; font-weight: 700;
                    border-bottom: 1px solid #2b3b52; padding: 10px 12px;
                    white-space: nowrap;
                }
                .ai-council-table tbody td {
                    color: #e7edf7; background: #0b1220;
                    border-bottom: 1px solid #1e2b3d; padding: 9px 12px;
                    vertical-align: middle; white-space: nowrap;
                }
                .ai-council-table tbody tr:nth-child(even) td {background: #0f1828;}
                .ai-council-table tbody tr:hover td {background: #15243a;}
                .ai-council-table td:last-child {white-space: normal; min-width: 260px;}
                .signal-badge {
                    display:inline-block; min-width:92px; text-align:center;
                    padding:4px 10px; border-radius:7px; font-weight:800;
                    letter-spacing:.02em; line-height:1.2;
                }
                .signal-bullish {
                    color:#00f0b5; background:rgba(0,240,181,.13);
                    border:1px solid rgba(0,240,181,.80);
                    box-shadow:0 0 12px rgba(0,240,181,.10) inset;
                }
                .signal-bearish {
                    color:#ff536b; background:rgba(255,83,107,.13);
                    border:1px solid rgba(255,83,107,.85);
                    box-shadow:0 0 12px rgba(255,83,107,.10) inset;
                }
                .signal-neutral {
                    color:#b8c6dc; background:rgba(184,198,220,.09);
                    border:1px solid rgba(184,198,220,.42);
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="ai-council-wrap">{table_html}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.dataframe(council_df, use_container_width=True, hide_index=True)

    with tab_hourly:
        st.subheader("Hourly Kalshi BTC Target AI")
        st.caption(
            "Separate 60-minute model. It estimates BTC's most likely price "
            "at the next hourly Kalshi settlement and compares that forecast "
            "with the nearest active Kalshi hourly strike."
        )

        h1, h2, h3, h4 = st.columns(4)
        h1.metric(
            "1-hour AI target",
            fmt_money(hourly_ai["target_price"]),
        )
        h2.metric(
            "Expected move",
            f"${hourly_ai['projected_move']:+,.2f}",
            f"{hourly_ai['projected_move_pct']*100:+.3f}%",
        )
        with h3:
            st.markdown(
                f'<div class="direction-card metric-direction-card"><div class="direction-card-label">Direction</div><div class="direction-card-value">{directional_badge_html(hourly_ai["direction"])}</div></div>',
                unsafe_allow_html=True,
            )
        h4.metric(
            "Confidence",
            f"{hourly_ai['confidence']*100:.1f}%",
        )

        h5, h6, h7 = st.columns(3)
        h5.metric(
            "BTC now",
            fmt_money(price),
        )
        h6.metric(
            "Nearest Kalshi hourly strike",
            (
                fmt_money(hourly_ai["nearest_strike"])
                if pd.notna(hourly_ai["nearest_strike"])
                else "N/A"
            ),
        )

        if pd.notna(hourly_ai["seconds_remaining"]):
            hr_min, hr_sec = divmod(
                max(0, int(hourly_ai["seconds_remaining"])),
                60,
            )
            h7.metric(
                "Hourly market time left",
                f"{hr_min:02d}:{hr_sec:02d}",
            )
        else:
            h7.metric("Hourly market time left", "N/A")

        st.plotly_chart(
            hourly_target_chart(hist, price, hourly_ai),
            use_container_width=True,
            key="hourly_kalshi_ai_chart",
            config={
                "displaylogo": False,
                "scrollZoom": True,
                "responsive": True,
            },
        )

        if hourly_ai["direction"] == "UP":
            st.success(
                f"Hourly AI expects BTC near ${hourly_ai['target_price']:,.2f} "
                "at the next hourly settlement."
            )
        elif hourly_ai["direction"] == "DOWN":
            st.error(
                f"Hourly AI expects BTC near ${hourly_ai['target_price']:,.2f} "
                "at the next hourly settlement."
            )
        else:
            st.info(
                f"Hourly AI currently expects a relatively flat finish near "
                f"${hourly_ai['target_price']:,.2f}."
            )

        if hourly_ai["kalshi_available"]:
            st.caption(
                "Yellow dashed line = nearest active Kalshi hourly strike. "
                "Blue solid line = this bot's independent 1-hour BTC target forecast."
            )
        else:
            st.warning(
                "Kalshi hourly strikes are temporarily unavailable. "
                "The Hourly AI target is still calculated from live BTC market data."
            )


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
        st.subheader("Kalshi — live BTC 15-minute market")
        kctx = stable_kalshi_contract(kalshi, price)
        if kctx["available"]:
            rr1, rr2, rr3, rr4 = st.columns(4)
            rr1.metric("Ticker", kctx["ticker"])
            rr2.metric("Target", fmt_money(kctx["target"]))
            rr3.metric("BTC vs target", f"${kctx['distance']:+,.2f}")
            rr4.metric(
                "UP / DOWN",
                (
                    "N/A"
                    if pd.isna(kctx["up_probability"])
                    else (
                        f"{kctx['up_probability']*100:.1f}% / "
                        f"{(1.0-kctx['up_probability'])*100:.1f}%"
                    )
                ),
            )
        st.caption(
            "Read-only Kalshi market data. The app does not place Kalshi orders."
        )

        st.subheader("Kalshi market-data details")
        if kalshi.get("ok"):
            markets = kalshi.get("markets", [])
            st.caption(f"Public market-data lookup • {len(markets)} BTC-related open markets found • target-polled every ~3 seconds")
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
        st.subheader("Automatic Paper Trading")
        auto_state = get_auto_state()
        account = get_account(price)

        status1, status2, status3, status4 = st.columns(4)
        status1.metric("AUTO PAPER", "ON" if bool(auto_state["enabled"]) else "OFF")
        status2.metric("Position", auto_state["side"])
        status3.metric("Kalshi call", decision["action"])
        status4.metric("Risk approved", "YES" if risk["approved"] else "NO")

        if bool(auto_state["enabled"]):
            st.success(auto_result["message"] if auto_result.get("message") else auto_state.get("last_message", "AUTO PAPER running."))
        else:
            st.info("AUTO PAPER TRADING is off. Turn it on in the sidebar to let approved paper signals execute automatically.")

        st.subheader("Paper Account")
        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("Cash", fmt_money(account["cash"]))
        a2.metric("BTC exposure", f"{account['btc']:+.6f}")
        a3.metric("Equity", fmt_money(account["equity"]))
        a4.metric("P&L", fmt_money(account["pnl"]))
        a5.metric("Return", f"{account['return_pct']:+.2f}%")

        auto_state = get_auto_state()
        if auto_state["side"] in {"LONG", "SHORT"}:
            entry = safe_float(auto_state["entry_price"])
            stop = safe_float(auto_state["stop_loss"])
            target = safe_float(auto_state["take_profit"])
            qty = abs(safe_float(auto_state["entry_qty"], 0.0))
            entry_ts = int(auto_state["entry_ts"] or int(time.time()))
            elapsed = max(0, int(time.time()) - entry_ts)
            if auto_state["side"] == "LONG":
                unrealized_dollars = (price - entry) * qty
            else:
                unrealized_dollars = (entry - price) * qty

            st.subheader("Active Position")
            p1, p2, p3, p4, p5, p6 = st.columns(6)
            p1.metric("Side", auto_state["side"])
            p2.metric("Entry", fmt_money(entry))
            p3.metric("Current", fmt_money(price))
            p4.metric("Stop", fmt_money(stop))
            p5.metric("Target", fmt_money(target))
            p6.metric("Unrealized", fmt_money(unrealized_dollars))
            st.caption(
                f"Quantity {qty:.6f} BTC • elapsed {elapsed//60:02d}:{elapsed%60:02d} • "
                f"automatic time exit at {PREDICTION_HORIZON_MIN}:00"
            )
            if st.button("Close Paper Position Now", use_container_width=True):
                result = close_paper_position(price, "manual close")
                if result["ok"]:
                    st.success(result["message"])
                else:
                    st.error(result["message"])
                st.rerun(scope="fragment")

        st.subheader("Risk Manager")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Approved", "YES" if risk["approved"] else "NO")
        r2.metric("Position size", f"{risk['position_pct']*100:.2f}%")
        r3.metric("Risk score", f"{risk['risk_score']:.2f}")
        r4.metric("Decision", decision["action"])
        st.caption(risk["reason"])

        if not bool(auto_state["enabled"]) and auto_state["side"] == "NONE":
            if st.button("Execute Approved Paper Trade", type="primary", use_container_width=True):
                if risk["approved"]:
                    internal_action = (
                        "BUY"
                        if decision["action"] == "SCALP UP"
                        else "SELL"
                    )
                    result = execute_paper_trade(
                        internal_action,
                        price,
                        risk["position_pct"],
                        hist,
                        note=(
                            f"MANUAL Kalshi-call={decision['action']}, "
                            f"master={decision['score']:+.3f}, "
                            f"confidence={decision['confidence']:.3f}"
                        ),
                    )
                    if result["ok"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])
                    st.rerun(scope="fragment")
                else:
                    st.error(f"Paper trade blocked: {risk['reason']}")

        with db_conn() as conn:
            trades = pd.read_sql_query("SELECT * FROM paper_trades ORDER BY id DESC LIMIT 100", conn)
        if not trades.empty:
            st.subheader("Paper Trade Log")
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

    with tab_learning:
        st.subheader("15-Minute Prediction Learning")
        learn = get_learning_state()

        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Completed windows", int(learn["samples"]))
        l2.metric(
            "Direction accuracy",
            "N/A"
            if pd.isna(learn["direction_accuracy"])
            else f"{learn['direction_accuracy']*100:.1f}%"
        )
        l3.metric("Avg final error", f"${learn['avg_abs_error']:,.2f}")
        l4.metric("Avg path error", f"${learn['avg_path_error']:,.2f}")

        _quick100 = rolling_master_accuracy(100)
        _quick500 = rolling_master_accuracy(500)
        _quick1000 = rolling_master_accuracy(1000)

        q1, q2, q3 = st.columns(3)

        q1.metric(
            "Last 100 accuracy",
            "N/A"
            if pd.isna(_quick100["accuracy"])
            else f"{_quick100['accuracy']*100:.1f}%"
        )

        q2.metric(
            "Last 500 accuracy",
            "N/A"
            if pd.isna(_quick500["accuracy"])
            else f"{_quick500['accuracy']*100:.1f}%"
        )

        q3.metric(
            "Last 1,000 accuracy",
            "N/A"
            if pd.isna(_quick1000["accuracy"])
            else f"{_quick1000['accuracy']*100:.1f}%"
        )

        st.caption(
            "After each completed 15-minute Kalshi window, the model grades "
            "its forecast and adjusts its momentum weights, move scale, "
            "target influence, and directional bias."
        )

        w1, w2, w3, w4 = st.columns(4)
        w1.metric("3m weight", f"{learn['w_ret3']*100:.1f}%")
        w2.metric("8m weight", f"{learn['w_ret8']*100:.1f}%")
        w3.metric("15m weight", f"{learn['w_ret15']*100:.1f}%")
        w4.metric("Move scale", f"{learn['momentum_scale']:.2f}×")

        st.divider()
        st.subheader("Specialist AI Learning")

        st.caption(
            "Every specialist is graded after each completed 15-minute window. "
            "The Master AI automatically increases the influence of specialists "
            "with stronger recent accuracy, edge, and confidence calibration, "
            "and reduces the influence of weaker ones."
        )

        st.divider()
        st.subheader("Rolling Master Accuracy")

        rolling_master_df = rolling_master_accuracy_table()

        for col in [
            "Direction Accuracy %",
            "Avg Final Error $",
            "Avg Path Error $",
        ]:
            rolling_master_df[col] = pd.to_numeric(
                rolling_master_df[col],
                errors="coerce",
            ).round(2)

        st.dataframe(
            rolling_master_df,
            use_container_width=True,
            hide_index=True,
        )

        _m100 = rolling_master_accuracy(100)
        _m1000 = rolling_master_accuracy(1000)

        _m100_acc = (
            np.nan
            if pd.isna(_m100["accuracy"])
            else _m100["accuracy"] * 100.0
        )

        _m1000_acc = (
            np.nan
            if pd.isna(_m1000["accuracy"])
            else _m1000["accuracy"] * 100.0
        )

        st.caption(
            "Master learning trend: "
            + learning_trend_label(
                _m100_acc,
                _m1000_acc,
            )
            + " — compares the most recent 100 completed windows "
              "with the broader 1,000-window baseline."
        )

        specialist_multi = add_specialist_learning_trends(
            specialist_multiwindow_accuracy()
        )

        if not specialist_multi.empty:
            for col in [
                "Acc 100 %",
                "Acc 500 %",
                "Acc 1000 %",
                "Edge 100",
                "Edge 500",
                "Edge 1000",
            ]:
                if col in specialist_multi.columns:
                    specialist_multi[col] = pd.to_numeric(
                        specialist_multi[col],
                        errors="coerce",
                    ).round(2)

            st.subheader("Specialist Rolling Accuracy")

            st.caption(
                "This view makes it easy to see which bots are improving, "
                "which are stable, and which are losing effectiveness as "
                "market conditions change."
            )

            st.dataframe(
                specialist_multi,
                use_container_width=True,
                hide_index=True,
            )

        specialist_df = specialist_learning_dataframe()

        if specialist_df.empty:
            st.info("Specialist learning will populate after completed windows.")
        else:
            specialist_df["Learned weight"] = pd.to_numeric(
                specialist_df["Learned weight"],
                errors="coerce",
            ).round(3)

            specialist_df["Accuracy %"] = pd.to_numeric(
                specialist_df["Accuracy %"],
                errors="coerce",
            ).round(1)

            specialist_df["Recent accuracy %"] = pd.to_numeric(
                specialist_df["Recent accuracy %"],
                errors="coerce",
            ).round(1)

            specialist_df["Recent edge"] = pd.to_numeric(
                specialist_df["Recent edge"],
                errors="coerce",
            ).round(4)

            specialist_df["Calibration"] = pd.to_numeric(
                specialist_df["Calibration"],
                errors="coerce",
            ).round(3)

            st.dataframe(
                specialist_df,
                use_container_width=True,
                hide_index=True,
            )

        learning_df = recent_learning_windows(50)
        if learning_df.empty:
            st.info(
                "No completed learning windows yet. The active Kalshi "
                "15-minute contract is being recorded now."
            )
        else:
            for col in [
                "start_price", "predicted_end", "actual_end",
                "abs_error", "path_error"
            ]:
                if col in learning_df.columns:
                    learning_df[col] = pd.to_numeric(
                        learning_df[col],
                        errors="coerce"
                    ).round(2)

            st.dataframe(
                learning_df,
                use_container_width=True,
                hide_index=True,
            )


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
                "auto_paper": get_auto_state(),
                "auto_cycle": auto_result,
                "full_cycle_ms": full_cycle_ms,
            })

    st.divider()
    st.caption(
        f"Last update {utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')} • "
        "Safety: PAPER ONLY • automatic simulation may trade long/short • no order API keys • no real-money exchange execution."
    )


live_dashboard()
