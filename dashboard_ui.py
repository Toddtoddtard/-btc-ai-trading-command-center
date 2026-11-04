"""Presentation helpers shared by the Streamlit dashboard.

This module deliberately contains no trading or persistence logic. Keeping
formatting here makes ``app.py`` easier to audit without changing decisions.
"""

from html import escape

import pandas as pd

from display_time import eastern_table


def fmt_money(value):
    return "N/A" if pd.isna(value) else f"${value:,.2f}"


def fmt_pct(value, digits=2):
    return "N/A" if pd.isna(value) else f"{value:.{digits}f}%"


def directional_badge_html(label, compact=False):
    """Return the existing visual-only badge for a directional call."""
    text = str(label or "HOLD").upper().strip()
    if any(key in text for key in ("LOCK UP", "SCALP UP", "OUTLOOK UP", "BULLISH")) or text == "UP":
        css_class, icon = "call-up", "▲"
    elif any(key in text for key in ("LOCK DOWN", "SCALP DOWN", "OUTLOOK DOWN", "BEARISH")) or text == "DOWN":
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

    dataframe = eastern_table(dataframe)
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


def metric_cards_html(cards):
    """Small responsive cards without Streamlit's lazy metric JS module."""
    body = ''.join(
        '<div class="technical-card" role="listitem"><div class="technical-label">'
        + escape(str(label)) + '</div><div class="technical-value">'
        + escape('Unavailable' if value is None else str(value)) + '</div></div>'
        for label, value in cards
    )
    return """<style>
.technical-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:12px 0}
.technical-card{border:1px solid var(--cc-border,#34404d);border-radius:12px;padding:14px;background:var(--cc-panel,#1b232c);color:var(--cc-text,#e6ebef);min-width:0}
.technical-label{font-size:.85rem;color:var(--cc-muted,#a8b4c0);margin-bottom:6px}
.technical-value{font-size:1.35rem;font-weight:700;overflow-wrap:anywhere}
@media(max-width:700px){.technical-cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style><div class="technical-cards" role="list">""" + body + '</div>'


def dashboard_theme_css(dark=True):
    """One quiet, responsive theme; colors never replace status text or warnings."""
    palette = (
        '--cc-bg:#11171d;--cc-panel:#1b232c;--cc-panel2:#202b36;'
        '--cc-border:#34404d;--cc-text:#e6ebef;--cc-muted:#a8b4c0;'
        '--cc-accent:#9abfdf;--cc-up:#87d4b6;--cc-down:#f0a5ac;'
    ) if dark else (
        '--cc-bg:#f3f5f7;--cc-panel:#ffffff;--cc-panel2:#e8eef3;'
        '--cc-border:#ccd5de;--cc-text:#202c38;--cc-muted:#526477;'
        '--cc-accent:#275b86;--cc-up:#176448;--cc-down:#a43340;'
    )
    return '<style>:root{' + palette + '}' + """
html,body,.stApp,[data-testid="stAppViewContainer"]{
    background:var(--cc-bg)!important;color:var(--cc-text)!important}
[data-testid="stHeader"]{background:var(--cc-bg)!important}
[data-testid="stSidebar"]{background:var(--cc-panel)!important;border-right:1px solid var(--cc-border)}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] label{color:var(--cc-text)}
.block-container{max-width:1360px;padding-top:1.2rem!important;padding-bottom:3rem}
h1,h2,h3,h4{color:var(--cc-text)!important;letter-spacing:-.025em;line-height:1.25!important}
h1{font-size:clamp(1.65rem,3vw,2.5rem)!important}
h2{font-size:clamp(1.4rem,2.2vw,1.9rem)!important}
h3{font-size:clamp(1.15rem,1.8vw,1.5rem)!important}
[data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:var(--cc-muted)!important;line-height:1.55}
hr{border-color:var(--cc-border)!important}
[data-testid="stMetric"],.direction-card,.confidence-metric-card,.pro-ticket{
    background:var(--cc-panel)!important;border:1px solid var(--cc-border)!important;
    border-radius:12px!important;box-shadow:none!important;min-width:0}
[data-testid="stMetric"]{padding:.9rem 1rem!important;min-height:100px!important}
[data-testid="stMetricLabel"],.direction-card-label,.confidence-metric-label,.pro-ticket-label{
    color:var(--cc-muted)!important;white-space:normal!important;line-height:1.4!important}
[data-testid="stMetricValue"],.confidence-metric-value,.pro-ticket-value{
    color:var(--cc-text)!important;font-weight:650!important}
[data-testid="stMetricValue"]{font-size:clamp(1.05rem,1.6vw,1.5rem)!important}
.direction-card,.confidence-metric-card{min-height:100px!important}
.direction-card.metric-direction-card .direction-call{padding:0;font-size:1rem;border:0}
.direction-card-value{justify-content:flex-start}
.direction-call{font-weight:650;box-shadow:none!important;min-width:0!important;max-width:100%;
    white-space:normal;line-height:1.3}
.direction-call.call-up{color:var(--cc-up);background:transparent;border-color:var(--cc-border)}
.direction-call.call-down{color:var(--cc-down);background:transparent;border-color:var(--cc-border)}
.direction-call.call-neutral{color:var(--cc-muted);background:transparent;border-color:var(--cc-border)}
.pro-ticket-cell{background:var(--cc-panel2);border-color:var(--cc-border)}
.pro-ticket-title,.pro-ticket-value{color:var(--cc-text)}
.pro-ticket-label,.pro-ticket-protection{color:var(--cc-muted)}
.paper-banner{background:var(--cc-panel)!important;border:1px solid var(--cc-border)!important;
    color:var(--cc-muted)!important;font-weight:500;font-size:.85rem;padding:.65rem .9rem}
[data-testid="stTabs"] [role="tablist"]{gap:.25rem!important;padding:.3rem!important;
    border-bottom:1px solid var(--cc-border);background:transparent!important;overflow-x:auto}
[data-testid="stTabs"] [role="tab"]{white-space:nowrap;border-radius:8px;padding:.5rem .8rem!important;
    color:var(--cc-muted)!important;background:transparent!important;min-height:44px;font-weight:500!important}
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{
    background:var(--cc-panel2)!important;color:var(--cc-accent)!important;font-weight:650!important}
[data-baseweb="tab-highlight"]{background:var(--cc-accent)!important}
[data-testid="stTabs"] .react-aria-SelectionIndicator{background:var(--cc-accent)!important}
[data-testid="stAlertContainer"]{background:var(--cc-panel2)!important;border:1px solid var(--cc-border);
    border-left:4px solid var(--cc-accent);border-radius:10px}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]){border-left-color:#d5ad67}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]){border-left-color:var(--cc-down)}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]){border-left-color:var(--cc-up)}
[data-testid="stAlertContainer"] p,[data-testid="stAlertContainer"] li{color:var(--cc-text)!important}
[data-testid="stExpander"],[data-testid="stForm"],[data-testid="stDataFrame"],[data-testid="stTable"]{
    border:1px solid var(--cc-border)!important;border-radius:12px!important;background:var(--cc-panel)!important;
    box-shadow:none!important}
[data-testid="stExpander"] summary{min-height:48px;color:var(--cc-text)}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,input,textarea{
    background:var(--cc-panel)!important;color:var(--cc-text)!important;border-color:var(--cc-border)!important}
.stButton>button,.stDownloadButton>button{background:var(--cc-panel2)!important;color:var(--cc-text)!important;
    border:1px solid var(--cc-border)!important;border-radius:9px;min-height:44px;box-shadow:none!important}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--cc-accent)!important}
button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--cc-accent)!important;outline-offset:3px}
.dashboard-dark-wrap,.dashboard-dark-table{background:var(--cc-panel)!important;border-color:var(--cc-border)!important}
.dashboard-dark-table thead th{background:var(--cc-panel2)!important;color:var(--cc-text)!important}
.dashboard-dark-table tbody td{background:var(--cc-panel)!important;color:var(--cc-text)!important;border-color:var(--cc-border)!important}
.dash-positive{color:var(--cc-up)!important;background:transparent!important;border-color:var(--cc-border)!important}
.dash-negative{color:var(--cc-down)!important;background:transparent!important;border-color:var(--cc-border)!important}
.dash-neutral{color:var(--cc-muted)!important;background:transparent!important;border-color:var(--cc-border)!important}
@media(max-width:700px){
    .block-container{padding-left:1rem!important;padding-right:1rem!important}
    [data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"] [data-testid="stMetric"]){
        display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem!important}
    [data-testid="stHorizontalBlock"]:has(>[data-testid="stColumn"] [data-testid="stMetric"])>[data-testid="stColumn"]{
        width:100%!important;min-width:0!important}
    [data-testid="stMetric"]{padding:.75rem!important}
    [data-testid="stMetricValue"]{font-size:1.2rem!important}
    .confidence-metric-label{flex-wrap:wrap}
    .technical-cards{gap:.65rem}
    .technical-value{font-size:1.15rem}
}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style>"""
