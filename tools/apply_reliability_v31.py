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
master_anchor = "def master_decision(results, hist, kalshi=None):\n    weighted_sum = 0.0\n"
require(master_anchor in text, "master_decision anchor not found")
text = text.replace(
    master_anchor,
    "def master_decision(results, hist, kalshi=None):\n    remote_learning = fetch_remote_learning_state() or {}\n    regime_name = detect_regime(hist)\n    policy = learned_policy(remote_learning, regime_name)\n    weighted_sum = 0.0\n",
    1,
)
text = text.replace("weight = adaptive_specialist_weight(name)", "weight = adaptive_specialist_weight(name, regime_name)")

# Replace fixed confidence/edge gates with learned policy. These tokens are intentionally
# narrow so unrelated risk/UI thresholds are left alone.
text = text.replace('confidence >= 0.68\n            and projected_edge', 'confidence >= policy["lock_confidence_floor"]\n            and projected_edge')
text = text.replace('confidence >= 0.58):\n            action = "SCALP UP"', 'confidence >= policy["trade_confidence_floor"]):\n            action = "SCALP UP"')
text = text.replace('confidence >= 0.58):\n            action = "SCALP DOWN"', 'confidence >= policy["trade_confidence_floor"]):\n            action = "SCALP DOWN"')
text = text.replace('base_score >= 0.30\n            and forecast_move', 'base_score >= policy["edge_floor"]\n            and forecast_move')
text = text.replace('base_score <= -0.30\n            and forecast_move', 'base_score <= -policy["edge_floor"]\n            and forecast_move')
text = text.replace('base_score >= 0.32 and confidence >= 0.60', 'base_score >= policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]')
text = text.replace('base_score <= -0.32 and confidence >= 0.60', 'base_score <= -policy["edge_floor"] and confidence >= policy["trade_confidence_floor"]')

# Final learned calibration + feed-health/conflict gate before risk classification.
risk_anchor = '    risk_level = (\n'
require(risk_anchor in text, "risk_level anchor not found")
if "source_health = source_health_from_specialists(results)" not in text:
    final_gate = '''    source_health = source_health_from_specialists(results)
    confidence = calibrate_confidence(
        confidence, consensus, policy, source_health=source_health, state=remote_learning
    )
    if action not in {"HOLD", "WAIT"}:
        allowed, gated_action = learned_trade_gate(
            action, confidence, base_score, consensus, policy, source_health=source_health
        )
        if not allowed:
            action = "HOLD"
            locked_side = None
            reason_parts = [f"{gated_action}; learned reliability gate blocked trade"]

'''
    text = text.replace(risk_anchor, final_gate + risk_anchor, 1)

# Realistic paper execution costs: 4 bps fee + 1 bps spread + 1.5 bps slippage each side.
# Entry cost is deducted from cash for both long and simulated short.
entry_anchor = "    qty = notional / price\n    atr = safe_float(hist[\"atr14\"].iloc[-1], price * 0.0025)\n"
require(entry_anchor in text, "paper entry anchor not found")
if "entry_cost = execution_cost_bps(notional)" not in text:
    text = text.replace(entry_anchor, "    entry_cost = execution_cost_bps(notional)\n    qty = notional / price\n    atr = safe_float(hist[\"atr14\"].iloc[-1], price * 0.0025)\n", 1)
    text = text.replace("            cash -= notional\n            btc += qty", "            cash -= (notional + entry_cost)\n            btc += qty", 1)
    text = text.replace("            cash += notional\n            btc -= qty", "            cash += (notional - entry_cost)\n            btc -= qty", 1)
    text = text.replace("            note,\n        )\n        conn.execute(", "            f\"{note} | entry_cost=${entry_cost:,.2f}\",\n        )\n        conn.execute(", 1)

# Exit cost is charged before realized P&L is recorded.
if "exit_cost = execution_cost_bps(notional)" not in text:
    text = text.replace("            notional = qty * price\n            cash += notional\n            btc -= qty\n            realized = (price - entry_price) * qty", "            notional = qty * price\n            exit_cost = execution_cost_bps(notional)\n            cash += (notional - exit_cost)\n            btc -= qty\n            realized = (price - entry_price) * qty - exit_cost", 1)
    text = text.replace("            notional = qty * price\n            cash -= notional\n            btc += qty\n            realized = (entry_price - price) * qty", "            notional = qty * price\n            exit_cost = execution_cost_bps(notional)\n            cash -= (notional + exit_cost)\n            btc += qty\n            realized = (entry_price - price) * qty - exit_cost", 1)
    text = text.replace('f"{reason} | realized_pnl=${realized:,.2f}",', 'f"{reason} | realized_pnl=${realized:,.2f} | exit_cost=${exit_cost:,.2f}",', 1)

# Version stamp.
text = re.sub(r'APP_VERSION = "[^"]+"', 'APP_VERSION = "2026.09.04-r35-reliability-v31"', text, count=1)

P.write_text(text)
print("app.py reliability v3.1 patch applied")
