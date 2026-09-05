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
            :root {
                color-scheme: dark;
            }
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
                color: #e8f1ff !important;
            }
            h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stCaption {
                color: #eef5ff !important;
            }
            [data-testid="stMetric"] {
                background: linear-gradient(180deg, rgba(11,27,47,.96), rgba(7,20,35,.96)) !important;
                border: 1px solid rgba(22,135,255,.55) !important;
                border-radius: 12px !important;
                padding: .65rem .8rem !important;
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
            .stAlert *, [data-testid="stAlert"] * {
                color: #eef5ff !important;
            }
            button, [data-testid="stBaseButton-secondary"] {
                border-color: rgba(22,135,255,.58) !important;
            }

            /* Keep JSON/diagnostics dark instead of Streamlit's white code surface. */
            [data-testid="stJson"],
            [data-testid="stJson"] > div,
            [data-testid="stJson"] pre,
            [data-testid="stJson"] code,
            [data-testid="stCode"],
            [data-testid="stCodeBlock"],
            pre, code {
                background: #0a111b !important;
                color: #d9e8ff !important;
                border-color: rgba(22,135,255,.45) !important;
            }
            [data-testid="stJson"] {
                border: 1px solid rgba(22,135,255,.55) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
            }
            [data-testid="stJson"] svg,
            [data-testid="stJson"] button {
                color: #9fc8ff !important;
                fill: #9fc8ff !important;
            }

            /* Dark containers around dataframe/table components. */
            [data-testid="stDataFrame"],
            [data-testid="stTable"],
            [data-testid="stDataEditor"] {
                background: #0a111b !important;
                color: #e7f1ff !important;
                border: 1px solid rgba(22,135,255,.48) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
            }
            [data-testid="stTable"] table,
            [data-testid="stTable"] thead,
            [data-testid="stTable"] tbody,
            [data-testid="stTable"] tr,
            [data-testid="stTable"] th,
            [data-testid="stTable"] td {
                background: #0a111b !important;
                color: #e7f1ff !important;
                border-color: rgba(93,128,166,.28) !important;
            }
            [data-testid="stTable"] th {
                background: #0d1a29 !important;
                color: #9fc8ff !important;
            }

            /* Inputs/selectors/expanders should never flash as bright white cards. */
            [data-baseweb="input"] > div,
            [data-baseweb="select"] > div,
            [data-baseweb="textarea"] > div,
            [data-testid="stExpander"] details,
            [data-testid="stPopoverBody"],
            [role="dialog"] {
                background: #0a111b !important;
                color: #eef5ff !important;
                border-color: rgba(22,135,255,.42) !important;
            }
            input, textarea {
                color: #eef5ff !important;
                caret-color: #ffffff !important;
            }
            [data-baseweb="menu"], [data-baseweb="popover"] {
                background: #0a111b !important;
                color: #eef5ff !important;
            }
            [data-baseweb="menu"] * {
                color: #eef5ff !important;
            }

            /* Download buttons, status pills and generic bordered blocks. */
            [data-testid="stDownloadButton"] button,
            [data-testid="stForm"],
            [data-testid="stVerticalBlockBorderWrapper"] {
                background-color: #0a111b !important;
                color: #eef5ff !important;
                border-color: rgba(22,135,255,.42) !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            :root { color-scheme: light; }
            html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
                background: #ffffff !important;
                color: #111827 !important;
            }
            [data-testid="stHeader"] { background: rgba(255,255,255,.96) !important; }
            [data-testid="stSidebar"] { background: #f6f8fb !important; }
            [data-testid="stSidebar"] * { color: #111827 !important; }
            h1, h2, h3, h4, h5, h6, p, label, .stMarkdown, .stCaption { color: #111827 !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )

    return dark_mode
