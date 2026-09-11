from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"{label}: already applied")
        return False
    if old not in text:
        raise SystemExit(f"{label}: expected source block not found in {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: applied")
    return True


# ---------------------------------------------------------------------------
# 1) Persistent GitHub paper ledger: always manage/settle the ACTUAL position
# ticker, not the next pending market ticker. Also reconcile any historical
# OFFICIAL_SETTLEMENT rows that were graded against the wrong market.
# ---------------------------------------------------------------------------
background_path = "background_paper.py"
background_text = Path(background_path).read_text(encoding="utf-8")

helper_anchor = '''def run_cycle(learning_state, market_reader=_market, now=None):\n'''
helper_block = r'''def _recompute_cash(paper):
    """Rebuild cash from the authoritative paper ledger after a correction."""
    base = _f(paper.get("starting_cash"), STARTING_CASH) + _f(
        paper.get("legacy_realized_pnl"), LEGACY_REALIZED_PNL
    )
    cash = base
    for trade in paper.get("trades", []):
        if not isinstance(trade, dict):
            continue
        amount = _f(trade.get("amount"), 0.0)
        contracts = max(0, int(_f(trade.get("contracts"), 0)))
        exit_price = _f(trade.get("exit_price"), 0.0)
        exit_fee = _f(trade.get("exit_fee"), 0.0)
        cash -= amount
        cash += contracts * exit_price - exit_fee
    position = paper.get("open_position")
    if isinstance(position, dict):
        cash -= _f(position.get("amount"), 0.0)
    paper["cash"] = cash
    return cash


def _repair_closed_settlements(paper, market_reader, now):
    """Repair only rows previously labeled as official settlements.

    A past bug could advance to the next pending ticker and then use that NEW
    market's result to settle the OLD position. Every repair below refetches the
    trade's own ticker and trusts only its official finalized YES/NO result.
    """
    corrected = []
    for trade in paper.get("trades", []):
        if not isinstance(trade, dict):
            continue
        reason = str(trade.get("exit_reason") or "")
        if not reason.startswith("OFFICIAL_SETTLEMENT:"):
            continue
        ticker = str(trade.get("ticker") or "")
        side = str(trade.get("side") or "").upper()
        if not ticker or side not in {"YES", "NO"}:
            continue
        try:
            market = market_reader(ticker)
        except Exception:
            continue
        if str(market.get("ticker") or ticker) != ticker:
            continue
        status = str(market.get("status") or "").lower()
        result = str(market.get("result") or "").lower()
        if status not in {"settled", "finalized"} or result not in {"yes", "no"}:
            continue
        exit_price = 1.0 if side.lower() == result else 0.0
        contracts = max(0, int(_f(trade.get("contracts"), 0)))
        amount = _f(trade.get("amount"), 0.0)
        pnl = contracts * exit_price - amount
        recorded_exit = _f(trade.get("exit_price"), -1.0)
        recorded_result = str(trade.get("result") or "").upper()
        expected_result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "EVEN")
        if abs(recorded_exit - exit_price) <= 1e-12 and recorded_result == expected_result:
            continue
        trade.update(
            exit_price=exit_price,
            exit_fee=0.0,
            pnl=pnl,
            result=expected_result,
            last_mark=exit_price,
            exit_reason="OFFICIAL_SETTLEMENT:" + result,
            corrected_at=now,
            correction_reason="REFETCHED_OWN_KALSHI_TICKER",
        )
        corrected.append(ticker)
    if corrected:
        _recompute_cash(paper)
        paper["last_message"] = (
            "Corrected prior paper settlement from each trade's own official "
            "Kalshi result: " + ", ".join(corrected)
        )
    return corrected


def _repair_master_learning_credit(learning_state, corrected_tickers):
    """Restore master credit when a paper trade is proven to be an official win.

    This does not blindly rewrite specialist calls. It only reverses a prior
    master-level wrong mark for the exact ticker whose executed paper side is
    now confirmed as the winning Kalshi side.
    """
    if not corrected_tickers:
        return 0
    paper = learning_state.get("background_paper") or {}
    winning = {
        str(t.get("ticker")): t
        for t in paper.get("trades", [])
        if isinstance(t, dict)
        and str(t.get("ticker")) in set(corrected_tickers)
        and str(t.get("result") or "").upper() == "WIN"
        and str(t.get("exit_reason") or "").startswith("OFFICIAL_SETTLEMENT:")
    }
    if not winning:
        return 0
    repaired = 0
    reward_system = learning_state.setdefault("reward_system", {})
    forecast = learning_state.setdefault("forecast", {})
    for row in learning_state.get("master_history", []):
        ticker = str(row.get("ticker") or "")
        if ticker not in winning or row.get("paper_truth_repaired"):
            continue
        old_hit = int(_f(row.get("direction_correct"), 0.0) or 0)
        if old_hit != 1:
            row["direction_correct"] = 1
            forecast["direction_hits"] = int(forecast.get("direction_hits", 0)) + 1
        old_reward = _f(row.get("time_reward"), 0.0)
        magnitude = abs(_f(row.get("reward_magnitude"), old_reward))
        if old_reward < 0 and magnitude > 0:
            new_reward = magnitude
            reward_system["master_points"] = float(
                reward_system.get("master_points", 0.0)
            ) + (new_reward - old_reward)
            row["time_reward"] = new_reward
        trade = winning[ticker]
        row["kalshi_correct"] = 1
        row["kalshi_result"] = str(trade.get("exit_reason")).split(":", 1)[-1]
        row["paper_truth_repaired"] = True
        row["reward_correction"] = "OFFICIAL_KALSHI_PAPER_WIN"
        repaired += 1
    if repaired:
        reward_system["paper_truth_repairs"] = int(
            reward_system.get("paper_truth_repairs", 0)
        ) + repaired
    return repaired


def run_cycle(learning_state, market_reader=_market, now=None):
'''
if "def _repair_closed_settlements(" not in background_text:
    if helper_anchor not in background_text:
        raise SystemExit("background helper anchor not found")
    background_text = background_text.replace(helper_anchor, helper_block, 1)

old_cycle_head = '''    pending = learning_state.get("pending") or {}\n    ticker = str(pending.get("ticker") or (paper.get("open_position") or {}).get("ticker") or "")\n    if not ticker:\n        paper["last_message"] = "No active Kalshi learner window."\n        return paper\n    market = market_reader(ticker)\n    if str(market.get("ticker") or ticker) != ticker:\n        paper["last_message"] = "Kalshi ticker mismatch; no paper action."\n        return paper\n\n    position = paper.get("open_position")\n    if position:\n        bid, _ = _quotes(market, position["side"])\n        expired = now >= _f(position.get("expires_at"), now + 1)\n        if expired:\n            result = str(market.get("result") or "").lower()\n            status = str(market.get("status") or "").lower()\n            if result in {"yes", "no"} and status in {"settled", "finalized"}:\n                _close(paper, position, 1.0 if position["side"].lower() == result else 0.0, "OFFICIAL_SETTLEMENT:" + result, now, False)\n            else:\n                paper["last_message"] = "Awaiting official Kalshi settlement: " + ticker\n            paper["metrics"] = _post_fix_metrics(paper)\n            paper["gate"] = _gate(paper["metrics"])\n            return paper\n'''
new_cycle_head = '''    corrected = _repair_closed_settlements(paper, market_reader, now)\n    if corrected:\n        _repair_master_learning_credit(learning_state, corrected)\n\n    pending = learning_state.get("pending") or {}\n    position = paper.get("open_position")\n    pending_ticker = str(pending.get("ticker") or "")\n    # While a position exists, its own ticker is authoritative. The old code\n    # could accidentally fetch the next pending market and use that market's\n    # result to settle the previous trade.\n    ticker = str((position or {}).get("ticker") or pending_ticker or "")\n    if not ticker:\n        paper["last_message"] = "No active Kalshi learner window."\n        return paper\n    market = market_reader(ticker)\n    if str(market.get("ticker") or ticker) != ticker:\n        paper["last_message"] = "Kalshi ticker mismatch; no paper action."\n        return paper\n\n    if position:\n        bid, _ = _quotes(market, position["side"])\n        expired = now >= _f(position.get("expires_at"), now + 1)\n        rolled_to_new_market = bool(pending_ticker and pending_ticker != ticker)\n        if expired or rolled_to_new_market:\n            result = str(market.get("result") or "").lower()\n            status = str(market.get("status") or "").lower()\n            if result in {"yes", "no"} and status in {"settled", "finalized"}:\n                _close(\n                    paper,\n                    position,\n                    1.0 if position["side"].lower() == result else 0.0,\n                    "OFFICIAL_SETTLEMENT:" + result,\n                    now,\n                    False,\n                )\n                _repair_master_learning_credit(learning_state, [ticker])\n            else:\n                paper["last_message"] = "Awaiting official Kalshi settlement: " + ticker\n            paper["metrics"] = _post_fix_metrics(paper)\n            paper["gate"] = _gate(paper["metrics"])\n            return paper\n'''
if new_cycle_head not in background_text:
    if old_cycle_head not in background_text:
        raise SystemExit("background run_cycle settlement block not found")
    background_text = background_text.replace(old_cycle_head, new_cycle_head, 1)

Path(background_path).write_text(background_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2) Learner: a Kalshi UP/DOWN call is graded against the CONTRACT TARGET,
# not whether BTC merely moved up/down from the opening spot price.
# ---------------------------------------------------------------------------
replace_once(
    "learner.py",
    '''    start = float(pending["start_price"])\n    predicted_end = float(pending["predicted_end"])\n    actual_direction = 1 if actual >= start else -1\n    direction_correct = int(actual_direction == int(pending["predicted_direction"]))\n''',
    '''    start = float(pending["start_price"])\n    predicted_end = float(pending["predicted_end"])\n    target = float(pending.get("target", start))\n    # Kalshi KXBTC15M direction is defined by settlement versus the contract\n    # target/strike, not simply whether BTC rose or fell from the window open.\n    actual_direction = 1 if actual >= target else -1\n    direction_correct = int(actual_direction == int(pending["predicted_direction"]))\n''',
    "learner target-based master grading",
)
replace_once(
    "learner.py",
    '''    realized = actual / start - 1.0\n    for name, call in pending["specialists"].items():\n''',
    '''    realized = actual / start - 1.0\n    contract_realized = (actual - target) / max(abs(start), 1.0)\n    for name, call in pending["specialists"].items():\n''',
    "learner contract edge basis",
)
replace_once(
    "learner.py",
    '''        edge = score * realized * 100 if predicted_direction else 0.0\n''',
    '''        # Edge must agree with the same target-based outcome used for hit/reward.\n        edge = score * contract_realized * 100 if predicted_direction else 0.0\n''',
    "learner specialist target-based edge",
)


# ---------------------------------------------------------------------------
# 3) Streamlit: re-grade SCALP journal rows against target strike, repair old
# resolved rows, and display user-facing timestamps in US Eastern time.
# Internal storage stays UTC for correctness and DST safety.
# ---------------------------------------------------------------------------
replace_once(
    "app.py",
    '''            if action == "SCALP UP":\n                correct = int(resolved_price > start_price)\n            elif action == "SCALP DOWN":\n                correct = int(resolved_price < start_price)\n            elif action == "LOCK UP":\n                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)\n            elif action == "LOCK DOWN":\n                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)\n''',
    '''            if action in {"SCALP UP", "LOCK UP"}:\n                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)\n            elif action in {"SCALP DOWN", "LOCK DOWN"}:\n                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)\n''',
    "journal target-based SCALP grading",
)
replace_once(
    "app.py",
    '''            updated += 1\n\n        conn.commit()\n    return updated\n\n\ndef recent_predictions(limit=100):\n''',
    '''            updated += 1\n\n        # Repair legacy resolved directional rows that were graded against the\n        # opening spot instead of the Kalshi target. HOLD/WAIT stays untouched.\n        conn.execute(\n            """UPDATE predictions\n               SET correct = CASE\n                   WHEN action IN ('SCALP UP','LOCK UP')\n                       THEN CASE WHEN resolved_price >= target_price THEN 1 ELSE 0 END\n                   WHEN action IN ('SCALP DOWN','LOCK DOWN')\n                       THEN CASE WHEN resolved_price < target_price THEN 1 ELSE 0 END\n                   ELSE correct\n               END\n               WHERE resolved=1\n                 AND resolved_price IS NOT NULL\n                 AND target_price IS NOT NULL\n                 AND action IN ('SCALP UP','SCALP DOWN','LOCK UP','LOCK DOWN')"""\n        )\n        conn.commit()\n    return updated\n\n\ndef recent_predictions(limit=100):\n''',
    "journal legacy regrade",
)
replace_once(
    "app.py",
    '''        df["confidence"] = (df["confidence"] * 100.0).round(1)\n        df["consensus"] = (df["consensus"] * 100.0).round(1)\n''',
    '''        if "created_iso" in df.columns:\n            _created_et = pd.to_datetime(df["created_iso"], utc=True, errors="coerce").dt.tz_convert("America/New_York")\n            df["created_iso"] = _created_et.dt.strftime("%Y-%m-%d %I:%M %p %Z")\n        df["confidence"] = (df["confidence"] * 100.0).round(1)\n        df["consensus"] = (df["consensus"] * 100.0).round(1)\n''',
    "journal Eastern display time",
)
replace_once(
    "app.py",
    '''                    "Opened": pd.to_datetime(\n                        row["opened_at"], unit="s", utc=True\n                    ).strftime("%Y-%m-%d %H:%M UTC"),\n                    "Closed": (\n                        "OPEN" if row["closed_at"] is None\n                        else pd.to_datetime(\n                            row["closed_at"], unit="s", utc=True\n                        ).strftime("%Y-%m-%d %H:%M UTC")\n                    ),\n''',
    '''                    "Opened": pd.to_datetime(\n                        row["opened_at"], unit="s", utc=True\n                    ).tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p %Z"),\n                    "Closed": (\n                        "OPEN" if row["closed_at"] is None\n                        else pd.to_datetime(\n                            row["closed_at"], unit="s", utc=True\n                        ).tz_convert("America/New_York").strftime("%Y-%m-%d %I:%M %p %Z")\n                    ),\n''',
    "paper log Eastern display time",
)
replace_once(
    "app.py",
    '''        f"Last update {utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')} • "\n''',
    '''        f"Last update {utc_now().astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %I:%M:%S %p %Z')} • "\n''',
    "footer Eastern display time",
)

print("Kalshi truth + Eastern-time hotfix source edits complete.")
