"""Persistent, paper-only Kalshi execution for the scheduled learner.

The Streamlit UI is not a daemon: its Python code only reruns while a browser
session is connected.  This module lets the existing five-minute learner job
manage one conservative KXBTC15M paper ledger inside learning_state.json.
It never authenticates to Kalshi and contains no live-order endpoint.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from kalshi_paper_engine import (
    LOCK_MIN_CONFIDENCE,
    LOCK_TAKE_PROFIT_PRICE,
    MAX_ENTRY_PRICE,
    MIN_SCALP_MARKET_PROBABILITY,
    MAX_LOCKS_PER_MARKET,
    MAX_SCALP_LOSSES_PER_MARKET,
    MAX_SCALPS_PER_MARKET,
    POST_FIX_GATE_TRADES,
    POST_FIX_MAX_DRAWDOWN_PCT,
    POST_FIX_PROFIT_FACTOR_FLOOR,
    POST_FIX_VALIDATION_TRADES,
    SCALP_MIN_GROSS_RETURN,
    SCALP_MIN_REMAINING_EDGE,
    SCALP_STOP_LOSS_POINTS,
    UNPROVEN_POSITION_CAP,
    kalshi_taker_fee,
    lock_target_pnl,
)

STATE_INPUT = os.environ.get("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json")
STARTING_CASH = 500.0
# Snapshot of the authoritative Streamlit ledger when background execution was
# introduced.  Old trades remain visible in Streamlit; only their aggregate
# result is carried forward here so the new post-fix sample stays uncontaminated.
LEGACY_REALIZED_PNL = -141.31
SEED_CASH = STARTING_CASH + LEGACY_REALIZED_PNL

# This pre-guard row was admitted at a 0.1% ask seconds before expiry, then sat
# open until the background worker revisited it 45 minutes later.  Keep the
# row for auditability, but void it from paper P/L and validation because the
# current 20% lottery floor would have rejected the entry.
INVALID_LEGACY_PAPER_TRADES = {
    "KXBTC15M-26SEP091400-00": {
        "opened_at": 1788976788.0083666,
        "maximum_entry_price": 0.001,
        "reason": "PRE_GUARD_ENTRY_BELOW_20_PCT_LOTTERY_FLOOR",
    },
}
PAPER_ACCOUNT_RESET_ID = "2026-09-11-post-fix-500-v2"
POST_FIX_CARRY_FORWARD_WINS = {"KXBTC15M-26SEP101845-45"}


def _f(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _now_iso(now=None):
    return datetime.fromtimestamp(now or time.time(), tz=timezone.utc).isoformat()


def initial_state(now=None):
    return {
        "version": 1,
        "enabled": True,
        "paper_only": True,
        "starting_cash": STARTING_CASH,
        "legacy_realized_pnl": LEGACY_REALIZED_PNL,
        "cash": SEED_CASH,
        "open_position": None,
        "trades": [],
        "rearm": {},
        "last_cycle_at": _now_iso(now),
        "last_message": "24/7 paper engine initialized; waiting for an approved signal.",
        "last_signal_at": None,
        "last_signal_message": "No approved signal has reached execution yet.",
        "signal_attempts": [],
        "worker_ok": True,
    }


def _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, message, outcome, now):
    """Persist the last actionable signal even when later WAIT cycles replace last_message."""
    signal_id = f"{ticker}:{pending.get('opened_at', '')}"
    attempt = {
        "signal_id": signal_id,
        "at": _now_iso(now),
        "ticker": ticker,
        "side": side,
        "direction": "UP" if side == "YES" else "DOWN",
        "strategy": strategy,
        "confidence": confidence,
        "outcome": outcome,
        "message": message,
    }
    attempts = paper.setdefault("signal_attempts", [])
    if attempts and attempts[-1].get("signal_id") == signal_id:
        attempts[-1] = attempt
    else:
        attempts.append(attempt)
        del attempts[:-100]
    paper["last_signal_at"] = attempt["at"]
    paper["last_signal_message"] = message
    paper["last_signal"] = attempt
    paper["last_message"] = message


def _market(ticker, timeout=4):
    url = (
        "https://external-api.kalshi.com/trade-api/v2/markets/"
        + quote(str(ticker), safe="")
    )
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "BTC-AI-Background-Paper/1.0"})
    with urlopen(req, timeout=timeout) as response:
        return json.load(response).get("market", {})


def _price(market, name):
    value = _f(market.get(name + "_dollars"))
    if value is None:
        cents = _f(market.get(name))
        value = cents / 100.0 if cents is not None else None
    return value


def _quotes(market, side):
    yes_bid, yes_ask = _price(market, "yes_bid"), _price(market, "yes_ask")
    no_bid, no_ask = _price(market, "no_bid"), _price(market, "no_ask")
    if no_ask is None and yes_bid is not None:
        no_ask = 1.0 - yes_bid
    if no_bid is None and yes_ask is not None:
        no_bid = 1.0 - yes_ask
    return (yes_bid, yes_ask) if side == "YES" else (no_bid, no_ask)


def _projected_side_value(pending, market, side):
    yes_bid, yes_ask = _quotes(market, "YES")
    if yes_bid is None or yes_ask is None:
        return None
    market_up = min(0.99, max(0.01, (yes_bid + yes_ask) / 2.0))
    start = _f(pending.get("start_price"))
    predicted = _f(pending.get("predicted_end"))
    target = _f(pending.get("target"))
    if start is None or predicted is None or target is None:
        return None
    scale = max(abs(start - target), start * 0.0008, 1.0)
    units = min(3.0, max(-3.0, (predicted - start) / scale))
    log_odds = math.log(market_up / (1.0 - market_up)) + 1.25 * units
    projected_up = 1.0 / (1.0 + math.exp(-log_odds))
    projected_up = min(0.99, max(0.01, 0.75 * projected_up + 0.25 * market_up))
    return projected_up if side == "YES" else 1.0 - projected_up


def _post_fix_metrics(paper):
    closed = [t for t in paper.get("trades", []) if t.get("status") == "CLOSED"]
    pnls = [_f(t.get("pnl"), 0.0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    equity, peak, max_dd = STARTING_CASH, STARTING_CASH, 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
    return {
        "samples": len(pnls),
        "markets": len({t.get("ticker") for t in closed}),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else None),
        "total_pnl": sum(pnls),
        "expectancy": sum(pnls) / len(pnls) if pnls else None,
        "fees": sum(_f(t.get("entry_fee"), 0.0) + _f(t.get("exit_fee"), 0.0) for t in closed),
        "max_drawdown_pct": max_dd,
        "gate_sample_target": POST_FIX_GATE_TRADES,
        "validation_sample_target": POST_FIX_VALIDATION_TRADES,
    }


def _gate(metrics):
    reasons = []
    if metrics["samples"] >= POST_FIX_GATE_TRADES:
        if metrics["profit_factor"] is None or metrics["profit_factor"] < POST_FIX_PROFIT_FACTOR_FLOOR:
            reasons.append("profit factor below 1.15")
        if metrics["expectancy"] is None or metrics["expectancy"] <= 0:
            reasons.append("expectancy is not positive")
        if metrics["max_drawdown_pct"] > POST_FIX_MAX_DRAWDOWN_PCT:
            reasons.append("drawdown above 10%")
    if metrics["samples"] < POST_FIX_GATE_TRADES:
        status = "COLLECTING EVIDENCE"
    elif reasons:
        status = "SCALPS PAUSED"
    elif metrics["samples"] < POST_FIX_VALIDATION_TRADES:
        status = "PROVISIONAL PASS"
    else:
        status = "VALIDATED PASS"
    return {"approved": not reasons, "status": status, "reason": "; ".join(reasons) or "Kalshi safeguards satisfied"}


def shared_paper_summary(paper):
    """Normalize the GitHub-persisted ledger for the Streamlit dashboard."""
    paper = paper if isinstance(paper, dict) else {}
    starting_cash = _f(paper.get("starting_cash"), STARTING_CASH)
    legacy_pnl = _f(paper.get("legacy_realized_pnl"), 0.0)
    trades = [
        trade for trade in paper.get("trades", [])
        if isinstance(trade, dict) and str(trade.get("status", "CLOSED")).upper() == "CLOSED"
    ]
    trade_pnls = [_f(trade.get("pnl"), 0.0) for trade in trades]
    realized = legacy_pnl + sum(trade_pnls)
    open_position = paper.get("open_position")
    open_position = dict(open_position) if isinstance(open_position, dict) else None
    unrealized = 0.0
    if open_position:
        entry = _f(open_position.get("entry_price"), 0.0)
        mark = _f(open_position.get("last_mark"), entry)
        contracts = max(0, int(_f(open_position.get("contracts"), 0)))
        amount = _f(
            open_position.get("amount"),
            contracts * entry + _f(open_position.get("entry_fee"), 0.0),
        )
        unrealized = contracts * mark - kalshi_taker_fee(contracts, mark) - amount
        open_position["amount_down"] = amount

    all_known_pnls = ([legacy_pnl] if legacy_pnl else []) + trade_pnls
    wins = [pnl for pnl in all_known_pnls if pnl > 0]
    losses = [pnl for pnl in all_known_pnls if pnl < 0]
    equity = starting_cash + realized + unrealized
    return {
        "cash": _f(paper.get("cash"), starting_cash + realized),
        "starting_cash": starting_cash,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "equity": equity,
        "return_pct": ((equity - starting_cash) / starting_cash * 100.0) if starting_cash else 0.0,
        "samples": len(trades),
        "wins": sum(pnl > 0 for pnl in trade_pnls),
        "losses": sum(pnl < 0 for pnl in trade_pnls),
        "win_rate": (
            sum(pnl > 0 for pnl in trade_pnls) / len(trade_pnls)
            if trade_pnls else None
        ),
        "profit_factor": (
            sum(wins) / abs(sum(losses))
            if losses else (math.inf if wins else None)
        ),
        "open_position": open_position,
        "ledger_source": "github-learning-state",
    }


def shared_paper_scorecard(paper):
    """Recalculate post-fix metrics and validation from persisted trades."""
    paper = paper if isinstance(paper, dict) else {}
    metrics = _post_fix_metrics(paper)
    return metrics, _gate(metrics)


def shared_paper_history(paper, limit=100):
    """Return display-ready rows from the persistent GitHub ledger."""
    paper = paper if isinstance(paper, dict) else {}
    positions = [
        trade for trade in paper.get("trades", []) if isinstance(trade, dict)
    ]
    if isinstance(paper.get("open_position"), dict):
        positions.append(paper["open_position"])
    positions.sort(
        key=lambda row: (_f(row.get("opened_at"), 0.0), str(row.get("ticker", ""))),
        reverse=True,
    )
    history = []
    for row in positions[:max(1, min(1000, int(limit)))]:
        status = str(row.get("status", "OPEN")).upper()
        is_open = status == "OPEN"
        is_void = status == "VOID"
        is_archived = status == "ARCHIVED"
        entry = _f(row.get("entry_price"), 0.0)
        contracts = max(0, int(_f(row.get("contracts"), 0)))
        amount = _f(
            row.get("amount"),
            contracts * entry + _f(row.get("entry_fee"), 0.0),
        )
        current_or_exit = (
            _f(row.get("last_mark"), entry)
            if is_open else _f(row.get("exit_price"))
        )
        if is_void:
            pnl = 0.0
            result = "VOID"
        elif is_archived:
            pnl = 0.0
            result = "ARCHIVED"
        elif is_open:
            pnl = (
                contracts * current_or_exit
                - kalshi_taker_fee(contracts, current_or_exit)
                - amount
            )
            result = "OPEN"
        else:
            pnl = _f(row.get("pnl"), 0.0)
            result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "EVEN")
        history.append({
            "status": (
                status
                if status in {"OPEN", "CLOSED", "VOID", "ARCHIVED"}
                else "CLOSED"
            ),
            "direction": "UP" if row.get("side") == "YES" else "DOWN",
            "strategy": str(row.get("strategy", "SCALP")),
            "amount": amount,
            "kalshi_entry_pct": entry * 100.0,
            "current_or_exit_pct": (
                current_or_exit * 100.0 if current_or_exit is not None else None
            ),
            "result": result,
            "pnl": pnl,
            "opened_at": _f(row.get("opened_at"), 0.0),
            "closed_at": _f(row.get("closed_at")),
            "expires_at": _f(row.get("expires_at")),
            "exit_reason": row.get("exit_reason"),
            "ticker": str(row.get("ticker", "")),
        })
    return history


def shared_paper_chart_entries(paper, ticker, limit=11):
    """Return entry markers from the same persistent ledger shown in the tab."""
    ticker = str(ticker or "").strip()
    if not ticker:
        return []
    rows = [
        row for row in shared_paper_history(paper, limit=1000)
        if row.get("ticker") == ticker and row.get("status") == "CLOSED"
    ]
    rows.sort(key=lambda row: row["opened_at"])
    return [
        {
            "direction": row["direction"],
            "strategy": row["strategy"],
            "opened_at": row["opened_at"],
            "kalshi_entry_pct": row["kalshi_entry_pct"],
            "spot_entry_price": next(
                (
                    _f(source.get("spot_entry_price"))
                    for source in (
                        list(paper.get("trades", []))
                        + ([paper.get("open_position")] if paper.get("open_position") else [])
                    )
                    if isinstance(source, dict)
                    and str(source.get("ticker", "")) == ticker
                    and _f(source.get("opened_at"), 0.0) == row["opened_at"]
                ),
                None,
            ),
        }
        for row in rows[-max(1, min(25, int(limit))):]
    ]


def _close(paper, position, exit_price, reason, now, charge_fee=True):
    contracts = int(position["contracts"])
    exit_fee = kalshi_taker_fee(contracts, exit_price) if charge_fee else 0.0
    proceeds = contracts * exit_price - exit_fee
    pnl = proceeds - position["amount"]
    paper["cash"] = _f(paper.get("cash"), SEED_CASH) + proceeds
    trade = dict(position)
    trade.update(status="CLOSED", closed_at=now, exit_price=exit_price, exit_fee=exit_fee, pnl=pnl, result="WIN" if pnl > 0 else "LOSS", exit_reason=reason)
    paper.setdefault("trades", []).append(trade)
    paper["open_position"] = None
    paper.setdefault("rearm", {})[position["ticker"] + ":" + position["side"]] = False
    paper["last_message"] = f"Closed PAPER {position['strategy']} {position['side']} @ {exit_price*100:.0f}% | P/L ${pnl:+.2f}"


def _recompute_cash(paper):
    """Rebuild cash from the authoritative paper ledger after a correction."""
    base = _f(paper.get("starting_cash"), STARTING_CASH) + _f(
        paper.get("legacy_realized_pnl"), LEGACY_REALIZED_PNL
    )
    cash = base
    for trade in paper.get("trades", []):
        if (
            not isinstance(trade, dict)
            or str(trade.get("status", "CLOSED")).upper() != "CLOSED"
        ):
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


def _void_invalid_legacy_paper_trades(paper, now):
    """Quarantine exact pre-guard executions without rewriting market truth."""
    voided = []
    for trade in paper.get("trades", []):
        if not isinstance(trade, dict):
            continue
        ticker = str(trade.get("ticker") or "")
        rule = INVALID_LEGACY_PAPER_TRADES.get(ticker)
        if not rule or str(trade.get("status", "")).upper() == "VOID":
            continue
        opened_at = _f(trade.get("opened_at"))
        entry_price = _f(trade.get("entry_price"))
        if (
            str(trade.get("strategy", "")).upper() != "SCALP"
            or opened_at is None
            or abs(opened_at - rule["opened_at"]) > 1.0
            or entry_price is None
            or entry_price > rule["maximum_entry_price"] + 1e-12
        ):
            continue
        trade.update(
            original_status=str(trade.get("status") or "CLOSED"),
            original_result=trade.get("result"),
            original_pnl=_f(trade.get("pnl"), 0.0),
            status="VOID",
            result="VOID",
            pnl=0.0,
            voided_at=now,
            void_reason=rule["reason"],
        )
        for attempt in paper.get("signal_attempts", []):
            if (
                isinstance(attempt, dict)
                and str(attempt.get("ticker") or "") == ticker
                and str(attempt.get("outcome") or "").upper() == "OPENED"
            ):
                attempt["outcome"] = "VOIDED"
                attempt["void_reason"] = rule["reason"]
        voided.append(ticker)
    if voided:
        _recompute_cash(paper)
        paper["last_message"] = (
            "Voided invalid pre-guard paper trade below the 20% lottery floor: "
            + ", ".join(voided)
        )
    return voided


def _reset_paper_account_to_post_fix_500(paper, now):
    """Reset bad legacy P/L but carry forward verified post-fix wins."""
    reset = paper.get("balance_reset")
    if isinstance(reset, dict) and reset.get("id") == PAPER_ACCOUNT_RESET_ID:
        return False

    archived = 0
    carried_wins = 0
    for trade in paper.get("trades", []):
        if not isinstance(trade, dict):
            continue
        ticker = str(trade.get("ticker") or "")
        if ticker in POST_FIX_CARRY_FORWARD_WINS:
            original_pnl = _f(trade.get("original_pnl"), _f(trade.get("pnl"), 0.0))
            trade.update(
                status="CLOSED",
                result="WIN",
                pnl=original_pnl,
                carry_forward=True,
                carry_forward_reason="VERIFIED_OFFICIAL_KALSHI_WIN",
            )
            carried_wins += 1
            continue
        if str(trade.get("status", "")).upper() != "CLOSED":
            continue
        trade.update(
            original_status="CLOSED",
            original_result=trade.get("result"),
            original_pnl=_f(trade.get("pnl"), 0.0),
            status="ARCHIVED",
            result="ARCHIVED",
            pnl=0.0,
            archived_at=now,
            archive_reason="PRE_POST_FIX_500_BASELINE",
        )
        archived += 1

    paper["starting_cash"] = STARTING_CASH
    paper["legacy_realized_pnl"] = 0.0
    _recompute_cash(paper)
    paper["balance_reset"] = {
        "id": PAPER_ACCOUNT_RESET_ID,
        "at": _now_iso(now),
        "starting_cash": STARTING_CASH,
        "archived_trades": archived,
        "carried_forward_wins": carried_wins,
        "reason": "CLEAN_POST_FIX_PAPER_BASELINE",
    }
    paper["metrics"] = _post_fix_metrics(paper)
    paper["gate"] = _gate(paper["metrics"])
    paper["last_message"] = (
        f"Paper account reset from ${STARTING_CASH:.2f}; carried forward "
        f"{carried_wins} verified win(s) and archived {archived} old trade(s)."
    )
    return True


def _repair_closed_settlements(paper, market_reader, now):
    """Repair only rows previously labeled as official settlements.

    A past bug could advance to the next pending ticker and then use that NEW
    market's result to settle the OLD position. Every repair below refetches the
    trade's own ticker and trusts only its official finalized YES/NO result.
    """
    corrected = []
    for trade in paper.get("trades", []):
        if (
            not isinstance(trade, dict)
            or str(trade.get("status", "CLOSED")).upper() != "CLOSED"
        ):
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
        and str(t.get("status", "CLOSED")).upper() == "CLOSED"
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
    now = float(now or time.time())
    paper = learning_state.get("background_paper")
    if not isinstance(paper, dict) or paper.get("version") != 1:
        paper = initial_state(now)
        learning_state["background_paper"] = paper
    paper["last_cycle_at"] = _now_iso(now)
    paper["worker_ok"] = True
    paper.setdefault("last_signal_at", None)
    paper.setdefault("last_signal_message", "No approved signal has reached execution yet.")
    paper.setdefault("signal_attempts", [])
    _void_invalid_legacy_paper_trades(paper, now)
    _reset_paper_account_to_post_fix_500(paper, now)
    if not paper.get("enabled", True):
        paper["last_message"] = "24/7 paper engine paused."
        return paper

    corrected = _repair_closed_settlements(paper, market_reader, now)
    if corrected:
        _repair_master_learning_credit(learning_state, corrected)

    pending = learning_state.get("pending") or {}
    position = paper.get("open_position")
    pending_ticker = str(pending.get("ticker") or "")
    # While a position exists, its own ticker is authoritative. The old code
    # could accidentally fetch the next pending market and use that market's
    # result to settle the previous trade.
    ticker = str((position or {}).get("ticker") or pending_ticker or "")
    if not ticker:
        paper["last_message"] = "No active Kalshi learner window."
        return paper
    market = market_reader(ticker)
    if str(market.get("ticker") or ticker) != ticker:
        paper["last_message"] = "Kalshi ticker mismatch; no paper action."
        return paper

    if position:
        bid, _ = _quotes(market, position["side"])
        expired = now >= _f(position.get("expires_at"), now + 1)
        rolled_to_new_market = bool(pending_ticker and pending_ticker != ticker)
        if expired or rolled_to_new_market:
            result = str(market.get("result") or "").lower()
            status = str(market.get("status") or "").lower()
            if result in {"yes", "no"} and status in {"settled", "finalized"}:
                _close(
                    paper,
                    position,
                    1.0 if position["side"].lower() == result else 0.0,
                    "OFFICIAL_SETTLEMENT:" + result,
                    now,
                    False,
                )
                _repair_master_learning_credit(learning_state, [ticker])
            else:
                paper["last_message"] = "Awaiting official Kalshi settlement: " + ticker
            paper["metrics"] = _post_fix_metrics(paper)
            paper["gate"] = _gate(paper["metrics"])
            return paper
        if bid is not None:
            position["last_mark"] = bid
            if position["strategy"] == "LOCK" and bid >= LOCK_TAKE_PROFIT_PRICE:
                _close(paper, position, bid, "LOCK_BID_95_PCT", now)
            elif position["strategy"] == "SCALP":
                entry_price = position["entry_price"]
                gain = bid - entry_price
                signal_side = (
                    "YES"
                    if int(pending.get("predicted_direction", 0)) > 0
                    else "NO"
                )
                projected_exit = _projected_side_value(
                    pending, market, position["side"]
                )
                sees_more_upside = (
                    not bool(pending.get("would_wait", True))
                    and signal_side == position["side"]
                    and projected_exit is not None
                    and projected_exit >= bid + SCALP_MIN_REMAINING_EDGE
                )
                confirmed_reversal = (
                    not bool(pending.get("would_wait", True))
                    and signal_side != position["side"]
                )
                if (
                    gain >= entry_price * SCALP_MIN_GROSS_RETURN
                    and not sees_more_upside
                ):
                    _close(
                        paper,
                        position,
                        bid,
                        "TAKE_PROFIT_AI_UPSIDE_EXHAUSTED",
                        now,
                    )
                elif confirmed_reversal:
                    _close(
                        paper,
                        position,
                        bid,
                        "AI_CONFIRMED_REVERSAL",
                        now,
                    )
                elif gain <= -SCALP_STOP_LOSS_POINTS:
                    _close(
                        paper,
                        position,
                        bid,
                        "EMERGENCY_STOP_15_POINTS",
                        now,
                    )
                else:
                    paper["last_message"] = f"Holding PAPER SCALP {position['side']} {ticker}"
        paper["metrics"] = _post_fix_metrics(paper)
        paper["gate"] = _gate(paper["metrics"])
        return paper

    metrics = _post_fix_metrics(paper)
    gate = _gate(metrics)
    paper["metrics"], paper["gate"] = metrics, gate
    if bool(pending.get("would_wait", True)):
        paper["last_message"] = "No paper action: learner selected WAIT."
        return paper
    side = "YES" if int(pending.get("predicted_direction", 0)) > 0 else "NO"
    confidence = _f(pending.get("master_confidence"), 0.0)
    strategy = "LOCK" if confidence >= LOCK_MIN_CONFIDENCE else "SCALP"
    bid, ask = _quotes(market, side)
    if ask is None or bid is None:
        _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, "Skipped PAPER entry: executable quote unavailable.", "BLOCKED", now)
        return paper
    if strategy == "SCALP" and ask > MAX_ENTRY_PRICE:
        _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, f"Skipped PAPER SCALP: Kalshi price {ask*100:.0f}% is above the 75% maximum.", "BLOCKED", now)
        return paper
    if strategy == "SCALP":
        market_probability = (bid + ask) / 2.0
        if market_probability < MIN_SCALP_MARKET_PROBABILITY:
            message = (
                f"Skipped PAPER SCALP: selected-side market probability "
                f"{market_probability*100:.0f}% is below the "
                f"{MIN_SCALP_MARKET_PROBABILITY*100:.0f}% lottery floor."
            )
            _record_signal_outcome(
                paper, pending, ticker, side, strategy, confidence,
                message, "BLOCKED", now,
            )
            return paper
    same_market = [
        t for t in paper.get("trades", [])
        if t.get("ticker") == ticker
        and t.get("strategy") == strategy
        and str(t.get("status", "CLOSED")).upper() == "CLOSED"
    ]
    if len(same_market) >= (MAX_LOCKS_PER_MARKET if strategy == "LOCK" else MAX_SCALPS_PER_MARKET):
        _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, f"Skipped PAPER {strategy}: per-market limit reached.", "BLOCKED", now)
        return paper
    if strategy == "SCALP":
        if not gate["approved"]:
            _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, "Skipped PAPER SCALP: " + gate["reason"], "BLOCKED", now)
            return paper
        projected = _projected_side_value(pending, market, side)
        required_exit = ask * (1.0 + SCALP_MIN_GROSS_RETURN)
        if projected is None or projected < required_exit:
            text = "unavailable" if projected is None else f"{projected*100:.0f}%"
            message = (
                f"Skipped PAPER SCALP: projected exit {text} is below the "
                f"{SCALP_MIN_GROSS_RETURN*100:.0f}% gross-return target "
                f"({required_exit*100:.0f}%)."
            )
            _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, message, "BLOCKED", now)
            return paper
        losses = sum(1 for t in same_market if _f(t.get("pnl"), 0.0) < 0)
        if losses >= MAX_SCALP_LOSSES_PER_MARKET:
            _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, "Skipped PAPER SCALP: two-loss market circuit breaker is active.", "BLOCKED", now)
            return paper
        key = ticker + ":" + side
        if paper.setdefault("rearm", {}).get(key) is False:
            _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, "Skipped PAPER SCALP: waiting for a fresh signal before re-entry.", "BLOCKED", now)
            return paper

    budget = max(0.0, paper["cash"]) * UNPROVEN_POSITION_CAP
    contracts = int(budget // max(ask, 0.01))
    while contracts and contracts * ask + kalshi_taker_fee(contracts, ask) > budget:
        contracts -= 1
    if contracts < 1:
        _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, "Skipped PAPER entry: paper allocation is too small.", "BLOCKED", now)
        return paper
    fee = kalshi_taker_fee(contracts, ask)
    amount = contracts * ask + fee
    if strategy == "LOCK":
        expected_pnl = lock_target_pnl(contracts, ask)
        if expected_pnl <= 1e-12:
            message = (
                f"Skipped PAPER LOCK at {ask*100:.0f}%: selling at the 95% "
                f"bid target would return {expected_pnl:+.2f} after estimated "
                "Kalshi fees."
            )
            _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, message, "BLOCKED", now)
            return paper
    expires = _f(pending.get("expires_at"))
    position = {"ticker": ticker, "side": side, "direction": "UP" if side == "YES" else "DOWN", "strategy": strategy, "status": "OPEN", "opened_at": now, "expires_at": expires, "entry_price": ask, "spot_entry_price": _f(pending.get("start_price")), "contracts": contracts, "entry_fee": fee, "amount": amount, "last_mark": bid}
    paper["cash"] -= amount
    paper["open_position"] = position
    message = f"Opened PAPER {strategy} {position['direction']} • Amount: ${amount:.2f} • Kalshi entry: {ask*100:.0f}%"
    _record_signal_outcome(paper, pending, ticker, side, strategy, confidence, message, "OPENED", now)
    return paper


def main():
    with open(STATE_INPUT, encoding="utf-8") as handle:
        state = json.load(handle)
    try:
        paper = run_cycle(state)
    except Exception as exc:
        paper = state.setdefault("background_paper", initial_state())
        paper["worker_ok"] = False
        paper["last_cycle_at"] = _now_iso()
        paper["last_message"] = "Background paper cycle failed safely: " + str(exc)
    with open(STATE_INPUT, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
    print(paper["last_message"])


if __name__ == "__main__":
    main()
