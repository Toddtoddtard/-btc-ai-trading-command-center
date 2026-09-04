"""Paper-trading profitability analytics for BTC AI v5.

Uses resolved prediction/paper outcomes to measure expectancy, profit factor,
precision, drawdown proxy, and confidence-bucket performance. Evaluation only;
no live order execution is implemented here.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np


def _f(x, default=0.0):
    try:
        x = float(x)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def trade_return_from_row(row, cost_bps=6.5):
    """Convert a resolved directional call to net return after simulated costs."""
    action = str(row.get("action", "")).upper()
    raw = _f(row.get("return_pct"), 0.0) / 100.0
    if action in {"SCALP DOWN", "LOCK DOWN"}:
        raw = -raw
    elif action not in {"SCALP UP", "LOCK UP"}:
        return None
    return raw - float(cost_bps) / 10000.0


def summarize_trades(rows, cost_bps=6.5):
    net = []
    wins = losses = 0
    gross_win = gross_loss = 0.0
    equity = peak = 1.0
    max_dd = 0.0
    buckets = defaultdict(lambda: {"n": 0, "wins": 0, "sum": 0.0})

    for row in rows or []:
        if not bool(row.get("resolved", 1)):
            continue
        r = trade_return_from_row(row, cost_bps)
        if r is None:
            continue
        net.append(r)
        if r > 0:
            wins += 1
            gross_win += r
        else:
            losses += 1
            gross_loss += abs(r)
        equity *= max(0.01, 1.0 + r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)

        conf = _f(row.get("confidence"), 0.0)
        if conf <= 1.0:
            conf *= 100.0
        lo = int(max(0, min(90, conf // 10 * 10)))
        key = f"{lo:02d}-{lo+9:02d}%"
        b = buckets[key]
        b["n"] += 1
        b["wins"] += int(r > 0)
        b["sum"] += r

    n = len(net)
    win_rate = wins / n if n else None
    avg_win = gross_win / wins if wins else 0.0
    avg_loss = gross_loss / losses if losses else 0.0
    expectancy = (win_rate * avg_win - (1.0 - win_rate) * avg_loss) if win_rate is not None else None
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    bucket_out = []
    for key, b in sorted(buckets.items()):
        bucket_out.append({
            "confidence_bucket": key,
            "samples": b["n"],
            "win_rate": b["wins"] / b["n"] if b["n"] else None,
            "avg_net_return": b["sum"] / b["n"] if b["n"] else None,
        })

    return {
        "samples": n,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "total_compounded_return": equity - 1.0 if n else None,
        "max_drawdown_proxy": max_dd if n else None,
        "simulated_cost_bps": float(cost_bps),
        "confidence_buckets": bucket_out,
    }


def profitability_gate(metrics, min_samples=30):
    """Require both precision and positive expectancy before loosening trade filters."""
    m = metrics or {}
    n = int(_f(m.get("samples"), 0))
    if n < min_samples:
        return False, f"LEARNING — {n}/{min_samples} resolved trade samples"
    wr = m.get("win_rate")
    exp = m.get("expectancy")
    pf = m.get("profit_factor")
    if wr is None or exp is None:
        return False, "WAIT — incomplete profitability evidence"
    if _f(exp, -1.0) <= 0:
        return False, "WAIT — net expectancy is not positive after simulated costs"
    if pf is not None and math.isfinite(_f(pf, 0.0)) and _f(pf, 0.0) < 1.25:
        return False, f"WAIT — profit factor {_f(pf):.2f} < 1.25"
    if _f(wr, 0.0) < 0.58:
        return False, f"WAIT — trade win rate {_f(wr):.1%} < 58%"
    return True, "PROFITABILITY GATE PASSED"
