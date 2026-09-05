from pathlib import Path

p = Path('app.py')
text = p.read_text()

anchor = '''def fmt_pct(x, digits=2):
    return "N/A" if pd.isna(x) else f"{x:.{digits}f}%"
'''
helper = '''def fmt_pct(x, digits=2):
    return "N/A" if pd.isna(x) else f"{x:.{digits}f}%"


def display_position_side(side):
    """UI-only translation: LONG means UP, SHORT means DOWN."""
    s = str(side or "NONE").upper().strip()
    if s == "LONG":
        return "LONG (UP)"
    if s == "SHORT":
        return "SHORT (DOWN)"
    if s in {"NONE", "HOLD", "WAIT"}:
        return "HOLD / NO TRADE"
    return s
'''

if 'def display_position_side(side):' not in text:
    if anchor not in text:
        raise SystemExit('fmt_pct anchor not found')
    text = text.replace(anchor, helper, 1)

text = text.replace('status2.metric("Position", auto_state["side"])', 'status2.metric("Position", display_position_side(auto_state["side"]))')
text = text.replace('p1.metric("Side", auto_state["side"])', 'p1.metric("Side", display_position_side(auto_state["side"]))')
text = text.replace('APP_VERSION = "2026.09.05-r50-global-metric-padding"', 'APP_VERSION = "2026.09.05-r51-up-down-position-labels"', 1)

p.write_text(text)
