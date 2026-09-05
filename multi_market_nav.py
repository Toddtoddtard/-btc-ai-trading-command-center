import streamlit as st


MARKETS = {
    "btc": {
        "label": "₿ BITCOIN",
        "title": "BTC AI Trading Command Center",
        "href": "/",
        "accent": "#1687ff",
    },
    "gold": {
        "label": "🥇 GOLD",
        "title": "Gold AI Trading Command Center",
        "href": "/Gold_Command_Center",
        "accent": "#f5c542",
    },
    "gas": {
        "label": "⛽ GAS PRICES",
        "title": "Gas Prices AI Trading Command Center",
        "href": "/Gas_Prices_Command_Center",
        "accent": "#20c997",
    },
    "zec": {
        "label": "ⓩ ZEC",
        "title": "ZEC AI Trading Command Center",
        "href": "/ZEC_Command_Center",
        "accent": "#ffd43b",
    },
    "wti": {
        "label": "🛢 WTI OIL",
        "title": "WTI Oil AI Trading Command Center",
        "href": "/WTI_Oil_Command_Center",
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
        .market-nav-link {
            display:flex;
            align-items:center;
            justify-content:center;
            min-height:46px;
            width:100%;
            padding:.45rem .55rem;
            border-radius:11px;
            border:1px solid rgba(22,135,255,.72);
            background:linear-gradient(180deg,rgba(10,31,53,.98),rgba(7,22,39,.98));
            box-shadow:0 6px 18px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.08) inset;
            color:#f4f8ff !important;
            text-decoration:none !important;
            font-weight:850;
            font-size:.84rem;
            letter-spacing:.02em;
            text-align:center;
            line-height:1.15;
        }
        .market-nav-link:hover {
            border-color:#45a0ff;
            box-shadow:0 0 18px rgba(22,135,255,.18);
        }
        .market-nav-active {
            border-color:#45a0ff;
            box-shadow:0 0 18px rgba(22,135,255,.22), 0 0 0 1px rgba(22,135,255,.14) inset;
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
    """Five-link market switcher shared by every command center.

    Uses plain browser links instead of st.switch_page/st.page_link so Streamlit
    Community Cloud cannot reject valid multipage routes during startup.
    """
    active = active if active in MARKETS else "btc"
    _nav_css()
    st.markdown('<div class="market-switcher-label">COMMAND CENTER</div>', unsafe_allow_html=True)
    cols = st.columns(5, gap="small")

    for col, (key, cfg) in zip(cols, MARKETS.items()):
        with col:
            active_class = " market-nav-active" if key == active else ""
            label = f"● {cfg['label']}" if key == active else cfg["label"]
            st.markdown(
                f'<a class="market-nav-link{active_class}" href="{cfg["href"]}" target="_self">{label}</a>',
                unsafe_allow_html=True,
            )

    st.markdown(
        '<div class="market-switcher-note">Bitcoin, Gold, Gas Prices, ZEC and WTI command centers are available from the navigation above.</div>',
        unsafe_allow_html=True,
    )
