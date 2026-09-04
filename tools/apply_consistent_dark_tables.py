from pathlib import Path

p = Path('app.py')
s = p.read_text()

helper = r'''

def render_dashboard_table(df, formatters=None):
    """Render dashboard tables with the same dark visual language as AI Council.

    Presentation only: underlying dataframe values and trading logic are untouched.
    """
    if not st.session_state.get("dashboard_dark_mode", True):
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    view = df.copy()
    fmts = dict(formatters or {})

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
            cls = "dash-positive"
        elif upper in negative or upper in {"0", "0.0"}:
            cls = "dash-negative"
        else:
            cls = "dash-neutral"
        return f'<span class="dash-badge {cls}">{text}</span>'

    semantic_cols = {
        "signal", "action", "direction", "trend", "correct", "resolved",
        "side", "approved", "result", "status",
    }
    for col in view.columns:
        if str(col).strip().lower() in semantic_cols and col not in fmts:
            fmts[col] = _semantic_badge

    table_html = view.to_html(
        index=False,
        border=0,
        classes="dashboard-dark-table",
        escape=False,
        formatters=fmts,
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
'''

if 'def render_dashboard_table(' not in s:
    anchor = '\ndef http_json(url, params=None, timeout=2.8):\n'
    if anchor not in s:
        raise SystemExit('Helper insertion anchor not found')
    s = s.replace(anchor, helper + anchor, 1)

replacements = {
    '            st.dataframe(show, use_container_width=True, hide_index=True)':
        '            render_dashboard_table(show)',
    '                st.dataframe(pd.DataFrame(krows), use_container_width=True, hide_index=True)':
        '                render_dashboard_table(pd.DataFrame(krows))',
    '            st.dataframe(trades, use_container_width=True, hide_index=True)':
        '            render_dashboard_table(trades)',
    '''        st.dataframe(
            rolling_master_df,
            use_container_width=True,
            hide_index=True,
        )''':
        '''        render_dashboard_table(rolling_master_df)''',
    '''            st.dataframe(
                specialist_multi,
                use_container_width=True,
                hide_index=True,
            )''':
        '''            render_dashboard_table(specialist_multi)''',
    '''            st.dataframe(
                specialist_df,
                use_container_width=True,
                hide_index=True,
            )''':
        '''            render_dashboard_table(specialist_df)''',
    '''            st.dataframe(
                learning_df,
                use_container_width=True,
                hide_index=True,
            )''':
        '''            render_dashboard_table(learning_df)''',
    '                st.dataframe(view, use_container_width=True, hide_index=True)':
        '                render_dashboard_table(view)',
}

for old, new in replacements.items():
    if old in s:
        s = s.replace(old, new, 1)

# Bump version only once after the journal r40 build.
s = s.replace(
    'APP_VERSION = "2026.09.04-r40-journal-dark-ui"',
    'APP_VERSION = "2026.09.04-r41-consistent-dark-tables"',
    1,
)

required = [
    'def render_dashboard_table(',
    'render_dashboard_table(show)',
    'render_dashboard_table(pd.DataFrame(krows))',
    'render_dashboard_table(trades)',
    'render_dashboard_table(rolling_master_df)',
    'render_dashboard_table(specialist_multi)',
    'render_dashboard_table(specialist_df)',
    'render_dashboard_table(learning_df)',
    'render_dashboard_table(view)',
    'r41-consistent-dark-tables',
]
missing = [x for x in required if x not in s]
if missing:
    raise SystemExit('Missing expected UI markers: ' + ', '.join(missing))

p.write_text(s)
print('Applied consistent dark dashboard tables')
