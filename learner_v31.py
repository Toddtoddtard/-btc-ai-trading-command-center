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
from reliability_v31 import detect_regime, exact_expiry_row, safe_float

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
    state["status"].setdefault("learning_version", 31)
    return state


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
                payload.setdefault("status", {})["loaded_from_private_branch"] = True
                return payload
        except Exception as exc:
            print(f"Could not load LEARNING_STATE_INPUT: {exc}")
    state = legacy.load()
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


def main():
    state = ensure_v31(load_previous_state())
    before_samples = int(state.get("forecast", {}).get("samples", 0))
    df = legacy.history()
    market_info = legacy.market()
    graded = strict_grade(state, df)
    official_resolved = legacy.resolve_official_results(state)
    registered = register_with_snapshot(state, df, market_info)
    v3.update_rolling(state)
    state["validation"] = v3.walk_forward_validate(df, state)
    champion_challenger(state, df)
    update_wait_counterfactual(state)
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
        "champion_promoted": state.get("champion_challenger", {}).get("promoted", False),
        "challenger_streak": state.get("champion_challenger", {}).get("qualification_streak", 0),
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
