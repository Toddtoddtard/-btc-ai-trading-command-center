"""Persistent window journal; official outcomes only, independent of UI uptime.

Historical forecasts without a saved execution action remain FORECAST rows.
They must never be retroactively represented as SCALP/LOCK calls.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math
import time

SIGNALS = {"SCALP UP", "SCALP DOWN", "LOCK UP", "LOCK DOWN"}
WAITS = {"WAIT", "HOLD"}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def iso(value):
    value = number(value)
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def ensure_journal(state):
    """Recover retained real observations without inventing missed windows."""
    journal = state.setdefault("prediction_journal", {"version": 1, "rows": []})
    rows = journal.setdefault("rows", [])
    by_ticker = {r["ticker"]: r for r in rows}
    snapshots = {r.get("ticker"): r for r in state.get("prediction_snapshots", [])}
    histories = {r.get("ticker"): r for r in state.get("master_history", [])}
    for ticker in dict.fromkeys([*snapshots, *histories]):
        if not ticker or ticker in by_ticker:
            continue
        snap = snapshots.get(ticker, {})
        history = histories.get(ticker, {})
        detail = snap.get("snapshot") or {}
        # Old records did not persist the final execution action. Preserve
        # that uncertainty instead of deriving a trade from forecast accuracy.
        direction = number(history.get("predicted_settlement_direction"))
        action = "FORECAST UP" if direction == 1 else "FORECAST DOWN" if direction == -1 else "FORECAST"
        row = {
            "ticker": ticker, "opened_at": snap.get("opened_at"),
            "expires_at": history.get("expires_at", snap.get("expires_at")),
            "action": action, "confidence": history.get("master_confidence", detail.get("master_confidence")),
            "target_price": detail.get("target"), "price": detail.get("start_price"),
            "source": "retained background forecast", "resolved": False,
            "correct": None, "official_result": None,
        }
        rows.append(row)
        by_ticker[ticker] = row
    outcomes = {ticker: r.get("kalshi_result") for ticker, r in histories.items()}
    for row in rows:
        apply_result(row, outcomes.get(row["ticker"]))
    journal["version"] = 1
    return journal


def apply_result(row, result):
    result = str(result or "").lower()
    if result not in {"yes", "no"}:
        return False
    was_resolved = bool(row.get("resolved"))
    row.update(official_result=result, resolved=True, correct=None)
    action = row.get("action", "")
    if action in SIGNALS:
        row["correct"] = int((action.endswith("UP")) == (result == "yes"))
    return not was_resolved


def record_prediction(state, call, market, now=None):
    """Keep one row per market, promoting WAIT to its first signal/first LOCK."""
    now = time.time() if now is None else float(now)
    journal = ensure_journal(state)
    if not isinstance(call, dict) or not call:
        return False
    call, market = call or {}, market or {}
    ticker = str(market.get("ticker") or call.get("ticker") or "")
    expiry = number(market.get("expires_at", call.get("expires_at")))
    if not ticker or expiry is None or now >= expiry:
        return False
    action = str(call.get("master_action") or "WAIT").upper()
    if action not in SIGNALS | WAITS:
        action = "WAIT"
    row = next((r for r in journal["rows"] if r["ticker"] == ticker), None)
    if row is not None:
        old = row.get("action", "")
        if row.get("resolved") or old.startswith("LOCK"):
            return False
        if old in SIGNALS and not action.startswith("LOCK"):
            return False
        if old in WAITS and action in WAITS:
            return False
    else:
        row = {"ticker": ticker, "first_observed_at": now}
        journal["rows"].append(row)
    focus = call.get("lock_focus") or {}
    row.update(
        opened_at=now, expires_at=expiry, action=action,
        confidence=number(call.get("master_confidence")),
        price=number(call.get("start_price")),
        target_price=number(market.get("target", call.get("target"))),
        consensus=number(focus.get("consensus")),
        rationale=str(call.get("execution_reason") or ""),
        source="background master call", resolved=False, correct=None,
        official_result=None,
    )
    return True


def resolve_journal(state, result_fetcher, now=None, max_requests=3):
    """Retry official results fairly; never substitute a later spot price."""
    now = time.time() if now is None else float(now)
    journal = ensure_journal(state)
    pending = [r for r in journal["rows"] if not r.get("resolved")
               and number(r.get("expires_at")) is not None and float(r["expires_at"]) <= now]
    pending.sort(key=lambda r: (number(r.get("last_result_check")) or 0, float(r["expires_at"])))
    resolved = 0
    for row in pending[:max_requests]:
        row["last_result_check"] = now
        try:
            result = result_fetcher(row["ticker"])
        except Exception:
            continue
        resolved += int(apply_result(row, result))
    return resolved


def journal_view(state):
    """A single snapshot supplies both metrics and table; no UI-local fallback."""
    if not isinstance(state, dict) or not state:
        return [], {"n": 0, "trade_resolved": 0, "wait_resolved": 0, "accuracy": None}
    # Read-only: cached state may also feed the execution/learning dashboard.
    journal = ensure_journal(deepcopy({key: state[key] for key in (
        "prediction_journal", "prediction_snapshots", "master_history"
    ) if key in state}))
    rows = sorted(journal["rows"], key=lambda r: number(r.get("expires_at")) or 0, reverse=True)
    signals = [r for r in rows if r.get("action") in SIGNALS and r.get("resolved")
               and r.get("official_result") in {"yes", "no"}]
    waits = [r for r in rows if r.get("action") in WAITS and r.get("resolved")]
    stats = {"n": len(rows), "trade_resolved": len(signals), "wait_resolved": len(waits),
             "accuracy": sum(r["correct"] for r in signals) / len(signals) if signals else None}
    view = [{
        "ticker": r["ticker"], "created_iso": iso(r.get("opened_at")),
        "action": r["action"], "confidence": r.get("confidence"),
        "target_price": r.get("target_price"), "closes_iso": iso(r.get("expires_at")),
        "resolved": int(bool(r.get("resolved"))), "correct": r.get("correct"),
        "official_result": r.get("official_result"), "source": r.get("source"),
    } for r in rows]
    return view, stats
