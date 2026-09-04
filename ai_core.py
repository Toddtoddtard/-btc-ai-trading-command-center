import math
import numpy as np
import pandas as pd

SPECIALIST_NAMES = [
    "Trend AI",
    "Momentum AI",
    "Volume AI",
    "Pattern AI",
    "Support/Resistance AI",
    "Volatility AI",
    "Market Regime AI",
    "Whale AI",
    "Liquidity AI",
    "Derivatives AI",
    "Kalshi Context AI",
    "Historical Pattern AI",
    "Combination AI",
]


def clamp(x, lo=-1.0, hi=1.0):
    try:
        return float(max(lo, min(hi, x)))
    except Exception:
        return 0.0


def safe_float(x, default=np.nan):
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def enrich_history_core(df):
    x = df.copy()
    c = x["close"]
    x["ret1"] = c.pct_change()
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema21"] = c.ewm(span=21, adjust=False).mean()
    x["ema50"] = c.ewm(span=50, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["vol20"] = x["ret1"].rolling(20).std() * np.sqrt(20)
    x["sma20"] = c.rolling(20).mean()
    x["std20"] = c.rolling(20).std()
    x["bb_upper"] = x["sma20"] + 2 * x["std20"]
    x["bb_lower"] = x["sma20"] - 2 * x["std20"]
    x["volume_ma20"] = x["volume"].rolling(20).mean()
    x["volume_z"] = (x["volume"] - x["volume_ma20"]) / x["volume"].rolling(20).std().replace(0, np.nan)
    x["high20"] = x["high"].rolling(20).max()
    x["low20"] = x["low"].rolling(20).min()
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - c.shift()).abs(),
        (x["low"] - c.shift()).abs(),
    ], axis=1).max(axis=1)
    x["atr14"] = tr.rolling(14).mean()
    return x


def _specialist(name, score, reason):
    score = clamp(score)
    if score > 0.12:
        signal = "BULLISH"
    elif score < -0.12:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    confidence = min(0.99, 0.48 + abs(score) * 0.48)
    return {"name": name, "signal": signal, "score": score, "confidence": confidence, "reason": reason}


def run_specialists_core(hist, agg, futures, kctx):
    last = hist.iloc[-1]
    prev = hist.iloc[-2]
    px = float(last["close"])
    out = {}

    trend_score = 0.55 * np.sign(last["ema9"] - last["ema21"]) + 0.45 * np.sign(last["ema21"] - last["ema50"])
    out["Trend AI"] = _specialist("Trend AI", trend_score, f"EMA9 {last['ema9']:.0f}, EMA21 {last['ema21']:.0f}, EMA50 {last['ema50']:.0f}")

    rsi = safe_float(last["rsi"], 50.0)
    macd_delta = safe_float(last["macd"] - last["macd_signal"], 0.0)
    momentum = clamp(((rsi - 50) / 30) * 0.55 + np.sign(macd_delta) * min(abs(macd_delta) / max(px * 0.0005, 1), 1) * 0.45)
    out["Momentum AI"] = _specialist("Momentum AI", momentum, f"RSI {rsi:.1f}; MACD spread {macd_delta:.2f}")

    volume_z = safe_float(last["volume_z"], 0.0)
    candle_dir = np.sign(last["close"] - last["open"])
    volume_score = clamp(candle_dir * min(abs(volume_z) / 2.5, 1.0))
    out["Volume AI"] = _specialist("Volume AI", volume_score, f"Volume z-score {volume_z:.2f}")

    body = last["close"] - last["open"]
    rng = max(last["high"] - last["low"], 1e-9)
    prev_body = prev["close"] - prev["open"]
    engulf = 0.0
    if body > 0 and prev_body < 0 and last["close"] >= prev["open"] and last["open"] <= prev["close"]:
        engulf = 1.0
    elif body < 0 and prev_body > 0 and last["open"] >= prev["close"] and last["close"] <= prev["open"]:
        engulf = -1.0
    pattern_score = clamp(0.55 * (body / rng) + 0.45 * engulf)
    out["Pattern AI"] = _specialist("Pattern AI", pattern_score, "Candle body/engulfing structure")

    support = safe_float(hist["low"].tail(60).min(), px)
    resistance = safe_float(hist["high"].tail(60).max(), px)
    span = max(resistance - support, px * 0.001)
    location = (px - support) / span
    sr_score = clamp((0.5 - location) * 1.4)
    out["Support/Resistance AI"] = _specialist("Support/Resistance AI", sr_score, f"Support ${support:,.0f}; resistance ${resistance:,.0f}")

    atr_pct = safe_float(last["atr14"] / px, 0.0)
    bb_mid = safe_float(last["sma20"], px)
    stretch = (px - bb_mid) / max(safe_float(last["std20"], px * 0.001), px * 0.001)
    vol_score = clamp(-stretch / 3.0) if atr_pct > 0.0015 else clamp(np.sign(last["ema9"] - last["ema21"]) * 0.25)
    out["Volatility AI"] = _specialist("Volatility AI", vol_score, f"ATR {atr_pct*100:.3f}% of price; BB stretch {stretch:.2f}")

    ema_spread = abs(last["ema9"] - last["ema50"]) / px
    regime_dir = np.sign(last["ema9"] - last["ema50"])
    regime_score = clamp(regime_dir * min(ema_spread / 0.003, 1.0))
    out["Market Regime AI"] = _specialist("Market Regime AI", regime_score, "Trend regime from EMA separation")

    if agg is not None and not agg.empty:
        buy = agg.loc[agg["aggressor"] == "BUY", "notional"].sum()
        sell = agg.loc[agg["aggressor"] == "SELL", "notional"].sum()
        total = buy + sell
        flow = (buy - sell) / total if total else 0.0
        med = agg["notional"].median()
        whales = agg[agg["notional"] >= max(med * 6, 50_000)]
        whale_buy = whales.loc[whales["aggressor"] == "BUY", "notional"].sum()
        whale_sell = whales.loc[whales["aggressor"] == "SELL", "notional"].sum()
        whale_total = whale_buy + whale_sell
        whale_flow = (whale_buy - whale_sell) / whale_total if whale_total else flow
        whale_score = clamp(0.55 * flow * 3 + 0.45 * whale_flow * 3)
        whale_reason = f"Aggressor flow {flow*100:+.1f}%; large-trade flow {whale_flow*100:+.1f}%"
    else:
        whale_score, whale_reason = 0.0, "Aggregate trade feed unavailable"
    out["Whale AI"] = _specialist("Whale AI", whale_score, whale_reason)

    book = safe_float((futures or {}).get("book_imbalance", 0.0), 0.0)
    out["Liquidity AI"] = _specialist("Liquidity AI", clamp(book * 3), f"Futures top-book imbalance {book*100:+.1f}%")

    funding = safe_float((futures or {}).get("funding_rate"), 0.0)
    deriv_score = clamp(book * 1.6 - np.sign(funding) * min(abs(funding) / 0.0005, 1.0) * 0.25)
    out["Derivatives AI"] = _specialist("Derivatives AI", deriv_score, f"Funding {funding*100:.4f}%; OI {safe_float((futures or {}).get('open_interest'), 0):,.0f} BTC")

    if kctx and kctx.get("available"):
        probability = safe_float(kctx.get("up_probability"))
        market_score = clamp((probability - 0.5) * 2.0) if pd.notna(probability) else 0.0
        target = safe_float(kctx.get("target"))
        distance = px - target if pd.notna(target) else np.nan
        distance_pct = distance / target if pd.notna(distance) and target else np.nan
        target_distance_score = clamp((px - target) / max(px * 0.0025, 1.0)) if pd.notna(target) else 0.0
        context_score = clamp(0.55 * market_score + 0.45 * target_distance_score)
        context_reason = (
            f"Kalshi target ${target:,.2f}; BTC {distance:+,.2f} ({distance_pct*100:+.3f}%) vs target; "
            + (f"UP market ~{probability*100:.1f}%" if pd.notna(probability) else "UP market price unavailable")
        )
    else:
        context_score = 0.0
        context_reason = "Live KXBTC15M target unavailable"
    out["Kalshi Context AI"] = _specialist("Kalshi Context AI", context_score, context_reason)

    recent3 = safe_float((hist["close"].iloc[-1] / hist["close"].iloc[-4] - 1), 0.0) if len(hist) >= 4 else 0.0
    hist_score = clamp(np.sign(recent3) * min(abs(recent3) / 0.003, 1.0) * 0.5)
    out["Historical Pattern AI"] = _specialist("Historical Pattern AI", hist_score, f"Recent 3-minute move {recent3*100:+.3f}%")

    base_names = list(out.keys())
    base_scores = np.array([out[k]["score"] for k in base_names], dtype=float)
    agreement = abs(np.mean(np.sign(base_scores))) if len(base_scores) else 0.0
    combo = clamp(np.mean(base_scores) * (0.8 + 0.5 * agreement)) if len(base_scores) else 0.0
    out["Combination AI"] = _specialist("Combination AI", combo, f"Cross-specialist directional agreement {agreement*100:.0f}%")
    return out


def model_inputs_from_rows_core(rows, target=None):
    closes = np.asarray([float(r["close"]) for r in rows], dtype=float)
    if len(closes) < 16:
        return None
    last = float(closes[-1])
    ret3 = last / float(closes[-4]) - 1.0
    ret8 = last / float(closes[-9]) - 1.0
    ret15 = last / float(closes[-16]) - 1.0
    recent = rows[-20:]
    ranges = [max(0.0, float(r["high"]) - float(r["low"])) for r in recent]
    avg_range = float(np.mean(ranges)) if ranges else max(last * 0.0005, 1.0)
    return {"last": last, "ret3": ret3, "ret8": ret8, "ret15": ret15, "avg_range": avg_range, "target": safe_float(target)}


def forecast_path_core(rows, target=None, state=None):
    state = state or {}
    defaults = {"w_ret3":0.46,"w_ret8":0.34,"w_ret15":0.20,"momentum_scale":2.20,"target_influence":0.18,"bias":0.0}
    cfg = {k: safe_float(state.get(k), v) for k, v in defaults.items()}
    inputs = model_inputs_from_rows_core(rows, target)
    if not inputs:
        return None
    last = inputs["last"]
    avg_range = inputs["avg_range"]
    directional = cfg["w_ret3"]*inputs["ret3"] + cfg["w_ret8"]*inputs["ret8"] + cfg["w_ret15"]*inputs["ret15"] + cfg["bias"]
    directional = float(np.clip(directional, -0.012, 0.012))
    projected_move = last * directional * cfg["momentum_scale"]
    if pd.notna(inputs["target"]):
        gap = inputs["target"] - last
        max_influence = max(avg_range * 2.0, last * 0.0015)
        projected_move += float(np.clip(gap * cfg["target_influence"], -max_influence, max_influence))
    min_visible = max(avg_range * 0.35, last * 0.00015)
    if abs(projected_move) < min_visible:
        projected_move = np.sign(projected_move or directional or 1.0) * min_visible
    forecast = []
    prev_close = last
    for i in range(1,16):
        progress = i/15.0
        eased = progress*progress*(3.0-2.0*progress)
        center = last + projected_move*eased
        wave = np.sin(i*1.35)*avg_range*0.16 + np.cos(i*0.72)*avg_range*0.08
        close = float(center + wave)
        open_ = float(prev_close)
        body = abs(close-open_)
        wick = max(avg_range*(0.18+0.08*progress), body*0.35)
        forecast.append({"step":i,"open":open_,"high":max(open_,close)+wick,"low":min(open_,close)-wick,"close":close})
        prev_close = close
    return {"inputs":inputs,"forecast":forecast,"predicted_end":float(forecast[-1]["close"]),"predicted_direction":1 if forecast[-1]["close"] >= last else -1}
