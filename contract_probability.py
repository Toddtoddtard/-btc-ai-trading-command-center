"""Causal probability helpers for KXBTC15M terminal-above-strike forecasts.

The dashboard's trading question is a binary terminal event, not whether the
next candle is green.  These helpers convert strike distance, remaining time,
recent realized volatility, the model score, and contemporaneous market depth
into a conservative probability.  The Kalshi midpoint remains the anchor so a
single model snapshot cannot manufacture a large paper-trading edge.
"""

from __future__ import annotations

import math


def _finite(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _clip(value, low, high):
    return min(high, max(low, float(value)))


def _logit(probability):
    probability = _clip(probability, 0.01, 0.99)
    return math.log(probability / (1.0 - probability))


def _sigmoid(value):
    value = _clip(value, -20.0, 20.0)
    return 1.0 / (1.0 + math.exp(-value))


def realized_minute_volatility(closes, lookback=60):
    """Return robust per-minute log-return volatility using only past closes."""
    source = [] if closes is None else closes
    clean = [value for value in (_finite(item) for item in source) if value and value > 0]
    clean = clean[-(max(3, int(lookback)) + 1):]
    if len(clean) < 4:
        return None
    returns = [math.log(clean[index] / clean[index - 1]) for index in range(1, len(clean))]
    center = sorted(returns)[len(returns) // 2]
    deviations = sorted(abs(value - center) for value in returns)
    mad = deviations[len(deviations) // 2]
    robust = 1.4826 * mad
    mean = sum(returns) / len(returns)
    ordinary = math.sqrt(sum((value - mean) ** 2 for value in returns) / len(returns))
    # The ordinary estimate reacts to real jumps; the robust component prevents
    # one bad print from dominating the entire 15-minute forecast.
    return max(1e-7, 0.65 * robust + 0.35 * ordinary)


def terminal_above_probability(
    spot,
    strike,
    seconds_remaining,
    volatility_per_minute,
    market_probability=None,
    model_score=0.0,
    orderbook=None,
    source_health=1.0,
):
    """Estimate P(terminal reference price > strike) with auditable components."""
    spot = _finite(spot)
    strike = _finite(strike)
    seconds = _finite(seconds_remaining)
    volatility = _finite(volatility_per_minute)
    if spot is None or strike is None or spot <= 0 or strike <= 0 or seconds is None:
        return {"available": False, "probability_up": None}

    minutes = max(1.0 / 60.0, seconds / 60.0)
    volatility = max(volatility or 0.0005, 1e-7)
    terminal_sigma_dollars = max(spot * volatility * math.sqrt(minutes), spot * 1e-6)
    normalized_distance = (spot - strike) / terminal_sigma_dollars
    statistical_probability = 0.5 * (1.0 + math.erf(normalized_distance / math.sqrt(2.0)))

    book = orderbook if isinstance(orderbook, dict) else {}
    depth_imbalance = _clip(_finite(book.get("weighted_depth_imbalance"), 0.0), -1.0, 1.0)
    microprice_edge = _finite(book.get("microprice_edge"), 0.0)
    spread = max(0.0, _finite(book.get("spread"), 0.0))
    micro_signal = _clip(depth_imbalance + microprice_edge / max(spread, 0.01), -1.0, 1.0)
    depth_concentration = _clip(_finite(book.get("depth_concentration"), 0.0), 0.0, 1.0)
    late_window_stress = bool(
        seconds <= 30.0
        and (
            spread >= 0.08
            or (spread >= 0.03 and abs(depth_imbalance) >= 0.90)
            or depth_concentration >= 0.95
        )
    )

    independent_log_odds = (
        _logit(_clip(statistical_probability, 0.01, 0.99))
        + 0.45 * _clip(_finite(model_score, 0.0), -1.0, 1.0)
        + 0.16 * micro_signal
    )
    independent_probability = _sigmoid(independent_log_odds)
    market = _finite(market_probability)
    health = _clip(_finite(source_health, 0.0), 0.0, 1.0)
    if market is not None and 0.0 <= market <= 1.0:
        market = _clip(market, 0.01, 0.99)
        # Start at 20% independent weight and permit at most 35% when feeds are
        # healthy.  This keeps the model a challenger to, not a replacement for,
        # the executable market estimate until walk-forward evidence promotes it.
        independent_weight = 0.20 + 0.15 * health
        probability_up = market + independent_weight * (independent_probability - market)
        market_edge = probability_up - market
    else:
        probability_up = 0.5 + health * (independent_probability - 0.5)
        market_edge = None

    probability_up = _clip(probability_up, 0.01, 0.99)
    return {
        "available": True,
        "probability_up": probability_up,
        "statistical_probability_up": _clip(statistical_probability, 0.01, 0.99),
        "independent_probability_up": _clip(independent_probability, 0.01, 0.99),
        "market_probability_up": market,
        "edge_vs_market": market_edge,
        "normalized_strike_distance": normalized_distance,
        "terminal_sigma_dollars": terminal_sigma_dollars,
        "volatility_per_minute": volatility,
        "microstructure_signal": micro_signal,
        "late_window_stress": late_window_stress,
        "late_window_stress_reason": (
            "Final-30-second spread/depth stress"
            if late_window_stress else "No abnormal final-window book stress"
        ),
        "seconds_remaining": seconds,
    }
