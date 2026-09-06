from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Anchor not found for {label}")
    return text.replace(old, new, 1)


# C3 — separate raw graded model output from chart-only decoration.
ai = Path("ai_core.py")
text = ai.read_text()
old = '''    min_visible = max(avg_range * 0.35, last * 0.00015)
    if abs(projected_move) < min_visible:
        projected_move = np.sign(projected_move or directional or 1.0) * min_visible
    forecast = []
    prev_close = last
    for i in range(1,16):
        progress = i/15.0
        eased = progress*progress*(3.0-2.0*progress)
        center = last + projected_move*eased
        wave = np.sin(i*1.35)*avg_range*0.16 + np.cos(i*0.72)*avg_range*0.08
        close = float(center + wave)
        open_ = float(prev_close)
        body = abs(close-open_)
        wick = max(avg_range*(0.18+0.08*progress), body*0.35)
        forecast.append({"step":i,"open":open_,"high":max(open_,close)+wick,"low":min(open_,close)-wick,"close":close})
        prev_close = close
    return {"inputs":inputs,"forecast":forecast,"predicted_end":float(forecast[-1]["close"]),"predicted_direction":1 if forecast[-1]["close"] >= last else -1}
'''
new = '''    # The raw model move is the ONLY value used for grading, calibration,
    # backtests and champion/challenger evaluation.  Presentation helpers below
    # may make a near-flat path visible, but can never alter the scored target.
    raw_projected_move = float(projected_move)
    raw_predicted_end = float(last + raw_projected_move)
    raw_predicted_direction = 1 if raw_projected_move > 0 else -1 if raw_projected_move < 0 else 0

    # Chart-only presentation path.  A minimum visible move and small wave make
    # the forecast readable on screen without contaminating model evidence.
    display_move = raw_projected_move
    min_visible = max(avg_range * 0.35, last * 0.00015)
    if abs(display_move) < min_visible:
        display_move = np.sign(display_move or directional or 1.0) * min_visible
    forecast = []
    prev_close = last
    for i in range(1,16):
        progress = i/15.0
        eased = progress*progress*(3.0-2.0*progress)
        center = last + display_move*eased
        wave = np.sin(i*1.35)*avg_range*0.16 + np.cos(i*0.72)*avg_range*0.08
        close = float(center + wave)
        open_ = float(prev_close)
        body = abs(close-open_)
        wick = max(avg_range*(0.18+0.08*progress), body*0.35)
        forecast.append({"step":i,"open":open_,"high":max(open_,close)+wick,"low":min(open_,close)-wick,"close":close})
        prev_close = close
    return {
        "inputs": inputs,
        "forecast": forecast,
        "predicted_end": raw_predicted_end,
        "predicted_direction": raw_predicted_direction,
        "raw_projected_move": raw_projected_move,
        "display_predicted_end": float(forecast[-1]["close"]),
    }
'''
text = replace_once(text, old, new, "C3 raw forecast grading")
ai.write_text(text)


# H2 — risk_evaluate becomes sizing / exposure control only.  Directional
# confidence/consensus/source-health gates already ran in master_decision and
# learned_trade_gate.  Removing duplicates makes WAIT causes attributable.
app = Path("app.py")
text = app.read_text()
old = '''    if decision["action"] in {"HOLD", "LOCK UP", "LOCK DOWN"}:
        reason = "LOCK: hold current Kalshi call to expiration" if decision["action"].startswith("LOCK") else "HOLD signal"
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": reason}
    if source_health < 0.60:
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "Market-data health below reliability floor"}
    if confidence < learned_conf_floor:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.9, "reason": f"Confidence below learned floor ({learned_conf_floor:.0%})"}
    if consensus < 0.30:
        return {"approved": False, "position_pct": 0.0, "risk_score": 0.8, "reason": "Specialist consensus too low"}
'''
new = '''    if decision["action"] in {"HOLD", "WAIT"}:
        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "No trade signal"}

    # Confidence, consensus and source-health are authoritative upstream gates.
    # Do not silently apply a second, conflicting threshold here.  This layer
    # only sizes an already-approved PAPER action and controls exposure.
'''
text = replace_once(text, old, new, "H2 duplicate gate removal")

# The legacy spot-position check cannot veto a LOCK paper-contract decision.
old = '''    state = get_auto_state()
    if state["side"] != "NONE":
        return {
            "approved": False,
            "position_pct": 0.0,
            "risk_score": risk_score,
            "reason": f"Paper {state['side']} already open",
        }

    return {"approved": True, "position_pct": position_pct, "risk_score": risk_score, "reason": "Paper-trade risk checks passed"}
'''
new = '''    state = get_auto_state()
    if state["side"] != "NONE" and not str(decision.get("action", "")).startswith("LOCK"):
        return {
            "approved": False,
            "position_pct": 0.0,
            "risk_score": risk_score,
            "reason": f"Paper {state['side']} already open",
        }

    return {"approved": True, "position_pct": position_pct, "risk_score": risk_score, "reason": "Authoritative decision gate passed; paper exposure sized"}
'''
text = replace_once(text, old, new, "H2 exposure-only risk layer")
app.write_text(text)

print("External review phase 1 applied: C3 raw grading + H2 duplicate gate cleanup")
