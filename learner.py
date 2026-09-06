#!/usr/bin/env python3
import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ai_core import SPECIALIST_NAMES, enrich_history_core, forecast_path_core, run_specialists_core
from learning_prices import closed_price_at

SPOT = "https://data-api.binance.vision"
FUTURES = "https://fapi.binance.com"
KALSHI = "https://external-api.kalshi.com/trade-api/v2"
STATE = "https://raw.githubusercontent.com/Toddtoddtard/-btc-ai-trading-command-center/learning-state/learning_state.json"
OUT = Path(os.getenv("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json"))
BOTS = list(SPECIALIST_NAMES)


def get(url, params=None):
    if params:
        url += "?" + urlencode(params)
    req = Request(
        url,
        headers={
            "User-Agent": "BTC-AI-24x7/2.0",
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def fresh():
    specs = {
        name: {
            "adaptive_weight": 1.0,
            "samples": 0,
            "direction_hits": 0,
            "ewma_accuracy": 0.5,
            "ewma_edge": 0.0,
            "ewma_calibration": 0.0,
        }
        for name in BOTS
    }
    return {
        "version": 2,
        "updated_at": None,
        "forecast": {
            "w_ret3": 0.46,
            "w_ret8": 0.34,
            "w_ret15": 0.20,
            "momentum_scale": 2.2,
            "target_influence": 0.18,
            "bias": 0.0,
            "learning_rate": 0.08,
            "samples": 0,
            "direction_hits": 0,
            "avg_abs_error": 0.0,
            "avg_path_error": 0.0,
            "kalshi_samples": 0,
            "kalshi_hits": 0,
        },
        "specialists": specs,
        "master_history": [],
        "specialist_history": {name: [] for name in BOTS},
        "pending": None,
        "official_pending": [],
        "status": {},
    }


def migrate_event_name(state):
    old = "Event AI"
    new = "Kalshi Context AI"
    specialists = state.setdefault("specialists", {})
    histories = state.setdefault("specialist_history", {})
    if old in specialists and new not in specialists:
        specialists[new] = specialists.pop(old)
    else:
        specialists.pop(old, None)
    if old in histories and new not in histories:
        histories[new] = histories.pop(old)
    else:
        histories.pop(old, None)
    pending = state.get("pending")
    if isinstance(pending, dict):
        preds = pending.get("specialists")
        if isinstance(preds, dict) and old in preds and new not in preds:
            preds[new] = preds.pop(old)
    return state


def load():
    base = fresh()
    try:
        state = get(STATE)
        if isinstance(state, dict) and "forecast" in state:
            state = migrate_event_name(state)
            base.update(state)
            merged_forecast = fresh()["forecast"]
            merged_forecast.update(state.get("forecast", {}))
            base["forecast"] = merged_forecast
            base.setdefault("official_pending", [])
            for name in BOTS:
                base.setdefault("specialists", {}).setdefault(name, fresh()["specialists"][name])
                base.setdefault("specialist_history", {}).setdefault(name, [])
            base["version"] = 2
            return base
    except Exception:
        pass
    return base


def history():
    raw = get(SPOT + "/api/v3/klines", {"symbol": "BTCUSDT", "interval": "1m", "limit": 240})
    cols = ["ot", "open", "high", "low", "close", "volume", "ct", "qv", "trades", "tb", "tq", "x"]
    df = pd.DataFrame(raw, columns=cols)
    for key in ["open", "high", "low", "close", "volume"]:
        df[key] = pd.to_numeric(df[key], errors="coerce")
    df["time"] = pd.to_datetime(df.ot, unit="ms", utc=True)
    return enrich_history_core(df)


def aggregate_trades():
    try:
        payload = get(SPOT + "/api/v3/aggTrades", {"symbol": "BTCUSDT", "limit": 700})
        rows = []
        for item in payload:
            price = float(item["p"])
            qty = float(item["q"])
            rows.append(
                {
                    "price": price,
                    "qty": qty,
                    "notional": price * qty,
                    "aggressor": "SELL" if bool(item.get("m")) else "BUY",
                }
            )
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["price", "qty", "notional", "aggressor"])


def futures_snapshot():
    result = {"book_imbalance": 0.0, "funding_rate": 0.0, "open_interest": 0.0}
    try:
        depth = get(FUTURES + "/fapi/v1/depth", {"symbol": "BTCUSDT", "limit": 20})
        bids = sum(float(x[0]) * float(x[1]) for x in depth.get("bids", []))
        asks = sum(float(x[0]) * float(x[1]) for x in depth.get("asks", []))
        denom = bids + asks
        result["book_imbalance"] = (bids - asks) / denom if denom else 0.0
    except Exception:
        pass
    try:
        premium = get(FUTURES + "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
        result["funding_rate"] = float(premium.get("lastFundingRate") or 0.0)
    except Exception:
        pass
    try:
        oi = get(FUTURES + "/fapi/v1/openInterest", {"symbol": "BTCUSDT"})
        result["open_interest"] = float(oi.get("openInterest") or 0.0)
    except Exception:
        pass
    return result


def strike(market):
    if not isinstance(market, dict):
        return None
    for key in ("yes_sub_title", "subtitle", "title"):
        text = str(market.get(key) or "")
        match = re.search(r"Target\s*Price\s*:\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)", text, re.I)
        if match:
            try:
                value = float(match.group(1).replace(",", ""))
                if math.isfinite(value) and value > 0:
                    return value
            except Exception:
                pass
    strike_type = str(market.get("strike_type") or "").lower()
    keys = ("cap_strike", "floor_strike") if strike_type in {"less", "less_equal", "less-than", "less_than"} else ("floor_strike", "cap_strike")
    for key in keys:
        try:
            value = float(market.get(key))
            if math.isfinite(value) and value > 0:
                return value
        except Exception:
            pass
    return None


def exact_market(ticker):
    try:
        return get(KALSHI + "/markets/" + ticker).get("market", {})
    except Exception:
        return {}


def market():
    try:
        markets = get(KALSHI + "/markets", {"limit": 100, "status": "open", "series_ticker": "KXBTC15M"}).get("markets", [])
    except Exception:
        return None
    now = time.time()
    choices = []
    for item in markets:
        try:
            expires = pd.Timestamp(item.get("close_time") or item.get("expiration_time") or item.get("expected_expiration_time")).timestamp()
            target = strike(item)
            if expires > now and target is not None:
                choices.append((expires, str(item.get("ticker", "")), item, target))
        except Exception:
            pass
    if not choices:
        return None
    expires, ticker, item, target = sorted(choices, key=lambda row: (row[0], row[1]))[0]
    exact = exact_market(ticker)
    if exact:
        exact_target = strike(exact)
        if exact_target is not None:
            target = exact_target
        raw_expiry = exact.get("close_time") or exact.get("expiration_time") or exact.get("expected_expiration_time")
        if raw_expiry:
            expires = pd.Timestamp(raw_expiry).timestamp()
        item = {**item, **exact}
    vals = []
    for key in ["yes_bid_dollars", "yes_ask_dollars"]:
        try:
            vals.append(float(item[key]))
        except Exception:
            pass
    prob = sum(vals) / len(vals) if vals else 0.5
    return {"ticker": ticker, "expires_at": expires, "target": float(target), "prob": prob}


def kalshi_context(market_info, price):
    if not market_info:
        return {"available": False}
    target = float(market_info["target"])
    distance = price - target
    return {
        "available": True,
        "ticker": market_info["ticker"],
        "target": target,
        "up_probability": float(market_info.get("prob", 0.5)),
        "distance": distance,
        "distance_pct": distance / target if target else 0.0,
    }


def official_result(ticker):
    market_data = exact_market(ticker)
    value = str(market_data.get("result") or "").strip().lower()
    if value in {"yes", "no"}:
        return value
    return None


def rows_for_forecast(df):
    return [
        {"open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close)}
        for row in df.tail(60).itertuples()
    ]


def register(state, df, market_info):
    if not market_info or state.get("pending") is not None:
        return False
    price = float(df.close.iloc[-1])
    agg = aggregate_trades()
    futures = futures_snapshot()
    specialists = run_specialists_core(df, agg, futures, kalshi_context(market_info, price))
    forecast = forecast_path_core(rows_for_forecast(df), market_info["target"], state["forecast"])
    if not forecast:
        return False
    inputs = forecast["inputs"]
    state["pending"] = {
        "ticker": market_info["ticker"],
        "opened_at": time.time(),
        "expires_at": market_info["expires_at"],
        "target": market_info["target"],
        "start_price": price,
        "predicted_end": forecast["predicted_end"],
        "predicted_direction": forecast["predicted_direction"],
        "ret3": inputs["ret3"],
        "ret8": inputs["ret8"],
        "ret15": inputs["ret15"],
        "forecast_path": forecast["forecast"],
        "specialists": specialists,
    }
    return True


def grade(state, df):
    pending = state.get("pending")
    if not pending or time.time() < pending["expires_at"]:
        return False
    expiry = pd.to_datetime(pending["expires_at"], unit="s", utc=True)
    actual = closed_price_at(df, expiry)
    if actual is None:
        return False
    start = float(pending["start_price"])
    predicted_end = float(pending["predicted_end"])
    actual_direction = 1 if actual >= start else -1
    direction_correct = int(actual_direction == int(pending["predicted_direction"]))
    abs_error = abs(actual - predicted_end)

    path_error = abs_error
    pred_path = pending.get("forecast_path") or []
    candle_closes = pd.to_datetime(df.time, utc=True, errors="coerce") + pd.Timedelta(minutes=1)
    actual_window = df.loc[(candle_closes > expiry - pd.Timedelta(minutes=15)) & (candle_closes <= expiry)].tail(15)
    if pred_path and len(actual_window) >= 5:
        pred_closes = np.array([float(point["close"]) for point in pred_path], dtype=float)
        actual_closes = actual_window["close"].astype(float).to_numpy()
        n_path = min(len(pred_closes), len(actual_closes))
        path_error = float(np.mean(np.abs(pred_closes[-n_path:] - actual_closes[-n_path:])))

    forecast_state = state["forecast"]
    lr = float(forecast_state["learning_rate"])
    actual_return = actual / start - 1.0
    predicted_return = predicted_end / start - 1.0
    error = actual_return - predicted_return
    features = np.array([pending["ret3"], pending["ret8"], pending["ret15"]], dtype=float)
    scale = max(float(np.abs(features).sum()), 1e-6)
    adjustments = lr * error * (features / scale) * 8.0
    weights = np.clip(
        np.array([forecast_state["w_ret3"], forecast_state["w_ret8"], forecast_state["w_ret15"]]) + adjustments,
        0.05,
        0.90,
    )
    weights /= weights.sum()
    forecast_state["w_ret3"], forecast_state["w_ret8"], forecast_state["w_ret15"] = map(float, weights)
    if abs(predicted_return) > 1e-5:
        ratio = actual_return / predicted_return
        forecast_state["momentum_scale"] *= float(np.clip(1.0 + lr * (ratio - 1.0) * 0.20, 0.94, 1.06))
    forecast_state["momentum_scale"] = float(np.clip(forecast_state["momentum_scale"], 0.60, 4.50))
    forecast_state["bias"] = float(np.clip(forecast_state["bias"] + np.clip(lr * error * 0.12, -0.00015, 0.00015), -0.004, 0.004))
    forecast_state["target_influence"] = float(np.clip(forecast_state["target_influence"], 0.0, 0.5))

    forecast_state["samples"] += 1
    forecast_state["direction_hits"] += direction_correct
    sample_count = forecast_state["samples"]
    forecast_state["avg_abs_error"] = abs_error if sample_count == 1 else forecast_state["avg_abs_error"] + (abs_error - forecast_state["avg_abs_error"]) / sample_count
    forecast_state["avg_path_error"] = path_error if sample_count == 1 else forecast_state["avg_path_error"] + (path_error - forecast_state["avg_path_error"]) / sample_count

    history_row = {
        "ticker": pending["ticker"],
        "expires_at": pending["expires_at"],
        "direction_correct": direction_correct,
        "abs_error": abs_error,
        "path_error": path_error,
        "kalshi_correct": None,
        "kalshi_result": None,
    }
    state["master_history"].append(history_row)
    state["master_history"] = state["master_history"][-1000:]
    state.setdefault("official_pending", []).append(
        {
            "ticker": pending["ticker"],
            "target": pending["target"],
            "predicted_end": predicted_end,
        }
    )
    state["official_pending"] = state["official_pending"][-100:]

    realized = actual / start - 1.0
    for name, call in pending["specialists"].items():
        if name not in state["specialists"]:
            continue
        learned = state["specialists"][name]
        score = float(call["score"])
        predicted_direction = 1 if score > 0.03 else -1 if score < -0.03 else 0
        hit = int(predicted_direction != 0 and predicted_direction == actual_direction)
        edge = score * realized * 100 if predicted_direction else 0.0
        calibration = float(call["confidence"]) if hit else -float(call["confidence"])
        alpha = 0.10
        learned["ewma_accuracy"] = (1 - alpha) * learned["ewma_accuracy"] + alpha * hit
        learned["ewma_edge"] = (1 - alpha) * learned["ewma_edge"] + alpha * edge
        learned["ewma_calibration"] = (1 - alpha) * learned["ewma_calibration"] + alpha * calibration
        learned["samples"] += 1
        learned["direction_hits"] += hit
        quality = 0.55 * (learned["ewma_accuracy"] - 0.5) * 2 + 0.25 * np.tanh(learned["ewma_edge"] * 4) + 0.20 * learned["ewma_calibration"]
        target_weight = float(np.clip(1 + quality, 0.35, 1.85))
        learned["adaptive_weight"] = float(np.clip(0.9 * learned["adaptive_weight"] + 0.1 * target_weight, 0.35, 1.85))
        history = state.setdefault("specialist_history", {}).setdefault(name, [])
        history.append({"ticker": pending["ticker"], "expires_at": pending["expires_at"], "direction_correct": hit, "signed_edge": edge})
        state["specialist_history"][name] = history[-1000:]

    state["pending"] = None
    state["status"]["last_graded_ticker"] = pending["ticker"]
    return True


def resolve_official_results(state):
    unresolved = []
    resolved_count = 0
    for item in state.get("official_pending", []):
        result = official_result(item["ticker"])
        if result not in {"yes", "no"}:
            unresolved.append(item)
            continue
        predicted_yes = float(item["predicted_end"]) >= float(item["target"])
        actual_yes = result == "yes"
        hit = int(predicted_yes == actual_yes)
        forecast = state["forecast"]
        forecast["kalshi_samples"] = int(forecast.get("kalshi_samples", 0)) + 1
        forecast["kalshi_hits"] = int(forecast.get("kalshi_hits", 0)) + hit
        for row in reversed(state.get("master_history", [])):
            if row.get("ticker") == item["ticker"]:
                row["kalshi_correct"] = hit
                row["kalshi_result"] = result
                break
        resolved_count += 1
    state["official_pending"] = unresolved[-100:]
    return resolved_count


def main():
    state = load()
    df = history()
    market_info = market()
    graded = grade(state, df)
    official_resolved = resolve_official_results(state)
    registered = register(state, df, market_info)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    forecast = state["forecast"]
    kalshi_samples = int(forecast.get("kalshi_samples", 0))
    state["status"].update(
        {
            "worker_ok": True,
            "shared_core": True,
            "graded_this_run": graded,
            "official_results_resolved": official_resolved,
            "registered_this_run": registered,
            "btc_price": float(df.close.iloc[-1]),
            "active_ticker": market_info["ticker"] if market_info else "",
            "active_target": market_info["target"] if market_info else None,
            "forecast_samples": forecast["samples"],
            "kalshi_samples": kalshi_samples,
            "kalshi_accuracy": (forecast.get("kalshi_hits", 0) / kalshi_samples) if kalshi_samples else None,
        }
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps(state["status"], indent=2))


if __name__ == "__main__":
    main()
