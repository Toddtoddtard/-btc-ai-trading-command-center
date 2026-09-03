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

# Paper account only
STARTING_PAPER_BALANCE = 10000.00

# Paper-trade rules
MIN_TRADE_CONFIDENCE = 60.0
TAKE_PROFIT_PCT = 0.0025
STOP_LOSS_PCT = 0.0015

# ============================================================
# SESSION STATE
# ============================================================

if "paper_balance" not in st.session_state:
    st.session_state.paper_balance = STARTING_PAPER_BALANCE

if "paper_trades" not in st.session_state:
    st.session_state.paper_trades = []

if "current_paper_trade" not in st.session_state:
    st.session_state.current_paper_trade = None

if "prediction_history" not in st.session_state:
    st.session_state.prediction_history = []

if "last_signal" not in st.session_state:
    st.session_state.last_signal = None

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
# BTC CANDLES
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

    temp["notional"] = (
        temp["price"] * temp["quantity"]
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
        subset=["open", "high", "low", "close"]
    )

    bars["buy_pressure"] = np.where(
        bars["volume"] > 0,
        bars["buy_volume"] / bars["volume"] * 100,
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
        77000
        + np.cumsum(
            demo_rng.normal(
                0,
                35,
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
            25,
            len(price)
        )
    )

    low = (
        np.minimum(open_, price)
        - demo_rng.uniform(
            3,
            25,
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
# INDICATORS
# ============================================================

def calculate_indicators(df):

    data = df.copy()

    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    # EMAs
    data["ema_fast"] = (
        close.ewm(span=9, adjust=False).mean()
    )

    data["ema_medium"] = (
        close.ewm(span=21, adjust=False).mean()
    )

    data["ema_slow"] = (
        close.ewm(span=50, adjust=False).mean()
    )

    # Returns
    data["return_1"] = close.pct_change(1)
    data["return_5"] = close.pct_change(5)
    data["return_15"] = close.pct_change(15)

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = (
        gain.rolling(14)
        .mean()
    )

    avg_loss = (
        loss.rolling(14)
        .mean()
    )

    rs = avg_gain / avg_loss.replace(
        0,
        np.nan
    )

    data["rsi"] = (
        100 - (100 / (1 + rs))
    )

    data["rsi"] = (
        data["rsi"]
        .fillna(50)
    )

    # ATR
    previous_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    data["atr"] = (
        tr.rolling(14)
        .mean()
        .bfill()
    )

    # Bollinger
    data["bb_mid"] = (
        close.rolling(20)
        .mean()
    )

    data["bb_std"] = (
        close.rolling(20)
        .std()
    )

    data["bb_upper"] = (
        data["bb_mid"]
        + 2 * data["bb_std"]
    )

    data["bb_lower"] = (
        data["bb_mid"]
        - 2 * data["bb_std"]
    )

    # Volume
    data["volume_avg"] = (
        volume.rolling(20)
        .mean()
    )

    # Momentum
    data["momentum"] = (
        data["return_5"] * 10000
    )

    # Support / resistance
    data["support"] = (
        low.rolling(50)
        .min()
    )

    data["resistance"] = (
        high.rolling(50)
        .max()
    )

    return data


# ============================================================
# SPECIALIST MODELS
# ============================================================

def trend_ai(d):

    if (
        d["ema_fast"]
        > d["ema_medium"]
        > d["ema_slow"]
    ):
        return 72.0, "UP"

    if (
        d["ema_fast"]
        < d["ema_medium"]
        < d["ema_slow"]
    ):
        return 72.0, "DOWN"

    return 50.0, "WAIT"


def momentum_ai(d):

    score = 50.0

    if d["return_5"] > 0:
        score += 15

    if d["return_15"] > 0:
        score += 15

    if d["rsi"] > 55:
        score += 10

    if d["rsi"] > 70:
        score -= 8

    if d["return_5"] < 0:
        score -= 15

    if d["return_15"] < 0:
        score -= 15

    if d["rsi"] < 45:
        score -= 10

    score = float(
        np.clip(score, 5, 95)
    )

    direction = (
        "UP" if score > 55
        else "DOWN" if score < 45
        else "WAIT"
    )

    return score, direction


def volume_ai(d, buy_pressure):

    score = 50.0

    if buy_pressure > 55:
        score += 20

    elif buy_pressure < 45:
        score -= 20

    if (
        d["volume"]
        > d["volume_avg"] * 1.25
    ):
        if buy_pressure > 50:
            score += 12
        else:
            score -= 12

    score = float(
        np.clip(score, 5, 95)
    )

    direction = (
        "UP" if score > 55
        else "DOWN" if score < 45
        else "WAIT"
    )

    return score, direction


def pattern_ai(d):

    body = d["close"] - d["open"]

    candle_range = (
        d["high"] - d["low"]
    )

    if candle_range <= 0:
        return 50.0, "WAIT"

    body_ratio = (
        abs(body) / candle_range
    )

    if body > 0 and body_ratio > 0.65:
        return 68.0, "UP"

    if body < 0 and body_ratio > 0.65:
        return 68.0, "DOWN"

    return 50.0, "WAIT"


def support_resistance_ai(d):

    price = d["close"]
    support = d["support"]
    resistance = d["resistance"]

    if pd.isna(support) or pd.isna(resistance):
        return 50.0, "WAIT"

    distance_support = (
        price - support
    ) / price

    distance_resistance = (
        resistance - price
    ) / price

    if distance_support < 0.002:
        return 68.0, "UP"

    if distance_resistance < 0.002:
        return 68.0, "DOWN"

    return 50.0, "WAIT"


def volatility_ai(d):

    atr_pct = (
        d["atr"] / d["close"]
    )

    if atr_pct < 0.0008:
        return 55.0, "WAIT"

    if atr_pct > 0.004:
        return 42.0, "WAIT"

    if d["close"] > d["bb_mid"]:
        return 62.0, "UP"

    return 62.0, "DOWN"


def regime_ai(d):

    spread = (
        abs(
            d["ema_fast"]
            - d["ema_slow"]
        )
        / d["close"]
    )

    if spread > 0.003:

        if d["ema_fast"] > d["ema_slow"]:
            return 75.0, "UP"

        return 75.0, "DOWN"

    return 50.0, "WAIT"


def historical_ai(df):

    if len(df) < 30:
        return 50.0, "WAIT"

    recent = (
        df["close"]
        .pct_change(15)
        .iloc[-1]
    )

    if recent > 0.002:
        return 65.0, "UP"

    if recent < -0.002:
        return 65.0, "DOWN"

    return 50.0, "WAIT"


# ============================================================
# MASTER COMBINATION ENGINE
# ============================================================

def master_prediction(scores):

    up_votes = []
    down_votes = []

    for score, direction in scores.values():

        if direction == "UP":
            up_votes.append(score)

        elif direction == "DOWN":
            down_votes.append(score)

    if up_votes:
        up_strength = np.mean(up_votes)
    else:
        up_strength = 50.0

    if down_votes:
        down_strength = np.mean(down_votes)
    else:
        down_strength = 50.0

    total_directional = (
        len(up_votes)
        + len(down_votes)
    )

    if total_directional == 0:

        return (
            "WAIT",
            50.0,
            up_strength,
            down_strength
        )

    if up_strength > down_strength:

        confidence = (
            up_strength
            + min(
                15,
                len(up_votes) * 2
            )
        )

        signal = (
            "SCALP UP"
            if confidence >= MIN_TRADE_CONFIDENCE
            else "WAIT"
        )

    elif down_strength > up_strength:

        confidence = (
            down_strength
            + min(
                15,
                len(down_votes) * 2
            )
        )

        signal = (
            "SCALP DOWN"
            if confidence >= MIN_TRADE_CONFIDENCE
            else "WAIT"
        )

    else:

        signal = "WAIT"
        confidence = 50.0

    confidence = float(
        np.clip(confidence, 50, 95)
    )

    return (
        signal,
        confidence,
        up_strength,
        down_strength
    )


# ============================================================
# PAPER TRADING
# ============================================================

def open_paper_trade(
    signal,
    confidence,
    price
):

    if signal not in [
        "SCALP UP",
        "SCALP DOWN"
    ]:
        return

    if confidence < MIN_TRADE_CONFIDENCE:
        return

    if st.session_state.current_paper_trade is not None:
        return

    direction = (
        "LONG"
        if signal == "SCALP UP"
        else "SHORT"
    )

    if direction == "LONG":

        target = (
            price
            * (1 + TAKE_PROFIT_PCT)
        )

        stop = (
            price
            * (1 - STOP_LOSS_PCT)
        )

    else:

        target = (
            price
            * (1 - TAKE_PROFIT_PCT)
        )

        stop = (
            price
            * (1 + STOP_LOSS_PCT)
        )

    st.session_state.current_paper_trade = {

        "opened": datetime.now(
            timezone.utc
        ).isoformat(),

        "direction": direction,

        "signal": signal,

        "confidence": confidence,

        "entry": price,

        "target": target,

        "stop": stop
    }


def update_paper_trade(price):

    trade = (
        st.session_state.current_paper_trade
    )

    if trade is None:
        return

    direction = trade["direction"]

    exit_reason = None

    if direction == "LONG":

        if price >= trade["target"]:
            exit_reason = "TAKE PROFIT"

        elif price <= trade["stop"]:
            exit_reason = "STOP LOSS"

    else:

        if price <= trade["target"]:
            exit_reason = "TAKE PROFIT"

        elif price >= trade["stop"]:
            exit_reason = "STOP LOSS"

    if exit_reason is None:
        return

    entry = trade["entry"]

    if direction == "LONG":

        pnl_pct = (
            (price - entry)
            / entry
        )

    else:

        pnl_pct = (
            (entry - price)
            / entry
        )

    paper_size = 1000.00

    pnl = paper_size * pnl_pct

    st.session_state.paper_balance += pnl

    completed = {
        **trade,
        "exit": price,
        "exit_time": datetime.now(
            timezone.utc
        ).isoformat(),
        "reason": exit_reason,
        "pnl": pnl,
        "pnl_pct": pnl_pct * 100
    }

    st.session_state.paper_trades.append(
        completed
    )

    st.session_state.current_paper_trade = None


# ============================================================
# LOAD DATA
# ============================================================

try:

    candles = get_btc_candles()
    trades = get_recent_trades()

    live_ok = True

except Exception as e:

    candles = create_demo_data()
    trades = pd.DataFrame()

    live_ok = False

    data_error = str(e)


# ============================================================
# SHORT-TERM DATA
# ============================================================

bars_1s = (
    build_trade_bars(trades, 1)
    if live_ok
    else pd.DataFrame()
)

bars_3s = (
    build_trade_bars(trades, 3)
    if live_ok
    else pd.DataFrame()
)

bars_5s = (
    build_trade_bars(trades, 5)
    if live_ok
    else pd.DataFrame()
)


# ============================================================
# INDICATORS
# ============================================================

indicators = calculate_indicators(
    candles
)

d = indicators.iloc[-1]


# ============================================================
# TRADE PRESSURE
# ============================================================

if not trades.empty:

    total_volume = (
        trades["quantity"].sum()
    )

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

        buy_pressure = 50.0

else:

    buy_pressure = 50.0


# ============================================================
# SPECIALISTS
# ============================================================

specialist_scores = {

    "Trend AI":
        trend_ai(d),

    "Momentum AI":
        momentum_ai(d),

    "Volume AI":
        volume_ai(
            d,
            buy_pressure
        ),

    "Pattern AI":
        pattern_ai(d),

    "S/R AI":
        support_resistance_ai(d),

    "Volatility AI":
        volatility_ai(d),

    "Regime AI":
        regime_ai(d),

    "Historical AI":
        historical_ai(indicators),

    # These remain independent until their
    # actual external data feeds are connected.
    "Whale AI":
        (
            buy_pressure,
            "UP"
            if buy_pressure > 55
            else "DOWN"
            if buy_pressure < 45
            else "WAIT"
        ),

    "Liquidity AI":
        (
            50.0,
            "WAIT"
        ),

    "Derivatives AI":
        (
            50.0,
            "WAIT"
        ),

    "Event AI":
        (
            50.0,
            "WAIT"
        )
}


# ============================================================
# MASTER
# ============================================================

signal, confidence, up_strength, down_strength = (
    master_prediction(
        specialist_scores
    )
)

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
    * 100
)


# ============================================================
# PAPER TRADE ENGINE
# ============================================================

update_paper_trade(
    last_price
)

if (
    signal != st.session_state.last_signal
):

    st.session_state.prediction_history.append({

        "time": datetime.now(
            timezone.utc
        ),

        "price": last_price,

        "signal": signal,

        "confidence": confidence
    })

    st.session_state.last_signal = signal


# ============================================================
# HEADER
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
        ]
    )

    st.divider()

    st.subheader(
        "Paper Account"
    )

    st.metric(
        "Virtual Balance",
        f"${st.session_state.paper_balance:,.2f}"
    )

    st.caption(
        "Virtual money only. "
        "No deposits or real orders."
    )

    st.divider()

    st.subheader(
        "Prediction"
    )

    st.write(
        f"Signal: **{signal}**"
    )

    st.write(
        f"Confidence: **{confidence:.1f}%**"
    )

    st.divider()

    st.subheader(
        "Data"
    )

    st.write(
        "BTC/USDT"
    )

    st.write(
        "Binance 1m candles: "
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


# ============================================================
# MASTER PREDICTION
# ============================================================

st.subheader(
    "Master Prediction"
)

if signal == "SCALP UP":

    st.success(
        f"🟢 SCALP UP • {confidence:.1f}% confidence"
    )

elif signal == "SCALP DOWN":

    st.error(
        f"🔴 SCALP DOWN • {confidence:.1f}% confidence"
    )

else:

    st.warning(
        f"🟡 WAIT • {confidence:.1f}% confidence"
    )


c1, c2, c3, c4 = st.columns(4)

with c1:

    st.metric(
        "BTC Price",
        f"${last_price:,.2f}",
        f"{price_change_pct:+.3f}%"
    )

with c2:

    st.metric(
        "Bullish Strength",
        f"{up_strength:.1f}%"
    )

with c3:

    st.metric(
        "Bearish Strength",
        f"{down_strength:.1f}%"
    )

with c4:

    st.metric(
        "Buy Pressure",
        f"{buy_pressure:.1f}%"
    )


# ============================================================
# PAPER POSITION
# ============================================================

st.subheader(
    "Paper Trading Position"
)

paper_trade = (
    st.session_state.current_paper_trade
)

if paper_trade is None:

    st.info(
        "No open paper position."
    )

    if (
        signal in [
            "SCALP UP",
            "SCALP DOWN"
        ]
        and confidence >= MIN_TRADE_CONFIDENCE
    ):

        open_paper_trade(
            signal,
            confidence,
            last_price
        )

        st.rerun()

else:

    pc1, pc2, pc3, pc4 = st.columns(4)

    with pc1:

        st.metric(
            "Direction",
            paper_trade["direction"]
        )

    with pc2:

        st.metric(
            "Entry",
            f"${paper_trade['entry']:,.2f}"
        )

    with pc3:

        st.metric(
            "Target",
            f"${paper_trade['target']:,.2f}"
        )

    with pc4:

        st.metric(
            "Stop",
            f"${paper_trade['stop']:,.2f}"
        )


# ============================================================
# SHORT-TERM ENGINE
# ============================================================

st.subheader(
    "Short-Term BTC Market Engine"
)

sc1, sc2, sc3, sc4 = st.columns(4)

with sc1:

    st.metric(
        "Recent Trades",
        f"{len(trades):,}"
    )

with sc2:

    st.metric(
        "Buy Pressure",
        f"{buy_pressure:.1f}%"
    )

with sc3:

    st.metric(
        "Sell Pressure",
        f"{100-buy_pressure:.1f}%"
    )

with sc4:

    st.metric(
        "Feed",
        "LIVE" if live_ok else "DEMO"
    )


# ============================================================
# SELECT CHART DATA
# ============================================================

if timeframe == "1 second":

    chart_df = bars_1s.tail(120)

elif timeframe == "3 seconds":

    chart_df = bars_3s.tail(120)

elif timeframe == "5 seconds":

    chart_df = bars_5s.tail(120)

else:

    chart_df = candles.copy()

    rule = None

    if timeframe == "3 minutes":
        rule = "3min"

    elif timeframe == "5 minutes":
        rule = "5min"

    elif timeframe == "15 minutes":
        rule = "15min"

    if rule:

        chart_df = (
            chart_df
            .set_index("time")
            .resample(rule)
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
# INDICATOR PANEL
# ============================================================

st.subheader(
    "Live Calculated Market Features"
)

i1, i2, i3, i4 = st.columns(4)

with i1:

    st.metric(
        "RSI",
        f"{d['rsi']:.1f}"
    )

with i2:

    st.metric(
        "EMA 9",
        f"${d['ema_fast']:,.0f}"
    )

with i3:

    st.metric(
        "EMA 21",
        f"${d['ema_medium']:,.0f}"
    )

with i4:

    st.metric(
        "ATR",
        f"${d['atr']:,.2f}"
    )


# ============================================================
# 15-MINUTE PROJECTION
# ============================================================

st.subheader(
    "15-Minute Projection"
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

last = float(
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

direction_bias = (
    1
    if signal == "SCALP UP"
    else -1
    if signal == "SCALP DOWN"
    else 0
)

projected_move = (
    direction_bias
    * max(
        0.0005,
        min(
            0.004,
            abs(
                d["return_15"]
            ) * 1.5
        )
    )
)

forecast = (
    last
    * (
        1
        + np.linspace(
            0,
            projected_move,
            15
        )
    )
)

band_size = (
    max(
        d["atr"] * 0.8,
        last * 0.001
    )
)

upper = forecast + band_size
lower = forecast - band_size

prediction_fig.add_trace(
    go.Scatter(
        x=future_t,
        y=forecast,
        mode="lines",
        name="Calculated projection",
        line=dict(width=3)
    )
)

prediction_fig.add_trace(
    go.Scatter(
        x=list(future_t)
        + list(future_t[::-1]),

        y=list(upper)
        + list(lower[::-1]),

        fill="toself",

        line=dict(width=0),

        name="Projection range",

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

st.info(
    "Whale AI is intentionally kept independent. "
    "The current version uses live trade-pressure information "
    "as a temporary proxy. Actual whale-transfer, exchange-flow "
    "and entity data will be connected separately."
)

whale_bull = float(
    np.clip(
        buy_pressure,
        5,
        95
    )
)

whale_bear = (
    100
    - whale_bull
)

wc1, wc2 = st.columns(2)

with wc1:

    st.metric(
        "Whale Bullish Probability",
        f"{whale_bull:.1f}%"
    )

with wc2:

    st.metric(
        "Whale Bearish Probability",
        f"{whale_bear:.1f}%"
    )


# ============================================================
# SPECIALIST NETWORK
# ============================================================

st.subheader(
    "Specialist Market AIs"
)

specialist_rows = []

for name, result in specialist_scores.items():

    score, direction = result

    specialist_rows.append({

        "Specialist":
            name,

        "Direction":
            direction,

        "Probability / Strength":
            f"{score:.1f}%"

    })

specialist_df = pd.DataFrame(
    specialist_rows
)

st.dataframe(
    specialist_df,
    use_container_width=True,
    hide_index=True
)


# ============================================================
# MASTER REASONING
# ============================================================

st.subheader(
    "Master AI Combination Layer"
)

up_names = [
    name
    for name, result
    in specialist_scores.items()
    if result[1] == "UP"
]

down_names = [
    name
    for name, result
    in specialist_scores.items()
    if result[1] == "DOWN"
]

col1, col2 = st.columns(2)

with col1:

    st.write(
        "**UP specialists**"
    )

    if up_names:

        for name in up_names:
            st.write(
                f"🟢 {name}"
            )

    else:

        st.write(
            "None"
        )

with col2:

    st.write(
        "**DOWN specialists**"
    )

    if down_names:

        for name in down_names:
            st.write(
                f"🔴 {name}"
            )

    else:

        st.write(
            "None"
        )


st.caption(
    "The combination layer is currently a transparent "
    "feature-based ensemble. It is not yet a trained machine "
    "learning model. Its scores will later become inputs to "
    "trained models and walk-forward evaluation."
)


# ============================================================
# PAPER TRADING HISTORY
# ============================================================

st.subheader(
    "Paper Trading Performance"
)

completed = st.session_state.paper_trades

if completed:

    total_pnl = sum(
        trade["pnl"]
        for trade in completed
    )

    wins = sum(
        1
        for trade in completed
        if trade["pnl"] > 0
    )

    losses = sum(
        1
        for trade in completed
        if trade["pnl"] <= 0
    )

    win_rate = (
        wins / len(completed) * 100
    )

    p1, p2, p3, p4 = st.columns(4)

    with p1:

        st.metric(
            "Paper P&L",
            f"${total_pnl:+,.2f}"
        )

    with p2:

        st.metric(
            "Trades",
            len(completed)
        )

    with p3:

        st.metric(
            "Win Rate",
            f"{win_rate:.1f}%"
        )

    with p4:

        st.metric(
            "Virtual Balance",
            f"${st.session_state.paper_balance:,.2f}"
        )

    history_df = pd.DataFrame(
        completed
    )

    display_columns = [
        "direction",
        "confidence",
        "entry",
        "exit",
        "reason",
        "pnl",
        "pnl_pct"
    ]

    st.dataframe(
        history_df[
            display_columns
        ],
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "No completed paper trades yet. "
        "The system will record trades when a qualifying "
        "signal opens and reaches its target or stop."
    )


# ============================================================
# PREDICTION JOURNAL
# ============================================================

st.subheader(
    "Prediction Journal"
)

if st.session_state.prediction_history:

    journal_df = pd.DataFrame(
        st.session_state.prediction_history
    )

    st.dataframe(
        journal_df.tail(20),
        use_container_width=True,
        hide_index=True
    )

else:

    st.info(
        "Prediction journal is waiting for signal changes."
    )


# ============================================================
# EXTERNAL FEEDS — NEXT CONNECTIONS
# ============================================================

st.subheader(
    "External Intelligence Feeds"
)

feed1, feed2, feed3 = st.columns(3)

with feed1:

    st.info(
        "📊 AGGR\n\n"
        "Planned connection:\n"
        "market aggregation / additional BTC intelligence"
    )

with feed2:

    st.info(
        "🎲 KALSHI\n\n"
        "Planned connection:\n"
        "event-market probability signals"
    )

with feed3:

    st.success(
        "₿ BINANCE\n\n"
        "CONNECTED\n"
        "Live BTC market data"
    )


# ============================================================
# SYSTEM STATUS
# ============================================================

st.subheader(
    "System Status"
)

s1, s2, s3, s4 = st.columns(4)

with s1:

    if live_ok:
        st.success(
            "BTC DATA — LIVE"
        )
    else:
        st.warning(
            "BTC DATA — DEMO"
        )

with s2:

    st.success(
        "MARKET FEATURES — LIVE"
    )

with s3:

    st.warning(
        "TRAINED AI — NOT YET"
    )

with s4:

    st.info(
        "TRADING — PAPER ONLY"
    )


# ============================================================
# SAFETY
# ============================================================

st.divider()

st.warning(
    "⚠️ PAPER TRADING ONLY. "
    "This application does not place real trades. "
    "The calculated signals are experimental and are not "
    "financial advice. Historical or paper performance does "
    "not guarantee future results."
)

st.caption(
    "No Binance API key is required for this market-data feed. "
    "Do not add exchange credentials to the public GitHub repository."
)