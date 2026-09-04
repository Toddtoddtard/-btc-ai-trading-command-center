#!/usr/bin/env python3
import copy
import json
import math
from datetime import datetime, timezone

import numpy as np

import learner as legacy
import learner_v3 as v3
from ai_core import forecast_path_core
from reliability_v31 import exact_expiry_row, safe_float, snapshot_payload


def ensure_v31(state):
    state = v3.ensure_v3(state)
    state["version"] = 31
    state.setdefault("champion_challenger", {})
    state.setdefault("data_quality", {})
    state.setdefault("wait_counterfactual", {"samples": 0, "profitable_waits": 0, "avoided_losses": 0})
    state.setdefault("prediction_snapshots", [])
    state["status"].setdefault("learning_version", 31)
    return state


def strict_grade(state, df):
    pending = copy.deepcopy(state.get("pending"))
    if not pending:
        return False
    if legacy.time.time() < safe_float(pending.get("expires_at"), float("inf")):
        return False
    row = exact_expiry_row(df, pending.get("expires_at"), tolerance_seconds=75)
    if row is None:
        state.setdefault("status", {})["last_grade_skipped_reason"] = "No candle within 75s of exact expiry"
        return False
    return v3.enhanced_grade(state, df)


def update_wait_counterfactual(state):
    hist = state.get("master_history", [])
    pending_history = state.setdefault("wait_counterfactual", {"samples": 0, "profitable_waits": 0, "avoided_losses": 0})
    rows = [r for r in hist if r.get("would_wait") is not None and not r.get("wait_cf_counted")]
    for row in rows:
        move = abs(safe_float(row.get("realized_return"), 0.0))
        waited = bool(row.get("would_wait"))
        hit = int(safe_float(row.get("direction_correct"), 0.0))
        if waited:
            pending_history["samples"] += 1
            if hit and move >= 0.0015:
                pending_history["profitable_waits"] += 1
            if (not hit) and move >= 0.0010:
                pending_history["avoided_losses"] += 1
        row["wait_cf_counted"] = True


def evaluate_cfg(df, cfg):
    if df is None or len(df) < 120:
        return {"samples": 0, "accuracy": None, "median_error": None}
    outcomes = []
    start = max(60, len(df) - 240)
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


def champion_challenger(state, df):
    forecast = state.get("forecast", {})
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
        for k in ("w_ret3", "w_ret8", "w_ret15"):
            cfg[k] /= total
        challengers.append(cfg)

    champ = evaluate_cfg(df, champion_cfg)
    scored = [(evaluate_cfg(df, cfg), cfg) for cfg in challengers]
    best_metrics, best_cfg = max(scored, key=lambda x: ((x[0]["accuracy"] or 0.0), -(x[0]["median_error"] or 1e18)))
    promoted = False
    if champ["samples"] >= 8 and best_metrics["samples"] >= 8:
        champ_acc = champ["accuracy"] or 0.0
        best_acc = best_metrics["accuracy"] or 0.0
        champ_err = champ["median_error"] or 1e18
        best_err = best_metrics["median_error"] or 1e18
        if best_acc >= champ_acc + 0.05 and best_err <= champ_err * 1.10:
            for key, value in best_cfg.items():
                forecast[key] = value
            promoted = True
    state["champion_challenger"] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "champion": champ,
        "best_challenger": best_metrics,
        "promoted": promoted,
        "minimum_margin": 0.05,
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
    state = ensure_v31(legacy.load())
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
    state["status"].update({
        "worker_ok": True,
        "shared_core": True,
        "learning_version": 31,
        "strict_expiry_grading": True,
        "graded_this_run": graded,
        "official_results_resolved": official_resolved,
        "registered_this_run": registered,
        "champion_promoted": state.get("champion_challenger", {}).get("promoted", False),
    })
    legacy.OUT.parent.mkdir(parents=True, exist_ok=True)
    legacy.OUT.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps(state["status"], indent=2))


if __name__ == "__main__":
    main()
