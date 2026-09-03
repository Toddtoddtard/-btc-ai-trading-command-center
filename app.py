import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json
import sqlite3
import os
from datetime import datetime, timezone, timedelta

# ============================================================
# BTC AI COMMAND CENTER — LIVE + JOURNAL + BACKTEST
# ============================================================
# PAPER / RESEARCH ONLY.
# No API keys. No order endpoints. No real trading.
#
# Live mode uses Streamlit fragments for automatic reruns.
# Requires Streamlit >= 1.37 for st.fragment(run_every=...).
# ============================================================

st.set_page_config(
    page_title="BTC AI Command Center",
    page_icon="₿",
    layout="wide",
)

BINANCE_BASE_URL = "https://data-api.binance.vision"
BINANCE_FUTURES_URL = "https://fapi.binance.com"
DB_PATH = os.environ.get("BTC_AI_DB", "btc_ai_journal.sqlite3")

TIMEFRAMES = [
    "1 second", "3 seconds", "5 seconds",
    "1 minute", "3 minutes", "5 minutes", "15 minutes",
]

REFRESH_OPTIONS = {
    "1 second": 1.0,
    "2 seconds": 2.0,
    "5 seconds": 5.0,
    "10 seconds": 10.0,
    "30 seconds": 30.0,
}

HORIZON_MINUTES = 15


# ============================================================
# DATA ACCESS
# ============================================================

def binance_get(base_url, endpoint, params):
    query = urlencode(params)
    url = f"{base_url}{endpoint}?{query}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/3.0",
        },
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


@st.cache_data(ttl=3, show_spinner=False)
def get_btc_candles(limit=750):
    data = binance_get(
        BINANCE_BASE_URL,
        "/api/v3/klines",
        {"symbol": "BTCUSDT", "interval": "1m", "limit": limit},
    )
    if not data:
        raise ValueError("Binance returned no candle data.")
    return pd.DataFrame([
        {
            "time": pd.to_datetime(x[0], unit="ms", utc=True),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
            "quote_volume": float(x[7]),
            "trades": int(x[8]),
        }
        for x in data
    ]).sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=2, show_spinner=False)
def get_recent_trades(limit=1000):
    data = binance_get(
        BINANCE_BASE_URL,
        "/api/v3/aggTrades",
        {"symbol": "BTCUSDT", "limit": limit},
    )
    if not data:
        raise ValueError("Binance returned no recent trades.")
    return pd.DataFrame([
        {
            "time": pd.to_datetime(x["T"], unit="ms", utc=True),
            "price": float(x["p"]),
            "quantity": float(x["q"]),
            "buyer_maker": bool(x["m"]),
        }
        for x in data
    ]).sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=2, show_spinner=False)
def get_live_price():
    data = binance_get(
        BINANCE_BASE_URL,
        "/api/v3/ticker/price",
        {"symbol": "BTCUSDT"},
    )
    return float(data["price"])


@st.cache_data(ttl=3, show_spinner=False)
def get_futures_snapshot():
    out = {"funding": None, "oi": None, "depth": None}
    requests = [
        ("funding", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}),
        ("oi", "/fapi/v1/openInterest", {"symbol": "BTCUSDT"}),
        ("depth", "/fapi/v1/depth", {"symbol": "BTCUSDT", "limit": 50}),
    ]
    for key, endpoint, params in requests:
        try:
            out[key] = binance_get(BINANCE_FUTURES_URL, endpoint, params)
        except Exception:
            pass
    return out


def demo_data():
    rng = np.random.default_rng(7)
    now = pd.Timestamp.now(tz="UTC").floor("min")
    times = pd.date_range(end=now, periods=750, freq="1min")
    close = 77500 + np.cumsum(rng.normal(0, 38, len(times)))
    open_prices = np.r_[close[0], close[:-1]]
    high = np.maximum(open_prices, close) + rng.uniform(3, 28, len(close))
    low = np.minimum(open_prices, close) - rng.uniform(3, 28, len(close))
    volume = rng.lognormal(9.1, 0.45, len(close))
    return pd.DataFrame({
        "time": times,
        "open": open_prices,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "quote_volume": close * volume,
        "trades": 0,
    })


def build_trade_bars(trades, seconds):
    if trades.empty:
        return pd.DataFrame()
    temp = trades.copy()
    temp["sell_volume"] = np.where(temp["buyer_maker"], temp["quantity"], 0.0)
    temp["buy_volume"] = np.where(~temp["buyer_maker"], temp["quantity"], 0.0)
    temp = temp.set_index("time")
    bars = temp["price"].resample(f"{seconds}s").ohlc()
    bars["volume"] = temp["quantity"].resample(f"{seconds}s").sum()
    bars["buy_volume"] = temp["buy_volume"].resample(f"{seconds}s").sum()
    bars["sell_volume"] = temp["sell_volume"].resample(f"{seconds}s").sum()
    bars["trades"] = temp["quantity"].resample(f"{seconds}s").count()
    bars = bars.dropna(subset=["open", "high", "low", "close"])
    bars["buy_pressure"] = np.where(
        bars["volume"] > 0, bars["buy_volume"] / bars["volume"] * 100, 50
    )
    return bars.reset_index()


# ============================================================
# INDICATORS
# ============================================================

def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    return result.fillna(50)


def atr(df, period=14):
    previous_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(
        alpha=1 / period, adjust=False, min_periods=period
    ).mean()


# ============================================================
# SPECIALIST NETWORK
# ============================================================

SPECIALIST_NAMES = [
    "Trend AI", "Momentum AI", "Volume AI", "Pattern AI",
    "S/R AI", "Volatility AI", "Regime AI", "Whale AI",
    "Liquidity AI", "Derivatives AI", "Event AI", "Historical AI",
]

SPECIALIST_DESCRIPTIONS = {
    "Trend AI": "EMA structure + price trend",
    "Momentum AI": "RSI + ROC + MACD",
    "Volume AI": "Volume expansion + trade pressure",
    "Pattern AI": "Candle body + short-term return",
    "S/R AI": "Recent support/resistance location",
    "Volatility AI": "ATR + volatility regime",
    "Regime AI": "Directional vs non-directional structure",
    "Whale AI": "Large-trade/aggressor proxy, not on-chain",
    "Liquidity AI": "Aggressor-side/order-flow proxy",
    "Derivatives AI": "Funding + open interest when available",
    "Event AI": "Neutral until a verified event feed is connected",
    "Historical AI": "Nearest historical feature setups",
}


def calculate_specialists(candles, buy_pressure=50.0, futures=None):
    c = candles.copy().reset_index(drop=True)
    close = c["close"]

    ema9 = ema(close, 9)
    ema21 = ema(close, 21)
    ema50 = ema(close, 50)
    rsi_value = rsi(close, 14)
    atr_value = atr(c, 14)
    macd = ema(close, 12) - ema(close, 26)
    macd_signal = ema(macd, 9)
    roc5 = close.pct_change(5) * 100

    vol_avg = c["volume"].rolling(20).mean()
    avg_vol = vol_avg.iloc[-1]
    volume_ratio = (
        float(c["volume"].iloc[-1] / avg_vol)
        if pd.notna(avg_vol) and avg_vol > 0 else 1.0
    )

    middle = close.rolling(20).mean()
    sd = close.rolling(20).std()
    upper = middle + 2 * sd
    lower = middle - 2 * sd

    current_atr = float(atr_value.iloc[-1])
    if not np.isfinite(current_atr) or current_atr <= 0:
        current_atr = float(close.iloc[-1]) * 0.001

    latest_open = float(c["open"].iloc[-1])
    latest_high = float(c["high"].iloc[-1])
    latest_low = float(c["low"].iloc[-1])
    latest_close = float(close.iloc[-1])
    candle_range = max(latest_high - latest_low, 1e-9)
    candle_body = (latest_close - latest_open) / candle_range
    latest_return = (
        (latest_close - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
        if len(c) > 1 else 0.0
    )

    def score(value):
        return float(np.clip(value, 5, 95))

    trend_strength = (ema9.iloc[-1] - ema21.iloc[-1]) / current_atr
    trend_score = score(50 + 35 * np.tanh(trend_strength * 2))

    rsi_component = float(rsi_value.iloc[-1] - 50)
    roc_component = float(roc5.iloc[-1]) if pd.notna(roc5.iloc[-1]) else 0.0
    macd_component = float(macd.iloc[-1] - macd_signal.iloc[-1])
    macd_scale = max(abs(float(macd.iloc[-1])), current_atr * 0.05, 1e-9)
    momentum_score = score(
        50
        + 22 * np.tanh(rsi_component / 12)
        + 18 * np.tanh(roc_component / 0.25)
        + 10 * np.tanh(macd_component / macd_scale)
    )

    volume_score = score(
        50 + (buy_pressure - 50) * 0.8 + 10 * np.tanh(volume_ratio - 1)
    )

    pattern_score = score(
        50
        + 25 * np.tanh(latest_return / 0.12)
        + 12 * np.tanh(candle_body * 2)
    )

    recent_high = float(c["high"].tail(60).max())
    recent_low = float(c["low"].tail(60).min())
    midpoint = (recent_high + recent_low) / 2
    sr_score = score(
        50 + 22 * np.tanh(
            (latest_close - midpoint) / max(current_atr * 3, 1e-9)
        )
    )

    volatility_percent = current_atr / latest_close * 100
    volatility_score = score(
        55
        + 12 * np.tanh(volume_ratio - 1)
        - 8 * np.tanh((volatility_percent - 0.12) * 3)
    )

    regime_strength = (ema9.iloc[-1] - ema50.iloc[-1]) / current_atr
    regime_score = score(50 + 30 * np.tanh(regime_strength))

    whale_score = score(50 + (buy_pressure - 50) * 0.65)
    liquidity_score = score(50 + (buy_pressure - 50) * 0.9)

    derivatives_score = 50 + roc_component * 8
    derivatives_note = "Price proxy — derivatives feed unavailable"
    if futures:
        funding = futures.get("funding")
        if funding:
            fr = float(funding.get("lastFundingRate", 0))
            derivatives_score += np.clip(-fr * 100000, -12, 12)
            derivatives_note = f"Funding {fr * 100:.4f}%"
            if futures.get("oi"):
                derivatives_note += " • OI live"
    derivatives_score = score(derivatives_score)

    event_score = 50.0

    # Historical analog probability based only on information available
    # at the current bar. It never uses the future target in the feature vector.
    historical_score = 50.0
    historical_note = "Not enough analog history"
    if len(c) >= 140:
        feature_cols = ["rsi", "roc5", "volume_ratio", "atr_pct"]
        x = c.copy()
        x["rsi"] = rsi(x["close"], 14)
        x["roc5"] = x["close"].pct_change(5) * 100
        x["volume_ratio"] = x["volume"] / x["volume"].rolling(20).mean()
        x["atr_pct"] = atr(x, 14) / x["close"] * 100
        target = x["close"].shift(-HORIZON_MINUTES) / x["close"] - 1
        current = x.iloc[-1]
        candidates = x.iloc[:-HORIZON_MINUTES].copy()
        vals = []
        for idx, row in candidates.iterrows():
            y = target.loc[idx]
            if not np.isfinite(y):
                continue
            d = 0.0
            for col in feature_cols:
                val = row[col]
                cur = current[col]
                scale = float(x[col].iloc[:-HORIZON_MINUTES].std())
                if pd.notna(val) and pd.notna(cur) and scale > 1e-9:
                    d += ((float(val) - float(cur)) / scale) ** 2
            vals.append((d, float(y)))
        vals.sort(key=lambda z: z[0])
        vals = vals[:30]
        if len(vals) >= 10:
            prob = float(np.mean([y > 0 for _, y in vals]))
            historical_score = 45 + 55 * prob
            historical_note = f"{len(vals)} nearest analogs • next-15m outcomes"

    scores = {
        "Trend AI": trend_score,
        "Momentum AI": momentum_score,
        "Volume AI": volume_score,
        "Pattern AI": pattern_score,
        "S/R AI": sr_score,
        "Volatility AI": volatility_score,
        "Regime AI": regime_score,
        "Whale AI": whale_score,
        "Liquidity AI": liquidity_score,
        "Derivatives AI": derivatives_score,
        "Event AI": event_score,
        "Historical AI": score(historical_score),
    }

    regime_label = (
        "TRENDING" if regime_score >= 60
        else "BEARISH TREND" if regime_score <= 40
        else "CHOP / MIXED"
    )

    evidence = {
        "Trend AI": f"EMA9 {ema9.iloc[-1]:,.0f} vs EMA21 {ema21.iloc[-1]:,.0f}",
        "Momentum AI": f"RSI {rsi_value.iloc[-1]:.1f} • ROC5 {roc_component:+.3f}%",
        "Volume AI": f"Volume {volume_ratio:.2f}x avg • pressure {buy_pressure:.1f}%",
        "Pattern AI": f"Candle body {candle_body:+.2f} of range • return {latest_return:+.3f}%",
        "S/R AI": f"Support ${recent_low:,.0f} • resistance ${recent_high:,.0f}",
        "Volatility AI": f"ATR ${current_atr:,.0f} • {volatility_percent:.3f}% of price",
        "Regime AI": regime_label,
        "Whale AI": f"Large-trade proxy • aggressor pressure {buy_pressure:.1f}%",
        "Liquidity AI": "Trade imbalance proxy" if not futures or not futures.get("depth") else "Top-50 futures depth",
        "Derivatives AI": derivatives_note,
        "Event AI": "Neutral — no verified point-in-time news feed",
        "Historical AI": historical_note,
    }

    features = {
        "ema9": float(ema9.iloc[-1]),
        "ema21": float(ema21.iloc[-1]),
        "ema50": float(ema50.iloc[-1]),
        "rsi": float(rsi_value.iloc[-1]),
        "atr": float(current_atr),
        "volume_ratio": float(volume_ratio),
        "recent_high": recent_high,
        "recent_low": recent_low,
        "upper_band": float(upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else latest_close,
        "lower_band": float(lower.iloc[-1]) if pd.notna(lower.iloc[-1]) else latest_close,
    }

    return scores, features, evidence


# ============================================================
# MASTER AI
# ============================================================

def master_decision(scores):
    weights = {name: 1.0 for name in scores}
    regime = scores["Regime AI"]

    if regime >= 60:
        for name in ["Trend AI", "Momentum AI", "Volume AI", "Regime AI"]:
            weights[name] = 1.35
    elif regime <= 40:
        weights["Trend AI"] = 0.75
        weights["Momentum AI"] = 0.75
        weights["Volatility AI"] = 1.25

    weights["Whale AI"] = 1.05

    numerator = sum(scores[n] * weights[n] for n in scores)
    denominator = sum(weights.values())
    weighted_score = numerator / denominator

    values = np.array(list(scores.values()), dtype=float)
    disagreement = float(np.std(values))

    confidence = float(np.clip(
        50 + abs(weighted_score - 50) * 1.55 - disagreement * 0.22,
        50, 95
    ))

    if weighted_score >= 58 and confidence >= 60:
        signal = "SCALP UP"
    elif weighted_score <= 42 and confidence >= 60:
        signal = "SCALP DOWN"
    else:
        signal = "WAIT"

    contributions = {}
    for name, value in scores.items():
        contributions[name] = {
            "score": float(value),
            "weight": float(weights[name]),
            "contribution": float((value - 50) * weights[name]),
        }

    return signal, confidence, float(weighted_score), disagreement, contributions


# ============================================================
# FORECAST
# ============================================================

def make_forecast(candles, signal, confidence, features):
    last_price = float(candles["close"].iloc[-1])
    current_atr = max(float(features["atr"]), last_price * 0.0005)
    direction = 1 if signal == "SCALP UP" else -1 if signal == "SCALP DOWN" else 0
    strength = max(0.15, (confidence - 50) / 45)
    expected = last_price + direction * current_atr * (0.8 + 1.4 * strength)

    start = candles["time"].iloc[-1] + pd.Timedelta(minutes=1)
    future = pd.date_range(start=start, periods=HORIZON_MINUTES, freq="1min")
    path = np.linspace(last_price, expected, HORIZON_MINUTES)
    uncertainty = current_atr * (0.45 + 0.04 * np.arange(HORIZON_MINUTES))
    return future, path, path + uncertainty, path - uncertainty, expected


# ============================================================
# PREDICTION JOURNAL — SQLITE
# ============================================================

def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = db_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            target_time TEXT NOT NULL,
            price REAL NOT NULL,
            signal TEXT NOT NULL,
            confidence REAL NOT NULL,
            bullish_score REAL NOT NULL,
            disagreement REAL NOT NULL,
            expected_price REAL,
            specialist_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            actual_price REAL,
            return_pct REAL,
            correct INTEGER,
            scored_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def journal_prediction(
    candle_time,
    price,
    signal,
    confidence,
    bullish_score,
    disagreement,
    expected_price,
    scores,
    evidence,
):
    key = f"{pd.Timestamp(candle_time).isoformat()}|{HORIZON_MINUTES}"
    target = pd.Timestamp(candle_time) + pd.Timedelta(minutes=HORIZON_MINUTES)
    conn = db_conn()
    conn.execute("""
        INSERT OR IGNORE INTO predictions
        (prediction_key, created_at, target_time, price, signal, confidence,
         bullish_score, disagreement, expected_price, specialist_json, evidence_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        key,
        pd.Timestamp(candle_time).isoformat(),
        target.isoformat(),
        float(price),
        signal,
        float(confidence),
        float(bullish_score),
        float(disagreement),
        float(expected_price),
        json.dumps(scores),
        json.dumps(evidence),
    ))
    conn.commit()
    conn.close()


def score_journal(candles):
    if candles.empty:
        return
    conn = db_conn()
    rows = conn.execute("""
        SELECT id, target_time, price, signal
        FROM predictions
        WHERE actual_price IS NULL
        ORDER BY target_time ASC
        LIMIT 1000
    """).fetchall()

    for row_id, target_time, entry_price, signal in rows:
        target_ts = pd.Timestamp(target_time)
        eligible = candles[candles["time"] >= target_ts]
        if eligible.empty:
            continue
        actual = float(eligible.iloc[0]["close"])
        ret_pct = (actual / float(entry_price) - 1) * 100
        correct = (
            1 if ret_pct > 0 else 0
        ) if signal == "SCALP UP" else (
            1 if ret_pct < 0 else 0
        ) if signal == "SCALP DOWN" else (
            1 if abs(ret_pct) < 0.15 else 0
        )
        conn.execute("""
            UPDATE predictions
            SET actual_price=?, return_pct=?, correct=?, scored_at=?
            WHERE id=?
        """, (
            actual,
            ret_pct,
            correct,
            datetime.now(timezone.utc).isoformat(),
            row_id,
        ))
    conn.commit()
    conn.close()


def journal_stats():
    conn = db_conn()
    df = pd.read_sql_query("SELECT * FROM predictions ORDER BY id", conn)
    conn.close()
    if df.empty:
        return {
            "count": 0, "scored": 0, "win_rate": None,
            "profit_factor": None, "drawdown": None,
            "brier": None, "df": df,
        }

    scored = df[df["actual_price"].notna()].copy()
    if scored.empty:
        return {
            "count": len(df), "scored": 0, "win_rate": None,
            "profit_factor": None, "drawdown": None,
            "brier": None, "df": df,
        }

    wins = scored["correct"].fillna(0).astype(int)
    win_rate = float(wins.mean() * 100)

    # A simple paper strategy return:
    # UP -> actual return; DOWN -> inverse actual return; WAIT -> 0.
    strat = np.where(
        scored["signal"].eq("SCALP UP"),
        scored["return_pct"],
        np.where(scored["signal"].eq("SCALP DOWN"),
                 -scored["return_pct"], 0.0)
    )
    strat = pd.Series(strat, index=scored.index)
    gross_profit = float(strat[strat > 0].sum())
    gross_loss = float(-strat[strat < 0].sum())
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else None
    )

    equity = strat.cumsum()
    drawdown = equity - equity.cummax()
    max_dd = float(abs(drawdown.min())) if not drawdown.empty else 0.0

    # Probability calibration for UP vs not-UP.
    probs = scored["bullish_score"] / 100.0
    outcomes = (scored["return_pct"] > 0).astype(float)
    brier = float(np.mean((probs - outcomes) ** 2))

    return {
        "count": len(df),
        "scored": len(scored),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "drawdown": max_dd,
        "brier": brier,
        "df": df,
    }


# ============================================================
# BACKTEST
# ============================================================

def historical_buy_pressure(df, i):
    # Historical candles do not contain aggressor-side trade data.
    # Use a deliberately labeled candle-pressure proxy for walk-forward testing.
    row = df.iloc[i]
    rng = max(float(row["high"] - row["low"]), 1e-9)
    body = (float(row["close"]) - float(row["open"])) / rng
    vol_ratio = (
        float(row["volume"]) /
        max(float(df["volume"].iloc[max(0, i-19):i+1].mean()), 1e-9)
    )
    return float(np.clip(50 + body * 22 + (vol_ratio - 1) * 8, 5, 95))


@st.cache_data(ttl=300, show_spinner=False)
def run_backtest(candles, step=5):
    df = candles.copy().reset_index(drop=True)
    results = []

    # Walk forward. The target is strictly after the prediction bar.
    start = 80
    end = len(df) - HORIZON_MINUTES - 1
    for i in range(start, end, step):
        history = df.iloc[:i + 1].copy()
        pressure = historical_buy_pressure(df, i)
        scores, features, evidence = calculate_specialists(
            history, pressure, futures=None
        )
        signal, confidence, bull, disagreement, _ = master_decision(scores)

        entry = float(df["close"].iloc[i])
        exit_price = float(df["close"].iloc[i + HORIZON_MINUTES])
        ret = (exit_price / entry - 1) * 100

        if signal == "SCALP UP":
            pnl = ret
            correct = ret > 0
        elif signal == "SCALP DOWN":
            pnl = -ret
            correct = ret < 0
        else:
            pnl = 0.0
            correct = abs(ret) < 0.15

        results.append({
            "time": df["time"].iloc[i],
            "signal": signal,
            "confidence": confidence,
            "bullish_score": bull,
            "disagreement": disagreement,
            "return_pct": ret,
            "strategy_return_pct": pnl,
            "correct": int(correct),
            "regime": (
                "UP" if scores["Regime AI"] >= 60
                else "DOWN" if scores["Regime AI"] <= 40
                else "MIXED"
            ),
        })

    result = pd.DataFrame(results)
    if result.empty:
        return result, {}

    non_wait = result[result["signal"] != "WAIT"].copy()
    win_rate = float(result["correct"].mean() * 100)
    avg_return = float(result["strategy_return_pct"].mean())
    gross_profit = float(result.loc[result.strategy_return_pct > 0, "strategy_return_pct"].sum())
    gross_loss = float(-result.loc[result.strategy_return_pct < 0, "strategy_return_pct"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else None

    equity = result["strategy_return_pct"].cumsum()
    dd = equity - equity.cummax()
    max_dd = float(abs(dd.min()))

    brier = float(np.mean(
        ((result["bullish_score"] / 100) - (result["return_pct"] > 0).astype(float)) ** 2
    ))

    metrics = {
        "samples": len(result),
        "trades": len(non_wait),
        "win_rate": win_rate,
        "avg_strategy_return": avg_return,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "brier": brier,
    }
    return result, metrics


# ============================================================
# LIVE REFRESH STATE
# ============================================================

init_db()

if "streaming" not in st.session_state:
    st.session_state.streaming = True
if "refresh_seconds" not in st.session_state:
    st.session_state.refresh_seconds = 2.0


# ============================================================
# SIDEBAR CONTROLS
# ============================================================

with st.sidebar:
    st.header("Controls")

    timeframe = st.selectbox(
        "Chart timeframe", TIMEFRAMES, index=6, key="timeframe"
    )

    mode = st.selectbox(
        "Trading mode",
        ["PAPER", "SIMULATED LIVE", "LIVE (LOCKED)"],
        key="mode",
    )

    refresh_seconds = st.select_slider(
        "Live refresh",
        options=list(REFRESH_OPTIONS.values()),
        value=st.session_state.refresh_seconds,
        format_func=lambda x: (
            f"{int(x)} second" if x == 1 else f"{int(x)} seconds"
        ),
        key="refresh_seconds",
    )

    st.session_state.refresh_seconds = refresh_seconds

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "▶ Start", disabled=st.session_state.streaming, use_container_width=True
        ):
            st.session_state.streaming = True
            st.rerun()
    with c2:
        if st.button(
            "⏸ Stop", disabled=not st.session_state.streaming, use_container_width=True
        ):
            st.session_state.streaming = False
            st.rerun()

    if st.button("🔄 Force full refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.subheader("Prediction Window")
    now = pd.Timestamp.now(tz="UTC")
    elapsed = ((now.minute % 15) * 60 + now.second) / 900
    st.progress(
        float(np.clip(elapsed, 0, 1)),
        text=f"{elapsed * 100:.0f}% of current 15m window elapsed",
    )

    st.divider()
    st.subheader("Safety")
    st.info(
        "PAPER ONLY. This application contains no order-placement "
        "code or trading API credentials."
    )

    if mode == "LIVE (LOCKED)":
        st.warning("🔒 LIVE trading is intentionally locked.")


# ============================================================
# LIVE DASHBOARD FRAGMENT
# ============================================================

run_every = f"{refresh_seconds}s" if st.session_state.streaming else None


@st.fragment(run_every=run_every)
def live_dashboard():
    fetch_started = datetime.now(timezone.utc)

    try:
        candles = get_btc_candles()
        trades = get_recent_trades()
        live_price = get_live_price()
        futures = get_futures_snapshot()
        live_ok = True
        data_error = ""
    except Exception as error:
        live_ok = False
        data_error = str(error)
        candles = demo_data()
        trades = pd.DataFrame()
        live_price = float(candles["close"].iloc[-1])
        futures = {"funding": None, "oi": None, "depth": None}

    bars_1s = build_trade_bars(trades, 1) if live_ok else pd.DataFrame()
    bars_3s = build_trade_bars(trades, 3) if live_ok else pd.DataFrame()
    bars_5s = build_trade_bars(trades, 5) if live_ok else pd.DataFrame()

    if not trades.empty:
        total_volume = float(trades["quantity"].sum())
        buy_volume = float(trades.loc[~trades["buyer_maker"], "quantity"].sum())
        buy_pressure = buy_volume / total_volume * 100 if total_volume > 0 else 50.0
        trade_count = len(trades)
    else:
        buy_pressure = 50.0
        trade_count = 0

    scores, features, evidence = calculate_specialists(
        candles, buy_pressure, futures
    )
    signal, confidence, master_score, disagreement, contributions = master_decision(scores)
    future, forecast, upper, lower, expected = make_forecast(
        candles, signal, confidence, features
    )

    # Persist one prediction per completed/current 1m candle bucket.
    current_bar_time = pd.Timestamp(candles["time"].iloc[-1])
    journal_prediction(
        current_bar_time,
        float(candles["close"].iloc[-1]),
        signal,
        confidence,
        master_score,
        disagreement,
        expected,
        scores,
        evidence,
    )
    score_journal(candles)
    stats = journal_stats()

    fetch_ms = (datetime.now(timezone.utc) - fetch_started).total_seconds() * 1000

    # ========================================================
    # HEADER
    # ========================================================

    st.title("₿ BTC AI Trading Command Center")
    st.caption(
        "Live multi-agent BTC market engine • 15-minute primary horizon • "
        "Prediction Journal • Walk-forward Backtesting • PAPER ONLY"
    )

    if live_ok:
        st.success(
            f"🟢 LIVE BTC DATA — BINANCE • updated "
            f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )
    else:
        st.warning("🟡 DEMO DATA — BINANCE CONNECTION FAILED")
        st.caption(f"Connection error: {data_error}")

    # ========================================================
    # MASTER
    # ========================================================

    st.subheader("Master Prediction")

    signal_text = f"{signal} • {confidence:.1f}% confidence"
    if signal == "SCALP UP":
        st.success(f"🟢 {signal_text}")
    elif signal == "SCALP DOWN":
        st.error(f"🔴 {signal_text}")
    else:
        st.warning(f"🟡 {signal_text}")

    master_cols = st.columns(5)
    with master_cols[0]:
        st.metric("BTC Price", f"${live_price:,.2f}")
    with master_cols[1]:
        st.metric("Master Bullish Score", f"{master_score:.1f}%")
    with master_cols[2]:
        st.metric("Trade Pressure", f"{buy_pressure:.1f}%", f"{buy_pressure - 50:+.1f} pts")
    with master_cols[3]:
        st.metric("AI Disagreement", f"{disagreement:.1f} pts")
    with master_cols[4]:
        st.metric("Feed Latency", f"{fetch_ms:.0f} ms")

    st.caption(
        "Bullish scores are engineered signal scores, not trained-model "
        "probabilities. They do not guarantee future price movement."
    )

    # ========================================================
    # TRADE PLAN
    # ========================================================

    st.subheader("Trade Plan — Paper Only")
    entry_low = live_price - features["atr"] * 0.20
    entry_high = live_price + features["atr"] * 0.20

    if signal == "SCALP UP":
        target = live_price + features["atr"] * 1.4
        invalidation = live_price - features["atr"] * 0.8
    elif signal == "SCALP DOWN":
        target = live_price - features["atr"] * 1.4
        invalidation = live_price + features["atr"] * 0.8
    else:
        target = invalidation = None

    plan_cols = st.columns(4)
    with plan_cols[0]:
        st.metric("Entry Zone", f"${entry_low:,.0f}–${entry_high:,.0f}")
    with plan_cols[1]:
        st.metric("Target", f"${target:,.0f}" if target else "—")
    with plan_cols[2]:
        st.metric("Invalidation", f"${invalidation:,.0f}" if invalidation else "—")
    with plan_cols[3]:
        st.metric("ATR (1m)", f"${features['atr']:,.2f}")

    # ========================================================
    # SHORT-TERM ENGINE
    # ========================================================

    st.subheader("Short-Term BTC Market Engine")
    short_cols = st.columns(5)
    with short_cols[0]:
        st.metric("Recent Trades", f"{trade_count:,}")
    with short_cols[1]:
        st.metric("Buy Pressure", f"{buy_pressure:.1f}%")
    with short_cols[2]:
        st.metric("Sell Pressure", f"{100 - buy_pressure:.1f}%")
    with short_cols[3]:
        st.metric("1s / 3s / 5s", "ACTIVE" if not bars_1s.empty else "WAITING")
    with short_cols[4]:
        st.metric("Data Feed", "LIVE" if live_ok else "DEMO")

    # ========================================================
    # MARKET CHART
    # ========================================================

    if timeframe == "1 second":
        chart_df = bars_1s.tail(180)
    elif timeframe == "3 seconds":
        chart_df = bars_3s.tail(180)
    elif timeframe == "5 seconds":
        chart_df = bars_5s.tail(180)
    elif timeframe == "1 minute":
        chart_df = candles.tail(240)
    elif timeframe == "3 minutes":
        chart_df = resample_candles(candles, "3min").tail(160)
    elif timeframe == "5 minutes":
        chart_df = resample_candles(candles, "5min").tail(120)
    else:
        chart_df = resample_candles(candles, "15min").tail(80)

    st.subheader(f"BTC Market Chart — {timeframe}")
    if chart_df.empty:
        st.info("Waiting for enough recent trade data for this timeframe.")
    else:
        chart = go.Figure()
        chart.add_trace(go.Candlestick(
            x=chart_df["time"],
            open=chart_df["open"],
            high=chart_df["high"],
            low=chart_df["low"],
            close=chart_df["close"],
            name="BTC",
        ))
        chart.update_layout(
            height=450,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis_rangeslider_visible=False,
        )
        st.plotly_chart(chart, use_container_width=True)

    # ========================================================
    # FORECAST
    # ========================================================

    st.subheader("15-Minute AI Prediction")
    recent = candles.tail(120)

    prediction_fig = go.Figure()
    prediction_fig.add_trace(go.Candlestick(
        x=recent["time"],
        open=recent["open"],
        high=recent["high"],
        low=recent["low"],
        close=recent["close"],
        name="BTC",
    ))
    prediction_fig.add_trace(go.Scatter(
        x=future, y=forecast, mode="lines",
        name="Feature forecast", line=dict(width=3),
    ))
    prediction_fig.add_trace(go.Scatter(
        x=list(future) + list(future[::-1]),
        y=list(upper) + list(lower[::-1]),
        fill="toself", line=dict(width=0),
        name="Uncertainty band", opacity=0.18,
    ))
    prediction_fig.add_trace(go.Scatter(
        x=[future[-1]], y=[expected], mode="markers",
        name="15m endpoint", marker=dict(size=10),
    ))
    prediction_fig.update_layout(
        height=450,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(prediction_fig, use_container_width=True)

    # ========================================================
    # DECISION EVIDENCE / STRUCTURED REASONING
    # ========================================================

    st.subheader("🧠 Master Decision Evidence")
    st.caption(
        "This is an auditable signal summary—not private chain-of-thought. "
        "It shows which measurable factors influenced the decision."
    )

    evidence_rows = []
    for name in SPECIALIST_NAMES:
        item = contributions[name]
        evidence_rows.append({
            "Specialist": name,
            "Signal Score": round(item["score"], 1),
            "Weight": round(item["weight"], 2),
            "Weighted Contribution": round(item["contribution"], 2),
            "Evidence": evidence[name],
        })

    evidence_df = pd.DataFrame(evidence_rows)
    st.dataframe(evidence_df, use_container_width=True, hide_index=True)

    top = sorted(
        evidence_rows,
        key=lambda r: abs(r["Weighted Contribution"]),
        reverse=True,
    )[:4]
    st.info(
        "Top decision factors: "
        + " • ".join(
            f"{r['Specialist']} {r['Signal Score']:.1f}%"
            for r in top
        )
        + f". Master disagreement is {disagreement:.1f} points."
    )

    # ========================================================
    # SPECIALISTS
    # ========================================================

    st.subheader("Specialist AI Network")
    grid = st.columns(3)
    for i, name in enumerate(SPECIALIST_NAMES):
        value = scores[name]
        direction = "UP" if value >= 55 else "DOWN" if value <= 45 else "MIXED"
        with grid[i % 3]:
            st.metric(
                name,
                f"{direction} • {value:.1f}%",
                SPECIALIST_DESCRIPTIONS[name],
            )

    # ========================================================
    # WHALE
    # ========================================================

    st.subheader("🐋 Whale AI — Independent Indicator")
    whale = scores["Whale AI"]
    w1, w2 = st.columns(2)
    with w1:
        st.metric("Whale Bullish Pressure", f"{whale:.1f}%")
    with w2:
        st.metric("Whale Bearish Pressure", f"{100 - whale:.1f}%")
    st.progress(whale / 100)
    st.caption(
        "Important: free Binance spot trade data does not contain blockchain "
        "whale transfers. Whale AI is currently a large-trade/aggressor "
        "proxy and does not claim to see on-chain wallets."
    )

    # ========================================================
    # COMBINATION LAYER
    # ========================================================

    st.subheader("AI Communication & Combination Layer")
    combinations = [
        ("Trend + Momentum + Regime",
         np.mean([scores["Trend AI"], scores["Momentum AI"], scores["Regime AI"]]),
         "Directional structure"),
        ("Volume + Liquidity + Whale",
         np.mean([scores["Volume AI"], scores["Liquidity AI"], scores["Whale AI"]]),
         "Aggressor-side pressure"),
        ("S/R + Volatility",
         np.mean([scores["S/R AI"], scores["Volatility AI"]]),
         "Location + risk"),
        ("Historical + Pattern",
         np.mean([scores["Historical AI"], scores["Pattern AI"]]),
         "Setup similarity"),
    ]
    interaction_rows = []
    for name, value, comment in combinations:
        interaction_rows.append([
            name,
            "UP" if value >= 58 else "DOWN" if value <= 42 else "WAIT",
            round(float(value), 1),
            comment,
        ])
    st.dataframe(pd.DataFrame(
        interaction_rows,
        columns=["Combination", "Signal", "Score", "Comment"],
    ), use_container_width=True, hide_index=True)

    # ========================================================
    # LIVE FEATURES
    # ========================================================

    st.subheader("Live Feature Snapshot")
    feature_cols = st.columns(6)
    with feature_cols[0]:
        st.metric("RSI", f"{features['rsi']:.1f}")
    with feature_cols[1]:
        st.metric("EMA 9", f"${features['ema9']:,.2f}")
    with feature_cols[2]:
        st.metric("EMA 21", f"${features['ema21']:,.2f}")
    with feature_cols[3]:
        st.metric("EMA 50", f"${features['ema50']:,.2f}")
    with feature_cols[4]:
        st.metric("Volume Ratio", f"{features['volume_ratio']:.2f}x")
    with feature_cols[5]:
        st.metric("ATR", f"${features['atr']:,.0f}")

    # ========================================================
    # PREDICTION JOURNAL
    # ========================================================

    st.subheader("📓 Prediction Journal")

    j1, j2, j3, j4 = st.columns(4)
    with j1:
        st.metric("Predictions Logged", f"{stats['count']:,}")
    with j2:
        st.metric(
            "Scored Predictions",
            f"{stats['scored']:,}",
        )
    with j3:
        st.metric(
            "Journal Win Rate",
            f"{stats['win_rate']:.1f}%"
            if stats["win_rate"] is not None else "—",
        )
    with j4:
        st.metric(
            "Calibration Brier",
            f"{stats['brier']:.3f}"
            if stats["brier"] is not None else "—",
        )

    journal_df = stats["df"].tail(30).copy()
    if not journal_df.empty:
        display_cols = [
            "created_at", "target_time", "price", "signal",
            "confidence", "bullish_score", "actual_price",
            "return_pct", "correct",
        ]
        display_cols = [c for c in display_cols if c in journal_df.columns]
        st.dataframe(
            journal_df[display_cols].sort_values("created_at", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "The journal will begin scoring after a full 15-minute prediction "
            "horizon has elapsed."
        )

    # ========================================================
    # BACKTEST
    # ========================================================

    st.subheader("📈 Walk-Forward Backtesting")

    with st.spinner("Running the same specialist/master logic over history..."):
        bt_df, bt = run_backtest(candles, step=5)

    if bt:
        b1, b2, b3, b4, b5 = st.columns(5)
        with b1:
            st.metric("Samples", f"{bt['samples']:,}")
        with b2:
            st.metric("Walk-Forward Win Rate", f"{bt['win_rate']:.1f}%")
        with b3:
            st.metric(
                "Profit Factor",
                f"{bt['profit_factor']:.2f}" if bt["profit_factor"] is not None else "—",
            )
        with b4:
            st.metric("Max Drawdown", f"{bt['max_drawdown']:.2f}%")
        with b5:
            st.metric("Brier Score", f"{bt['brier']:.3f}")

        equity = bt_df["strategy_return_pct"].cumsum()
        bt_fig = go.Figure()
        bt_fig.add_trace(go.Scatter(
            x=bt_df["time"],
            y=equity,
            mode="lines",
            name="Cumulative paper return",
        ))
        bt_fig.update_layout(
            height=320,
            title="Walk-Forward Cumulative Strategy Return",
            yaxis_title="Cumulative return (%)",
            xaxis_title="Prediction time",
        )
        st.plotly_chart(bt_fig, use_container_width=True)

        regime_summary = (
            bt_df.groupby("regime")
            .agg(
                Samples=("regime", "size"),
                Win_Rate=("correct", "mean"),
                Avg_Strategy_Return=("strategy_return_pct", "mean"),
            )
            .reset_index()
        )
        regime_summary["Win_Rate"] *= 100
        st.dataframe(
            regime_summary.round(3),
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Backtest is walk-forward: each prediction uses only candles available "
            "before its target horizon. Historical aggressor pressure is a labeled "
            "candle-pressure proxy because old Binance candle data does not contain "
            "the same recent trade stream."
        )
    else:
        st.info("Not enough historical candles for the walk-forward test.")

    # ========================================================
    # SYSTEM STATUS
    # ========================================================

    st.subheader("System Status")
    status_cols = st.columns(5)

    with status_cols[0]:
        st.success("BTC DATA — LIVE" if live_ok else "BTC DATA — DEMO")
    with status_cols[1]:
        st.success("AUTO REFRESH — ON" if st.session_state.streaming else "AUTO REFRESH — OFF")
    with status_cols[2]:
        st.success("SPECIALISTS — LIVE CALCULATED")
    with status_cols[3]:
        st.success("JOURNAL — SQLITE ACTIVE")
    with status_cols[4]:
        st.info("TRADING — PAPER ONLY")

    st.divider()
    st.caption(
        "Last dashboard update: "
        + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        + f" • refresh interval {refresh_seconds:g}s"
    )
    st.caption(
        "⚠️ Educational/research/paper-trading prototype. Not financial advice. "
        "No real trades are placed. Live trading is locked."
    )


# ============================================================
# RENDER
# ============================================================

live_dashboard()


# ============================================================
# HELP / COMPATIBILITY NOTE
# ============================================================

with st.expander("Build Notes"):
    st.markdown(
        """
**What is now live:**
- Automatic dashboard reruns using `st.fragment(run_every=...)`
- 1s / 3s / 5s trade bars from recent Binance aggregate trades
- Live spot price, candles, trade pressure, futures funding/OI/depth
- 12 specialist signal engines
- Master weighted decision layer
- Auditable decision evidence and weighted contributions
- Persistent SQLite prediction journal
- Automatic 15-minute outcome scoring
- Walk-forward backtesting using the same specialist/master architecture
- Win rate, profit factor, drawdown and Brier calibration metrics
- Regime-level backtest breakdown

**Important modeling distinction:**
The specialist percentages are engineered scores, not probabilities from a
trained predictive model. The journal/backtest is what turns those scores into
measurable historical performance.

**Safety:**
This app contains no Binance API key handling and no order-placement endpoint.
"""
    )
