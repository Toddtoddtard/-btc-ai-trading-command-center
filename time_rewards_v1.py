"""Bounded, symmetric time-weighted learning rewards for 15-minute markets."""
from __future__ import annotations

import math

MARKET_WINDOW_SECONDS = 15.0 * 60.0
MIN_MAGNITUDE = 1.0
MAX_MAGNITUDE = 2.0


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def time_reward(opened_at, expires_at, correct, directional=True):
    """Reward an early correct call and equally penalize an early wrong call.

    A call made with the full 15-minute window remaining is worth +/-2 points.
    A call at expiry is worth +/-1 point. Neutral/no-call observations are zero.
    Symmetric loss magnitude prevents early random guessing from having positive
    expected reward.
    """
    if not directional:
        return {
            "points": 0.0,
            "magnitude": 0.0,
            "earliness": 0.0,
            "lead_seconds": 0.0,
        }
    expiry = _finite(expires_at)
    opened = _finite(opened_at, expiry)
    lead_seconds = max(0.0, min(MARKET_WINDOW_SECONDS, expiry - opened))
    earliness = lead_seconds / MARKET_WINDOW_SECONDS
    magnitude = MIN_MAGNITUDE + (MAX_MAGNITUDE - MIN_MAGNITUDE) * earliness
    return {
        "points": float(magnitude if bool(correct) else -magnitude),
        "magnitude": float(magnitude),
        "earliness": float(earliness),
        "lead_seconds": float(lead_seconds),
    }
