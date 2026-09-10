"""Curated, live-only cross-market research for the BTC specialist council.

Only fixed public market-data endpoints are queried.  No article text, links,
prompts, or executable content are accepted.  Historical callers are always
neutral so a current Internet response can never leak into a backtest.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
_CACHE = {"at": 0.0, "snapshot": None}


def _finite(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _get_json(base_url, params, timeout=6):
    # The caller can only select one of these exact hosts/paths.  This prevents
    # fetched content from redirecting the bot toward arbitrary web resources.
    if base_url not in {COINBASE_CANDLES, KRAKEN_OHLC}:
        raise ValueError("market-research URL is not allowlisted")
    req = Request(
        base_url + "?" + urlencode(params),
        headers={"User-Agent": "BTC-AI-Cross-Market-Research/1.0", "Accept": "application/json"},
    )
    with urlopen(req, timeout=timeout) as response:
        if response.geturl().split("?", 1)[0] != base_url:
            raise ValueError("market-research redirect rejected")
        return json.loads(response.read(1_000_001).decode("utf-8"))


def _return_from_rows(rows, timestamp_index, close_index, now_ts, drop_last=False):
    parsed = []
    for row in rows or []:
        try:
            ts = int(float(row[timestamp_index]))
            close = _finite(row[close_index])
            # One-minute buckets are identified by their opening timestamp;
            # only use buckets whose close is already in the past.
            if close and close > 0 and ts + 60 <= now_ts:
                parsed.append((ts, close))
        except Exception:
            continue
    parsed.sort()
    if drop_last and parsed:
        parsed = parsed[:-1]  # Kraken documents its final candle as uncommitted.
    if len(parsed) < 6:
        raise ValueError("fewer than six completed one-minute candles")
    latest_ts, latest = parsed[-1]
    if now_ts - latest_ts > 180:
        raise ValueError("latest completed candle is stale")
    earlier = parsed[-6][1]
    return latest / earlier - 1.0, latest_ts, latest


def build_cross_market_snapshot(fetch_json=_get_json, now=None):
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    sources = {}
    health = {}

    try:
        start = datetime.fromtimestamp(now_ts - 12 * 60, tz=timezone.utc).isoformat()
        end = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
        payload = fetch_json(COINBASE_CANDLES, {"granularity": 60, "start": start, "end": end})
        ret, candle_ts, price = _return_from_rows(payload, 0, 4, now_ts)
        sources["coinbase"] = {"return_5m": ret, "candle_time": candle_ts, "price": price}
        health["coinbase"] = "OK"
    except Exception as exc:
        health["coinbase"] = f"UNAVAILABLE: {str(exc)[:100]}"

    try:
        payload = fetch_json(KRAKEN_OHLC, {"pair": "XBTUSD", "interval": 1, "since": now_ts - 12 * 60})
        errors = payload.get("error") or []
        if errors:
            raise ValueError(str(errors[0]))
        result = payload.get("result") or {}
        rows = next((value for key, value in result.items() if key != "last" and isinstance(value, list)), [])
        ret, candle_ts, price = _return_from_rows(rows, 0, 4, now_ts, drop_last=True)
        sources["kraken"] = {"return_5m": ret, "candle_time": candle_ts, "price": price}
        health["kraken"] = "OK"
    except Exception as exc:
        health["kraken"] = f"UNAVAILABLE: {str(exc)[:100]}"

    return {
        "version": 1,
        "generated_at": now.isoformat(),
        "sources": sources,
        "source_health": health,
        "policy": "Fixed official APIs only; live-only; two-source agreement required.",
    }


def load_cross_market_snapshot(ttl=300.0):
    now = time.time()
    if _CACHE["snapshot"] is None or now - _CACHE["at"] >= ttl:
        _CACHE.update(at=now, snapshot=build_cross_market_snapshot())
    return _CACHE["snapshot"]


def _is_live_history(hist, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        value = hist.iloc[-1].get("time")
        ts = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
        if ts is None:
            return False
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return abs((now - ts).total_seconds()) <= 900
    except Exception:
        return False


def cross_market_research_result(hist, snapshot=None, now=None):
    name = "Cross-Market Research AI"
    if not _is_live_history(hist, now=now):
        return {
            "name": name, "signal": "NEUTRAL", "score": 0.0, "confidence": 0.0,
            "reason": "Inactive during historical/backtest data", "research_status": "INACTIVE",
        }

    snapshot = snapshot if snapshot is not None else load_cross_market_snapshot()
    sources = snapshot.get("sources", {}) if isinstance(snapshot, dict) else {}
    returns = [_finite(row.get("return_5m")) for row in sources.values() if isinstance(row, dict)]
    returns = [value for value in returns if value is not None]
    if len(returns) < 2:
        return {
            "name": name, "signal": "NEUTRAL", "score": 0.0, "confidence": 0.0,
            "reason": "Waiting for both allowlisted exchange feeds", "research_status": "PARTIAL",
            "source_health": (snapshot or {}).get("source_health", {}),
        }

    signs_agree = returns[0] * returns[1] > 0
    spread = abs(returns[0] - returns[1])
    if not signs_agree or spread > 0.0035:
        score = 0.0
        status = "CONFLICT"
        reason = f"Independent venues disagree; Coinbase {returns[0]*100:+.3f}%, Kraken {returns[1]*100:+.3f}%"
    else:
        mean_return = sum(returns) / len(returns)
        # This is intentionally capped below a normal specialist's full vote.
        # Live outcome grading can raise or lower its adaptive weight over time.
        agreement = max(0.0, 1.0 - spread / 0.0035)
        score = max(-0.55, min(0.55, math.tanh(mean_return / 0.0030) * 0.55 * agreement))
        status = "ACTIVE"
        reason = f"Independent 5m confirmation; Coinbase {returns[0]*100:+.3f}%, Kraken {returns[1]*100:+.3f}%"

    signal = "BULLISH" if score > 0.12 else "BEARISH" if score < -0.12 else "NEUTRAL"
    confidence = min(0.72, 0.52 + abs(score) * 0.30) if status == "ACTIVE" else 0.0
    return {
        "name": name, "signal": signal, "score": float(score), "confidence": float(confidence),
        "reason": reason, "research_status": status,
        "source_health": (snapshot or {}).get("source_health", {}),
    }
