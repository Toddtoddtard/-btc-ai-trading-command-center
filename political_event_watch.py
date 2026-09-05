import json
import math
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

STATE_URL = "https://raw.githubusercontent.com/Toddtoddtard/-btc-ai-trading-command-center/learning-state/political_event_watch.json"
_CACHE = {"ts": 0.0, "state": None}


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def load_political_event_state(ttl=20.0):
    now = time.time()
    if _CACHE["state"] is not None and now - _CACHE["ts"] < ttl:
        return _CACHE["state"]
    try:
        req = Request(STATE_URL, headers={"User-Agent": "BTC-AI-Political-Watch/1.0", "Cache-Control": "no-cache"})
        with urlopen(req, timeout=2.5) as response:
            state = json.loads(response.read().decode("utf-8"))
        generated = state.get("generated_at")
        if generated:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(generated.replace("Z", "+00:00"))).total_seconds()
        else:
            age = 10**9
        state["state_age_seconds"] = age
        if age > 1800:
            state["active"] = False
            state["status"] = "STALE"
        _CACHE.update(ts=now, state=state)
        return state
    except Exception as exc:
        state = {
            "active": False,
            "status": "SOURCE UNAVAILABLE",
            "impact_score": 0.0,
            "direction_score": 0.0,
            "confidence": 0.0,
            "reason": f"Political watch state unavailable: {str(exc)[:120]}",
            "events": [],
        }
        _CACHE.update(ts=now, state=state)
        return state


def political_specialist_result(hist):
    """Return an event-driven specialist result for live BTC only.

    Historical/backtest timestamps never consume current political news. The bot has
    zero score and zero council influence whenever no qualifying event is active.
    """
    try:
        last_ts = hist.iloc[-1].get("time")
        if last_ts is not None:
            ts = last_ts.to_pydatetime() if hasattr(last_ts, "to_pydatetime") else last_ts
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if abs((datetime.now(timezone.utc) - ts).total_seconds()) > 900:
                return {
                    "name": "Political Event Watch AI",
                    "signal": "NEUTRAL",
                    "score": 0.0,
                    "confidence": 0.0,
                    "reason": "Inactive during historical/backtest data",
                    "event_status": "INACTIVE",
                }
    except Exception:
        pass

    state = load_political_event_state()
    active = bool(state.get("active"))
    score = max(-1.0, min(1.0, _safe_float(state.get("direction_score"), 0.0))) if active else 0.0
    confidence = max(0.0, min(0.95, _safe_float(state.get("confidence"), 0.0))) if active else 0.0
    if active and score > 0.12:
        signal = "BULLISH"
    elif active and score < -0.12:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"
    reason = state.get("reason") or ("Qualifying political market event active" if active else "No qualifying political event active")
    status = state.get("status") or ("ACTIVE" if active else "INACTIVE")
    return {
        "name": "Political Event Watch AI",
        "signal": signal,
        "score": score,
        "confidence": confidence,
        "reason": f"{status}: {reason}",
        "event_status": status,
        "impact_score": _safe_float(state.get("impact_score"), 0.0),
        "events": state.get("events") or [],
    }
