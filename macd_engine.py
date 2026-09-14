"""Adaptive, volatility-normalized MACD features for the 15-minute engine.

The standard 12/26/9 MACD remains the slow confirmation layer.  A 6/13/5
MACD provides earlier information on one-minute candles.  Scoring requires
direction, slope, and local trend to agree, and deliberately suppresses tiny
zero-line flips so a single crossover cannot create false conviction.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _clamp(value, lo=-1.0, hi=1.0):
    return float(max(lo, min(hi, _finite(value))))


def add_macd_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return *frame* with standard and fast MACD columns added."""
    x = frame.copy()
    close = pd.to_numeric(x["close"], errors="coerce")

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["macd_hist"] = x["macd"] - x["macd_signal"]

    ema6 = close.ewm(span=6, adjust=False).mean()
    ema13 = close.ewm(span=13, adjust=False).mean()
    x["macd_fast"] = ema6 - ema13
    x["macd_fast_signal"] = x["macd_fast"].ewm(span=5, adjust=False).mean()
    x["macd_fast_hist"] = x["macd_fast"] - x["macd_fast_signal"]

    x["macd_hist_slope"] = x["macd_hist"].diff()
    x["macd_hist_accel"] = x["macd_hist_slope"].diff()
    return x


def score_macd(hist: pd.DataFrame) -> dict:
    """Score MACD from -1 (bearish) to +1 (bullish).

    The normalization uses ATR so identical MACD values do not imply the same
    conviction in quiet and volatile markets.  Standard/fast disagreement is
    damped; weak values near zero are treated as noise.
    """
    if hist is None or len(hist) < 30:
        return {
            "score": 0.0,
            "state": "warming up",
            "standard_hist": 0.0,
            "fast_hist": 0.0,
            "slope": 0.0,
            "acceleration": 0.0,
            "cross": "none",
            "agreement": "insufficient history",
        }

    required = {"macd", "macd_signal", "macd_hist", "macd_fast", "macd_fast_signal", "macd_fast_hist"}
    x = hist if required.issubset(hist.columns) else add_macd_features(hist)
    last, prev, prior = x.iloc[-1], x.iloc[-2], x.iloc[-3]
    px = max(abs(_finite(last.get("close"), 0.0)), 1.0)

    atr = _finite(last.get("atr14"), 0.0)
    if atr <= 0.0 and {"high", "low", "close"}.issubset(x.columns):
        tail = x.tail(15)
        previous_close = tail["close"].shift()
        tr = pd.concat(
            [
                tail["high"] - tail["low"],
                (tail["high"] - previous_close).abs(),
                (tail["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = _finite(tr.mean(), 0.0)

    # A floor keeps a flat/low-volatility feed from magnifying penny-size noise.
    scale = max(atr * 0.32, px * 0.00018, 1e-9)
    fast_scale = max(atr * 0.24, px * 0.00013, 1e-9)
    standard_hist = _finite(last.get("macd_hist"))
    fast_hist = _finite(last.get("macd_fast_hist"))
    prev_hist = _finite(prev.get("macd_hist"))
    prior_hist = _finite(prior.get("macd_hist"))
    slope = standard_hist - prev_hist
    acceleration = slope - (prev_hist - prior_hist)

    standard_component = math.tanh(standard_hist / scale)
    fast_component = math.tanh(fast_hist / fast_scale)
    slope_component = math.tanh(slope / max(scale * 0.32, 1e-9))
    accel_component = math.tanh(acceleration / max(scale * 0.24, 1e-9))

    ema9 = _finite(last.get("ema9"), px)
    ema21 = _finite(last.get("ema21"), px)
    trend_component = math.tanh((ema9 - ema21) / max(atr * 1.4, px * 0.0008, 1e-9))

    now_macd = _finite(last.get("macd"))
    now_signal = _finite(last.get("macd_signal"))
    prev_macd = _finite(prev.get("macd"))
    prev_signal = _finite(prev.get("macd_signal"))
    bullish_cross = prev_macd <= prev_signal and now_macd > now_signal
    bearish_cross = prev_macd >= prev_signal and now_macd < now_signal
    cross = "bullish" if bullish_cross else "bearish" if bearish_cross else "none"

    score = (
        0.34 * standard_component
        + 0.28 * fast_component
        + 0.20 * slope_component
        + 0.06 * accel_component
        + 0.12 * trend_component
    )

    standard_direction = int(np.sign(standard_hist))
    fast_direction = int(np.sign(fast_hist))
    if standard_direction and fast_direction and standard_direction != fast_direction:
        score *= 0.55
        agreement = "fast/standard conflict"
    elif standard_direction and standard_direction == fast_direction:
        agreement = "fast/standard aligned"
    else:
        agreement = "mixed"

    # Crosses are useful only when momentum is already moving with the cross.
    if bullish_cross and fast_component > 0.08 and slope_component > 0.08:
        score += 0.10
    elif bearish_cross and fast_component < -0.08 and slope_component < -0.08:
        score -= 0.10

    weak = abs(standard_component) < 0.08 and abs(fast_component) < 0.10 and abs(slope_component) < 0.12
    if weak:
        score *= 0.20
        state = "flat / noise filtered"
    elif score > 0.12:
        state = "bullish strengthening" if slope > 0 else "bullish fading"
    elif score < -0.12:
        state = "bearish strengthening" if slope < 0 else "bearish fading"
    else:
        state = "neutral / mixed"

    return {
        "score": _clamp(score),
        "state": state,
        "standard_hist": standard_hist,
        "fast_hist": fast_hist,
        "slope": slope,
        "acceleration": acceleration,
        "cross": cross,
        "agreement": agreement,
    }
