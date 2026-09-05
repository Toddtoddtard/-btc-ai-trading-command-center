from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")
old = '''    m4.metric("Confidence", f"{decision['confidence']*100:.1f}%")'''
new = '''    # Visual-only directional lean beside Confidence. For directional Master calls,
    # mirror the Master side; while HOLDing, show the side the Master score leans.
    _master_action = str(decision.get("action", "HOLD")).upper()
    if "UP" in _master_action:
        _confidence_direction = "UP"
    elif "DOWN" in _master_action:
        _confidence_direction = "DOWN"
    else:
        _confidence_direction = "UP" if safe_float(decision.get("base_score"), safe_float(decision.get("score"), 0.0)) >= 0 else "DOWN"
    _confidence_color = "#20f0bd" if _confidence_direction == "UP" else "#ff5d72"
    _confidence_arrow = "▲" if _confidence_direction == "UP" else "▼"
    with m4:
        st.markdown(
            f'''<div style="padding:.45rem .6rem;min-height:92px;box-sizing:border-box;">
                <div style="color:#9fb2ce;font-size:.90rem;line-height:1.15;font-weight:500;white-space:nowrap;">
                    Confidence <span style="font-size:.72rem;font-weight:800;color:{_confidence_color};margin-left:.28rem;">{_confidence_arrow} {_confidence_direction}</span>
                </div>
                <div style="font-size:1.55rem;font-weight:750;line-height:1.65;">{decision['confidence']*100:.1f}%</div>
            </div>''',
            unsafe_allow_html=True,
        )'''
if old not in s:
    if '_confidence_direction = "UP"' in s and 'Confidence <span' in s:
        print("Confidence direction UI already installed")
        raise SystemExit(0)
    raise SystemExit("Confidence metric anchor not found")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("Installed confidence UP/DOWN direction label")
