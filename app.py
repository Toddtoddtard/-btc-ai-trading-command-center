import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json
from datetime import datetime, timezone


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="BTC AI Command Center",
    page_icon="₿",
    layout="wide"
)


# ============================================================
# CONFIG
# ============================================================

BINANCE_BASE_URL = "https://data-api.binance.vision"

TIMEFRAMES = [
    "1 second",
    "3 seconds",
    "5 seconds",
    "1 minute",
    "3 minutes",
    "5 minutes",
    "15 minutes"
]


# ============================================================
# BINANCE PUBLIC DATA
# ============================================================

def binance_get(endpoint, params):
    """
    Public Binance market-data request.

    No API key.
    No account.
    No trading permissions.
    """

    query = urlencode(params)

    url = f"{BINANCE_BASE_URL}{endpoint}?{query}"

    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/2.0"
        }
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


# ============================================================
# LIVE BTC CANDLES
# ============================================================

@st.cache_data(ttl=15, show_spinner=False)
def get_btc_candles(limit=500):

    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": limit
        }
    )

    if not data:
        raise ValueError(
            "Binance returned no candle data."
        )

    rows = []

    for candle in data:

        rows.append({
            "time": pd.to_datetime(
                candle[0],
                unit="ms",
                utc=True
            ),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5])
        })

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


# ============================================================
# LIVE AGGREGATED TRADES
# ============================================================

@st.cache_data(ttl=5, show_spinner=False)
def get_recent_trades(limit=1000):

    data = binance_get(
        "/api/v3/aggTrades",
        {
            "symbol": "BTCUSDT",
            "limit": limit
        }
    )

    if not data:
        raise ValueError(
            "Binance returned no recent trades."
        )

    rows = []

    for trade in data:

        rows.append({
            "time": pd.to_datetime(
                trade["T"],
                unit="ms",
                utc=True
            ),
            "price": float(trade["p"]),
            "quantity": float(trade["q"]),

            # True means buyer was maker.
            # Therefore the aggressor was selling.
            "buyer_maker": bool(trade["m"])
        })

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


# ============================================================
# LIVE BTC PRICE
# ============================================================

@st.cache_data(ttl=5, show_spinner=False)
def get_live_price():

    data = binance_get(
        "/api/v3/ticker/price",
        {
            "symbol": "BTCUSDT"
        }
    )

    return float(data["price"])


# ============================================================
# SHORT-TERM TRADE BARS
# ============================================================

def build_trade_bars(trades, seconds):

    if trades.empty:
        return pd.DataFrame()

    temp = trades.copy()

    temp["sell_volume"] = np.where(
        temp["buyer_maker"],
        temp["quantity"],
        0.0
    )

    temp["buy_volume"] = np.where(
        ~temp["buyer_maker"],
        temp["quantity"],
        0.0
    )

    temp = temp.set_index("time")

    rule = f"{seconds}s"

    bars = temp["price"].resample(rule).ohlc()

    bars["volume"] = (
        temp["quantity"]
        .resample(rule)
        .sum()
    )

    bars["buy_volume"] = (
        temp["buy_volume"]
        .resample(rule)
        .sum()
    )

    bars["sell_volume"] = (
        temp["sell_volume"]
        .resample(rule)
        .sum()
    )

    bars["trades"] = (
        temp["quantity"]
        .resample(rule)
        .count()
    )

    bars = bars.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close"
        ]
    )

    bars["buy_pressure"] = np.where(
        bars["volume"] > 0,
        (
            bars["buy_volume"]
            / bars["volume"]
        ) * 100,
        50
    )

    return bars.reset_index()


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def ema(series, span):

    return series.ewm(
        span=span,
        adjust=False
    ).mean()


def rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(
        lower=0
    )

    loss = -delta.clip(
        upper=0
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan
        )
    )

    result = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    return result.fillna(50)


def atr(df, period=14):

    previous_close = df["close"].shift(1)

    true_range = pd.concat(
        [
            df["high"] - df["low"],

            (
                df["high"]
                - previous_close
            ).abs(),

            (
                df["low"]
                - previous_close
            ).abs()
        ],
        axis=1
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()


# ============================================================
# SPECIALIST AI ENGINE
# ============================================================

def calculate_specialists(
    candles,
    buy_pressure
):

    c = candles.copy()

    close = c["close"]

    # -------------------------
    # Core indicators
    # -------------------------

    ema9 = ema(
        close,
        9
    )

    ema21 = ema(
        close,
        21
    )

    ema50 = ema(
        close,
        50
    )

    rsi_value = rsi(
        close,
        14
    )

    atr_value = atr(
        c,
        14
    )

    macd = (
        ema(close, 12)
        - ema(close, 26)
    )

    macd_signal = ema(
        macd,
        9
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

    current_volume = (
        c["volume"].iloc[-1]
    )

    average_volume = (
        volume_average.iloc[-1]
    )

    if (
        pd.isna(average_volume)
        or average_volume <= 0
    ):
        volume_ratio = 1.0
    else:
        volume_ratio = (
            current_volume
            / average_volume
        )

    middle_band = (
        close
        .rolling(20)
        .mean()
    )

    standard_deviation = (
        close
        .rolling(20)
        .std()
    )

    upper_band = (
        middle_band
        + 2 * standard_deviation
    )

    lower_band = (
        middle_band
        - 2 * standard_deviation
    )

    # -------------------------
    # Safety helper
    # -------------------------

    def score(value):

        return float(
            np.clip(
                value,
                5,
                95
            )
        )

    # ========================================================
    # TREND AI
    # ========================================================

    current_atr = float(
        atr_value.iloc[-1]
    )

    if (
        not np.isfinite(current_atr)
        or current_atr <= 0
    ):
        current_atr = (
            float(close.iloc[-1])
            * 0.001
        )

    trend_strength = (
        ema9.iloc[-1]
        - ema21.iloc[-1]
    ) / current_atr

    trend_score = (
        50
        + 35
        * np.tanh(
            trend_strength * 2
        )
    )

    trend_score = score(
        trend_score
    )

    # ========================================================
    # MOMENTUM AI
    # ========================================================

    rsi_component = (
        rsi_value.iloc[-1]
        - 50
    )

    roc_component = (
        roc5.iloc[-1]
        if pd.notna(roc5.iloc[-1])
        else 0
    )

    macd_component = (
        macd.iloc[-1]
        - macd_signal.iloc[-1]
    )

    momentum_score = (
        50
        + 22
        * np.tanh(
            rsi_component / 12
        )
        + 18
        * np.tanh(
            roc_component / 0.25
        )
        + 10
        * np.tanh(
            macd_component
            / max(
                abs(macd.iloc[-1]),
                1e-9
            )
        )
    )

    momentum_score = score(
        momentum_score
    )

    # ========================================================
    # VOLUME AI
    # ========================================================

    volume_score = (
        50
        + (
            buy_pressure
            - 50
        )
        * 0.8
        + 10
        * np.tanh(
            volume_ratio - 1
        )
    )

    volume_score = score(
        volume_score
    )

    # ========================================================
    # PATTERN AI
    # ========================================================

    latest_open = (
        c["open"].iloc[-1]
    )

    latest_high = (
        c["high"].iloc[-1]
    )

    latest_low = (
        c["low"].iloc[-1]
    )

    latest_close = (
        c["close"].iloc[-1]
    )

    candle_range = max(
        latest_high
        - latest_low,
        1e-9
    )

    candle_body = (
        latest_close
        - latest_open
    ) / candle_range

    latest_return = (
        latest_close
        - c["close"].iloc[-2]
    ) / c["close"].iloc[-2] * 100

    pattern_score = (
        50
        + 25
        * np.tanh(
            latest_return
            / 0.12
        )
        + 12
        * np.tanh(
            candle_body * 2
        )
    )

    pattern_score = score(
        pattern_score
    )

    # ========================================================
    # SUPPORT / RESISTANCE AI
    # ========================================================

    recent_high = (
        c["high"]
        .tail(60)
        .max()
    )

    recent_low = (
        c["low"]
        .tail(60)
        .min()
    )

    midpoint = (
        recent_high
        + recent_low
    ) / 2

    sr_score = (
        50
        + 22
        * np.tanh(
            (
                latest_close
                - midpoint
            )
            / (
                current_atr * 3
            )
        )
    )

    sr_score = score(
        sr_score
    )

    # ========================================================
    # VOLATILITY AI
    # ========================================================

    volatility_percent = (
        current_atr
        / latest_close
    ) * 100

    volatility_score = (
        55
        + 12
        * np.tanh(
            volume_ratio - 1
        )
        - 8
        * np.tanh(
            (
                volatility_percent
                - 0.12
            ) * 3
        )
    )

    volatility_score = score(
        volatility_score
    )

    # ========================================================
    # REGIME AI
    # ========================================================

    regime_strength = (
        ema9.iloc[-1]
        - ema50.iloc[-1]
    ) / current_atr

    regime_score = (
        50
        + 30
        * np.tanh(
            regime_strength
        )
    )

    regime_score = score(
        regime_score
    )

    # ========================================================
    # WHALE AI
    # ========================================================
    #
    # Binance public spot trade data does NOT provide
    # blockchain whale transfers.
    #
    # Therefore this is intentionally an independent
    # large-trade / aggressor-pressure proxy.
    #
    # It is NOT pretending to see on-chain whales.
    # ========================================================

    whale_score = (
        50
        + (
            buy_pressure
            - 50
        )
        * 0.65
    )

    whale_score = score(
        whale_score
    )

    # ========================================================
    # LIQUIDITY AI
    # ========================================================

    liquidity_score = (
        50
        + (
            buy_pressure
            - 50
        )
        * 0.9
    )

    liquidity_score = score(
        liquidity_score
    )

    # ========================================================
    # DERIVATIVES AI
    # ========================================================
    #
    # No derivatives API is used yet.
    # For now this specialist uses short-term price behavior
    # as a temporary proxy.
    # ========================================================

    derivatives_score = (
        50
        + (
            roc_component
            * 12
        )
    )

    derivatives_score = score(
        derivatives_score
    )

    # ========================================================
    # EVENT AI
    # ========================================================
    #
    # No news/event feed yet.
    # Remains neutral instead of inventing information.
    # ========================================================

    event_score = 50.0

    # ========================================================
    # HISTORICAL AI
    # ========================================================

    historical_score = (
        50
        + 20
        * np.tanh(
            roc_component
            / 0.5
        )
    )

    historical_score = score(
        historical_score
    )

    scores = {

        "Trend AI":
            trend_score,

        "Momentum AI":
            momentum_score,

        "Volume AI":
            volume_score,

        "Pattern AI":
            pattern_score,

        "S/R AI":
            sr_score,

        "Volatility AI":
            volatility_score,

        "Regime AI":
            regime_score,

        "Whale AI":
            whale_score,

        "Liquidity AI":
            liquidity_score,

        "Derivatives AI":
            derivatives_score,

        "Event AI":
            event_score,

        "Historical AI":
            historical_score
    }

    features = {

        "ema9":
            float(ema9.iloc[-1]),

        "ema21":
            float(ema21.iloc[-1]),

        "ema50":
            float(ema50.iloc[-1]),

        "rsi":
            float(rsi_value.iloc[-1]),

        "atr":
            float(current_atr),

        "volume_ratio":
            float(volume_ratio),

        "recent_high":
            float(recent_high),

        "recent_low":
            float(recent_low),

        "upper_band":
            float(upper_band.iloc[-1])
            if pd.notna(upper_band.iloc[-1])
            else float(latest_close),

        "lower_band":
            float(lower_band.iloc[-1])
            if pd.notna(lower_band.iloc[-1])
            else float(latest_close)
    }

    return scores, features


# ============================================================
# MASTER AI
# ============================================================

def master_decision(
    scores,
    features
):

    regime = scores[
        "Regime AI"
    ]

    # Start with equal weights.
    weights = {
        name: 1.0
        for name in scores
    }

    # Directional market:
    # trend/momentum/regime become more important.
    if regime >= 60:

        for name in [
            "Trend AI",
            "Momentum AI",
            "Volume AI",
            "Regime AI"
        ]:

            weights[name] = 1.35

    # Choppy market:
    # reduce trend dependence.
    elif regime <= 40:

        weights[
            "Trend AI"
        ] = 0.75

        weights[
            "Momentum AI"
        ] = 0.75

        weights[
            "Volatility AI"
        ] = 1.25

    # Whale remains independent
    # but is never allowed to decide alone.

    weights[
        "Whale AI"
    ] = 1.05

    weighted_score = (
        sum(
            scores[name]
            * weights[name]
            for name in scores
        )
        /
        sum(
            weights.values()
        )
    )

    score_values = np.array(
        list(scores.values()),
        dtype=float
    )

    disagreement = float(
        np.std(score_values)
    )

    confidence = (
        50
        + abs(
            weighted_score
            - 50
        ) * 1.55
        - disagreement * 0.22
    )

    confidence = float(
        np.clip(
            confidence,
            50,
            95
        )
    )

    if (
        weighted_score >= 58
        and confidence >= 60
    ):

        signal = "SCALP UP"

    elif (
        weighted_score <= 42
        and confidence >= 60
    ):

        signal = "SCALP DOWN"

    else:

        signal = "WAIT"

    return (
        signal,
        confidence,
        float(weighted_score),
        disagreement
    )


# ============================================================
# FORECAST
# ============================================================

def make_forecast(
    candles,
    signal,
    confidence,
    features
):

    last_price = float(
        candles["close"].iloc[-1]
    )

    current_atr = max(
        float(features["atr"]),
        last_price * 0.0005
    )

    if signal == "SCALP UP":

        direction = 1

    elif signal == "SCALP DOWN":

        direction = -1

    else:

        direction = 0

    strength = max(
        0.15,
        (
            confidence
            - 50
        ) / 45
    )

    expected = (
        last_price
        + direction
        * current_atr
        * (
            0.8
            + 1.4 * strength
        )
    )

    future_times = pd.date_range(
        start=(
            candles["time"].iloc[-1]
            + pd.Timedelta(minutes=1)
        ),
        periods=15,
        freq="1min"
    )

    path = np.linspace(
        last_price,
        expected,
        15
    )

    uncertainty = (
        current_atr
        * (
            0.45
            + 0.04
            * np.arange(15)
        )
    )

    upper = (
        path
        + uncertainty
    )

    lower = (
        path
        - uncertainty
    )

    return (
        future_times,
        path,
        upper,
        lower,
        expected
    )


# ============================================================
# RESAMPLE CANDLES
# ============================================================

def resample_candles(
    df,
    rule
):

    return (
        df
        .set_index("time")
        .resample(rule)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }
        )
        .dropna()
        .reset_index()
    )


# ============================================================
# LOAD LIVE DATA
# ============================================================

try:

    candles = get_btc_candles()

    trades = get_recent_trades()

    live_price = get_live_price()

    live_ok = True

    data_error = ""

except Exception as error:

    live_ok = False

    data_error = str(error)

    # Demo fallback only if Binance fails.

    rng = np.random.default_rng(7)

    now = pd.Timestamp.now(
        tz="UTC"
    )

    times = pd.date_range(
        end=now,
        periods=500,
        freq="1min"
    )

    price = (
        77500
        + np.cumsum(
            rng.normal(
                0,
                38,
                len(times)
            )
        )
    )

    open_prices = np.r_[
        price[0],
        price[:-1]
    ]

    high = (
        np.maximum(
            open_prices,
            price
        )
        + rng.uniform(
            3,
            28,
            len(price)
        )
    )

    low = (
        np.minimum(
            open_prices,
            price
        )
        - rng.uniform(
            3,
            28,
            len(price)
        )
    )

    volume = rng.lognormal(
        9.1,
        0.45,
        len(price)
    )

    candles = pd.DataFrame(
        {
            "time": times,
            "open": open_prices,
            "high": high,
            "low": low,
            "close": price,
            "volume": volume
        }
    )

    trades = pd.DataFrame()

    live_price = float(
        candles["close"].iloc[-1]
    )


# ============================================================
# SHORT-TERM BARS
# ============================================================

if live_ok:

    bars_1s = build_trade_bars(
        trades,
        1
    )

    bars_3s = build_trade_bars(
        trades,
        3
    )

    bars_5s = build_trade_bars(
        trades,
        5
    )

else:

    bars_1s = pd.DataFrame()

    bars_3s = pd.DataFrame()

    bars_5s = pd.DataFrame()


# ============================================================
# LIVE TRADE PRESSURE
# ============================================================

if not trades.empty:

    total_volume = (
        trades["quantity"]
        .sum()
    )

    buy_volume = (
        trades
        .loc[
            ~trades["buyer_maker"],
            "quantity"
        ]
        .sum()
    )

    sell_volume = (
        trades
        .loc[
            trades["buyer_maker"],
            "quantity"
        ]
        .sum()
    )

    if total_volume > 0:

        buy_pressure = (
            buy_volume
            / total_volume
        ) * 100

    else:

        buy_pressure = 50.0

    trade_count = len(
        trades
    )

else:

    buy_pressure = 50.0

    trade_count = 0


# ============================================================
# CALCULATE SPECIALISTS
# ============================================================

scores, features = calculate_specialists(
    candles,
    buy_pressure
)


# ============================================================
# MASTER DECISION
# ============================================================

(
    signal,
    confidence,
    master_score,
    disagreement
) = master_decision(
    scores,
    features
)


# ============================================================
# HEADER
# ============================================================

st.title(
    "₿ BTC AI Trading Command Center"
)

st.caption(
    "Live multi-agent BTC market engine • "
    "15-minute primary horizon • "
    "PAPER TRADING ONLY"
)

if live_ok:

    st.success(
        "🟢 LIVE BTC DATA — BINANCE"
    )

else:

    st.warning(
        "🟡 DEMO DATA — BINANCE CONNECTION FAILED"
    )

    st.caption(
        f"Connection error: {data_error}"
    )


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header(
        "Controls"
    )

    timeframe = st.selectbox(
        "Chart timeframe",
        TIMEFRAMES,
        index=6
    )

    mode = st.selectbox(
        "Trading mode",
        [
            "PAPER",
            "SIMULATED LIVE",
            "LIVE (LOCKED)"
        ]
    )

    refresh = st.button(
        "🔄 Refresh live data"
    )

    if refresh:

        st.cache_data.clear()

        st.rerun()

    st.divider()

    st.subheader(
        "Market Data"
    )

    st.write(
        "BTC/USDT"
    )

    st.write(
        "1-minute candles: "
        + (
            "LIVE"
            if live_ok
            else "DEMO"
        )
    )

    st.write(
        "Recent trades: "
        + (
            "LIVE"
            if live_ok
            else "DEMO"
        )
    )

    st.divider()

    st.subheader(
        "Prediction Window"
    )

    now = pd.Timestamp.now(
        tz="UTC"
    )

    seconds_into_window = (
        (now.minute % 15)
        * 60
        + now.second
    )

    elapsed = (
        seconds_into_window
        / 900
    )

    st.progress(
        float(
            np.clip(
                elapsed,
                0,
                1
            )
        ),
        text=(
            f"{elapsed * 100:.0f}% "
            "of current 15m window elapsed"
        )
    )

    st.divider()

    st.subheader(
        "Short-Term Engine"
    )

    st.write(
        "1-second bars: "
        + (
            "ACTIVE"
            if not bars_1s.empty
            else "WAITING"
        )
    )

    st.write(
        "3-second bars: "
        + (
            "ACTIVE"
            if not bars_3s.empty
            else "WAITING"
        )
    )

    st.write(
        "5-second bars: "
        + (
            "ACTIVE"
            if not bars_5s.empty
            else "WAITING"
        )
    )

    st.divider()

    st.caption(
        "No API key is required. "
        "This app cannot place trades."
    )


# ============================================================
# LIVE MODE LOCK
# ============================================================

if mode == "LIVE (LOCKED)":

    st.info(
        "🔒 LIVE trading is intentionally locked. "
        "No real orders can be placed by this app."
    )


# ============================================================
# MASTER PREDICTION
# ============================================================

st.subheader(
    "Master Prediction"
)

signal_text = (
    f"{signal} • "
    f"{confidence:.1f}% confidence"
)

if signal == "SCALP UP":

    st.success(
        f"🟢 {signal_text}"
    )

elif signal == "SCALP DOWN":

    st.error(
        f"🔴 {signal_text}"
    )

else:

    st.warning(
        f"🟡 {signal_text}"
    )


# ============================================================
# MASTER METRICS
# ============================================================

master_cols = st.columns(4)

with master_cols[0]:

    st.metric(
        "BTC Price",
        f"${live_price:,.2f}"
    )

with master_cols[1]:

    st.metric(
        "Master Bullish Score",
        f"{master_score:.1f}%"
    )

with master_cols[2]:

    st.metric(
        "Live Trade Pressure",
        f"{buy_pressure:.1f}%",
        f"{buy_pressure - 50:+.1f} pts"
    )

with master_cols[3]:

    st.metric(
        "AI Disagreement",
        f"{disagreement:.1f} pts"
    )


st.caption(
    "Scores are calculated from current market features. "
    "They are not trained-model probabilities and do not "
    "guarantee future price movement."
)


# ============================================================
# TRADE PLAN
# ============================================================

st.subheader(
    "Trade Plan — Paper Only"
)

entry_low = (
    live_price
    - features["atr"] * 0.20
)

entry_high = (
    live_price
    + features["atr"] * 0.20
)

if signal == "SCALP UP":

    target = (
        live_price
        + features["atr"] * 1.4
    )

    invalidation = (
        live_price
        - features["atr"] * 0.8
    )

elif signal == "SCALP DOWN":

    target = (
        live_price
        - features["atr"] * 1.4
    )

    invalidation = (
        live_price
        + features["atr"] * 0.8
    )

else:

    target = None

    invalidation = None


plan_cols = st.columns(4)

with plan_cols[0]:

    st.metric(
        "Entry Zone",
        (
            f"${entry_low:,.0f}"
            f"–"
            f"${entry_high:,.0f}"
        )
    )

with plan_cols[1]:

    st.metric(
        "Target",
        (
            f"${target:,.0f}"
            if target is not None
            else "—"
        )
    )

with plan_cols[2]:

    st.metric(
        "Invalidation",
        (
            f"${invalidation:,.0f}"
            if invalidation is not None
            else "—"
        )
    )

with plan_cols[3]:

    st.metric(
        "ATR (1m)",
        f"${features['atr']:,.2f}"
    )


# ============================================================
# SHORT-TERM MARKET ENGINE
# ============================================================

st.subheader(
    "Short-Term BTC Market Engine"
)

short_cols = st.columns(4)

with short_cols[0]:

    st.metric(
        "Recent Trades",
        f"{trade_count:,}"
    )

with short_cols[1]:

    st.metric(
        "Buy Pressure",
        f"{buy_pressure:.1f}%"
    )

with short_cols[2]:

    st.metric(
        "Sell Pressure",
        f"{100 - buy_pressure:.1f}%"
    )

with short_cols[3]:

    st.metric(
        "Data Feed",
        "LIVE"
        if live_ok
        else "DEMO"
    )


# ============================================================
# MARKET CHART DATA
# ============================================================

if timeframe == "1 second":

    chart_df = (
        bars_1s.tail(180)
    )

elif timeframe == "3 seconds":

    chart_df = (
        bars_3s.tail(180)
    )

elif timeframe == "5 seconds":

    chart_df = (
        bars_5s.tail(180)
    )

elif timeframe == "1 minute":

    chart_df = (
        candles.tail(240)
    )

elif timeframe == "3 minutes":

    chart_df = (
        resample_candles(
            candles,
            "3min"
        )
        .tail(160)
    )

elif timeframe == "5 minutes":

    chart_df = (
        resample_candles(
            candles,
            "5min"
        )
        .tail(120)
    )

else:

    chart_df = (
        resample_candles(
            candles,
            "15min"
        )
        .tail(80)
    )


# ============================================================
# MARKET CHART
# ============================================================

st.subheader(
    f"BTC Market Chart — {timeframe}"
)

if chart_df.empty:

    st.info(
        "Waiting for enough recent Binance "
        "trade data to build this timeframe."
    )

else:

    chart = go.Figure()

    chart.add_trace(
        go.Candlestick(
            x=chart_df["time"],
            open=chart_df["open"],
            high=chart_df["high"],
            low=chart_df["low"],
            close=chart_df["close"],
            name="BTC"
        )
    )

    chart.update_layout(
        height=450,
        margin=dict(
            l=10,
            r=10,
            t=10,
            b=10
        ),
        xaxis_rangeslider_visible=False
    )

    st.plotly_chart(
        chart,
        use_container_width=True
    )


# ============================================================
# 15-MINUTE PREDICTION
# ============================================================

st.subheader(
    "15-Minute AI Prediction"
)

recent = candles.tail(
    120
)

(
    future,
    forecast,
    upper,
    lower,
    expected
) = make_forecast(
    candles,
    signal,
    confidence,
    features
)

prediction_fig = go.Figure()

prediction_fig.add_trace(
    go.Candlestick(
        x=recent["time"],
        open=recent["open"],
        high=recent["high"],
        low=recent["low"],
        close=recent["close"],
        name="BTC"
    )
)

prediction_fig.add_trace(
    go.Scatter(
        x=future,
        y=forecast,
        mode="lines",
        name="Live feature forecast",
        line=dict(
            width=3
        )
    )
)

prediction_fig.add_trace(
    go.Scatter(
        x=(
            list(future)
            + list(future[::-1])
        ),
        y=(
            list(upper)
            + list(lower[::-1])
        ),
        fill="toself",
        line=dict(
            width=0
        ),
        name="Uncertainty band",
        opacity=0.18
    )
)

prediction_fig.add_trace(
    go.Scatter(
        x=[future[-1]],
        y=[expected],
        mode="markers",
        name="15m endpoint",
        marker=dict(
            size=10
        )
    )
)

prediction_fig.update_layout(
    height=450,
    margin=dict(
        l=10,
        r=10,
        t=10,
        b=10
    ),
    xaxis_rangeslider_visible=False
)

st.plotly_chart(
    prediction_fig,
    use_container_width=True
)


# ============================================================
# WHALE AI
# ============================================================

st.subheader(
    "🐋 Whale AI — Independent Indicator"
)

whale_score = scores[
    "Whale AI"
]

whale_cols = st.columns(2)

with whale_cols[0]:

    st.metric(
        "Whale Bullish Pressure",
        f"{whale_score:.1f}%"
    )

with whale_cols[1]:

    st.metric(
        "Whale Bearish Pressure",
        f"{100 - whale_score:.1f}%"
    )

st.progress(
    whale_score / 100
)

st.caption(
    "Important: free Binance public spot data does not "
    "contain blockchain whale-transfer information. "
    "This independent Whale AI currently uses large-trade "
    "and aggressor-pressure information as a proxy. "
    "It does not claim to see on-chain whale transfers."
)

st.caption(
    "A future on-chain data adapter can be connected to "
    "this specialist without changing the master architecture."
)


# ============================================================
# SPECIALIST AI NETWORK
# ============================================================

st.subheader(
    "Specialist AI Network"
)

specialist_descriptions = {

    "Trend AI":
        "EMA structure + price trend",

    "Momentum AI":
        "RSI + ROC + MACD",

    "Volume AI":
        "Volume expansion + trade pressure",

    "Pattern AI":
        "Recent candle behavior",

    "S/R AI":
        "Recent support/resistance",

    "Volatility AI":
        "ATR + volatility regime",

    "Regime AI":
        "Directional vs non-directional regime",

    "Whale AI":
        "Independent large-trade pressure proxy",

    "Liquidity AI":
        "Aggressor-side trade imbalance",

    "Derivatives AI":
        "Short-term price/momentum proxy",

    "Event AI":
        "Neutral until verified event feed",

    "Historical AI":
        "Recent return-pattern proxy"
}


grid = st.columns(3)

for i, (
    name,
    score_value
) in enumerate(
    scores.items()
):

    with grid[
        i % 3
    ]:

        if score_value >= 55:

            direction = "UP"

        elif score_value <= 45:

            direction = "DOWN"

        else:

            direction = "MIXED"

        st.metric(
            name,
            (
                f"{direction} • "
                f"{score_value:.1f}%"
            ),
            specialist_descriptions[
                name
            ]
        )


# ============================================================
# AI COMBINATION LAYER
# ============================================================

st.subheader(
    "AI Communication & Combination Layer"
)

combinations = [

    (
        "Trend + Momentum + Regime",

        np.mean(
            [
                scores["Trend AI"],
                scores["Momentum AI"],
                scores["Regime AI"]
            ]
        ),

        "Directional structure"
    ),

    (
        "Volume + Liquidity + Whale",

        np.mean(
            [
                scores["Volume AI"],
                scores["Liquidity AI"],
                scores["Whale AI"]
            ]
        ),

        "Aggressor-side pressure"
    ),

    (
        "S/R + Volatility",

        np.mean(
            [
                scores["S/R AI"],
                scores["Volatility AI"]
            ]
        ),

        "Location + risk"
    ),

    (
        "Historical + Pattern",

        np.mean(
            [
                scores["Historical AI"],
                scores["Pattern AI"]
            ]
        ),

        "Recent setup similarity"
    )
]


interaction_rows = []

for (
    combination_name,
    combination_score,
    comment
) in combinations:

    if combination_score >= 58:

        combination_signal = "UP"

    elif combination_score <= 42:

        combination_signal = "DOWN"

    else:

        combination_signal = "WAIT"

    interaction_rows.append(
        [
            combination_name,
            combination_signal,
            round(
                combination_score,
                1
            ),
            comment
        ]
    )


interaction = pd.DataFrame(
    interaction_rows,
    columns=[
        "Combination",
        "Signal",
        "Score",
        "Comment"
    ]
)

st.dataframe(
    interaction,
    use_container_width=True,
    hide_index=True
)


# ============================================================
# MASTER AI EXPLANATION
# ============================================================

st.subheader(
    "Why the Master AI Chose This"
)

dominant_specialists = sorted(
    scores.items(),
    key=lambda item:
        abs(
            item[1] - 50
        ),
    reverse=True
)[:4]


reason_lines = [
    (
        f"• {name}: "
        f"{score_value:.1f}%"
    )
    for name, score_value
    in dominant_specialists
]


explanation = (
    f"Master bullish score: "
    f"{master_score:.1f}%\n\n"

    f"Confidence: "
    f"{confidence:.1f}%\n\n"

    f"AI disagreement: "
    f"{disagreement:.1f} points\n\n"

    + "\n".join(
        reason_lines
    )

    + "\n\n"

    "The master layer gives more weight to "
    "directional specialists when the market "
    "appears directional. It reduces confidence "
    "when the specialists disagree. Whale AI "
    "remains independent and cannot decide the "
    "master signal by itself."
)

st.info(
    explanation
)


# ============================================================
# LIVE FEATURES
# ============================================================

st.subheader(
    "Live Feature Snapshot"
)

feature_cols = st.columns(4)

with feature_cols[0]:

    st.metric(
        "RSI",
        f"{features['rsi']:.1f}"
    )

with feature_cols[1]:

    st.metric(
        "EMA 9",
        f"${features['ema9']:,.2f}"
    )

with feature_cols[2]:

    st.metric(
        "EMA 21",
        f"${features['ema21']:,.2f}"
    )

with feature_cols[3]:

    st.metric(
        "Volume Ratio",
        f"{features['volume_ratio']:.2f}x"
    )


# ============================================================
# MODEL PERFORMANCE
# ============================================================

st.subheader(
    "Model Performance"
)

performance_cols = st.columns(4)

with performance_cols[0]:

    st.metric(
        "Model Win Rate",
        "—",
        "Needs scored predictions"
    )

with performance_cols[1]:

    st.metric(
        "Profit Factor",
        "—",
        "Needs backtesting"
    )

with performance_cols[2]:

    st.metric(
        "Max Drawdown",
        "—",
        "Needs paper trading"
    )

with performance_cols[3]:

    st.metric(
        "Calibration",
        "—",
        "Needs scored predictions"
    )


# ============================================================
# SYSTEM STATUS
# ============================================================

st.subheader(
    "System Status"
)

status_cols = st.columns(4)

with status_cols[0]:

    if live_ok:

        st.success(
            "BTC DATA — LIVE"
        )

    else:

        st.warning(
            "BTC DATA — DEMO"
        )


with status_cols[1]:

    if not bars_1s.empty:

        st.success(
            "1s / 3s / 5s ENGINE"
        )

    else:

        st.warning(
            "SHORT DATA — WAITING"
        )


with status_cols[2]:

    st.warning(
        "SPECIALIST ENGINE — LIVE FEATURES"
    )


with status_cols[3]:

    st.info(
        "TRADING — PAPER ONLY"
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Last data refresh: "
    + datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
)

st.caption(
    "⚠️ Educational/paper-trading prototype. "
    "Not financial advice. "
    "No real trades are placed. "
    "Live trading is locked."
)