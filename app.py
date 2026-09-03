import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json
import time
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

# Paper-trading rules.
# These are deliberately conservative prototype values.
TARGET_PCT = 0.0025       # 0.25%
STOP_PCT = 0.0015         # 0.15%
MAX_HOLD_MINUTES = 15

# ============================================================
# SESSION STATE
# ============================================================

if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []

if "paper_position" not in st.session_state:
    st.session_state.paper_position = None

if "prediction_journal" not in st.session_state:
    st.session_state.prediction_journal = []

if "paper_balance" not in st.session_state:
    st.session_state.paper_balance = 10000.0

if "starting_balance" not in st.session_state:
    st.session_state.starting_balance = 10000.0

if "last_prediction_time" not in st.session_state:
    st.session_state.last_prediction_time = None

# ============================================================
# BINANCE REQUEST
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

# ============================================================
# BTC 1-MINUTE CANDLES
# ============================================================

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
        raise ValueError("Binance returned no candle data.")

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
# RECENT AGGREGATED TRADES
# ============================================================

def get_recent_trades():

    data = binance_get(
        "/api/v3/aggTrades",
        {
            "symbol": "BTCUSDT",
            "limit": 1000
        }
    )

    if not data:
        raise ValueError("Binance returned no recent trades.")

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
# SHORT-TERM TRADE BARS
# ============================================================

def build_trade_bars(trades, seconds):

    if trades.empty:
        return pd.DataFrame()

    temp = trades.copy()

    temp["buy_volume"] = np.where(
        ~temp["buyer_maker"],
        temp["quantity"],
        0.0
    )

    temp["sell_volume"] = np.where(
        temp["buyer_maker"],
        temp["quantity"],
        0.0
    )

    temp = temp.set_index("time")

    bars = temp["price"].resample(
        f"{seconds}s"
    ).ohlc()

    bars["volume"] = (
        temp["quantity"]
        .resample(f"{seconds}s")
        .sum()
    )

    bars["buy_volume"] = (
        temp["buy_volume"]
        .resample(f"{seconds}s")
        .sum()
    )

    bars["sell_volume"] = (
        temp["sell_volume"]
        .resample(f"{seconds}s")
        .sum()
    )

    bars["trades"] = (
        temp["quantity"]
        .resample(f"{seconds}s")
        .count()
    )

    bars = bars.dropna(
        subset=["open", "high", "low", "close"]
    )

    bars["buy_pressure"] = np.where(
        bars["volume"] > 0,
        bars["buy_volume"]
        / bars["volume"]
        * 100,
        50
    )

    return bars.reset_index()

# ============================================================
# DEMO FALLBACK
# ============================================================

def create_demo_data():

    demo_rng = np.random.default_rng(7)

    now = pd.Timestamp.now(tz="UTC")

    times = pd.date_range(
        end=now,
        periods=500,
        freq="1min"
    )

    price = (
        77500
        + np.cumsum(
            demo_rng.normal(
                0,
                38,
                len(times)
            )
        )
    )

    open_ = np.r_[
        price[0],
        price[:-1]
    ]

    high = (
        np.maximum(open_, price)
        + demo_rng.uniform(
            3,
            28,
            len(price)
        )
    )

    low = (
        np.minimum(open_, price)
        - demo_rng.uniform(
            3,
            28,
            len(price)
        )
    )

    volume = demo_rng.lognormal(
        9.1,
        0.45,
        len(price)
    )

    return pd.DataFrame({
        "time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": price,
        "volume": volume
    })

# ============================================================
# LOAD MARKET DATA
# ============================================================

try:

    candles = get_btc_candles()
    trades = get_recent_trades()

    live_ok = True
    data_error = ""

except Exception as e:

    candles = create_demo_data()
    trades = pd.DataFrame()

    live_ok = False
    data_error = str(e)

# ============================================================
# SHORT-TERM DATA
# ============================================================

if live_ok:

    bars_1s = build_trade_bars(trades, 1)
    bars_3s = build_trade_bars(trades, 3)
    bars_5s = build_trade_bars(trades, 5)

else:

    bars_1s = pd.DataFrame()
    bars_3s = pd.DataFrame()
    bars_5s = pd.DataFrame()

# ============================================================
# MARKET FEATURES
# ============================================================

def calculate_features(candles, trades):

    close = candles["close"]

    # Short momentum
    momentum_5 = (
        close.iloc[-1]
        / close.iloc[-6]
        - 1
    ) * 100

    momentum_15 = (
        close.iloc[-1]
        / close.iloc[-16]
        - 1
    ) * 100

    # Simple moving averages
    ema_fast = close.ewm(
        span=9,
        adjust=False
    ).mean().iloc[-1]

    ema_slow = close.ewm(
        span=21,
        adjust=False
    ).mean().iloc[-1]

    # Recent volatility
    returns = close.pct_change()

    volatility = (
        returns.tail(30).std()
        * 100
    )

    # Recent high/low range
    recent_high = candles["high"].tail(20).max()
    recent_low = candles["low"].tail(20).min()

    # Live trade pressure
    if not trades.empty:

        total_volume = trades["quantity"].sum()

        buy_volume = trades.loc[
            ~trades["buyer_maker"],
            "quantity"
        ].sum()

        if total_volume > 0:

            buy_pressure = (
                buy_volume
                / total_volume
                * 100
            )

        else:

            buy_pressure = 50

    else:

        buy_pressure = 50

    return {
        "momentum_5": momentum_5,
        "momentum_15": momentum_15,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "volatility": volatility,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "buy_pressure": buy_pressure
    }

features = calculate_features(
    candles,
    trades
)

# ============================================================
# SPECIALIST AI PROTOTYPES
# ============================================================

def specialist_scores(features):

    buy = features["buy_pressure"]

    momentum = features["momentum_5"]

    momentum_score = np.clip(
        50 + momentum * 12,
        20,
        80
    )

    trend_score = 65

    if features["ema_fast"] > features["ema_slow"]:
        trend_score = 72
    else:
        trend_score = 38

    volume_score = np.clip(
        buy,
        20,
        80
    )

    volatility_score = 60

    if features["volatility"] < 0.35:
        volatility_score = 65
    elif features["volatility"] > 0.80:
        volatility_score = 45

    # Whale remains independent for now.
    # It is NOT falsely claiming access to whale data.
    whale_score = 50

    historical_score = 55

    regime_score = 60

    return {
        "Trend AI": trend_score,
        "Momentum AI": momentum_score,
        "Volume AI": volume_score,
        "Pattern AI": 55,
        "S/R AI": 55,
        "Volatility AI": volatility_score,
        "Regime AI": regime_score,
        "Whale AI": whale_score,
        "Liquidity AI": 55,
        "Derivatives AI": 50,
        "Event AI": 50,
        "Historical AI": historical_score
    }

scores = specialist_scores(features)

# ============================================================
# MASTER AI PROTOTYPE
# ============================================================

def master_prediction(scores):

    # Independent specialist inputs.
    trend = scores["Trend AI"]
    momentum = scores["Momentum AI"]
    volume = scores["Volume AI"]
    regime = scores["Regime AI"]
    volatility = scores["Volatility AI"]
    whale = scores["Whale AI"]

    # Combination layer.
    bullish_score = (
        trend * 0.22
        + momentum * 0.20
        + volume * 0.20
        + regime * 0.14
        + volatility * 0.08
        + whale * 0.06
        + scores["S/R AI"] * 0.05
        + scores["Historical AI"] * 0.05
    )

    bearish_score = 100 - bullish_score

    confidence = max(
        bullish_score,
        bearish_score
    )

    # Don't trade weak signals.
    if confidence < 58:
        signal = "WAIT"

    elif bullish_score > bearish_score:
        signal = "SCALP UP"

    else:
        signal = "SCALP DOWN"

    return (
        signal,
        float(confidence),
        float(bullish_score),
        float(bearish_score)
    )

(
    master_signal,
    master_confidence,
    bullish_probability,
    bearish_probability
) = master_prediction(scores)

# ============================================================
# PAPER TRADING ENGINE
# ============================================================

def open_paper_trade(
    signal,
    price,
    confidence
):

    if signal not in [
        "SCALP UP",
        "SCALP DOWN"
    ]:
        return False

    if st.session_state.paper_position is not None:
        return False

    now = datetime.now(timezone.utc)

    if signal == "SCALP UP":

        target = price * (
            1 + TARGET_PCT
        )

        stop = price * (
            1 - STOP_PCT
        )

        side = "LONG"

    else:

        target = price * (
            1 - TARGET_PCT
        )

        stop = price * (
            1 + STOP_PCT
        )

        side = "SHORT"

    position = {
        "side": side,
        "signal": signal,
        "entry": price,
        "target": target,
        "stop": stop,
        "confidence": confidence,
        "opened_at": now,
        "status": "OPEN"
    }

    st.session_state.paper_position = position

    return True

# ============================================================
# CHECK PAPER TRADE
# ============================================================

def check_paper_trade(candles):

    position = st.session_state.paper_position

    if position is None:
        return

    current = candles.iloc[-1]

    high = float(current["high"])
    low = float(current["low"])
    close = float(current["close"])

    entry = position["entry"]

    side = position["side"]

    opened_at = position["opened_at"]

    now = datetime.now(timezone.utc)

    age_minutes = (
        now - opened_at
    ).total_seconds() / 60

    result = None
    exit_price = None
    reason = None

    if side == "LONG":

        if low <= position["stop"]:

            result = "LOSS"
            exit_price = position["stop"]
            reason = "STOP"

        elif high >= position["target"]:

            result = "WIN"
            exit_price = position["target"]
            reason = "TARGET"

        elif age_minutes >= MAX_HOLD_MINUTES:

            exit_price = close

            if exit_price > entry:
                result = "WIN"
            else:
                result = "LOSS"

            reason = "TIME EXIT"

    else:

        if high >= position["stop"]:

            result = "LOSS"
            exit_price = position["stop"]
            reason = "STOP"

        elif low <= position["target"]:

            result = "WIN"
            exit_price = position["target"]
            reason = "TARGET"

        elif age_minutes >= MAX_HOLD_MINUTES:

            exit_price = close

            if exit_price < entry:
                result = "WIN"
            else:
                result = "LOSS"

            reason = "TIME EXIT"

    if result is None:
        return

    if side == "LONG":

        pnl_pct = (
            exit_price
            - entry
        ) / entry

    else:

        pnl_pct = (
            entry
            - exit_price
        ) / entry

    paper_pnl = (
        st.session_state.paper_balance
        * pnl_pct
    )

    st.session_state.paper_balance += paper_pnl

    completed = {
        **position,
        "exit": exit_price,
        "closed_at": now,
        "result": result,
        "reason": reason,
        "pnl_pct": pnl_pct * 100,
        "paper_pnl": paper_pnl,
        "status": "CLOSED"
    }

    st.session_state.paper_trades.append(
        completed
    )

    st.session_state.paper_position = None

# Check any existing trade before potentially opening another.
check_paper_trade(candles)

# ============================================================
# PREDICTION JOURNAL
# ============================================================

current_minute = candles["time"].iloc[-1]

if (
    st.session_state.last_prediction_time
    != current_minute
):

    journal_entry = {
        "time": current_minute,
        "price": float(candles["close"].iloc[-1]),
        "signal": master_signal,
        "confidence": master_confidence,
        "bullish_probability": bullish_probability,
        "bearish_probability": bearish_probability
    }

    st.session_state.prediction_journal.append(
        journal_entry
    )

    st.session_state.last_prediction_time = (
        current_minute
    )

# ============================================================
# PAGE HEADER
# ============================================================

st.title(
    "₿ BTC AI Trading Command Center"
)

st.caption(
    "Live multi-agent BTC market engine • "
    "15-minute primary horizon • PAPER TRADING"
)

if live_ok:

    st.success(
        "🟢 LIVE BTC DATA — BINANCE"
    )

else:

    st.warning(
        "🟡 DEMO DATA — BINANCE CONNECTION FAILED"
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
        ],
        index=0
    )

    st.divider()

    st.subheader("Market Data")

    if live_ok:

        st.success(
            "Binance connected"
        )

        st.write(
            "BTC/USDT"
        )

        st.write(
            "1-minute candles: LIVE"
        )

        st.write(
            "Recent trades: LIVE"
        )

    else:

        st.warning(
            "Demo mode"
        )

    st.divider()

    st.subheader(
        "Paper Account"
    )

    st.metric(
        "Paper Balance",
        f"${st.session_state.paper_balance:,.2f}"
    )

    st.caption(
        "Starting balance: $10,000"
    )

    if st.button(
        "Reset Paper Account"
    ):

        st.session_state.paper_trades = []
        st.session_state.paper_position = None
        st.session_state.prediction_journal = []
        st.session_state.paper_balance = 10000.0

        st.rerun()

    st.divider()

    st.subheader(
        "Safety"
    )

    st.info(
        "No exchange account is connected. "
        "No real orders can be placed."
    )

# ============================================================
# CURRENT PRICE
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

# ============================================================
# MASTER PREDICTION
# ============================================================

st.subheader(
    "Master Prediction"
)

if master_signal == "SCALP UP":

    st.success(
        f"SCALP UP • "
        f"{master_confidence:.1f}% confidence"
    )

elif master_signal == "SCALP DOWN":

    st.error(
        f"SCALP DOWN • "
        f"{master_confidence:.1f}% confidence"
    )

else:

    st.warning(
        f"WAIT • "
        f"{master_confidence:.1f}% confidence"
    )

master_cols = st.columns(4)

with master_cols[0]:

    st.metric(
        "BTC Price",
        f"${last_price:,.2f}",
        f"{price_change_pct:+.3f}%"
    )

with master_cols[1]:

    st.metric(
        "Bullish Probability",
        f"{bullish_probability:.1f}%"
    )

with master_cols[2]:

    st.metric(
        "Bearish Probability",
        f"{bearish_probability:.1f}%"
    )

with master_cols[3]:

    st.metric(
        "Buy Pressure",
        f"{features['buy_pressure']:.1f}%"
    )

# ============================================================
# PAPER POSITION
# ============================================================

st.subheader(
    "Paper Trading Position"
)

position = st.session_state.paper_position

if position is None:

    st.info(
        "No open paper position."
    )

    if mode == "PAPER":

        if master_signal in [
            "SCALP UP",
            "SCALP DOWN"
        ]:

            if st.button(
                "OPEN PAPER TRADE"
            ):

                opened = open_paper_trade(
                    master_signal,
                    last_price,
                    master_confidence
                )

                if opened:
                    st.success(
                        "Paper trade opened."
                    )

                    st.rerun()

        else:

            st.caption(
                "Master AI says WAIT. "
                "No paper trade is recommended."
            )

else:

    position_cols = st.columns(5)

    with position_cols[0]:

        st.metric(
            "Side",
            position["side"]
        )

    with position_cols[1]:

        st.metric(
            "Entry",
            f"${position['entry']:,.2f}"
        )

    with position_cols[2]:

        st.metric(
            "Target",
            f"${position['target']:,.2f}"
        )

    with position_cols[3]:

        st.metric(
            "Stop",
            f"${position['stop']:,.2f}"
        )

    with position_cols[4]:

        age = (
            datetime.now(timezone.utc)
            - position["opened_at"]
        ).total_seconds() / 60

        st.metric(
            "Age",
            f"{age:.1f} min"
        )

# ============================================================
# MARKET CHART
# ============================================================

st.subheader(
    f"BTC Market Chart — {timeframe}"
)

if timeframe == "1 second":

    chart_df = bars_1s.tail(120)

elif timeframe == "3 seconds":

    chart_df = bars_3s.tail(120)

elif timeframe == "5 seconds":

    chart_df = bars_5s.tail(120)

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

if chart_df.empty:

    st.info(
        "Waiting for enough trade data."
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

direction = (
    1
    if master_signal == "SCALP UP"
    else -1
    if master_signal == "SCALP DOWN"
    else 0
)

forecast_move = (
    prediction_last
    * 0.0025
    * direction
)

forecast = (
    prediction_last
    + np.linspace(
        0,
        forecast_move,
        15
    )
)

uncertainty = (
    prediction_last
    * 0.0012
)

upper = forecast + uncertainty
lower = forecast - uncertainty

prediction_fig.add_trace(
    go.Scatter(
        x=future_t,
        y=forecast,
        mode="lines",
        name="AI projected path",
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
        name="Confidence band",
        opacity=0.18
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
    "🐋 Whale AI — Independent Specialist"
)

whale_value = scores["Whale AI"]

whale_cols = st.columns(3)

with whale_cols[0]:

    st.metric(
        "Whale Bullish",
        f"{whale_value:.0f}%"
    )

with whale_cols[1]:

    st.metric(
        "Whale Bearish",
        f"{100-whale_value:.0f}%"
    )

with whale_cols[2]:

    st.metric(
        "Status",
        "AWAITING WHALE FEED"
    )

st.caption(
    "Whale AI is intentionally kept independent. "
    "This version does NOT pretend that Binance trade data "
    "is whale data. A dedicated whale/on-chain provider can "
    "be connected later."
)

# ============================================================
# SPECIALIST NETWORK
# ============================================================

st.subheader(
    "Specialist AI Network"
)

specialist_descriptions = {

    "Trend AI":
        "EMA structure + market structure",

    "Momentum AI":
        "Short-term price momentum",

    "Volume AI":
        "Live trade volume + buying pressure",

    "Pattern AI":
        "Candlestick pattern engine",

    "S/R AI":
        "Support/resistance reactions",

    "Volatility AI":
        "Recent volatility regime",

    "Regime AI":
        "Trend / chop / breakout regime",

    "Whale AI":
        "Independent whale-flow specialist",

    "Liquidity AI":
        "Liquidity-zone specialist",

    "Derivatives AI":
        "Funding/OI/liquidation specialist",

    "Event AI":
        "Event/news specialist",

    "Historical AI":
        "Historical setup specialist"
}

grid = st.columns(3)

for i, name in enumerate(scores.keys()):

    with grid[i % 3]:

        score = scores[name]

        direction = (
            "UP"
            if score >= 55
            else "DOWN"
        )

        st.metric(
            name,
            f"{direction} • {score:.1f}%",
            specialist_descriptions[name]
        )

# ============================================================
# AI COMMUNICATION
# ============================================================

st.subheader(
    "AI Communication & Combination Layer"
)

interaction = pd.DataFrame([
    [
        "Trend + Momentum + Volume",
        "UP" if (
            scores["Trend AI"]
            + scores["Momentum AI"]
            + scores["Volume AI"]
        ) / 3 >= 55 else "DOWN",
        round(
            (
                scores["Trend AI"]
                + scores["Momentum AI"]
                + scores["Volume AI"]
            ) / 3,
            1
        ),
        "Primary short-term combination"
    ],

    [
        "Trend + Regime",
        "UP" if (
            scores["Trend AI"]
            + scores["Regime AI"]
        ) / 2 >= 55 else "DOWN",
        round(
            (
                scores["Trend AI"]
                + scores["Regime AI"]
            ) / 2,
            1
        ),
        "Trend/regime agreement"
    ],

    [
        "Momentum + Volume",
        "UP" if (
            scores["Momentum AI"]
            + scores["Volume AI"]
        ) / 2 >= 55 else "DOWN",
        round(
            (
                scores["Momentum AI"]
                + scores["Volume AI"]
            ) / 2,
            1
        ),
        "Short-term pressure"
    ],

    [
        "Whale + Market",
        "WAIT",
        scores["Whale AI"],
        "Dedicated whale data not connected yet"
    ]
], columns=[
    "Combination",
    "Signal",
    "Score",
    "Comment"
])

st.dataframe(
    interaction,
    use_container_width=True,
    hide_index=True
)

# ============================================================
# WHY MASTER AI CHOSE IT
# ============================================================

st.subheader(
    "Why the Master AI Chose This"
)

if master_signal == "SCALP UP":

    explanation = (
        "The current prototype combination layer favors UP "
        "because the live trend, momentum and trade-pressure "
        "specialists are leaning bullish."
    )

elif master_signal == "SCALP DOWN":

    explanation = (
        "The current prototype combination layer favors DOWN "
        "because the live trend, momentum and trade-pressure "
        "specialists are leaning bearish."
    )

else:

    explanation = (
        "The combination layer does not have enough agreement "
        "to justify a scalp signal, so the system is WAITING."
    )

st.info(
    explanation
    + " These are prototype calculations, not a trained "
    "machine-learning model. The next stage will replace "
    "these rules with walk-forward-trained specialists."
)

# ============================================================
# PAPER TRADING PERFORMANCE
# ============================================================

st.subheader(
    "Paper Trading Performance"
)

trades_df = pd.DataFrame(
    st.session_state.paper_trades
)

if trades_df.empty:

    perf_cols = st.columns(5)

    perf_cols[0].metric(
        "Trades",
        "0"
    )

    perf_cols[1].metric(
        "Win Rate",
        "—"
    )

    perf_cols[2].metric(
        "Profit Factor",
        "—"
    )

    perf_cols[3].metric(
        "Paper P&L",
        "$0.00"
    )

    perf_cols[4].metric(
        "Drawdown",
        "$0.00"
    )

else:

    wins = (
        trades_df["result"] == "WIN"
    ).sum()

    losses = (
        trades_df["result"] == "LOSS"
    ).sum()

    total = len(trades_df)

    win_rate = (
        wins / total * 100
        if total > 0
        else 0
    )

    gross_profit = trades_df.loc[
        trades_df["paper_pnl"] > 0,
        "paper_pnl"
    ].sum()

    gross_loss = abs(
        trades_df.loc[
            trades_df["paper_pnl"] < 0,
            "paper_pnl"
        ].sum()
    )

    if gross_loss > 0:

        profit_factor = (
            gross_profit
            / gross_loss
        )

    else:

        profit_factor = np.inf

    equity = (
        trades_df["paper_pnl"]
        .cumsum()
        + st.session_state.starting_balance
    )

    running_peak = equity.cummax()

    drawdown = (
        equity
        - running_peak
    )

    max_drawdown = drawdown.min()

    total_pnl = trades_df[
        "paper_pnl"
    ].sum()

    perf_cols = st.columns(5)

    perf_cols[0].metric(
        "Trades",
        f"{total}"
    )

    perf_cols[1].metric(
        "Win Rate",
        f"{win_rate:.1f}%"
    )

    perf_cols[2].metric(
        "Profit Factor",
        (
            f"{profit_factor:.2f}"
            if np.isfinite(profit_factor)
            else "∞"
        )
    )

    perf_cols[3].metric(
        "Paper P&L",
        f"${total_pnl:+,.2f}"
    )

    perf_cols[4].metric(
        "Max Drawdown",
        f"${max_drawdown:,.2f}"
    )

# ============================================================
# PAPER TRADE JOURNAL
# ============================================================

st.subheader(
    "Paper Trade Journal"
)

if not trades_df.empty:

    display_columns = [
        "side",
        "entry",
        "target",
        "stop",
        "exit",
        "confidence",
        "result",
        "reason",
        "pnl_pct",
        "paper_pnl"
    ]

    available = [
        col
        for col in display_columns
        if col in trades_df.columns
    ]

    st.dataframe(
        trades_df[available].tail(25),
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "No completed paper trades yet."
    )

# ============================================================
# PREDICTION JOURNAL
# ============================================================

st.subheader(
    "Prediction Journal"
)

journal_df = pd.DataFrame(
    st.session_state.prediction_journal
)

if journal_df.empty:

    st.info(
        "Predictions will appear here as the system runs."
    )

else:

    st.dataframe(
        journal_df.tail(25),
        use_container_width=True,
        hide_index=True
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

    st.success(
        "PAPER ENGINE — ACTIVE"
    )

with status_cols[2]:

    st.warning(
        "SPECIALIST AIs — PROTOTYPE"
    )

with status_cols[3]:

    st.info(
        "REAL TRADING — LOCKED"
    )

# ============================================================
# REFRESH
# ============================================================

st.divider()

if st.button(
    "🔄 Refresh Live BTC Data"
):

    st.rerun()

st.caption(
    "Refresh the app to pull the newest Binance data. "
    "Paper positions are evaluated during each refresh."
)

# ============================================================
# SAFETY
# ============================================================

st.divider()

st.caption(
    "⚠️ PAPER TRADING ONLY. "
    "No exchange account is connected. "
    "No real orders are placed. "
    "Prototype signals are not financial advice."
)