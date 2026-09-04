# ================================================================
# BTC AI TRADING COMMAND CENTER v5
# ================================================================
# PAPER TRADING / RESEARCH ONLY
#
# NO REAL-MONEY ORDER EXECUTION
# NO EXCHANGE ORDER ENDPOINTS
# NO KALSHI ORDER EXECUTION
#
# Features:
#   - Binance live BTC spot candles
#   - Binance aggregate trades
#   - Binance futures funding / OI / depth
#   - Concurrent data collection for lower latency
#   - Explicit LIVE / DEGRADED / DEMO states
#   - 13 specialist AI engines
#   - Prediction-market signal via public Kalshi data
#   - Optional AGGR-compatible HTTP adapter
#   - Master decision engine
#   - Calibrated probability
#   - Disagreement penalty
#   - Paper broker
#   - Fees / spread / slippage
#   - Stop loss / take profit
#   - Daily-loss / drawdown protection
#   - Persistent SQLite prediction journal
#   - Prediction scoring
#   - Proper Brier score
#   - Walk-forward backtesting
#   - Performance metrics
#   - Controlled learner
#   - Versioned learner weights
#   - Diagnostics
#
# Streamlit Cloud compatible.
# ================================================================

import os
import json
import sqlite3
import threading
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ================================================================
# CONFIG
# ================================================================

st.set_page_config(
    page_title="BTC AI Trading Command Center",
    page_icon="₿",
    layout="wide",
)

APP_VERSION = "5.0-PAPER"
SYMBOL = "BTCUSDT"
HORIZON = 15

BINANCE_SPOT = "https://data-api.binance.vision"
BINANCE_FUTURES = "https://fapi.binance.com"

KALSHI_API = os.getenv(
    "KALSHI_API_BASE",
    "https://api.elections.kalshi.com/trade-api/v2",
)

AGGR_API_URL = os.getenv("AGGR_API_URL", "").strip()
AGGR_API_KEY = os.getenv("AGGR_API_KEY", "").strip()

DB_PATH = os.getenv(
    "BTC_AI_DB",
    "btc_ai_journal.sqlite3",
)

STARTING_BALANCE = float(
    os.getenv("PAPER_START_BALANCE", "10000")
)

DB_LOCK = threading.Lock()


SPECIALISTS = [
    "Trend AI",
    "Momentum AI",
    "Volume AI",
    "Pattern AI",
    "S/R AI",
    "Volatility AI",
    "Regime AI",
    "Whale AI",
    "Liquidity AI",
    "Derivatives AI",
    "Event AI",
    "Historical AI",
    "Prediction Market AI",
]


# ================================================================
# HTTP
# ================================================================

def http_json(
    base,
    endpoint="",
    params=None,
    timeout=5,
    headers=None,
):
    url = base.rstrip("/") + "/" + endpoint.lstrip("/")

    if params:
        url += "?" + urlencode(params)

    request_headers = {
        "Accept": "application/json",
        "User-Agent": "BTC-AI-Command-Center/5.0",
    }

    if headers:
        request_headers.update(headers)

    request = Request(
        url,
        headers=request_headers,
    )

    with urlopen(request, timeout=timeout) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def timed_call(function):
    started = datetime.now(timezone.utc)

    try:
        result = function()

        elapsed = (
            datetime.now(timezone.utc) - started
        ).total_seconds() * 1000

        return result, elapsed, None

    except Exception as exc:
        return (
            None,
            None,
            f"{type(exc).__name__}: {exc}",
        )


# ================================================================
# BINANCE DATA
# ================================================================

def fetch_candles(limit=750):

    data = http_json(
        BINANCE_SPOT,
        "/api/v3/klines",
        {
            "symbol": SYMBOL,
            "interval": "1m",
            "limit": min(limit, 1000),
        },
        timeout=5,
    )

    rows = []

    for x in data:

        rows.append(
            {
                "time": pd.to_datetime(
                    x[0],
                    unit="ms",
                    utc=True,
                ),
                "open": float(x[1]),
                "high": float(x[2]),
                "low": float(x[3]),
                "close": float(x[4]),
                "volume": float(x[5]),
                "quote_volume": float(x[7]),
                "trades": int(x[8]),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


def fetch_trades(limit=1000):

    data = http_json(
        BINANCE_SPOT,
        "/api/v3/aggTrades",
        {
            "symbol": SYMBOL,
            "limit": min(limit, 1000),
        },
        timeout=5,
    )

    rows = []

    for x in data:

        rows.append(
            {
                "time": pd.to_datetime(
                    x["T"],
                    unit="ms",
                    utc=True,
                ),
                "price": float(x["p"]),
                "quantity": float(x["q"]),
                "buyer_maker": bool(x["m"]),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


def fetch_price():

    data = http_json(
        BINANCE_SPOT,
        "/api/v3/ticker/price",
        {"symbol": SYMBOL},
        timeout=4,
    )

    return float(data["price"])


def fetch_funding():

    return http_json(
        BINANCE_FUTURES,
        "/fapi/v1/premiumIndex",
        {"symbol": SYMBOL},
        timeout=4,
    )


def fetch_open_interest():

    return http_json(
        BINANCE_FUTURES,
        "/fapi/v1/openInterest",
        {"symbol": SYMBOL},
        timeout=4,
    )


def fetch_depth():

    return http_json(
        BINANCE_FUTURES,
        "/fapi/v1/depth",
        {
            "symbol": SYMBOL,
            "limit": 50,
        },
        timeout=4,
    )


# ================================================================
# DEMO DATA
# ================================================================

def demo_data():

    rng = np.random.default_rng(42)

    now = (
        pd.Timestamp.now(tz="UTC")
        .floor("min")
    )

    times = pd.date_range(
        end=now,
        periods=750,
        freq="1min",
    )

    close = (
        75000
        + np.cumsum(
            rng.normal(
                0,
                40,
                len(times),
            )
        )
    )

    open_price = np.r_[
        close[0],
        close[:-1],
    ]

    high = (
        np.maximum(
            open_price,
            close,
        )
        + rng.uniform(
            3,
            25,
            len(close),
        )
    )

    low = (
        np.minimum(
            open_price,
            close,
        )
        - rng.uniform(
            3,
            25,
            len(close),
        )
    )

    volume = rng.lognormal(
        9,
        0.45,
        len(close),
    )

    return pd.DataFrame(
        {
            "time": times,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": close * volume,
            "trades": np.zeros(
                len(close),
                dtype=int,
            ),
        }
    )


# ================================================================
# MARKET DATA HUB
# ================================================================

def fetch_aggr():

    if not AGGR_API_URL:
        raise RuntimeError(
            "AGGR_API_URL is not configured."
        )

    headers = {}

    if AGGR_API_KEY:
        headers["Authorization"] = (
            f"Bearer {AGGR_API_KEY}"
        )

    return http_json(
        AGGR_API_URL,
        "",
        None,
        timeout=5,
        headers=headers,
    )


def fetch_kalshi():

    return http_json(
        KALSHI_API,
        "/markets",
        {
            "limit": 100,
            "status": "open",
        },
        timeout=5,
    )


def collect_market_data():

    jobs = {
        "candles": fetch_candles,
        "trades": fetch_trades,
        "price": fetch_price,
        "funding": fetch_funding,
        "oi": fetch_open_interest,
        "depth": fetch_depth,
    }

    started = datetime.now(timezone.utc)

    results = {}

    with ThreadPoolExecutor(
        max_workers=6
    ) as executor:

        futures = {
            executor.submit(
                fn
            ): name

            for name, fn in jobs.items()
        }

        for future in as_completed(
            futures
        ):

            name = futures[future]

            try:
                results[name] = (
                    future.result()
                )

            except Exception:
                results[name] = None

    elapsed = (
        datetime.now(timezone.utc)
        - started
    ).total_seconds() * 1000

    errors = {}

    for name in jobs:

        if results.get(name) is None:
            errors[name] = "unavailable"

    if results.get("candles") is None:

        results["candles"] = demo_data()
        results["mode"] = "DEMO"

    elif errors:

        results["mode"] = "DEGRADED"

    else:

        results["mode"] = "LIVE"

    kalshi, klat, kerr = timed_call(
        fetch_kalshi
    )

    aggr, alat, aerr = timed_call(
        fetch_aggr
    )

    results["kalshi"] = kalshi
    results["kalshi_latency"] = klat
    results["kalshi_error"] = kerr

    results["aggr"] = aggr
    results["aggr_latency"] = alat
    results["aggr_error"] = aerr

    results["errors"] = errors
    results["latency_ms"] = elapsed

    return results


# ================================================================
# INDICATORS
# ================================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False,
    ).mean()


def rsi(series, period=14):

    delta = series.diff()

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

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan,
        )
    )

    return (
        100 - 100 / (1 + rs)
    ).fillna(50)


def atr(df, period=14):

    previous = df["close"].shift(1)

    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (
                df["high"]
                - previous
            ).abs(),
            (
                df["low"]
                - previous
            ).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


# ================================================================
# ORDER FLOW
# ================================================================

def trade_pressure(trades):

    if (
        trades is None
        or trades.empty
    ):
        return 50.0, {}

    x = trades.copy()

    x["buy_volume"] = np.where(
        ~x["buyer_maker"],
        x["quantity"],
        0.0,
    )

    x["sell_volume"] = np.where(
        x["buyer_maker"],
        x["quantity"],
        0.0,
    )

    total = float(
        x["quantity"].sum()
    )

    buy = float(
        x["buy_volume"].sum()
    )

    pressure = (
        buy / total * 100
        if total > 0
        else 50
    )

    threshold = (
        float(
            x["quantity"].quantile(
                0.95
            )
        )
        if len(x) >= 10
        else 0
    )

    large = (
        x[x["quantity"] >= threshold]
        if threshold > 0
        else x.iloc[0:0]
    )

    large_buy = float(
        large["buy_volume"].sum()
    )

    large_sell = float(
        large["sell_volume"].sum()
    )

    large_pressure = (
        large_buy
        / (large_buy + large_sell)
        * 100
        if large_buy + large_sell > 0
        else pressure
    )

    return (
        float(pressure),
        {
            "trade_volume": total,
            "trade_count": len(x),
            "large_trade_pressure": float(
                large_pressure
            ),
        },
    )


# ================================================================
# KALSHI SIGNAL
# ================================================================

def kalshi_signal(data):

    if not data:
        return (
            50.0,
            "Kalshi unavailable",
        )

    markets = data.get(
        "markets",
        [],
    )

    candidates = []

    for market in markets:

        text = (
            str(
                market.get(
                    "title",
                    "",
                )
            )
            + " "
            + str(
                market.get(
                    "ticker",
                    "",
                )
            )
            + " "
            + str(
                market.get(
                    "subtitle",
                    "",
                )
            )
        ).lower()

        if (
            "bitcoin" not in text
            and "btc" not in text
        ):
            continue

        value = (
            market.get("yes_bid")
            or market.get("yes_ask")
            or market.get("last_price")
            or market.get("yes_price")
        )

        try:

            value = float(value)

            if value > 1:
                value /= 100

            if 0 < value < 1:
                candidates.append(
                    value
                )

        except Exception:
            continue

    if not candidates:

        return (
            50.0,
            "No usable BTC prediction-market probability",
        )

    probability = float(
        np.mean(candidates)
    )

    return (
        float(
            np.clip(
                probability * 100,
                1,
                99,
            )
        ),
        (
            f"{len(candidates)} BTC-related "
            f"Kalshi market(s); mean "
            f"Yes probability "
            f"{probability:.1%}"
        ),
    )


# ================================================================
# SPECIALIST AI ENGINE
# ================================================================

def specialist_engine(
    candles,
    pressure=50,
    futures=None,
    kalshi=None,
    aggr=None,
):

    c = (
        candles.copy()
        .reset_index(drop=True)
    )

    close = c["close"]

    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)

    r = rsi(close)
    a = atr(c)

    macd = (
        ema(close, 12)
        - ema(close, 26)
    )

    macd_signal = ema(
        macd,
        9,
    )

    roc5 = (
        close.pct_change(5)
        * 100
    )

    volume_average = (
        c["volume"]
        .rolling(20)
        .mean()
    )

    volume_ratio = (
        float(
            c["volume"].iloc[-1]
            / volume_average.iloc[-1]
        )
        if (
            pd.notna(
                volume_average.iloc[-1]
            )
            and volume_average.iloc[-1] > 0
        )
        else 1.0
    )

    last = float(
        close.iloc[-1]
    )

    current_atr = (
        float(a.iloc[-1])
        if pd.notna(a.iloc[-1])
        else last * 0.001
    )

    current_atr = max(
        current_atr,
        last * 0.0001,
    )

    def clip(value):
        return float(
            np.clip(
                value,
                5,
                95,
            )
        )

    # ------------------------------------------------------------
    # TREND
    # ------------------------------------------------------------

    trend_strength = (
        e9.iloc[-1]
        - e21.iloc[-1]
    ) / current_atr

    trend = clip(
        50
        + 35
        * np.tanh(
            trend_strength * 2
        )
    )

    # ------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------

    roc = (
        float(roc5.iloc[-1])
        if pd.notna(roc5.iloc[-1])
        else 0
    )

    macd_difference = float(
        macd.iloc[-1]
        - macd_signal.iloc[-1]
    )

    macd_scale = max(
        abs(float(macd.iloc[-1])),
        current_atr * 0.05,
        1e-9,
    )

    momentum = clip(
        50
        + 22
        * np.tanh(
            (float(r.iloc[-1]) - 50)
            / 12
        )
        + 18
        * np.tanh(
            roc / 0.25
        )
        + 10
        * np.tanh(
            macd_difference
            / macd_scale
        )
    )

    # ------------------------------------------------------------
    # VOLUME
    # ------------------------------------------------------------

    volume = clip(
        50
        + (pressure - 50) * 0.8
        + 10
        * np.tanh(
            volume_ratio - 1
        )
    )

    # ------------------------------------------------------------
    # PATTERN
    # ------------------------------------------------------------

    candle_range = max(
        float(
            c["high"].iloc[-1]
            - c["low"].iloc[-1]
        ),
        1e-9,
    )

    body = (
        float(
            c["close"].iloc[-1]
            - c["open"].iloc[-1]
        )
        / candle_range
    )

    one_min_return = (
        float(
            (
                close.iloc[-1]
                - close.iloc[-2]
            )
            / close.iloc[-2]
            * 100
        )
        if len(c) > 1
        else 0
    )

    pattern = clip(
        50
        + 25
        * np.tanh(
            one_min_return / 0.12
        )
        + 12
        * np.tanh(
            body * 2
        )
    )

    # ------------------------------------------------------------
    # SUPPORT / RESISTANCE
    # ------------------------------------------------------------

    recent_high = float(
        c["high"]
        .tail(60)
        .max()
    )

    recent_low = float(
        c["low"]
        .tail(60)
        .min()
    )

    midpoint = (
        recent_high
        + recent_low
    ) / 2

    sr = clip(
        50
        + 22
        * np.tanh(
            (
                last
                - midpoint
            )
            / max(
                current_atr * 3,
                1e-9,
            )
        )
    )

    # ------------------------------------------------------------
    # VOLATILITY
    # ------------------------------------------------------------

    atr_pct = (
        current_atr
        / last
        * 100
    )

    volatility = clip(
        55
        + 12
        * np.tanh(
            volume_ratio - 1
        )
        - 8
        * np.tanh(
            (
                atr_pct
                - 0.12
            ) * 3
        )
    )

    # ------------------------------------------------------------
    # REGIME
    # ------------------------------------------------------------

    regime_strength = (
        e9.iloc[-1]
        - e50.iloc[-1]
    ) / current_atr

    regime = clip(
        50
        + 30
        * np.tanh(
            regime_strength
        )
    )

    # ------------------------------------------------------------
    # WHALE
    # ------------------------------------------------------------

    whale = clip(
        50
        + (pressure - 50)
        * 0.65
    )

    # ------------------------------------------------------------
    # LIQUIDITY
    # ------------------------------------------------------------

    liquidity = 50.0

    liquidity_note = (
        "Futures depth unavailable"
    )

    if futures and futures.get(
        "depth"
    ):

        try:

            depth = futures["depth"]

            bids = sum(
                float(x[1])
                for x in depth.get(
                    "bids",
                    [],
                )
            )

            asks = sum(
                float(x[1])
                for x in depth.get(
                    "asks",
                    [],
                )
            )

            total = bids + asks

            if total > 0:

                bid_pct = (
                    bids
                    / total
                    * 100
                )

                liquidity = clip(
                    50
                    + (
                        bid_pct
                        - 50
                    ) * 1.2
                )

                liquidity_note = (
                    f"{bid_pct:.1f}% "
                    "of displayed depth on bids"
                )

        except Exception:
            pass

    # ------------------------------------------------------------
    # DERIVATIVES
    # ------------------------------------------------------------

    derivatives = (
        50
        + roc * 8
    )

    derivatives_note = (
        "Derivatives unavailable"
    )

    if futures:

        try:

            funding = futures.get(
                "funding"
            )

            funding_rate = (
                float(
                    funding.get(
                        "lastFundingRate",
                        0,
                    )
                )
                if funding
                else 0
            )

            derivatives += float(
                np.clip(
                    -funding_rate
                    * 100000,
                    -12,
                    12,
                )
            )

            derivatives_note = (
                f"Funding "
                f"{funding_rate * 100:.4f}%"
            )

            if futures.get("oi"):
                derivatives_note += (
                    " • OI live"
                )

        except Exception:
            pass

    derivatives = clip(
        derivatives
    )

    # ------------------------------------------------------------
    # EVENT
    # ------------------------------------------------------------

    event = 50.0

    event_note = (
        "No independently verified "
        "event feed connected"
    )

    # ------------------------------------------------------------
    # HISTORICAL ANALOG
    # ------------------------------------------------------------

    historical = 50.0

    historical_note = (
        "Not enough historical data"
    )

    if len(c) >= 140:

        x = c.copy()

        x["rsi"] = rsi(
            x["close"]
        )

        x["roc5"] = (
            x["close"]
            .pct_change(5)
            * 100
        )

        x["volume_ratio"] = (
            x["volume"]
            / x["volume"]
            .rolling(20)
            .mean()
        )

        x["atr_pct"] = (
            atr(x)
            / x["close"]
            * 100
        )

        future_return = (
            x["close"]
            .shift(-HORIZON)
            / x["close"]
            - 1
        )

        current = x.iloc[-1]

        candidates = x.iloc[
            :-HORIZON
        ]

        columns = [
            "rsi",
            "roc5",
            "volume_ratio",
            "atr_pct",
        ]

        scales = {}

        for column in columns:

            scales[column] = float(
                x[column]
                .iloc[:-HORIZON]
                .std()
            )

        distances = []

        for index, row in candidates.iterrows():

            future = (
                future_return.loc[index]
            )

            if not np.isfinite(
                future
            ):
                continue

            distance = 0.0

            for column in columns:

                value = row[column]
                current_value = (
                    current[column]
                )

                scale = scales[column]

                if (
                    pd.notna(value)
                    and pd.notna(
                        current_value
                    )
                    and scale > 1e-9
                ):

                    distance += (
                        (
                            float(value)
                            - float(
                                current_value
                            )
                        )
                        / scale
                    ) ** 2

            distances.append(
                (
                    distance,
                    float(future),
                )
            )

        nearest = sorted(
            distances,
            key=lambda x: x[0],
        )[:30]

        if len(nearest) >= 10:

            probability = np.mean(
                [
                    future > 0
                    for _, future
                    in nearest
                ]
            )

            historical = (
                45
                + 55
                * probability
            )

            historical_note = (
                f"{len(nearest)} "
                "OOS-safe historical analogs"
            )

    # ------------------------------------------------------------
    # PREDICTION MARKET
    # ------------------------------------------------------------

    prediction_market, prediction_note = (
        kalshi_signal(
            kalshi
        )
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
        "Historical AI": clip(
            historical
        ),
        "Prediction Market AI": prediction_market,
    }

    evidence = {
        "Trend AI": (
            f"EMA9 "
            f"{e9.iloc[-1]:,.0f} vs "
            f"EMA21 "
            f"{e21.iloc[-1]:,.0f}"
        ),

        "Momentum AI": (
            f"RSI "
            f"{r.iloc[-1]:.1f} • "
            f"ROC5 "
            f"{roc:+.3f}%"
        ),

        "Volume AI": (
            f"Volume "
            f"{volume_ratio:.2f}x avg • "
            f"pressure "
            f"{pressure:.1f}%"
        ),

        "Pattern AI": (
            f"Body "
            f"{body:+.2f} • "
            f"1m return "
            f"{one_min_return:+.3f}%"
        ),

        "S/R AI": (
            f"Support "
            f"${recent_low:,.0f} • "
            f"Resistance "
            f"${recent_high:,.0f}"
        ),

        "Volatility AI": (
            f"ATR "
            f"${current_atr:,.0f} • "
            f"{atr_pct:.3f}%"
        ),

        "Regime AI": (
            "BULL TREND"
            if regime >= 60
            else
            "BEAR TREND"
            if regime <= 40
            else
            "CHOP / MIXED"
        ),

        "Whale AI": (
            f"Aggressor pressure "
            f"{pressure:.1f}%"
        ),

        "Liquidity AI":
            liquidity_note,

        "Derivatives AI":
            derivatives_note,

        "Event AI":
            event_note,

        "Historical AI":
            historical_note,

        "Prediction Market AI":
            prediction_note,
    }

    features = {
        "price": last,
        "ema9": float(
            e9.iloc[-1]
        ),
        "ema21": float(
            e21.iloc[-1]
        ),
        "ema50": float(
            e50.iloc[-1]
        ),
        "rsi": float(
            r.iloc[-1]
        ),
        "atr": current_atr,
        "atr_pct": atr_pct,
        "volume_ratio": volume_ratio,
        "support": recent_low,
        "resistance": recent_high,
        "pressure": pressure,
    }

    return (
        scores,
        features,
        evidence,
    )


# ================================================================
# MASTER AI
# ================================================================

DEFAULT_WEIGHTS = {
    name: 1.0
    for name in SPECIALISTS
}

DEFAULT_WEIGHTS.update(
    {
        "Trend AI": 1.20,
        "Momentum AI": 1.15,
        "Regime AI": 1.15,
        "Liquidity AI": 1.05,
        "Prediction Market AI": 0.85,
    }
)


def calibrated_probability(
    weighted_score,
    disagreement,
):

    edge = max(
        0,
        (
            abs(
                weighted_score
                - 50
            )
            - 2
        )
        / 48,
    )

    raw = (
        0.5
        + 0.45
        * edge
        * (
            1
            if weighted_score >= 50
            else -1
        )
    )

    shrink = np.clip(
        disagreement / 30,
        0,
        0.45,
    )

    probability = (
        0.5
        + (
            raw
            - 0.5
        )
        * (
            1
            - shrink
        )
    )

    return float(
        np.clip(
            probability,
            0.01,
            0.99,
        )
    )


def master_ai(
    scores,
    learned_weights=None,
):

    weights = DEFAULT_WEIGHTS.copy()

    if learned_weights:

        for name, value in (
            learned_weights.items()
        ):

            if name in weights:

                weights[name] = float(
                    np.clip(
                        value,
                        0.50,
                        1.50,
                    )
                )

    regime = scores.get(
        "Regime AI",
        50,
    )

    if regime >= 60:

        for name in (
            "Trend AI",
            "Momentum AI",
            "Volume AI",
        ):
            weights[name] *= 1.12

    elif regime <= 40:

        weights[
            "Volatility AI"
        ] *= 1.15

    weighted = sum(
        scores[name]
        * weights.get(
            name,
            1,
        )
        for name in scores
    ) / sum(
        weights.get(
            name,
            1,
        )
        for name in scores
    )

    values = np.array(
        list(
            scores.values()
        ),
        dtype=float,
    )

    disagreement = float(
        np.std(values)
    )

    probability = (
        calibrated_probability(
            weighted,
            disagreement,
        )
    )

    confidence = float(
        np.clip(
            50
            + abs(
                probability
                - 0.5
            )
            * 100
            - disagreement
            * 0.25,
            50,
            95,
        )
    )

    if (
        probability >= 0.60
        and confidence >= 58
    ):

        signal = "LONG"

    elif (
        probability <= 0.40
        and confidence >= 58
    ):

        signal = "SHORT"

    else:

        signal = "HOLD"

    contributions = {}

    for name, score in scores.items():

        contributions[name] = {
            "score": float(score),
            "weight": float(
                weights.get(
                    name,
                    1,
                )
            ),
            "contribution": float(
                (
                    score - 50
                )
                * weights.get(
                    name,
                    1,
                )
            ),
        }

    return (
        signal,
        confidence,
        float(weighted),
        disagreement,
        probability,
        contributions,
    )


# ================================================================
# DATABASE
# ================================================================

def database():

    connection = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=10,
    )

    connection.execute(
        "PRAGMA journal_mode=WAL"
    )

    connection.execute(
        "PRAGMA busy_timeout=5000"
    )

    return connection


def init_database():

    with DB_LOCK:

        connection = database()

        # --------------------------------------------------------
        # SQLite settings
        # --------------------------------------------------------

        connection.execute(
            "PRAGMA journal_mode=WAL"
        )

        connection.execute(
            "PRAGMA busy_timeout=10000"
        )

        # --------------------------------------------------------
        # Original prediction table
        # --------------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_key TEXT UNIQUE,
                created_at TEXT,
                target_time TEXT,
                price REAL,
                signal TEXT,
                confidence REAL,
                bullish_score REAL,
                bullish_probability REAL,
                expected_price REAL,
                disagreement REAL,
                specialist_json TEXT,
                evidence_json TEXT,
                features_json TEXT,
                actual_price REAL,
                return_pct REAL,
                error_pct REAL,
                correct INTEGER,
                scored_at TEXT
            )
            """
        )

        # --------------------------------------------------------
        # SAFE MIGRATION FOR EXISTING DATABASES
        # --------------------------------------------------------

        existing_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(predictions)"
            ).fetchall()
        }

        migrations = {
            "bullish_probability":
                "ALTER TABLE predictions ADD COLUMN bullish_probability REAL",

            "error_pct":
                "ALTER TABLE predictions ADD COLUMN error_pct REAL",

            "features_json":
                "ALTER TABLE predictions ADD COLUMN features_json TEXT",
        }

        for column, statement in migrations.items():

            if column not in existing_columns:

                connection.execute(
                    statement
                )

        # --------------------------------------------------------
        # Backfill probability from old bullish_score
        # --------------------------------------------------------

        columns_after_migration = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(predictions)"
            ).fetchall()
        }

        if (
            "bullish_score"
            in columns_after_migration
            and "bullish_probability"
            in columns_after_migration
        ):

            connection.execute(
                """
                UPDATE predictions
                SET bullish_probability =
                    CASE
                        WHEN bullish_probability IS NULL
                        THEN
                            MAX(
                                0.01,
                                MIN(
                                    0.99,
                                    bullish_score / 100.0
                                )
                            )
                        ELSE bullish_probability
                    END
                WHERE bullish_score IS NOT NULL
                """
            )

        # --------------------------------------------------------
        # Paper trades
        # --------------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opened_at TEXT,
                closed_at TEXT,
                side TEXT,
                entry REAL,
                exit REAL,
                qty REAL,
                fees REAL,
                slippage REAL,
                pnl REAL,
                return_pct REAL,
                reason TEXT
            )
            """
        )

        # --------------------------------------------------------
        # Learner versions
        # --------------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learner_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                version TEXT,
                weights_json TEXT,
                reason TEXT
            )
            """
        )

        # --------------------------------------------------------
        # System events
        # --------------------------------------------------------

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                level TEXT,
                source TEXT,
                message TEXT
            )
            """
        )

        connection.commit()

        connection.close()

# ================================================================
# PREDICTION JOURNAL
# ================================================================

def log_prediction(
    timestamp,
    price,
    signal,
    confidence,
    probability,
    expected_price,
    disagreement,
    scores,
    evidence,
    features,
):

    timestamp = pd.Timestamp(
        timestamp
    )

    target = (
        timestamp
        + pd.Timedelta(
            minutes=HORIZON
        )
    )

    key = (
        f"{timestamp.isoformat()}"
        f"|{HORIZON}"
    )

    with DB_LOCK:

        connection = database()

        connection.execute(
            """
            INSERT OR IGNORE INTO predictions
            (
                prediction_key,
                created_at,
                target_time,
                price,
                signal,
                confidence,
                bullish_probability,
                expected_price,
                disagreement,
                specialist_json,
                evidence_json,
                features_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                key,
                timestamp.isoformat(),
                target.isoformat(),
                float(price),
                signal,
                float(confidence),
                float(probability),
                float(expected_price),
                float(disagreement),
                json.dumps(
                    scores,
                    allow_nan=False,
                ),
                json.dumps(
                    evidence,
                    allow_nan=False,
                ),
                json.dumps(
                    features,
                    allow_nan=False,
                ),
            ),
        )

        connection.commit()
        connection.close()

def score_predictions(
    candles
):

    if candles is None:
        return

    if candles.empty:
        return

    with DB_LOCK:

        connection = database()

        rows = connection.execute(
            """
            SELECT
                id,
                target_time,
                price,
                signal,
                expected_price
            FROM predictions
            WHERE actual_price IS NULL
            """
        ).fetchall()

        for (
            row_id,
            target_time,
            entry,
            signal,
            expected,
        ) in rows:

            future = candles[
                pd.to_datetime(
                    candles["time"],
                    utc=True,
                )
                >= pd.Timestamp(
                    target_time
                )
            ]

            if future.empty:
                continue

            actual = float(
                future["close"].iloc[0]
            )

            return_pct = (
                actual
                / entry
                - 1
            ) * 100

            if signal == "LONG":

                correct = int(
                    return_pct > 0
                )

            elif signal == "SHORT":

                correct = int(
                    return_pct < 0
                )

            else:

                correct = int(
                    abs(
                        return_pct
                    )
                    < 0.15
                )

            error_pct = (
                abs(
                    actual
                    - expected
                )
                / entry
                * 100
                if expected
                else None
            )

            connection.execute(
                """
                UPDATE predictions
                SET
                    actual_price = ?,
                    return_pct = ?,
                    error_pct = ?,
                    correct = ?,
                    scored_at = ?
                WHERE id = ?
                """,
                (
                    actual,
                    return_pct,
                    error_pct,
                    correct,
                    datetime.now(
                        timezone.utc
                    ).isoformat(),
                    row_id,
                ),
            )

        connection.commit()
        connection.close()


def journal_stats():

    with DB_LOCK:

        connection = database()

        row = connection.execute(
            """
            SELECT
                COUNT(*),
                SUM(
                    actual_price IS NOT NULL
                ),
                AVG(correct),
                AVG(error_pct)
            FROM predictions
            """
        ).fetchone()

        brier_rows = connection.execute(
            """
            SELECT
                bullish_probability,
                return_pct
            FROM predictions
            WHERE
                actual_price IS NOT NULL
                AND bullish_probability IS NOT NULL
                AND return_pct IS NOT NULL
            """
        ).fetchall()

        connection.close()

    brier = 0.0

    if brier_rows:

        errors = []

        for probability, ret in (
            brier_rows
        ):

            outcome = (
                1.0
                if ret > 0
                else 0.0
            )

            errors.append(
                (
                    float(probability)
                    - outcome
                )
                ** 2
            )

        brier = float(
            np.mean(errors)
        )

    return {
        "predictions": int(
            row[0] or 0
        ),
        "scored": int(
            row[1] or 0
        ),
        "accuracy": float(
            row[2] or 0
        ) * 100,
        "magnitude_error": float(
            row[3] or 0
        ),
        "brier": brier,
    }


# ================================================================
# PAPER BROKER
# ================================================================

class PaperBroker:

    def __init__(
        self,
        balance=STARTING_BALANCE,
    ):

        self.starting_balance = (
            float(balance)
        )

        self.cash = float(
            balance
        )

        self.position = None

        self.fee_bps = 6
        self.slippage_bps = 2
        self.spread_bps = 2

        self.max_position_pct = 0.25

        self.max_daily_loss_pct = 0.03
        self.max_drawdown_pct = 0.10

        self.equity_peak = (
            self.cash
        )

        self.day_start = (
            self.cash
        )

    def equity(self, price):

        if self.position is None:
            return self.cash

        position = self.position

        direction = (
            1
            if position["side"]
            == "LONG"
            else -1
        )

        unrealized = (
            price
            - position["entry"]
        ) * position["qty"] * direction

        return (
            self.cash
            + unrealized
        )

    def risk_halt(self, price):

        equity = self.equity(
            price
        )

        self.equity_peak = max(
            self.equity_peak,
            equity,
        )

        drawdown = (
            (
                self.equity_peak
                - equity
            )
            / self.equity_peak
            if self.equity_peak
            else 0
        )

        daily_loss = (
            (
                self.day_start
                - equity
            )
            / self.day_start
            if self.day_start
            else 0
        )

        return (
            drawdown
            >= self.max_drawdown_pct
            or
            daily_loss
            >= self.max_daily_loss_pct
        )

    def open(
        self,
        side,
        price,
        confidence,
        atr_value,
    ):

        if self.position:
            return False

        if side == "HOLD":
            return False

        if self.risk_halt(price):
            return False

        strength = np.clip(
            (
                confidence
                - 50
            ) / 45,
            0.25,
            1,
        )

        notional = (
            self.cash
            * self.max_position_pct
            * strength
        )

        qty = (
            notional
            / price
        )

        execution_cost = (
            self.slippage_bps
            + self.spread_bps
        )

        price_adjustment = (
            price
            * execution_cost
            / 10000
        )

        if side == "LONG":

            fill = (
                price
                + price_adjustment
            )

        else:

            fill = (
                price
                - price_adjustment
            )

        fee = (
            fill
            * qty
            * self.fee_bps
            / 10000
        )

        self.cash -= fee

        stop_distance = max(
            atr_value * 1.2,
            price * 0.002,
        )

        take_distance = max(
            atr_value * 1.8,
            price * 0.003,
        )

        if side == "LONG":

            stop = (
                fill
                - stop_distance
            )

            take = (
                fill
                + take_distance
            )

        else:

            stop = (
                fill
                + stop_distance
            )

            take = (
                fill
                - take_distance
            )

        self.position = {
            "side": side,
            "entry": fill,
            "qty": qty,
            "opened_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "stop": stop,
            "take": take,
        }

        return True

    def close(
        self,
        price,
        reason,
    ):

        if not self.position:
            return None

        position = self.position

        side = position["side"]

        if side == "LONG":

            fill = (
                price
                * (
                    1
                    - self.spread_bps
                    / 10000
                )
            )

            direction = 1

        else:

            fill = (
                price
                * (
                    1
                    + self.spread_bps
                    / 10000
                )
            )

            direction = -1

        gross = (
            fill
            - position["entry"]
        ) * position["qty"] * direction

        fee = (
            fill
            * position["qty"]
            * self.fee_bps
            / 10000
        )

        pnl = gross - fee

        self.cash += pnl

        return_pct = (
            pnl
            / (
                position["entry"]
                * position["qty"]
            )
            * 100
        )

        trade = {
            "opened_at":
                position["opened_at"],
            "closed_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "side": side,
            "entry":
                position["entry"],
            "exit": fill,
            "qty":
                position["qty"],
            "fees": fee,
            "slippage":
                abs(fill - price),
            "pnl": pnl,
            "return_pct":
                return_pct,
            "reason": reason,
        }

        with DB_LOCK:

            connection = database()

            connection.execute(
                """
                INSERT INTO trades
                (
                    opened_at,
                    closed_at,
                    side,
                    entry,
                    exit,
                    qty,
                    fees,
                    slippage,
                    pnl,
                    return_pct,
                    reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(
                    trade.values()
                ),
            )

            connection.commit()
            connection.close()

        self.position = None

        return trade

    def manage(self, price):

        if not self.position:
            return None

        p = self.position

        stop_hit = (
            price <= p["stop"]
            if p["side"] == "LONG"
            else price >= p["stop"]
        )

        take_hit = (
            price >= p["take"]
            if p["side"] == "LONG"
            else price <= p["take"]
        )

        if stop_hit:
            return self.close(
                price,
                "STOP LOSS",
            )

        if take_hit:
            return self.close(
                price,
                "TAKE PROFIT",
            )

        if self.risk_halt(price):
            return self.close(
                price,
                "RISK HALT",
            )

        return None


# ================================================================
# LEARNING
# ================================================================

def learn_weights():

    with DB_LOCK:

        connection = database()

        rows = connection.execute(
            """
            SELECT
                specialist_json,
                return_pct
            FROM predictions
            WHERE
                actual_price IS NOT NULL
                AND return_pct IS NOT NULL
            """
        ).fetchall()

        connection.close()

    if len(rows) < 30:

        return (
            DEFAULT_WEIGHTS.copy(),
            "Need at least 30 scored predictions",
        )

    performance = {
        name: []
        for name in SPECIALISTS
    }

    for specialist_json, return_pct in rows:

        try:

            scores = json.loads(
                specialist_json
            )

            direction = (
                1
                if return_pct > 0
                else -1
            )

            for name, score in (
                scores.items()
            ):

                performance.setdefault(
                    name,
                    [],
                ).append(
                    (
                        float(score)
                        - 50
                    )
                    * direction
                )

        except Exception:
            continue

    weights = (
        DEFAULT_WEIGHTS.copy()
    )

    for name, values in (
        performance.items()
    ):

        if len(values) < 10:
            continue

        edge = np.tanh(
            np.mean(values)
            / 20
        )

        weights[name] = float(
            np.clip(
                1
                + 0.35
                * edge,
                0.70,
                1.30,
            )
        )

    return (
        weights,
        f"Bounded learner update from "
        f"{len(rows)} scored predictions",
    )


def save_learner(
    weights,
    reason,
):

    with DB_LOCK:

        connection = database()

        connection.execute(
            """
            INSERT INTO learner_versions
            (
                created_at,
                version,
                weights_json,
                reason
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now(
                    timezone.utc
                ).isoformat(),
                APP_VERSION,
                json.dumps(weights),
                reason,
            ),
        )

        connection.commit()
        connection.close()


# ================================================================
# WALK-FORWARD BACKTEST
# ================================================================

def backtest(
    candles,
    weights=None,
):

    if (
        candles is None
        or len(candles)
        < 180
    ):

        return (
            pd.DataFrame(),
            {},
        )

    starting = 10000.0
    equity = starting

    curve = []
    trades = []

    for index in range(
        100,
        len(candles)
        - HORIZON,
        5,
    ):

        history = (
            candles.iloc[
                : index + 1
            ]
            .copy()
        )

        scores, features, evidence = (
            specialist_engine(
                history,
                pressure=50,
                futures=None,
                kalshi=None,
                aggr=None,
            )
        )

        (
            signal,
            confidence,
            weighted,
            disagreement,
            probability,
            contributions,
        ) = master_ai(
            scores,
            weights,
        )

        price = float(
            candles["close"]
            .iloc[index]
        )

        if (
            signal
            not in (
                "LONG",
                "SHORT",
            )
            or confidence < 58
        ):

            curve.append(
                (
                    candles["time"]
                    .iloc[index],
                    equity,
                )
            )

            continue

        direction = (
            1
            if signal == "LONG"
            else -1
        )

        entry = (
            price
            * (
                1
                + direction
                * 0.0004
            )
        )

        exit_price = float(
            candles["close"]
            .iloc[
                index + HORIZON
            ]
        )

        exit_price *= (
            1
            - direction
            * 0.0004
        )

        gross_return = (
            (
                exit_price
                - entry
            )
            / entry
            * 100
            * direction
        )

        costs = 0.12

        net_return = (
            gross_return
            - costs
        )

        position_notional = (
            equity * 0.10
        )

        pnl = (
            position_notional
            * net_return
            / 100
        )

        equity += pnl

        trades.append(
            {
                "return_pct":
                    net_return,
                "pnl": pnl,
                "regime":
                    scores[
                        "Regime AI"
                    ],
            }
        )

        curve.append(
            (
                candles["time"]
                .iloc[index],
                equity,
            )
        )

    curve_df = pd.DataFrame(
        curve,
        columns=[
            "time",
            "equity",
        ],
    )

    if curve_df.empty:

        return (
            curve_df,
            {},
        )

    returns = (
        curve_df["equity"]
        .pct_change()
        .dropna()
    )

    peak = (
        curve_df["equity"]
        .cummax()
    )

    drawdown = (
        curve_df["equity"]
        / peak
        - 1
    ) * 100

    wins = [
        trade["return_pct"]
        for trade in trades
        if trade["return_pct"] > 0
    ]

    losses = [
        trade["return_pct"]
        for trade in trades
        if trade["return_pct"] <= 0
    ]

    gross_win = sum(wins)
    gross_loss = abs(
        sum(losses)
    )

    if gross_loss > 0:

        profit_factor = (
            gross_win
            / gross_loss
        )

    elif wins:

        profit_factor = float(
            "inf"
        )

    else:

        profit_factor = 0

    if returns.std() > 0:

        sharpe = (
            returns.mean()
            / returns.std()
            * np.sqrt(
                365
                * 24
                * 4
            )
        )

    else:

        sharpe = 0

    summary = {
        "start":
            starting,

        "end":
            float(
                curve_df[
                    "equity"
                ].iloc[-1]
            ),

        "return_pct":
            (
                curve_df[
                    "equity"
                ].iloc[-1]
                / starting
                - 1
            )
            * 100,

        "trades":
            len(trades),

        "win_rate":
            (
                len(wins)
                / len(trades)
                * 100
                if trades
                else 0
            ),

        "profit_factor":
            profit_factor,

        "max_drawdown_pct":
            abs(
                float(
                    drawdown.min()
                )
            ),

        "sharpe":
            float(sharpe),

        "avg_win":
            float(
                np.mean(wins)
            )
            if wins
            else 0,

        "avg_loss":
            float(
                np.mean(losses)
            )
            if losses
            else 0,
    }

    return (
        curve_df,
        summary,
    )


# ================================================================
# UI
# ================================================================

init_database()

if "broker" not in st.session_state:

    st.session_state.broker = (
        PaperBroker()
    )

if "streaming" not in st.session_state:

    st.session_state.streaming = True


with st.sidebar:

    st.header(
        "₿ BTC AI Command Center"
    )

    refresh = st.slider(
        "Refresh interval",
        1,
        30,
        3,
    )

    st.caption(
        f"Build {APP_VERSION}"
    )

    st.warning(
        "PAPER TRADING ONLY"
    )

    if st.button(
        "Refresh now"
    ):

        st.cache_data.clear()
        st.rerun()

    if st.button(
        "Reset paper account"
    ):

        st.session_state.broker = (
            PaperBroker()
        )

        st.success(
            "Paper account reset."
        )


@st.fragment(
    run_every=(
        refresh
        if st.session_state.streaming
        else None
    )
)
def dashboard():

    data = (
        collect_market_data()
    )

    candles = data[
        "candles"
    ]

    trades = data.get(
        "trades"
    )

    pressure, flow = (
        trade_pressure(
            trades
        )
    )

    futures = {
        "funding":
            data.get(
                "funding"
            ),
        "oi":
            data.get(
                "oi"
            ),
        "depth":
            data.get(
                "depth"
            ),
    }

    learned_weights, learn_reason = (
        learn_weights()
    )

    (
        scores,
        features,
        evidence,
    ) = specialist_engine(
        candles,
        pressure,
        futures,
        data.get("kalshi"),
        data.get("aggr"),
    )

    (
        signal,
        confidence,
        weighted,
        disagreement,
        probability,
        contributions,
    ) = master_ai(
        scores,
        learned_weights,
    )

    price = float(
        data.get(
            "price"
        )
        or candles[
            "close"
        ].iloc[-1]
    )

    expected_move = (
        (
            probability
            - 0.5
        )
        * 2
        * max(
            features["atr"]
            / price,
            0.0005,
        )
    )

    expected_price = (
        price
        * (
            1
            + expected_move
        )
    )

    log_prediction(
        candles["time"].iloc[-1],
        price,
        signal,
        confidence,
        probability,
        expected_price,
        disagreement,
        scores,
        evidence,
        features,
    )

    score_predictions(
        candles
    )

    stats = (
        journal_stats()
    )

    broker = (
        st.session_state.broker
    )

    broker.manage(
        price
    )

    # Only take paper trades when confidence is high.
    if (
        signal
        in (
            "LONG",
            "SHORT",
        )
        and confidence >= 65
        and broker.position is None
        and data["mode"]
        != "DEMO"
    ):

        broker.open(
            signal,
            price,
            confidence,
            features["atr"],
        )

    equity = broker.equity(
        price
    )

    drawdown = (
        (
            broker.equity_peak
            - equity
        )
        / broker.equity_peak
        * 100
        if broker.equity_peak
        else 0
    )

    # ------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------

    st.title(
        "₿ BTC AI Trading Command Center"
    )

    st.caption(
        "Live BTC intelligence • "
        "specialist ensemble • "
        "15-minute prediction • "
        "paper execution • "
        "prediction journal • "
        "walk-forward testing"
    )

    # ------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------

    if data["mode"] == "LIVE":

        st.success(
            "LIVE MARKET DATA"
        )

    elif data["mode"] == "DEGRADED":

        st.warning(
            "DEGRADED MARKET DATA — "
            "some feeds unavailable"
        )

    else:

        st.error(
            "DEMO MODE — live candle "
            "feed unavailable"
        )

    # ------------------------------------------------------------
    # TOP METRICS
    # ------------------------------------------------------------

    c1, c2, c3, c4, c5 = (
        st.columns(5)
    )

    c1.metric(
        "BTC",
        f"${price:,.2f}",
    )

    c2.metric(
        "MASTER",
        signal,
    )

    c3.metric(
        "Probability",
        f"{probability:.1%}",
    )

    c4.metric(
        "Confidence",
        f"{confidence:.1f}%",
    )

    c5.metric(
        "Feed Latency",
        f"{data['latency_ms']:.0f} ms",
    )

    # ------------------------------------------------------------
    # MASTER DECISION
    # ------------------------------------------------------------

    st.subheader(
        "15-Minute Master Decision"
    )

    a, b, c, d, e = (
        st.columns(5)
    )

    a.metric(
        "Weighted Score",
        f"{weighted:.1f}",
    )

    b.metric(
        "Disagreement",
        f"{disagreement:.1f}",
    )

    c.metric(
        "Expected Price",
        f"${expected_price:,.2f}",
    )

    d.metric(
        "Paper Equity",
        f"${equity:,.2f}",
    )

    e.metric(
        "Drawdown",
        f"{drawdown:.2f}%",
    )

    # ------------------------------------------------------------
    # PRICE CHART
    # ------------------------------------------------------------

    figure = go.Figure()

    figure.add_trace(
        go.Candlestick(
            x=candles["time"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name="BTCUSDT",
        )
    )

    figure.update_layout(
        height=450,
        margin=dict(
            l=10,
            r=10,
            t=30,
            b=10,
        ),
        xaxis_rangeslider_visible=False,
    )

    st.plotly_chart(
        figure,
        use_container_width=True,
    )

    # ------------------------------------------------------------
    # SPECIALISTS
    # ------------------------------------------------------------

    st.subheader(
        "Specialist AI Ensemble"
    )

    specialist_rows = []

    for name in SPECIALISTS:

        specialist_rows.append(
            {
                "Specialist":
                    name,
                "Score":
                    round(
                        scores[name],
                        1,
                    ),
                "Weight":
                    round(
                        contributions[
                            name
                        ][
                            "weight"
                        ],
                        2,
                    ),
                "Evidence":
                    evidence[name],
            }
        )

    st.dataframe(
        pd.DataFrame(
            specialist_rows
        ),
        use_container_width=True,
        hide_index=True,
    )

    # ------------------------------------------------------------
    # PAPER POSITION
    # ------------------------------------------------------------

    st.subheader(
        "Paper Position & Risk"
    )

    if broker.position:

        position = (
            broker.position
        )

        st.write(
            f"**{position['side']}** • "
            f"Entry "
            f"${position['entry']:,.2f} • "
            f"Quantity "
            f"{position['qty']:.6f} BTC • "
            f"Stop "
            f"${position['stop']:,.2f} • "
            f"Take "
            f"${position['take']:,.2f}"
        )

    else:

        st.write(
            "No open paper position."
        )

    st.write(
        f"Equity: "
        f"**${equity:,.2f}** • "
        f"Peak: "
        f"**${broker.equity_peak:,.2f}** • "
        f"Drawdown: "
        f"**{drawdown:.2f}%**"
    )

    # ------------------------------------------------------------
    # JOURNAL
    # ------------------------------------------------------------

    st.subheader(
        "Prediction Journal"
    )

    j1, j2, j3, j4 = (
        st.columns(4)
    )

    j1.metric(
        "Predictions",
        stats["predictions"],
    )

    j2.metric(
        "Scored",
        stats["scored"],
    )

    j3.metric(
        "Accuracy",
        f"{stats['accuracy']:.1f}%",
    )

    j4.metric(
        "Brier",
        f"{stats['brier']:.4f}",
    )

    st.caption(
        "Mean absolute expected-price "
        f"error: "
        f"{stats['magnitude_error']:.3f}%"
    )

    # ------------------------------------------------------------
    # BACKTEST
    # ------------------------------------------------------------

    st.subheader(
        "Walk-Forward Backtest"
    )

    equity_curve, summary = (
        backtest(
            candles,
            learned_weights,
        )
    )

    if summary:

        b1, b2, b3, b4, b5, b6 = (
            st.columns(6)
        )

        b1.metric(
            "Return",
            f"{summary['return_pct']:.2f}%",
        )

        b2.metric(
            "Win Rate",
            f"{summary['win_rate']:.2f}%",
        )

        b3.metric(
            "Profit Factor",
            (
                "∞"
                if summary[
                    "profit_factor"
                ] == float("inf")
                else f"{summary['profit_factor']:.2f}"
            ),
        )

        b4.metric(
            "Max DD",
            f"{summary['max_drawdown_pct']:.2f}%",
        )

        b5.metric(
            "Sharpe",
            f"{summary['sharpe']:.2f}",
        )

        b6.metric(
            "Trades",
            summary["trades"],
        )

        if not equity_curve.empty:

            st.line_chart(
                equity_curve.set_index(
                    "time"
                )["equity"]
            )

    else:

        st.info(
            "Need more historical data "
            "for the walk-forward test."
        )

    # ------------------------------------------------------------
    # SOURCE HEALTH
    # ------------------------------------------------------------

    with st.expander(
        "External Source Health"
    ):

        st.write(
            {
                "Binance mode":
                    data["mode"],
                "Binance errors":
                    data.get(
                        "errors",
                        {},
                    ),
                "Kalshi":
                    (
                        "CONNECTED"
                        if data.get(
                            "kalshi"
                        )
                        is not None
                        else data.get(
                            "kalshi_error"
                        )
                    ),
                "AGGR":
                    (
                        "CONNECTED"
                        if data.get(
                            "aggr"
                        )
                        is not None
                        else (
                            "NOT CONFIGURED"
                            if not AGGR_API_URL
                            else data.get(
                                "aggr_error"
                            )
                        )
                    ),
                "Primary latency":
                    f"{data['latency_ms']:.0f} ms",
                "Kalshi latency":
                    data.get(
                        "kalshi_latency"
                    ),
                "AGGR latency":
                    data.get(
                        "aggr_latency"
                    ),
            }
        )

        st.caption(
            "A failed source is reported as unavailable "
            "instead of silently replacing the entire "
            "live dataset with synthetic data."
        )

    # ------------------------------------------------------------
    # LEARNING
    # ------------------------------------------------------------

    with st.expander(
        "Controlled Learning"
    ):

        st.write(
            learn_reason
        )

        st.write(
            "Learner weights are bounded between "
            "0.70 and 1.30."
        )

        st.write(
            "The system does not rewrite its own "
            "source code or trading logic."
        )

        if st.button(
            "Save learner version"
        ):

            save_learner(
                learned_weights,
                learn_reason,
            )

            st.success(
                "Learner version saved."
            )

    # ------------------------------------------------------------
    # FEATURES
    # ------------------------------------------------------------

    with st.expander(
        "Current Features"
    ):

        st.json(
            features
        )

        st.write(
            "Order-flow:",
            flow,
        )

    # ------------------------------------------------------------
    # SAFETY
    # ------------------------------------------------------------

    with st.expander(
        "Safety / Trading Rules"
    ):

        st.markdown(
            """
            **Real-money trading is disabled.**

            - Binance order endpoints are not used.
            - Kalshi order endpoints are not used.
            - Paper broker only.
            - Maximum paper position: 25%.
            - Maximum daily loss: 3%.
            - Maximum drawdown: 10%.
            - Stop loss and take profit are simulated.
            - Fees are simulated.
            - Spread is simulated.
            - Slippage is simulated.
            - Demo data is explicitly labeled.
            - Historical analogs exclude their future horizon.
            - Backtesting only uses information available up to each test point.
            - Learning is bounded and versioned.
            """
        )

    # ------------------------------------------------------------
    # VERSION
    # ------------------------------------------------------------

    st.caption(
        f"Algorithm version: {APP_VERSION} • "
        "Paper trading only"
    )


dashboard()