#!/usr/bin/env python3
"""Five-year walk-forward replay for the BTC AI Council v4.

Uses Binance Vision 1-minute archives. Candle/volume specialists are replayed
from information available at each timestamp. Whale flow is approximated from
Binance taker-buy quote volume versus total quote volume. Historical futures
book/funding/open-interest and Kalshi contracts are not available in the spot
archive, so those specialists remain neutral and are explicitly reported as
non-replayable rather than fabricated.
"""
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core
from council_v4 import EXCLUDED_FROM_COUNCIL, _action_direction, _direction, council_vote
from historical_backtest import fetch_month, month_iter, month_url

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
YEARS = 5
BASE = "https://data.binance.vision/data/spot/monthly/klines"
OUT = Path(os.getenv("COUNCIL_BACKTEST_OUTPUT", "/tmp/council_backtest_v4.json"))
REPLAYABLE = [
    "Trend AI", "Momentum AI", "Volume AI", "Pattern AI",
    "Support/Resistance AI", "Volatility AI", "Market Regime AI",
    "Whale AI", "Historical Pattern AI", "FVG / MACD AI",
]
NON_REPLAYABLE = ["Liquidity AI", "Derivatives AI", "Kalshi Context AI"]


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
    return defaultdict(int)


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
    missing_deadline_prices = 0
    traded = traded_hits = 0
    by_regime = defaultdict(lambda: {"samples": 0, "hits": 0, "trades": 0, "trade_hits": 0})
    bot_stats = defaultdict(stats_bucket)
    started = time.time()
    last_eval_minute = None
    last_timestamp = None

    for year, month in month_iter(start_year, start_month, end_year, end_month):
        try:
            month_df = fetch_month(year, month)
            months_loaded.append(f"{year}-{month:02d}")
        except Exception as exc:
            months_failed.append({"month": f"{year}-{month:02d}", "error": str(exc)[:180]})
            continue

        for r in month_df.itertuples(index=False):
            ts = pd.Timestamp(r.time)
            if last_timestamp is not None and ts - last_timestamp != pd.Timedelta(minutes=1):
                raw_buffer.clear()
            last_timestamp = ts
            raw_buffer.append({
                "time": ts, "open": float(r.open), "high": float(r.high), "low": float(r.low),
                "close": float(r.close), "volume": float(r.volume),
                "qv": float(r.qv or 0.0), "tq": float(r.tq or 0.0),
            })

            while pending and pending[0][0] <= ts.value:
                deadline, start_px, vote, specialist_results, regime = pending.popleft()
                if deadline != ts.value:
                    missing_deadline_prices += 1
                    continue
                actual_dir = 1 if float(r.close) >= start_px else -1
                full_dir = _action_direction(vote)
                full_hit = int(full_dir != 0 and full_dir == actual_dir)
                total += 1
                hits += full_hit
                rb = by_regime[regime]
                rb["samples"] += 1
                rb["hits"] += full_hit
                if not full_dir:
                    waits += 1
                else:
                    traded += 1
                    traded_hits += full_hit
                    rb["trades"] += 1
                    rb["trade_hits"] += full_hit

                for name, call in specialist_results.items():
                    if name in EXCLUDED_FROM_COUNCIL or name in NON_REPLAYABLE:
                        continue
                    st = bot_stats[name]
                    st["samples"] += 1
                    d = _direction(call.get("score"))
                    if d:
                        st["calls"] += 1
                        st["standalone_hits"] += int(d == actual_dir)
                    without = council_vote(specialist_results, {}, regime, exclude={name})
                    wd = _action_direction(without)
                    without_hit = int(wd != 0 and wd == actual_dir)
                    st["full_calls"] += int(full_dir != 0)
                    st["full_hits"] += full_hit
                    st["without_calls"] += int(wd != 0)
                    st["hits"] += without_hit
                    if full_dir and wd:
                        st["paired_calls"] += 1
                        st["unique_saves"] += int(full_hit and not without_hit)
                        st["harmful_flips"] += int(not full_hit and without_hit)
                    elif full_dir or wd:
                        st["abstention_changes"] += 1
                    if full_dir or wd:
                        st["paired_decisions"] += 1
                        full_value = (1 if full_hit else -1) if full_dir else 0
                        without_value = (1 if without_hit else -1) if wd else 0
                        st["utility_delta"] += full_value - without_value
                        st["beneficial_decisions"] += int(full_value > without_value)
                        st["harmful_decisions"] += int(full_value < without_value)

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
            pending.append((ts.value + 15 * 60 * 1_000_000_000, float(r.close), vote, results, regime))

    bots = []
    for name, st in bot_stats.items():
        n = st["samples"]
        full_acc = st["full_hits"] / st["full_calls"] if st["full_calls"] else None
        without_acc = st["hits"] / st["without_calls"] if st["without_calls"] else None
        paired = st["paired_calls"]
        decisions = st["paired_decisions"]
        bots.append({
            "name": name,
            "samples": n,
            "standalone_accuracy": st["standalone_hits"] / st["calls"] if st["calls"] else None,
            "full_council_accuracy": full_acc,
            "without_bot_accuracy": without_acc,
            "full_council_calls": st["full_calls"],
            "without_bot_calls": st["without_calls"],
            "paired_calls": paired,
            "marginal_accuracy": (st["unique_saves"] - st["harmful_flips"]) / paired if paired else None,
            "unique_save_rate": st["unique_saves"] / paired if paired else None,
            "harmful_flip_rate": st["harmful_flips"] / paired if paired else None,
            "abstention_changes": st["abstention_changes"],
            "paired_decisions": decisions,
            "beneficial_decisions": st["beneficial_decisions"],
            "harmful_decisions": st["harmful_decisions"],
            "marginal_decision_utility": st["utility_delta"] / decisions if decisions else None,
        })
    bots.sort(key=lambda x: (x["marginal_decision_utility"] if x["marginal_decision_utility"] is not None else -999), reverse=True)

    regime_out = {}
    for name, b in sorted(by_regime.items()):
        regime_out[name] = {
            **b,
            "accuracy": b["trade_hits"] / b["trades"] if b["trades"] else None,
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
        "label_basis": "archived_btc_15m_direction_v1",
        "decision_basis": "gated_council_subdecision_with_empty_learning_state",
        "decision_utility": "correct +1, incorrect -1, WAIT 0; no trade-profit inference",
        "actual_master_execution_replayed": False,
        "affects_execution": False,
        "paper_only": True,
        "missing_deadline_prices": missing_deadline_prices,
        "ungraded_pending": len(pending),
        "replayable_specialists": REPLAYABLE,
        "non_replayable_specialists": NON_REPLAYABLE,
        "limitations": [
            "Whale AI uses Binance taker-buy quote-volume flow as a historical proxy, not raw aggTrades.",
            "Historical futures depth/funding/open-interest are unavailable in the spot archive and are not fabricated.",
            "Historical Kalshi KXBTC15M context is unavailable in the Binance archive and is not fabricated.",
            "Labels measure archived BTC price direction at the exact 15-minute deadline, not official Kalshi settlement.",
            "Council subdecisions use empty learning state; actual Master execution and trade P/L are not replayed.",
            "Missing deadline candles are skipped; later prices cannot substitute for the requested horizon.",
        ],
        "months_loaded": months_loaded,
        "months_failed": months_failed,
        "overall": {
            "samples": total,
            "direction_hits": hits,
            "direction_calls": traded,
            "direction_accuracy": hits / traded if traded else None,
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
