#!/usr/bin/env python3
"""Five-year walk-forward historical priors for OHLCV-based BTC specialists.

v16 correctness fix: carry rows from the previous month are used only to warm
indicators. They are never re-evaluated, never create duplicate pending windows,
and stale pending windows are discarded rather than being graded against a
far-future price after a data gap.
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core
from reliability_v31 import detect_regime

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
YEARS = 5
BASE = "https://data.binance.vision/data/spot/monthly/klines"
OUT = Path(os.getenv("HISTORICAL_SPECIALIST_OUTPUT", "/tmp/historical_specialist_knowledge_v7.json"))
ELIGIBLE = {
    "Trend AI", "Momentum AI", "Volume AI", "Pattern AI",
    "Support/Resistance AI", "Volatility AI", "Market Regime AI",
    "Historical Pattern AI",
}
HORIZON_NS = 15 * 60 * 1_000_000_000
MAX_RESOLUTION_LATENESS_NS = 90 * 1_000_000_000


def month_iter(start_year, start_month, end_year, end_month):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m == 13:
            y += 1
            m = 1


def month_url(year, month):
    stem = f"{SYMBOL}-{INTERVAL}-{year}-{month:02d}.zip"
    return f"{BASE}/{SYMBOL}/{INTERVAL}/{stem}"


def fetch_month(year, month):
    req = Request(month_url(year, month), headers={"User-Agent": "BTC-AI-Specialist-History-v16/1.0"})
    with urlopen(req, timeout=45) as response:
        raw = response.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        data = zf.read(zf.namelist()[0])
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "trades", "tb", "tq", "ignore"]
    df = pd.read_csv(io.BytesIO(data), header=None, names=cols)
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    unit = "us" if float(ot.dropna().median()) > 1e14 else "ms"
    df["time"] = pd.to_datetime(ot, unit=unit, utc=True, errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return (
        df.dropna(subset=["time", "open", "high", "low", "close", "volume"])
        [["time", "open", "high", "low", "close", "volume"]]
        .drop_duplicates("time")
        .sort_values("time")
        .reset_index(drop=True)
    )


def blank_stat():
    return {"samples": 0, "hits": 0, "calls": 0, "abs_score_sum": 0.0}


def add_stat(bucket, score, actual_dir):
    pred = 1 if score > 0.03 else -1 if score < -0.03 else 0
    bucket["samples"] += 1
    bucket["abs_score_sum"] += abs(float(score))
    if pred:
        bucket["calls"] += 1
        bucket["hits"] += int(pred == actual_dir)


def summarize(bucket):
    n = int(bucket["samples"])
    calls = int(bucket["calls"])
    return {
        "samples": n,
        "directional_calls": calls,
        "direction_hits": int(bucket["hits"]),
        "accuracy": (bucket["hits"] / calls) if calls else None,
        "coverage": (calls / n) if n else None,
        "avg_abs_score": (bucket["abs_score_sum"] / n) if n else None,
    }


def first_fresh_index(enriched, fresh_start):
    """Return the first row belonging to the newly fetched month."""
    times = pd.to_datetime(enriched["time"], utc=True)
    idx = np.flatnonzero((times >= fresh_start).to_numpy())
    return int(idx[0]) if len(idx) else len(enriched)


def main():
    now = datetime.now(timezone.utc)
    end_year, end_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    start_year = end_year - YEARS
    start_month = end_month + 1
    if start_month == 13:
        start_year += 1
        start_month = 1

    history = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    pending = deque()  # expiry_ns, start_px, regime, specialist_scores
    global_stats = defaultdict(blank_stat)
    regime_stats = defaultdict(lambda: defaultdict(blank_stat))
    months_loaded, months_failed = [], []
    total_windows = 0
    stale_windows = 0
    started = time.time()

    for year, month in month_iter(start_year, start_month, end_year, end_month):
        try:
            fresh = fetch_month(year, month)
            months_loaded.append(f"{year}-{month:02d}")
        except Exception as exc:
            months_failed.append({"month": f"{year}-{month:02d}", "error": str(exc)[:180]})
            continue
        if fresh.empty:
            continue

        fresh_start = pd.Timestamp(fresh["time"].iloc[0])
        combined = fresh
        if not history.empty:
            combined = pd.concat([history.tail(180), fresh], ignore_index=True)
            combined = combined.drop_duplicates("time").sort_values("time").reset_index(drop=True)

        enriched = enrich_history_core(combined.copy())
        start_i = first_fresh_index(enriched, fresh_start)

        # Critical: only iterate fresh rows. Carry rows exist solely for indicator
        # warm-up and must never recreate old predictions or reorder `pending`.
        for i in range(start_i, len(enriched)):
            row = enriched.iloc[i]
            ts = pd.Timestamp(row["time"])
            px = float(row["close"])

            while pending and pending[0][0] <= ts.value:
                expiry_ns, start_px, regime, calls = pending.popleft()
                lateness = ts.value - expiry_ns
                if lateness > MAX_RESOLUTION_LATENESS_NS:
                    stale_windows += 1
                    continue
                actual_dir = 1 if px >= start_px else -1
                for name, score in calls.items():
                    add_stat(global_stats[name], score, actual_dir)
                    add_stat(regime_stats[name][regime], score, actual_dir)
                total_windows += 1

            minute_key = int(ts.timestamp() // 60)
            if minute_key % 15 != 0:
                continue
            hist_slice = enriched.iloc[: i + 1].tail(180).copy()
            if len(hist_slice) < 80 or hist_slice[["ema50", "rsi", "atr14"]].tail(1).isna().any(axis=None):
                continue
            results = run_specialists_core(hist_slice, pd.DataFrame(), {}, {"available": False})
            calls = {name: float(item.get("score", 0.0)) for name, item in results.items() if name in ELIGIBLE}
            regime = detect_regime(hist_slice)
            pending.append((ts.value + HORIZON_NS, px, regime, calls))

        history = combined.tail(240).copy()

    specialists = {}
    for name in sorted(ELIGIBLE):
        specialists[name] = summarize(global_stats[name])
        specialists[name]["regimes"] = {r: summarize(b) for r, b in sorted(regime_stats[name].items())}

    report = {
        "version": 8,
        "methodology": "fresh-row-only cross-month walk-forward",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Binance Vision monthly BTCUSDT 1m archives",
        "period_requested_years": YEARS,
        "evaluation_horizon_minutes": 15,
        "walk_forward": True,
        "production_parameters_changed": False,
        "eligible_specialists": sorted(ELIGIBLE),
        "excluded_specialists": ["Whale AI", "Liquidity AI", "Derivatives AI", "Kalshi Context AI", "Political Event Watch AI", "Combination AI"],
        "months_loaded": months_loaded,
        "months_failed": months_failed,
        "evaluated_windows": total_windows,
        "stale_windows_discarded": stale_windows,
        "specialists": specialists,
        "runtime_seconds": time.time() - started,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({"evaluated_windows": total_windows, "months_loaded": len(months_loaded), "stale_discarded": stale_windows}, indent=2))
    if total_windows < 10000:
        raise RuntimeError(f"Specialist historical backtest produced too few windows: {total_windows}")


if __name__ == "__main__":
    main()
