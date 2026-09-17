"""Shared paper-only policy for the temporary BTC LOCK-first mode."""

from __future__ import annotations

import math


AUTO_SCALPING_ENABLED = False
LOCK_FOCUS_ENABLED = True
LOCK_EARLIEST_SECONDS = 10 * 60
LOCK_LATEST_SECONDS = 30
# Live calibrated history tops out near 0.73 with a ~0.67 95th percentile.
# A 0.68 floor selects the strongest few percent without creating an
# impossible gate; independent checks below must still all pass.
LOCK_MIN_CONFIDENCE = 0.68
LOCK_MIN_CONSENSUS = 0.55
LOCK_MIN_SOURCE_HEALTH = 0.70
LOCK_MIN_ABS_SCORE = 0.20
LOCK_MIN_MARKET_SUPPORT = 0.52
LOCK_MAX_ENTRY_PRICE = 0.75


def _f(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _quote(market, name):
    value = _f((market or {}).get(name))
    if value is None:
        value = _f((market or {}).get(name + "_dollars"))
    if value is not None and 1.0 < value <= 100.0:
        value /= 100.0
    return value


def specialist_consensus(specialists, direction):
    """Confidence-weighted agreement with the proposed settlement side."""
    wanted = 1.0 if str(direction).upper() == "UP" else -1.0
    agreeing = total = 0.0
    for row in (specialists or {}).values():
        score = _f((row or {}).get("score"), 0.0)
        confidence = max(0.05, _f((row or {}).get("confidence"), 0.5))
        if abs(score) < 0.03:
            continue
        weight = confidence * min(1.0, abs(score) / 0.20)
        total += weight
        if score * wanted > 0:
            agreeing += weight
    return agreeing / total if total > 0 else 0.0


def evaluate_lock_focus(
    *,
    base_score,
    confidence,
    consensus,
    source_health,
    seconds_remaining,
    market,
    target_confirmed,
    edge_floor=0.0,
):
    """Return a guarded LOCK action or WAIT with auditable diagnostics."""
    base_score = _f(base_score, 0.0)
    confidence = _f(confidence, 0.0)
    consensus = _f(consensus, 0.0)
    source_health = _f(source_health, 0.0)
    seconds_remaining = _f(seconds_remaining)
    direction = "UP" if base_score > 0 else "DOWN"
    side = "YES" if direction == "UP" else "NO"
    bid = _quote(market, "yes_bid" if side == "YES" else "no_bid")
    ask = _quote(market, "yes_ask" if side == "YES" else "no_ask")
    if side == "NO":
        if ask is None:
            yes_bid = _quote(market, "yes_bid")
            ask = None if yes_bid is None else 1.0 - yes_bid
        if bid is None:
            yes_ask = _quote(market, "yes_ask")
            bid = None if yes_ask is None else 1.0 - yes_ask
    market_support = None if bid is None or ask is None else (bid + ask) / 2.0
    required_score = max(LOCK_MIN_ABS_SCORE, _f(edge_floor, 0.0))

    checks = {
        "window": seconds_remaining is not None and LOCK_LATEST_SECONDS < seconds_remaining <= LOCK_EARLIEST_SECONDS,
        "confidence": confidence >= LOCK_MIN_CONFIDENCE,
        "score": abs(base_score) >= required_score,
        "consensus": consensus >= LOCK_MIN_CONSENSUS,
        "source_health": source_health >= LOCK_MIN_SOURCE_HEALTH,
        "target_confirmed": bool(target_confirmed),
        "quote": ask is not None and bid is not None,
        "entry_price": ask is not None and ask <= LOCK_MAX_ENTRY_PRICE,
        "market_support": market_support is not None and market_support >= LOCK_MIN_MARKET_SUPPORT,
    }
    action = f"LOCK {direction}" if all(checks.values()) else "WAIT"
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "action": action,
        "direction": direction,
        "side": side,
        "eligible": action.startswith("LOCK"),
        "seconds_remaining": seconds_remaining,
        "confidence": confidence,
        "consensus": consensus,
        "source_health": source_health,
        "base_score": base_score,
        "required_score": required_score,
        "selected_bid": bid,
        "selected_ask": ask,
        "market_support": market_support,
        "checks": checks,
        "reason": (
            "Qualified LOCK-first setup"
            if action.startswith("LOCK")
            else "WAIT — " + ", ".join(failed)
        ),
    }
