#!/usr/bin/env python3
import copy
import json
import math
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import learner as legacy
from ai_core import forecast_path_core
from learning_prices import closed_price_at


def safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def detect_regime(df):
    if df is None or len(df) < 55:
        return "UNKNOWN"
    last = df.iloc[-1]
    px = safe_float(last.get("close"), 0.0)
    if px <= 0:
        return "UNKNOWN"
    ema9 = safe_float(last.get("ema9"), px)
    ema21 = safe_float(last.get("ema21"), px)
    ema50 = safe_float(last.get("ema50"), px)
    atr = safe_float(last.get("atr14"), px * 0.001)
    atr_pct = atr / px if px else 0.0
    spread = abs(ema9 - ema50) / px
    slope = (ema9 - ema21) / px

    if atr_pct >= 0.0022:
        return "HIGH_VOL"
    if spread >= 0.0016:
        return "TREND_UP" if slope >= 0 else "TREND_DOWN"
    if atr_pct <= 0.0008:
        return "LOW_VOL_RANGE"
    return "RANGE"


def ensure_v3(state):
    state["version"] = 3
    state.setdefault("validation", {})
    state.setdefault("rolling", {})
    state.setdefault("regimes", {})
    state.setdefault("confidence_model", {})
    state.setdefault("wait_policy", {})

    forecast = state.setdefault("forecast", {})
    forecast.setdefault("robust_abs_error", safe_float(forecast.get("avg_abs_error"), 0.0))
    forecast.setdefault("robust_path_error", safe_float(forecast.get("avg_path_error"), 0.0))
    forecast.setdefault("ewma_direction_accuracy", 0.5)
    forecast.setdefault("ewma_brier", 0.25)

    state["wait_policy"].setdefault("minimum_samples", 40)
    state["wait_policy"].setdefault("minimum_edge_score", 0.18)
    state["wait_policy"].setdefault("minimum_calibrated_confidence", 0.58)
    state["wait_policy"].setdefault("overconfidence_penalty", 0.0)

    for name in legacy.BOTS:
        spec = state.setdefault("specialists", {}).setdefault(name, {})
        spec.setdefault("adaptive_weight", 1.0)
        spec.setdefault("samples", 0)
        spec.setdefault("direction_hits", 0)
        spec.setdefault("ewma_accuracy", 0.5)
        spec.setdefault("ewma_edge", 0.0)
        spec.setdefault("ewma_calibration", 0.0)
        spec.setdefault("brier_ewma", 0.25)
        spec.setdefault("overconfident_misses", 0)
        spec.setdefault("reward_points", 0.0)
        spec.setdefault("reward_ewma", 0.0)
        spec.setdefault("rewarded_correct_calls", 0)
        spec.setdefault("regimes", {})
        # Older saved states may predate a newly added specialist. Keep the
        # parallel history mapping in sync during every state migration.
        state.setdefault("specialist_history", {}).setdefault(name, [])
    return state


def weighted_master_confidence(pending, state):
    calls = pending.get("specialists", {}) if isinstance(pending, dict) else {}
    if not calls:
        return 0.5, 0.0
    numerator = 0.0
    denom = 0.0
    signed = []
    for name, call in calls.items():
        if name == "Political Event Watch AI" and str(call.get("event_status", "INACTIVE")).upper() != "ACTIVE":
            continue
        if name == "Cross-Market Research AI" and str(call.get("research_status", "INACTIVE")).upper() != "ACTIVE":
            continue
        score = safe_float(call.get("score"), 0.0)
        confidence = safe_float(call.get("confidence"), 0.5)
        learned = state.get("specialists", {}).get(name, {})
        weight = safe_float(learned.get("adaptive_weight"), 1.0)
        numerator += score * confidence * weight
        denom += confidence * weight
        if abs(score) > 0.03:
            signed.append(1 if score > 0 else -1)
    base_score = numerator / denom if denom else 0.0
    consensus = abs(sum(signed)) / len(signed) if signed else 0.0
    raw_conf = float(np.clip(0.45 + abs(base_score) * 0.34 + consensus * 0.15, 0.45, 0.95))
    penalty = safe_float(state.get("wait_policy", {}).get("overconfidence_penalty"), 0.0)
    calibrated = float(np.clip(raw_conf - penalty, 0.40, 0.93))
    return calibrated, base_score


def update_rolling(state):
    hist = state.get("master_history", [])
    rolling = {}
    for window in (25, 50, 100, 250):
        rows = hist[-window:]
        if not rows:
            rolling[str(window)] = {"samples": 0, "direction_accuracy": None, "kalshi_accuracy": None, "median_abs_error": None, "median_path_error": None}
            continue
        direction = [safe_float(r.get("direction_correct"), 0.0) for r in rows if r.get("direction_correct") is not None]
        kalshi = [safe_float(r.get("kalshi_correct"), 0.0) for r in rows if r.get("kalshi_correct") is not None]
        abs_errors = [safe_float(r.get("abs_error"), np.nan) for r in rows]
        path_errors = [safe_float(r.get("path_error"), np.nan) for r in rows]
        abs_errors = [x for x in abs_errors if math.isfinite(x)]
        path_errors = [x for x in path_errors if math.isfinite(x)]
        rolling[str(window)] = {
            "samples": len(rows),
            "direction_accuracy": float(np.mean(direction)) if direction else None,
            "kalshi_accuracy": float(np.mean(kalshi)) if kalshi else None,
            "median_abs_error": float(np.median(abs_errors)) if abs_errors else None,
            "median_path_error": float(np.median(path_errors)) if path_errors else None,
        }
    state["rolling"] = rolling


def update_regime_learning(state, pending, actual_direction, realized_return, hit_master):
    regime = str(pending.get("regime") or "UNKNOWN")
    bucket = state.setdefault("regimes", {}).setdefault(regime, {
        "samples": 0,
        "direction_hits": 0,
        "ewma_accuracy": 0.5,
        "avg_abs_return": 0.0,
    })
    bucket["samples"] += 1
    bucket["direction_hits"] += int(hit_master)
    alpha = 0.12
    bucket["ewma_accuracy"] = (1 - alpha) * safe_float(bucket.get("ewma_accuracy"), 0.5) + alpha * int(hit_master)
    n = bucket["samples"]
    move = abs(realized_return)
    bucket["avg_abs_return"] = move if n == 1 else safe_float(bucket.get("avg_abs_return"), 0.0) + (move - safe_float(bucket.get("avg_abs_return"), 0.0)) / n

    for name, call in pending.get("specialists", {}).items():
        learned = state.get("specialists", {}).get(name)
        if not learned:
            continue
        score = safe_float(call.get("score"), 0.0)
        pred = 1 if score > 0.03 else -1 if score < -0.03 else 0
        hit = int(pred != 0 and pred == actual_direction)
        rb = learned.setdefault("regimes", {}).setdefault(regime, {"samples": 0, "hits": 0, "ewma_accuracy": 0.5, "adaptive_weight": 1.0})
        rb["samples"] += 1
        rb["hits"] += hit
        rb["ewma_accuracy"] = 0.88 * safe_float(rb.get("ewma_accuracy"), 0.5) + 0.12 * hit
        sample_shrink = min(1.0, rb["samples"] / 30.0)
        regime_quality = (rb["ewma_accuracy"] - 0.5) * 2.0
        target = 1.0 + sample_shrink * 0.55 * regime_quality
        rb["adaptive_weight"] = float(np.clip(0.88 * safe_float(rb.get("adaptive_weight"), 1.0) + 0.12 * target, 0.45, 1.65))


def recalibrate_weights(state, pending, actual_direction, realized_return):
    for name, call in pending.get("specialists", {}).items():
        learned = state.get("specialists", {}).get(name)
        if not learned:
            continue
        score = safe_float(call.get("score"), 0.0)
        conf = float(np.clip(safe_float(call.get("confidence"), 0.5), 0.01, 0.99))
        pred = 1 if score > 0.03 else -1 if score < -0.03 else 0
        if pred == 0:
            continue
        hit = int(pred == actual_direction)
        outcome = 1.0 if hit else 0.0
        brier = (conf - outcome) ** 2 if pred != 0 else 0.25
        learned["brier_ewma"] = 0.90 * safe_float(learned.get("brier_ewma"), 0.25) + 0.10 * brier
        if pred != 0 and not hit and conf >= 0.72:
            learned["overconfident_misses"] = int(learned.get("overconfident_misses", 0)) + 1

        sample_shrink = min(1.0, safe_float(learned.get("samples"), 0.0) / 60.0)
        accuracy_edge = (safe_float(learned.get("ewma_accuracy"), 0.5) - 0.5) * 2.0
        calibration_quality = 1.0 - min(1.0, safe_float(learned.get("brier_ewma"), 0.25) / 0.35)
        signed_edge = math.tanh(safe_float(learned.get("ewma_edge"), 0.0) * 4.0)
        reward_quality = math.tanh(safe_float(learned.get("reward_ewma"), 0.0) / 1.5)
        quality = (
            0.42 * accuracy_edge
            + 0.18 * signed_edge
            + 0.24 * (calibration_quality - 0.3)
            + 0.16 * reward_quality
        )
        target_weight = 1.0 + sample_shrink * quality
        learned["adaptive_weight"] = float(np.clip(0.86 * safe_float(learned.get("adaptive_weight"), 1.0) + 0.14 * target_weight, 0.30, 1.75))


def update_confidence_model(state, pending, hit_master):
    conf, base_score = weighted_master_confidence(pending, state)
    outcome = 1.0 if hit_master else 0.0
    brier = (conf - outcome) ** 2
    model = state.setdefault("confidence_model", {})
    model["samples"] = int(model.get("samples", 0)) + 1
    model["brier_ewma"] = 0.90 * safe_float(model.get("brier_ewma"), 0.25) + 0.10 * brier
    model["last_confidence"] = conf
    model["last_base_score"] = base_score
    model["last_correct"] = int(hit_master)

    penalty = float(np.clip((model["brier_ewma"] - 0.20) * 0.55, 0.0, 0.16))
    state.setdefault("wait_policy", {})["overconfidence_penalty"] = penalty
    samples = int(state.get("forecast", {}).get("samples", 0))
    state["wait_policy"]["minimum_calibrated_confidence"] = float(np.clip(0.61 - min(samples, 300) / 3000.0 + penalty * 0.6, 0.56, 0.68))
    state["wait_policy"]["minimum_edge_score"] = float(np.clip(0.20 + penalty * 0.65, 0.18, 0.30))


def robustify_forecast_metrics(state, last_row):
    forecast = state.get("forecast", {})
    hist = state.get("master_history", [])[-100:]
    abs_vals = [safe_float(r.get("abs_error"), np.nan) for r in hist]
    path_vals = [safe_float(r.get("path_error"), np.nan) for r in hist]
    abs_vals = np.array([x for x in abs_vals if math.isfinite(x)], dtype=float)
    path_vals = np.array([x for x in path_vals if math.isfinite(x)], dtype=float)
    if len(abs_vals):
        med = float(np.median(abs_vals))
        mad = float(np.median(np.abs(abs_vals - med)))
        cap = med + 4.0 * max(mad, 1.0)
        forecast["robust_abs_error"] = float(np.mean(np.clip(abs_vals, 0.0, cap)))
    if len(path_vals):
        med = float(np.median(path_vals))
        mad = float(np.median(np.abs(path_vals - med)))
        cap = med + 4.0 * max(mad, 1.0)
        forecast["robust_path_error"] = float(np.mean(np.clip(path_vals, 0.0, cap)))
    hits = [safe_float(r.get("direction_correct"), np.nan) for r in hist if r.get("direction_correct") is not None]
    if hits:
        ewma = 0.5
        for hit in hits:
            ewma = 0.92 * ewma + 0.08 * hit
        forecast["ewma_direction_accuracy"] = float(ewma)


def walk_forward_validate(df, state):
    if df is None or len(df) < 100:
        return {"samples": 0, "direction_accuracy": None, "mae": None, "median_abs_error": None, "regimes": {}}
    cfg = state.get("forecast", {})
    outcomes = []
    start = max(60, len(df) - 210)
    for end_idx in range(start, len(df) - 15, 15):
        train_slice = df.iloc[: end_idx + 1]
        rows = legacy.rows_for_forecast(train_slice)
        forecast = forecast_path_core(rows, None, cfg)
        if not forecast:
            continue
        start_price = safe_float(train_slice.close.iloc[-1], 0.0)
        actual = safe_float(df.close.iloc[end_idx + 15], start_price)
        predicted = safe_float(forecast.get("predicted_end"), start_price)
        pred_dir = 1 if predicted >= start_price else -1
        actual_dir = 1 if actual >= start_price else -1
        outcomes.append({
            "hit": int(pred_dir == actual_dir),
            "error": abs(actual - predicted),
            "regime": detect_regime(train_slice),
        })
    if not outcomes:
        return {"samples": 0, "direction_accuracy": None, "mae": None, "median_abs_error": None, "regimes": {}}
    by_regime = {}
    for row in outcomes:
        bucket = by_regime.setdefault(row["regime"], {"samples": 0, "hits": 0, "errors": []})
        bucket["samples"] += 1
        bucket["hits"] += row["hit"]
        bucket["errors"].append(row["error"])
    regime_summary = {
        name: {
            "samples": b["samples"],
            "direction_accuracy": b["hits"] / b["samples"] if b["samples"] else None,
            "median_abs_error": float(np.median(b["errors"])) if b["errors"] else None,
        }
        for name, b in by_regime.items()
    }
    errors = [r["error"] for r in outcomes]
    return {
        "samples": len(outcomes),
        "direction_accuracy": float(np.mean([r["hit"] for r in outcomes])),
        "mae": float(np.mean(errors)),
        "median_abs_error": float(np.median(errors)),
        "regimes": regime_summary,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def enhanced_grade(state, df):
    pending_copy = copy.deepcopy(state.get("pending"))
    if not pending_copy or time.time() < safe_float(pending_copy.get("expires_at"), float("inf")):
        return False

    expiry = pd.to_datetime(pending_copy["expires_at"], unit="s", utc=True)
    actual = closed_price_at(df, expiry)
    if actual is None:
        return False
    actual = safe_float(actual, safe_float(pending_copy.get("start_price"), 0.0))
    start = safe_float(pending_copy.get("start_price"), actual)
    predicted_end = safe_float(pending_copy.get("predicted_end"), start)
    actual_direction = 1 if actual >= start else -1
    master_pred = int(pending_copy.get("predicted_direction", 1))
    master_hit = int(actual_direction == master_pred)
    realized_return = (actual / start - 1.0) if start else 0.0

    graded = legacy.grade(state, df)
    if not graded:
        return False

    if state.get("master_history"):
        state["master_history"][-1]["regime"] = pending_copy.get("regime", "UNKNOWN")
        state["master_history"][-1]["master_confidence"] = safe_float(pending_copy.get("master_confidence"), 0.5)
        state["master_history"][-1]["realized_return"] = realized_return

    update_regime_learning(state, pending_copy, actual_direction, realized_return, master_hit)
    recalibrate_weights(state, pending_copy, actual_direction, realized_return)
    update_confidence_model(state, pending_copy, master_hit)
    robustify_forecast_metrics(state, state.get("master_history", [{}])[-1])
    update_rolling(state)
    return True


def enhanced_register(state, df, market_info):
    if not market_info or state.get("pending") is not None:
        return False
    registered = legacy.register(state, df, market_info)
    if registered and state.get("pending"):
        state["pending"]["regime"] = detect_regime(df)
        confidence, base_score = weighted_master_confidence(state["pending"], state)
        state["pending"]["master_confidence"] = confidence
        state["pending"]["master_base_score"] = base_score
        wait = state.get("wait_policy", {})
        state["pending"]["would_wait"] = bool(
            abs(base_score) < safe_float(wait.get("minimum_edge_score"), 0.18)
            or confidence < safe_float(wait.get("minimum_calibrated_confidence"), 0.58)
        )
    return registered


def main():
    state = ensure_v3(legacy.load())
    df = legacy.history()
    market_info = legacy.market()

    graded = enhanced_grade(state, df)
    official_resolved = legacy.resolve_official_results(state)
    registered = enhanced_register(state, df, market_info)

    state["validation"] = walk_forward_validate(df, state)
    update_rolling(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    forecast = state["forecast"]
    kalshi_samples = int(forecast.get("kalshi_samples", 0))
    wait = state.get("wait_policy", {})
    current_regime = detect_regime(df)
    state["status"].update({
        "worker_ok": True,
        "shared_core": True,
        "learning_version": 3,
        "graded_this_run": graded,
        "official_results_resolved": official_resolved,
        "registered_this_run": registered,
        "btc_price": float(df.close.iloc[-1]),
        "active_ticker": market_info["ticker"] if market_info else "",
        "active_target": market_info["target"] if market_info else None,
        "forecast_samples": forecast.get("samples", 0),
        "kalshi_samples": kalshi_samples,
        "kalshi_accuracy": (forecast.get("kalshi_hits", 0) / kalshi_samples) if kalshi_samples else None,
        "current_regime": current_regime,
        "wait_confidence_floor": wait.get("minimum_calibrated_confidence"),
        "wait_edge_floor": wait.get("minimum_edge_score"),
        "walk_forward_samples": state.get("validation", {}).get("samples", 0),
        "walk_forward_accuracy": state.get("validation", {}).get("direction_accuracy"),
        "robust_abs_error": forecast.get("robust_abs_error"),
        "robust_path_error": forecast.get("robust_path_error"),
    })

    legacy.OUT.parent.mkdir(parents=True, exist_ok=True)
    legacy.OUT.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps(state["status"], indent=2))


if __name__ == "__main__":
    main()
