#!/usr/bin/env python3
"""Five-year 1-minute BTC walk-forward backtest for the 15-minute forecast core.

This is deliberately evaluation-only: it does not promote production parameters.
It downloads Binance's free monthly BTCUSDT 1m archives, evaluates only with
past candles, and writes a compact JSON report for the private learning branch.
"""
import io
import json
import os
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ai_core import forecast_path_core

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
YEARS = 5
OUT = Path(os.getenv("HISTORICAL_BACKTEST_OUTPUT", "/tmp/historical_backtest.json"))
BASE = "https://data.binance.vision/data/spot/monthly/klines"

DEFAULT_CFG = {
    "w_ret3": 0.46,
    "w_ret8": 0.34,
    "w_ret15": 0.20,
    "momentum_scale": 2.2,
    "target_influence": 0.18,
    "bias": 0.0,
}


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
    url = month_url(year, month)
    req = Request(url, headers={"User-Agent": "BTC-AI-Historical-Backtest/1.0"})
    with urlopen(req, timeout=45) as response:
        raw = response.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        data = zf.read(name)
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "trades", "tb", "tq", "ignore"]
    df = pd.read_csv(io.BytesIO(data), header=None, names=cols)
    # Binance archive timestamps can be milliseconds or microseconds depending on era.
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    unit = "us" if float(ot.dropna().median()) > 1e14 else "ms"
    df["time"] = pd.to_datetime(ot, unit=unit, utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["time", "open", "high", "low", "close"])


def rows_for_forecast(buffer):
    return list(buffer)[-60:]


def main():
    now = datetime.now(timezone.utc)
    end_year, end_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    start_year = end_year - YEARS
    start_month = end_month + 1
    if start_month == 13:
        start_year += 1
        start_month = 1

    buffer = deque(maxlen=80)
    pending = deque()  # (target_timestamp_ns, start_price, predicted_end)
    total = hits = 0
    abs_errors = []
    returns = []
    yearly = {}
    months_loaded = []
    months_failed = []
    last_eval_minute = None
    started = time.time()

    for year, month in month_iter(start_year, start_month, end_year, end_month):
        try:
            df = fetch_month(year, month)
            months_loaded.append(f"{year}-{month:02d}")
        except Exception as exc:
            months_failed.append({"month": f"{year}-{month:02d}", "error": str(exc)[:180]})
            continue

        for r in df.itertuples(index=False):
            ts = pd.Timestamp(r.time)
            px = float(r.close)

            while pending and pending[0][0] <= ts.value:
                target_ns, start_px, pred_end, eval_year = pending.popleft()
                actual = px
                correct = int((pred_end >= start_px) == (actual >= start_px))
                err = abs(actual - pred_end)
                ret = actual / start_px - 1.0
                total += 1
                hits += correct
                abs_errors.append(err)
                returns.append(ret)
                bucket = yearly.setdefault(str(eval_year), {"samples": 0, "hits": 0, "abs_errors": []})
                bucket["samples"] += 1
                bucket["hits"] += correct
                bucket["abs_errors"].append(err)

            buffer.append({"open": float(r.open), "high": float(r.high), "low": float(r.low), "close": px})
            if len(buffer) < 60:
                continue

            # Evaluate one fresh 15-minute forecast at each quarter-hour.
            minute_key = int(ts.timestamp() // 60)
            if minute_key % 15 != 0 or minute_key == last_eval_minute:
                continue
            last_eval_minute = minute_key
            forecast = forecast_path_core(rows_for_forecast(buffer), None, DEFAULT_CFG)
            if not forecast:
                continue
            pred_end = float(forecast.get("predicted_end", px))
            pending.append((ts.value + 15 * 60 * 1_000_000_000, px, pred_end, ts.year))

    yearly_out = {}
    for year, b in sorted(yearly.items()):
        errs = b.pop("abs_errors")
        yearly_out[year] = {
            "samples": b["samples"],
            "direction_hits": b["hits"],
            "direction_accuracy": b["hits"] / b["samples"] if b["samples"] else None,
            "median_abs_error": float(np.median(errs)) if errs else None,
            "mean_abs_error": float(np.mean(errs)) if errs else None,
        }

    report = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "source": "Binance Vision monthly 1m archives",
        "period_requested_years": YEARS,
        "evaluation_horizon_minutes": 15,
        "walk_forward": True,
        "production_parameters_changed": False,
        "config": DEFAULT_CFG,
        "months_loaded": months_loaded,
        "months_failed": months_failed,
        "overall": {
            "samples": total,
            "direction_hits": hits,
            "direction_accuracy": hits / total if total else None,
            "median_abs_error": float(np.median(abs_errors)) if abs_errors else None,
            "mean_abs_error": float(np.mean(abs_errors)) if abs_errors else None,
            "median_realized_abs_return": float(np.median(np.abs(returns))) if returns else None,
        },
        "yearly": yearly_out,
        "runtime_seconds": time.time() - started,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report["overall"], indent=2))
    if total < 10000:
        raise RuntimeError(f"Historical backtest produced too few samples: {total}")


if __name__ == "__main__":
    main()
