from pathlib import Path

p = Path('app.py')
s = p.read_text()

if 'single-file-r23-directional-call-badges' in s:
    print('R23 already applied')
    raise SystemExit(0)

# Add a reusable visual-only badge helper near generic helpers.
anchor = '''def fmt_pct(x, digits=2):\n    return "N/A" if pd.isna(x) else f"{x:.{digits}f}%"\n'''
helper = '''def fmt_pct(x, digits=2):\n    return "N/A" if pd.isna(x) else f"{x:.{digits}f}%"\n\n\ndef directional_badge_html(label, compact=False):\n    \"\"\"Visual-only badge for directional calls; does not change decision logic.\"\"\"\n    text = str(label or "HOLD").upper().strip()\n    if any(k in text for k in ("LOCK UP", "SCALP UP", "BULLISH")) or text == "UP":\n        cls, icon = "call-up", "▲"\n    elif any(k in text for k in ("LOCK DOWN", "SCALP DOWN", "BEARISH")) or text == "DOWN":\n        cls, icon = "call-down", "▼"\n    else:\n        cls, icon = "call-neutral", "•"\n    size_cls = " compact" if compact else ""\n    return f'<span class="direction-call {cls}{size_cls}">{icon}&nbsp;&nbsp;{text}</span>'\n'''
if anchor not in s:
    raise SystemExit('fmt_pct anchor not found')
s = s.replace(anchor, helper, 1)

# Add badge CSS to the global style block so it works in dark and light mode.
css_anchor = '''    .paper-banner {\n        padding: 0.7rem 1rem; border: 1px solid rgba(255,255,255,.15);\n        border-radius: 10px; margin-bottom: 0.8rem; font-weight: 700;\n    }\n'''
css = '''    .paper-banner {\n        padding: 0.7rem 1rem; border: 1px solid rgba(255,255,255,.15);\n        border-radius: 10px; margin-bottom: 0.8rem; font-weight: 700;\n    }\n    .direction-call {\n        display:inline-flex; align-items:center; justify-content:center;\n        min-width:116px; padding:7px 13px; border-radius:9px;\n        font-weight:800; letter-spacing:.02em; line-height:1;\n        border:1px solid transparent; box-shadow:0 0 18px rgba(0,0,0,.12);\n        white-space:nowrap;\n    }\n    .direction-call.compact {min-width:92px; padding:5px 10px; font-size:.9rem;}\n    .direction-call.call-up {\n        color:#20f0bd; background:rgba(0,230,179,.12);\n        border-color:rgba(0,230,179,.72); box-shadow:0 0 14px rgba(0,230,179,.13);\n    }\n    .direction-call.call-down {\n        color:#ff5d72; background:rgba(255,73,100,.12);\n        border-color:rgba(255,73,100,.78); box-shadow:0 0 14px rgba(255,73,100,.12);\n    }\n    .direction-call.call-neutral {\n        color:#c2d1e6; background:rgba(140,160,190,.11);\n        border-color:rgba(140,160,190,.45);\n    }\n'''
if css_anchor not in s:
    raise SystemExit('global CSS anchor not found')
s = s.replace(css_anchor, css, 1)

# Master call card: keep the label, replace plain text with the badge.
old = '        d1.metric("Call", decision["action"])\n'
new = '''        with d1:\n            st.caption("Call")\n            st.markdown(directional_badge_html(decision["action"]), unsafe_allow_html=True)\n'''
if old not in s:
    raise SystemExit('master Call metric anchor not found')
s = s.replace(old, new, 1)

# Friendly council verdict: use the same visual language.
old = '        st.markdown(f"### {call_icon} Council verdict: **{action}**")\n'
new = '''        st.markdown("### Council verdict")\n        st.markdown(directional_badge_html(action), unsafe_allow_html=True)\n'''
if old not in s:
    raise SystemExit('council verdict anchor not found')
s = s.replace(old, new, 1)

# When a side is locked, show the lock call itself as a colored badge too.
old = '''        if decision["action"] in {"LOCK UP", "LOCK DOWN"}:\n            st.warning(\n                f"LOCKED SIDE: {decision['locked_side']} — "\n                "hold call until Kalshi market expiration."\n            )\n'''
new = '''        if decision["action"] in {"LOCK UP", "LOCK DOWN"}:\n            st.markdown(directional_badge_html(decision["action"]), unsafe_allow_html=True)\n            st.warning(\n                f"LOCKED SIDE: {decision['locked_side']} — "\n                "hold call until Kalshi market expiration."\n            )\n'''
if old in s:
    s = s.replace(old, new, 1)

# Update version label. Support whichever R21/R22 version landed first.
for old_version in [
    'APP_VERSION = "2026.09.04-single-file-r22-signal-badges"',
    'APP_VERSION = "2026.09.04-single-file-r21-visual-dashboard"',
    'APP_VERSION = "2026.09.04-single-file-r21-dark-council-table"',
]:
    if old_version in s:
        s = s.replace(old_version, 'APP_VERSION = "2026.09.04-single-file-r23-directional-call-badges"', 1)
        break
else:
    print('Warning: version string not matched; continuing')

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R23 directional call badges applied successfully')
