"""Presentation helpers shared by the Streamlit dashboard.

This module deliberately contains no trading or persistence logic. Keeping
formatting here makes ``app.py`` easier to audit without changing decisions.
"""

import pandas as pd


def fmt_money(value):
    return "N/A" if pd.isna(value) else f"${value:,.2f}"


def fmt_pct(value, digits=2):
    return "N/A" if pd.isna(value) else f"{value:.{digits}f}%"


def directional_badge_html(label, compact=False):
    """Return the existing visual-only badge for a directional call."""
    text = str(label or "HOLD").upper().strip()
    if any(key in text for key in ("LOCK UP", "SCALP UP", "BULLISH")) or text == "UP":
        css_class, icon = "call-up", "▲"
    elif any(key in text for key in ("LOCK DOWN", "SCALP DOWN", "BEARISH")) or text == "DOWN":
        css_class, icon = "call-down", "▼"
    else:
        css_class, icon = "call-neutral", "•"
    size_class = " compact" if compact else ""
    return (
        f'<span class="direction-call {css_class}{size_class}">'
        f"{icon}&nbsp;&nbsp;{text}</span>"
    )


def _semantic_badge(value):
    text = str(value if value is not None else "").strip()
    upper = text.upper()
    positive = {
        "BULLISH", "UP", "SCALP UP", "LOCK UP", "LONG", "BUY",
        "CORRECT", "IMPROVING", "RESOLVED", "YES", "WIN", "TRUE",
    }
    negative = {
        "BEARISH", "DOWN", "SCALP DOWN", "LOCK DOWN", "SHORT", "SELL",
        "WRONG", "DECLINING", "LOSS", "NO", "FALSE",
    }
    if upper in positive or upper in {"1", "1.0"}:
        css_class = "dash-positive"
    elif upper in negative or upper in {"0", "0.0"}:
        css_class = "dash-negative"
    else:
        css_class = "dash-neutral"
    return f'<span class="dash-badge {css_class}">{text}</span>'


def render_dashboard_table(dataframe, formatters=None):
    """Render a table using the dashboard theme without altering its values."""
    import streamlit as st

    if not st.session_state.get("dashboard_dark_mode", True):
        st.dataframe(dataframe, use_container_width=True, hide_index=True)
        return

    view = dataframe.copy()
    resolved_formatters = dict(formatters or {})
    semantic_columns = {
        "signal", "action", "direction", "trend", "correct", "resolved",
        "side", "approved", "result", "status",
    }
    for column in view.columns:
        if str(column).strip().lower() in semantic_columns and column not in resolved_formatters:
            resolved_formatters[column] = _semantic_badge

    table_html = view.to_html(
        index=False,
        border=0,
        classes="dashboard-dark-table",
        escape=False,
        formatters=resolved_formatters,
    )
    st.markdown(
        """
        <style>
        .dashboard-dark-wrap {
            width:100%; overflow-x:auto; border:1px solid #1687ff;
            border-radius:12px; background:#0b1220;
        }
        .dashboard-dark-table {
            width:100%; border-collapse:collapse; color:#e8eef8;
            background:#0b1220; font-size:.93rem; margin:0;
        }
        .dashboard-dark-table thead th {
            position:sticky; top:0; z-index:1; text-align:left;
            color:#b8cff7; background:#111c2e; font-weight:700;
            border-bottom:1px solid #2b3b52; padding:10px 12px;
            white-space:nowrap;
        }
        .dashboard-dark-table tbody td {
            color:#e7edf7; background:#0b1220;
            border-bottom:1px solid #1e2b3d; padding:9px 12px;
            vertical-align:middle; white-space:nowrap;
        }
        .dashboard-dark-table tbody tr:nth-child(even) td {background:#0f1828;}
        .dashboard-dark-table tbody tr:hover td {background:#15243a;}
        .dash-badge {
            display:inline-block; min-width:78px; text-align:center;
            padding:4px 9px; border-radius:7px; font-weight:800;
            letter-spacing:.02em; line-height:1.2; box-sizing:border-box;
        }
        .dash-positive {
            color:#00f0b5; background:rgba(0,240,181,.13);
            border:1px solid rgba(0,240,181,.80);
        }
        .dash-negative {
            color:#ff536b; background:rgba(255,83,107,.13);
            border:1px solid rgba(255,83,107,.85);
        }
        .dash-neutral {
            color:#b8c6dc; background:rgba(184,198,220,.09);
            border:1px solid rgba(184,198,220,.42);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="dashboard-dark-wrap">{table_html}</div>',
        unsafe_allow_html=True,
    )
