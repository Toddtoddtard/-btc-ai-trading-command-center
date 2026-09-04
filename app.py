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
APP_VERSION = "2026.09.04-single-file-r10-lock-scalp-semantics"

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

                target = safe_float(market.get("floor_strike"))
                if pd.isna(target) or target <= 0:
                    target = safe_float(market.get("cap_strike"))
                if pd.isna(target) or target <= 0:
                    continue

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
                min(future, key=lambda row: row["_close_ts"])
                if future else (hits[0] if hits else None)
            )

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
    """
    Freeze the current Kalshi 15-minute contract target in session state.
    The target/ticker only changes when Kalshi exposes a different active ticker.
    This prevents the horizontal target from being rebuilt on every live refresh.
    """
    live = current_kalshi_context(kalshi, spot_price)

    if not live.get("available"):
        cached = st.session_state.get("kalshi_contract_snapshot")
        if cached:
            cached = dict(cached)
            cached["distance"] = spot_price - cached["target"]
            cached["distance_pct"] = (
                cached["distance"] / cached["target"]
                if cached.get("target") else np.nan
            )
            return cached
        return live

    live_ticker = live.get("ticker", "")
    cached = st.session_state.get("kalshi_contract_snapshot")

    if (
        cached is None
        or cached.get("ticker") != live_ticker
        or pd.isna(cached.get("target", np.nan))
    ):
        cached = {
            "available": True,
            "ticker": live_ticker,
            "title": live.get("title", "BTC 15 min"),
            "target": live.get("target", np.nan),
            "close_time": live.get("close_time"),
            "market": live.get("market"),
        }
        st.session_state["kalshi_contract_snapshot"] = cached

    # Dynamic fields may refresh, but the target/ticker snapshot stays fixed.
    result = dict(cached)
    result["seconds_remaining"] = live.get("seconds_remaining", np.nan)
    result["up_probability"] = live.get("up_probability", np.nan)
    result["distance"] = (
        spot_price - result["target"]
        if pd.notna(result.get("target", np.nan))
        else np.nan
    )
    result["distance_pct"] = (
        result["distance"] / result["target"]
        if pd.notna(result.get("distance", np.nan)) and result.get("target")
        else np.nan
    )
    return result


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

    # Event / Kalshi 15-minute market
    kctx = stable_kalshi_contract(kalshi, px)
    if kctx["available"]:
        probability = kctx["up_probability"]
        market_score = clamp((probability - 0.5) * 2.0) if pd.notna(probability) else 0.0
        target_distance_score = clamp(
            (px - kctx["target"]) / max(px * 0.0025, 1.0)
        )
        event_score = clamp(0.55 * market_score + 0.45 * target_distance_score)
        event_reason = (
            f"Kalshi target ${kctx['target']:,.2f}; BTC {kctx['distance']:+,.2f} "
            f"({kctx['distance_pct']*100:+.3f}%) vs target; "
            + (
                f"UP market ~{probability*100:.1f}%"
                if pd.notna(probability)
                else "UP market price unavailable"
            )
        )
    else:
        event_score = 0.0
        event_reason = "Live KXBTC15M target unavailable"
    out["Event AI"] = specialist("Event AI", event_score, event_reason)

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


def master_decision(results, hist, kalshi=None):
    weighted_sum = 0.0
    total_weight = 0.0
    signs = []

    for name, result in results.items():
        weight = SPECIALIST_WEIGHTS.get(name, 1.0)
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
st.caption(f"Single-file build {APP_VERSION} • Kalshi BTC 15-minute target engine • SCALP UP / SCALP DOWN / LOCK UP / LOCK DOWN • specialist council • paper-only")

# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("Command Center")

dark_mode = st.sidebar.toggle(
    "🌙 Dark Mode",
    value=True,
    key="dashboard_dark_mode",
    help="Switch the command center and charts between dark and light mode.",
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

    if hist.empty:
        st.error("Price history is unavailable, so the AI engine cannot run safely right now.")
        if errors:
            st.code("\n".join(errors))
        st.stop()

    price = safe_float(ticker.get("price"), safe_float(hist["close"].iloc[-1]))
    if pd.isna(price):
        price = float(hist["close"].iloc[-1])

    results = run_specialists(hist, agg, futures, kalshi)
    decision = master_decision(results, hist, kalshi)
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
    m3.metric("Master", decision["action"])
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

    tab_market, tab_ai, tab_flow, tab_paper, tab_journal, tab_backtest = st.tabs(
        ["Market", "AI Council", "Order Flow + Kalshi", "Paper Trading", "Prediction Journal", "Backtest"]
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

            st.plotly_chart(
                kalshi_15m_chart(
                    hist, price, kctx, decision["projected_end"]
                ),
                use_container_width=True,
                key="kalshi_15m_live_chart",
                config={
                    "displaylogo": False,
                    "scrollZoom": True,
                    "responsive": True,
                    "doubleClick": "reset",
                },
            )

            side_text = (
                "UP"
                if decision["action"] in {"SCALP UP", "LOCK UP"}
                else "DOWN"
                if decision["action"] in {"SCALP DOWN", "LOCK DOWN"}
                else "WAIT"
            )

            call1, call2, call3, call4 = st.columns(4)
            call1.metric("CALL", decision["action"])
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
                f"Live Kalshi market: {kctx['ticker']} • target comes "
                "from Kalshi. The candles use this app's Binance 1-minute feed "
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
        d1.metric("Call", decision["action"])
        d2.metric("Master score", f"{decision['score']:+.3f}")
        d3.metric("Confidence", f"{decision['confidence']*100:.1f}%")
        d4.metric("Consensus", f"{decision['consensus']*100:.1f}%")
        d5.metric("Risk level", decision["risk_level"])
        if decision["action"] in {"LOCK UP", "LOCK DOWN"}:
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