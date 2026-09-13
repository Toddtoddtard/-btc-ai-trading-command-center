from pathlib import Path
import re


def replace_function(text, name, replacement):
    pattern = rf"(?ms)^def {re.escape(name)}\(.*?(?=^def |\Z)"
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"Could not find function {name}")
    return text[:match.start()] + replacement.rstrip() + "\n\n" + text[match.end():]


# ---------------- SQLite paper engine ----------------
p = Path("kalshi_paper_engine.py")
s = p.read_text(encoding="utf-8")

# Add an optional settlement timestamp without breaking old Streamlit databases.
needle = '''    if "spot_entry_price" not in columns:\n        conn.execute(\n            "ALTER TABLE kalshi_paper_positions ADD COLUMN spot_entry_price REAL"\n        )\n'''
insert = needle + '''    if "settled_at" not in columns:\n        conn.execute(\n            "ALTER TABLE kalshi_paper_positions ADD COLUMN settled_at REAL"\n        )\n'''
if 'ADD COLUMN settled_at REAL' not in s:
    if needle not in s:
        raise SystemExit("engine migration anchor missing")
    s = s.replace(needle, insert, 1)

new_close = r'''def _close(conn, row, exit_price, reason, charge_exit_fee=True):
    """Finalize an OPEN or PENDING_SETTLEMENT paper position exactly once.

    For a pending settlement, ``closed_at`` already represents the exact
    15-minute window boundary. Finalization preserves that timestamp and stores
    ``settled_at`` separately so UI timing never implies the call stayed open.
    """
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT * FROM kalshi_paper_positions WHERE id=? "
        "AND status IN ('OPEN','PENDING_SETTLEMENT')",
        (int(row["id"]),),
    ).fetchone()
    if row is None:
        conn.rollback()
        return {"event": False, "message": "Paper position already closed"}
    exit_price = min(1.0, max(0.0, float(exit_price)))
    contracts = int(row["contracts"])
    exit_fee = kalshi_taker_fee(contracts, exit_price) if charge_exit_fee else 0.0
    proceeds = exit_price * contracts - exit_fee
    basis = float(row["entry_price"]) * contracts + float(row["entry_fee"])
    pnl = proceeds - basis
    cash = float(
        conn.execute("SELECT cash FROM kalshi_paper_account WHERE id=1").fetchone()["cash"]
    )
    now = time.time()
    closed_at = _f(row["closed_at"], now)
    conn.execute(
        "UPDATE kalshi_paper_account SET cash=?,updated_at=? WHERE id=1",
        (cash + proceeds, now),
    )
    conn.execute(
        """
        UPDATE kalshi_paper_positions
        SET status='CLOSED',closed_at=?,settled_at=?,exit_price=?,exit_fee=?,
            pnl=?,exit_reason=?,last_mark=?
        WHERE id=?
        """,
        (
            closed_at,
            now,
            exit_price,
            exit_fee,
            pnl,
            reason,
            exit_price,
            int(row["id"]),
        ),
    )
    if str(row["strategy"]).upper() == "SCALP":
        _set_scalp_armed(conn, row["ticker"], row["side"], False)
    conn.commit()
    return {
        "event": True,
        "message": (
            f"Settled PAPER {row['strategy']} {row['side']} {row['ticker']} "
            f"@ {exit_price:.2f} | P/L {pnl:+.2f}"
        ),
    }
'''
s = replace_function(s, "_close", new_close)

new_settle = r'''def _settle_from_official_result(conn, row, settlement_reader=None):
    """Finalize one position only from its own official Kalshi result."""
    result = (settlement_reader or fetch_settled_result)(str(row["ticker"]))
    if result not in {"yes", "no"}:
        return None
    payoff = float(str(row["side"]).lower() == result)
    return _close(
        conn,
        row,
        payoff,
        "OFFICIAL_SETTLEMENT:" + result,
        charge_exit_fee=False,
    )


def _settle_pending_positions(conn, settlement_reader=None):
    """Try every expired call independently; never use the current ticker."""
    rows = conn.execute(
        "SELECT * FROM kalshi_paper_positions "
        "WHERE status='PENDING_SETTLEMENT' ORDER BY closed_at ASC,id ASC"
    ).fetchall()
    settled = []
    for row in rows:
        result = _settle_from_official_result(
            conn, row, settlement_reader=settlement_reader
        )
        if result is not None and result.get("event"):
            settled.append(str(row["ticker"]))
    return settled


def _mark_window_ended_pending(conn, row, boundary_ts):
    """End exposure at the window boundary without inventing a settlement."""
    boundary = _f(boundary_ts, time.time())
    conn.execute(
        """UPDATE kalshi_paper_positions
           SET status='PENDING_SETTLEMENT',closed_at=?,
               exit_reason='AWAITING_OFFICIAL_SETTLEMENT',opposite_since=NULL
           WHERE id=? AND status='OPEN'""",
        (boundary, int(row["id"])),
    )
    conn.commit()
    return {
        "event": True,
        "message": (
            "Window ended — settlement pending: " + str(row["ticker"])
        ),
    }
'''
s = replace_function(s, "_settle_from_official_result", new_settle)

# Replace lifecycle manager, preserving the existing entry-management tail.
start = s.index("def manage_kalshi_paper_cycle(")
entry_marker = "    if not enabled:\n"
entry_at = s.index(entry_marker, start)
next_def = s.index("\ndef paper_summary(", entry_at)
tail = s[entry_at:next_def]
new_manager_head = r'''def manage_kalshi_paper_cycle(
    db_path,
    starting_cash,
    decision,
    risk,
    spot_price,
    enabled=True,
    settlement_reader=None,
):
    conn = _connect(db_path, starting_cash)
    try:
        # Settlement is asynchronous. Resolve any prior ended windows by each
        # trade's own ticker, but never let them block the new 15-minute market.
        _settle_pending_positions(conn, settlement_reader=settlement_reader)

        row = conn.execute(
            "SELECT * FROM kalshi_paper_positions "
            "WHERE status='OPEN' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            side = row["side"]
            current_ticker = str(decision.get("kalshi_ticker") or "").strip()
            same_ticker = current_ticker == str(row["ticker"])
            rolled_to_new_market = bool(current_ticker and not same_ticker)
            mark = _quote(decision, side, ask=False) if same_ticker else None
            if mark is not None:
                conn.execute(
                    "UPDATE kalshi_paper_positions SET last_mark=? WHERE id=?",
                    (mark, int(row["id"])),
                )
                conn.commit()

            now = time.time()
            expires_at = _f(row["expires_at"])
            expired = expires_at is not None and now >= expires_at
            if expired or rolled_to_new_market:
                # If Kalshi has already finalized, settle immediately. Otherwise
                # the CALL still ends now and becomes PENDING_SETTLEMENT. This
                # frees the next 15-minute window without fabricating P/L.
                settlement = _settle_from_official_result(
                    conn, row, settlement_reader=settlement_reader
                )
                if settlement is not None:
                    return settlement
                boundary = expires_at if expired and expires_at is not None else now
                return _mark_window_ended_pending(conn, row, boundary)

            # LOCK is immutable through the exact window. It cannot take profit,
            # reverse, or downgrade before the timer ends.
            if row["strategy"] == "SCALP" and mark is not None:
                action_side = _side_from_action(decision.get("action"))
                entry_price = float(row["entry_price"])
                price_gain = mark - entry_price
                projected_exit = _projected_scalp_exit(decision)
                sees_more_upside = (
                    action_side == side
                    and projected_exit is not None
                    and projected_exit >= mark + SCALP_MIN_REMAINING_EDGE - 1e-12
                )
                if (
                    price_gain >= entry_price * SCALP_MIN_GROSS_RETURN - 1e-12
                    and not sees_more_upside
                ):
                    return _close(
                        conn, row, mark, "TAKE_PROFIT_AI_UPSIDE_EXHAUSTED"
                    )
                price_loss = entry_price - mark
                if price_loss >= SCALP_STOP_LOSS_POINTS - 1e-12:
                    return _close(conn, row, mark, "EMERGENCY_STOP_15_POINTS")
                opposite_since = _f(row["opposite_since"])
                if action_side and action_side != side:
                    if opposite_since is None:
                        conn.execute(
                            "UPDATE kalshi_paper_positions "
                            "SET opposite_since=? WHERE id=?",
                            (now, int(row["id"])),
                        )
                        conn.commit()
                    elif now - opposite_since >= OPPOSITE_SIGNAL_CONFIRM_SECONDS:
                        return _close(conn, row, mark, "CONFIRMED_OPPOSITE_SIGNAL")
                elif opposite_since is not None:
                    conn.execute(
                        "UPDATE kalshi_paper_positions SET opposite_since=NULL WHERE id=?",
                        (int(row["id"]),),
                    )
                    conn.commit()
            return {
                "event": False,
                "message": f"Holding PAPER {row['strategy']} {row['side']} {row['ticker']}",
            }
    finally:
        conn.close()

'''
s = s[:start] + new_manager_head + tail + s[next_def:]

new_summary = r'''def paper_summary(db_path, starting_cash=500.0):
    conn = _connect(db_path, starting_cash)
    try:
        acct = conn.execute(
            "SELECT cash,starting_cash FROM kalshi_paper_account WHERE id=1"
        ).fetchone()
        closed = conn.execute(
            "SELECT pnl FROM kalshi_paper_positions "
            "WHERE status='CLOSED' AND pnl IS NOT NULL"
        ).fetchall()
        opened = conn.execute(
            "SELECT * FROM kalshi_paper_positions "
            "WHERE status='OPEN' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        pending = conn.execute(
            "SELECT * FROM kalshi_paper_positions "
            "WHERE status='PENDING_SETTLEMENT' ORDER BY closed_at ASC,id ASC"
        ).fetchall()
        pnls = [float(row["pnl"]) for row in closed]
        realized = sum(pnls)
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        unrealized = 0.0
        valuation_rows = ([opened] if opened else []) + list(pending)
        for position in valuation_rows:
            mark = _f(position["last_mark"], float(position["entry_price"]))
            contracts = int(position["contracts"])
            unrealized += mark * contracts - kalshi_taker_fee(contracts, mark) - (
                float(position["entry_price"]) * contracts
                + float(position["entry_fee"])
            )
        start = float(acct["starting_cash"])
        equity = start + realized + unrealized
        open_position = dict(opened) if opened else None
        if open_position:
            open_position["amount_down"] = (
                float(open_position["entry_price"])
                * int(open_position["contracts"])
                + float(open_position["entry_fee"])
            )
        return {
            "cash": float(acct["cash"]),
            "starting_cash": start,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": realized + unrealized,
            "equity": equity,
            "return_pct": ((equity - start) / start * 100.0) if start else 0.0,
            "samples": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(pnls)) if pnls else None,
            "profit_factor": (
                sum(wins) / abs(sum(losses))
                if losses else (math.inf if wins else None)
            ),
            "open_position": open_position,
            "pending_settlements": len(pending),
        }
    finally:
        conn.close()
'''
s = replace_function(s, "paper_summary", new_summary)

new_history = r'''def paper_history(db_path, starting_cash=500.0, limit=100):
    """Return the automatic Kalshi ledger without disguising pending rows."""
    conn = _connect(db_path, starting_cash)
    try:
        rows = conn.execute(
            """SELECT * FROM kalshi_paper_positions
               ORDER BY opened_at DESC, id DESC LIMIT ?""",
            (max(1, min(1000, int(limit))),),
        ).fetchall()
        history = []
        for row in rows:
            item = dict(row)
            contracts = int(item["contracts"])
            entry = float(item["entry_price"])
            amount = entry * contracts + float(item["entry_fee"])
            status = str(item["status"]).upper()
            if status == "OPEN":
                mark = _f(item.get("last_mark"), entry)
                pnl = mark * contracts - kalshi_taker_fee(contracts, mark) - amount
                result = "OPEN"
                current_or_exit = mark
            elif status == "PENDING_SETTLEMENT":
                mark = _f(item.get("last_mark"), entry)
                pnl = None
                result = "PENDING"
                current_or_exit = mark
            else:
                pnl = _f(item.get("pnl"), 0.0)
                result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "EVEN")
                current_or_exit = _f(item.get("exit_price"))
            history.append(
                {
                    "status": status,
                    "direction": "UP" if item["side"] == "YES" else "DOWN",
                    "strategy": item["strategy"],
                    "amount": amount,
                    "kalshi_entry_pct": entry * 100.0,
                    "current_or_exit_pct": (
                        current_or_exit * 100.0 if current_or_exit is not None else None
                    ),
                    "result": result,
                    "pnl": pnl,
                    "opened_at": item["opened_at"],
                    "closed_at": item.get("closed_at"),
                    "settled_at": item.get("settled_at"),
                    "expires_at": item.get("expires_at"),
                    "exit_reason": item.get("exit_reason"),
                    "ticker": item.get("ticker"),
                }
            )
        return history
    finally:
        conn.close()
'''
s = replace_function(s, "paper_history", new_history)
p.write_text(s, encoding="utf-8")


# ---------------- Background GitHub-persisted paper engine ----------------
p = Path("background_paper.py")
s = p.read_text(encoding="utf-8")
if '"pending_settlements": []' not in s:
    s = s.replace(
        '        "open_position": None,\n        "trades": [],',
        '        "open_position": None,\n        "pending_settlements": [],\n        "trades": [],',
        1,
    )

# Make _close safe when finalizing a pending row while a newer active row exists.
new_bg_close = r'''def _close(paper, position, exit_price, reason, now, charge_fee=True):
    contracts = int(position["contracts"])
    exit_fee = kalshi_taker_fee(contracts, exit_price) if charge_fee else 0.0
    proceeds = contracts * exit_price - exit_fee
    pnl = proceeds - position["amount"]
    paper["cash"] = _f(paper.get("cash"), SEED_CASH) + proceeds
    trade = dict(position)
    trade.update(
        status="CLOSED",
        closed_at=_f(position.get("closed_at"), now),
        settled_at=now,
        exit_price=exit_price,
        exit_fee=exit_fee,
        pnl=pnl,
        result="WIN" if pnl > 0 else "LOSS",
        exit_reason=reason,
    )
    paper.setdefault("trades", []).append(trade)
    current = paper.get("open_position")
    if isinstance(current, dict) and (
        current is position
        or (
            str(current.get("ticker")) == str(position.get("ticker"))
            and _f(current.get("opened_at"), -1) == _f(position.get("opened_at"), -2)
        )
    ):
        paper["open_position"] = None
    paper.setdefault("rearm", {})[position["ticker"] + ":" + position["side"]] = False
    paper["last_message"] = (
        f"Settled PAPER {position['strategy']} {position['side']} "
        f"@ {exit_price*100:.0f}% | P/L ${pnl:+.2f}"
    )
'''
s = replace_function(s, "_close", new_bg_close)

# Include pending rows in cash rebuild and dashboard history/valuation.
s = s.replace(
    '''    position = paper.get("open_position")\n    if isinstance(position, dict):\n        cash -= _f(position.get("amount"), 0.0)\n    paper["cash"] = cash\n''',
    '''    position = paper.get("open_position")\n    if isinstance(position, dict):\n        cash -= _f(position.get("amount"), 0.0)\n    for pending in paper.get("pending_settlements", []):\n        if isinstance(pending, dict):\n            cash -= _f(pending.get("amount"), 0.0)\n    paper["cash"] = cash\n''',
    1,
)

# shared_paper_summary: value pending contracts but don't call them open.
s = s.replace(
    '''    if open_position:\n        entry = _f(open_position.get("entry_price"), 0.0)\n        mark = _f(open_position.get("last_mark"), entry)\n        contracts = max(0, int(_f(open_position.get("contracts"), 0)))\n        amount = _f(\n            open_position.get("amount"),\n            contracts * entry + _f(open_position.get("entry_fee"), 0.0),\n        )\n        unrealized = contracts * mark - kalshi_taker_fee(contracts, mark) - amount\n        open_position["amount_down"] = amount\n''',
    '''    valuation_rows = ([open_position] if open_position else []) + [\n        dict(row) for row in paper.get("pending_settlements", []) if isinstance(row, dict)\n    ]\n    for valuation in valuation_rows:\n        entry = _f(valuation.get("entry_price"), 0.0)\n        mark = _f(valuation.get("last_mark"), entry)\n        contracts = max(0, int(_f(valuation.get("contracts"), 0)))\n        amount = _f(\n            valuation.get("amount"),\n            contracts * entry + _f(valuation.get("entry_fee"), 0.0),\n        )\n        unrealized += contracts * mark - kalshi_taker_fee(contracts, mark) - amount\n        if valuation is open_position:\n            open_position["amount_down"] = amount\n''',
    1,
)
s = s.replace(
    '        "open_position": open_position,\n        "ledger_source": "github-learning-state",',
    '        "open_position": open_position,\n        "pending_settlements": len(paper.get("pending_settlements", [])),\n        "ledger_source": "github-learning-state",',
    1,
)

# shared history includes pending rows and labels them correctly.
s = s.replace(
    '''    if isinstance(paper.get("open_position"), dict):\n        positions.append(paper["open_position"])\n''',
    '''    if isinstance(paper.get("open_position"), dict):\n        positions.append(paper["open_position"])\n    positions.extend(\n        row for row in paper.get("pending_settlements", []) if isinstance(row, dict)\n    )\n''',
    1,
)
s = s.replace(
    '''        is_open = status == "OPEN"\n        is_void = status == "VOID"\n        is_archived = status == "ARCHIVED"\n''',
    '''        is_open = status == "OPEN"\n        is_pending = status == "PENDING_SETTLEMENT"\n        is_void = status == "VOID"\n        is_archived = status == "ARCHIVED"\n''',
    1,
)
s = s.replace(
    '''        current_or_exit = (\n            _f(row.get("last_mark"), entry)\n            if is_open else _f(row.get("exit_price"))\n        )\n''',
    '''        current_or_exit = (\n            _f(row.get("last_mark"), entry)\n            if (is_open or is_pending) else _f(row.get("exit_price"))\n        )\n''',
    1,
)
s = s.replace(
    '''        elif is_open:\n            pnl = (\n                contracts * current_or_exit\n                - kalshi_taker_fee(contracts, current_or_exit)\n                - amount\n            )\n            result = "OPEN"\n        else:\n''',
    '''        elif is_open:\n            pnl = (\n                contracts * current_or_exit\n                - kalshi_taker_fee(contracts, current_or_exit)\n                - amount\n            )\n            result = "OPEN"\n        elif is_pending:\n            pnl = None\n            result = "PENDING"\n        else:\n''',
    1,
)
s = s.replace(
    '                if status in {"OPEN", "CLOSED", "VOID", "ARCHIVED"}\n',
    '                if status in {"OPEN", "PENDING_SETTLEMENT", "CLOSED", "VOID", "ARCHIVED"}\n',
    1,
)

# Insert pending settlement processing before selecting the active window.
anchor = '''    corrected = _repair_closed_settlements(paper, market_reader, now)\n    if corrected:\n        _repair_master_learning_credit(learning_state, corrected)\n\n    pending = learning_state.get("pending") or {}\n'''
replacement = '''    corrected = _repair_closed_settlements(paper, market_reader, now)\n    if corrected:\n        _repair_master_learning_credit(learning_state, corrected)\n\n    # Ended calls wait here for their OWN official Kalshi result while the next\n    # 15-minute window is free to trade. Multiple pending windows are supported.\n    pending_rows = paper.setdefault("pending_settlements", [])\n    for ended in list(pending_rows):\n        if not isinstance(ended, dict):\n            pending_rows.remove(ended)\n            continue\n        ended_ticker = str(ended.get("ticker") or "")\n        if not ended_ticker:\n            continue\n        try:\n            ended_market = market_reader(ended_ticker)\n        except Exception:\n            continue\n        if str(ended_market.get("ticker") or ended_ticker) != ended_ticker:\n            continue\n        result = str(ended_market.get("result") or "").lower()\n        status = str(ended_market.get("status") or "").lower()\n        if result in {"yes", "no"} and status in {"settled", "finalized"}:\n            _close(\n                paper, ended,\n                1.0 if ended["side"].lower() == result else 0.0,\n                "OFFICIAL_SETTLEMENT:" + result, now, False,\n            )\n            pending_rows.remove(ended)\n            _repair_master_learning_credit(learning_state, [ended_ticker])\n\n    pending = learning_state.get("pending") or {}\n'''
if anchor not in s:
    raise SystemExit("background pending insertion anchor missing")
s = s.replace(anchor, replacement, 1)

# At expiry, move to pending rather than retaining the active slot.
old_expiry = '''            if result in {"yes", "no"} and status in {"settled", "finalized"}:\n                _close(\n                    paper,\n                    position,\n                    1.0 if position["side"].lower() == result else 0.0,\n                    "OFFICIAL_SETTLEMENT:" + result,\n                    now,\n                    False,\n                )\n                _repair_master_learning_credit(learning_state, [ticker])\n            else:\n                paper["last_message"] = "Awaiting official Kalshi settlement: " + ticker\n            paper["metrics"] = _post_fix_metrics(paper)\n            paper["gate"] = _gate(paper["metrics"])\n            return paper\n'''
new_expiry = '''            if result in {"yes", "no"} and status in {"settled", "finalized"}:\n                _close(\n                    paper,\n                    position,\n                    1.0 if position["side"].lower() == result else 0.0,\n                    "OFFICIAL_SETTLEMENT:" + result,\n                    now,\n                    False,\n                )\n                _repair_master_learning_credit(learning_state, [ticker])\n            else:\n                boundary = _f(position.get("expires_at"), now) if expired else now\n                ended = dict(position)\n                ended.update(\n                    status="PENDING_SETTLEMENT",\n                    closed_at=boundary,\n                    exit_reason="AWAITING_OFFICIAL_SETTLEMENT",\n                )\n                paper.setdefault("pending_settlements", []).append(ended)\n                paper["open_position"] = None\n                paper["last_message"] = "Window ended — settlement pending: " + ticker\n            paper["metrics"] = _post_fix_metrics(paper)\n            paper["gate"] = _gate(paper["metrics"])\n            return paper\n'''
if old_expiry not in s:
    raise SystemExit("background expiry block missing")
s = s.replace(old_expiry, new_expiry, 1)

# Per-market entry count must also see a same-market pending settlement.
old_same = '''    same_market = [\n        t for t in paper.get("trades", [])\n        if t.get("ticker") == ticker\n        and t.get("strategy") == strategy\n        and str(t.get("status", "CLOSED")).upper() == "CLOSED"\n    ]\n'''
new_same = '''    same_market = [\n        t for t in (list(paper.get("trades", [])) + list(paper.get("pending_settlements", [])))\n        if isinstance(t, dict)\n        and t.get("ticker") == ticker\n        and t.get("strategy") == strategy\n        and str(t.get("status", "CLOSED")).upper() in {"CLOSED", "PENDING_SETTLEMENT"}\n    ]\n'''
if old_same not in s:
    raise SystemExit("background same-market block missing")
s = s.replace(old_same, new_same, 1)
p.write_text(s, encoding="utf-8")


# ---------------- Regression tests ----------------
p = Path("tests/test_settlement_rollover.py")
s = p.read_text(encoding="utf-8")
old_test = '''    def test_rollover_waits_when_official_result_is_not_ready(self):\n        self._open_down_scalp()\n        self.decision["kalshi_ticker"] = self.new_ticker\n\n        result = engine.manage_kalshi_paper_cycle(\n            self.db,\n            500.0,\n            self.decision,\n            self.risk,\n            1.0,\n            settlement_reader=lambda _: None,\n        )\n\n        self.assertFalse(result["event"])\n        self.assertIn("Awaiting official Kalshi settlement", result["message"])\n        self.assertIsNotNone(engine.paper_summary(self.db)["open_position"])\n        self.assertEqual(engine.paper_summary(self.db)["samples"], 0)\n'''
new_test = '''    def test_rollover_ends_call_and_waits_as_pending_when_result_not_ready(self):\n        self._open_down_scalp()\n        self.decision["kalshi_ticker"] = self.new_ticker\n\n        result = engine.manage_kalshi_paper_cycle(\n            self.db, 500.0, self.decision, self.risk, 1.0,\n            settlement_reader=lambda _: None,\n        )\n\n        self.assertTrue(result["event"])\n        self.assertIn("Window ended", result["message"])\n        summary = engine.paper_summary(self.db)\n        self.assertIsNone(summary["open_position"])\n        self.assertEqual(summary["pending_settlements"], 1)\n        self.assertEqual(summary["samples"], 0)\n        row = engine.paper_history(self.db)[0]\n        self.assertEqual(row["status"], "PENDING_SETTLEMENT")\n        self.assertEqual(row["result"], "PENDING")\n        self.assertIsNone(row["pnl"])\n\n    def test_next_market_can_open_while_previous_market_is_pending(self):\n        self._open_down_scalp()\n        self.decision["kalshi_ticker"] = self.new_ticker\n        engine.manage_kalshi_paper_cycle(\n            self.db, 500.0, self.decision, self.risk, 1.0,\n            settlement_reader=lambda _: None,\n        )\n        next_decision = dict(self.decision)\n        next_decision.update({\n            "action": "SCALP UP",\n            "kalshi_ticker": self.new_ticker,\n            "kalshi_close_ts": time.time() + 900,\n            "yes_ask_dollars": 0.40,\n            "yes_bid_dollars": 0.38,\n            "no_ask_dollars": 0.62,\n            "no_bid_dollars": 0.60,\n            "scalp_projected_exit_price": 0.60,\n        })\n        opened = engine.manage_kalshi_paper_cycle(\n            self.db, 500.0, next_decision, self.risk, 100.0,\n            settlement_reader=lambda _: None,\n        )\n        self.assertTrue(opened["event"])\n        self.assertIn("Opened PAPER SCALP", opened["message"])\n        self.assertEqual(engine.paper_summary(self.db)["pending_settlements"], 1)\n        self.assertIsNotNone(engine.paper_summary(self.db)["open_position"])\n\n    def test_pending_finalizes_by_its_own_ticker_and_preserves_window_close(self):\n        self._open_down_scalp()\n        with engine._connect(self.db) as conn:\n            expiry = time.time() - 1\n            conn.execute(\n                "UPDATE kalshi_paper_positions SET expires_at=? WHERE status='OPEN'",\n                (expiry,),\n            )\n            conn.commit()\n        engine.manage_kalshi_paper_cycle(\n            self.db, 500.0, self.decision, self.risk, 100.0,\n            settlement_reader=lambda _: None,\n        )\n        calls = []\n        def official(ticker):\n            calls.append(ticker)\n            return "no" if ticker == self.old_ticker else None\n        engine.manage_kalshi_paper_cycle(\n            self.db, 500.0, {"action": "WAIT", "kalshi_ticker": self.new_ticker},\n            self.risk, 100.0, settlement_reader=official,\n        )\n        self.assertIn(self.old_ticker, calls)\n        row = engine.paper_history(self.db)[0]\n        self.assertEqual(row["status"], "CLOSED")\n        self.assertEqual(row["result"], "WIN")\n        self.assertAlmostEqual(row["closed_at"], expiry, places=3)\n        self.assertIsNotNone(row["settled_at"])\n'''
if old_test not in s:
    raise SystemExit("settlement rollover old test missing")
s = s.replace(old_test, new_test, 1)
p.write_text(s, encoding="utf-8")

print("Applied 15-minute boundary / pending-settlement architecture.")
