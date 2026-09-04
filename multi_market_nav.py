import streamlit as st


MARKETS = {
    "btc": {
        "label": "₿ BITCOIN",
        "title": "BTC AI Trading Command Center",
        "page": "app.py",
        "accent": "#1687ff",
    },
    "gold": {
        "label": "🥇 GOLD",
        "title": "Gold AI Trading Command Center",
        "page": "pages/Gold_Command_Center.py",
        "accent": "#f5c542",
    },
    "gas": {
        "label": "⛽ GAS PRICES",
        "title": "Gas Prices AI Trading Command Center",
        "page": "pages/Gas_Prices_Command_Center.py",
        "accent": "#20c997",
    },
    "zec": {
        "label": "ⓩ ZEC",
        "title": "ZEC AI Trading Command Center",
        "page": "pages/ZEC_Command_Center.py",
        "accent": "#ffd43b",
    },
    "wti": {
        "label": "🛢 WTI OIL",
        "title": "WTI Oil AI Trading Command Center",
        "page": "pages/WTI_Oil_Command_Center.py",
        "accent": "#ff922b",
    },
}


def _nav_css():
    st.markdown(
        """
        <style>
        .market-switcher-label {
            color:#8ea9ca;
            font-size:.78rem;
            font-weight:800;
            letter-spacing:.13em;
            margin:.15rem 0 .45rem 0;
        }
        .market-switcher-note {
            color:#7890ad;
            font-size:.76rem;
            margin-top:.2rem;
            margin-bottom:.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_market_nav(active="btc"):
    """Five-link market switcher shared by every command center."""
    active = active if active in MARKETS else "btc"
    _nav_css()
    st.markdown('<div class="market-switcher-label">COMMAND CENTER</div>', unsafe_allow_html=True)
    cols = st.columns(5, gap="small")

    for col, (key, cfg) in zip(cols, MARKETS.items()):
        with col:
            label = cfg["label"]
            if key == active:
                label = f"● {label}"
            st.page_link(cfg["page"], label=label, use_container_width=True)

    st.markdown(
        '<div class="market-switcher-note">Bitcoin, Gold, Gas Prices, ZEC and WTI command centers are available from the navigation above.</div>',
        unsafe_allow_html=True,
    )
