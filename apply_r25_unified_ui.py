from pathlib import Path

p = Path('app.py')
s = p.read_text()

# Always work from the current R23/R24 line without touching trading logic.
s = s.replace('APP_VERSION = "2026.09.04-single-file-r23-directional-call-badges"', 'APP_VERSION = "2026.09.04-single-file-r25-unified-council-style"')
s = s.replace('APP_VERSION = "2026.09.04-single-file-r24-large-call-cards"', 'APP_VERSION = "2026.09.04-single-file-r25-unified-council-style"')

# Add the larger blue-framed directional cards if R24 has not already landed.
if '.direction-card {' not in s:
    anchor = '''    .direction-call.call-neutral {\n        color:#c2d1e6; background:rgba(140,160,190,.11);\n        border-color:rgba(140,160,190,.45);\n    }\n'''
    insert = anchor + '''    .direction-card {\n        width:100%; min-height:92px; box-sizing:border-box;\n        display:flex; align-items:center; justify-content:center;\n        padding:14px 16px; border-radius:13px;\n        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));\n        border:1px solid #1687ff;\n        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;\n    }\n    .direction-card .direction-call {\n        min-width:150px; padding:10px 18px; font-size:1.08rem;\n    }\n    .direction-card.verdict-card {\n        width:min(100%, 330px); min-height:82px; justify-content:flex-start;\n    }\n    .direction-card.verdict-card .direction-call {min-width:165px;}\n'''
    if anchor not in s:
        raise SystemExit('directional CSS anchor missing')
    s = s.replace(anchor, insert, 1)

# Unify all metric/card/table/alert styling in dark mode so every tab feels like AI Council.
style_anchor = '''        [data-testid="stMetric"] {\n            background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96)) !important;\n            border:1px solid var(--cc-border) !important;\n            border-radius:13px !important;\n            padding:.85rem 1rem !important;\n            box-shadow:0 10px 28px rgba(0,0,0,.18) !important;\n        }\n'''
style_repl = '''        [data-testid="stMetric"] {\n            background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96)) !important;\n            border:1px solid #1687ff !important;\n            border-radius:13px !important;\n            padding:.85rem 1rem !important;\n            min-height:92px !important;\n            box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.08) inset !important;\n        }\n        [data-testid="stMetric"]:hover {border-color:#4aa3ff !important;}\n        [data-testid="stTabs"] [data-testid="stVerticalBlock"] > div {\n            border-radius:12px;\n        }\n        [data-testid="stTabs"] h2, [data-testid="stTabs"] h3 {\n            padding-bottom:.35rem;\n            border-bottom:1px solid rgba(22,135,255,.24);\n        }\n'''
if style_anchor in s:
    s = s.replace(style_anchor, style_repl, 1)

alert_anchor = '''        [data-testid="stAlert"] {\n            background:#0a1a2d !important;\n            border:1px solid #24466b !important;\n            border-radius:12px !important;\n            color:#eaf2ff !important;\n        }\n'''
alert_repl = '''        [data-testid="stAlert"] {\n            background:linear-gradient(180deg,#0a1a2d,#081522) !important;\n            border:1px solid #1687ff !important;\n            border-radius:12px !important;\n            color:#eaf2ff !important;\n            box-shadow:0 8px 22px rgba(0,0,0,.14) !important;\n        }\n'''
if alert_anchor in s:
    s = s.replace(alert_anchor, alert_repl, 1)

# Main header Master card.
old = '    m3.metric("Master", decision["action"])\n'
new = '''    with m3:\n        st.caption("Master")\n        st.markdown(\n            f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>',\n            unsafe_allow_html=True,\n        )\n'''
if old in s:
    s = s.replace(old, new, 1)

# Market tab CALL card.
old = '            call1.metric("CALL", decision["action"])\n'
new = '''            with call1:\n                st.caption("CALL")\n                st.markdown(\n                    f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>',\n                    unsafe_allow_html=True,\n                )\n'''
if old in s:
    s = s.replace(old, new, 1)

# AI Council main call card.
old = '''        with d1:\n            st.caption("Call")\n            st.markdown(directional_badge_html(decision["action"]), unsafe_allow_html=True)\n'''
new = '''        with d1:\n            st.caption("Call")\n            st.markdown(\n                f'<div class="direction-card">{directional_badge_html(decision["action"])}</div>',\n                unsafe_allow_html=True,\n            )\n'''
if old in s:
    s = s.replace(old, new, 1)

# Council verdict card.
old = '''        st.markdown("### Council verdict")\n        st.markdown(directional_badge_html(action), unsafe_allow_html=True)\n        st.write(plain_call)\n'''
new = '''        st.markdown("### Council verdict")\n        st.markdown(\n            f'<div class="direction-card verdict-card">{directional_badge_html(action)}</div>',\n            unsafe_allow_html=True,\n        )\n        st.write(plain_call)\n'''
if old in s:
    s = s.replace(old, new, 1)

# Hourly direction gets same visual treatment.
old = '''        h3.metric(\n            "Direction",\n            hourly_ai["direction"],\n        )\n'''
new = '''        with h3:\n            st.caption("Direction")\n            st.markdown(\n                f'<div class="direction-card">{directional_badge_html(hourly_ai["direction"])}</div>',\n                unsafe_allow_html=True,\n            )\n'''
if old in s:
    s = s.replace(old, new, 1)

# Give all major tables the same blue framed container in dark mode.
s = s.replace('border: 1px solid #263447;\n                    border-radius: 12px; background: #0b1220;', 'border: 1px solid #1687ff;\n                    border-radius: 12px; background: #0b1220;', 1)

# Syntax validation before writing.
compile(s, 'app.py', 'exec')
p.write_text(s)
print('Applied R25 unified AI Council-style UI across dashboard tabs.')
