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
# CONFIGURATION
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

rng = np.random.default_rng(7)


# ============================================================
# BINANCE REQUEST HELPER
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
            "User-Agent": "BTC-AI-Command-Center/1.0"
        }
    )

    with urlopen(request, timeout=10) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


# ============================================================
# 1-MINUTE BTC CANDLES
# ============================================================

def get_btc_candles():

    data = binance_get(
        "/api/v3/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "limit": 240
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
# RECENT BINANCE AGGREGATED TRADES
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
        raise ValueError(
            "Binance returned no recent trades."
        )

    rows = []

    for trade in data:

        price = float(trade["p"])
        quantity = float(trade["q"])

        rows.append({
            "time": pd.to_datetime(
                trade["T"],
                unit="ms",
                utc=True
            ),
            "price": price,
            "quantity": quantity,

            # Binance field:
            # m = buyer is market maker
            "buyer_maker": bool(trade["m"])
        })

    return (
        pd.DataFrame(rows)
        .sort_values("time")
        .reset_index(drop=True)
    )


# ============================================================
# BUILD SHORT-TERM BARS
# ============================================================

def build_trade_bars(trades, seconds):

    if trades.empty:
        return pd.DataFrame()

    temp = trades.copy()

    temp["notional"] = (
        temp["price"]
        * temp["quantity"]
    )

    # If buyer_maker is True, the aggressor was a seller.
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
        subset=["open", "high", "low", "close"]
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
# DEMO FALLBACK
# ============================================================

def create_demo_data():

    demo_rng = np.random.default_rng(7)

    now = pd.Timestamp.now(
        tz="UTC"
    )

    times = pd.date_range(
        end=now,
        periods=240,
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

    price[-1] = (
        price[-2] + 22
    )

    open_ = np.r_[
        price[0],
        price[:-1]
    ]

    high = (
        np.maximum(
            open_,
            price
        )
        + demo_rng.uniform(
            3,
            28,
            len(price)
        )
    )

    low = (
        np.minimum(
            open_,
            price
        )
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
# LOAD LIVE DATA
# ============================================================

try:

    candles = get_btc_candles()
    trades = get_recent_trades()

    live_ok = True
    data_status = "🟢 LIVE BTC DATA — BINANCE"

except Exception as e:

    candles = create_demo_data()
    trades = pd.DataFrame()

    live_ok = False
    data_status = (
        "🟡 DEMO DATA — BINANCE CONNECTION FAILED"
    )

    data_error = str(e)


# ============================================================
# BUILD SHORT-TERM DATA
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
# SPECIALIST AI NETWORK
# ============================================================

specialists = [

    (
        "Trend AI",
        "EMA structure + market structure",
        74
    ),

    (
        "Momentum AI",
        "RSI + MACD + rate of change",
        69
    ),

    (
        "Volume AI",
        "Volume expansion + buying pressure",
        81
    ),

    (
        "Pattern AI",
        "Candles + recurring formations",
        63
    ),

    (
        "S/R AI",
        "Support/resistance reactions",
        71
    ),

    (
        "Volatility AI",
        "ATR + Bollinger regime",
        76
    ),

    (
        "Regime AI",
        "Trend / chop / breakout / reversal",
        82
    ),

    (
        "Whale AI",
        "Large transfers + exchange flow + accumulation",
        78
    ),

    (
        "Liquidity AI",
        "Order-book imbalance + liquidity zones",
        67
    ),

    (
        "Derivatives AI",
        "Funding + OI + liquidations",
        72
    ),

    (
        "Event AI",
        "Major BTC event/news pressure",
        61
    ),

    (
        "Historical AI",
        "Similar historical setups",
        75
    ),
]


# ============================================================
# HEADER
# ============================================================

st.title(
    "₿ BTC AI Trading Command Center"
)

st.caption(
    "Multi-agent prediction system • "
    "15-minute primary horizon • PAPER MODE"
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

    auto_refresh = st.toggle(
        "Auto refresh",
        False
    )

    st.divider()

    st.subheader(
        "Market Data"
    )

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
        "Prediction Window"
    )

    st.write(
        "Next 15-minute window"
    )

    st.progress(
        0.62,
        text="62% of current window elapsed"
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
# LIVE TRADE PRESSURE
# ============================================================

if not trades.empty:

    total_volume = trades["quantity"].sum()

    buy_volume = trades.loc[
        ~trades["buyer_maker"],
        "quantity"
    ].sum()

    sell_volume = trades.loc[
        trades["buyer_maker"],
        "quantity"
    ].sum()

    if total_volume > 0:

        buy_pressure = (
            buy_volume
            / total_volume
        ) * 100

    else:

        buy_pressure = 50

    trade_count = len(trades)

else:

    buy_pressure = 50
    trade_count = 0


if buy_pressure >= 55:

    pressure_label = "BUYING"

elif buy_pressure <= 45:

    pressure_label = "SELLING"

else:

    pressure_label = "BALANCED"


# ============================================================
# MASTER PREDICTION
# ============================================================

st.subheader(
    "Master Prediction"
)

master_cols = st.columns(4)

with master_cols[0]:

    st.markdown(
        "**MASTER SIGNAL**"
    )

    st.markdown(
        "# SCALP UP"
    )

    st.write(
        "Confidence: **79%**"
    )

with master_cols[1]:

    st.metric(
        "BTC Price",
        f"${last_price:,.2f}",
        f"{price_change_pct:+.3f}%"
    )

with master_cols[2]:

    st.metric(
        "Live Trade Pressure",
        pressure_label,
        f"{buy_pressure:.1f}% buy"
    )

with master_cols[3]:

    st.metric(
        "Risk / Reward",
        "1.7 : 1",
        "Paper only"
    )


# ============================================================
# SHORT-TERM MARKET DATA
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
        "Waiting for enough recent trade data "
        "to build this timeframe."
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

forecast = (
    prediction_last
    + np.linspace(
        0,
        prediction_last * 0.0042,
        15
    )
    + rng.normal(
        0,
        prediction_last * 0.00035,
        15
    )
)

upper = (
    forecast
    + prediction_last * 0.0025
)

lower = (
    forecast
    - prediction_last * 0.0025
)

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
    "🐋 Whale AI — Independent Indicator"
)

wt = pd.date_range(
    end=pd.Timestamp.now(
        tz="UTC"
    ),
    periods=48,
    freq="15min"
)

base = (
    58
    + np.cumsum(
        rng.normal(
            0,
            2.1,
            len(wt)
        )
    )
)

bull = np.clip(
    base,
    5,
    95
)

bear = (
    100
    - bull
)

whale_fig = go.Figure()

whale_fig.add_trace(
    go.Scatter(
        x=wt,
        y=bull,
        mode="lines",
        name="Bullish %"
    )
)

whale_fig.add_trace(
    go.Scatter(
        x=wt,
        y=bear,
        mode="lines",
        name="Bearish %"
    )
)

whale_fig.add_hline(
    y=50,
    line_dash="dot"
)

whale_fig.update_layout(
    height=280,
    yaxis=dict(
        range=[0, 100],
        title="Probability %"
    ),
    margin=dict(
        l=10,
        r=10,
        t=10,
        b=10
    )
)

st.plotly_chart(
    whale_fig,
    use_container_width=True
)

st.caption(
    "Whale AI remains an independent specialist. "
    "Large transfers are not automatically bullish or bearish. "
    "The production version will learn the relationship between "
    "whale-flow behavior and subsequent BTC price outcomes."
)


# ============================================================
# SPECIALIST AI NETWORK
# ============================================================

st.subheader(
    "Specialist AI Network"
)

grid = st.columns(3)

for i, (
    name,
    desc,
    score
) in enumerate(specialists):

    with grid[i % 3]:

        direction = (
            "UP"
            if score >= 60
            else "DOWN"
        )

        st.metric(
            name,
            f"{direction} • {score}%",
            desc
        )


# ============================================================
# AI COMMUNICATION
# ============================================================

st.subheader(
    "AI Communication & Combination Layer"
)

interaction = pd.DataFrame(
    [
        [
            "Trend + Volume + Whale",
            "UP",
            84,
            "Strongest current combination"
        ],
        [
            "Momentum + S/R",
            "UP",
            76,
            "Support rejection + positive momentum"
        ],
        [
            "Derivatives + Liquidity",
            "UP",
            64,
            "Positive but mixed"
        ],
        [
            "Volatility + Event",
            "WAIT",
            58,
            "Risk of confidence collapse"
        ],
        [
            "Historical + Regime",
            "UP",
            79,
            "Similar trending setups"
        ]
    ],
    columns=[
        "Combination",
        "Signal",
        "Historical Score",
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

st.info(
    """
The current master signal is still a prototype signal.

Live Binance market data now feeds the market-data layer,
including recent trade activity and short-term buying/selling
pressure.

The specialist percentages are still placeholders.

The next development stage will replace those hard-coded
percentages with actual calculated features and eventually
trained models evaluated through walk-forward backtesting.
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
    "Model Win Rate",
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
    "Needs paper trading"
)

m4.metric(
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
        st.success("BTC DATA — LIVE")
    else:
        st.warning("BTC DATA — DEMO")

with status_cols[1]:

    if not bars_1s.empty:
        st.success("1s / 3s / 5s ENGINE")
    else:
        st.warning("SHORT DATA — WAITING")

with status_cols[2]:

    st.warning(
        "SPECIALIST AIs — PROTOTYPE"
    )

with status_cols[3]:

    st.info(
        "TRADING — PAPER ONLY"
    )


# ============================================================
# REFRESH
# ============================================================

st.divider()

if auto_refresh:

    st.caption(
        "Auto refresh is enabled. "
        "Use the browser refresh button if the app does not "
        "automatically update."
    )

else:

    st.caption(
        "Turn on Auto refresh in the sidebar or refresh the "
        "page to pull the newest Binance trade data."
    )


# ============================================================
# SAFETY
# ============================================================

st.divider()

st.caption(
    "⚠️ Prototype / paper-trading interface. "
    "Not financial advice. "
    "No real trades are placed."
)