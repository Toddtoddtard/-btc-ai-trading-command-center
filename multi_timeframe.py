"""Causal higher-timeframe context for BTC forecasts.

Only completed Binance candles are accepted.  The returned values are bounded,
scale-adjusted returns so a monthly candle cannot numerically overwhelm a
30-minute candle merely because its raw move is larger.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np


TIMEFRAME_SPECS = (
    ("context_30m", "30m", 0.012),
    ("context_1h", "1h", 0.020),
    ("context_4h", "4h", 0.040),
    ("context_12h", "12h", 0.070),
    ("context_1d", "1d", 0.100),
    ("context_1w", "1w", 0.220),
    ("context_1mo", "1M", 0.450),
)
CONTEXT_FEATURE_NAMES = tuple(row[0] for row in TIMEFRAME_SPECS)


def _finite(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def normalize_return(raw_return, scale):
    value = _finite(raw_return, 0.0)
    return float(np.clip(math.tanh(value / float(scale)), -1.0, 1.0))


def context_vector(context):
    context = context if isinstance(context, dict) else {}
    values = context.get("features", context)
    return np.asarray([_finite(values.get(name), 0.0) for name in CONTEXT_FEATURE_NAMES], dtype=float)


def summarize_context(context):
    vector = context_vector(context)
    available = int((context or {}).get("available_timeframes", 0)) if isinstance(context, dict) else 0
    score = float(np.mean(vector)) if len(vector) else 0.0
    nonzero = vector[np.abs(vector) > 1e-9]
    agreement = float(np.mean(np.sign(nonzero) == np.sign(score))) if len(nonzero) and score else 0.0
    return {
        "score": score,
        "direction": "UP" if score > 0.03 else "DOWN" if score < -0.03 else "MIXED",
        "agreement": agreement,
        "available_timeframes": available,
        "total_timeframes": len(TIMEFRAME_SPECS),
        "research_only": True,
    }


def _closed_candle_feature(get_json, base_url, interval, scale, now_ms):
    rows = get_json(
        base_url + "/api/v3/klines",
        {"symbol": "BTCUSDT", "interval": interval, "limit": 4},
    )
    closed = [row for row in rows if len(row) >= 7 and _finite(row[6], now_ms + 1) < now_ms]
    if not closed:
        return None
    row = max(closed, key=lambda item: float(item[6]))
    open_price = _finite(row[1])
    close_price = _finite(row[4])
    if open_price is None or close_price is None or open_price <= 0:
        return None
    raw_return = close_price / open_price - 1.0
    return {
        "value": normalize_return(raw_return, scale),
        "raw_return": raw_return,
        "open_time": int(float(row[0])),
        "close_time": int(float(row[6])),
        "closed": True,
    }


def fetch_multi_timeframe_context(get_json, base_url, now_ms=None):
    """Fetch all requested frames concurrently from public market-data reads."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    details = {}
    with ThreadPoolExecutor(max_workers=len(TIMEFRAME_SPECS), thread_name_prefix="btc-context") as pool:
        jobs = {
            pool.submit(_closed_candle_feature, get_json, base_url, interval, scale, now_ms): (name, interval)
            for name, interval, scale in TIMEFRAME_SPECS
        }
        for job in as_completed(jobs):
            name, interval = jobs[job]
            try:
                row = job.result()
            except Exception:
                row = None
            if row is not None:
                details[name] = {"interval": interval, **row}

    features = {name: _finite(details.get(name, {}).get("value"), 0.0) for name in CONTEXT_FEATURE_NAMES}
    result = {
        "version": 1,
        "source": "Binance public closed klines",
        "fetched_at": now_ms / 1000.0,
        "features": features,
        "details": details,
        "available_timeframes": len(details),
        "all_closed": len(details) == len(TIMEFRAME_SPECS) and all(
            row.get("closed") is True for row in details.values()
        ),
    }
    result["summary"] = summarize_context(result)
    return result
