"""BTCC-inspired execution preview for the paper-only Kalshi trader.

The exchange app puts the complete order economics in one compact ticket.
This module provides the same clarity without adding authentication, leverage,
deposits, or a live-order path.  It is deliberately pure so the preview can be
regression-tested independently from Streamlit.
"""

from __future__ import annotations

import math
import time

from kalshi_paper_engine import (
    entry_price_limit,
    SCALP_MIN_GROSS_RETURN,
    SCALP_STOP_LOSS_POINTS,
    UNPROVEN_POSITION_CAP,
    kalshi_taker_fee,
    executable_entry_quote,
    expected_lock_net_pnl,
    LOCK_MIN_CONFIDENCE,
    _quote as _execution_quote,
    _projected_scalp_exit,
)


def _finite(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _side_from_action(action):
    text = str(action or "").upper().strip()
    if text.endswith("UP"):
        return "YES"
    if text.endswith("DOWN"):
        return "NO"
    return None


def _quote(decision, side, ask=True):
    if side not in {"YES", "NO"}:
        return None
    return _execution_quote(decision, side, ask=ask)


def _contract_count(budget, entry_price):
    if budget <= 0 or entry_price is None or entry_price <= 0:
        return 0
    contracts = int(budget // max(entry_price, 0.01))
    while (
        contracts > 0
        and contracts * entry_price + kalshi_taker_fee(contracts, entry_price)
        > budget + 1e-12
    ):
        contracts -= 1
    return contracts


def _break_even_price(contracts, total_cost):
    if contracts < 1:
        return None
    # Kalshi prices trade in cents.  Return the first executable cent whose
    # proceeds, after the estimated taker fee, recover the full entry cost.
    for cents in range(1, 101):
        price = cents / 100.0
        proceeds = contracts * price - kalshi_taker_fee(contracts, price)
        if proceeds + 1e-12 >= total_cost:
            return price
    return 1.0


def build_pro_trade_ticket(decision, risk, paper_summary, has_open_position=False):
    """Return the paper order economics shown before any automatic entry.

    The authoritative background paper worker currently allocates the
    unproven-strategy cap per entry.  Mirroring that cap here prevents the UI
    from advertising a larger order than the worker can actually open.
    """

    action = str((decision or {}).get("action") or "HOLD").upper().strip()
    side = _side_from_action(action)
    strategy = "LOCK" if action.startswith("LOCK") else "SCALP" if action.startswith("SCALP") else "WAIT"
    direction = "UP" if side == "YES" else "DOWN" if side == "NO" else "WAIT"
    entry = _quote(decision or {}, side, ask=True)
    bid = _quote(decision or {}, side, ask=False)
    cash = max(0.0, _finite((paper_summary or {}).get("cash"), 0.0))
    risk_pct = max(0.0, _finite((risk or {}).get("position_pct"), 0.0))
    allocation_pct = min(UNPROVEN_POSITION_CAP, risk_pct)
    budget = cash * allocation_pct
    valid_quote = executable_entry_quote(bid, entry)
    contracts = _contract_count(budget, entry) if valid_quote else 0
    entry_fee = (
        kalshi_taker_fee(contracts, entry)
        if contracts and entry is not None
        else 0.0
    )
    total_cost = (
        contracts * entry + entry_fee
        if contracts and entry is not None
        else 0.0
    )
    break_even = _break_even_price(contracts, total_cost)

    projected_exit = None
    if strategy == "SCALP":
        projected_exit = _projected_scalp_exit(decision or {})
    elif strategy == "LOCK":
        projected_exit = 1.0
    if projected_exit is not None:
        projected_exit = min(1.0, max(0.0, projected_exit))

    projected_exit_fee = (
        kalshi_taker_fee(contracts, projected_exit)
        if contracts and projected_exit is not None
        else 0.0
    )
    projected_net = (
        contracts * projected_exit - projected_exit_fee - total_cost
        if contracts and projected_exit is not None
        else None
    )
    projected_return = (
        projected_net / total_cost
        if projected_net is not None and total_cost > 0
        else None
    )

    take_profit = None
    emergency_stop = None
    if entry is not None and strategy == "SCALP":
        take_profit = min(1.0, entry * (1.0 + SCALP_MIN_GROSS_RETURN))
        emergency_stop = max(0.0, entry - SCALP_STOP_LOSS_POINTS)

    blockers = []
    if side is None:
        blockers.append("Master AI is waiting for a qualified call")
    if has_open_position:
        blockers.append("one paper position is already open")
    now = time.time()
    expires = _finite((decision or {}).get("kalshi_close_ts"))
    if expires is None:
        remaining = _finite((decision or {}).get("seconds_remaining"))
        expires = now + remaining if remaining is not None else None
    if expires is None or expires <= now:
        blockers.append("Kalshi window is expired or expiry is unavailable")
    if not valid_quote and side is not None:
        blockers.append("selected-side Kalshi executable quote is unavailable or invalid")
    if (decision or {}).get("execution_approved") is False:
        blockers.append("reliability gate blocked PAPER entry")
    if strategy == "SCALP" and not bool((risk or {}).get("approved")):
        blockers.append("risk manager has not approved the SCALP")
    if strategy == "SCALP":
        if (projected_exit is None or entry is None
                or projected_exit < entry * (1.0 + SCALP_MIN_GROSS_RETURN) - 1e-12):
            blockers.append("projected SCALP exit is below the required gross-return target")
        if projected_net is None or projected_net <= 0:
            blockers.append("projected SCALP profit is not positive after entry and exit fees")
    if strategy in {"SCALP", "LOCK"} and entry is not None and entry > entry_price_limit(strategy):
        blockers.append(f"{strategy} entry is above the {entry_price_limit(strategy) * 100:.0f}% cap")
    if side is not None and contracts < 1:
        blockers.append("paper allocation is too small for one contract")
    expected_net = None
    if strategy == "LOCK":
        confidence = _finite((decision or {}).get("confidence"), 0.0)
        if confidence > 1:
            confidence /= 100.0
        if confidence < LOCK_MIN_CONFIDENCE:
            blockers.append("LOCK confidence is below the 68% floor")
        if contracts:
            expected_net = expected_lock_net_pnl(contracts, entry, decision or {}, side)
        if expected_net is None or expected_net <= 0:
            blockers.append("expected LOCK settlement profit is unavailable or not positive after entry fees")

    return {
        "action": action,
        "strategy": strategy,
        "direction": direction,
        "side": side,
        "status": "READY" if not blockers else "WAIT",
        "blockers": blockers,
        "entry_price": entry,
        "current_bid": bid,
        "allocation_pct": allocation_pct,
        "budget": budget,
        "contracts": contracts,
        "entry_fee": entry_fee,
        "total_cost": total_cost,
        "max_loss": total_cost,
        "break_even_price": break_even,
        "take_profit_price": take_profit,
        "emergency_stop_price": emergency_stop,
        "projected_exit_price": projected_exit,
        "projected_exit_fee": projected_exit_fee,
        "projected_net_pnl": projected_net,
        "projected_return": projected_return,
        "expected_settlement_net_pnl": expected_net,
        "protection": (
            "AI reversal exit + 15-point emergency stop"
            if strategy == "SCALP"
            else "Immutable direction; official Kalshi settlement"
            if strategy == "LOCK"
            else "No order while the Master AI waits"
        ),
    }
