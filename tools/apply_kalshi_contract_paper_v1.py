from pathlib import Path
import re
import runpy

# First apply the external-review phase-1 fixes (raw grading + duplicate gate cleanup).
runpy.run_path("tools/apply_external_review_phase1.py", run_name="__main__")

p = Path("app.py")
s = p.read_text()

imp = "from kalshi_paper_engine import manage_kalshi_paper_cycle, paper_history, paper_summary, persistent_lock_side\n"
legacy_imp = "from kalshi_paper_engine import manage_kalshi_paper_cycle, paper_summary, persistent_lock_side\n"
anchor = "from bot_intelligence_dashboard import render_bot_intelligence_dashboard\n"
if imp in s:
    s = s.replace(legacy_imp, "", 1)
elif legacy_imp in s:
    s = s.replace(legacy_imp, imp, 1)
else:
    if anchor not in s:
        raise SystemExit("Kalshi paper import anchor not found")
    s = s.replace(anchor, anchor + imp, 1)

# Persist LOCK state in SQLite by reading the open paper contract, not browser session_state.
old_lock = '''        # Persistent lock state for the current Kalshi contract.\n        lock_ticker = st.session_state.get("kalshi_lock_ticker", "")\n        lock_side = st.session_state.get("kalshi_lock_side")\n        current_ticker = kctx.get("ticker", "")\n\n        if lock_ticker and (\n            lock_ticker != current_ticker\n            or (pd.notna(remaining) and remaining <= 0)\n        ):\n            st.session_state.pop("kalshi_lock_ticker", None)\n            st.session_state.pop("kalshi_lock_side", None)\n            lock_ticker = ""\n            lock_side = None\n'''
new_lock = '''        # Persistent LOCK state comes from the SQLite Kalshi paper position,\n        # so refreshes/new tabs cannot erase a live paper settlement call.\n        current_ticker = kctx.get("ticker", "")\n        _db_lock_side = persistent_lock_side(DB_PATH, current_ticker, STARTING_CASH)\n        lock_side = "UP" if _db_lock_side == "YES" else "DOWN" if _db_lock_side == "NO" else None\n        lock_ticker = current_ticker if lock_side else ""\n'''
if new_lock not in s:
    if old_lock not in s:
        raise SystemExit("Persistent LOCK anchor not found")
    s = s.replace(old_lock, new_lock, 1)

s = s.replace('            st.session_state["kalshi_lock_ticker"] = current_ticker\n            st.session_state["kalshi_lock_side"] = "UP"\n', '', 1)
s = s.replace('            st.session_state["kalshi_lock_ticker"] = current_ticker\n            st.session_state["kalshi_lock_side"] = "DOWN"\n', '', 1)

# Decision now carries the actual contract quote needed for paper fills.
quote_anchor = '''        "kalshi_ticker": kctx.get("ticker", ""),\n        "seconds_remaining": remaining,\n'''
quote_new = '''        "kalshi_ticker": kctx.get("ticker", ""),\n        "kalshi_close_ts": (pd.Timestamp(kctx.get("close_time")).timestamp() if kctx.get("close_time") else np.nan),\n        "yes_bid_dollars": safe_float((kctx.get("market") or {}).get("yes_bid_dollars")),\n        "yes_ask_dollars": safe_float((kctx.get("market") or {}).get("yes_ask_dollars")),\n        "no_bid_dollars": safe_float((kctx.get("market") or {}).get("no_bid_dollars")),\n        "no_ask_dollars": safe_float((kctx.get("market") or {}).get("no_ask_dollars")),\n        "seconds_remaining": remaining,\n'''
if quote_new not in s:
    if quote_anchor not in s:
        raise SystemExit("Decision quote anchor not found")
    s = s.replace(quote_anchor, quote_new, 1)

# Replace legacy BTC-spot paper execution with real KXBTC15M contract paper execution.
wrapper = '''def manage_auto_paper(decision, risk, price, hist):\n    """Run one PAPER-only KXBTC15M contract cycle; never sends a live order."""\n    return manage_kalshi_paper_cycle(DB_PATH, STARTING_CASH, decision, risk, price)\n'''
if wrapper not in s:
    pattern = r'def manage_auto_paper\(decision, risk, price, hist\):.*?(?=\n\ndef [A-Za-z_][A-Za-z0-9_]*\()'
    s2, n = re.subn(pattern, wrapper, s, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"manage_auto_paper replacement failed ({n})")
    s = s2

# Keep the automatic paper tab on one authoritative Kalshi-ledger surface.
# Older installer runs inserted this legacy scorecard above the preferred one;
# remove it if encountered and never reinsert it on future main pushes.
paper_anchor = '    with tab_paper:\n        st.subheader("Automatic Paper Trading")\n'
legacy_paper_ui = '''        _kp = paper_summary(DB_PATH, STARTING_CASH)
        st.caption("PRIMARY P/L EVIDENCE — simulated KXBTC15M contracts filled at ask, exited at bid/settlement; general Kalshi taker-fee model applied.")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Contract Equity", f"${_kp['equity']:,.2f}", f"{_kp['return_pct']:+.2f}%")
        k2.metric("Total P/L", f"${_kp['total_pnl']:+,.2f}")
        k3.metric("Realized P/L", f"${_kp['realized_pnl']:+,.2f}")
        k4.metric("Open P/L", f"${_kp['unrealized_pnl']:+,.2f}")
        _pf = _kp.get('profit_factor')
        k5.metric("Contract Profit Factor", "Learning" if _pf is None else ("∞" if not np.isfinite(_pf) else f"{_pf:.2f}"))
        _open_contract = _kp.get("open_position")
        if _open_contract:
            st.info(f"OPEN PAPER {_open_contract['strategy']} {_open_contract['side']} • {_open_contract['contracts']} contracts • {_open_contract['ticker']} • entry ${_open_contract['entry_price']:.2f}")
        st.caption("Prediction-quality statistics below remain useful for calibration, but they are not the profitability evidence chain.")

'''
if legacy_paper_ui in s:
    s = s.replace(legacy_paper_ui, "", 1)
if paper_anchor not in s or "Automatic Kalshi Paper Trade Log" not in s:
    raise SystemExit("Canonical automatic paper ledger UI not found")
if s.count('k1.metric("Contract Equity"') != 1:
    raise SystemExit("Automatic paper summary must appear exactly once")

p.write_text(s)

# Sanity tokens.
for token in (
    "manage_kalshi_paper_cycle",
    "persistent_lock_side",
    "yes_ask_dollars",
    "paper_history",
    "Automatic Kalshi Paper Trade Log",
):
    if token not in s:
        raise SystemExit(f"Missing integration token: {token}")

print("Kalshi contract paper v1 integration applied")
