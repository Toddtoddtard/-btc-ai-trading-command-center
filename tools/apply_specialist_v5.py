#!/usr/bin/env python3
from pathlib import Path

p = Path('app.py')
s = p.read_text()

old_import = 'from council_v4 import council_vote\nfrom bot_intelligence_dashboard import render_bot_intelligence_dashboard\n'
new_import = 'from council_v4 import council_vote\nfrom specialist_knowledge_v5 import knowledge_council_vote\nfrom profitability_v5 import summarize_trades, profitability_gate\nfrom bot_intelligence_dashboard import render_bot_intelligence_dashboard\n'
if old_import not in s and 'from specialist_knowledge_v5 import knowledge_council_vote' not in s:
    raise SystemExit('import anchor not found')
s = s.replace(old_import, new_import)

old_vote = '''    # Bot Intelligence v4 is the single authoritative source-council vote.\n    # It excludes Combination AI to avoid double-counting the council's own\n    # aggregate, and applies learned + regime-specific specialist reliability.\n    v4_council = council_vote(results, remote_learning, regime_name)\n    base_score = clamp(v4_council["base_score"])\n    consensus = float(v4_council["consensus"])\n    council_confidence = float(v4_council["confidence"])\n'''
new_vote = '''    # Bot Intelligence v5 adds Bayesian specialist knowledge on top of the v4\n    # learned/regime-aware council. The 90% value is a precision target, not a\n    # claimed accuracy; weak evidence causes abstention rather than a forced call.\n    v5_council = knowledge_council_vote(results, remote_learning, regime_name, target_precision=0.90)\n    base_score = clamp(v5_council["base_score"])\n    consensus = float(v5_council["consensus"])\n    council_confidence = float(v5_council["confidence"])\n'''
if old_vote not in s and 'v5_council = knowledge_council_vote' not in s:
    raise SystemExit('council vote anchor not found')
s = s.replace(old_vote, new_vote)

anchor = '''    risk_level = (\n        "LOW"\n        if confidence > 0.78 and consensus > 0.55\n'''
insert = '''    # v5 selective-precision gate: the live app must not take a trade merely\n    # because the older threshold fired. The Bayesian evidence floor must pass.\n    if action not in {"HOLD", "WAIT"} and not bool(v5_council.get("precision_gate_passed")):\n        if action.startswith("LOCK"):\n            st.session_state.pop("kalshi_lock_ticker", None)\n            st.session_state.pop("kalshi_lock_side", None)\n        action = "HOLD"\n        locked_side = None\n        precision_reason = str(v5_council.get("precision_gate_reason", "WAIT — v5 precision gate"))\n        gate_note = (gate_note + "; " if gate_note else "") + precision_reason\n\n'''
if anchor not in s:
    raise SystemExit('risk anchor not found')
if 'v5 selective-precision gate' not in s:
    s = s.replace(anchor, insert + anchor)

# Make v5 visible in the AI Council tab immediately before the v4 ranking panel.
ui_anchor = '        render_bot_intelligence_dashboard(results, fetch_remote_learning_state() or {}, detect_regime(hist), dark_mode=dark_mode)\n'
ui = '''        v5_state = fetch_remote_learning_state() or {}\n        v5k = (v5_state.get("specialist_knowledge_v5") or {})\n        v5bots = (v5k.get("bots") or {})\n        mature = [x for x in v5bots.values() if isinstance(x, dict) and x.get("mature")]\n        best_floor = max([safe_float(x.get("lower95_accuracy"), 0.0) for x in mature], default=0.0)\n        k1, k2, k3, k4 = st.columns(4)\n        k1.metric("V5 precision target", "90%")\n        k2.metric("Mature specialists", f"{len(mature)}/{len(v5bots) if v5bots else 12}")\n        k3.metric("Best bot 95% floor", f"{best_floor*100:.1f}%" if best_floor else "Learning")\n        k4.metric("Precision gate", "PASS" if v5_council.get("precision_gate_passed") else "WAIT")\n        st.caption(str(v5_council.get("precision_gate_reason", "V5 learning evidence unavailable")))\n\n        render_bot_intelligence_dashboard(results, v5_state, detect_regime(hist), dark_mode=dark_mode)\n'''
if ui_anchor in s:
    s = s.replace(ui_anchor, ui)
elif 'V5 precision target' not in s:
    print('warning: bot intelligence UI anchor not found; core v5 integration still applied')

s = s.replace('APP_VERSION = "2026.09.04-r42-bot-intelligence-v4"', 'APP_VERSION = "2026.09.04-r43-specialist-self-learning-v5"')
p.write_text(s)
print('specialist v5 app integration applied')
