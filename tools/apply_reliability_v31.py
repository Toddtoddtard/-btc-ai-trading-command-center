#!/usr/bin/env python3
from pathlib import Path
import re

P = Path("app.py")
text = P.read_text()


def require(condition, message):
    if not condition:
        raise SystemExit(message)

# Import reliability layer exactly once.
anchor = "from ai_core import enrich_history_core, forecast_path_core, run_specialists_core\n"
if "from reliability_v31 import" not in text:
    require(anchor in text, "ai_core import anchor not found")
    text = text.replace(anchor, anchor + "from reliability_v31 import (\n    calibrate_confidence, detect_regime, execution_cost_bps,\n    learned_policy, learned_trade_gate, regime_specialist_weight,\n    source_health_from_specialists,\n)\n", 1)

# Regime-aware specialist weights with shrinkage toward global learning.
if "def adaptive_specialist_weight(name, regime=None):" not in text:
    pattern = re.compile(r"def adaptive_specialist_weight\(name\):.*?(?=\ndef [A-Za-z_][A-Za-z0-9_]*\()", re.S)
    replacement = '''def adaptive_specialist_weight(name, regime=None):
    remote = fetch_remote_learning_state() or {}
    state = (remote.get("specialists", {}) or {}).get(name, {})
    base = safe_float(SPECIALIST_WEIGHTS.get(name), 1.0)
    regime = regime or "UNKNOWN"
    return regime_specialist_weight(base, state, regime)

'''
    text, n = pattern.subn(replacement, text, count=1)
    require(n == 1, "adaptive_specialist_weight patch failed")

# Master decision: obtain learned regime policy before the council vote.
if "remote_learning = fetch_remote_learning_state() or {}" not in text:
    master_anchor = "def master_decision(results, hist, kalshi=None):\n    weighted_sum = 0.0\n"
    require(master_anchor in text, "master_decision anchor not found")
    text = text.replace(
        master_anchor,
        "def master_decision(results, hist, kalshi=None):\n    remote_learning = fetch_remote_learning_state() or {}\n    regime_name = detect_regime(hist)\n    policy = learned_policy(remote_learning, regime_name)\n    weighted_sum = 0.0\n",
        1,
    )
text = text.replace("weight = adaptive_specialist_weight(name)", "weight = adaptive_specialist_weight(name, regime_name)")

# Replace fixed confidence/edge gates with learned policy.
text = text.replace('confidence >= 0.68\n            and projected_edge', 'confidence >= policy["lock_confidence_floor"]\n            and projected_edge')
text = text.replace('elif strong_move_up and up_price_favorable and confidence >= 0.58:', 'elif strong_move_up and up_price_favorable and confidence >= policy["trade_confidence_floor"]:')
text = text.replace('elif strong_move_down and down_price_favorable and confidence >= 0.58:', 'elif strong_move_down and down_price_favorable and confidence >= policy["trade_confidence_floor"]:')
text = text.replace('base_score >= 0.30\n            and forecast_move', 'base_score >= policy["edge_floor"]\n            and forecast_move')
text = text.replace('base_score <= -0.30\n            and forecast_move', 'base_score <= -policy["edge_floor"]\n            and forecast_move')
text = text.replace('base_score >= 0.32 and confidence >= 0.60', 'base_score >= policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]')
text = text.replace('base_score <= -0.32 and confidence >= 0.60', 'base_score <= -policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]')

# Final learned calibration + feed-health/conflict gate before risk classification.
risk_anchor = '    risk_level = (\n'
require(risk_anchor in text, "risk_level anchor not found")
if "source_health = source_health_from_specialists(results)" not in text:
    final_gate = '''    source_health = source_health_from_specialists(results)
    gate_note = ""
    confidence = calibrate_confidence(
        confidence, consensus, policy, source_health=source_health, state=remote_learning
    )
    if action not in {"HOLD", "WAIT"}:
        allowed, gated_action = learned_trade_gate(
            action, confidence, base_score, consensus, policy, source_health=source_health
        )
        if not allowed:
            if action.startswith("LOCK"):
                st.session_state.pop("kalshi_lock_ticker", None)
                st.session_state.pop("kalshi_lock_side", None)
            action = "HOLD"
            locked_side = None
            gate_note = f"{gated_action}; learned reliability gate blocked trade"

'''
    text = text.replace(risk_anchor, final_gate + risk_anchor, 1)
else:
    # Upgrade older first-pass gate to preserve the block reason.
    text = text.replace('    source_health = source_health_from_specialists(results)\n    confidence = calibrate_confidence(', '    source_health = source_health_from_specialists(results)\n    gate_note = ""\n    confidence = calibrate_confidence(', 1)
    text = text.replace('            action = "HOLD"\n            locked_side = None\n            reason_parts = [f"{gated_action}; learned reliability gate blocked trade"]', '            if action.startswith("LOCK"):\n                st.session_state.pop("kalshi_lock_ticker", None)\n                st.session_state.pop("kalshi_lock_side", None)\n            action = "HOLD"\n            locked_side = None\n            gate_note = f"{gated_action}; learned reliability gate blocked trade"', 1)

# Append gate rationale after the standard council rationale is created.
reason_anchor = '''    reason_parts = [
        "; ".join(
            f"{result['name']}: {result['signal']} ({result['score']:+.2f})"
            for result in strongest
        )
    ]
'''
if reason_anchor in text and "if gate_note:\n        reason_parts.append(gate_note)" not in text:
    text = text.replace(reason_anchor, reason_anchor + "\n    if gate_note:\n        reason_parts.append(gate_note)\n", 1)

# Return learned policy/health so downstream risk logic uses the same decision context.
return_anchor = '        "kalshi_available": kctx["available"],\n'
if return_anchor in text and '        "policy": policy,\n' not in text:
    text = text.replace(return_anchor, return_anchor + '        "policy": policy,\n        "source_health": source_health,\n        "regime": regime_name,\n', 1)

# Risk engine: same learned confidence floor, plus feed-health protection.
risk_fn_anchor = 'def risk_evaluate(decision, account, hist, futures):\n    px = float(hist["close"].iloc[-1])\n'
if risk_fn_anchor in text and '    policy = decision.get("policy", {})\n' not in text:
    text = text.replace(risk_fn_anchor, risk_fn_anchor + '    policy = decision.get("policy", {})\n    source_health = safe_float(decision.get("source_health"), 1.0)\n    learned_conf_floor = safe_float(policy.get("trade_confidence_floor"), 0.62)\n', 1)
text = text.replace('    if confidence < 0.62:\n        return {"approved": False, "position_pct": 0.0, "risk_score": 0.9, "reason": "Confidence below 62%"}', '    if source_health < 0.68:\n        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "Market-data health below reliability floor"}\n    if confidence < learned_conf_floor:\n        return {"approved": False, "position_pct": 0.0, "risk_score": 0.9, "reason": f"Confidence below learned floor ({learned_conf_floor:.0%})"}', 1)

# Realistic paper execution costs: 4 bps fee + 1 bps spread + 1.5 bps slippage each side.
entry_anchor = "    qty = notional / price\n    atr = safe_float(hist[\"atr14\"].iloc[-1], price * 0.0025)\n"
if "entry_cost = execution_cost_bps(notional)" not in text:
    require(entry_anchor in text, "paper entry anchor not found")
    text = text.replace(entry_anchor, "    entry_cost = execution_cost_bps(notional)\n    qty = notional / price\n    atr = safe_float(hist[\"atr14\"].iloc[-1], price * 0.0025)\n", 1)
    text = text.replace("            cash -= notional\n            btc += qty", "            cash -= (notional + entry_cost)\n            btc += qty", 1)
    text = text.replace("            cash += notional\n            btc -= qty", "            cash += (notional - entry_cost)\n            btc -= qty", 1)
    text = text.replace("            note,\n        )\n        conn.execute(", "            f\"{note} | entry_cost=${entry_cost:,.2f}\",\n        )\n        conn.execute(", 1)

if "exit_cost = execution_cost_bps(notional)" not in text:
    text = text.replace("            notional = qty * price\n            cash += notional\n            btc -= qty\n            realized = (price - entry_price) * qty", "            notional = qty * price\n            exit_cost = execution_cost_bps(notional)\n            cash += (notional - exit_cost)\n            btc -= qty\n            realized = (price - entry_price) * qty - exit_cost", 1)
    text = text.replace("            notional = qty * price\n            cash -= notional\n            btc += qty\n            realized = (entry_price - price) * qty", "            notional = qty * price\n            exit_cost = execution_cost_bps(notional)\n            cash -= (notional + exit_cost)\n            btc += qty\n            realized = (entry_price - price) * qty - exit_cost", 1)
    text = text.replace('f"{reason} | realized_pnl=${realized:,.2f}",', 'f"{reason} | realized_pnl=${realized:,.2f} | exit_cost=${exit_cost:,.2f}",', 1)

# Version stamp.
text = re.sub(r'APP_VERSION = "[^"]+"', 'APP_VERSION = "2026.09.04-r36-reliability-v31"', text, count=1)

# Safety assertions: these fixed gates must not survive in the master decision.
master = text.split("def master_decision(results, hist, kalshi=None):", 1)[1].split("def risk_evaluate", 1)[0]
require('strong_move_up and up_price_favorable and confidence >= 0.58' not in master, "fixed scalp-up threshold survived")
require('strong_move_down and down_price_favorable and confidence >= 0.58' not in master, "fixed scalp-down threshold survived")
require('policy["trade_confidence_floor"]' in master, "learned confidence floor missing")

P.write_text(text)
print("app.py reliability v3.1 patch applied")
