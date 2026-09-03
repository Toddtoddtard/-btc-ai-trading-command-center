import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json
import sqlite3
import os
import traceback
from datetime import datetime, timezone

# ============================================================
# BTC AI COMMAND CENTER — CLEAN PHONE COPY/PASTE BUILD
# ============================================================
# PAPER / RESEARCH ONLY.
# No API keys. No order endpoints. No real trading.
#
# Requires Streamlit >= 1.37.
# ============================================================

st.set_page_config(
    page_title="BTC AI Command Center",
    page_icon="₿",
    layout="wide",
)

BINANCE = "https://data-api.binance.vision"
FUTURES = "https://fapi.binance.com"
DB_PATH = os.environ.get("BTC_AI_DB", "btc_ai_journal.sqlite3")
HORIZON = 15

SPECIALISTS = [
    "Trend AI", "Momentum AI", "Volume AI", "Pattern AI",
    "S/R AI", "Volatility AI", "Regime AI", "Whale AI",
    "Liquidity AI", "Derivatives AI", "Event AI", "Historical AI",
]

DESCRIPTIONS = {
    "Trend AI": "EMA trend structure",
    "Momentum AI": "RSI, ROC and MACD",
    "Volume AI": "Volume expansion and pressure",
    "Pattern AI": "Candle body and short return",
    "S/R AI": "Recent support/resistance",
    "Volatility AI": "ATR and volatility",
    "Regime AI": "Trend vs chop",
    "Whale AI": "Large-trade/aggressor proxy",
    "Liquidity AI": "Order-flow/depth proxy",
    "Derivatives AI": "Funding and open interest",
    "Event AI": "Verified event feed",
    "Historical AI": "Nearest historical setups",
}


# ============================================================
# SAFE DATA ACCESS
# ============================================================

def api_get(base, endpoint, params):
    url = f"{base}{endpoint}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/4.0",
        },
    )
    with urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


@st.cache_data(ttl=3, show_spinner=False)
def get_candles(limit=750):
    data = api_get(
        BINANCE,
        "/api/v3/klines",
        {"symbol": "BTCUSDT", "interval": "1m", "limit": limit},
    )
    if not data:
        raise RuntimeError("Binance returned no candle data.")

    return pd.DataFrame(
        [
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
        ]
    ).sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=2, show_spinner=False)
def get_trades(limit=1000):
    data = api_get(
        BINANCE,
        "/api/v3/aggTrades",
        {"symbol": "BTCUSDT", "limit": limit},
    )
    if not data:
        raise RuntimeError("Binance returned no trade data.")

    return pd.DataFrame(
        [
            {
                "time": pd.to_datetime(x["T"], unit="ms", utc=True),
                "price": float(x["p"]),
                "quantity": float(x["q"]),
                "buyer_maker": bool(x["m"]),
            }
            for x in data
        ]
    ).sort_values("time").reset_index(drop=True)


@st.cache_data(ttl=2, show_spinner=False)
def get_price():
    data = api_get(
        BINANCE,
        "/api/v3/ticker/price",
        {"symbol": "BTCUSDT"},
    )
    return float(data["price"])


@st.cache_data(ttl=3, show_spinner=False)
def get_futures():
    result = {"funding": None, "oi": None, "depth": None}

    calls = [
        ("funding", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"}),
        ("oi", "/fapi/v1/openInterest", {"symbol": "BTCUSDT"}),
        ("depth", "/fapi/v1/depth", {"symbol": "BTCUSDT", "limit": 50}),
    ]

    for key, endpoint, params in calls:
        try:
            result[key] = api_get(FUTURES, endpoint, params)
        except Exception:
            pass

    return result


def demo_data():
    rng = np.random.default_rng(42)
    now = pd.Timestamp.now(tz="UTC").floor("min")
    times = pd.date_range(end=now, periods=750, freq="1min")

    close = 75000 + np.cumsum(rng.normal(0, 40, len(times)))
    open_price = np.r_[close[0], close[:-1]]
    high = np.maximum(open_price, close) + rng.uniform(3, 25, len(close))
    low = np.minimum(open_price, close) - rng.uniform(3, 25, len(close))
    volume = rng.lognormal(9, 0.45, len(close))

    return pd.DataFrame(
        {
            "time": times,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": close * volume,
            "trades": np.zeros(len(close), dtype=int),
        }
    )


# ============================================================
# MISSING-FUNCTION FIX
# ============================================================

def resample_candles(df, rule):
    """Safely turn 1-minute candles into larger candles."""
    if df is None or df.empty:
        return pd.DataFrame()

    x = df.copy()
    x["time"] = pd.to_datetime(x["time"], utc=True)
    x = x.set_index("time")

    out = x.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "quote_volume": "sum",
            "trades": "sum",
        }
    )

    return (
        out.dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )


def trade_bars(trades, seconds):
    if trades is None or trades.empty:
        return pd.DataFrame()

    x = trades.copy()
    x["sell_volume"] = np.where(
        x["buyer_maker"], x["quantity"], 0.0
    )
    x["buy_volume"] = np.where(
        ~x["buyer_maker"], x["quantity"], 0.0
    )

    x = x.set_index("time")

    bars = x["price"].resample(f"{seconds}s").ohlc()
    bars["volume"] = x["quantity"].resample(f"{seconds}s").sum()
    bars["buy_volume"] = x["buy_volume"].resample(f"{seconds}s").sum()
    bars["sell_volume"] = x["sell_volume"].resample(f"{seconds}s").sum()
    bars["trades"] = x["quantity"].resample(f"{seconds}s").count()

    bars = bars.dropna(subset=["open", "high", "low", "close"])

    bars["buy_pressure"] = np.where(
        bars["volume"] > 0,
        bars["buy_volume"] / bars["volume"] * 100,
        50,
    )

    return bars.reset_index()


# ============================================================
# INDICATORS
# ============================================================

def ema(s, span):
    return s.ewm(span=span, adjust=False).mean()


def rsi(s, period=14):
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(50)


def atr(df, period=14):
    prev = df["close"].shift(1)

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev).abs(),
            (df["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


# ============================================================
# SPECIALIST AIs
# ============================================================

def specialist_engine(candles, pressure=50.0, futures=None):
    c = candles.copy().reset_index(drop=True)
    close = c["close"]

    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)

    r = rsi(close, 14)
    a = atr(c, 14)

    macd = ema(close, 12) - ema(close, 26)
    macd_signal = ema(macd, 9)

    roc5 = close.pct_change(5) * 100

    vol_avg = c["volume"].rolling(20).mean()
    avg = vol_avg.iloc[-1]

    volume_ratio = (
        float(c["volume"].iloc[-1] / avg)
        if pd.notna(avg) and avg > 0
        else 1.0
    )

    current_atr = float(a.iloc[-1])
    last = float(close.iloc[-1])

    if not np.isfinite(current_atr) or current_atr <= 0:
        current_atr = last * 0.001

    def clip(v):
        return float(np.clip(v, 5, 95))

    trend_strength = (e9.iloc[-1] - e21.iloc[-1]) / current_atr
    trend = clip(50 + 35 * np.tanh(trend_strength * 2))

    r_component = float(r.iloc[-1] - 50)
    roc_component = (
        float(roc5.iloc[-1])
        if pd.notna(roc5.iloc[-1])
        else 0
    )

    macd_component = float(
        macd.iloc[-1] - macd_signal.iloc[-1]
    )

    macd_scale = max(
        abs(float(macd.iloc[-1])),
        current_atr * 0.05,
        1e-9,
    )

    momentum = clip(
        50
        + 22 * np.tanh(r_component / 12)
        + 18 * np.tanh(roc_component / 0.25)
        + 10 * np.tanh(macd_component / macd_scale)
    )

    volume = clip(
        50
        + (pressure - 50) * 0.8
        + 10 * np.tanh(volume_ratio - 1)
    )

    candle_range = max(
        float(c["high"].iloc[-1] - c["low"].iloc[-1]),
        1e-9,
    )

    body = (
        float(c["close"].iloc[-1] - c["open"].iloc[-1])
        / candle_range
    )

    one_return = (
        float(
            (close.iloc[-1] - close.iloc[-2])
            / close.iloc[-2]
            * 100
        )
        if len(c) > 1
        else 0
    )

    pattern = clip(
        50
        + 25 * np.tanh(one_return / 0.12)
        + 12 * np.tanh(body * 2)
    )

    recent_high = float(c["high"].tail(60).max())
    recent_low = float(c["low"].tail(60).min())
    midpoint = (recent_high + recent_low) / 2

    sr = clip(
        50
        + 22
        * np.tanh(
            (last - midpoint)
            / max(current_atr * 3, 1e-9)
        )
    )

    atr_pct = current_atr / last * 100

    volatility = clip(
        55
        + 12 * np.tanh(volume_ratio - 1)
        - 8 * np.tanh((atr_pct - 0.12) * 3)
    )

    regime_strength = (
        (e9.iloc[-1] - e50.iloc[-1])
        / current_atr
    )

    regime = clip(
        50 + 30 * np.tanh(regime_strength)
    )

    whale = clip(
        50 + (pressure - 50) * 0.65
    )

    # --------------------------------------------------------
    # Real futures depth imbalance when available
    # --------------------------------------------------------

    liquidity = 50.0
    liquidity_note = "Spot aggressor proxy"

    if futures and futures.get("depth"):
        try:
            depth = futures["depth"]
            bids = sum(float(x[1]) for x in depth.get("bids", []))
            asks = sum(float(x[1]) for x in depth.get("asks", []))
            total = bids + asks

            if total > 0:
                imbalance = bids / total * 100
                liquidity = clip(50 + (imbalance - 50) * 1.2)
                liquidity_note = (
                    f"Futures depth imbalance {imbalance:.1f}% bids"
                )
        except Exception:
            pass

    # --------------------------------------------------------
    # Derivatives
    # --------------------------------------------------------

    derivatives = 50 + roc_component * 8
    derivatives_note = "Price proxy — derivatives unavailable"

    if futures:
        funding = futures.get("funding")

        if funding:
            fr = float(
                funding.get("lastFundingRate", 0)
            )

            derivatives += np.clip(
                -fr * 100000,
                -12,
                12,
            )

            derivatives_note = (
                f"Funding {fr * 100:.4f}%"
            )

            if futures.get("oi"):
                derivatives_note += " • OI live"

    derivatives = clip(derivatives)

    # --------------------------------------------------------
    # Event
    # --------------------------------------------------------

    event = 50.0

    # --------------------------------------------------------
    # Historical analog
    # --------------------------------------------------------

    historical = 50.0
    historical_note = "Not enough analog history"

    if len(c) >= 140:
        x = c.copy()

        x["rsi"] = rsi(x["close"], 14)
        x["roc5"] = x["close"].pct_change(5) * 100
        x["volume_ratio"] = (
            x["volume"] /
            x["volume"].rolling(20).mean()
        )
        x["atr_pct"] = (
            atr(x, 14) /
            x["close"] *
            100
        )

        target = (
            x["close"].shift(-HORIZON)
            / x["close"]
            - 1
        )

        cols = [
            "rsi",
            "roc5",
            "volume_ratio",
            "atr_pct",
        ]

        current = x.iloc[-1]
        candidates = x.iloc[:-HORIZON]

        distances = []

        for idx, row in candidates.iterrows():
            future_return = target.loc[idx]

            if not np.isfinite(future_return):
                continue

            distance = 0.0

            for col in cols:
                value = row[col]
                current_value = current[col]

                scale = float(
                    x[col]
                    .iloc[:-HORIZON]
                    .std()
                )

                if (
                    pd.notna(value)
                    and pd.notna(current_value)
                    and scale > 1e-9
                ):
                    distance += (
                        (
                            float(value)
                            - float(current_value)
                        )
                        / scale
                    ) ** 2

            distances.append(
                (distance, float(future_return))
            )

        distances.sort(key=lambda z: z[0])
        nearest = distances[:30]

        if len(nearest) >= 10:
            probability = float(
                np.mean(
                    [
                        future > 0
                        for _, future in nearest
                    ]
                )
            )

            historical = 45 + 55 * probability
            historical_note = (
                f"{len(nearest)} nearest analogs • "
                f"next {HORIZON}m outcomes"
            )

    scores = {
        "Trend AI": trend,
        "Momentum AI": momentum,
        "Volume AI": volume,
        "Pattern AI": pattern,
        "S/R AI": sr,
        "Volatility AI": volatility,
        "Regime AI": regime,
        "Whale AI": whale,
        "Liquidity AI": liquidity,
        "Derivatives AI": derivatives,
        "Event AI": event,
        "Historical AI": clip(historical),
    }

    evidence = {
        "Trend AI": (
            f"EMA9 {e9.iloc[-1]:,.0f} vs "
            f"EMA21 {e21.iloc[-1]:,.0f}"
        ),
        "Momentum AI": (
            f"RSI {r.iloc[-1]:.1f} • "
            f"ROC5 {roc_component:+.3f}%"
        ),
        "Volume AI": (
            f"Volume {volume_ratio:.2f}x avg • "
            f"pressure {pressure:.1f}%"
        ),
        "Pattern AI": (
            f"Body {body:+.2f} of range • "
            f"return {one_return:+.3f}%"
        ),
        "S/R AI": (
            f"Support ${recent_low:,.0f} • "
            f"Resistance ${recent_high:,.0f}"
        ),
        "Volatility AI": (
            f"ATR ${current_atr:,.0f} • "
            f"{atr_pct:.3f}% of price"
        ),
        "Regime AI": (
            "TRENDING" if regime >= 60
            else "BEARISH TREND" if regime <= 40
            else "CHOP / MIXED"
        ),
        "Whale AI": (
            f"Large-trade proxy • "
            f"aggressor pressure {pressure:.1f}%"
        ),
        "Liquidity AI": liquidity_note,
        "Derivatives AI": derivatives_note,
        "Event AI": (
            "Neutral — verified event feed not connected"
        ),
        "Historical AI": historical_note,
    }

    features = {
        "ema9": float(e9.iloc[-1]),
        "ema21": float(e21.iloc[-1]),
        "ema50": float(e50.iloc[-1]),
        "rsi": float(r.iloc[-1]),
        "atr": float(current_atr),
        "volume_ratio": float(volume_ratio),
        "recent_high": recent_high,
        "recent_low": recent_low,
    }

    return scores, features, evidence


# ============================================================
# MASTER AI
# ============================================================

def master(scores):
    weights = {
        name: 1.0
        for name in scores
    }

    regime = scores["Regime AI"]

    if regime >= 60:
        for name in [
            "Trend AI",
            "Momentum AI",
            "Volume AI",
            "Regime AI",
        ]:
            weights[name] = 1.35

    elif regime <= 40:
        weights["Trend AI"] = 0.75
        weights["Momentum AI"] = 0.75
        weights["Volatility AI"] = 1.25

    weights["Whale AI"] = 1.05

    weighted = (
        sum(
            scores[n] * weights[n]
            for n in scores
        )
        / sum(weights.values())
    )

    disagreement = float(
        np.std(
            np.array(
                list(scores.values()),
                dtype=float,
            )
        )
    )

    confidence = float(
        np.clip(
            50
            + abs(weighted - 50) * 1.55
            - disagreement * 0.22,
            50,
            95,
        )
    )

    if weighted >= 58 and confidence >= 60:
        signal = "SCALP UP"
    elif weighted <= 42 and confidence >= 60:
        signal = "SCALP DOWN"
    else:
        signal = "WAIT"

    contributions = {}

    for name, value in scores.items():
        contributions[name] = {
            "score": float(value),
            "weight": float(weights[name]),
            "contribution": float(
                (value - 50)
                * weights[name]
            ),
        }

    return (
        signal,
        confidence,
        float(weighted),
        disagreement,
        contributions,
    )


# ============================================================
# FORECAST
# ============================================================

def forecast(candles, signal, confidence, features):
    price = float(candles["close"].iloc[-1])
    current_atr = max(
        float(features["atr"]),
        price * 0.0005,
    )

    direction = (
        1 if signal == "SCALP UP"
        else -1 if signal == "SCALP DOWN"
        else 0
    )

    strength = max(
        0.15,
        (confidence - 50) / 45,
    )

    expected = (
        price
        + direction
        * current_atr
        * (0.8 + 1.4 * strength)
    )

    start = (
        candles["time"].iloc[-1]
        + pd.Timedelta(minutes=1)
    )

    future = pd.date_range(
        start=start,
        periods=HORIZON,
        freq="1min",
    )

    path = np.linspace(
        price,
        expected,
        HORIZON,
    )

    uncertainty = (
        current_atr
        * (0.45 + 0.04 * np.arange(HORIZON))
    )

    return (
        future,
        path,
        path + uncertainty,
        path - uncertainty,
        expected,
    )


# ============================================================
# JOURNAL
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
    )
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = db()

    conn.execute(
        """
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
        """
    )

    conn.commit()
    conn.close()


def log_prediction(
    candle_time,
    price,
    signal,
    confidence,
    bullish,
    disagreement,
    expected,
    scores,
    evidence,
):
    candle_time = pd.Timestamp(candle_time)
    target = (
        candle_time
        + pd.Timedelta(minutes=HORIZON)
    )

    key = (
        f"{candle_time.isoformat()}|"
        f"{HORIZON}"
    )

    conn = db()

    conn.execute(
        """
        INSERT OR IGNORE INTO predictions
        (
            prediction_key,
            created_at,
            target_time,
            price,
            signal,
            confidence,
            bullish_score,
            disagreement,
            expected_price,
            specialist_json,
            evidence_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            key,
            candle_time.isoformat(),
            target.isoformat(),
            float(price),
            signal,
            float(confidence),
            float(bullish),
            float(disagreement),
            float(expected),
            json.dumps(scores),
            json.dumps(evidence),
        ),
    )

    conn.commit()
    conn.close()


def score_predictions(candles):
    if candles.empty:
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT id, target_time, price, signal
        FROM predictions
        WHERE actual_price IS NULL
        ORDER BY target_time
        LIMIT 1000
        """
    ).fetchall()

    for row_id, target_time, entry, signal in rows:
        target = pd.Timestamp(target_time)

        eligible = candles[
            candles["time"] >= target
        ]

        if eligible.empty:
            continue

        actual = float(
            eligible.iloc[0]["close"]
        )

        ret = (
            actual / float(entry) - 1
        ) * 100

        if signal == "SCALP UP":
            correct = int(ret > 0)
        elif signal == "SCALP DOWN":
            correct = int(ret < 0)
        else:
            correct = int(abs(ret) < 0.15)

        conn.execute(
            """
            UPDATE predictions
            SET actual_price=?,
                return_pct=?,
                correct=?,
                scored_at=?
            WHERE id=?
            """,
            (
                actual,
                ret,
                correct,
                datetime.now(
                    timezone.utc
                ).isoformat(),
                row_id,
            ),
        )

    conn.commit()
    conn.close()


def journal_stats():
    conn = db()

    df = pd.read_sql_query(
        "SELECT * FROM predictions ORDER BY id",
        conn,
    )

    conn.close()

    if df.empty:
        return df, {
            "count": 0,
            "scored": 0,
            "win_rate": None,
            "profit_factor": None,
            "drawdown": None,
            "brier": None,
        }

    scored = df[
        df["actual_price"].notna()
    ].copy()

    if scored.empty:
        return df, {
            "count": len(df),
            "scored": 0,
            "win_rate": None,
            "profit_factor": None,
            "drawdown": None,
            "brier": None,
        }

    win_rate = float(
        scored["correct"].mean() * 100
    )

    strategy = np.where(
        scored["signal"].eq("SCALP UP"),
        scored["return_pct"],
        np.where(
            scored["signal"].eq("SCALP DOWN"),
            -scored["return_pct"],
            0,
        ),
    )

    strategy = pd.Series(
        strategy,
        index=scored.index,
    )

    profit = float(
        strategy[strategy > 0].sum()
    )

    loss = float(
        -strategy[strategy < 0].sum()
    )

    pf = (
        profit / loss
        if loss > 0
        else None
    )

    equity = strategy.cumsum()
    dd = equity - equity.cummax()

    max_dd = float(
        abs(dd.min())
    ) if not dd.empty else 0

    probability = (
        scored["bullish_score"] / 100
    )

    outcome = (
        scored["return_pct"] > 0
    ).astype(float)

    brier = float(
        np.mean(
            (probability - outcome) ** 2
        )
    )

    return df, {
        "count": len(df),
        "scored": len(scored),
        "win_rate": win_rate,
        "profit_factor": pf,
        "drawdown": max_dd,
        "brier": brier,
    }


# ============================================================
# BACKTEST
# ============================================================

def historical_pressure(df, i):
    row = df.iloc[i]

    rng = max(
        float(row["high"] - row["low"]),
        1e-9,
    )

    body = (
        float(row["close"] - row["open"])
        / rng
    )

    avg_volume = max(
        float(
            df["volume"]
            .iloc[max(0, i - 19):i + 1]
            .mean()
        ),
        1e-9,
    )

    ratio = (
        float(row["volume"])
        / avg_volume
    )

    return float(
        np.clip(
            50 + body * 22
            + (ratio - 1) * 8,
            5,
            95,
        )
    )


@st.cache_data(ttl=300, show_spinner=False)
def backtest(candles, step=5):
    df = candles.copy().reset_index(drop=True)

    results = []

    start = 80
    end = len(df) - HORIZON - 1

    for i in range(
        start,
        end,
        step,
    ):
        history = df.iloc[
            :i + 1
        ].copy()

        pressure = historical_pressure(
            df,
            i,
        )

        scores, features, evidence = (
            specialist_engine(
                history,
                pressure,
                None,
            )
        )

        (
            signal,
            confidence,
            bullish,
            disagreement,
            _,
        ) = master(scores)

        entry = float(
            df["close"].iloc[i]
        )

        exit_price = float(
            df["close"].iloc[
                i + HORIZON
            ]
        )

        ret = (
            exit_price / entry - 1
        ) * 100

        if signal == "SCALP UP":
            strategy_return = ret
            correct = ret > 0
        elif signal == "SCALP DOWN":
            strategy_return = -ret
            correct = ret < 0
        else:
            strategy_return = 0
            correct = abs(ret) < 0.15

        regime = (
            "UP"
            if scores["Regime AI"] >= 60
            else "DOWN"
            if scores["Regime AI"] <= 40
            else "MIXED"
        )

        results.append(
            {
                "time": df["time"].iloc[i],
                "signal": signal,
                "confidence": confidence,
                "bullish_score": bullish,
                "disagreement": disagreement,
                "return_pct": ret,
                "strategy_return_pct": strategy_return,
                "correct": int(correct),
                "regime": regime,
            }
        )

    result = pd.DataFrame(results)

    if result.empty:
        return result, {}

    non_wait = result[
        result["signal"] != "WAIT"
    ]

    gross_profit = float(
        result.loc[
            result["strategy_return_pct"] > 0,
            "strategy_return_pct",
        ].sum()
    )

    gross_loss = float(
        -result.loc[
            result["strategy_return_pct"] < 0,
            "strategy_return_pct",
        ].sum()
    )

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    equity = result[
        "strategy_return_pct"
    ].cumsum()

    dd = equity - equity.cummax()

    brier = float(
        np.mean(
            (
                result["bullish_score"] / 100
                - (
                    result["return_pct"] > 0
                ).astype(float)
            ) ** 2
        )
    )

    metrics = {
        "samples": len(result),
        "trades": len(non_wait),
        "win_rate": float(
            result["correct"].mean() * 100
        ),
        "avg_return": float(
            result[
                "strategy_return_pct"
            ].mean()
        ),
        "profit_factor": pf,
        "max_drawdown": float(
            abs(dd.min())
        ),
        "brier": brier,
    }

    return result, metrics


# ============================================================
# ERROR DISPLAY
# ============================================================

def show_error(title, error):
    st.error(title)

    st.code(
        traceback.format_exc(),
        language="text",
    )

    st.caption(
        "Copy the entire traceback above and send it to me. "
        "Do not change anything else."
    )


# ============================================================
# INITIALIZE
# ============================================================

init_db()

if "streaming" not in st.session_state:
    st.session_state.streaming = True

if "refresh" not in st.session_state:
    st.session_state.refresh = 2.0


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("₿ Command Center")

    timeframe = st.selectbox(
        "Chart timeframe",
        [
            "1 second",
            "3 seconds",
            "5 seconds",
            "1 minute",
            "3 minutes",
            "5 minutes",
            "15 minutes",
        ],
        index=6,
    )

    refresh = st.select_slider(
        "Auto refresh",
        options=[
            1.0,
            2.0,
            5.0,
            10.0,
            30.0,
        ],
        value=st.session_state.refresh,
        format_func=lambda x: (
            "1 second"
            if x == 1
            else f"{int(x)} seconds"
        ),
    )

    st.session_state.refresh = refresh

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "▶ Start",
            use_container_width=True,
            disabled=st.session_state.streaming,
        ):
            st.session_state.streaming = True
            st.rerun()

    with col2:
        if st.button(
            "⏸ Stop",
            use_container_width=True,
            disabled=not st.session_state.streaming,
        ):
            st.session_state.streaming = False
            st.rerun()

    if st.button(
        "🔄 Full Refresh",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    st.info(
        "PAPER / RESEARCH ONLY\n\n"
        "No API keys.\n"
        "No order endpoints.\n"
        "No real trading."
    )


# ============================================================
# DASHBOARD
# ============================================================

run_every = (
    f"{refresh}s"
    if st.session_state.streaming
    else None
)


@st.fragment(run_every=run_every)
def dashboard():

    try:
        started = datetime.now(timezone.utc)

        # ----------------------------------------------------
        # LIVE DATA
        # ----------------------------------------------------

        live = True
        data_error = ""

        try:
            candles = get_candles()
            trades = get_trades()
            price = get_price()
            futures = get_futures()

        except Exception as e:
            live = False
            data_error = (
                f"{type(e).__name__}: {e}"
            )

            candles = demo_data()
            trades = pd.DataFrame()
            price = float(
                candles["close"].iloc[-1]
            )

            futures = {
                "funding": None,
                "oi": None,
                "depth": None,
            }

        # ----------------------------------------------------
        # TRADE PRESSURE
        # ----------------------------------------------------

        if not trades.empty:
            total = float(
                trades["quantity"].sum()
            )

            buys = float(
                trades.loc[
                    ~trades["buyer_maker"],
                    "quantity",
                ].sum()
            )

            pressure = (
                buys / total * 100
                if total > 0
                else 50
            )

            trade_count = len(trades)

        else:
            pressure = 50
            trade_count = 0

        # ----------------------------------------------------
        # SPECIALISTS
        # ----------------------------------------------------

        scores, features, evidence = (
            specialist_engine(
                candles,
                pressure,
                futures,
            )
        )

        (
            signal,
            confidence,
            bullish,
            disagreement,
            contributions,
        ) = master(scores)

        (
            future,
            path,
            upper,
            lower,
            expected,
        ) = forecast(
            candles,
            signal,
            confidence,
            features,
        )

        # ----------------------------------------------------
        # JOURNAL
        # ----------------------------------------------------

        candle_time = pd.Timestamp(
            candles["time"].iloc[-1]
        )

        log_prediction(
            candle_time,
            float(
                candles["close"].iloc[-1]
            ),
            signal,
            confidence,
            bullish,
            disagreement,
            expected,
            scores,
            evidence,
        )

        score_predictions(candles)

        journal, stats = journal_stats()

        elapsed_ms = (
            datetime.now(timezone.utc)
            - started
        ).total_seconds() * 1000

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        st.title(
            "₿ BTC AI Command Center"
        )

        st.caption(
            "Live BTC market engine • "
            "12 Specialist AIs • "
            "15-minute prediction horizon • "
            "Journal • Backtest • PAPER ONLY"
        )

        if live:
            st.success(
                "🟢 BINANCE LIVE DATA • "
                + datetime.now(
                    timezone.utc
                ).strftime(
                    "%H:%M:%S UTC"
                )
            )
        else:
            st.warning(
                "🟡 DEMO FALLBACK — Binance "
                "connection failed"
            )

            st.code(
                data_error,
                language="text",
            )

        # ----------------------------------------------------
        # MASTER
        # ----------------------------------------------------

        st.subheader(
            "🧠 Master Prediction"
        )

        text = (
            f"{signal} • "
            f"{confidence:.1f}% confidence"
        )

        if signal == "SCALP UP":
            st.success(
                "🟢 " + text
            )
        elif signal == "SCALP DOWN":
            st.error(
                "🔴 " + text
            )
        else:
            st.warning(
                "🟡 " + text
            )

        cols = st.columns(5)

        with cols[0]:
            st.metric(
                "BTC Price",
                f"${price:,.2f}",
            )

        with cols[1]:
            st.metric(
                "Master Score",
                f"{bullish:.1f}%",
            )

        with cols[2]:
            st.metric(
                "Trade Pressure",
                f"{pressure:.1f}%",
            )

        with cols[3]:
            st.metric(
                "AI Disagreement",
                f"{disagreement:.1f}",
            )

        with cols[4]:
            st.metric(
                "Feed Time",
                f"{elapsed_ms:.0f} ms",
            )

        st.caption(
            "Specialist percentages are engineered "
            "signal scores, not guaranteed probabilities."
        )

        # ----------------------------------------------------
        # TRADE PLAN
        # ----------------------------------------------------

        st.subheader(
            "Paper Trade Plan"
        )

        atr_value = features["atr"]

        entry_low = (
            price - atr_value * 0.20
        )

        entry_high = (
            price + atr_value * 0.20
        )

        if signal == "SCALP UP":
            target = (
                price + atr_value * 1.4
            )
            invalidation = (
                price - atr_value * 0.8
            )

        elif signal == "SCALP DOWN":
            target = (
                price - atr_value * 1.4
            )
            invalidation = (
                price + atr_value * 0.8
            )

        else:
            target = None
            invalidation = None

        cols = st.columns(4)

        with cols[0]:
            st.metric(
                "Entry Zone",
                f"${entry_low:,.0f}–"
                f"${entry_high:,.0f}",
            )

        with cols[1]:
            st.metric(
                "Target",
                f"${target:,.0f}"
                if target
                else "—",
            )

        with cols[2]:
            st.metric(
                "Invalidation",
                f"${invalidation:,.0f}"
                if invalidation
                else "—",
            )

        with cols[3]:
            st.metric(
                "1m ATR",
                f"${atr_value:,.2f}",
            )

        # ----------------------------------------------------
        # SHORT TERM
        # ----------------------------------------------------

        st.subheader(
            "⚡ Short-Term Market Engine"
        )

        bars1 = (
            trade_bars(trades, 1)
            if live
            else pd.DataFrame()
        )

        bars3 = (
            trade_bars(trades, 3)
            if live
            else pd.DataFrame()
        )

        bars5 = (
            trade_bars(trades, 5)
            if live
            else pd.DataFrame()
        )

        cols = st.columns(5)

        with cols[0]:
            st.metric(
                "Recent Trades",
                f"{trade_count:,}",
            )

        with cols[1]:
            st.metric(
                "Buy Pressure",
                f"{pressure:.1f}%",
            )

        with cols[2]:
            st.metric(
                "Sell Pressure",
                f"{100-pressure:.1f}%",
            )

        with cols[3]:
            st.metric(
                "1s / 3s / 5s",
                "ACTIVE"
                if not bars1.empty
                else "WAITING",
            )

        with cols[4]:
            st.metric(
                "Feed",
                "LIVE"
                if live
                else "DEMO",
            )

        # ----------------------------------------------------
        # CHART
        # ----------------------------------------------------

        if timeframe == "1 second":
            chart_df = bars1.tail(180)

        elif timeframe == "3 seconds":
            chart_df = bars3.tail(180)

        elif timeframe == "5 seconds":
            chart_df = bars5.tail(180)

        elif timeframe == "1 minute":
            chart_df = candles.tail(240)

        elif timeframe == "3 minutes":
            chart_df = resample_candles(
                candles,
                "3min",
            ).tail(160)

        elif timeframe == "5 minutes":
            chart_df = resample_candles(
                candles,
                "5min",
            ).tail(120)

        else:
            chart_df = resample_candles(
                candles,
                "15min",
            ).tail(80)

        st.subheader(
            f"BTC Market Chart — {timeframe}"
        )

        if chart_df.empty:
            st.info(
                "Waiting for chart data."
            )
        else:
            fig = go.Figure()

            fig.add_trace(
                go.Candlestick(
                    x=chart_df["time"],
                    open=chart_df["open"],
                    high=chart_df["high"],
                    low=chart_df["low"],
                    close=chart_df["close"],
                    name="BTC",
                )
            )

            fig.update_layout(
                height=450,
                margin=dict(
                    l=10,
                    r=10,
                    t=10,
                    b=10,
                ),
                xaxis_rangeslider_visible=False,
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

        # ----------------------------------------------------
        # FORECAST
        # ----------------------------------------------------

        st.subheader(
            "🔮 15-Minute AI Prediction"
        )

        recent = candles.tail(120)

        fig = go.Figure()

        fig.add_trace(
            go.Candlestick(
                x=recent["time"],
                open=recent["open"],
                high=recent["high"],
                low=recent["low"],
                close=recent["close"],
                name="BTC",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=future,
                y=path,
                mode="lines",
                name="AI forecast",
                line=dict(width=3),
            )
        )

        fig.add_trace(
            go.Scatter(
                x=list(future)
                + list(future[::-1]),
                y=list(upper)
                + list(lower[::-1]),
                fill="toself",
                line=dict(width=0),
                name="Uncertainty",
                opacity=0.18,
            )
        )

        fig.update_layout(
            height=450,
            margin=dict(
                l=10,
                r=10,
                t=10,
                b=10,
            ),
            xaxis_rangeslider_visible=False,
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
        )

        # ----------------------------------------------------
        # DECISION EVIDENCE
        # ----------------------------------------------------

        st.subheader(
            "🔍 Master Decision Evidence"
        )

        st.caption(
            "Auditable signal summary. "
            "This shows measurable factors and "
            "weighted influence rather than private "
            "chain-of-thought."
        )

        rows = []

        for name in SPECIALISTS:
            item = contributions[name]

            rows.append(
                {
                    "Specialist": name,
                    "Score": round(
                        item["score"],
                        1,
                    ),
                    "Weight": round(
                        item["weight"],
                        2,
                    ),
                    "Contribution": round(
                        item["contribution"],
                        2,
                    ),
                    "Evidence": evidence[name],
                }
            )

        evidence_df = pd.DataFrame(rows)

        st.dataframe(
            evidence_df,
            use_container_width=True,
            hide_index=True,
        )

        # ----------------------------------------------------
        # SPECIALIST GRID
        # ----------------------------------------------------

        st.subheader(
            "🤖 Specialist AI Network"
        )

        grid = st.columns(3)

        for i, name in enumerate(
            SPECIALISTS
        ):
            value = scores[name]

            direction = (
                "UP"
                if value >= 55
                else "DOWN"
                if value <= 45
                else "MIXED"
            )

            with grid[i % 3]:
                st.metric(
                    name,
                    f"{direction} • "
                    f"{value:.1f}%",
                    DESCRIPTIONS[name],
                )

        # ----------------------------------------------------
        # WHALE
        # ----------------------------------------------------

        st.subheader(
            "🐋 Whale AI"
        )

        st.metric(
            "Whale Pressure",
            f"{scores['Whale AI']:.1f}%",
        )

        st.progress(
            scores["Whale AI"] / 100
        )

        st.caption(
            "Whale AI currently uses large-trade/"
            "aggressor pressure as a proxy. It does "
            "not see blockchain wallet transfers."
        )

        # ----------------------------------------------------
        # FEATURES
        # ----------------------------------------------------

        st.subheader(
            "📊 Live Feature Snapshot"
        )

        cols = st.columns(6)

        with cols[0]:
            st.metric(
                "RSI",
                f"{features['rsi']:.1f}",
            )

        with cols[1]:
            st.metric(
                "EMA 9",
                f"${features['ema9']:,.0f}",
            )

        with cols[2]:
            st.metric(
                "EMA 21",
                f"${features['ema21']:,.0f}",
            )

        with cols[3]:
            st.metric(
                "EMA 50",
                f"${features['ema50']:,.0f}",
            )

        with cols[4]:
            st.metric(
                "Volume Ratio",
                f"{features['volume_ratio']:.2f}x",
            )

        with cols[5]:
            st.metric(
                "ATR",
                f"${features['atr']:,.0f}",
            )

        # ----------------------------------------------------
        # JOURNAL
        # ----------------------------------------------------

        st.subheader(
            "📓 Prediction Journal"
        )

        cols = st.columns(4)

        with cols[0]:
            st.metric(
                "Logged",
                f"{stats['count']:,}",
            )

        with cols[1]:
            st.metric(
                "Scored",
                f"{stats['scored']:,}",
            )

        with cols[2]:
            st.metric(
                "Win Rate",
                (
                    f"{stats['win_rate']:.1f}%"
                    if stats["win_rate"]
                    is not None
                    else "—"
                ),
            )

        with cols[3]:
            st.metric(
                "Brier",
                (
                    f"{stats['brier']:.3f}"
                    if stats["brier"]
                    is not None
                    else "—"
                ),
            )

        if not journal.empty:
            show = journal.tail(30).copy()

            columns = [
                "created_at",
                "target_time",
                "price",
                "signal",
                "confidence",
                "bullish_score",
                "actual_price",
                "return_pct",
                "correct",
            ]

            columns = [
                c for c in columns
                if c in show.columns
            ]

            st.dataframe(
                show[
                    columns
                ].sort_values(
                    "created_at",
                    ascending=False,
                ),
                use_container_width=True,
                hide_index=True,
            )

        # ----------------------------------------------------
        # BACKTEST
        # ----------------------------------------------------

        st.subheader(
            "📈 Walk-Forward Backtest"
        )

        with st.spinner(
            "Running walk-forward test..."
        ):
            bt_df, bt = backtest(
                candles,
                step=5,
            )

        if bt:
            cols = st.columns(5)

            with cols[0]:
                st.metric(
                    "Samples",
                    f"{bt['samples']:,}",
                )

            with cols[1]:
                st.metric(
                    "Win Rate",
                    f"{bt['win_rate']:.1f}%",
                )

            with cols[2]:
                st.metric(
                    "Profit Factor",
                    (
                        f"{bt['profit_factor']:.2f}"
                        if bt["profit_factor"]
                        is not None
                        else "—"
                    ),
                )

            with cols[3]:
                st.metric(
                    "Max Drawdown",
                    f"{bt['max_drawdown']:.2f}%",
                )

            with cols[4]:
                st.metric(
                    "Brier",
                    f"{bt['brier']:.3f}",
                )

            equity = (
                bt_df[
                    "strategy_return_pct"
                ].cumsum()
            )

            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    x=bt_df["time"],
                    y=equity,
                    mode="lines",
                    name="Paper equity",
                )
            )

            fig.update_layout(
                height=320,
                title=(
                    "Walk-Forward "
                    "Cumulative Return"
                ),
                yaxis_title="Return (%)",
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
            )

            regime = (
                bt_df.groupby("regime")
                .agg(
                    Samples=("regime", "size"),
                    Win_Rate=("correct", "mean"),
                    Avg_Return=(
                        "strategy_return_pct",
                        "mean",
                    ),
                )
                .reset_index()
            )

            regime["Win_Rate"] *= 100

            st.dataframe(
                regime.round(3),
                use_container_width=True,
                hide_index=True,
            )

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        st.subheader(
            "🟢 System Status"
        )

        cols = st.columns(5)

        with cols[0]:
            st.success(
                "BTC DATA — LIVE"
                if live
                else "BTC DATA — DEMO"
            )

        with cols[1]:
            st.success(
                "AUTO REFRESH — ON"
                if st.session_state.streaming
                else "AUTO REFRESH — OFF"
            )

        with cols[2]:
            st.success(
                "12 SPECIALISTS — ACTIVE"
            )

        with cols[3]:
            st.success(
                "JOURNAL — ACTIVE"
            )

        with cols[4]:
            st.info(
                "TRADING — PAPER ONLY"
            )

        st.caption(
            "Last update: "
            + datetime.now(
                timezone.utc
            ).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            + f" • refresh {refresh:g}s"
        )

    except Exception as error:
        # IMPORTANT:
        # If anything breaks, show the full traceback
        # instead of giving a generic Streamlit error.
        show_error(
            "🚨 BTC AI Command Center encountered "
            "a runtime error.",
            error,
        )


# ============================================================
# RENDER
# ============================================================

dashboard()


# ============================================================
# BUILD NOTES
# ============================================================

with st.expander(
    "Build Notes / Troubleshooting"
):
    st.markdown(
        """
### This build includes

- Live Binance BTC spot data
- Recent aggregate trades
- 1s / 3s / 5s trade bars
- Futures funding
- Futures open interest
- Futures depth imbalance
- 12 specialist signal engines
- Master weighted decision
- Auditable decision evidence
- 15-minute forecast
- SQLite prediction journal
- Automatic journal scoring
- Walk-forward backtesting
- Win rate
- Profit factor
- Maximum drawdown
- Brier calibration score
- Automatic Streamlit fragment refresh
- Full runtime traceback display

### If the app crashes

1. Look for the red error section.
2. Find **Traceback (most recent call last)**.
3. Copy the ENTIRE traceback.
4. Send it back to the developer/assistant.
5. Do not try to repair the code yourself.

### Safety

This application is paper/research only.
It contains no Binance API credentials and no
order-placement endpoints.
"""
    )
