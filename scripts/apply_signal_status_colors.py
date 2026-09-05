from pathlib import Path

p = Path("app.py")
text = p.read_text()

old = '''        if bool(auto_state["enabled"]):
            st.success(auto_result["message"] if auto_result.get("message") else auto_state.get("last_message", "AUTO PAPER running."))
        else:
            st.info("AUTO PAPER TRADING is off. Turn it on in the sidebar to let approved paper signals execute automatically.")
'''

new = '''        if bool(auto_state["enabled"]):
            _status_message = auto_result["message"] if auto_result.get("message") else auto_state.get("last_message", "AUTO PAPER running.")
            _status_side = str(auto_state.get("side", "NONE")).upper()
            _decision_action = str(decision.get("action", "HOLD")).upper()
            if _status_side == "LONG" or _decision_action in {"SCALP UP", "LOCK UP", "UP"}:
                st.success(_status_message)
            elif _status_side == "SHORT" or _decision_action in {"SCALP DOWN", "LOCK DOWN", "DOWN"}:
                st.error(_status_message)
            else:
                st.info(_status_message)
        else:
            st.info("AUTO PAPER TRADING is off. Turn it on in the sidebar to let approved paper signals execute automatically.")
'''

if old not in text:
    if new in text:
        print("Signal status colors already applied.")
    else:
        raise SystemExit("AUTO PAPER status block not found; refusing partial update")
else:
    text = text.replace(old, new, 1)

text = text.replace(
    'APP_VERSION = "2026.09.05-r51-up-down-position-labels"',
    'APP_VERSION = "2026.09.05-r52-signal-status-colors"',
    1,
)

p.write_text(text)
