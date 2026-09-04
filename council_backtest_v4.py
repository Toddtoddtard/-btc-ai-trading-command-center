#!/usr/bin/env python3
"""Five-year walk-forward replay for the BTC AI Council v4.

Uses Binance Vision 1-minute archives. Candle/volume specialists are replayed
from information available at each timestamp. Whale flow is approximated from
Binance taker-buy quote volume versus total quote volume. Historical futures
book/funding/open-interest and Kalshi contracts are not available in the spot
archive, so those specialists remain neutral and are explicitly reported as
non-replayable rather than fabricated.
"""
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
from council_v4 import EXCLUDED_FROM_COUNCIL, council_vote

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
YEARS = 5
BASE = "https://data.binance.vision/data/spot/monthly/klines"
OUT = Path(os.getenv("COUNCIL_BACKTEST_OUTPUT", "/tmp/council_backtest_v4.json"))
REPLAYABLE = [
    "Trend AI", "Momentum AI", "Volume AI", "Pattern AI",
    "Support/Resistance AI", "Volatility AI", "Market Regime AI",
    "Whale AI", "Historical Pattern AI",
]
NON_REPLAYABLE = ["Liquidity AI", "Derivatives AI", "Kalshi Context AI"]


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
    req = Request(month_url(year, month), headers={"User-Agent": "BTC-AI-Council-v4/1.0"})
    with urlopen(req, timeout=45) as response:
        raw = response.read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        data = zf.read(zf.namelist()[0])
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "trades", "tb", "tq", "ignore"]
    df = pd.read_csv(io.BytesIO(data), header=None, names=cols)
    ot = pd.to_numeric(df["open_time"], errors="coerce")
    unit = "us" if float(ot.dropna().median()) > 1e14 else "ms"
    df["time"] = pd.to_datetime(ot, unit=unit, utc=True, errors="coerce")
    for c in ("open", "high", "low", "close", "volume", "qv", "tb", "tq"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["time", "open", "high", "low", "close", "volume"])


def regime_from_hist(hist):
    row = hist.iloc[-1]
    px = float(row.close)
    atr_pct = float(row.atr14 / px) if px and pd.notna(row.atr14) else 0.0
    spread = abs(float(row.ema9 - row.ema50)) / px if px else 0.0
    slope = float(row.ema9 - row.ema21)
    if atr_pct >= 0.0022:
        return "HIGH_VOL"
    if spread >= 0.0016:
        return "TREND_UP" if slope >= 0 else "TREND_DOWN"
    if atr_pct <= 0.0008:
        return "LOW_VOL_RANGE"
    return "RANGE"


def flow_proxy(raw_recent):
    rows = []
    for r in raw_recent.itertuples(index=False):
        qv = max(float(r.qv or 0.0), 0.0)
        buy = min(max(float(r.tq or 0.0), 0.0), qv)
        sell = max(qv - buy, 0.0)
        px = max(float(r.close), 1.0)
        if buy > 0:
            rows.append({"price": px, "qty": buy / px, "notional": buy, "aggressor": "BUY"})
        if sell > 0:
            rows.append({"price": px, "qty": sell / px, "notional": sell, "aggressor": "SELL"})
    return pd.DataFrame(rows, columns=["price", "qty", "notional", "aggressor"])


def stats_bucket():
    return {"samples": 0, "hits": 0, "calls": 0, "standalone_hits": 0, "unique_saves": 0, "harmful_flips": 0}


def main():
    now = datetime.now(timezone.utc)
    end_year, end_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    start_year = end_year - YEARS
    start_month = end_month + 1
    if start_month == 13:
        start_year += 1
        start_month = 1

    raw_buffer = deque(maxlen=120)
    pending = deque()
    months_loaded, months_failed = [], []
    total = hits = waits = 0
    traded = traded_hits = 0
    by_regime = defaultdict(lambda: {"samples": 0, "hits": 0, "trades": 0, "trade_hits": 0})
    bot_stats = defaultdict(stats_bucket)
    started = time.time()
    last_eval_minute = None

    for year, month in month_iter(start_year, start_month, end_year, end_month):
        try:
            month_df = fetch_month(year, month)
            months_loaded.append(f"{year}-{month:02d}")
        except Exception as exc:
            months_failed.append({"month": f"{year}-{month:02d}", "error": str(exc)[:180]})
            continue

        for r in month_df.itertuples(index=False):
            ts = pd.Timestamp(r.time)
            raw_buffer.append({
                "time": ts, "open": float(r.open), "high": float(r.high), "low": float(r.low),
                "close": float(r.close), "volume": float(r.volume),
                "qv": float(r.qv or 0.0), "tq": float(r.tq or 0.0),
            })

            while pending and pending[0][0] <= ts.value:
                _, start_px, vote, specialist_scores, regime = pending.popleft()
                actual_dir = 1 if float(r.close) >= start_px else -1
                full_dir = 1 if vote["base_score"] > 0.03 else -1 if vote["base_score"] < -0.03 else 0
                full_hit = int(full_dir != 0 and full_dir == actual_dir)
                total += 1
                hits += full_hit
                rb = by_regime[regime]
                rb["samples"] += 1
                rb["hits"] += full_hit
                if vote["action"] == "WAIT":
                    waits += 1
                else:
                    traded += 1
                    traded_hits += full_hit
                    rb["trades"] += 1
                    rb["trade_hits"] += full_hit

                for name, score in specialist_scores.items():
                    if name in EXCLUDED_FROM_COUNCIL or name in NON_REPLAYABLE:
                        continue
                    st = bot_stats[name]
                    st["samples"] += 1
                    d = 1 if score > 0.03 else -1 if score < -0.03 else 0
                    if d:
                        st["calls"] += 1
                        st["standalone_hits"] += int(d == actual_dir)
                    without_results = {k: {"score": v, "confidence": 0.70} for k, v in specialist_scores.items() if k != name}
                    without = council_vote(without_results, {}, regime)
                    wd = 1 if without["base_score"] > 0.03 else -1 if without["base_score"] < -0.03 else 0
                    without_hit = int(wd != 0 and wd == actual_dir)
                    st["hits"] += without_hit
                    if full_hit and not without_hit:
                        st["unique_saves"] += 1
                    if (not full_hit) and without_hit:
                        st["harmful_flips"] += 1

            if len(raw_buffer) < 60:
                continue
            minute_key = int(ts.timestamp() // 60)
            if minute_key % 15 != 0 or minute_key == last_eval_minute:
                continue
            last_eval_minute = minute_key

            raw_hist = pd.DataFrame(list(raw_buffer))
            hist = enrich_history_core(raw_hist[["time", "open", "high", "low", "close", "volume"]])
            if hist[["ema50", "rsi", "atr14"]].tail(1).isna().any(axis=None):
                continue
            agg = flow_proxy(raw_hist.tail(8))
            results = run_specialists_core(
                hist,
                agg,
                {"book_imbalance": 0.0, "funding_rate": 0.0, "open_interest": 0.0},
                {"available": False},
            )
            regime = regime_from_hist(hist)
            vote = council_vote(results, {}, regime)
            scores = {name: float(item.get("score", 0.0)) for name, item in results.items()}
            pending.append((ts.value + 15 * 60 * 1_000_000_000, float(r.close), vote, scores, regime))

    bots = []
    full_acc = hits / total if total else None
    for name, st in bot_stats.items():
        n = st["samples"]
        without_acc = st["hits"] / n if n else None
        bots.append({
            "name": name,
            "samples": n,
            "standalone_accuracy": st["standalone_hits"] / st["calls"] if st["calls"] else None,
            "full_council_accuracy": full_acc,
            "without_bot_accuracy": without_acc,
            "marginal_accuracy": (full_acc - without_acc) if full_acc is not None and without_acc is not None else None,
            "unique_save_rate": st["unique_saves"] / n if n else None,
            "harmful_flip_rate": st["harmful_flips"] / n if n else None,
        })
    bots.sort(key=lambda x: (x["marginal_accuracy"] if x["marginal_accuracy"] is not None else -999), reverse=True)

    regime_out = {}
    for name, b in sorted(by_regime.items()):
        regime_out[name] = {
            **b,
            "accuracy": b["hits"] / b["samples"] if b["samples"] else None,
            "trade_accuracy": b["trade_hits"] / b["trades"] if b["trades"] else None,
        }

    report = {
        "version": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": SYMBOL,
        "source": "Binance Vision monthly 1m archives",
        "period_requested_years": YEARS,
        "horizon_minutes": 15,
        "walk_forward": True,
        "replayable_specialists": REPLAYABLE,
        "non_replayable_specialists": NON_REPLAYABLE,
        "limitations": [
            "Whale AI uses Binance taker-buy quote-volume flow as a historical proxy, not raw aggTrades.",
            "Historical futures depth/funding/open-interest are unavailable in the spot archive and are not fabricated.",
            "Historical Kalshi KXBTC15M context is unavailable in the Binance archive and is not fabricated.",
            "This report measures signal direction; it is not a claim of profitable execution after all real-world costs.",
        ],
        "months_loaded": months_loaded,
        "months_failed": months_failed,
        "overall": {
            "samples": total,
            "direction_hits": hits,
            "direction_accuracy": hits / total if total else None,
            "waits": waits,
            "trade_signals": traded,
            "trade_signal_accuracy": traded_hits / traded if traded else None,
        },
        "regimes": regime_out,
        "specialist_ablation": bots,
        "runtime_seconds": time.time() - started,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report["overall"], indent=2))
    if total < 10000:
        raise RuntimeError(f"Council v4 historical replay produced too few samples: {total}")


if __name__ == "__main__":
    main()
