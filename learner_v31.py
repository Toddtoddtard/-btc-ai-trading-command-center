#!/usr/bin/env python3
import copy
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import learner as legacy
import learner_v3 as v3
from ai_core import forecast_path_core
from forward_outlook import build_next_market_outlooks
from horizon_models import (
    baseline_probabilities,
    ensure_horizon_state,
    merge_offline_bundle,
    register_horizon_predictions,
    resolve_horizon_predictions,
)
from lock_focus import (
    AUTO_SCALPING_ENABLED,
    LOCK_EARLIEST_SECONDS,
    LOCK_MAX_ENTRY_PRICE,
    LOCK_MIN_CONFIDENCE,
    evaluate_lock_focus,
    specialist_consensus,
)
from reliability_v31 import (
    detect_regime,
    exact_expiry_row,
    learned_policy,
    safe_float,
    source_health_from_specialists,
)
from research_lab import ensure_research_lab, register_shadow, resolve_shadows, update_lifecycles

PROMOTION_MIN_SAMPLES = 20
PROMOTION_REQUIRED_STREAK = 3
PROMOTION_ACCURACY_MARGIN = 0.05
PROMOTION_MAX_ERROR_MULTIPLIER = 1.10


def ensure_v31(state):
    state = v3.ensure_v3(state)
    state["version"] = 31
    state.setdefault("champion_challenger", {})
    state.setdefault("data_quality", {})
    state.setdefault("wait_counterfactual", {"samples": 0, "profitable_waits": 0, "avoided_losses": 0})
    state.setdefault("prediction_snapshots", [])
    state.setdefault("forward_outlook_history", [])
    state.setdefault("forward_outlook_stats", {})
    state.setdefault("next_market_outlooks", [])
    state["btc_execution_mode"] = {
        "name": "LOCK_FIRST",
        "paper_only": True,
        "auto_scalping_enabled": AUTO_SCALPING_ENABLED,
        "lock_focus_enabled": True,
        "earliest_lock_seconds": LOCK_EARLIEST_SECONDS,
        "confidence_floor": LOCK_MIN_CONFIDENCE,
        "maximum_entry_price": LOCK_MAX_ENTRY_PRICE,
    }
    state["status"].setdefault("learning_version", 31)
    ensure_research_lab(state)
    ensure_horizon_state(state)
    return state


def grade_forward_outlooks(state, df, now=None):
    """Grade future-window direction and Brier score at exact boundaries."""
    now = time.time() if now is None else float(now)
    graded = 0
    history = state.setdefault("forward_outlook_history", [])
    stats = state.setdefault("forward_outlook_stats", {})
    for row in history:
        if row.get("resolved") or safe_float(row.get("expires_at"), now + 1) > now:
            continue
        start_row = exact_expiry_row(df, row.get("window_start"))
        close_row = exact_expiry_row(df, row.get("expires_at"))
        if start_row is None or close_row is None:
            continue
        actual_open = safe_float(start_row.get("close"))
        actual_close = safe_float(close_row.get("close"))
        if actual_open is None or actual_close is None:
            continue
        actual_up = int(actual_close >= actual_open)
        predicted_up = str(row.get("direction", "")).upper() == "UP"
        confidence = float(np.clip(safe_float(row.get("confidence"), 0.5), 0.5, 0.99))
        probability_up = confidence if predicted_up else 1.0 - confidence
        correct = int(predicted_up == bool(actual_up))
        brier = float((probability_up - actual_up) ** 2)
        row.update({
            "resolved": True,
            "actual_open": actual_open,
            "actual_close": actual_close,
            "actual_direction": "UP" if actual_up else "DOWN",
            "correct": correct,
            "brier": brier,
        })
        key = str(int(row.get("horizon", 0)))
        bucket = stats.setdefault(key, {"samples": 0, "hits": 0, "brier_sum": 0.0})
        bucket["samples"] = int(bucket.get("samples", 0)) + 1
        bucket["hits"] = int(bucket.get("hits", 0)) + correct
        bucket["brier_sum"] = safe_float(bucket.get("brier_sum"), 0.0) + brier
        bucket["accuracy"] = bucket["hits"] / bucket["samples"]
        bucket["brier"] = bucket["brier_sum"] / bucket["samples"]
        graded += 1
    state["forward_outlook_history"] = history[-900:]
    return graded


def refresh_forward_outlooks(state, df, market_info, confidence, consensus, now=None):
    """Refresh next-three outlooks and retain snapshots for honest grading."""
    if not market_info:
        state["next_market_outlooks"] = []
        return []
    now = time.time() if now is None else float(now)
    outlooks = build_next_market_outlooks(
        legacy.rows_for_forecast(df),
        state.get("forecast", {}),
        market_info.get("expires_at"),
        confidence,
        consensus,
        state.get("forward_outlook_stats", {}),
        state.get("horizon_models", {}),
    )
    state["next_market_outlooks"] = outlooks
    history = state.setdefault("forward_outlook_history", [])
    for outlook in outlooks:
        history.append({**outlook, "created_at": now, "resolved": False})
    state["forward_outlook_history"] = history[-900:]
    return outlooks


def load_previous_state():
    """Prefer a workflow-provided local copy of the private learning-state branch.

    The repository is private, so unauthenticated raw.githubusercontent.com reads
    can fail. GitHub Actions fetches the branch with its built-in token and writes
    it to LEARNING_STATE_INPUT before this learner starts. This preserves live
    samples across runs instead of silently resetting to a fresh state.
    """
    input_path = os.getenv("LEARNING_STATE_INPUT", "").strip()
    if input_path:
        try:
            payload = json.loads(Path(input_path).read_text())
            if isinstance(payload, dict) and "forecast" in payload:
                payload = legacy.migrate_event_name(payload)
                bundle_path = os.getenv("HORIZON_MODELS_INPUT", "").strip()
                if bundle_path and Path(bundle_path).is_file():
                    merge_offline_bundle(payload, json.loads(Path(bundle_path).read_text()))
                payload.setdefault("status", {})["loaded_from_private_branch"] = True
                return payload
        except Exception as exc:
            print(f"Could not load LEARNING_STATE_INPUT: {exc}")
    state = legacy.load()
    bundle_path = os.getenv("HORIZON_MODELS_INPUT", "").strip()
    if bundle_path and Path(bundle_path).is_file():
        try:
            merge_offline_bundle(state, json.loads(Path(bundle_path).read_text()))
        except Exception as exc:
            print(f"Could not load HORIZON_MODELS_INPUT: {exc}")
    state.setdefault("status", {})["loaded_from_private_branch"] = False
    return state


def _tag_latest_specialist_history_with_regime(state, pending):
    """Attach the market regime to the just-graded specialist records.

    Legacy grading stores per-bot correctness but historically omitted regime,
    preventing v5 from learning that a bot can be strong in one market regime
    and weak in another. Only the matching latest ticker is modified.
    """
    ticker = str((pending or {}).get("ticker") or "")
    regime = str((pending or {}).get("regime") or "UNKNOWN")
    if not ticker:
        return
    histories = state.get("specialist_history", {}) or {}
    for rows in histories.values():
        if not isinstance(rows, list) or not rows:
            continue
        row = rows[-1]
        if isinstance(row, dict) and str(row.get("ticker") or "") == ticker:
            row.setdefault("regime", regime)


def _historical_expiry_frame(expiry_ts):
    """Fetch the exact one-minute candle that CLOSED at a stale expiry."""
    expiry = int(float(expiry_ts))
    raw = legacy.get(
        legacy.SPOT + "/api/v3/klines",
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "startTime": (expiry - 60) * 1000,
            "endTime": expiry * 1000 - 1,
            "limit": 1,
        },
    )
    if not raw:
        return None
    cols = ["ot", "open", "high", "low", "close", "volume", "ct", "qv", "trades", "tb", "tq", "x"]
    frame = pd.DataFrame(raw, columns=cols)
    for key in ["open", "high", "low", "close", "volume"]:
        frame[key] = pd.to_numeric(frame[key], errors="coerce")
    frame["time"] = pd.to_datetime(frame["ot"], unit="ms", utc=True, errors="coerce")
    return frame.dropna(subset=["time", "close"])


def strict_grade(state, df):
    pending = copy.deepcopy(state.get("pending"))
    if not pending:
        return False
    if time.time() < safe_float(pending.get("expires_at"), float("inf")):
        return False

    grade_df = df
    row = exact_expiry_row(grade_df, pending.get("expires_at"), tolerance_seconds=75)
    if row is None:
        try:
            recovered = _historical_expiry_frame(pending.get("expires_at"))
        except Exception as exc:
            recovered = None
            state.setdefault("status", {})["last_grade_recovery_error"] = str(exc)
        if recovered is not None and not recovered.empty:
            grade_df = recovered
            row = exact_expiry_row(grade_df, pending.get("expires_at"), tolerance_seconds=75)
    if row is None:
        state.setdefault("status", {})["last_grade_skipped_reason"] = "Exact closed expiry candle unavailable"
        return False

    graded = v3.enhanced_grade(state, grade_df)
    if not graded:
        return False

    _tag_latest_specialist_history_with_regime(state, pending)

    if state.get("master_history"):
        last = state["master_history"][-1]
        last["would_wait"] = bool(pending.get("would_wait", False))
        last["master_base_score"] = safe_float(pending.get("master_base_score"), 0.0)
        last["snapshot_available"] = bool(pending.get("snapshot"))
    state.setdefault("status", {}).pop("last_grade_skipped_reason", None)
    state.setdefault("status", {}).pop("last_grade_recovery_error", None)
    return True


def update_wait_counterfactual(state):
    hist = state.get("master_history", [])
    metrics = state.setdefault("wait_counterfactual", {"samples": 0, "profitable_waits": 0, "avoided_losses": 0})
    rows = [r for r in hist if r.get("would_wait") is not None and not r.get("wait_cf_counted")]
    for row in rows:
        move = abs(safe_float(row.get("realized_return"), 0.0))
        waited = bool(row.get("would_wait"))
        hit = int(safe_float(row.get("direction_correct"), 0.0))
        if waited:
            metrics["samples"] += 1
            if hit and move >= 0.0015:
                metrics["profitable_waits"] += 1
            if (not hit) and move >= 0.0010:
                metrics["avoided_losses"] += 1
        row["wait_cf_counted"] = True


def evaluate_cfg(df, cfg):
    if df is None or len(df) < 120:
        return {"samples": 0, "accuracy": None, "median_error": None}
    outcomes = []
    start = max(60, len(df) - 420)
    for end in range(start, len(df) - 15, 15):
        train = df.iloc[: end + 1]
        rows = legacy.rows_for_forecast(train)
        forecast = forecast_path_core(rows, None, cfg)
        if not forecast:
            continue
        px = safe_float(train.close.iloc[-1])
        actual = safe_float(df.close.iloc[end + 15], px)
        pred = safe_float(forecast.get("predicted_end"), px)
        outcomes.append((int((pred >= px) == (actual >= px)), abs(actual - pred)))
    if not outcomes:
        return {"samples": 0, "accuracy": None, "median_error": None}
    return {
        "samples": len(outcomes),
        "accuracy": float(np.mean([x[0] for x in outcomes])),
        "median_error": float(np.median([x[1] for x in outcomes])),
    }


def challenger_qualifies(champ, challenger):
    if champ.get("samples", 0) < PROMOTION_MIN_SAMPLES or challenger.get("samples", 0) < PROMOTION_MIN_SAMPLES:
        return False
    champ_acc = champ.get("accuracy")
    challenger_acc = challenger.get("accuracy")
    champ_err = champ.get("median_error")
    challenger_err = challenger.get("median_error")
    if None in (champ_acc, challenger_acc, champ_err, challenger_err):
        return False
    return bool(
        challenger_acc >= champ_acc + PROMOTION_ACCURACY_MARGIN
        and challenger_err <= champ_err * PROMOTION_MAX_ERROR_MULTIPLIER
    )


def champion_challenger(state, df):
    forecast = state.get("forecast", {})
    previous = state.get("champion_challenger", {}) if isinstance(state.get("champion_challenger"), dict) else {}
    champion_cfg = {k: safe_float(forecast.get(k), d) for k, d in {
        "w_ret3": 0.46, "w_ret8": 0.34, "w_ret15": 0.20,
        "momentum_scale": 2.2, "target_influence": 0.18, "bias": 0.0,
    }.items()}
    challengers = []
    for scale_mul, short_shift in ((0.90, -0.03), (1.0, 0.03), (1.10, 0.00)):
        cfg = dict(champion_cfg)
        cfg["momentum_scale"] = float(np.clip(cfg["momentum_scale"] * scale_mul, 0.6, 4.5))
        cfg["w_ret3"] = float(np.clip(cfg["w_ret3"] + short_shift, 0.05, 0.90))
        cfg["w_ret15"] = float(np.clip(cfg["w_ret15"] - short_shift, 0.05, 0.90))
        total = cfg["w_ret3"] + cfg["w_ret8"] + cfg["w_ret15"]
        for key in ("w_ret3", "w_ret8", "w_ret15"):
            cfg[key] /= total
        challengers.append(cfg)

    champ = evaluate_cfg(df, champion_cfg)
    scored = [(evaluate_cfg(df, cfg), cfg) for cfg in challengers]
    best_metrics, best_cfg = max(
        scored,
        key=lambda x: ((x[0]["accuracy"] or 0.0), -(x[0]["median_error"] or 1e18)),
    )

    qualifies = challenger_qualifies(champ, best_metrics)
    streak = int(previous.get("qualification_streak", 0)) + 1 if qualifies else 0
    promoted = False
    if qualifies and streak >= PROMOTION_REQUIRED_STREAK:
        for key, value in best_cfg.items():
            forecast[key] = value
        promoted = True
        streak = 0

    state["champion_challenger"] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "champion": champ,
        "best_challenger": best_metrics,
        "qualification_streak": streak,
        "promoted": promoted,
        "minimum_samples": PROMOTION_MIN_SAMPLES,
        "required_streak": PROMOTION_REQUIRED_STREAK,
        "minimum_margin": PROMOTION_ACCURACY_MARGIN,
        "max_error_multiplier": PROMOTION_MAX_ERROR_MULTIPLIER,
    }


def register_with_snapshot(state, df, market_info):
    registered = v3.enhanced_register(state, df, market_info)
    if registered and state.get("pending"):
        p = state["pending"]
        p["data_quality"] = {
            "spot_history_rows": int(len(df)),
            "exact_expiry_required": True,
        }
        p["snapshot"] = {
            "start_price": safe_float(p.get("start_price")),
            "target": safe_float(p.get("target"), None),
            "regime": p.get("regime", "UNKNOWN"),
            "master_confidence": safe_float(p.get("master_confidence"), 0.5),
            "master_base_score": safe_float(p.get("master_base_score"), 0.0),
            "would_wait": bool(p.get("would_wait", False)),
            "specialists": p.get("specialists", {}),
        }
        state.setdefault("prediction_snapshots", []).append({
            "ticker": p.get("ticker"),
            "opened_at": p.get("opened_at"),
            "expires_at": p.get("expires_at"),
            "snapshot": p["snapshot"],
        })
        state["prediction_snapshots"] = state["prediction_snapshots"][-500:]
    return registered


def current_shadow_call(state, df, market_info):
    """Recompute a paper-only call for the current phase without touching pending."""
    if not market_info:
        return None
    price = float(df.close.iloc[-1])
    specialists = legacy.run_specialists_core(
        df,
        legacy.aggregate_trades(),
        legacy.futures_snapshot(),
        legacy.kalshi_context(market_info, price),
    )
    forecast = forecast_path_core(
        legacy.rows_for_forecast(df), market_info.get("target"),
        state.get("forecast"), state.get("horizon_models"),
    )
    if not forecast:
        return None
    call = {
        "ticker": market_info.get("ticker"),
        "opened_at": time.time(),
        "expires_at": market_info.get("expires_at"),
        "predicted_direction": forecast.get("predicted_direction"),
        "specialists": specialists,
    }
    confidence, base_score = v3.weighted_master_confidence(call, state)
    call["master_confidence"] = confidence
    call["master_base_score"] = base_score
    direction = "UP" if base_score > 0 else "DOWN"
    consensus = specialist_consensus(specialists, direction)
    source_health = source_health_from_specialists(specialists)
    seconds_remaining = safe_float(market_info.get("expires_at"), 0.0) - time.time()
    predicted_end = safe_float(forecast.get("predicted_end"))
    target = safe_float(market_info.get("target"))
    price_floor = price * 0.00035
    target_confirmed = bool(
        predicted_end is not None
        and target is not None
        and ((predicted_end - target) * base_score) > 0
        and abs(predicted_end - target) >= price_floor
    )
    policy = learned_policy(state, detect_regime(df))
    focus = evaluate_lock_focus(
        base_score=base_score,
        confidence=confidence,
        consensus=consensus,
        source_health=source_health,
        seconds_remaining=seconds_remaining,
        market=market_info,
        target_confirmed=target_confirmed,
        edge_floor=policy["edge_floor"],
    )
    call["master_action"] = focus["action"]
    call["would_wait"] = not focus["eligible"]
    call["lock_focus"] = focus
    return call


def refresh_pending_lock_focus(state, live_call, market_info):
    """Refresh WAIT into a qualified LOCK without altering grading geometry."""
    pending = state.get("pending")
    if not isinstance(pending, dict) or not isinstance(live_call, dict):
        return False
    if str(pending.get("ticker") or "") != str((market_info or {}).get("ticker") or ""):
        return False
    old_action = str(pending.get("master_action") or "WAIT").upper()
    if old_action.startswith("LOCK"):
        return False
    for key in (
        "specialists", "master_confidence", "master_base_score",
        "master_action", "would_wait", "lock_focus",
    ):
        pending[key] = live_call.get(key)
    if str(pending.get("master_action") or "").startswith("LOCK"):
        pending["lock_called_at"] = time.time()
        pending["lock_called_seconds_remaining"] = (
            (live_call.get("lock_focus") or {}).get("seconds_remaining")
        )
    return True


def main():
    state = ensure_v31(load_previous_state())
    before_samples = int(state.get("forecast", {}).get("samples", 0))
    df = legacy.history()
    market_info = legacy.market()
    timeframe_context = legacy.market_timeframe_context()
    horizon_root = ensure_horizon_state(state)
    horizon_root["latest_context"] = timeframe_context
    horizon_graded = resolve_horizon_predictions(state, df)
    graded = strict_grade(state, df)
    forward_outlooks_graded = grade_forward_outlooks(state, df)
    research_resolved = resolve_shadows(state, legacy.official_result)
    official_resolved = legacy.resolve_official_results(state)
    registered = register_with_snapshot(state, df, market_info)
    live_call = current_shadow_call(state, df, market_info)
    forecast_rows = legacy.rows_for_forecast(df)
    legacy_forecast = forecast_path_core(
        forecast_rows, (market_info or {}).get("target"), state.get("forecast")
    )
    horizon_registered = register_horizon_predictions(
        state,
        forecast_rows,
        market_info=market_info,
        baseline=baseline_probabilities(forecast_rows, legacy_forecast),
    )
    _live_confidence = safe_float((live_call or {}).get("master_confidence"), 0.5)
    _live_focus = (live_call or {}).get("lock_focus") or {}
    forward_outlooks = refresh_forward_outlooks(
        state,
        df,
        market_info,
        _live_confidence,
        safe_float(_live_focus.get("consensus"), 0.0),
    )
    refreshed_lock_focus = refresh_pending_lock_focus(state, live_call, market_info)
    pending_action = str((state.get("pending") or {}).get("master_action") or "").upper()
    if live_call and pending_action.startswith("LOCK"):
        live_call["master_action"] = pending_action
        live_call["would_wait"] = False
    # Research phases use the current observation time, while execution keeps
    # the original pending forecast geometry for strict expiry grading.
    shadow_call = live_call or state.get("pending")
    research_registered = register_shadow(state, shadow_call, market_info)
    v3.update_rolling(state)
    state["validation"] = v3.walk_forward_validate(df, state)
    champion_challenger(state, df)
    update_wait_counterfactual(state)
    update_lifecycles(state)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    current_regime = detect_regime(df)
    state["status"].update({
        "worker_ok": True,
        "shared_core": True,
        "learning_version": 31,
        "strict_expiry_grading": True,
        "graded_this_run": graded,
        "official_results_resolved": official_resolved,
        "registered_this_run": registered,
        "research_lab_ok": True,
        "research_resolved_this_run": research_resolved,
        "research_registered_this_run": research_registered,
        "lock_focus_refreshed_this_run": refreshed_lock_focus,
        "continuous_lock_evaluation": True,
        "forward_outlooks_generated": len(forward_outlooks),
        "forward_outlooks_graded_this_run": forward_outlooks_graded,
        "btc_execution_mode": "LOCK_FIRST",
        "auto_scalping_enabled": AUTO_SCALPING_ENABLED,
        "champion_promoted": state.get("champion_challenger", {}).get("promoted", False),
        "challenger_streak": state.get("champion_challenger", {}).get("qualification_streak", 0),
        "horizon_models_paper_only": state.get("horizon_models", {}).get("paper_only") is True,
        "horizon_models_affect_execution": state.get("horizon_models", {}).get("affects_execution", False),
        "horizon_predictions_graded_this_run": horizon_graded,
        "horizon_predictions_registered_this_run": horizon_registered,
        "higher_timeframes_requested": 7,
        "higher_timeframes_available": int(timeframe_context.get("available_timeframes", 0)),
        "higher_timeframes_all_closed": bool(timeframe_context.get("all_closed", False)),
        "samples_before_run": before_samples,
        "samples_after_run": int(state.get("forecast", {}).get("samples", 0)),
        "current_regime": current_regime,
        "regime_tagged_specialist_history": True,
    })
    legacy.OUT.parent.mkdir(parents=True, exist_ok=True)
    legacy.OUT.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps(state["status"], indent=2))


if __name__ == "__main__":
    main()
