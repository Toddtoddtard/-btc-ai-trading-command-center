import streamlit as st


def apply_multi_asset_theme():
    """Give every non-BTC command center the same dark-mode behavior as Bitcoin.

    Reuses the shared `dashboard_dark_mode` session key so the preference carries
    between Bitcoin and the other command centers during the same Streamlit session.
    """
    dark_mode = st.sidebar.toggle(
        "🌙 Dark Mode",
        value=bool(st.session_state.get("dashboard_dark_mode", True)),
        key="multi_asset_dark_mode_toggle",
    )
    st.session_state["dashboard_dark_mode"] = dark_mode

    if dark_mode:
        st.markdown(
            """
            <style>
            html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
                background: #070b12 !important;
                color: #eef5ff !important;
            }
            [data-testid="stHeader"] {
                background: rgba(7,11,18,.94) !important;
            }
            [data-testid="stSidebar"] {
                background: #090f18 !important;
                border-right: 1px solid rgba(22,135,255,.22) !important;
            }
            [data-testid="stSidebar"] * {
                color: #e8f1ff;
            }
            h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stCaption {
                color: #eef5ff;
            }
            [data-testid="stMetric"] {
                background: linear-gradient(180deg, rgba(11,27,47,.96), rgba(7,20,35,.96));
                border: 1px solid rgba(22,135,255,.55);
                border-radius: 12px;
                padding: .65rem .8rem;
            }
            [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
                color: #eef5ff !important;
            }
            div[data-testid="stTabs"] button {
                color: #c9daf3 !important;
            }
            div[data-testid="stTabs"] button[aria-selected="true"] {
                color: #ffffff !important;
                border-bottom-color: #1687ff !important;
            }
            .stAlert, [data-testid="stAlert"] {
                background-color: rgba(10,24,40,.96) !important;
                color: #eef5ff !important;
            }
            button, [data-testid="stBaseButton-secondary"] {
                border-color: rgba(22,135,255,.58) !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
                background: #ffffff !important;
                color: #111827 !important;
            }
            [data-testid="stHeader"] { background: rgba(255,255,255,.96) !important; }
            [data-testid="stSidebar"] { background: #f6f8fb !important; }
            [data-testid="stSidebar"] * { color: #111827; }
            h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stCaption { color: #111827; }
            </style>
            """,
            unsafe_allow_html=True,
        )

    return dark_mode
