import streamlit as st

from multi_market_nav import render_market_nav


def render_market_guide():
    """Beginner-friendly guide for approved users of the command center."""
    render_market_nav("btc")

    st.info(
        "New here? Read the Bitcoin Market Guide below before acting on any signal. "
        "The dashboard is decision support for paper trading, not a guarantee of price direction."
    )

    with st.expander("📘 Bitcoin Market Guide — what to check first", expanded=False):
        st.markdown(
            """
### 1) Start with the market regime
**Trend Up / Trend Down** means price structure is directional. **Range / Low Vol** means price is chopping and breakout signals are less trustworthy. **High Vol** means moves can be fast and reversals violent.

### 2) Read the Master Decision, then verify it
- **SCALP UP**: short-term bullish setup passed the bot's trade gate.
- **SCALP DOWN**: short-term bearish setup passed the bot's trade gate.
- **WAIT / HOLD**: the edge, confidence, feed quality, or specialist agreement is not strong enough.
- **LOCK UP / LOCK DOWN**: a stronger Kalshi-window directional call. Treat it as higher-conviction analysis, not certainty.

### 3) Confidence is not probability of guaranteed profit
Higher confidence means the bot sees stronger evidence and/or agreement. A high-confidence call can still lose. Watch **consensus**, **source health**, and the reason text beside the decision.

### 4) Use the specialist AIs together
- **Trend AI** — EMA structure and directional trend.
- **Momentum AI** — RSI/MACD acceleration or exhaustion.
- **Volume AI** — whether participation confirms the move.
- **Pattern AI** — candle/body structure and short-term reversal/continuation clues.
- **Support/Resistance AI** — nearby levels where price may reject or break.
- **Volatility AI** — ATR/Bollinger behavior; helps judge move size and risk.
- **Market Regime AI** — whether trend, range, or volatility conditions dominate.
- **Whale AI** — aggressive buy/sell flow and large-trade pressure.
- **Liquidity AI** — order-book imbalance and near-term pressure.
- **Derivatives AI** — funding/open-interest context when the feed is available.
- **Kalshi Context AI** — BTC versus the current Kalshi target and market-implied direction.
- **Historical Pattern AI** — recent price behavior compared with prior patterns.
- **Combination AI** — cross-specialist agreement.

### 5) Stronger setup checklist
A setup is more convincing when **trend + momentum + whale/flow + volume** point the same way, price is not running directly into major support/resistance, source health is good, and the Master AI agrees. When specialists fight each other, waiting is often the better signal.

### 6) Watch support and resistance
Near **resistance**, bullish trades need enough volume/flow to break through. Near **support**, bearish trades need enough selling pressure to break down. A quick move through a level without confirmation can become a fake breakout.

### 7) Volume confirms; weak volume warns
A breakout with expanding volume and aggressive flow is generally more credible than a breakout on weak participation. Whale flow alone can be noisy, so confirm it with price structure and volume.

### 8) Volatility changes risk
High volatility can create bigger opportunities but also wider stops, faster reversals, and more slippage. Low volatility can create false starts. Do not compare confidence without also checking the regime and ATR/volatility context.

### 9) For a 15-minute prediction
Check: **current BTC price → Kalshi target → seconds remaining → support/resistance → Master direction → confidence → consensus → Whale/Volume/Trend agreement**. The closer the window is to expiration, the more important the distance to the target becomes.

### 10) Treat WAIT as a real decision
The bot is deliberately designed to skip weak setups. More trades does not mean better results. The learning system tracks misses and mistakes so thresholds can improve over time.

---
**Paper trading only:** use the journal and backtest results to judge whether the system has a real edge before considering any real-money execution.
"""
        )

    with st.sidebar.expander("📘 Quick BTC checklist", expanded=False):
        st.markdown(
            """
1. Regime
2. Master direction
3. Confidence + consensus
4. Source health
5. Trend + Momentum
6. Whale + Volume
7. Support / resistance
8. Kalshi target + time left
9. Risk/reward
10. If signals conflict: **WAIT**
"""
        )

# The guide is intentionally static so every approved user starts from the same market-analysis framework.
