"""Persistent automatic paper trading for Gold, Gas, ZEC and WTI.

The worker is deliberately paper-only.  It reads public prices, evaluates the
same specialist council used by the Streamlit command centers, and stores four
independent $500 simulated ledgers inside ``learning_state.json``.  There are no
broker credentials or live-order functions in this module.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ai_core import enrich_history_core, run_specialists_core


MARKETS = {
    "gold": {"symbol": "GC=F", "display": "GOLD", "provider": "yahoo"},
    "gas": {"symbol": "RB=F", "display": "RBOB GAS", "provider": "yahoo"},
    "zec": {"symbol": "ZECUSDT", "display": "ZEC", "provider": "binance"},
    "wti": {"symbol": "CL=F", "display": "WTI OIL", "provider": "yahoo"},
}

BASE_SPECIALISTS = (
    "Trend AI",
    "Momentum AI",
    "Volume AI",
    "Pattern AI",
    "Support/Resistance AI",
    "Volatility AI",
    "Market Regime AI",
    "Historical Pattern AI",
    "Combination AI",
)

STARTING_CASH = 500.0
POSITION_FRACTION = 0.05
FEE_RATE = 0.00065
MIN_CONFIDENCE = 0.66
MIN_CONSENSUS = 0.60
MAX_HOLD_SECONDS = 15 * 60
REENTRY_COOLDOWN_SECONDS = 60
HISTORY_LIMIT = 250


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _iso(epoch):
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _http_json(url, params=None, timeout=8.0):
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/multi-asset-paper",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_history(market_key):
    cfg = MARKETS[market_key]
    if cfg["provider"] == "binance":
        payload = _http_json(
            "https://data-api.binance.vision/api/v3/klines",
            {"symbol": cfg["symbol"], "interval": "1m", "limit": 480},
        )
        rows = [
            {
                "time": pd.to_datetime(int(row[0]), unit="ms", utc=True),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in payload
        ]
        frame = pd.DataFrame(rows)
    else:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(cfg['symbol'], safe='')}"
        )
        payload = _http_json(
            url,
            {
                "interval": "1m",
                "range": "1d",
                "includePrePost": "true",
                "events": "div,splits",
            },
        )
        results = ((payload or {}).get("chart") or {}).get("result") or []
        if not results:
            raise RuntimeError("Yahoo history unavailable")
        node = results[0]
        timestamps = node.get("timestamp") or []
        quotes = ((((node.get("indicators") or {}).get("quote")) or [{}])[0]) or {}
        count = len(timestamps)
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime(timestamps, unit="s", utc=True),
                "open": quotes.get("open", [None] * count),
                "high": quotes.get("high", [None] * count),
                "low": quotes.get("low", [None] * count),
                "close": quotes.get("close", [None] * count),
                "volume": quotes.get("volume", [0] * count),
            }
        )
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["volume"] = frame["volume"].fillna(0.0)

    frame = (
        frame.dropna(subset=["open", "high", "low", "close"])
        .drop_duplicates("time")
        .sort_values("time")
        .tail(480)
        .reset_index(drop=True)
    )
    if len(frame) < 30:
        raise RuntimeError("Not enough clean 1-minute history")
    return frame


def fetch_zec_flow():
    trades = _http_json(
        "https://data-api.binance.vision/api/v3/aggTrades",
        {"symbol": "ZECUSDT", "limit": 500},
    )
    agg = pd.DataFrame(
        [
            {
                "price": float(row["p"]),
                "qty": float(row["q"]),
                "notional": float(row["p"]) * float(row["q"]),
                "aggressor": "SELL" if bool(row.get("m")) else "BUY",
            }
            for row in trades
        ]
    )
    depth = _http_json(
        "https://data-api.binance.vision/api/v3/depth",
        {"symbol": "ZECUSDT", "limit": 100},
    )
    bids = sum(float(price) * float(qty) for price, qty in depth.get("bids", []))
    asks = sum(float(price) * float(qty) for price, qty in depth.get("asks", []))
    total = bids + asks
    return agg, {
        "book_imbalance": (bids - asks) / total if total else 0.0,
        "funding_rate": 0.0,
        "open_interest": 0.0,
    }


def decision_from_specialists(results, market_key, kalshi_available=False):
    active = list(BASE_SPECIALISTS)
    if kalshi_available:
        active.append("Kalshi Context AI")
    if market_key == "zec":
        active.extend(["Whale AI", "Liquidity AI"])

    rows = [results[name] for name in active if name in results]
    if not rows:
        return {
            "action": "WAIT",
            "score": 0.0,
            "confidence": 0.0,
            "consensus": 0.0,
            "active_specialists": 0,
        }

    total_weight = 0.0
    weighted_score = 0.0
    directional = []
    for result in rows:
        confidence = float(np.clip(_safe_float(result.get("confidence"), 0.48), 0.0, 1.0))
        score = float(np.clip(_safe_float(result.get("score"), 0.0), -1.0, 1.0))
        weight = max(0.15, confidence)
        total_weight += weight
        weighted_score += score * weight
        if abs(score) >= 0.12:
            directional.append(np.sign(score))

    score = weighted_score / max(total_weight, 1e-9)
    direction = np.sign(score)
    consensus = (
        sum(1 for sign in directional if sign == direction) / len(directional)
        if directional
        else 0.0
    )
    evidence = min(1.0, abs(score) / 0.55)
    confidence = float(np.clip(0.48 + 0.30 * evidence + 0.18 * consensus, 0.48, 0.92))
    action = "WAIT"
    if abs(score) >= 0.14 and consensus >= MIN_CONSENSUS and confidence >= MIN_CONFIDENCE:
        action = "SCALP UP" if score > 0 else "SCALP DOWN"
    return {
        "action": action,
        "score": float(score),
        "confidence": confidence,
        "consensus": float(consensus),
        "active_specialists": len(rows),
    }


def default_asset_state():
    return {
        "enabled": True,
        "starting_cash": STARTING_CASH,
        "cash": STARTING_CASH,
        "side": "NONE",
        "entry": None,
        "qty": 0.0,
        "entry_fee": 0.0,
        "opened_at": None,
        "realized": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "last_exit_at": None,
        "last_price": None,
        "last_action": "WAIT",
        "last_message": "AUTO PAPER ready.",
        "history": [],
    }


def ensure_multi_asset_state(root):
    multi = root.setdefault("multi_asset_paper", {})
    multi["version"] = 1
    multi["paper_only"] = True
    multi["real_money_execution"] = False
    multi["enabled"] = True
    assets = multi.setdefault("assets", {})
    for key in MARKETS:
        bucket = assets.setdefault(key, {})
        defaults = default_asset_state()
        for field, value in defaults.items():
            bucket.setdefault(field, value)
        # Automation is a project-level invariant, not a browser preference.
        bucket["enabled"] = True
    return multi


def _position_return(bucket, price):
    entry = _safe_float(bucket.get("entry"), 0.0)
    if entry <= 0 or bucket.get("side") not in {"LONG", "SHORT"}:
        return 0.0
    raw = (price / entry) - 1.0
    return raw if bucket["side"] == "LONG" else -raw


def paper_cycle(bucket, price, decision, atr_pct, now=None, feed_fresh=True):
    """Advance one simulated ledger and return the action taken this cycle."""
    now = float(time.time() if now is None else now)
    price = _safe_float(price, 0.0)
    if price <= 0:
        bucket["last_message"] = "AUTO PAPER waiting: invalid public price."
        return "WAIT"

    bucket["last_price"] = price
    bucket["last_action"] = str(decision.get("action") or "WAIT")
    bucket["updated_at"] = _iso(now)
    if not feed_fresh:
        bucket["last_message"] = "AUTO PAPER waiting: source market is closed or stale."
        return "STALE"

    side = bucket.get("side", "NONE")
    action = str(decision.get("action") or "WAIT")
    confidence = _safe_float(decision.get("confidence"), 0.0)
    consensus = _safe_float(decision.get("consensus"), 0.0)
    target_pct = float(np.clip(max(0.004, atr_pct * 1.25), 0.004, 0.025))
    stop_pct = float(np.clip(max(0.003, atr_pct * 0.75), 0.003, 0.015))

    if side in {"LONG", "SHORT"}:
        held = max(0.0, now - _safe_float(bucket.get("opened_at"), now))
        position_return = _position_return(bucket, price)
        opposite = (side == "LONG" and action == "SCALP DOWN") or (
            side == "SHORT" and action == "SCALP UP"
        )
        exit_reason = None
        if position_return >= target_pct:
            exit_reason = "VOLATILITY TARGET"
        elif position_return <= -stop_pct:
            exit_reason = "VOLATILITY STOP"
        elif opposite and confidence >= MIN_CONFIDENCE and consensus >= MIN_CONSENSUS:
            exit_reason = "COUNCIL REVERSAL"
        elif held >= MAX_HOLD_SECONDS:
            exit_reason = "15-MINUTE HORIZON"

        if exit_reason:
            entry = _safe_float(bucket.get("entry"), price)
            qty = _safe_float(bucket.get("qty"), 0.0)
            gross = (price - entry) * qty
            if side == "SHORT":
                gross = -gross
            exit_fee = price * qty * FEE_RATE
            net = gross - _safe_float(bucket.get("entry_fee"), 0.0) - exit_fee
            bucket["cash"] = _safe_float(bucket.get("cash"), STARTING_CASH) + gross - exit_fee
            bucket["realized"] = _safe_float(bucket.get("realized"), 0.0) + gross - exit_fee
            bucket["trades"] = int(bucket.get("trades") or 0) + 1
            won = net > 0
            bucket["wins" if won else "losses"] = int(bucket.get("wins" if won else "losses") or 0) + 1
            trade = {
                "side": side,
                "entry": entry,
                "exit": price,
                "qty": qty,
                "net_pnl": net,
                "opened_at": bucket.get("opened_at"),
                "closed_at": _iso(now),
                "exit_reason": exit_reason,
            }
            bucket.setdefault("history", []).append(trade)
            bucket["history"] = bucket["history"][-HISTORY_LIMIT:]
            bucket.update(
                side="NONE",
                entry=None,
                qty=0.0,
                entry_fee=0.0,
                opened_at=None,
                last_exit_at=_iso(now),
                last_message=f"Closed {side} automatically: {exit_reason}; net {net:+.2f}.",
            )
            return "CLOSE"

        bucket["last_message"] = (
            f"Managing automatic {side}; return {position_return:+.2%}, "
            f"target {target_pct:.2%}, stop {-stop_pct:.2%}."
        )
        return "MANAGE"

    last_exit = bucket.get("last_exit_at")
    if last_exit:
        try:
            last_exit_epoch = datetime.fromisoformat(str(last_exit).replace("Z", "+00:00")).timestamp()
        except Exception:
            last_exit_epoch = 0.0
        if now - last_exit_epoch < REENTRY_COOLDOWN_SECONDS:
            bucket["last_message"] = "AUTO PAPER cooldown after the last exit."
            return "COOLDOWN"

    if (
        action in {"SCALP UP", "SCALP DOWN"}
        and confidence >= MIN_CONFIDENCE
        and consensus >= MIN_CONSENSUS
    ):
        cash = max(0.0, _safe_float(bucket.get("cash"), STARTING_CASH))
        notional = cash * POSITION_FRACTION
        if notional <= 0:
            bucket["last_message"] = "AUTO PAPER paused: simulated cash exhausted."
            return "WAIT"
        qty = notional / price
        entry_fee = notional * FEE_RATE
        side = "LONG" if action == "SCALP UP" else "SHORT"
        bucket["cash"] = cash - entry_fee
        bucket["realized"] = _safe_float(bucket.get("realized"), 0.0) - entry_fee
        bucket.update(
            side=side,
            entry=price,
            qty=qty,
            entry_fee=entry_fee,
            opened_at=_iso(now),
            last_message=(
                f"Opened automatic {side} at {price:.4f}; "
                f"confidence {confidence:.0%}, consensus {consensus:.0%}."
            ),
        )
        return "OPEN"

    bucket["last_message"] = "AUTO PAPER scanning; no approved council entry."
    return "WAIT"


def _evaluate_market(market_key, now):
    raw = fetch_history(market_key)
    hist = enrich_history_core(raw)
    if len(hist.dropna(subset=["ema21", "rsi", "atr14"])) < 10:
        raise RuntimeError("Indicators are still warming up")
    agg, flow = (fetch_zec_flow() if market_key == "zec" else (None, {}))
    results = run_specialists_core(hist, agg, flow, {"available": False})
    decision = decision_from_specialists(results, market_key, kalshi_available=False)
    price = float(hist["close"].iloc[-1])
    atr_pct = _safe_float(hist["atr14"].iloc[-1] / price, 0.0)
    last_bar = pd.Timestamp(hist["time"].iloc[-1]).timestamp()
    max_age = 5 * 60 if market_key == "zec" else 30 * 60
    return price, atr_pct, decision, (now - last_bar) <= max_age, _iso(last_bar)


def run_all_markets(root, now=None):
    now = float(time.time() if now is None else now)
    multi = ensure_multi_asset_state(root)
    failures = {}
    actions = {}
    for market_key in MARKETS:
        bucket = multi["assets"][market_key]
        try:
            price, atr_pct, decision, fresh, bar_time = _evaluate_market(market_key, now)
            bucket["source_bar_at"] = bar_time
            bucket["decision"] = decision
            actions[market_key] = paper_cycle(
                bucket,
                price,
                decision,
                atr_pct,
                now=now,
                feed_fresh=fresh,
            )
        except Exception as exc:
            failures[market_key] = str(exc)
            bucket["last_message"] = f"AUTO PAPER source error: {exc}"
            actions[market_key] = "ERROR"

    multi["updated_at"] = _iso(now)
    multi["runs"] = int(multi.get("runs") or 0) + 1
    multi["worker_ok"] = not failures
    multi["failures"] = failures
    multi["actions"] = actions
    return multi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state",
        default="/tmp/learning_state.json",
        help="Learning-state JSON file to update in place.",
    )
    args = parser.parse_args()
    path = Path(args.state)
    root = json.loads(path.read_text()) if path.exists() else {}
    multi = run_all_markets(root)
    path.write_text(json.dumps(root, indent=2, allow_nan=False) + "\n")
    print(
        "Multi-asset AUTO PAPER",
        "ok" if multi["worker_ok"] else "degraded",
        multi["actions"],
        multi["failures"],
    )


if __name__ == "__main__":
    main()
