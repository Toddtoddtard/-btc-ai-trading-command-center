import math
import numpy as np
import pandas as pd

from political_event_watch import political_specialist_result
from market_research import cross_market_research_result

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
    "FVG / MACD AI",
    "Political Event Watch AI",
    "Cross-Market Research AI",
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
    x["ret15"] = c.pct_change(15)
    x["ret60"] = c.pct_change(60)
    x["ret240"] = c.pct_change(240)
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema21"] = c.ewm(span=21, adjust=False).mean()
    x["ema50"] = c.ewm(span=50, adjust=False).mean()
    x["ema200"] = c.ewm(span=200, adjust=False).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = 100 - (100 / (1 + rs))
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["macd_hist"] = x["macd"] - x["macd_signal"]

    # Three-candle fair-value gaps (ICT-style imbalance zones).
    # Bullish FVG: current low is above the high from two candles ago.
    # Bearish FVG: current high is below the low from two candles ago.
    x["bull_fvg"] = x["low"] > x["high"].shift(2)
    x["bull_fvg_lower"] = np.where(x["bull_fvg"], x["high"].shift(2), np.nan)
    x["bull_fvg_upper"] = np.where(x["bull_fvg"], x["low"], np.nan)
    x["bear_fvg"] = x["high"] < x["low"].shift(2)
    x["bear_fvg_lower"] = np.where(x["bear_fvg"], x["high"], np.nan)
    x["bear_fvg_upper"] = np.where(x["bear_fvg"], x["low"].shift(2), np.nan)

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


def run_specialists_core(hist, agg, futures, kctx, research_snapshot=None):
    last = hist.iloc[-1]
    prev = hist.iloc[-2]
    px = float(last["close"])
    out = {}

    # Use EMA separation magnitude, not just sign. This prevents tiny low-volatility
    # EMA differences from producing a false +/-1 trend conviction.
    fast_spread = safe_float((last["ema9"] - last["ema21"]) / px, 0.0)
    slow_spread = safe_float((last["ema21"] - last["ema50"]) / px, 0.0)
    long_spread = safe_float((last["ema50"] - last.get("ema200", last["ema50"])) / px, 0.0)
    fast_component = math.tanh(fast_spread / 0.0010)
    slow_component = math.tanh(slow_spread / 0.0018)
    long_component = math.tanh(long_spread / 0.0045)
    hour_component = math.tanh(safe_float(last.get("ret60"), 0.0) / 0.0060)
    four_hour_component = math.tanh(safe_float(last.get("ret240"), 0.0) / 0.0120)
    short_trend = clamp(0.58 * fast_component + 0.42 * slow_component)
    higher_trend = clamp(0.50 * long_component + 0.30 * hour_component + 0.20 * four_hour_component)
    if abs(higher_trend) < 0.08:
        trend_score = clamp(0.78 * short_trend)
        alignment = "higher timeframe neutral"
    elif short_trend * higher_trend < 0:
        trend_score = clamp(0.35 * short_trend + 0.15 * higher_trend)
        alignment = "short/long conflict damped"
    else:
        trend_score = clamp(0.70 * short_trend + 0.30 * higher_trend)
        alignment = "short/long aligned"
    out["Trend AI"] = _specialist(
        "Trend AI",
        trend_score,
        (
            f"EMA9 {last['ema9']:.0f}, EMA21 {last['ema21']:.0f}, EMA50 {last['ema50']:.0f}, "
            f"EMA200 {safe_float(last.get('ema200'), px):.0f}; 1h {hour_component:+.2f}; "
            f"4h {four_hour_component:+.2f}; {alignment}"
        ),
    )

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

    ema_spread = safe_float((last["ema9"] - last["ema50"]) / px, 0.0)
    short_regime = math.tanh(ema_spread / 0.0030)
    regime_score = clamp(0.55 * short_regime + 0.45 * higher_trend)
    if short_regime * higher_trend < 0 and abs(higher_trend) >= 0.08:
        regime_score = clamp(regime_score * 0.45)
        regime_alignment = "conflicting timeframes"
    else:
        regime_alignment = "timeframes aligned/neutral"
    out["Market Regime AI"] = _specialist(
        "Market Regime AI",
        regime_score,
        f"Short regime {short_regime:+.2f}; higher-timeframe regime {higher_trend:+.2f}; {regime_alignment}",
    )

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

        # Sparse large prints used to create +/-1 scores and ~96% confidence. Blend
        # whale flow with broad aggressor flow and scale conviction by evidence size.
        whale_count = int(len(whales))
        sample_strength = min(1.0, whale_count / 8.0)
        participation = (whale_total / total) if total else 0.0
        participation_strength = min(1.0, participation / 0.20)
        evidence_strength = 0.5 * sample_strength + 0.5 * participation_strength
        raw_whale = 0.60 * clamp(flow * 2.0) + 0.40 * clamp(whale_flow * 2.0)
        whale_score = clamp(raw_whale * (0.40 + 0.60 * evidence_strength))
        whale_reason = (
            f"Aggressor flow {flow*100:+.1f}%; large-trade flow {whale_flow*100:+.1f}%; "
            f"large trades {whale_count}; evidence {evidence_strength*100:.0f}%"
        )
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
    recent15 = safe_float(last.get("ret15"), 0.0)
    recent60 = safe_float(last.get("ret60"), 0.0)
    move3 = math.tanh(recent3 / 0.0030)
    move15 = math.tanh(recent15 / 0.0060)
    move60 = math.tanh(recent60 / 0.0120)
    hist_score = clamp(0.35 * move3 + 0.35 * move15 + 0.30 * move60)
    out["Historical Pattern AI"] = _specialist(
        "Historical Pattern AI",
        hist_score,
        f"Multi-horizon move: 3m {recent3*100:+.3f}%, 15m {recent15*100:+.3f}%, 1h {recent60*100:+.3f}%",
    )

    # FVG / MACD Technical AI: combines price imbalance structure with
    # momentum confirmation. It is intentionally one council member rather
    # than a master override so live learning can raise/lower its influence.
    macd_hist = safe_float(last.get("macd_hist"), safe_float(last["macd"] - last["macd_signal"], 0.0))
    prev_macd = safe_float(prev["macd"], 0.0)
    prev_signal = safe_float(prev["macd_signal"], 0.0)
    now_macd = safe_float(last["macd"], 0.0)
    now_signal = safe_float(last["macd_signal"], 0.0)
    if now_macd > now_signal and prev_macd <= prev_signal:
        macd_cross = 1.0
        macd_state = "bullish cross"
    elif now_macd < now_signal and prev_macd >= prev_signal:
        macd_cross = -1.0
        macd_state = "bearish cross"
    elif macd_hist > 0:
        macd_cross = 0.35
        macd_state = "bullish histogram"
    elif macd_hist < 0:
        macd_cross = -0.35
        macd_state = "bearish histogram"
    else:
        macd_cross = 0.0
        macd_state = "flat"

    macd_strength = math.tanh(macd_hist / max(px * 0.00035, 1e-9))
    macd_score = clamp(0.65 * macd_strength + 0.35 * macd_cross)

    fvg_score = 0.0
    fvg_state = "no fresh FVG"
    lookback = hist.tail(60)
    candidates = []
    for age, (_, row) in enumerate(reversed(list(lookback.iterrows()))):
        decay = max(0.20, 1.0 - age / 60.0)
        if bool(row.get("bull_fvg", False)):
            lower = safe_float(row.get("bull_fvg_lower"))
            upper = safe_float(row.get("bull_fvg_upper"))
            if pd.notna(lower) and pd.notna(upper):
                if lower <= px <= upper:
                    state = f"inside bullish FVG ${lower:,.0f}-${upper:,.0f}"
                    score = 0.90 * decay
                elif px > upper:
                    state = f"bullish FVG support ${lower:,.0f}-${upper:,.0f}"
                    score = 0.62 * decay
                else:
                    state = f"bullish FVG filled ${lower:,.0f}-${upper:,.0f}"
                    score = 0.10 * decay
                candidates.append((age, score, state))
        if bool(row.get("bear_fvg", False)):
            lower = safe_float(row.get("bear_fvg_lower"))
            upper = safe_float(row.get("bear_fvg_upper"))
            if pd.notna(lower) and pd.notna(upper):
                if lower <= px <= upper:
                    state = f"inside bearish FVG ${lower:,.0f}-${upper:,.0f}"
                    score = -0.90 * decay
                elif px < lower:
                    state = f"bearish FVG resistance ${lower:,.0f}-${upper:,.0f}"
                    score = -0.62 * decay
                else:
                    state = f"bearish FVG filled ${lower:,.0f}-${upper:,.0f}"
                    score = -0.10 * decay
                candidates.append((age, score, state))

    if candidates:
        age, fvg_score, fvg_state = min(candidates, key=lambda item: item[0])
        fvg_state += f"; age {age}m"

    technical_score = clamp(0.55 * fvg_score + 0.45 * macd_score)
    technical_reason = (
        f"{fvg_state}; MACD {macd_state}; histogram {macd_hist:+.2f}; "
        f"FVG score {fvg_score:+.2f}; MACD score {macd_score:+.2f}"
    )
    out["FVG / MACD AI"] = _specialist("FVG / MACD AI", technical_score, technical_reason)

    base_names = list(out.keys())
    base_scores = np.array([out[k]["score"] for k in base_names], dtype=float)
    agreement = abs(np.mean(np.sign(base_scores))) if len(base_scores) else 0.0
    combo = clamp(np.mean(base_scores) * (0.8 + 0.5 * agreement)) if len(base_scores) else 0.0
    out["Combination AI"] = _specialist("Combination AI", combo, f"Cross-specialist directional agreement {agreement*100:.0f}%")

    # Event-driven specialist: zero score/confidence unless a fresh qualifying
    # political event is active. Added after Combination so an inactive watcher
    # cannot dilute or distort the normal technical specialist ensemble.
    out["Political Event Watch AI"] = political_specialist_result(hist)
    out["Cross-Market Research AI"] = cross_market_research_result(hist, research_snapshot)
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
    # The raw model move is the ONLY value used for grading, calibration,
    # backtests and champion/challenger evaluation.  Presentation helpers below
    # may make a near-flat path visible, but can never alter the scored target.
    raw_projected_move = float(projected_move)
    raw_predicted_end = float(last + raw_projected_move)
    raw_predicted_direction = 1 if raw_projected_move > 0 else -1 if raw_projected_move < 0 else 0

    # Chart-only presentation path.  A minimum visible move and small wave make
    # the forecast readable on screen without contaminating model evidence.
    display_move = raw_projected_move
    min_visible = max(avg_range * 0.35, last * 0.00015)
    if abs(display_move) < min_visible:
        display_move = np.sign(display_move or directional or 1.0) * min_visible
    forecast = []
    prev_close = last
    for i in range(1,16):
        progress = i/15.0
        eased = progress*progress*(3.0-2.0*progress)
        center = last + display_move*eased
        wave = np.sin(i*1.35)*avg_range*0.16 + np.cos(i*0.72)*avg_range*0.08
        close = float(center + wave)
        open_ = float(prev_close)
        body = abs(close-open_)
        wick = max(avg_range*(0.18+0.08*progress), body*0.35)
        forecast.append({"step":i,"open":open_,"high":max(open_,close)+wick,"low":min(open_,close)-wick,"close":close})
        prev_close = close
    return {
        "inputs": inputs,
        "forecast": forecast,
        "predicted_end": raw_predicted_end,
        "predicted_direction": raw_predicted_direction,
        "raw_projected_move": raw_projected_move,
        "display_predicted_end": float(forecast[-1]["close"]),
    }
