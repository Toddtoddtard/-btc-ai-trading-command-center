#!/usr/bin/env python3
"""Train horizon-specific BTC models with chronological train/calibrate/test splits."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from historical_backtest import fetch_month, month_iter
from horizon_models import FEATURE_NAMES, HORIZONS

OUT = Path(os.getenv("HORIZON_MODELS_OUTPUT", "/tmp/horizon_models.json"))
YEARS = max(1, int(os.getenv("HISTORICAL_YEARS", "10")))
STEP = max(1, int(os.getenv("TRAINING_STEP_MINUTES", "5")))


def _sigmoid(values):
    return 1.0 / (1.0 + np.exp(-np.clip(values, -20.0, 20.0)))


def feature_frame(df):
    """Vectorized equivalent of the live, past-only feature calculation."""
    x = df.copy()
    close = x["close"].astype(float)
    logret = np.log(close.clip(lower=1e-12)).diff()
    out = pd.DataFrame(index=x.index)
    for lag, scale in ((1, .0015), (3, .003), (5, .004), (15, .008), (30, .012), (60, .020)):
        out[f"ret{lag}"] = np.tanh(close.pct_change(lag) / scale)
    mean5, mean20 = close.rolling(5).mean(), close.rolling(20).mean()
    out["trend_5_20"] = np.tanh((mean5 / mean20 - 1.0) / .003)
    out["vol_ratio_5_30"] = np.tanh(logret.rolling(5).std(ddof=0) / logret.rolling(30).std(ddof=0).clip(lower=1e-8) - 1.0)
    candle_range = (x["high"] - x["low"]).clip(lower=close * 1e-6)
    out["body"] = (close - x["open"]) / candle_range
    high20, low20 = x["high"].rolling(20).max(), x["low"].rolling(20).min()
    span20 = (high20 - low20).clip(lower=close * 1e-6)
    out["range_position_20"] = ((close - low20) / span20) * 2.0 - 1.0
    out["zscore_20"] = (close - mean20) / (2.0 * close.rolling(20).std(ddof=0).clip(lower=close * 1e-6))
    volume = x.get("volume", pd.Series(0.0, index=x.index)).astype(float)
    out["volume_z"] = ((volume - volume.rolling(20).mean()) / volume.rolling(20).std().replace(0, np.nan)) / 3.0
    stamp = pd.to_datetime(x["time"], utc=True)
    angle = 2.0 * math.pi * (stamp.dt.hour * 60 + stamp.dt.minute) / 1440.0
    out["tod_sin"], out["tod_cos"] = np.sin(angle), np.cos(angle)
    return out.loc[:, FEATURE_NAMES].clip(-5.0, 5.0).replace([np.inf, -np.inf], np.nan)


def month_samples(df, horizon):
    features = feature_frame(df)
    close = df["close"].astype(float)
    target = (close.shift(-horizon) >= close).astype(float)
    baseline = _sigmoid(np.tanh(close.pct_change(15) / .008).fillna(0.0).to_numpy())
    valid = features.notna().all(axis=1) & close.shift(-horizon).notna()
    idx = np.flatnonzero(valid.to_numpy())[::STEP]
    return features.iloc[idx].to_numpy(float), target.iloc[idx].to_numpy(float), baseline[idx]


def fit_batch(weights, bias, x, y, learning_rate=.08, epochs=4):
    if not len(x):
        return weights, bias
    for _ in range(epochs):
        probability = _sigmoid(x @ weights + bias)
        error = probability - y
        weights -= learning_rate * ((x.T @ error) / len(x) + .0005 * weights)
        bias -= learning_rate * float(error.mean())
    return np.clip(weights, -3.0, 3.0), float(np.clip(bias, -2.0, 2.0))


def calibration_grid(logits, labels):
    best = (float("inf"), 1.0, 0.0)
    for temperature in np.linspace(.6, 2.2, 17):
        for bias in np.linspace(-.5, .5, 21):
            probability = _sigmoid(logits / temperature + bias)
            brier = float(np.mean((probability - labels) ** 2))
            if brier < best[0]:
                best = (brier, float(temperature), float(bias))
    return best[1], best[2]


def metrics(probability, labels, baseline):
    return {
        "samples": int(len(labels)),
        "accuracy": float(np.mean((probability >= .5) == labels)),
        "brier": float(np.mean((probability - labels) ** 2)),
        "baseline_accuracy": float(np.mean((baseline >= .5) == labels)),
        "baseline_brier": float(np.mean((baseline - labels) ** 2)),
    }


def requested_months(now=None):
    now = now or datetime.now(timezone.utc)
    end_y, end_m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    start_y, start_m = end_y - YEARS, end_m + 1
    if start_m == 13:
        start_y, start_m = start_y + 1, 1
    return list(month_iter(start_y, start_m, end_y, end_m))


def main():
    months = requested_months()
    train_end = max(1, int(len(months) * .70))
    calibration_end = max(train_end + 1, int(len(months) * .85))
    states = {h: {"weights": np.zeros(len(FEATURE_NAMES)), "bias": 0.0, "cal": [], "test": []} for h in HORIZONS}
    loaded, failed = [], []
    for index, (year, month) in enumerate(months):
        try:
            frame = fetch_month(year, month)
            loaded.append(f"{year}-{month:02d}")
        except Exception as exc:
            failed.append({"month": f"{year}-{month:02d}", "error": str(exc)[:160]})
            continue
        for horizon in HORIZONS:
            x, y, baseline = month_samples(frame, horizon)
            state = states[horizon]
            if index < train_end:
                state["weights"], state["bias"] = fit_batch(state["weights"], state["bias"], x, y)
            else:
                bucket = "cal" if index < calibration_end else "test"
                state[bucket].append((x, y, baseline))

    models = {}
    trained_through = loaded[-1] if loaded else None
    for horizon, state in states.items():
        cal_x = np.concatenate([r[0] for r in state["cal"]])
        cal_y = np.concatenate([r[1] for r in state["cal"]])
        test_x = np.concatenate([r[0] for r in state["test"]])
        test_y = np.concatenate([r[1] for r in state["test"]])
        test_baseline = np.concatenate([r[2] for r in state["test"]])
        temperature, calibration_bias = calibration_grid(cal_x @ state["weights"] + state["bias"], cal_y)
        probability = _sigmoid((test_x @ state["weights"] + state["bias"]) / temperature + calibration_bias)
        validation = metrics(probability, test_y, test_baseline)
        validation["brier_edge"] = validation["baseline_brier"] - validation["brier"]
        eligible = validation["samples"] >= 10000 and validation["brier_edge"] >= .002 and validation["accuracy"] >= validation["baseline_accuracy"]
        models[str(horizon)] = {
            "weights": state["weights"].tolist(), "bias": state["bias"],
            "temperature": temperature, "calibration_bias": calibration_bias,
            "validation": validation, "promotion_eligible": bool(eligible),
            "trained_through": trained_through,
        }
    report = {
        "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Binance Vision BTCUSDT 1m monthly archives",
        "temporal_split": {"train": .70, "calibration": .15, "untouched_test": .15},
        "years_requested": YEARS, "months_loaded": loaded, "months_failed": failed,
        "models": models,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({h: row["validation"] for h, row in models.items()}, indent=2))
    if len(loaded) < min(12, len(months)):
        raise RuntimeError("Too few Binance archive months loaded")


if __name__ == "__main__":
    main()
