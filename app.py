import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json
from datetime import datetime

# ============================================================
# BTC AI TRADING COMMAND CENTER
# LIVE BINANCE DATA + REAL FEATURE-BASED SIGNAL ENGINE
# PAPER TRADING ONLY
# ============================================================

st.set_page_config(
    page_title="BTC AI Command Center",
    page_icon="₿",
    layout="wide"
)

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


def get_btc_candles():
    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": 500
        }
    )

    if not data:
        raise ValueError("No candle data returned.")

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


def get_recent_trades():
    data = binance_get(
        "/api/v3/aggTrades",
        {
            "symbol": "BTCUSDT",
            "limit": 1000
        }
    )

    if not data:
        raise ValueError("No trade data returned.")

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
            "buyer_maker": bool(trade["m"])
        })

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(50)


def add_indicators(df):
    data = df.copy()

    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    # EMA
    data["ema_fast"] = close.ewm(
        span=9,
        adjust=False
    ).mean()

    data["ema_mid"] = close.ewm(
        span=21,
        adjust=False
    ).mean()

    data["ema_slow"] = close.ewm(
        span=50,
        adjust=False
    ).mean()

    # RSI
    data["rsi"] = calculate_rsi(
        close,
        14
    )

    # MACD
    ema12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    data["macd"] = ema12 - ema26

    data["macd_signal"] = data["macd"].ewm(
        span=9,
        adjust=False
    ).mean()

    data["macd_hist"] = (
        data["macd"]
        - data["macd_signal"]
    )

    # True range / ATR
    previous_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - previous_close).abs()
    tr3 = (low - previous_close).abs()

    true_range = pd.concat(
        [tr1, tr2, tr3],
        axis=1
    ).max(axis=1)

    data["atr"] = true_range.rolling(
        14
    ).mean()

    # Bollinger Bands
    data["bb_mid"] = close.rolling(
        20
    ).mean()

    bb_std = close.rolling(
        20
    ).std()

    data["bb_upper"] = (
        data["bb_mid"]
        + 2 * bb_std
    )

    data["bb_lower"] = (
        data["bb_mid"]
        - 2 * bb_std
    )

    # Returns
    data["return_1"] = close.pct_change(1)
    data["return_5"] = close.pct_change(5)
    data["return_15"] = close.pct_change(15)

    # Volume statistics
    data["volume_avg"] = volume.rolling(
        20
    ).mean()

    data["volume_ratio"] = (
        volume
        / data["volume_avg"].replace(0, np.nan)
    )

    # Recent volatility
    data["volatility"] = (
        data["return_1"]
        .rolling(20)
        .std()
    )

    # Rolling support / resistance
    data["support"] = low.rolling(
        30
    ).min()

    data["resistance"] = high.rolling(
        30
    ).max()

    return data


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

    bars = temp["price"].resample(
        rule
    ).ohlc()

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
# TRADE PRESSURE
# ============================================================

def calculate_trade_pressure(trades):

    if trades.empty:
        return 50.0, 50.0, 0

    total = trades["quantity"].sum()

    if total <= 0:
        return 50.0, 50.0, len(trades)

    buy = trades.loc[
        ~trades["buyer_maker"],
        "quantity"
    ].sum()

    buy_pct = (
        buy / total
    ) * 100

    sell_pct = 100 - buy_pct

    return buy_pct, sell_pct, len(trades)


# ============================================================
# LARGE TRADE / WHALE PROXY
# ============================================================

def calculate_large_trade_pressure(trades):

    if trades.empty:
        return 50.0

    temp = trades.copy()

    temp["notional"] = (
        temp["price"]
        * temp["quantity"]
    )

    threshold = temp["notional"].quantile(
        0.90
    )

    large = temp[
        temp["notional"] >= threshold
    ].copy()

    if large.empty:
        return 50.0

    buy = large.loc[
        ~large["buyer_maker"],
        "quantity"
    ].sum()

    sell = large.loc[
        large["buyer_maker"],
        "quantity"
    ].sum()

    total = buy + sell

    if total <= 0:
        return 50.0

    return (
        buy / total
    ) * 100


# ============================================================
# SPECIALIST SIGNAL FUNCTIONS
# ============================================================

def clamp(value, low=5, high=95):
    return float(
        np.clip(value, low, high)
    )


def trend_signal(df):

    row = df.iloc[-1]

    score = 50

    if row["ema_fast"] > row["ema_mid"]:
        score += 15
    else:
        score -= 15

    if row["ema_mid"] > row["ema_slow"]:
        score += 15
    else:
        score -= 15

    if row["close"] > row["ema_fast"]:
        score += 10
    else:
        score -= 10

    return clamp(score)


def momentum_signal(df):

    row = df.iloc[-1]

    score = 50

    rsi = row["rsi"]

    if 50 <= rsi <= 68:
        score += 18
    elif rsi > 72:
        score -= 8
    elif rsi < 40:
        score -= 18
    else:
        score += 3

    if row["macd_hist"] > 0:
        score += 15
    else:
        score -= 15

    if row["return_5"] > 0:
        score += 10
    else:
        score -= 10

    return clamp(score)


def volume_signal(df):

    row = df.iloc[-1]

    score = 50

    ratio = row["volume_ratio"]

    if ratio > 1.25:
        score += 10

    if row["close"] > row["open"]:
        score += 18
    else:
        score -= 18

    if row["return_5"] > 0:
        score += 10
    else:
        score -= 10

    return clamp(score)


def pattern_signal(df):

    row = df.iloc[-1]

    candle_range = max(
        row["high"] - row["low"],
        0.000001
    )

    body = abs(
        row["close"] - row["open"]
    )

    body_ratio = body / candle_range

    score = 50

    if row["close"] > row["open"]:
        score += 12
    else:
        score -= 12

    if body_ratio > 0.55:
        score += 10 if row["close"] > row["open"] else -10

    return clamp(score)


def support_resistance_signal(df):

    row = df.iloc[-1]

    price = row["close"]
    support = row["support"]
    resistance = row["resistance"]

    if pd.isna(support) or pd.isna(resistance):
        return 50

    score = 50

    support_distance = (
        price - support
    ) / price * 100

    resistance_distance = (
        resistance - price
    ) / price * 100

    if support_distance < 0.25:
        score += 18

    if resistance_distance < 0.20:
        score -= 18

    if price > row["ema_fast"]:
        score += 8

    return clamp(score)


def volatility_signal(df):

    row = df.iloc[-1]

    score = 50

    if pd.isna(row["atr"]):
        return score

    atr_pct = (
        row["atr"]
        / row["close"]
    ) * 100

    if atr_pct < 0.35:
        score += 5
    elif atr_pct > 1.0:
        score -= 5

    if (
        row["close"] > row["bb_mid"]
        and row["close"] < row["bb_upper"]
    ):
        score += 10

    return clamp(score)


def regime_signal(df):

    row = df.iloc[-1]

    if pd.isna(row["volatility"]):
        return 50

    trend_strength = abs(
        row["ema_fast"]
        - row["ema_slow"]
    ) / row["close"] * 100

    score = 50

    if trend_strength > 0.20:
        if row["ema_fast"] > row["ema_slow"]:
            score += 20
        else:
            score -= 20

    if trend_strength > 0.50:
        score += 8 if row["ema_fast"] > row["ema_slow"] else -8

    return clamp(score)


def whale_signal(large_trade_pressure):

    # This is NOT an on-chain whale feed.
    # It is a large-trade proxy from Binance aggTrades.

    return clamp(
        large_trade_pressure
    )


def liquidity_signal(buy_pressure):

    score = 50

    if buy_pressure > 55:
        score += 20
    elif buy_pressure < 45:
        score -= 20

    return clamp(score)


def derivatives_signal(df):

    # Binance public spot endpoint does not provide
    # the full derivatives stack here.
    # We use momentum/volatility as a temporary proxy.

    row = df.iloc[-1]

    score = 50

    if row["return_15"] > 0:
        score += 15
    else:
        score -= 15

    if row["volatility"] < 0.008:
        score += 5

    return clamp(score)


def event_signal():

    # No news/event API connected yet.
    # Neutral is safer than inventing an event signal.

    return 50.0


def historical_signal(df):

    # Simple historical analogue:
    # compare current short-term return direction
    # with recent observations.

    if len(df) < 60:
        return 50.0

    returns = df["return_5"].dropna()

    current = returns.iloc[-1]

    recent = returns.iloc[-51:-1]

    if recent.empty:
        return 50.0

    if current > 0:
        similar = recent[recent > 0]
    else:
        similar = recent[recent < 0]

    if len(recent) == 0:
        return 50.0

    probability = (
        len(similar)
        / len(recent)
    ) * 100

    return clamp(probability)


# ============================================================
# MASTER COMBINATION ENGINE
# ============================================================

def calculate_master(
    signals,
    buy_pressure,
    large_trade_pressure
):

    # Weighted combination.
    # These are feature weights, NOT trained model weights.
    weights = {
        "Trend AI": 1.25,
        "Momentum AI": 1.15,
        "Volume AI": 1.10,
        "Pattern AI": 0.75,
        "S/R AI": 0.90,
        "Volatility AI": 0.75,
        "Regime AI": 1.15,
        "Whale AI": 0.95,
        "Liquidity AI": 0.90,
        "Derivatives AI": 0.70,
        "Event AI": 0.45,
        "Historical AI": 0.85
    }

    weighted_total = 0
    weight_total = 0

    for name, score in signals.items():

        weight = weights.get(
            name,
            1.0
        )

        weighted_total += (
            score * weight
        )

        weight_total += weight

    probability = (
        weighted_total
        / weight_total
    )

    # Additional live trade-pressure adjustment
    pressure_adjustment = (
        buy_pressure - 50
    ) * 0.12

    whale_adjustment = (
        large_trade_pressure - 50
    ) * 0.08

    probability += (
        pressure_adjustment
        + whale_adjustment
    )

    probability = clamp(
        probability,
        5,
        95
    )

    if probability >= 62:
        direction = "SCALP UP"

    elif probability <= 38:
        direction = "SCALP DOWN"

    else:
        direction = "WAIT"

    # Confidence should reflect distance from neutral.
    confidence = 50 + (
        abs(probability - 50)
        * 1.35
    )

    confidence = clamp(
        confidence,
        50,
        95
    )

    return direction, probability, confidence


# ============================================================
# LOAD DATA
# ============================================================

try:

    candles = get_btc_candles()
    trades = get_recent_trades()

    live_ok = True
    data_error = ""

except Exception as e:

    live_ok = False
    data_error = str(e)

    candles = pd.DataFrame()
    trades = pd.DataFrame()


if not live_ok:

    st.error(
        "Binance live data could not be loaded."
    )

    st.write(
        "The app will not invent a live signal."
    )

    st.caption(
        f"Connection error: {data_error}"
    )

    st.stop()


# ============================================================
# DATA PROCESSING
# ============================================================

candles = add_indicators(
    candles
)

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

buy_pressure, sell_pressure, trade_count = (
    calculate_trade_pressure(trades)
)

large_trade_pressure = (
    calculate_large_trade_pressure(trades)
)


# ============================================================
# SPECIALIST AIs
# ============================================================

signals = {
    "Trend AI": trend_signal(candles),
    "Momentum AI": momentum_signal(candles),
    "Volume AI": volume_signal(candles),
    "Pattern AI": pattern_signal(candles),
    "S/R AI": support_resistance_signal(candles),
    "Volatility AI": volatility_signal(candles),
    "Regime AI": regime_signal(candles),
    "Whale AI": whale_signal(large_trade_pressure),
    "Liquidity AI": liquidity_signal(buy_pressure),
    "Derivatives AI": derivatives_signal(candles),
    "Event AI": event_signal(),
    "Historical AI": historical_signal(candles)
}


master_signal, master_probability, master_confidence = (
    calculate_master(
        signals,
        buy_pressure,
        large_trade_pressure
    )
)


# ============================================================
# PRICE / TARGET LEVELS
# ============================================================

last_price = float(
    candles["close"].iloc[-1]
)

previous_price = float(
    candles["close"].iloc[-2]
)

price_change_pct = (
    (
        last_price
        - previous_price
    )
    / previous_price
) * 100

atr = candles["atr"].iloc[-1]

if pd.isna(atr):
    atr = last_price * 0.004

if master_signal == "SCALP UP":

    entry_low = last_price - (
        atr * 0.25
    )

    entry_high = last_price + (
        atr * 0.10
    )

    target = last_price + (
        atr * 1.20
    )

    invalidation = last_price - (
        atr * 0.75
    )

elif master_signal == "SCALP DOWN":

    entry_low = last_price - (
        atr * 0.10
    )

    entry_high = last_price + (
        atr * 0.25
    )

    target = last_price - (
        atr * 1.20
    )

    invalidation = last_price + (
        atr * 0.75
    )

else:

    entry_low = last_price - (
        atr * 0.20
    )

    entry_high = last_price + (
        atr * 0.20
    )

    target = last_price

    invalidation = last_price


# ============================================================
# HEADER
# ============================================================

st.title(
    "₿ BTC AI Trading Command Center"
)

st.caption(
    "Live multi-agent BTC market engine • "
    "15-minute primary horizon • PAPER MODE"
)

st.success(
    "🟢 LIVE BTC DATA — BINANCE"
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.header("Controls")

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

    st.divider()

    st.subheader("Market Data")

    st.success(
        "Binance connected"
    )

    st.write(
        "BTC / USDT"
    )

    st.write(
        "500 × 1-minute candles"
    )

    st.write(
        f"{trade_count:,} recent trades"
    )

    st.divider()

    st.subheader(
        "Prediction Window"
    )

    st.write(
        "Next 15-minute BTC window"
    )

    st.info(
        "Primary prediction horizon: 15 minutes"
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

    st.warning(
        "REAL TRADING IS LOCKED"
    )


# ============================================================
# MASTER PREDICTION
# ============================================================

st.subheader(
    "Master Prediction"
)

master_cols = st.columns(4)

with master_cols[0]:

    st.markdown(
        "### MASTER SIGNAL"
    )

    if master_signal == "SCALP UP":
        st.success(
            f"# {master_signal}"
        )

    elif master_signal == "SCALP DOWN":
        st.error(
            f"# {master_signal}"
        )

    else:
        st.warning(
            f"# {master_signal}"
        )

    st.write(
        f"Confidence: **{master_confidence:.1f}%**"
    )

with master_cols[1]:

    st.metric(
        "BTC Price",
        f"${last_price:,.2f}",
        f"{price_change_pct:+.3f}%"
    )

with master_cols[2]:

    pressure_label = (
        "BUYING"
        if buy_pressure >= 55
        else "SELLING"
        if buy_pressure <= 45
        else "BALANCED"
    )

    st.metric(
        "Live Trade Pressure",
        pressure_label,
        f"{buy_pressure:.1f}% buy"
    )

with master_cols[3]:

    st.metric(
        "15m Probability",
        f"{master_probability:.1f}%",
        master_signal
    )


# ============================================================
# TRADE PLAN
# ============================================================

st.subheader(
    "15-Minute Paper Trade Plan"
)

plan_cols = st.columns(4)

with plan_cols[0]:

    st.metric(
        "Entry Zone",
        f"${entry_low:,.0f}–${entry_high:,.0f}"
    )

with plan_cols[1]:

    st.metric(
        "Target",
        f"${target:,.2f}"
    )

with plan_cols[2]:

    st.metric(
        "Invalidation",
        f"${invalidation:,.2f}"
    )

with plan_cols[3]:

    if master_signal == "WAIT":
        rr_text = "N/A"
    else:
        risk = abs(
            last_price - invalidation
        )

        reward = abs(
            target - last_price
        )

        rr = (
            reward / risk
            if risk > 0
            else 0
        )

        rr_text = f"{rr:.2f} : 1"

    st.metric(
        "Risk / Reward",
        rr_text
    )


st.caption(
    "These levels are algorithmic paper-trading levels "
    "based on current price and ATR. They are not guarantees."
)


# ============================================================
# LIVE MARKET ENGINE
# ============================================================

st.subheader(
    "Live BTC Market Engine"
)

engine_cols = st.columns(5)

with engine_cols[0]:

    st.metric(
        "Recent Trades",
        f"{trade_count:,}"
    )

with engine_cols[1]:

    st.metric(
        "Buy Pressure",
        f"{buy_pressure:.1f}%"
    )

with engine_cols[2]:

    st.metric(
        "Sell Pressure",
        f"{sell_pressure:.1f}%"
    )

with engine_cols[3]:

    st.metric(
        "Large Trade Bias",
        f"{large_trade_pressure:.1f}% buy"
    )

with engine_cols[4]:

    st.metric(
        "RSI",
        f"{candles['rsi'].iloc[-1]:.1f}"
    )


# ============================================================
# CHART DATA
# ============================================================

if timeframe == "1 second":

    chart_df = bars_1s.tail(150)

elif timeframe == "3 seconds":

    chart_df = bars_3s.tail(150)

elif timeframe == "5 seconds":

    chart_df = bars_5s.tail(150)

else:

    chart_df = candles.copy()

    if timeframe == "3 minutes":

        chart_df = (
            chart_df
            .set_index("time")
            .resample("3min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
            .dropna()
            .reset_index()
        )

    elif timeframe == "5 minutes":

        chart_df = (
            chart_df
            .set_index("time")
            .resample("5min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
            .dropna()
            .reset_index()
        )

    elif timeframe == "15 minutes":

        chart_df = (
            chart_df
            .set_index("time")
            .resample("15min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            })
            .dropna()
            .reset_index()
        )


# ============================================================
# MARKET CHART
# ============================================================

st.subheader(
    f"BTC Market Chart — {timeframe}"
)

if chart_df.empty:

    st.info(
        "Waiting for enough Binance trade data."
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
    "15-Minute AI Projection"
)

recent = candles.tail(90)

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

prediction_last = float(
    recent["close"].iloc[-1]
)

future_t = pd.date_range(
    start=(
        recent["time"].iloc[-1]
        + pd.Timedelta(minutes=1)
    ),
    periods=15,
    freq="1min"
)

# Projection is based on current signal probability,
# momentum and ATR rather than a hard-coded 0.42%.

direction_factor = (
    1
    if master_signal == "SCALP UP"
    else -1
    if master_signal == "SCALP DOWN"
    else 0
)

move_fraction = (
    abs(
        master_probability - 50
    ) / 50
)

projected_move = (
    prediction_last
    * 0.004
    * move_fraction
    * direction_factor
)

forecast = (
    prediction_last
    + np.linspace(
        0,
        projected_move,
        15
    )
)

band_size = (
    prediction_last
    * (
        0.0015
        + (
            0.0025
            * (
                1
                - master_confidence / 100
            )
        )
    )
)

upper = forecast + band_size
lower = forecast - band_size

prediction_fig.add_trace(
    go.Scatter(
        x=future_t,
        y=forecast,
        mode="lines",
        name="Model projected path",
        line=dict(width=3)
    )
)

prediction_fig.add_trace(
    go.Scatter(
        x=(
            list(future_t)
            + list(future_t[::-1])
        ),
        y=(
            list(upper)
            + list(lower[::-1])
        ),
        fill="toself",
        line=dict(width=0),
        name="Model uncertainty band",
        opacity=0.18
    )
)

prediction_fig.add_hline(
    y=target,
    line_dash="dash",
    annotation_text="Target"
)

if master_signal != "WAIT":

    prediction_fig.add_hline(
        y=invalidation,
        line_dash="dot",
        annotation_text="Invalidation"
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
    "🐋 Whale / Large-Trade AI — Independent Indicator"
)

whale_cols = st.columns(3)

with whale_cols[0]:

    if large_trade_pressure >= 55:

        st.success(
            f"BULLISH — {large_trade_pressure:.1f}%"
        )

    elif large_trade_pressure <= 45:

        st.error(
            f"BEARISH — {large_trade_pressure:.1f}%"
        )

    else:

        st.warning(
            f"NEUTRAL — {large_trade_pressure:.1f}%"
        )

with whale_cols[1]:

    st.metric(
        "Large Trade Buy %",
        f"{large_trade_pressure:.1f}%"
    )

with whale_cols[2]:

    st.metric(
        "Large Trade Sell %",
        f"{100 - large_trade_pressure:.1f}%"
    )


st.caption(
    "This is currently a Binance large-trade proxy, not a true "
    "on-chain whale-flow feed. A large trade is not automatically "
    "bullish or bearish. A future on-chain whale provider can be "
    "added as a separate data source."
)


# ============================================================
# SPECIALIST AI NETWORK
# ============================================================

st.subheader(
    "Specialist AI Network"
)

grid = st.columns(3)

descriptions = {
    "Trend AI":
        "EMA structure + market direction",

    "Momentum AI":
        "RSI + MACD + short-term returns",

    "Volume AI":
        "Volume expansion + candle pressure",

    "Pattern AI":
        "Candle structure",

    "S/R AI":
        "Rolling support + resistance",

    "Volatility AI":
        "ATR + Bollinger conditions",

    "Regime AI":
        "Trend/chop regime detection",

    "Whale AI":
        "Large Binance trade pressure",

    "Liquidity AI":
        "Aggressive buy/sell pressure proxy",

    "Derivatives AI":
        "Temporary market proxy until derivatives feed",

    "Event AI":
        "Neutral until event/news feed connected",

    "Historical AI":
        "Recent historical analogue"
}

for i, (name, score) in enumerate(
    signals.items()
):

    with grid[i % 3]:

        if score >= 60:
            direction = "UP"
        elif score <= 40:
            direction = "DOWN"
        else:
            direction = "NEUTRAL"

        st.metric(
            name,
            f"{direction} • {score:.1f}%"
        )

        st.caption(
            descriptions[name]
        )


# ============================================================
# AI COMMUNICATION / COMBINATIONS
# ============================================================

st.subheader(
    "AI Communication & Combination Layer"
)

combination_rows = [
    [
        "Trend + Momentum",
        (
            signals["Trend AI"]
            + signals["Momentum AI"]
        ) / 2
    ],

    [
        "Trend + Volume + Whale",
        (
            signals["Trend AI"]
            + signals["Volume AI"]
            + signals["Whale AI"]
        ) / 3
    ],

    [
        "Momentum + S/R",
        (
            signals["Momentum AI"]
            + signals["S/R AI"]
        ) / 2
    ],

    [
        "Regime + Historical",
        (
            signals["Regime AI"]
            + signals["Historical AI"]
        ) / 2
    ],

    [
        "Liquidity + Volume",
        (
            signals["Liquidity AI"]
            + signals["Volume AI"]
        ) / 2
    ]
]

combination_rows = [
    [
        name,
        (
            "UP"
            if score >= 60
            else "DOWN"
            if score <= 40
            else "WAIT"
        ),
        f"{score:.1f}%",
        "Feature combination"
    ]
    for name, score in combination_rows
]

interaction = pd.DataFrame(
    combination_rows,
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
# WHY MASTER AI CHOSE IT
# ============================================================

st.subheader(
    "Why the Master Engine Chose This"
)

supporting = sorted(
    signals.items(),
    key=lambda x: x[1],
    reverse=True
)

strongest = supporting[:5]

weakest = supporting[-3:]

strongest_text = ", ".join(
    [
        f"{name} ({score:.1f}%)"
        for name, score in strongest
    ]
)

weakest_text = ", ".join(
    [
        f"{name} ({score:.1f}%)"
        for name, score in weakest
    ]
)

st.info(
    f"""
**Current signal:** {master_signal}

**Master probability:** {master_probability:.1f}%

**Confidence:** {master_confidence:.1f}%

Strongest specialists:
{strongest_text}

Lowest-scoring specialists:
{weakest_text}

The master engine combines the independent specialist outputs
with live Binance trade pressure. This is a feature-based
prototype, not a trained machine-learning model yet.

The next stage is walk-forward training, prediction logging,
calibration, and historical out-of-sample testing.
"""
)


# ============================================================
# PERFORMANCE
# ============================================================

st.subheader(
    "Model Performance"
)

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "Win Rate",
    "—",
    "Needs scored predictions"
)

m2.metric(
    "Profit Factor",
    "—",
    "Needs backtesting"
)

m3.metric(
    "Max Drawdown",
    "—",
    "Needs paper trades"
)

m4.metric(
    "Calibration",
    "—",
    "Needs prediction journal"
)


# ============================================================
# SYSTEM STATUS
# ============================================================

st.subheader(
    "System Status"
)

status_cols = st.columns(4)

with status_cols[0]:
    st.success(
        "BTC DATA — LIVE"
    )

with status_cols[1]:
    st.success(
        "1s / 3s / 5s ENGINE"
    )

with status_cols[2]:
    st.success(
        "FEATURE ENGINE — ACTIVE"
    )

with status_cols[3]:
    st.info(
        "TRADING — PAPER ONLY"
    )


# ============================================================
# DATA DETAILS
# ============================================================

st.subheader(
    "Data & Model Details"
)

detail_cols = st.columns(3)

with detail_cols[0]:

    st.write(
        "**Live market data**"
    )

    st.write(
        "• BTC/USDT candles"
    )

    st.write(
        "• Binance aggregated trades"
    )

    st.write(
        "• Buy/sell pressure"
    )

with detail_cols[1]:

    st.write(
        "**Calculated features**"
    )

    st.write(
        "• EMA 9 / 21 / 50"
    )

    st.write(
        "• RSI / MACD"
    )

    st.write(
        "• ATR / Bollinger Bands"
    )

    st.write(
        "• Volume / volatility"
    )

with detail_cols[2]:

    st.write(
        "**Not connected yet**"
    )

    st.write(
        "• True on-chain whale data"
    )

    st.write(
        "• Full derivatives data"
    )

    st.write(
        "• News/event feed"
    )

    st.write(
        "• Trained ML models"
    )


# ============================================================
# REFRESH
# ============================================================

st.divider()

st.caption(
    "Refresh the page to pull the newest Binance data. "
    "The signal is recalculated whenever the app reruns."
)


# ============================================================
# SAFETY
# ============================================================

st.divider()

st.warning(
    "PAPER TRADING ONLY — NO REAL ORDERS ARE PLACED."
)

st.caption(
    "This software is a research/prototype system and is not "
    "financial advice. Model outputs are probabilistic and can "
    "be wrong. Real trading remains locked."
)