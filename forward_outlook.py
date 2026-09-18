"""Paper-only forecasts for the three 15-minute markets after the active one."""

from __future__ import annotations

import math

import numpy as np

from ai_core import forecast_path_core
from multi_timeframe import summarize_context


OUTLOOK_HORIZONS = 3
MARKET_SECONDS = 15 * 60


def _f(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def build_next_market_outlooks(
    rows,
    forecast_state,
    current_expires_at,
    confidence,
    consensus,
    horizon_stats=None,
    horizon_state=None,
):
    """Project and expose the next three full market windows.

    These are research forecasts, not executable orders. Each forecast is tied
    to an exact future 15-minute boundary so the learner can grade it later.
    """
    current_expires_at = _f(current_expires_at)
    forecast = forecast_path_core(rows, None, forecast_state or {})
    if current_expires_at is None or not forecast:
        return []

    inputs = forecast.get("inputs") or {}
    last = _f(inputs.get("last"))
    if last is None or last <= 0:
        return []
    base_move = _f(forecast.get("raw_projected_move"), 0.0)
    fast_minus_slow = _f(inputs.get("ret3"), 0.0) - _f(inputs.get("ret15"), 0.0)
    confidence = float(np.clip(_f(confidence, 0.5), 0.5, 0.99))
    consensus = float(np.clip(_f(consensus, 0.0), 0.0, 1.0))
    stats = horizon_stats if isinstance(horizon_stats, dict) else {}
    context = summarize_context((horizon_state or {}).get("latest_context", {}))
    context_score = _f(context.get("score"), 0.0)

    projected_open = _f(forecast.get("predicted_end"), last)
    outlooks = []
    for horizon in range(1, OUTLOOK_HORIZONS + 1):
        # Momentum persists but decays; a fast-vs-slow stretch contributes a
        # bounded mean-reversion term. This can forecast a later flip instead
        # of blindly repeating the same direction three times.
        persistence = 0.78 ** horizon
        reversal = -last * fast_minus_slow * (0.10 + 0.05 * horizon)
        # Higher frames are a bounded, decaying early-warning prior here. This
        # surface is research-only and cannot place or change an order.
        context_move = last * context_score * 0.0015 * (0.86 ** (horizon - 1))
        move = base_move * persistence + reversal + context_move
        move = float(np.clip(move, -last * 0.012, last * 0.012))
        projected_close = projected_open + move
        direction = "UP" if move >= 0 else "DOWN"

        evidence_confidence = 0.5 + (confidence - 0.5) * (0.82 ** horizon)
        evidence_confidence = 0.5 + (evidence_confidence - 0.5) * (0.65 + 0.35 * consensus)
        h_stats = stats.get(str(horizon), stats.get(horizon, {})) or {}
        samples = int(_f(h_stats.get("samples"), 0.0))
        accuracy = _f(h_stats.get("accuracy"))
        if samples >= 20 and accuracy is not None:
            reliability = float(np.clip((accuracy - 0.5) * 2.0, 0.25, 1.10))
            evidence_confidence = 0.5 + (evidence_confidence - 0.5) * reliability

        window_start = current_expires_at + MARKET_SECONDS * (horizon - 1)
        expires_at = window_start + MARKET_SECONDS
        outlooks.append({
            "horizon": horizon,
            "minutes_ahead": horizon * 15,
            "window_start": window_start,
            "expires_at": expires_at,
            "direction": direction,
            "projected_open": projected_open,
            "projected_close": projected_close,
            "projected_move": move,
            "confidence": float(np.clip(evidence_confidence, 0.5, 0.90)),
            "research_only": True,
            "executable": False,
            "graded_samples": samples,
            "higher_timeframe_context": context_score,
            "context_direction": context.get("direction", "MIXED"),
            "context_agreement": context.get("agreement", 0.0),
        })
        projected_open = projected_close
    return outlooks
