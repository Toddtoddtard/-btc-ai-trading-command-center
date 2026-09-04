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
    "eth": {
        "label": "◆ ETH",
        "title": "ETH AI Trading Command Center",
        "page": "pages/ETH_Command_Center.py",
        "accent": "#8d9eff",
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
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button {
            min-height:46px;
            border-radius:11px;
            font-weight:850;
            letter-spacing:.02em;
            border:1px solid rgba(22,135,255,.72);
            background:linear-gradient(180deg,rgba(10,31,53,.98),rgba(7,22,39,.98));
            box-shadow:0 6px 18px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.08) inset;
        }
        div[data-testid="stHorizontalBlock"] div[data-testid="stButton"] > button:hover {
            border-color:#45a0ff;
            box-shadow:0 0 18px rgba(22,135,255,.18);
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
    """Five-button market switcher shared by every command center."""
    active = active if active in MARKETS else "btc"
    _nav_css()
    st.markdown('<div class="market-switcher-label">COMMAND CENTER</div>', unsafe_allow_html=True)
    cols = st.columns(5, gap="small")

    for col, (key, cfg) in zip(cols, MARKETS.items()):
        with col:
            label = cfg["label"]
            if key == active:
                label = f"● {label}"
            if st.button(label, key=f"market_nav_{active}_{key}", use_container_width=True):
                if key != active:
                    st.switch_page(cfg["page"])

    st.markdown(
        '<div class="market-switcher-note">Bitcoin is live now. The other command centers are UI shells first; their market feeds and specialist AIs will be integrated separately.</div>',
        unsafe_allow_html=True,
    )
