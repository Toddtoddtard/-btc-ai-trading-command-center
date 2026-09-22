"""Leakage-safe, horizon-specific probability models for BTC direction.

The models are deliberately small and JSON-serializable.  A prediction is
stored before its label exists, graded test-then-train, and may influence the
production forecast only after repeated live Brier-score outperformance.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from multi_timeframe import CONTEXT_FEATURE_NAMES, context_vector, summarize_context


HORIZONS = (1, 5, 15)
BASE_FEATURE_NAMES = (
    "ret1", "ret3", "ret5", "ret15", "ret30", "ret60",
    "trend_5_20", "vol_ratio_5_30", "body", "range_position_20",
    "zscore_20", "volume_z", "tod_sin", "tod_cos",
)
FEATURE_NAMES = BASE_FEATURE_NAMES + CONTEXT_FEATURE_NAMES
MODEL_VERSION = 2
MIN_LIVE_SAMPLES = 200
PROMOTION_REQUIRED_STREAK = 3
MIN_DIRECTIONAL_ACCURACY = 0.70
MIN_BRIER_EDGE = 0.005
MIN_RECENT_BRIER_EDGE = 0.003
MAX_PENDING = 120
MAX_RECENT = 200


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _bounded(value, lo=-5.0, hi=5.0):
    return float(np.clip(_finite(value), lo, hi))


def _sigmoid(value):
    value = float(np.clip(_finite(value), -20.0, 20.0))
    return 1.0 / (1.0 + math.exp(-value))


def _as_frame(rows):
    frame = pd.DataFrame(list(rows or []))
    required = {"open", "high", "low", "close"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    for column in required | {"volume"}:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])


def feature_vector(rows, context=None):
    """Build bounded scale-free features using only observations in ``rows``."""
    frame = _as_frame(rows)
    if len(frame) < 61:
        return None
    close = frame["close"].astype(float).to_numpy()
    last = float(close[-1])
    if last <= 0:
        return None

    def ret(lag, scale):
        return _bounded(math.tanh((last / float(close[-lag - 1]) - 1.0) / scale))

    returns = np.diff(np.log(np.maximum(close, 1e-12)))
    vol5 = float(np.std(returns[-5:]))
    vol30 = float(np.std(returns[-30:]))
    mean5 = float(np.mean(close[-5:]))
    mean20 = float(np.mean(close[-20:]))
    std20 = max(float(np.std(close[-20:])), last * 1e-6)
    high20 = float(frame["high"].tail(20).max())
    low20 = float(frame["low"].tail(20).min())
    span20 = max(high20 - low20, last * 1e-6)
    latest = frame.iloc[-1]
    candle_range = max(float(latest["high"]) - float(latest["low"]), last * 1e-6)

    volume_z = 0.0
    if "volume" in frame and frame["volume"].notna().sum() >= 20:
        volumes = frame["volume"].astype(float).tail(20)
        volume_std = float(volumes.std())
        if volume_std > 0:
            volume_z = (float(volumes.iloc[-1]) - float(volumes.mean())) / volume_std

    minute = None
    if "time" in frame:
        try:
            stamp = pd.Timestamp(frame["time"].iloc[-1])
            minute = stamp.hour * 60 + stamp.minute
        except Exception:
            minute = None
    angle = 0.0 if minute is None else 2.0 * math.pi * minute / 1440.0

    values = (
        ret(1, 0.0015),
        ret(3, 0.0030),
        ret(5, 0.0040),
        ret(15, 0.0080),
        ret(30, 0.0120),
        ret(60, 0.0200),
        _bounded(math.tanh(((mean5 / mean20) - 1.0) / 0.0030)),
        _bounded(math.tanh(((vol5 / max(vol30, 1e-8)) - 1.0))),
        _bounded((float(latest["close"]) - float(latest["open"])) / candle_range),
        _bounded(((last - low20) / span20) * 2.0 - 1.0),
        _bounded((last - mean20) / (2.0 * std20)),
        _bounded(volume_z / 3.0),
        math.sin(angle),
        math.cos(angle),
    )
    return np.concatenate((np.asarray(values, dtype=float), context_vector(context)))


def default_model(horizon):
    return {
        "horizon_minutes": int(horizon),
        "feature_names": list(FEATURE_NAMES),
        "weights": [0.0] * len(FEATURE_NAMES),
        "bias": 0.0,
        "learning_rate": 0.035,
        "l2": 0.0005,
        "samples": 0,
        "hits": 0,
        "brier_sum": 0.0,
        "baseline_brier_sum": 0.0,
        "baseline_hits": 0,
        "recent": [],
        "qualification_streak": 0,
        "enabled": False,
        "historical_validated": False,
        "offline_metrics": {},
        "updated_at": None,
    }


def ensure_horizon_state(state):
    root = state.setdefault("horizon_models", {})
    schema_changed = (
        int(root.get("version", 0)) != MODEL_VERSION
        or root.get("feature_names") != list(FEATURE_NAMES)
    )
    if schema_changed:
        root["models"] = {}
        root["pending"] = []
        root["last_registered_minute"] = None
        root["affects_execution"] = False
        root["schema_migrated_at"] = datetime.now(timezone.utc).isoformat()
    root["version"] = MODEL_VERSION
    root["feature_names"] = list(FEATURE_NAMES)
    root.setdefault("paper_only", True)
    root.setdefault("affects_execution", False)
    root.setdefault("minimum_live_samples", MIN_LIVE_SAMPLES)
    root.setdefault("required_streak", PROMOTION_REQUIRED_STREAK)
    root["minimum_directional_accuracy"] = MIN_DIRECTIONAL_ACCURACY
    root.setdefault("pending", [])
    root.setdefault("last_registered_minute", None)
    models = root.setdefault("models", {})
    for horizon in HORIZONS:
        model = models.setdefault(str(horizon), default_model(horizon))
        fresh = default_model(horizon)
        for key, value in fresh.items():
            model.setdefault(key, value)
        if len(model.get("weights", [])) != len(FEATURE_NAMES):
            model["weights"] = fresh["weights"]
            model["enabled"] = False
    return root


def model_probability(model, features):
    if features is None:
        return 0.5
    weights = np.asarray(model.get("weights", []), dtype=float)
    if len(weights) != len(features):
        return 0.5
    raw = float(np.dot(weights, features)) + _finite(model.get("bias"), 0.0)
    temperature = max(0.50, min(2.50, _finite(model.get("temperature"), 1.0)))
    calibration_bias = _finite(model.get("calibration_bias"), 0.0)
    return float(np.clip(_sigmoid(raw / temperature + calibration_bias), 0.01, 0.99))


def predict_horizons(rows, state_or_root, context=None):
    root = (
        state_or_root.get("horizon_models", {})
        if isinstance(state_or_root, dict) and "horizon_models" in state_or_root
        else (state_or_root or {})
    )
    context = context if context is not None else root.get("latest_context", {})
    features = feature_vector(rows, context)
    models = root.get("models", {}) if isinstance(root, dict) else {}
    return {
        str(horizon): {
            "probability_up": model_probability(models.get(str(horizon), {}), features),
            "enabled": bool(models.get(str(horizon), {}).get("enabled", False)),
            "historical_validated": bool(models.get(str(horizon), {}).get("historical_validated", False)),
            "samples": int(models.get(str(horizon), {}).get("samples", 0)),
        }
        for horizon in HORIZONS
    }


def _phase(seconds_remaining):
    seconds = _finite(seconds_remaining, 900.0)
    if seconds <= 120:
        return "FINAL_2"
    if seconds <= 300:
        return "FINAL_5"
    if seconds <= 600:
        return "MIDDLE"
    return "OPEN"


def register_horizon_predictions(state, rows, observed_at=None, market_info=None, baseline=None):
    """Register one prediction set per observed minute before outcomes exist."""
    root = ensure_horizon_state(state)
    observed_at = time.time() if observed_at is None else float(observed_at)
    minute_key = int(observed_at // 60)
    if root.get("last_registered_minute") == minute_key:
        return False
    context = root.get("latest_context", {})
    features = feature_vector(rows, context)
    if features is None:
        return False
    frame = _as_frame(rows)
    start_price = float(frame["close"].iloc[-1])
    predictions = predict_horizons(rows, root, context)
    baseline = baseline if isinstance(baseline, dict) else {}
    root.setdefault("pending", []).append({
        "created_at": observed_at,
        "minute_key": minute_key,
        "start_price": start_price,
        "features": features.tolist(),
        "phase": _phase((market_info or {}).get("expires_at", observed_at + 900) - observed_at),
        "ticker": str((market_info or {}).get("ticker") or ""),
        "predictions": {
            str(h): {
                "target_at": observed_at + 60 * h,
                "probability_up": predictions[str(h)]["probability_up"],
                "baseline_probability_up": float(np.clip(_finite(baseline.get(str(h)), 0.5), 0.01, 0.99)),
            }
            for h in HORIZONS
        },
    })
    root["pending"] = root["pending"][-MAX_PENDING:]
    root["last_registered_minute"] = minute_key
    root["last_prediction"] = predictions
    root["early_context"] = summarize_context(context)
    return True


def _price_at_or_after(frame, target_at, tolerance_seconds=75):
    if frame.empty or "time" not in frame:
        return None
    times = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    closes_at = times + pd.Timedelta(minutes=1)
    target = pd.to_datetime(float(target_at), unit="s", utc=True)
    delta = (closes_at - target).dt.total_seconds().abs()
    valid = delta <= tolerance_seconds
    if not valid.any():
        return None
    idx = delta[valid].idxmin()
    return _finite(frame.loc[idx, "close"], None)


def _update_model(model, features, outcome, probability, baseline_probability):
    error = float(outcome) - float(probability)
    samples = int(model.get("samples", 0)) + 1
    learning_rate = _finite(model.get("learning_rate"), 0.035) / math.sqrt(max(1.0, samples / 100.0))
    l2 = _finite(model.get("l2"), 0.0005)
    weights = np.asarray(model.get("weights", [0.0] * len(features)), dtype=float)
    weights += learning_rate * (error * features - l2 * weights)
    weights = np.clip(weights, -3.0, 3.0)
    model["weights"] = weights.tolist()
    model["bias"] = float(np.clip(_finite(model.get("bias")) + learning_rate * error, -2.0, 2.0))
    model["samples"] = samples
    hit = int((probability >= 0.5) == bool(outcome))
    baseline_hit = int((baseline_probability >= 0.5) == bool(outcome))
    brier = (probability - outcome) ** 2
    baseline_brier = (baseline_probability - outcome) ** 2
    model["hits"] = int(model.get("hits", 0)) + hit
    model["baseline_hits"] = int(model.get("baseline_hits", 0)) + baseline_hit
    model["brier_sum"] = _finite(model.get("brier_sum")) + brier
    model["baseline_brier_sum"] = _finite(model.get("baseline_brier_sum")) + baseline_brier
    recent = model.setdefault("recent", [])
    recent.append({"brier": brier, "baseline_brier": baseline_brier, "hit": hit, "baseline_hit": baseline_hit})
    model["recent"] = recent[-MAX_RECENT:]
    model["updated_at"] = datetime.now(timezone.utc).isoformat()


def _evaluate_promotion(model):
    samples = int(model.get("samples", 0))
    recent = list(model.get("recent") or [])
    if not samples or not recent:
        return False
    brier = _finite(model.get("brier_sum")) / samples
    baseline_brier = _finite(model.get("baseline_brier_sum")) / samples
    accuracy = int(model.get("hits", 0)) / samples
    baseline_accuracy = int(model.get("baseline_hits", 0)) / samples
    recent_brier = float(np.mean([row["brier"] for row in recent]))
    recent_baseline = float(np.mean([row["baseline_brier"] for row in recent]))
    qualifies = bool(
        model.get("historical_validated")
        and samples >= MIN_LIVE_SAMPLES
        and baseline_brier - brier >= MIN_BRIER_EDGE
        and recent_baseline - recent_brier >= MIN_RECENT_BRIER_EDGE
        and accuracy >= MIN_DIRECTIONAL_ACCURACY
        and accuracy >= baseline_accuracy
    )
    streak = int(model.get("qualification_streak", 0)) + 1 if qualifies else 0
    model["qualification_streak"] = streak
    if streak >= PROMOTION_REQUIRED_STREAK:
        model["enabled"] = True
    if model.get("enabled"):
        disabled_reason = None
        if accuracy < MIN_DIRECTIONAL_ACCURACY:
            disabled_reason = "Directional accuracy fell below the 70% execution floor"
        elif len(recent) >= 50 and recent_brier - recent_baseline > 0.01:
            disabled_reason = "Recent Brier score fell behind the baseline"
        if disabled_reason:
            model["enabled"] = False
            model["qualification_streak"] = 0
            model["disabled_reason"] = disabled_reason
    model["metrics"] = {
        "samples": samples,
        "accuracy": accuracy,
        "baseline_accuracy": baseline_accuracy,
        "minimum_directional_accuracy": MIN_DIRECTIONAL_ACCURACY,
        "brier": brier,
        "baseline_brier": baseline_brier,
        "brier_edge": baseline_brier - brier,
        "recent_brier_edge": recent_baseline - recent_brier,
        "qualifies": qualifies,
    }
    return qualifies


def resolve_horizon_predictions(state, frame, now=None):
    """Grade matured forecasts before updating their models (prequential)."""
    root = ensure_horizon_state(state)
    frame = _as_frame(frame.to_dict("records") if isinstance(frame, pd.DataFrame) else frame)
    now = time.time() if now is None else float(now)
    unresolved = []
    graded = 0
    for record in root.get("pending", []):
        features = np.asarray(record.get("features", []), dtype=float)
        remaining = {}
        for key, prediction in (record.get("predictions") or {}).items():
            target_at = _finite(prediction.get("target_at"), now + 1)
            if target_at > now:
                remaining[key] = prediction
                continue
            actual_price = _price_at_or_after(frame, target_at)
            if actual_price is None:
                remaining[key] = prediction
                continue
            outcome = int(actual_price >= _finite(record.get("start_price"), actual_price))
            probability = float(np.clip(_finite(prediction.get("probability_up"), 0.5), 0.01, 0.99))
            baseline_probability = float(np.clip(_finite(prediction.get("baseline_probability_up"), 0.5), 0.01, 0.99))
            model = root["models"].get(key)
            if model is not None and len(features) == len(FEATURE_NAMES):
                _update_model(model, features, outcome, probability, baseline_probability)
                _evaluate_promotion(model)
                graded += 1
        if remaining:
            record["predictions"] = remaining
            unresolved.append(record)
    root["pending"] = unresolved[-MAX_PENDING:]
    root["affects_execution"] = any(bool(model.get("enabled")) for model in root["models"].values())
    root["graded_this_run"] = graded
    return graded


def baseline_probabilities(rows, forecast_result):
    """Convert the legacy path into comparable 1m/5m/15m probabilities."""
    frame = _as_frame(rows)
    path = (forecast_result or {}).get("forecast") or []
    if frame.empty or not path:
        return {str(h): 0.5 for h in HORIZONS}
    start = float(frame["close"].iloc[-1])
    ranges = (frame["high"] - frame["low"]).tail(30)
    avg_range = max(_finite(ranges.mean(), start * 0.0005), start * 1e-6)
    result = {}
    for horizon in HORIZONS:
        index = min(horizon, len(path)) - 1
        move = _finite(path[index].get("close"), start) - start
        scale = max(avg_range * math.sqrt(horizon), start * 0.00025)
        result[str(horizon)] = float(np.clip(_sigmoid(move / scale), 0.01, 0.99))
    return result


def merge_offline_bundle(state, bundle):
    """Install historical candidates without enabling execution influence."""
    root = ensure_horizon_state(state)
    if not isinstance(bundle, dict) or int(bundle.get("version", 0)) != MODEL_VERSION:
        return False
    changed = False
    for horizon in HORIZONS:
        incoming = (bundle.get("models") or {}).get(str(horizon), {})
        weights = incoming.get("weights")
        if len(weights or []) != len(FEATURE_NAMES):
            continue
        model = root["models"][str(horizon)]
        if str(model.get("offline_trained_through") or "") >= str(incoming.get("trained_through") or ""):
            continue
        model.update({
            "weights": [float(x) for x in weights],
            "bias": _finite(incoming.get("bias")),
            "temperature": _finite(incoming.get("temperature"), 1.0),
            "calibration_bias": _finite(incoming.get("calibration_bias"), 0.0),
            "historical_validated": bool(incoming.get("promotion_eligible", False)),
            "offline_metrics": incoming.get("validation", {}),
            "offline_trained_through": incoming.get("trained_through"),
            "enabled": False,
            "qualification_streak": 0,
            # A new offline candidate is a new model. Never attach the prior
            # candidate's live scorecard to different weights.
            "samples": 0,
            "hits": 0,
            "baseline_hits": 0,
            "brier_sum": 0.0,
            "baseline_brier_sum": 0.0,
            "recent": [],
        })
        changed = True
    root["offline_source"] = bundle.get("source")
    root["offline_generated_at"] = bundle.get("generated_at")
    return changed
