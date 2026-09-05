from pathlib import Path

path = Path("app.py")
text = path.read_text()

replacements = [
    (
        'STARTING_CASH = 100_000.0\nPREDICTION_HORIZON_MIN = 15\nAPP_VERSION = "2026.09.05-r46-batched-journal-settlement"',
        'STARTING_CASH = 500.0\nPREDICTION_HORIZON_MIN = 15\nAPP_VERSION = "2026.09.05-r47-paper-500-total-pl"',
    ),
    (
        '''        row = conn.execute("SELECT id FROM paper_account WHERE id=1").fetchone()\n        if row is None:\n            conn.execute(\n                "INSERT INTO paper_account(id,cash,btc,starting_equity,updated_iso) VALUES(1,?,?,?,?)",\n                (STARTING_CASH, 0.0, STARTING_CASH, utc_now().isoformat()),\n            )\n        conn.commit()\n''',
        '''        row = conn.execute("SELECT id, starting_equity FROM paper_account WHERE id=1").fetchone()\n        if row is None:\n            conn.execute(\n                "INSERT INTO paper_account(id,cash,btc,starting_equity,updated_iso) VALUES(1,?,?,?,?)",\n                (STARTING_CASH, 0.0, STARTING_CASH, utc_now().isoformat()),\n            )\n        elif abs(float(row["starting_equity"]) - STARTING_CASH) > 1e-9:\n            # One-time migration to the new $500 paper baseline. Start clean so\n            # old $100k results do not contaminate the new account performance.\n            conn.execute(\n                "UPDATE paper_account SET cash=?, btc=0, starting_equity=?, updated_iso=? WHERE id=1",\n                (STARTING_CASH, STARTING_CASH, utc_now().isoformat()),\n            )\n            conn.execute("DELETE FROM paper_trades")\n            conn.execute(\n                """UPDATE auto_paper_state\n                   SET side='NONE',entry_price=NULL,entry_ts=NULL,entry_qty=NULL,\n                       stop_loss=NULL,take_profit=NULL,last_exit_ts=0,\n                       last_message='Paper account migrated to $500 starting balance.'\n                   WHERE id=1"""\n            )\n        conn.commit()\n''',
    ),
    (
        '''        st.subheader("Paper Account")\n        a1, a2, a3, a4, a5 = st.columns(5)\n        a1.metric("Cash", fmt_money(account["cash"]))\n        a2.metric("BTC exposure", f"{account['btc']:+.6f}")\n        a3.metric("Equity", fmt_money(account["equity"]))\n        a4.metric("P&L", fmt_money(account["pnl"]))\n        a5.metric("Return", f"{account['return_pct']:+.2f}%")\n\n        auto_state = get_auto_state()\n''',
        '''        st.subheader("Paper Account")\n        auto_state = get_auto_state()\n\n        # Total bot P/L is current marked-to-market equity minus the original\n        # $500 starting balance. It therefore includes both realized closed\n        # trades and the live unrealized P/L of any currently open position.\n        _open_pnl = 0.0\n        if auto_state["side"] in {"LONG", "SHORT"}:\n            _entry = safe_float(auto_state["entry_price"])\n            _qty = abs(safe_float(auto_state["entry_qty"], 0.0))\n            if pd.notna(_entry) and _qty > 0:\n                _entry_cost = execution_cost_bps(_qty * _entry)\n                if auto_state["side"] == "LONG":\n                    _open_pnl = (price - _entry) * _qty - _entry_cost\n                else:\n                    _open_pnl = (_entry - price) * _qty - _entry_cost\n\n        _closed_pnl = float(account["pnl"]) - float(_open_pnl)\n\n        perf1, perf2, perf3, perf4, perf5 = st.columns(5)\n        perf1.metric("Starting Balance", fmt_money(account["starting_equity"]))\n        perf2.metric("Current Equity", fmt_money(account["equity"]))\n        perf3.metric(\n            "Bot P/L From Start",\n            f"${account['pnl']:+,.2f}",\n            f"{account['return_pct']:+.2f}% from $500 start",\n        )\n        perf4.metric("Closed P/L", f"${_closed_pnl:+,.2f}")\n        perf5.metric("Open P/L", f"${_open_pnl:+,.2f}")\n\n        a1, a2, a3 = st.columns(3)\n        a1.metric("Cash", fmt_money(account["cash"]))\n        a2.metric("BTC exposure", f"{account['btc']:+.6f}")\n        a3.metric("Return", f"{account['return_pct']:+.2f}%")\n\n''',
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit("Expected app.py block not found; refusing partial update.")
    text = text.replace(old, new, 1)

path.write_text(text)
