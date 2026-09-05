from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old = '    m4.metric("Confidence", f"{decision[\'confidence\']*100:.1f}%")'

new = """    # Confidence card only: keep every other top metric unchanged and add the
    # Master directional lean beside the Confidence label.
    _confidence_action = str(decision.get("action", "HOLD")).upper().strip()
    if "UP" in _confidence_action:
        _confidence_direction = "UP"
    elif "DOWN" in _confidence_action:
        _confidence_direction = "DOWN"
    else:
        _confidence_score = safe_float(
            decision.get("base_score"),
            safe_float(decision.get("score"), 0.0),
        )
        _confidence_direction = "UP" if _confidence_score >= 0 else "DOWN"

    _confidence_color = "#20f0bd" if _confidence_direction == "UP" else "#ff5d72"
    _confidence_arrow = "▲" if _confidence_direction == "UP" else "▼"
    with m4:
        st.markdown(
            f\"\"\"
            <div class=\"confidence-metric-card\">
                <div class=\"confidence-metric-label\">
                    Confidence
                    <span style=\"color:{_confidence_color};\">{_confidence_arrow}&nbsp;{_confidence_direction}</span>
                </div>
                <div class=\"confidence-metric-value\">{decision['confidence']*100:.1f}%</div>
            </div>
            \"\"\",
            unsafe_allow_html=True,
        )"""

if old not in s:
    if 'class="confidence-metric-card"' in s:
        print("Confidence direction card already installed")
        raise SystemExit(0)
    raise SystemExit("Confidence metric anchor not found")

s = s.replace(old, new, 1)

css_anchor = """    .direction-card.metric-direction-card .direction-call {
        min-width:min(150px, 100%);
        max-width:100%;
        box-sizing:border-box;
    }
"""
css_insert = """    .direction-card.metric-direction-card .direction-call {
        min-width:min(150px, 100%);
        max-width:100%;
        box-sizing:border-box;
    }
    .confidence-metric-card {
        min-height:92px;
        box-sizing:border-box;
        padding:.45rem .6rem;
    }
    .confidence-metric-label {
        color:#9fb2ce;
        font-size:.90rem;
        line-height:1.15;
        font-weight:500;
        white-space:nowrap;
        display:flex;
        align-items:center;
        gap:.32rem;
    }
    .confidence-metric-label span {
        font-size:.72rem;
        font-weight:800;
        letter-spacing:.02em;
    }
    .confidence-metric-value {
        font-size:1.55rem;
        font-weight:750;
        line-height:1.65;
    }
"""

if ".confidence-metric-card {" not in s:
    if css_anchor not in s:
        raise SystemExit("Confidence CSS anchor not found")
    s = s.replace(css_anchor, css_insert, 1)

p.write_text(s, encoding="utf-8")
print("Installed Confidence UP/DOWN indicator only")
