import streamlit as st

from access_control import require_owner_approval
from multi_market_nav import MARKETS, render_market_nav


SHELL_COPY = {
    "gold": {
        "symbol": "XAU",
        "market": "Gold",
        "subtitle": "Gold market command center shell",
        "feed": "Kalshi Gold integration queued next",
        "kalshi": "AVAILABLE",
        "kalshi_note": "Kalshi lists Gold markets, including short-window Up/Down contracts.",
    },
    "gas": {
        "symbol": "GAS",
        "market": "Gas Prices",
        "subtitle": "Gas-prices market command center shell",
        "feed": "Kalshi gas-market integration queued next",
        "kalshi": "AVAILABLE",
        "kalshi_note": "Kalshi lists gasoline and natural-gas markets. The exact contract family will be shown rather than mixing the two.",
    },
    "zec": {
        "symbol": "ZEC",
        "market": "Zcash",
        "subtitle": "ZEC market command center shell",
        "feed": "No verified Kalshi ZEC market currently available",
        "kalshi": "UNAVAILABLE",
        "kalshi_note": "This page stays UI-only until Kalshi offers a real ZEC contract or you approve a separate free ZEC source.",
    },
    "wti": {
        "symbol": "WTI",
        "market": "WTI Crude Oil",
        "subtitle": "WTI oil market command center shell",
        "feed": "Kalshi WTI integration queued next",
        "kalshi": "AVAILABLE",
        "kalshi_note": "Chosen as the fifth market because Kalshi offers WTI Up/Down 15-minute contracts that fit the BTC-style decision window.",
    },
}


def _shell_css(accent):
    st.markdown(
        f"""
        <style>
        .block-container {{padding-top:1.1rem; padding-bottom:2rem;}}
        .shell-banner {{
            padding:.72rem 1rem; border:1px solid {accent}; border-radius:11px;
            background:linear-gradient(180deg,rgba(8,25,44,.96),rgba(6,18,32,.96));
            box-shadow:0 8px 24px rgba(0,0,0,.18); font-weight:800; margin-bottom:.85rem;
        }}
        .shell-grid {{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:.6rem 0 1rem 0;}}
        .shell-card {{
            border:1px solid rgba(22,135,255,.55); border-radius:12px; padding:14px;
            min-height:92px; background:linear-gradient(180deg,#0b1b2e,#081522);
        }}
        .shell-label {{color:#8da6c4;font-size:.78rem;font-weight:750;letter-spacing:.05em;}}
        .shell-value {{color:#edf5ff;font-size:1.05rem;font-weight:850;margin-top:8px;}}
        .shell-muted {{color:#8196b2;font-size:.82rem;margin-top:5px;}}
        .shell-panel {{
            border:1px dashed rgba(116,154,196,.55); border-radius:13px; padding:18px;
            background:rgba(9,22,38,.72); min-height:210px;
        }}
        .shell-panel h3 {{margin-top:0;}}
        .shell-chip {{
            display:inline-block;padding:5px 9px;border-radius:999px;margin:3px 5px 3px 0;
            border:1px solid rgba(144,170,205,.45);color:#bed0e8;font-size:.78rem;font-weight:750;
        }}
        @media (max-width:900px) {{.shell-grid {{grid-template-columns:repeat(2,minmax(0,1fr));}}}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_market_shell(market_key):
    require_owner_approval()
    cfg = MARKETS[market_key]
    data = SHELL_COPY[market_key]
    _shell_css(cfg["accent"])

    render_market_nav(market_key)
    st.title(cfg["title"])
    st.markdown(
        '<div class="shell-banner">COMMAND CENTER PREVIEW — layout only. No automated signals, AI decisions, or paper trades are active on this market yet.</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"{data['subtitle']} • phase 1: command center UI • phase 2: live/Kalshi data • phase 3: specialist AI council")

    st.markdown(
        f"""
        <div class="shell-grid">
          <div class="shell-card"><div class="shell-label">MARKET</div><div class="shell-value">{data['market']}</div><div class="shell-muted">{data['symbol']} command center</div></div>
          <div class="shell-card"><div class="shell-label">KALSHI</div><div class="shell-value">{data['kalshi']}</div><div class="shell-muted">{data['kalshi_note']}</div></div>
          <div class="shell-card"><div class="shell-label">AI COUNCIL</div><div class="shell-value">COMING NEXT</div><div class="shell-muted">Separate specialists will be trained for this market</div></div>
          <div class="shell-card"><div class="shell-label">PAPER TRADING</div><div class="shell-value">LOCKED</div><div class="shell-muted">Will stay off until feed + validation are ready</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    market_tab, council_tab, flow_tab, paper_tab = st.tabs(
        ["Market", "AI Council", "Order Flow", "Paper Trading"]
    )

    with market_tab:
        st.markdown(
            f"""
            <div class="shell-panel">
              <h3>{data['market']} Market View</h3>
              <p>This is where the live price chart, Kalshi target/odds when available, trend structure, volatility, support/resistance and multi-timeframe market data will live.</p>
              <span class="shell-chip">1m</span><span class="shell-chip">3m</span><span class="shell-chip">5m</span><span class="shell-chip">15m</span><span class="shell-chip">1h</span>
              <p><b>No fake price is shown.</b> The chart stays empty until the real market feed is connected.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with council_tab:
        st.markdown(
            """
            <div class="shell-panel">
              <h3>Specialist AI Council</h3>
              <p>The council will be market-specific rather than copying Bitcoin's learned weights.</p>
              <span class="shell-chip">Trend AI</span><span class="shell-chip">Momentum AI</span><span class="shell-chip">Volume AI</span><span class="shell-chip">S/R AI</span><span class="shell-chip">Volatility AI</span><span class="shell-chip">Regime AI</span><span class="shell-chip">Liquidity AI</span><span class="shell-chip">Historical AI</span><span class="shell-chip">Kalshi Context AI</span>
              <p>Scores and confidence remain disabled until each specialist has a real input source.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with flow_tab:
        st.markdown(
            """
            <div class="shell-panel">
              <h3>Order Flow / Positioning</h3>
              <p>This panel is reserved for the best available market-specific flow data. It will not pretend unavailable data is neutral.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with paper_tab:
        st.markdown(
            """
            <div class="shell-panel">
              <h3>Paper Trading</h3>
              <p>Paper execution, journal, win rate, drawdown and P&amp;L will be added only after the market feed and decision engine are wired and tested.</p>
              <p><b>Real-money execution is not included.</b></p>
            </div>
            """,
            unsafe_allow_html=True,
        )
