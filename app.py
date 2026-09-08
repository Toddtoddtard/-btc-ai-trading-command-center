import json
import math
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from access_control import require_owner_approval
from market_guide import render_market_guide
from shared_learning import fetch_shared_learning_state

from ai_core import enrich_history_core, forecast_path_core, run_specialists_core
from council_v4 import council_vote
from specialist_knowledge_v5 import knowledge_council_vote
from profitability_v5 import summarize_trades, profitability_gate
from bot_intelligence_dashboard import render_bot_intelligence_dashboard
from kalshi_paper_engine import manage_kalshi_paper_cycle, paper_history, paper_summary, persistent_lock_side
from learning_prices import closed_price_at
from reliability_v31 import (
    calibrate_confidence, detect_regime, execution_cost_bps,
    learned_policy, learned_trade_gate, regime_specialist_weight,
    source_health_from_specialists,
)

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


require_owner_approval()

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
STARTING_CASH = 500.0
PREDICTION_HORIZON_MIN = 15
APP_VERSION = "2026.09.08-r70-parallel-live-fetch"

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
    "FVG / MACD AI": 0.90,
    "Combination AI": 1.25,
}

# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    [data-testid="stMetricValue"] {
        font-size: clamp(.84rem, 1.48vw, 1.48rem) !important;
        line-height: 1.15 !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        min-width: 0 !important;
        width: 100% !important;
        box-sizing: border-box !important;
        padding-right: .65rem !important;
    }
    [data-testid="stMetricValue"] > div,
    [data-testid="stMetricValue"] p {
        font-size: inherit !important;
        line-height: inherit !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        padding-right: .10rem !important;
    }
    [data-testid="stMetric"] {
        min-width: 0 !important;
        box-sizing: border-box !important;
        padding-right: .20rem !important;
    }
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
    .confidence-metric-card {
        width:100%;
        min-height:92px;
        box-sizing:border-box;
        padding:.72rem 1rem;
        border:1px solid #1687ff;
        border-radius:13px;
        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        justify-content:flex-start;
        gap:.30rem;
    }
    .confidence-metric-label {
        color:#9fb2ce;
        font-size:.90rem;
        line-height:1.15;
        font-weight:500;
        white-space:nowrap;
        display:flex;
        align-items:center;
        gap:.32rem;
    }
    .confidence-metric-label span {
        font-size:.72rem;
        font-weight:800;
        letter-spacing:.02em;
    }
    .confidence-metric-value {
        font-size:1.55rem;
        font-weight:750;
        line-height:1.65;
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


def display_position_side(side):
    """UI-only translation: LONG means UP, SHORT means DOWN."""
    s = str(side or "NONE").upper().strip()
    if s == "LONG":
        return "LONG (UP)"
    if s == "SHORT":
        return "SHORT (DOWN)"
    if s in {"NONE", "HOLD", "WAIT"}:
        return "HOLD / NO TRADE"
    return s


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



def render_dashboard_table(df, formatters=None):
    """Render dashboard tables with the same dark visual language as AI Council.

    Presentation only: underlying dataframe values and trading logic are untouched.
    """
    if not st.session_state.get("dashboard_dark_mode", True):
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    view = df.copy()
    fmts = dict(formatters or {})

    def _semantic_badge(value):
        text = str(value if value is not None else "").strip()
        upper = text.upper()
        positive = {
            "BULLISH", "UP", "SCALP UP", "LOCK UP", "LONG", "BUY",
            "CORRECT", "IMPROVING", "RESOLVED", "YES", "WIN", "TRUE",
        }
        negative = {
            "BEARISH", "DOWN", "SCALP DOWN", "LOCK DOWN", "SHORT", "SELL",
            "WRONG", "DECLINING", "LOSS", "NO", "FALSE",
        }
        if upper in positive or upper in {"1", "1.0"}:
            cls = "dash-positive"
        elif upper in negative or upper in {"0", "0.0"}:
            cls = "dash-negative"
        else:
            cls = "dash-neutral"
        return f'<span class="dash-badge {cls}">{text}</span>'

    semantic_cols = {
        "signal", "action", "direction", "trend", "correct", "resolved",
        "side", "approved", "result", "status",
    }
    for col in view.columns:
        if str(col).strip().lower() in semantic_cols and col not in fmts:
            fmts[col] = _semantic_badge

    table_html = view.to_html(
        index=False,
        border=0,
        classes="dashboard-dark-table",
        escape=False,
        formatters=fmts,
    )
    st.markdown(
        """
        <style>
        .dashboard-dark-wrap {
            width:100%; overflow-x:auto; border:1px solid #1687ff;
            border-radius:12px; background:#0b1220;
        }
        .dashboard-dark-table {
            width:100%; border-collapse:collapse; color:#e8eef8;
            background:#0b1220; font-size:.93rem; margin:0;
        }
        .dashboard-dark-table thead th {
            position:sticky; top:0; z-index:1; text-align:left;
            color:#b8cff7; background:#111c2e; font-weight:700;
            border-bottom:1px solid #2b3b52; padding:10px 12px;
            white-space:nowrap;
        }
        .dashboard-dark-table tbody td {
            color:#e7edf7; background:#0b1220;
            border-bottom:1px solid #1e2b3d; padding:9px 12px;
            vertical-align:middle; white-space:nowrap;
        }
        .dashboard-dark-table tbody tr:nth-child(even) td {background:#0f1828;}
        .dashboard-dark-table tbody tr:hover td {background:#15243a;}
        .dash-badge {
            display:inline-block; min-width:78px; text-align:center;
            padding:4px 9px; border-radius:7px; font-weight:800;
            letter-spacing:.02em; line-height:1.2; box-sizing:border-box;
        }
        .dash-positive {
            color:#00f0b5; background:rgba(0,240,181,.13);
            border:1px solid rgba(0,240,181,.80);
        }
        .dash-negative {
            color:#ff536b; background:rgba(255,83,107,.13);
            border:1px solid rgba(255,83,107,.85);
        }
        .dash-neutral {
            color:#b8c6dc; background:rgba(184,198,220,.09);
            border:1px solid rgba(184,198,220,.42);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="dashboard-dark-wrap">{table_html}</div>',
        unsafe_allow_html=True,
    )

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
    """Compatibility wrapper around the private-repo-safe shared loader."""
    return fetch_shared_learning_state(ttl=ttl)


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
        row = conn.execute("SELECT id, starting_equity FROM paper_account WHERE id=1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO paper_account(id,cash,btc,starting_equity,updated_iso) VALUES(1,?,?,?,?)",
                (STARTING_CASH, 0.0, STARTING_CASH, utc_now().isoformat()),
            )
        elif abs(float(row["starting_equity"]) - STARTING_CASH) > 1e-9:
            # One-time migration to the new $500 paper baseline. Start clean so
            # old $100k results do not contaminate the new account performance.
            conn.execute(
                "UPDATE paper_account SET cash=?, btc=0, starting_equity=?, updated_iso=? WHERE id=1",
                (STARTING_CASH, STARTING_CASH, utc_now().isoformat()),
            )
            conn.execute("DELETE FROM paper_trades")
            conn.execute(
                """UPDATE auto_paper_state
                   SET side='NONE',entry_price=NULL,entry_ts=NULL,entry_qty=NULL,
                       stop_loss=NULL,take_profit=NULL,last_exit_ts=0,
                       last_message='Paper account migrated to $500 starting balance.'
                   WHERE id=1"""
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

    entry_cost = execution_cost_bps(notional)
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
            if cash < notional + entry_cost:
                return {"ok": False, "message": "Not enough paper cash for the approved long including simulated costs."}
            cash -= (notional + entry_cost)
            btc += qty
            side = "LONG"
            stop_loss = price - stop_distance
            take_profit = price + target_distance
            signed_qty = qty
        else:
            # Simulated short: sale proceeds are credited to paper cash and the
            # BTC balance becomes negative. Equity remains cash + BTC*price.
            cash += (notional - entry_cost)
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
            f"{note} | entry_cost=${entry_cost:,.2f}",
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
            exit_cost = execution_cost_bps(notional)
            cash += (notional - exit_cost)
            btc -= qty
            entry_cost_est = execution_cost_bps(qty * entry_price)
            realized = (price - entry_price) * qty - entry_cost_est - exit_cost
            signed_qty = -qty
        else:
            qty = min(entry_qty, abs(min(0.0, btc)))
            notional = qty * price
            exit_cost = execution_cost_bps(notional)
            cash -= (notional + exit_cost)
            btc += qty
            entry_cost_est = execution_cost_bps(qty * entry_price)
            realized = (entry_price - price) * qty - entry_cost_est - exit_cost
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
            f"{reason} | realized_pnl=${realized:,.2f} | entry_cost=${entry_cost_est:,.2f} | exit_cost=${exit_cost:,.2f}",
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
    """Run one PAPER-only KXBTC15M contract cycle; never sends a live order."""
    return manage_kalshi_paper_cycle(DB_PATH, STARTING_CASH, decision, risk, price)


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


def _kalshi_15m_boundary(now_ts=None):
    """Return the next Kalshi 15m close boundary in America/New_York."""
    now_ts = time.time() if now_ts is None else float(now_ts)
    ny = datetime.fromtimestamp(now_ts, tz=ZoneInfo("America/New_York"))
    minute = ((ny.minute // 15) + 1) * 15
    if minute >= 60:
        close_ny = ny.replace(minute=0, second=0, microsecond=0) + pd.Timedelta(hours=1)
    else:
        close_ny = ny.replace(minute=minute, second=0, microsecond=0)
    return close_ny


def _kalshi_15m_ticker(close_ny):
    mon = close_ny.strftime("%b").upper()
    return f"KXBTC15M-{close_ny.strftime('%y')}{mon}{close_ny.strftime('%d%H%M')}-{close_ny.strftime('%M')}"


@st.cache_data(ttl=3, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
    """Resolve the active KXBTC15M contract robustly.

    Primary path: construct the exact active ticker from the next 15-minute
    New York boundary and fetch that exact market directly. This avoids Kalshi
    list/status lag. Secondary path: series-list discovery for resilience.
    """
    now_ts = time.time()
    errors = []

    # Deterministic exact-ticker path. Try the expected active close first,
    # then adjacent boundaries in case Kalshi publishes a few seconds early/late.
    expected_close = _kalshi_15m_boundary(now_ts)
    for offset_min in (0, 15, -15):
        close_ny = expected_close + pd.Timedelta(minutes=offset_min)
        ticker = _kalshi_15m_ticker(close_ny)
        exact = fetch_exact_kalshi_market(ticker)
        if not exact:
            continue
        exact_close_ts = kalshi_close_timestamp(exact)
        if pd.isna(exact_close_ts):
            exact_close_ts = float(close_ny.timestamp())
        if exact_close_ts <= now_ts:
            continue
        target = kalshi_numeric_target(exact)
        row = dict(exact)
        row["ticker"] = ticker
        row["_close_ts"] = exact_close_ts
        row["_seconds_remaining"] = max(0, int(exact_close_ts - now_ts))
        row["_target"] = target
        return {
            "ok": True,
            "markets": [row],
            "current": row,
            "feed_ms": np.nan,
            "error": None,
            "resolution": "deterministic-exact-ticker",
        }

    # Fallback: discover from the KXBTC15M series list, but never require target
    # fields in the list response. Canonical target still comes from exact ticker.
    for base in KALSHI_BASES:
        for params in (
            {"limit": 100, "status": "open", "series_ticker": "KXBTC15M"},
            {"limit": 100, "series_ticker": "KXBTC15M"},
        ):
            try:
                payload, ms = http_json(base + "/markets", params, timeout=3.0)
                markets = payload.get("markets", []) if isinstance(payload, dict) else []
                hits = []
                for market in markets:
                    ticker = str(market.get("ticker") or "")
                    if not ticker.upper().startswith("KXBTC15M-"):
                        continue
                    close_ts = kalshi_close_timestamp(market)
                    if pd.isna(close_ts) or close_ts <= now_ts:
                        continue
                    row = dict(market)
                    row["_close_ts"] = close_ts
                    row["_seconds_remaining"] = max(0, int(close_ts - now_ts))
                    row["_target"] = kalshi_numeric_target(market)
                    hits.append(row)
                if not hits:
                    continue
                current = min(hits, key=lambda row: (row["_close_ts"], str(row.get("ticker", ""))))
                exact = fetch_exact_kalshi_market(current.get("ticker", ""))
                if exact:
                    merged = dict(current)
                    merged.update(exact)
                    target = kalshi_numeric_target(exact)
                    exact_close_ts = kalshi_close_timestamp(exact)
                    if pd.notna(target) and target > 0:
                        merged["_target"] = float(target)
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
                    "resolution": "series-fallback",
                }
            except Exception as exc:
                errors.append(str(exc))

    # Last-resort timer seed: even if Kalshi API is temporarily unreachable,
    # the 15m countdown remains usable from the official quarter-hour schedule.
    close_ny = expected_close
    synthetic_close = float(close_ny.timestamp())
    ticker = _kalshi_15m_ticker(close_ny)
    row = {
        "ticker": ticker,
        "title": "BTC price up in next 15 mins?",
        "close_time": close_ny.astimezone(timezone.utc).isoformat(),
        "_close_ts": synthetic_close,
        "_seconds_remaining": max(0, int(synthetic_close - now_ts)),
        "_target": np.nan,
    }
    return {
        "ok": True,
        "markets": [row],
        "current": row,
        "feed_ms": np.nan,
        "error": " | ".join(errors[-4:]),
        "resolution": "schedule-only-fallback",
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

    live_ticker = str(live.get("ticker") or "")
    cached_ticker = str((cached or {}).get("ticker") or "")
    should_replace = (
        cached is None
        or pd.isna(cached.get("target", np.nan))
        or cache_expired(cached)
        or (live.get("available") and live_ticker and live_ticker != cached_ticker)
    )

    if live.get("available") and should_replace:
        cached = {
            "available": True,
            "ticker": live_ticker,
            "title": live.get("title", "BTC 15 min"),
            "target": live.get("target", np.nan),
            "close_time": live.get("close_time"),
            "market": live.get("market"),
        }
        st.session_state["kalshi_contract_snapshot"] = cached
    elif live.get("available") and cached and live_ticker == cached_ticker:
        # Keep the same contract fresh. Kalshi can publish/update the explicit
        # Target Price shortly after the market shell appears; never preserve a
        # stale target just because the ticker itself has not changed.
        live_target = safe_float(live.get("target"))
        if pd.notna(live_target) and live_target > 0:
            cached["target"] = float(live_target)
        if live.get("close_time"):
            cached["close_time"] = live.get("close_time")
        if live.get("market"):
            cached["market"] = live.get("market")
        cached["title"] = live.get("title", cached.get("title", "BTC 15 min"))
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


def _ensure_window_lock_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kalshi_decision_locks (
            ticker TEXT PRIMARY KEY,
            side TEXT NOT NULL CHECK(side IN ('YES', 'NO')),
            locked_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
    """)


def _persistent_window_lock_side(ticker=None):
    """Read the app-level immutable window latch, with legacy fallback."""
    ticker = str(ticker or "").strip()
    now = time.time()
    with db_conn() as conn:
        _ensure_window_lock_table(conn)
        if ticker:
            row = conn.execute(
                """SELECT side FROM kalshi_decision_locks
                   WHERE ticker=? AND expires_at>?
                   ORDER BY locked_at DESC LIMIT 1""",
                (ticker, now),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT side FROM kalshi_decision_locks
                   WHERE expires_at>?
                   ORDER BY locked_at DESC LIMIT 1""",
                (now,),
            ).fetchone()
    if row:
        return row["side"]
    return persistent_lock_side(DB_PATH, ticker, STARTING_CASH)


def _register_window_lock(ticker, side, expires_at):
    """First valid LOCK wins; later writes cannot replace its direction."""
    ticker = str(ticker or "").strip()
    side = "YES" if str(side).upper() in {"YES", "UP", "LOCK UP"} else "NO"
    expiry = safe_float(expires_at)
    now = time.time()
    if not ticker or pd.isna(expiry) or expiry <= now:
        return None
    with db_conn() as conn:
        _ensure_window_lock_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM kalshi_decision_locks WHERE expires_at<=?", (now,))
        conn.execute(
            """INSERT OR IGNORE INTO kalshi_decision_locks(
                   ticker,side,locked_at,expires_at
               ) VALUES(?,?,?,?)""",
            (ticker, side, now, expiry),
        )
        row = conn.execute(
            "SELECT side FROM kalshi_decision_locks WHERE ticker=? AND expires_at>?",
            (ticker, now),
        ).fetchone()
        conn.commit()
    return row["side"] if row else None


def master_decision(results, hist, kalshi=None):
    remote_learning = fetch_remote_learning_state() or {}
    regime_name = detect_regime(hist)
    policy = learned_policy(remote_learning, regime_name)

    # Bot Intelligence v5 adds Bayesian specialist knowledge on top of the v4
    # learned/regime-aware council. The 90% value is a precision target, not a
    # claimed accuracy; weak evidence causes abstention rather than a forced call.
    v5_council = knowledge_council_vote(results, remote_learning, regime_name, target_precision=0.90)
    base_score = clamp(v5_council["base_score"])
    consensus = float(v5_council["consensus"])
    council_confidence = float(v5_council["confidence"])

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

    # The decision lock is independent of paper execution. Once a side is
    # registered for a still-open ticker, every refresh and every downstream
    # gate must keep that exact side until the contract window expires.
    current_ticker = kctx.get("ticker", "")
    _db_lock_side = _persistent_window_lock_side(current_ticker)
    lock_side = "UP" if _db_lock_side == "YES" else "DOWN" if _db_lock_side == "NO" else None
    lock_ticker = current_ticker if lock_side else ""
    _lock_was_already_persisted = lock_side in {"UP", "DOWN"}

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

        target_confidence = min(
            0.97,
            max(
                0.45,
                0.49
                + abs(score) * 0.28
                + consensus * 0.13
                + distance_strength * 0.10,
            ),
        )
        # Never let target geometry erase the reliability calibration learned
        # by v4. Blend both views and cap at the safer of their high extremes.
        confidence = float(np.clip(
            0.58 * target_confidence + 0.42 * council_confidence,
            0.40,
            min(0.97, max(target_confidence, council_confidence)),
        ))

        # -----------------------------------------------------------
        # LOCK semantics
        # LOCK UP   = expected to FINISH ABOVE the Kalshi target.
        # LOCK DOWN = expected to FINISH BELOW the Kalshi target.
        # -----------------------------------------------------------
        lock_up = (
            raw_side == "UP"
            and confidence >= policy["lock_confidence_floor"]
            and projected_edge >= max(atr * 0.35, px * 0.00035)
            and (
                (pd.notna(remaining) and remaining <= 300)
                or abs(score) >= 0.30
            )
        )

        lock_down = (
            raw_side == "DOWN"
            and confidence >= policy["lock_confidence_floor"]
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
        # BTC scalp calls are directional market calls. The prior thresholds
        # accidentally required roughly a 0.56 council score in low-volatility
        # conditions, far above the learned edge floor, so valid setups almost
        # never reached SCALP. Align movement/consensus with the learned policy.
        strong_move_up = (
            base_score >= policy["edge_floor"]
            and forecast_move >= max(atr * 0.14, px * 0.00014)
            and consensus >= 0.12
        )
        strong_move_down = (
            base_score <= -policy["edge_floor"]
            and forecast_move <= -max(atr * 0.14, px * 0.00014)
            and consensus >= 0.12
        )

        # Kalshi is context/confirmation for BTC scalps, not the instrument being
        # scalp-traded. Only an extreme opposing prediction-market signal blocks
        # the call; a high same-direction probability is confirmation, not a veto.
        up_market_conflict = pd.notna(up_prob) and up_prob < 0.20
        down_market_conflict = pd.notna(down_prob) and down_prob < 0.20

        scalp_up_candidate = (
            strong_move_up
            and not up_market_conflict
            and confidence >= policy["trade_confidence_floor"]
        )
        scalp_down_candidate = (
            strong_move_down
            and not down_market_conflict
            and confidence >= policy["trade_confidence_floor"]
        )
        scalp_candidate = scalp_up_candidate or scalp_down_candidate

        # Compare the quality of the shorter-term scalp thesis against the
        # settlement/target thesis. SCALP is the default when both are valid;
        # LOCK only wins when its evidence is stronger.
        edge_strength = min(1.0, abs(base_score) / max(policy["edge_floor"] * 2.0, 1e-6))
        scalp_likelihood = float(np.clip(
            0.58 * confidence + 0.24 * consensus + 0.18 * edge_strength,
            0.0, 1.0,
        ))
        settlement_urgency = (
            float(np.clip(1.0 - (remaining / 900.0), 0.0, 1.0))
            if pd.notna(remaining) else 0.0
        )
        lock_likelihood = float(np.clip(
            0.58 * confidence + 0.27 * distance_strength + 0.15 * settlement_urgency,
            0.0, 1.0,
        ))

        # Preserve an already-established lock for the active contract.
        if lock_ticker == current_ticker and lock_side in {"UP", "DOWN"}:
            action = f"LOCK {lock_side}"
            locked_side = lock_side

        # New decisions are scalp-first. A lock is selected only when its
        # settlement case is more likely than the competing scalp case.
        elif scalp_candidate and not ((lock_up or lock_down) and lock_likelihood > scalp_likelihood):
            action = "SCALP UP" if scalp_up_candidate else "SCALP DOWN"
            locked_side = None

        elif lock_up:
            action = "LOCK UP"
            locked_side = "UP"

        elif lock_down:
            action = "LOCK DOWN"
            locked_side = "DOWN"

        elif scalp_candidate:
            action = "SCALP UP" if scalp_up_candidate else "SCALP DOWN"
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

        if base_score >= policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]:
            action = "SCALP UP"
        elif base_score <= -policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]:
            action = "SCALP DOWN"
        else:
            action = "HOLD"

        prediction_label = "Kalshi target unavailable"

    source_health = source_health_from_specialists(results)
    gate_note = ""
    confidence = calibrate_confidence(
        confidence, consensus, policy, source_health=source_health, state=remote_learning
    )
    if not _lock_was_already_persisted and action not in {"HOLD", "WAIT"}:
        allowed, gated_action = learned_trade_gate(
            action, confidence, base_score, consensus, policy, source_health=source_health
        )
        if not allowed:
            action = "HOLD"
            locked_side = None
            gate_note = f"{gated_action}; learned reliability gate blocked trade"

    # Learned precision layer is a final safety veto only. It must not duplicate
    # the council trade gate or permanently deadlock otherwise-valid calls.
    if (
        not _lock_was_already_persisted
        and action not in {"HOLD", "WAIT"}
        and not bool(v5_council.get("precision_gate_passed"))
    ):
        action = "HOLD"
        locked_side = None
        precision_reason = str(v5_council.get("precision_gate_reason", "WAIT — v5 precision gate"))
        gate_note = (gate_note + "; " if gate_note else "") + precision_reason

    # Final one-way latch. Existing locks override all later signal/gate changes.
    # A newly approved lock is atomically registered; INSERT OR IGNORE guarantees
    # that simultaneous reruns can never replace the first side for this ticker.
    if _lock_was_already_persisted:
        action = f"LOCK {lock_side}"
        locked_side = lock_side
        gate_note = ""
    elif action in {"LOCK UP", "LOCK DOWN"} and current_ticker:
        _registered_side = _register_window_lock(
            current_ticker,
            "YES" if action == "LOCK UP" else "NO",
            pd.Timestamp(kctx.get("close_time")).timestamp() if kctx.get("close_time") else np.nan,
        )
        if _registered_side in {"YES", "NO"}:
            lock_side = "UP" if _registered_side == "YES" else "DOWN"
            action = f"LOCK {lock_side}"
            locked_side = lock_side

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

    if gate_note:
        reason_parts.append(gate_note)

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
        "kalshi_close_ts": (pd.Timestamp(kctx.get("close_time")).timestamp() if kctx.get("close_time") else np.nan),
        "yes_bid_dollars": safe_float((kctx.get("market") or {}).get("yes_bid_dollars")),
        "yes_ask_dollars": safe_float((kctx.get("market") or {}).get("yes_ask_dollars")),
        "no_bid_dollars": safe_float((kctx.get("market") or {}).get("no_bid_dollars")),
        "no_ask_dollars": safe_float((kctx.get("market") or {}).get("no_ask_dollars")),
        "seconds_remaining": remaining,
        "up_probability": up_prob,
        "down_probability": down_prob,
        "kalshi_available": kctx["available"],
        "policy": policy,
        "source_health": source_health,
        "regime": regime_name,
        "whale_score": safe_float(
            (results.get("Whale AI") or {}).get("score"), 0.0
        ),
        "whale_confidence": safe_float(
            (results.get("Whale AI") or {}).get("confidence"), 0.0
        ),
    }


def risk_evaluate(decision, account, hist, futures):
    px = float(hist["close"].iloc[-1])
    policy = decision.get("policy", {})
    source_health = safe_float(decision.get("source_health"), 1.0)
    learned_conf_floor = safe_float(policy.get("trade_confidence_floor"), 0.62)
    atr_pct = safe_float(hist["atr14"].iloc[-1] / px, 0.003)
    confidence = decision["confidence"]
    consensus = decision["consensus"]

    if decision["action"] in {"HOLD", "WAIT"}:
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "No trade signal"}

    # Confidence, consensus and source-health are authoritative upstream gates.
    # Do not silently apply a second, conflicting threshold here.  This layer
    # only sizes an already-approved PAPER action and controls exposure.

    volatility_penalty = min(0.55, max(0.0, (atr_pct - 0.002) * 100))
    base = 0.04 + (confidence - 0.60) * 0.22 + consensus * 0.04
    position_pct = max(0.02, min(0.15, base * (1 - volatility_penalty)))
    risk_score = clamp(0.6 - confidence * 0.35 - consensus * 0.15 + volatility_penalty, 0, 1)

    state = get_auto_state()
    if state["side"] != "NONE" and not str(decision.get("action", "")).startswith("LOCK"):
        return {
            "approved": False,
            "position_pct": 0.0,
            "risk_score": risk_score,
            "reason": f"Paper {state['side']} already open",
        }

    return {"approved": True, "position_pct": position_pct, "risk_score": risk_score, "reason": "Authoritative decision gate passed; paper exposure sized"}


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
        actual_end = closed_price_at(hist2, expiry_dt)
        if actual_end is None:
            continue
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

def adaptive_specialist_weight(name, regime=None):
    remote = fetch_remote_learning_state() or {}
    state = (remote.get("specialists", {}) or {}).get(name, {})
    base = safe_float(SPECIALIST_WEIGHTS.get(name), 1.0)
    regime = regime or "UNKNOWN"
    return regime_specialist_weight(base, state, regime)


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

        actual_end = closed_price_at(hist2, expiry_dt)
        if actual_end is None:
            continue
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
    """Record one primary prediction per Kalshi 15-minute contract window.

    Dashboard refreshes may recalculate the call many times, but overlapping
    snapshots are correlated evidence and must not be counted as independent
    learning samples. min_seconds remains accepted for older callers.
    """
    del min_seconds
    now_ts = int(time.time())
    close_ts = safe_float(decision.get("kalshi_close_ts"))
    if pd.notna(close_ts) and float(close_ts) > now_ts:
        target_ts = int(close_ts)
    else:
        horizon_seconds = int(PREDICTION_HORIZON_MIN * 60)
        target_ts = ((now_ts // horizon_seconds) + 1) * horizon_seconds

    with db_conn() as conn:
        # target_ts identifies the contract window. Existing rows are preserved,
        # but no refresh or changed call can create another row for this window.
        if conn.execute(
            "SELECT 1 FROM predictions WHERE target_ts=? LIMIT 1",
            (target_ts,),
        ).fetchone():
            return False
        conn.execute(
            """INSERT INTO predictions
               (created_ts,created_iso,target_ts,price,action,score,confidence,consensus,target_price,rationale)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                now_ts,
                utc_now().isoformat(),
                target_ts,
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


def resolve_predictions(hist, current_price=None):
    """Resolve every expired journal row from the nearest real 1m BTC candle.

    The resolver is intentionally batch-oriented so a large legacy journal does
    not make hundreds of HTTP requests during one Streamlit rerun. It also
    repairs legacy rows whose stored target_ts is inconsistent by falling back
    to created_ts + the configured prediction horizon.
    """
    now_ts = int(time.time())
    horizon_seconds = int(PREDICTION_HORIZON_MIN * 60)

    # Use the already-loaded dashboard history first.
    candle_points = []
    if hist is not None and not hist.empty and "time" in hist.columns and "close" in hist.columns:
        hist2 = hist[["time", "close"]].copy()
        hist2["_ts"] = pd.to_datetime(hist2["time"], utc=True, errors="coerce")
        # pandas 3 may store microseconds rather than nanoseconds. Do not
        # assume the integer dtype's time unit when computing epoch seconds.
        hist2["_epoch"] = hist2["_ts"].map(lambda ts: ts.timestamp() if pd.notna(ts) else np.nan)
        hist2["close"] = pd.to_numeric(hist2["close"], errors="coerce")
        for _, candle in hist2.dropna(subset=["_epoch", "close"]).iterrows():
            px = safe_float(candle["close"])
            if pd.notna(px) and px > 0:
                candle_points.append((int(candle["_epoch"]) + 60, float(px)))

    with db_conn() as conn:
        # created_ts is the reliable expiry gate for legacy rows. A prediction is
        # mature once its full configured horizon has elapsed even if an older
        # build stored a malformed target_ts.
        rows = conn.execute(
            """SELECT * FROM predictions
               WHERE created_ts<=?
                 AND (
                    resolved=0
                    OR (resolved=1 AND correct IS NULL AND action NOT IN ('HOLD','WAIT'))
                 )
               ORDER BY id ASC LIMIT 500""",
            (now_ts - horizon_seconds,),
        ).fetchall()

        if not rows:
            return 0

        prepared = []
        missing_targets = []
        for row in rows:
            created_ts = int(row["created_ts"] or 0)
            expected_target = created_ts + horizon_seconds
            stored_target = int(row["target_ts"] or 0)

            # Normal rows should be almost exactly one horizon apart. If not,
            # self-heal the legacy row using its creation timestamp.
            if stored_target <= 0 or abs(stored_target - expected_target) > 300:
                target_ts = expected_target
            else:
                target_ts = stored_target

            action = str(row["action"] or "HOLD").upper().strip()
            prepared.append((row, target_ts, action))

            # HOLD/WAIT can be marked resolved without a directional grade.
            if action not in {"HOLD", "WAIT"}:
                missing_targets.append(target_ts)

        # Fetch missing historical candles in large chronological batches.
        # Binance allows up to 1000 1m candles per call; keep each batch under
        # ~14 hours and only request ranges that contain prediction targets.
        if missing_targets:
            targets = sorted(set(int(x) for x in missing_targets))
            batches = []
            batch_start = targets[0]
            batch_end = targets[0]
            for target in targets[1:]:
                if target - batch_start <= 800 * 60:
                    batch_end = target
                else:
                    batches.append((batch_start, batch_end))
                    batch_start = batch_end = target
            batches.append((batch_start, batch_end))

            for batch_start, batch_end in batches:
                try:
                    market_rows, _ = try_bases(
                        SPOT_BASES,
                        "/api/v3/klines",
                        {
                            "symbol": SYMBOL,
                            "interval": "1m",
                            "startTime": max(0, (batch_start - 120) * 1000),
                            "endTime": (batch_end + 120) * 1000,
                            "limit": 1000,
                        },
                        timeout=4.0,
                    )
                    for candle in market_rows or []:
                        try:
                            open_ts = int(candle[0]) // 1000
                            close_px = safe_float(candle[4])
                            if pd.notna(close_px) and close_px > 0:
                                candle_points.append((open_ts + 60, float(close_px)))
                        except Exception:
                            continue
                except Exception:
                    # Do not corrupt rows if a historical data request fails.
                    # They remain open and will be retried on the next rerun.
                    continue

        if candle_points:
            # Dedupe by timestamp and keep a sorted sequence for nearest lookup.
            candle_map = {}
            for candle_ts, candle_px in candle_points:
                candle_map[int(candle_ts)] = float(candle_px)
            candle_points = sorted(candle_map.items())

        def _nearest_price(target_ts):
            if not candle_points:
                return np.nan
            eligible = [(ts, px) for ts, px in candle_points if 0 <= int(target_ts) - ts < 60]
            if not eligible:
                return np.nan
            nearest_ts, nearest_px = max(eligible)
            return float(nearest_px)

        updated = 0
        for row, target_ts, action in prepared:
            start_price = safe_float(row["price"])
            if pd.isna(start_price) or start_price <= 0:
                continue

            # HOLD/WAIT is a completed no-trade observation. Keep it outside
            # directional win/loss accuracy, even if historical data is offline.
            if action in {"HOLD", "WAIT"}:
                resolved_price = _nearest_price(target_ts)
                ret = (
                    (resolved_price / start_price - 1.0) * 100.0
                    if pd.notna(resolved_price) and resolved_price > 0
                    else None
                )
                conn.execute(
                    "UPDATE predictions SET target_ts=?,resolved=1,resolved_price=?,return_pct=?,correct=NULL WHERE id=?",
                    (
                        int(target_ts),
                        None if pd.isna(resolved_price) else float(resolved_price),
                        ret,
                        int(row["id"]),
                    ),
                )
                updated += 1
                continue

            resolved_price = _nearest_price(target_ts)
            if pd.isna(resolved_price) or resolved_price <= 0:
                continue

            ret = (resolved_price / start_price - 1.0) * 100.0
            strike = safe_float(row["target_price"])

            if action == "SCALP UP":
                correct = int(resolved_price > start_price)
            elif action == "SCALP DOWN":
                correct = int(resolved_price < start_price)
            elif action == "LOCK UP":
                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)
            elif action == "LOCK DOWN":
                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)
            else:
                correct = None

            conn.execute(
                """UPDATE predictions
                   SET target_ts=?,resolved=1,resolved_price=?,return_pct=?,correct=?
                   WHERE id=?""",
                (
                    int(target_ts),
                    float(resolved_price),
                    float(ret),
                    correct,
                    int(row["id"]),
                ),
            )
            updated += 1

        conn.commit()
    return updated


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
                      SUM(CASE WHEN resolved=1 AND action NOT IN ('HOLD','WAIT') THEN 1 ELSE 0 END) AS trade_resolved_n,
                      SUM(CASE WHEN resolved=1 AND action NOT IN ('HOLD','WAIT') AND correct=1 THEN 1 ELSE 0 END) AS correct_n,
                      SUM(CASE WHEN resolved=1 AND action IN ('HOLD','WAIT') THEN 1 ELSE 0 END) AS wait_resolved_n,
                      AVG(CASE WHEN resolved=1 THEN ABS(return_pct) END) AS avg_abs_move
               FROM predictions"""
        ).fetchone()
    n = int(row["n"] or 0)
    resolved_n = int(row["resolved_n"] or 0)
    trade_resolved_n = int(row["trade_resolved_n"] or 0)
    correct_n = int(row["correct_n"] or 0)
    wait_resolved_n = int(row["wait_resolved_n"] or 0)
    return {
        "n": n,
        "resolved": resolved_n,
        "trade_resolved": trade_resolved_n,
        "wait_resolved": wait_resolved_n,
        "accuracy": correct_n / trade_resolved_n if trade_resolved_n else np.nan,
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
render_market_guide()

# ============================================================
# SIDEBAR
# ============================================================

# Persistent Kalshi 15-minute countdown.
# Seed the timer from Streamlit's server-side Kalshi request (avoids browser CORS issues),
# then tick locally in the browser for smooth second-by-second updates.
_timer_close_ms = 0
_timer_ticker = ""
try:
    _timer_payload = fetch_kalshi_bitcoin_markets()
    _timer_market = (_timer_payload or {}).get("current") or {}
    _timer_close_ts = kalshi_close_timestamp(_timer_market)
    if pd.notna(_timer_close_ts):
        _timer_close_ms = int(float(_timer_close_ts) * 1000)
    _timer_ticker = str(_timer_market.get("ticker") or "")
except Exception:
    pass

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
  const TOTAL=15*60;
  let closeMs=Number('__CLOSE_MS__') || null;
  let ticker='__TICKER__';
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
  function rollWindowIfNeeded(){
    if(closeMs && Date.now() >= closeMs){
      // KXBTC15M markets are sequential 15-minute windows. Continue the timer
      // immediately while Streamlit refreshes the exact active ticker in the background.
      const step=15*60*1000;
      while(Date.now() >= closeMs) closeMs += step;
      ticker='';
      status.textContent='Next Kalshi 15m market';
    }
  }
  status.textContent=ticker || (closeMs ? 'Kalshi 15m market' : 'Waiting for Kalshi market…');
  render();
  setInterval(()=>{rollWindowIfNeeded();render();},250);
})();
</script>
</body>
</html>
"""
_kalshi_timer_html = _kalshi_timer_html.replace("__CLOSE_MS__", str(_timer_close_ms)).replace("__TICKER__", _timer_ticker.replace("\\", "").replace("'", ""))
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
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"],
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] span,
        [data-testid="stAlert"] > div {
            color:#eaf2ff !important;
            opacity:1 !important;
        }
        a[aria-label="Link to heading"] {
            display:none !important;
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
        <div style="position:relative;width:100%;height:415px;">
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
    </div>

    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <script>
    (() => {{
        const initial = {payload};
        const chart = document.getElementById("persistent-market-chart");
        const status = document.getElementById("market-status");

        let currentTarget = initial.target;
        let currentTicker = initial.ticker || "";
        // Track the active UTC 15-minute window in the browser. At rollover we
        // immediately clear the old Kalshi target so a previous contract can
        // never remain visible while the new market is publishing.
        let kalshiWindowKey = Math.floor(Date.now() / 900000);
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

        function predictionTrace(rows, horizonMinutes = 15) {{
            const horizon = [1, 5, 15].includes(Number(horizonMinutes)) ? Number(horizonMinutes) : 15;
            const forecast = predictedCandles(rows).slice(0, horizon);

            return {{
                type: "candlestick",
                x: forecast.map(r => r.time),
                open: forecast.map(r => r.open),
                high: forecast.map(r => r.high),
                low: forecast.map(r => r.low),
                close: forecast.map(r => r.close),
                name: "Predicted " + horizon + "m candles",
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

        function predictionPathTrace(rows, horizonMinutes = 15) {{
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
                    predictionTrace(rows, selectedPredictionHorizon),
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

        Plotly.newPlot(
            chart,
            [
                candleTrace(rows),
                predictionTrace(rows, selectedPredictionHorizon),
                predictionPathTrace(rows, selectedPredictionHorizon)
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
                        predictionTrace(rows, selectedPredictionHorizon),
                        predictionPathTrace(rows, selectedPredictionHorizon)
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
            const windowKey = Math.floor(Date.now() / 900000);
            if (windowKey !== kalshiWindowKey) {{
                kalshiWindowKey = windowKey;
                currentTicker = "";
                currentTarget = NaN;
                await Plotly.relayout(chart, {{
                    shapes: [],
                    annotations: []
                }});
                status.textContent = "Loading new Kalshi 15m target…";
            }}

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
        const kalshiTimer = setInterval(updateTarget, 1000);

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
st.caption("1m / 5m / 15m select portions of the same 15-minute forecast, not separately trained models. Forecasts are estimates, not guaranteed price paths.")

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

    # All six reads are independent and already have their original cache TTLs.
    # Starting them together removes network wait stacking without changing any
    # returned value, freshness policy, decision rule, or rendering order.
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="live-feed") as pool:
        ticker_job = pool.submit(fetch_spot_ticker)
        kline_job = pool.submit(fetch_klines, "1m", 500)
        agg_job = pool.submit(fetch_agg_trades, 600)
        futures_job = pool.submit(fetch_futures_snapshot)
        kalshi_job = pool.submit(fetch_kalshi_bitcoin_markets)
        hourly_kalshi_job = pool.submit(fetch_kalshi_hourly_bitcoin_markets)

        try:
            ticker = ticker_job.result()
        except Exception as exc:
            ticker = {"price": np.nan, "change_24h": np.nan, "quote_volume_24h": np.nan, "feed_ms": np.nan, "source": "Unavailable"}
            errors.append(f"Spot ticker: {exc}")

        try:
            raw_hist, kline_ms = kline_job.result()
            hist = enrich_history(raw_hist)
        except Exception as exc:
            hist, kline_ms = pd.DataFrame(), np.nan
            errors.append(f"Klines: {exc}")

        try:
            agg, agg_ms = agg_job.result()
        except Exception as exc:
            agg, agg_ms = pd.DataFrame(), np.nan
            errors.append(f"Aggregate trades: {exc}")

        futures = futures_job.result()
        kalshi = kalshi_job.result()
        hourly_kalshi = hourly_kalshi_job.result()

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
    resolve_predictions(hist, price)

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
    # Confidence card only: keep every other top metric unchanged and add the
    # Master directional lean beside the Confidence label.
    _confidence_action = str(decision.get("action", "HOLD")).upper().strip()
    if "UP" in _confidence_action:
        _confidence_direction = "UP"
    elif "DOWN" in _confidence_action:
        _confidence_direction = "DOWN"
    else:
        _confidence_score = safe_float(
            decision.get("base_score"),
            safe_float(decision.get("score"), 0.0),
        )
        _confidence_direction = "UP" if _confidence_score >= 0 else "DOWN"

    _confidence_color = "#20f0bd" if _confidence_direction == "UP" else "#ff5d72"
    _confidence_arrow = "▲" if _confidence_direction == "UP" else "▼"
    with m4:
        st.markdown(
            f"""
            <div class="confidence-metric-card">
                <div class="confidence-metric-label">
                    Confidence
                    <span style="color:{_confidence_color};">{_confidence_arrow}&nbsp;{_confidence_direction}</span>
                </div>
                <div class="confidence-metric-value">{decision['confidence']*100:.1f}%</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
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

        st.subheader("TradingView-style FVG + MACD Technical Lab")
        st.caption("Calculated locally from the same live BTC candles used by the bots — no TradingView scraping or paid key required.")

        _tech = results.get("FVG / MACD AI", {})
        _tech_cols = st.columns(4)
        _tech_cols[0].metric("Technical AI", _tech.get("signal", "NEUTRAL"))
        _tech_cols[1].metric("Confidence", f"{safe_float(_tech.get('confidence'), 0.0)*100:.1f}%")
        _tech_cols[2].metric("MACD histogram", f"{safe_float(hist['macd_hist'].iloc[-1], 0.0):+.2f}")
        _fresh_fvg = hist.tail(60)
        _bull_count = int(_fresh_fvg.get("bull_fvg", pd.Series(dtype=bool)).fillna(False).sum())
        _bear_count = int(_fresh_fvg.get("bear_fvg", pd.Series(dtype=bool)).fillna(False).sum())
        _tech_cols[3].metric("Fresh FVGs (60m)", f"{_bull_count} bull / {_bear_count} bear")
        st.caption(_tech.get("reason", "FVG/MACD specialist warming up"))

        _tv = hist.tail(180).copy()
        _price_fig = go.Figure()
        _price_fig.add_trace(go.Candlestick(
            x=_tv["time"], open=_tv["open"], high=_tv["high"],
            low=_tv["low"], close=_tv["close"], name="BTCUSDT"
        ))

        # Highlight the most recent bullish and bearish fair-value-gap zones.
        _zone_rows = []
        for _idx, _row in _tv.iterrows():
            if bool(_row.get("bull_fvg", False)):
                _zone_rows.append((
                    _row["time"], safe_float(_row.get("bull_fvg_lower")),
                    safe_float(_row.get("bull_fvg_upper")), "bull"
                ))
            if bool(_row.get("bear_fvg", False)):
                _zone_rows.append((
                    _row["time"], safe_float(_row.get("bear_fvg_lower")),
                    safe_float(_row.get("bear_fvg_upper")), "bear"
                ))
        for _x0, _low, _high, _kind in _zone_rows[-10:]:
            if not (pd.notna(_low) and pd.notna(_high)):
                continue
            _price_fig.add_shape(
                type="rect", x0=_x0, x1=_tv["time"].iloc[-1], y0=_low, y1=_high,
                line=dict(width=1, color="#00d6a3" if _kind == "bull" else "#ff4d68"),
                fillcolor="rgba(0,214,163,0.13)" if _kind == "bull" else "rgba(255,77,104,0.13)",
                layer="below",
            )
        _price_fig.update_layout(
            template="plotly_dark", height=470, margin=dict(l=10, r=10, t=35, b=10),
            title="BTC 1-minute candles with Fair Value Gaps",
            xaxis_rangeslider_visible=False,
            paper_bgcolor="#080d14", plot_bgcolor="#0d141f",
            legend=dict(orientation="h"),
        )
        st.plotly_chart(_price_fig, use_container_width=True, key="fvg_price_chart")

        _macd_fig = go.Figure()
        _macd_fig.add_trace(go.Scatter(
            x=_tv["time"], y=_tv["macd"], mode="lines", name="MACD", line=dict(width=2)
        ))
        _macd_fig.add_trace(go.Scatter(
            x=_tv["time"], y=_tv["macd_signal"], mode="lines", name="Signal", line=dict(width=2)
        ))
        _hist_colors = ["#00d6a3" if safe_float(v, 0.0) >= 0 else "#ff4d68" for v in _tv["macd_hist"]]
        _macd_fig.add_trace(go.Bar(
            x=_tv["time"], y=_tv["macd_hist"], name="Histogram", marker_color=_hist_colors, opacity=0.72
        ))
        _macd_fig.add_hline(y=0, line_width=1, line_dash="dot")
        _macd_fig.update_layout(
            template="plotly_dark", height=300, margin=dict(l=10, r=10, t=35, b=10),
            title="MACD (12, 26, 9)", paper_bgcolor="#080d14", plot_bgcolor="#0d141f",
            legend=dict(orientation="h"),
        )
        st.plotly_chart(_macd_fig, use_container_width=True, key="fvg_macd_chart")

        st.divider()

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
                    f"LOCK {decision['locked_side']} → direction stays fixed; "
                    "the paper position sells at a 95% executable bid or settles at expiry."
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
                f"LOCKED SIDE: {decision['locked_side']} — direction cannot reverse; "
                "paper position sells at a 95% bid or settles at expiry."
            )
        st.info(decision["reason"])

        try:
            _bot_learning_state = fetch_remote_learning_state() or {}
            _bot_regime = detect_regime(hist)
            render_bot_intelligence_dashboard(
                results,
                _bot_learning_state,
                _bot_regime,
                dark_mode=dark_mode,
            )
        except Exception as _bot_ui_exc:
            st.caption(f"Bot Intelligence v4 panel temporarily unavailable: {_bot_ui_exc}")

        st.markdown("### Live specialist signals")
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
            render_dashboard_table(show)
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
                render_dashboard_table(pd.DataFrame(krows))
            else:
                st.info("Kalshi responded, but no open market in the returned page matched Bitcoin/BTC right now.")
        else:
            st.warning("Kalshi public data is currently unavailable. The Event AI automatically falls back to neutral.")
            if show_raw:
                st.code(kalshi.get("error", "Unknown Kalshi error"))

    with tab_paper:
        st.subheader("Automatic Paper Trading")

        _kp = paper_summary(DB_PATH, STARTING_CASH)
        st.caption(
            "PRIMARY P/L EVIDENCE — every balance, position and trade below "
            "comes from the same automatic Kalshi paper ledger."
        )
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Contract Equity", f"${_kp['equity']:,.2f}", f"{_kp['return_pct']:+.2f}%")
        k2.metric("Total P/L", f"${_kp['total_pnl']:+,.2f}")
        k3.metric("Realized P/L", f"${_kp['realized_pnl']:+,.2f}")
        k4.metric("Open P/L", f"${_kp['unrealized_pnl']:+,.2f}")
        _pf = _kp.get("profit_factor")
        k5.metric(
            "Contract Profit Factor",
            "Learning" if _pf is None else ("∞" if not np.isfinite(_pf) else f"{_pf:.2f}"),
        )

        _open_contract = _kp.get("open_position")
        if _open_contract:
            display_position_side = "UP" if _open_contract["side"] == "YES" else "DOWN"
            st.info(
                f"OPEN PAPER {_open_contract['strategy']} {display_position_side} • "
                f"Amount: ${_open_contract['amount_down']:,.2f} • "
                f"Kalshi entry: {_open_contract['entry_price'] * 100:.0f}%"
            )

        auto_state = get_auto_state()
        _status_side = (
            "UP" if _open_contract and _open_contract["side"] == "YES"
            else "DOWN" if _open_contract
            else "NONE"
        )
        status1, status2, status3, status4 = st.columns(4)
        status1.metric("AUTO PAPER", "ON" if bool(auto_state["enabled"]) else "OFF")
        status2.metric("Contract position", _status_side)
        status3.metric("Kalshi call", decision["action"])
        status4.metric("Risk approved", "YES" if risk["approved"] else "NO")

        if bool(auto_state["enabled"]):
            _status_message = (
                auto_result["message"]
                if auto_result.get("message")
                else auto_state.get("last_message", "AUTO PAPER running.")
            )
            _decision_action = str(decision.get("action", "HOLD")).upper()
            if _decision_action in {"SCALP UP", "LOCK UP", "UP"}:
                st.success(_status_message)
            elif _decision_action in {"SCALP DOWN", "LOCK DOWN", "DOWN"}:
                st.error(_status_message)
            else:
                st.info(_status_message)
        else:
            st.info(
                "AUTO PAPER TRADING is off. Turn it on in the sidebar to let "
                "approved paper signals execute automatically."
            )

        st.subheader("Risk Manager")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Approved", "YES" if risk["approved"] else "NO")
        r2.metric("Position size", f"{risk['position_pct']*100:.2f}%")
        r3.metric("Risk score", f"{risk['risk_score']:.2f}")
        r4.metric("Decision", decision["action"])
        _next_amount = max(
            0.0,
            float(_kp["cash"]) * min(0.25, max(0.0, float(risk["position_pct"]))),
        )
        st.metric(
            "Next Approved Amount",
            f"${_next_amount:,.2f}" if risk["approved"] and not _open_contract else "$0.00",
        )
        st.caption(risk["reason"])
        st.caption(
            "Entry rule: automatic SCALP and LOCK trades are rejected above "
            "a 75% Kalshi contract price. SCALP requires a projected 15-point "
            "contract gain; LOCK sells automatically at a 95% executable bid."
        )

        st.subheader("Automatic Kalshi Paper Trade Log")
        _contract_history = paper_history(DB_PATH, STARTING_CASH, limit=100)
        if _contract_history:
            _history_view = pd.DataFrame([
                {
                    "Status": row["status"],
                    "Direction": row["direction"],
                    "Strategy": row["strategy"],
                    "Amount": f"${row['amount']:,.2f}",
                    "Kalshi Entry": f"{row['kalshi_entry_pct']:.0f}%",
                    "Current / Exit": (
                        "N/A" if row["current_or_exit_pct"] is None
                        else f"{row['current_or_exit_pct']:.0f}%"
                    ),
                    "Result": row["result"],
                    "P/L": f"${row['pnl']:+,.2f}",
                    "Opened": pd.to_datetime(
                        row["opened_at"], unit="s", utc=True
                    ).strftime("%Y-%m-%d %H:%M UTC"),
                    "Closed": (
                        "OPEN" if row["closed_at"] is None
                        else pd.to_datetime(
                            row["closed_at"], unit="s", utc=True
                        ).strftime("%Y-%m-%d %H:%M UTC")
                    ),
                }
                for row in _contract_history
            ])
            render_dashboard_table(_history_view)
        else:
            st.info("No automatic Kalshi paper trades yet.")

    with tab_journal:
        stats = prediction_stats()
        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Predictions", stats["n"])
        j2.metric("Trade calls resolved", stats["trade_resolved"])
        j3.metric("Trade-call accuracy", "N/A" if pd.isna(stats["accuracy"]) else f"{stats['accuracy']*100:.1f}%")
        j4.metric("HOLD/WAIT resolved", stats["wait_resolved"])
        st.caption(
            "Win/loss accuracy counts only SCALP/LOCK calls. HOLD/WAIT decisions are still recorded and resolved for learning, but are not treated as wins or losses."
        )
        journal_df = recent_predictions(150)
        if not journal_df.empty:
            if dark_mode:
                # Match the AI Council table: dark card, blue outline, and
                # directional visual cues. This is presentation-only.
                journal_view = journal_df.copy()
                _journal_actions = journal_view["action"].astype(str).str.upper().str.strip()
                _journal_resolved = pd.to_numeric(journal_view["resolved"], errors="coerce").fillna(0).astype(int)
                # Keep database/analytics correctness numeric. Only the dark-mode
                # display copy becomes object dtype so pandas can safely render
                # textual states such as NO TRADE and OPEN.
                journal_view["correct"] = journal_view["correct"].astype(object)
                journal_view.loc[_journal_actions.isin(["HOLD", "WAIT"]), "correct"] = "NO TRADE"
                journal_view.loc[_journal_resolved != 1, "correct"] = "OPEN"

                def _journal_action_badge(value):
                    label = str(value or "HOLD").upper().strip()
                    if label in {"SCALP UP", "LOCK UP", "UP", "BULLISH"}:
                        cls, icon = "journal-up", "▲"
                    elif label in {"SCALP DOWN", "LOCK DOWN", "DOWN", "BEARISH"}:
                        cls, icon = "journal-down", "▼"
                    else:
                        cls, icon = "journal-neutral", "•"
                    return f'<span class="journal-badge {cls}">{icon}&nbsp;&nbsp;{label}</span>'

                def _journal_result_badge(value):
                    label = str(value).upper().strip()
                    if label == "NO TRADE":
                        return '<span class="journal-result journal-neutral">NO TRADE</span>'
                    if label == "OPEN" or pd.isna(value):
                        return '<span class="journal-result journal-pending">OPEN</span>'
                    try:
                        return (
                            '<span class="journal-result journal-win">✓ CORRECT</span>'
                            if int(float(value)) == 1
                            else '<span class="journal-result journal-loss">✕ WRONG</span>'
                        )
                    except Exception:
                        return '<span class="journal-result journal-pending">OPEN</span>'

                def _journal_resolved_badge(value):
                    try:
                        resolved = int(float(value)) == 1
                    except Exception:
                        resolved = False
                    cls = "journal-resolved" if resolved else "journal-pending"
                    text = "RESOLVED" if resolved else "OPEN"
                    return f'<span class="journal-result {cls}">{text}</span>'

                journal_html = journal_view.to_html(
                    index=False,
                    border=0,
                    classes="prediction-journal-table",
                    escape=False,
                    formatters={
                        "action": _journal_action_badge,
                        "resolved": _journal_resolved_badge,
                        "correct": _journal_result_badge,
                    },
                )
                st.markdown(
                    """
                    <style>
                    .prediction-journal-wrap {
                        width:100%; overflow-x:auto; border:1px solid #1687ff;
                        border-radius:12px; background:#0b1220;
                    }
                    .prediction-journal-table {
                        width:100%; border-collapse:collapse; color:#e8eef8;
                        background:#0b1220; font-size:.93rem; margin:0;
                    }
                    .prediction-journal-table thead th {
                        position:sticky; top:0; z-index:1; text-align:left;
                        color:#b8cff7; background:#111c2e; font-weight:700;
                        border-bottom:1px solid #2b3b52; padding:10px 12px;
                        white-space:nowrap;
                    }
                    .prediction-journal-table tbody td {
                        color:#e7edf7; background:#0b1220;
                        border-bottom:1px solid #1e2b3d; padding:9px 12px;
                        vertical-align:middle; white-space:nowrap;
                    }
                    .prediction-journal-table tbody tr:nth-child(even) td {background:#0f1828;}
                    .prediction-journal-table tbody tr:hover td {background:#15243a;}
                    .journal-badge, .journal-result {
                        display:inline-block; min-width:92px; text-align:center;
                        padding:4px 10px; border-radius:7px; font-weight:800;
                        letter-spacing:.02em; line-height:1.2; box-sizing:border-box;
                    }
                    .journal-up, .journal-win, .journal-resolved {
                        color:#00f0b5; background:rgba(0,240,181,.13);
                        border:1px solid rgba(0,240,181,.80);
                    }
                    .journal-down, .journal-loss {
                        color:#ff536b; background:rgba(255,83,107,.13);
                        border:1px solid rgba(255,83,107,.85);
                    }
                    .journal-neutral, .journal-pending {
                        color:#b8c6dc; background:rgba(184,198,220,.09);
                        border:1px solid rgba(184,198,220,.42);
                    }
                    </style>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="prediction-journal-wrap">{journal_html}</div>',
                    unsafe_allow_html=True,
                )
            else:
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

        render_dashboard_table(rolling_master_df)

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

            render_dashboard_table(specialist_multi)

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

            render_dashboard_table(specialist_df)

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

            render_dashboard_table(learning_df)


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
                render_dashboard_table(view)

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
