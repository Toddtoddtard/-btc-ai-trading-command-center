import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode
import json

st.set_page_config(
    page_title="BTC AI Command Center",
    page_icon="₿",
    layout="wide"
)

# ============================================================
# CONFIGURATION
# ============================================================

COINAPI_SYMBOL = "BITSTAMP_SPOT_BTC_USD"
COINAPI_BASE = "https://rest.coinapi.io/v1/ohlcv"

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
# COINAPI CONNECTION
# ============================================================

def get_coinapi_key():
    try:
        return st.secrets["COINAPI_KEY"]
    except Exception:
        return None


def get_coinapi_ohlcv(period_id="1MIN", limit=240):
    """
    Pull BTC/USD OHLCV candles from CoinAPI.

    This first version uses 1-minute candles.
    Higher-frequency feeds will be added in the streaming layer.
    """

    api_key = get_coinapi_key()

    if not api_key:
        return None, "CoinAPI key not configured"

    url = f"{COINAPI_BASE}/{COINAPI_SYMBOL}/history"

    params = urlencode({
        "period_id": period_id,
        "limit": limit
    })

    request = Request(
        f"{url}?{params}",
        headers={
            "X-CoinAPI-Key": api_key,
            "Accept": "application/json"
        }
    )

    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)

        if not data:
            return None, "CoinAPI returned no data"

        rows = []

        for item in data:
            rows.append({
                "time": pd.to_datetime(
                    item["time_period_start"],
                    utc=True
                ),
                "open": float(item["price_open"]),
                "high": float(item["price_high"]),
                "low": float(item["price_low"]),
                "close": float(item["price_close"]),
                "volume": float(item["volume_traded"])
            })

        df = pd.DataFrame(rows)

        df = df.sort_values("time").reset_index(drop=True)

        return df, None

    except Exception as e:
        return None, str(e)


# ============================================================
# DEMO FALLBACK
# ============================================================

def create_demo_data():
    rng = np.random.default_rng(7)

    now = pd.Timestamp.now(tz="UTC")

    times = pd.date_range(
        end=now,
        periods=240,
        freq="1min"
    )

    price = 77500 + np.cumsum(
        rng.normal(0, 38, len(times))
    )

    price[-1] = price[-2] + 22

    open_ = np.r_[price[0], price[:-1]]

    high = (
        np.maximum(open_, price)
        + rng.uniform(3, 28, len(price))
    )

    low = (
        np.minimum(open_, price)
        - rng.uniform(3, 28, len(price))
    )

    volume = rng.lognormal(
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

coinapi_key = get_coinapi_key()

if coinapi_key:
    df, api_error = get_coinapi_ohlcv(
        period_id="1MIN",
        limit=240
    )

    if df is None:
        df = create_demo_data()
        data_status = "⚠️ COINAPI ERROR — DEMO FALLBACK"
        data_error = api_error
    else:
        data_status = "🟢 LIVE COINAPI DATA"
        data_error = None
else:
    df = create_demo_data()
    data_status = "🟡 DEMO DATA — COINAPI NOT CONNECTED"
    data_error = None


# ============================================================
# SPECIALIST AIs
# ============================================================

specialists = [
    ("Trend AI", "EMA structure + market structure", 74),
    ("Momentum AI", "RSI + MACD + rate of change", 69),
    ("Volume AI", "Volume expansion + buying pressure", 81),
    ("Pattern AI", "Candles + recurring formations", 63),
    ("S/R AI", "Support/resistance reactions", 71),
    ("Volatility AI", "ATR + Bollinger regime", 76),
    ("Regime AI", "Trend / chop / breakout / reversal", 82),
    ("Whale AI", "Large transfers + exchange flow + accumulation", 78),
    ("Liquidity AI", "Order-book imbalance + liquidity zones", 67),
    ("Derivatives AI", "Funding + OI + liquidations", 72),
    ("Event AI", "Major BTC event/news pressure", 61),
    ("Historical AI", "Similar historical setups", 75),
]


# ============================================================
# UI STYLING
# ============================================================

st.markdown("""
<style>

.block-container {
    padding-top: 1.2rem;
    padding-bottom: 2rem;
}

.hero {
    padding: 18px 22px;
    border: 1px solid rgba(128,128,128,.25);
    border-radius: 16px;
    background: rgba(128,128,128,.08);
}

.signal {
    font-size: 32px;
    font-weight: 800;
}

.muted {
    opacity: .72;
}

.data-status {
    padding: 10px 14px;
    border-radius: 10px;
    border: 1px solid rgba(128,128,128,.25);
    margin-bottom: 15px;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# HEADER
# ============================================================

st.title("₿ BTC AI Trading Command Center")

st.caption(
    "Multi-agent prediction system • "
    "15-minute primary horizon • PAPER MODE"
)

st.markdown(
    f'<div class="data-status"><b>{data_status}</b></div>',
    unsafe_allow_html=True
)

if data_error:
    st.warning(
        f"CoinAPI connection failed, so the dashboard is using "
        f"demo data for safety. Error: {data_error}"
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

    if coinapi_key:
        st.success("CoinAPI key detected")
    else:
        st.info(
            "CoinAPI key not configured.\n\n"
            "The dashboard is currently using demo data."
        )

    st.divider()

    st.subheader("Prediction window")

    st.write(
        "Next 15-minute window"
    )

    st.progress(
        0.62,
        text="62% of current window elapsed"
    )

    st.caption(
        "Step 1 uses CoinAPI 1-minute candles. "
        "Higher-frequency streaming will be added next."
    )


# ============================================================
# CURRENT BTC PRICE
# ============================================================

last_price = float(df["close"].iloc[-1])

previous_price = float(
    df["close"].iloc[-2]
)

price_change = last_price - previous_price

price_change_pct = (
    price_change / previous_price
) * 100


# ============================================================
# MASTER PREDICTION
# ============================================================

cols = st.columns([
    1.1,
    1,
    1,
    1
])

with cols[0]:

    st.markdown(
        '''
        <div class="hero">
            <div class="muted">MASTER SIGNAL</div>
            <div class="signal">SCALP UP</div>
            <div>Confidence <b>79%</b></div>
        </div>
        ''',
        unsafe_allow_html=True
    )

with cols[1]:

    st.metric(
        "BTC price",
        f"${last_price:,.2f}",
        f"{price_change_pct:+.3f}%"
    )

with cols[2]:

    st.metric(
        "Whale pressure",
        "BULLISH",
        "78%"
    )

with cols[3]:

    st.metric(
        "Risk / reward",
        "1.7 : 1",
        "Paper only"
    )


# ============================================================
# 15-MINUTE PREDICTION CHART
# ============================================================

st.subheader("15-minute prediction")

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

rng = np.random.default_rng(7)

future_t = pd.date_range(
    start=recent["time"].iloc[-1]
    + pd.Timedelta(minutes=1),
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

upper = forecast + last * 0.0025
lower = forecast - last * 0.0025


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
        x=list(future_t)
        + list(future_t[::-1]),
        y=list(upper)
        + list(lower[::-1]),
        fill="toself",
        line=dict(width=0),
        name="Confidence band",
        opacity=.18
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

base = 58 + np.cumsum(
    rng.normal(
        0,
        2.1,
        len(wt)
    )
)

bull = np.clip(
    base,
    5,
    95
)

bear = 100 - bull

whale_df = pd.DataFrame({
    "time": wt,
    "Bullish %": bull,
    "Bearish %": bear
})

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
    "A large transfer is not automatically bullish or bearish; "
    "the production model will combine multiple flow and market "
    "signals and score them against subsequent price outcomes."
)


# ============================================================
# SPECIALIST AI NETWORK
# ============================================================

st.subheader(
    "Specialist AI network"
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
# AI COMMUNICATION LAYER
# ============================================================

st.subheader(
    "AI communication & combination layer"
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
        "Historical score",
        "Comment"
    ]
)

st.dataframe(
    interaction,
    use_container_width=True,
    hide_index=True
)


# ============================================================
# TRANSPARENCY
# ============================================================

st.subheader(
    "Why the Master AI chose this"
)

st.info(
    """
The master layer currently favors UP because several independent
specialists agree, with Trend, Volume, Whale, Regime, and Historical
AIs providing the strongest support.

In production, these weights will be learned from walk-forward
backtests rather than hard-coded.

The system will lower confidence when specialists disagree or when
historical evidence is weak.
"""
)


# ============================================================
# PERFORMANCE
# ============================================================

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "Model win rate",
    "—",
    "Needs live/backtest data"
)

m2.metric(
    "Profit factor",
    "—",
    "Needs live/backtest data"
)

m3.metric(
    "Max drawdown",
    "—",
    "Needs live/backtest data"
)

m4.metric(
    "Calibration",
    "—",
    "Needs scored predictions"
)


# ============================================================
# SAFETY
# ============================================================

st.divider()

st.caption(
    "⚠️ Prototype / paper-trading interface. "
    "Not financial advice. No real trades are placed."
)