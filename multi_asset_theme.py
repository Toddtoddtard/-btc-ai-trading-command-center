import html

import pandas as pd
import streamlit as st


_ORIGINAL_DATAFRAME = st.dataframe


def _signal_badge(value):
    text = str(value if value is not None else "").strip()
    upper = text.upper()
    if upper in {"BULLISH", "UP", "SCALP UP", "LOCK UP", "LONG", "BUY", "YES"}:
        cls = "multi-council-positive"
    elif upper in {"BEARISH", "DOWN", "SCALP DOWN", "LOCK DOWN", "SHORT", "SELL", "NO"}:
        cls = "multi-council-negative"
    else:
        cls = "multi-council-neutral"
    return f'<span class="multi-council-badge {cls}">{html.escape(text)}</span>'


def _dark_dataframe(data=None, *args, **kwargs):
    """Render non-BTC dataframe surfaces like the BTC AI Council in dark mode."""
    try:
        df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    except Exception:
        return _ORIGINAL_DATAFRAME(data, *args, **kwargs)

    if df.empty:
        return _ORIGINAL_DATAFRAME(data, *args, **kwargs)

    formatters = {}
    for col in df.columns:
        name = str(col).strip().lower()
        if name in {"signal", "used", "direction", "action", "side", "status"}:
            formatters[col] = _signal_badge
        else:
            formatters[col] = lambda value: html.escape(str(value if value is not None else ""))

    table_html = df.to_html(
        index=False,
        border=0,
        classes="multi-council-table",
        escape=False,
        formatters=formatters,
    )
    st.markdown(
        f'<div class="multi-council-wrap">{table_html}</div>',
        unsafe_allow_html=True,
    )


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

    # The native Streamlit dataframe canvas remains bright on some browsers even
    # when the surrounding app is dark. Bitcoin already avoids that by rendering
    # its council as HTML, so non-BTC command centers do the same while dark mode
    # is enabled. Each command center remains a separate page.
    st.dataframe = _dark_dataframe if dark_mode else _ORIGINAL_DATAFRAME

    if dark_mode:
        st.markdown(
            """
            <style>
            :root { color-scheme: dark; }
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
            [data-testid="stSidebar"] * { color: #e8f1ff !important; }
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
            div[data-testid="stTabs"] button { color: #c9daf3 !important; }
            div[data-testid="stTabs"] button[aria-selected="true"] {
                color: #ffffff !important;
                border-bottom-color: #1687ff !important;
            }
            .stAlert, [data-testid="stAlert"] {
                background-color: rgba(10,24,40,.96) !important;
                color: #eef5ff !important;
            }
            .stAlert *, [data-testid="stAlert"] * { color: #eef5ff !important; }
            button, [data-testid="stBaseButton-secondary"] {
                border-color: rgba(22,135,255,.58) !important;
            }

            /* Bitcoin-style dark AI Council table. */
            .multi-council-wrap {
                width:100%; overflow-x:auto;
                border:1px solid #1687ff;
                border-radius:12px;
                background:#0b1220;
                box-shadow:0 10px 28px rgba(0,0,0,.18);
            }
            .multi-council-table {
                width:100%; border-collapse:collapse;
                color:#e8eef8; background:#0b1220;
                font-size:.93rem; margin:0;
            }
            .multi-council-table thead th {
                text-align:left; color:#b8cff7;
                background:#111c2e; font-weight:700;
                border-bottom:1px solid #2b3b52;
                padding:10px 12px; white-space:nowrap;
            }
            .multi-council-table tbody td {
                color:#e7edf7; background:#0b1220;
                border-bottom:1px solid #1e2b3d;
                padding:9px 12px; vertical-align:middle;
                white-space:nowrap;
            }
            .multi-council-table tbody tr:nth-child(even) td { background:#0f1828; }
            .multi-council-table tbody tr:hover td { background:#15243a; }
            .multi-council-badge {
                display:inline-block; min-width:78px;
                text-align:center; padding:4px 9px;
                border-radius:7px; font-weight:800;
                letter-spacing:.02em; line-height:1.2;
                box-sizing:border-box;
            }
            .multi-council-positive {
                color:#00f0b5; background:rgba(0,240,181,.13);
                border:1px solid rgba(0,240,181,.80);
            }
            .multi-council-negative {
                color:#ff536b; background:rgba(255,83,107,.13);
                border:1px solid rgba(255,83,107,.85);
            }
            .multi-council-neutral {
                color:#b8c6dc; background:rgba(184,198,220,.09);
                border:1px solid rgba(184,198,220,.42);
            }

            /* Keep JSON/diagnostics dark instead of Streamlit's white code surface. */
            [data-testid="stJson"], [data-testid="stJson"] > div,
            [data-testid="stJson"] pre, [data-testid="stJson"] code,
            [data-testid="stCode"], [data-testid="stCodeBlock"], pre, code {
                background: #0a111b !important;
                color: #d9e8ff !important;
                border-color: rgba(22,135,255,.45) !important;
            }
            [data-testid="stJson"] {
                border: 1px solid rgba(22,135,255,.55) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
            }
            [data-testid="stJson"] svg, [data-testid="stJson"] button {
                color: #9fc8ff !important;
                fill: #9fc8ff !important;
            }

            [data-testid="stDataFrame"], [data-testid="stTable"], [data-testid="stDataEditor"] {
                background: #0a111b !important;
                color: #e7f1ff !important;
                border: 1px solid rgba(22,135,255,.48) !important;
                border-radius: 12px !important;
                overflow: hidden !important;
            }
            [data-testid="stTable"] table, [data-testid="stTable"] thead,
            [data-testid="stTable"] tbody, [data-testid="stTable"] tr,
            [data-testid="stTable"] th, [data-testid="stTable"] td {
                background: #0a111b !important;
                color: #e7f1ff !important;
                border-color: rgba(93,128,166,.28) !important;
            }
            [data-testid="stTable"] th {
                background: #0d1a29 !important;
                color: #9fc8ff !important;
            }

            [data-baseweb="input"] > div, [data-baseweb="select"] > div,
            [data-baseweb="textarea"] > div, [data-testid="stExpander"] details,
            [data-testid="stPopoverBody"], [role="dialog"] {
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
            [data-baseweb="menu"] * { color: #eef5ff !important; }
            [data-testid="stDownloadButton"] button,
            [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {
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
