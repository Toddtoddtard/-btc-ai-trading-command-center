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

# Surface cost-aware paper profitability in the Paper Trading tab.
paper_anchor = '    with tab_paper:\n        st.subheader("Automatic Paper Trading")\n'
paper_ui = '''    with tab_paper:\n        st.subheader("Automatic Paper Trading")\n\n        # V5 profitability scorecard uses resolved paper/prediction outcomes and\n        # subtracts simulated fees/slippage before calculating expectancy.\n        _profit_rows = recent_predictions(300)\n        _profit_records = _profit_rows.to_dict("records") if _profit_rows is not None and not _profit_rows.empty else []\n        _profit = summarize_trades(_profit_records, cost_bps=6.5)\n        _profit_ok, _profit_reason = profitability_gate(_profit, min_samples=30)\n        p1, p2, p3, p4, p5 = st.columns(5)\n        p1.metric("Net win rate", "Learning" if _profit.get("win_rate") is None else f"{_profit['win_rate']*100:.1f}%")\n        p2.metric("Net expectancy", "Learning" if _profit.get("expectancy") is None else f"{_profit['expectancy']*100:+.3f}%")\n        _pf = _profit.get("profit_factor")\n        p3.metric("Profit factor", "Learning" if _pf is None else ("∞" if not np.isfinite(_pf) else f"{_pf:.2f}"))\n        p4.metric("Drawdown proxy", "Learning" if _profit.get("max_drawdown_proxy") is None else f"{_profit['max_drawdown_proxy']*100:.2f}%")\n        p5.metric("Profitability gate", "PASS" if _profit_ok else "WAIT")\n        st.caption(f"V5 net-of-cost analytics • {_profit.get('samples', 0)} resolved trade calls • simulated cost 6.5 bps • {_profit_reason}")\n'''
if paper_anchor in s and 'V5 profitability scorecard' not in s:
    s = s.replace(paper_anchor, paper_ui)

s = s.replace('APP_VERSION = "2026.09.04-r42-bot-intelligence-v4"', 'APP_VERSION = "2026.09.04-r43-specialist-self-learning-v5"')
p.write_text(s)
print('specialist v5 app integration applied')
