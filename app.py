import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from config import APP_NAME, REFRESH_SECONDS
from market_data import MarketData
from specialists import SpecialistAI
from decision_engine import DecisionEngine
from risk_manager import RiskManager
from paper_broker import PaperBroker
from prediction_journal import PredictionJournal


st.set_page_config(
    page_title=APP_NAME,
    page_icon="₿",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def initialize_system():
    market = MarketData()
    specialists = SpecialistAI()
    engine = DecisionEngine()
    risk = RiskManager()
    broker = PaperBroker()
    journal = PredictionJournal()

    return market, specialists, engine, risk, broker, journal


market, specialists, engine, risk, broker, journal = initialize_system()


st.title("₿ Bitcoin AI Trading Command Center")

st.caption(
    "Multi-specialist AI paper-trading system • "
    "Live market monitoring • Prediction journal • Backtesting"
)

# ---------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------

st.sidebar.header("System Controls")

auto_refresh = st.sidebar.checkbox(
    "Auto Refresh",
    value=True,
)

refresh_seconds = st.sidebar.slider(
    "Refresh interval",
    min_value=2,
    max_value=60,
    value=REFRESH_SECONDS,
)

st.sidebar.divider()

st.sidebar.subheader("Trading Mode")

st.sidebar.warning(
    "PAPER TRADING ONLY\n\n"
    "Real-money execution is intentionally disabled."
)

if st.sidebar.button("Reset Paper Account"):
    broker.reset_account()
    st.success("Paper account reset.")
    st.rerun()


# ---------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------

with st.spinner("Updating market data..."):
    market_snapshot = market.get_snapshot()

btc_price = market_snapshot.get("price", np.nan)
change_24h = market_snapshot.get("change_24h", np.nan)
volume = market_snapshot.get("volume_24h", np.nan)
feed_ms = market_snapshot.get("feed_ms", np.nan)


# ---------------------------------------------------------------------
# Header metrics
# ---------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric(
        "BTC Price",
        f"${btc_price:,.2f}" if pd.notna(btc_price) else "N/A",
    )

with c2:
    st.metric(
        "24H Change",
        f"{change_24h:.2f}%" if pd.notna(change_24h) else "N/A",
    )

with c3:
    st.metric(
        "24H Volume",
        f"${volume:,.0f}" if pd.notna(volume) else "N/A",
    )

with c4:
    st.metric(
        "Feed",
        f"{feed_ms:.0f} ms" if pd.notna(feed_ms) else "N/A",
    )


# ---------------------------------------------------------------------
# Price History
# ---------------------------------------------------------------------

st.subheader("Market")

history = market.get_history()

if history is not None and not history.empty:
    st.line_chart(
        history.set_index("time")["close"],
        height=300,
    )
else:
    st.info("Historical market data unavailable.")


# ---------------------------------------------------------------------
# Specialist AI Analysis
# ---------------------------------------------------------------------

st.subheader("Specialist AI Council")

specialist_results = specialists.run_all(
    history=history,
    snapshot=market_snapshot,
)


specialist_rows = []

for name, result in specialist_results.items():
    specialist_rows.append(
        {
            "Specialist": name,
            "Signal": result.get("signal", "NEUTRAL"),
            "Confidence": round(
                float(result.get("confidence", 0.0)) * 100,
                1,
            ),
            "Score": round(
                float(result.get("score", 0.0)),
                3,
            ),
            "Reason": result.get("reason", ""),
        }
    )


specialist_df = pd.DataFrame(specialist_rows)

if not specialist_df.empty:
    st.dataframe(
        specialist_df,
        use_container_width=True,
        hide_index=True,
    )


# ---------------------------------------------------------------------
# Master Decision
# ---------------------------------------------------------------------

decision = engine.decide(
    specialist_results=specialist_results,
    market_snapshot=market_snapshot,
)


st.subheader("Master AI Decision")

d1, d2, d3, d4 = st.columns(4)

with d1:
    st.metric(
        "Decision",
        decision["action"],
    )

with d2:
    st.metric(
        "Confidence",
        f'{decision["confidence"] * 100:.1f}%',
    )

with d3:
    st.metric(
        "Consensus",
        f'{decision["consensus"] * 100:.1f}%',
    )

with d4:
    st.metric(
        "Risk",
        decision["risk_level"],
    )


st.info(decision["reason"])


# ---------------------------------------------------------------------
# Risk Management
# ---------------------------------------------------------------------

risk_result = risk.evaluate(
    decision=decision,
    account=broker.get_account(),
    market_snapshot=market_snapshot,
)


st.subheader("Risk Manager")

r1, r2, r3, r4 = st.columns(4)

with r1:
    st.metric(
        "Approved",
        "YES" if risk_result["approved"] else "NO",
    )

with r2:
    st.metric(
        "Position %",
        f'{risk_result["position_pct"] * 100:.2f}%',
    )

with r3:
    st.metric(
        "Risk Score",
        f'{risk_result["risk_score"]:.2f}',
    )

with r4:
    st.metric(
        "Reason",
        risk_result["reason"],
    )


# ---------------------------------------------------------------------
# Paper Broker
# ---------------------------------------------------------------------

st.subheader("Paper Trading Account")

account = broker.get_account()

a1, a2, a3, a4 = st.columns(4)

with a1:
    st.metric(
        "Cash",
        f'${account["cash"]:,.2f}',
    )

with a2:
    st.metric(
        "BTC",
        f'{account["btc"]:,.6f}',
    )

with a3:
    st.metric(
        "Equity",
        f'${account["equity"]:,.2f}',
    )

with a4:
    st.metric(
        "P&L",
        f'${account["pnl"]:,.2f}',
    )


# ---------------------------------------------------------------------
# Execute paper decision
# ---------------------------------------------------------------------

if st.button(
    "Execute Approved Paper Trade",
    type="primary",
):
    if risk_result["approved"]:
        result = broker.execute(
            action=decision["action"],
            price=btc_price,
            position_pct=risk_result["position_pct"],
        )

        journal.record_execution(
            decision=decision,
            risk_result=risk_result,
            execution=result,
            price=btc_price,
        )

        st.success(result["message"])

    else:
        st.error(
            "Trade rejected by risk manager: "
            + risk_result["reason"]
        )


# ---------------------------------------------------------------------
# Prediction Journal
# ---------------------------------------------------------------------

st.subheader("Prediction Journal")

journal_df = journal.get_recent(100)

if not journal_df.empty:
    st.dataframe(
        journal_df,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No predictions recorded yet.")


# ---------------------------------------------------------------------
# System Status
# ---------------------------------------------------------------------

st.divider()

st.caption(
    f"Last update: "
    f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
)

st.caption(
    "Safety: real-money order execution is disabled."
)


# ---------------------------------------------------------------------
# Auto refresh
# ---------------------------------------------------------------------

if auto_refresh:
    import time

    time.sleep(refresh_seconds)
    st.rerun()