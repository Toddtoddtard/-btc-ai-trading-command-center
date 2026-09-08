import json
import math
from datetime import timezone

import numpy as np
import pandas as pd


def safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def detect_regime(hist):
    if hist is None or len(hist) < 50:
        return "UNKNOWN"
    row = hist.iloc[-1]
    px = safe_float(row.get("close"), 0.0)
    if px <= 0:
        return "UNKNOWN"
    ema9 = safe_float(row.get("ema9"), px)
    ema21 = safe_float(row.get("ema21"), px)
    ema50 = safe_float(row.get("ema50"), px)
    atr = safe_float(row.get("atr14"), px * 0.001)
    atr_pct = atr / px
    spread = abs(ema9 - ema50) / px
    slope = (ema9 - ema21) / px
    if atr_pct >= 0.0022:
        return "HIGH_VOL"
    if spread >= 0.0016:
        return "TREND_UP" if slope >= 0 else "TREND_DOWN"
    if atr_pct <= 0.0008:
        return "LOW_VOL_RANGE"
    return "RANGE"


def source_health_from_specialists(results):
    if not results:
        return 0.0
    health = 1.0
    penalties = 0.0
    checks = 0
    for name in ("Liquidity AI", "Derivatives AI", "Kalshi Context AI", "Whale AI"):
        item = results.get(name)
        if not item:
            penalties += 1.0
            checks += 1
            continue
        reason = str(item.get("reason", "")).lower()
        checks += 1
        if any(token in reason for token in ("unavailable", "missing", "failed", "0 btc")):
            penalties += 1.0
    if checks:
        health -= 0.10 * penalties
    return float(np.clip(health, 0.55, 1.0))


def learned_policy(state, regime="UNKNOWN"):
    state = state if isinstance(state, dict) else {}
    wait = state.get("wait_policy", {}) if isinstance(state.get("wait_policy", {}), dict) else {}
    base_conf = safe_float(wait.get("minimum_calibrated_confidence"), 0.56)
    base_edge = safe_float(wait.get("minimum_edge_score"), 0.16)
    regime_state = state.get("regimes", {}).get(regime, {}) if isinstance(state.get("regimes", {}), dict) else {}
    samples = int(safe_float(regime_state.get("samples"), 0))
    acc = safe_float(regime_state.get("ewma_accuracy"), 0.5)
    shrink = min(1.0, samples / 60.0)
    reliability = (acc - 0.5) * 2.0 * shrink

    # Participation-aware calibration: keep HOLD available, but do not require
    # near-perfect evidence before the bot is allowed to make a directional call.
    # Learning can still raise/lower these floors by regime as evidence matures.
    trade_conf = float(np.clip(base_conf - 0.045 * reliability, 0.50, 0.64))
    edge_floor = float(np.clip(base_edge - 0.035 * reliability, 0.10, 0.24))
    return {
        "trade_confidence_floor": trade_conf,
        # LOCK is a near-certain, once-per-market commitment. Unlike SCALP,
        # learning may not relax this hard confidence floor.
        "lock_confidence_floor": 0.95,
        "edge_floor": edge_floor,
        "regime": regime,
        "regime_samples": samples,
        "regime_accuracy": acc,
    }


def regime_specialist_weight(base_weight, specialist_state, regime):
    base = safe_float(base_weight, 1.0)
    specialist_state = specialist_state if isinstance(specialist_state, dict) else {}
    global_weight = safe_float(specialist_state.get("adaptive_weight"), 1.0)
    regime_state = specialist_state.get("regimes", {}).get(regime, {}) if isinstance(specialist_state.get("regimes", {}), dict) else {}
    n = int(safe_float(regime_state.get("samples"), 0))
    rw = safe_float(regime_state.get("adaptive_weight"), 1.0)
    shrink = min(1.0, n / 40.0)
    learned = (1.0 - shrink) * global_weight + shrink * rw
    return float(np.clip(base * learned, 0.25, 2.25))


def calibrate_confidence(confidence, consensus, policy, source_health=1.0, state=None):
    confidence = safe_float(confidence, 0.5)
    consensus = safe_float(consensus, 0.0)
    source_health = float(np.clip(source_health, 0.0, 1.0))
    state = state if isinstance(state, dict) else {}
    brier = safe_float(state.get("confidence_model", {}).get("brier_ewma"), 0.25)
    calibration_penalty = float(np.clip((brier - 0.20) * 0.42, 0.0, 0.10))
    disagreement_penalty = max(0.0, 0.28 - consensus) * 0.14
    feed_penalty = (1.0 - source_health) * 0.16
    result = confidence - calibration_penalty - disagreement_penalty - feed_penalty
    return float(np.clip(result, 0.40, 0.95))


def learned_trade_gate(action, confidence, base_score, consensus, policy, source_health=1.0):
    action = str(action or "HOLD").upper()
    if action in {"HOLD", "WAIT"}:
        return False, "WAIT"
    if source_health < 0.60:
        return False, "WAIT — FEED HEALTH"
    if consensus < 0.10:
        return False, "WAIT — COUNCIL CONFLICT"
    required = policy["lock_confidence_floor"] if action.startswith("LOCK") else policy["trade_confidence_floor"]
    if confidence < required:
        return False, "WAIT — CALIBRATION"
    if abs(safe_float(base_score, 0.0)) < policy["edge_floor"]:
        return False, "WAIT — EDGE"
    return True, action


def exact_expiry_row(df, expiry_ts, tolerance_seconds=75):
    if df is None or df.empty:
        return None
    expiry = pd.to_datetime(float(expiry_ts), unit="s", utc=True)
    # Binance timestamps identify candle OPEN time. Settlement must use a
    # candle that has fully closed at or before expiry, never the candle that
    # begins at expiry (which contains future price action).
    closes = pd.to_datetime(df["time"], utc=True, errors="coerce") + pd.Timedelta(minutes=1)
    ages = (expiry - closes).dt.total_seconds()
    eligible = ages[(ages >= 0) & (ages <= float(tolerance_seconds))]
    if eligible.empty:
        return None
    return df.loc[eligible.idxmin()]


def execution_cost_bps(notional, spread_bps=1.0, slippage_bps=1.5, fee_bps=4.0):
    notional = max(0.0, safe_float(notional, 0.0))
    total_bps = max(0.0, safe_float(spread_bps)) + max(0.0, safe_float(slippage_bps)) + max(0.0, safe_float(fee_bps))
    return notional * total_bps / 10000.0


def snapshot_payload(price, regime, policy, results, futures=None, kalshi=None, source_health=1.0):
    specialists = {}
    for name, item in (results or {}).items():
        specialists[name] = {
            "score": safe_float(item.get("score"), 0.0),
            "confidence": safe_float(item.get("confidence"), 0.0),
            "signal": str(item.get("signal", "NEUTRAL")),
        }
    return {
        "price": safe_float(price, 0.0),
        "regime": regime,
        "policy": policy,
        "source_health": safe_float(source_health, 0.0),
        "specialists": specialists,
        "futures": futures or {},
        "kalshi": kalshi or {},
    }
