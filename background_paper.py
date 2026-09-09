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
    MAX_LOCKS_PER_MARKET,
    MAX_SCALP_LOSSES_PER_MARKET,
    MAX_SCALPS_PER_MARKET,
    POST_FIX_GATE_TRADES,
    POST_FIX_MAX_DRAWDOWN_PCT,
    POST_FIX_PROFIT_FACTOR_FLOOR,
    POST_FIX_VALIDATION_TRADES,
    SCALP_MIN_GROSS_RETURN,
    SCALP_STOP_LOSS_POINTS,
    UNPROVEN_POSITION_CAP,
    kalshi_taker_fee,
)

STATE_INPUT = os.environ.get("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json")
STARTING_CASH = 500.0
# Snapshot of the authoritative Streamlit ledger when background execution was
# introduced.  Old trades remain visible in Streamlit; only their aggregate
# result is carried forward here so the new post-fix sample stays uncontaminated.
LEGACY_REALIZED_PNL = -141.31
SEED_CASH = STARTING_CASH + LEGACY_REALIZED_PNL


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
        "worker_ok": True,
    }


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


def run_cycle(learning_state, market_reader=_market, now=None):
    now = float(now or time.time())
    paper = learning_state.get("background_paper")
    if not isinstance(paper, dict) or paper.get("version") != 1:
        paper = initial_state(now)
        learning_state["background_paper"] = paper
    paper["last_cycle_at"] = _now_iso(now)
    paper["worker_ok"] = True
    if not paper.get("enabled", True):
        paper["last_message"] = "24/7 paper engine paused."
        return paper

    pending = learning_state.get("pending") or {}
    ticker = str(pending.get("ticker") or (paper.get("open_position") or {}).get("ticker") or "")
    if not ticker:
        paper["last_message"] = "No active Kalshi learner window."
        return paper
    market = market_reader(ticker)
    if str(market.get("ticker") or ticker) != ticker:
        paper["last_message"] = "Kalshi ticker mismatch; no paper action."
        return paper

    position = paper.get("open_position")
    if position:
        bid, _ = _quotes(market, position["side"])
        expired = now >= _f(position.get("expires_at"), now + 1)
        if expired:
            result = str(market.get("result") or "").lower()
            status = str(market.get("status") or "").lower()
            if result in {"yes", "no"} and status in {"settled", "finalized"}:
                _close(paper, position, 1.0 if position["side"].lower() == result else 0.0, "OFFICIAL_SETTLEMENT:" + result, now, False)
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
                if gain >= entry_price * SCALP_MIN_GROSS_RETURN:
                    _close(paper, position, bid, "TAKE_PROFIT_20_PCT_GROSS", now)
                elif gain <= -SCALP_STOP_LOSS_POINTS:
                    _close(paper, position, bid, "STOP_LOSS_5_POINTS", now)
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
        paper["last_message"] = "Skipped PAPER entry: executable quote unavailable."
        return paper
    if ask > MAX_ENTRY_PRICE:
        paper["last_message"] = f"Skipped PAPER entry: Kalshi price {ask*100:.0f}% is above the 75% maximum."
        return paper
    same_market = [t for t in paper.get("trades", []) if t.get("ticker") == ticker and t.get("strategy") == strategy]
    if len(same_market) >= (MAX_LOCKS_PER_MARKET if strategy == "LOCK" else MAX_SCALPS_PER_MARKET):
        paper["last_message"] = f"Skipped PAPER {strategy}: per-market limit reached."
        return paper
    if strategy == "SCALP":
        if not gate["approved"]:
            paper["last_message"] = "Skipped PAPER SCALP: " + gate["reason"]
            return paper
        projected = _projected_side_value(pending, market, side)
        required_exit = ask * (1.0 + SCALP_MIN_GROSS_RETURN)
        if projected is None or projected < required_exit:
            text = "unavailable" if projected is None else f"{projected*100:.0f}%"
            paper["last_message"] = (
                f"Skipped PAPER SCALP: projected exit {text} is below the "
                f"{SCALP_MIN_GROSS_RETURN*100:.0f}% gross-return target "
                f"({required_exit*100:.0f}%)."
            )
            return paper
        losses = sum(1 for t in same_market if _f(t.get("pnl"), 0.0) < 0)
        if losses >= MAX_SCALP_LOSSES_PER_MARKET:
            paper["last_message"] = "Skipped PAPER SCALP: two-loss market circuit breaker is active."
            return paper
        key = ticker + ":" + side
        if paper.setdefault("rearm", {}).get(key) is False:
            paper["last_message"] = "Skipped PAPER SCALP: waiting for a fresh signal before re-entry."
            return paper

    budget = max(0.0, paper["cash"]) * UNPROVEN_POSITION_CAP
    contracts = int(budget // max(ask, 0.01))
    while contracts and contracts * ask + kalshi_taker_fee(contracts, ask) > budget:
        contracts -= 1
    if contracts < 1:
        paper["last_message"] = "Skipped PAPER entry: paper allocation is too small."
        return paper
    fee = kalshi_taker_fee(contracts, ask)
    amount = contracts * ask + fee
    expires = _f(pending.get("expires_at"))
    position = {"ticker": ticker, "side": side, "direction": "UP" if side == "YES" else "DOWN", "strategy": strategy, "status": "OPEN", "opened_at": now, "expires_at": expires, "entry_price": ask, "spot_entry_price": _f(pending.get("start_price")), "contracts": contracts, "entry_fee": fee, "amount": amount, "last_mark": bid}
    paper["cash"] -= amount
    paper["open_position"] = position
    paper["last_message"] = f"Opened PAPER {strategy} {position['direction']} • Amount: ${amount:.2f} • Kalshi entry: {ask*100:.0f}%"
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
