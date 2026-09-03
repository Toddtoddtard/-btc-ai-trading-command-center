import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json

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

# Used only for demo/placeholder sections.
# This does NOT generate the live BTC price.
rng = np.random.default_rng(7)


# ============================================================
# LIVE BTC MARKET DATA
# ============================================================

def get_btc_data():
    """
    Pull the latest BTC/USDT 1-minute candles
    from Binance public market data.

    No API key.
    No Binance account.
    No trading permissions.
    """

    url = f"{BINANCE_BASE_URL}/api/v3/klines"

    params = urlencode({
        "symbol": "BTCUSDT",
        "interval": "1m",
        "limit": 240
    })

    request = Request(
        f"{url}?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/1.0"
        }
    )

    with urlopen(request, timeout=10) as response:
        data = json.loads(
            response.read().decode("utf-8")
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

    return pd.DataFrame(rows).sort_values(
        "time"
    ).reset_index(drop=True)


# ============================================================
# SAFE DEMO FALLBACK
# ============================================================

def create_demo_data():

    demo_rng = np.random.default_rng(7)

    now = pd.Timestamp.now(tz="UTC")

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

    price[-1] = price[-2] + 22

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
# LOAD MARKET DATA
# ============================================================

try:

    df = get_btc_data()

    data_status = "🟢 LIVE BTC DATA — BINANCE"
    data_error = None

except Exception as e:

    df = create_demo_data()

    data_status = (
        "🟡 DEMO DATA — BINANCE CONNECTION FAILED"
    )

    data_error = str(e)


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

st.success(
    data_status
)

if data_error:
    st.warning(
        "The public Binance connection failed. "
        "The dashboard is safely using demo data."
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

    st.subheader("Market Data")

    st.write(
        data_status
    )

    st.caption(
        "Binance public market data requires "
        "no API key. Trading is not connected."
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

    st.caption(
        "Current feed: BTC/USDT 1-minute candles."
    )


# ============================================================
# CURRENT BTC PRICE
# ============================================================

last_price = float(
    df["close"].iloc[-1]
)

previous_price = float(
    df["close"].iloc[-2]
)

price_change = (
    last_price
    - previous_price
)

price_change_pct = (
    price_change
    / previous_price
) * 100


# ============================================================
# MASTER SIGNAL
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
        "Whale Pressure",
        "BULLISH",
        "78%"
    )

with master_cols[3]:

    st.metric(
        "Risk / Reward",
        "1.7 : 1",
        "Paper only"
    )


# ============================================================
# 15-MINUTE PREDICTION CHART
# ============================================================

st.subheader(
    "15-minute prediction"
)

fig = go.Figure()

recent = df.tail(90)

fig.add_trace(
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

forecast = (
    last
    + np.linspace(
        0,
        last * 0.0042,
        15
    )
    + rng.normal(
        0,
        last * 0.00035,
        15
    )
)

upper = (
    forecast
    + last * 0.0025
)

lower = (
    forecast
    - last * 0.0025
)

fig.add_trace(
    go.Scatter(
        x=future_t,
        y=forecast,
        mode="lines",
        name="AI projected path",
        line=dict(width=3)
    )
)

fig.add_trace(
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

fig.update_layout(
    height=460,
    margin=dict(
        l=10,
        r=10,
        t=10,
        b=10
    ),
    xaxis_rangeslider_visible=False
)

st.plotly_chart(
    fig,
    use_container_width=True
)


# ============================================================
# WHALE AI
# ============================================================

st.subheader(
    "🐋 Whale AI — independent indicator"
)

wt = pd.date_range(
    end=pd.Timestamp.now(tz="UTC"),
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

wf = go.Figure()

wf.add_trace(
    go.Scatter(
        x=wt,
        y=bull,
        mode="lines",
        name="Bullish %",
        line=dict(width=2)
    )
)

wf.add_trace(
    go.Scatter(
        x=wt,
        y=bear,
        mode="lines",
        name="Bearish %",
        line=dict(width=2)
    )
)

wf.add_hline(
    y=50,
    line_dash="dot"
)

wf.update_layout(
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
    wf,
    use_container_width=True
)

st.caption(
    "Whale AI is an independent model. "
    "A large transfer is not automatically bullish or bearish. "
    "The production model will evaluate whale-flow signals "
    "against subsequent BTC price outcomes."
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
        ],
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
The current prototype favors UP because several independent
specialists agree, with Trend, Volume, Whale, Regime, and
Historical AIs providing the strongest support.

In production, these weights will be learned from walk-forward
backtests rather than hard-coded.

The system will lower confidence when specialists disagree,
when historical evidence is weak, or when market conditions
change significantly.
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
    st.success("BTC MARKET DATA")

with status_cols[1]:
    st.warning("SPECIALIST AIs — DEMO")

with status_cols[2]:
    st.warning("WHALE AI — DEMO")

with status_cols[3]:
    st.info("TRADING — PAPER ONLY")


# ============================================================
# SAFETY
# ============================================================

st.divider()

st.caption(
    "⚠️ Prototype / paper-trading interface. "
    "Not financial advice. No real trades are placed."
)