"""Paper-trading profitability analytics for BTC AI v5.

Uses resolved prediction/paper outcomes to measure expectancy, profit factor,
precision, drawdown proxy, and confidence-bucket performance. Evaluation only;
no live order execution is implemented here.

This module also installs a deliberately narrow Streamlit presentation adapter.
The adapter does not place trades or alter the trading engine. It keeps the main
BTC dashboard aligned with the authoritative paper-trading state by:

* replacing the old ``Spot feed`` metric with the latest Kalshi call entry;
* replacing the main ``24h`` BTC-change metric with lifetime directional-call accuracy; and
* rendering ``HOLD SCALP UP/DOWN`` when the existing paper engine says that a
  fresh scalp no longer meets its profitability / projected-return target.

The HOLD display is intentionally independent of the separate 75% automatic
entry cap. That cap can still protect execution, but it does not decide whether
the directional recommendation is shown as HOLD SCALP.
"""
from __future__ import annotations

import math
import os
import sqlite3
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
            wins += 1; gross_win += r
        else:
            losses += 1; gross_loss += abs(r)
        equity *= max(0.01, 1.0 + r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        conf = _f(row.get("confidence"), 0.0)
        if conf <= 1.0: conf *= 100.0
        lo = int(max(0, min(90, conf // 10 * 10)))
        key = f"{lo:02d}-{lo+9:02d}%"
        b = buckets[key]; b["n"] += 1; b["wins"] += int(r > 0); b["sum"] += r
    n = len(net)
    win_rate = wins / n if n else None
    avg_win = gross_win / wins if wins else 0.0
    avg_loss = gross_loss / losses if losses else 0.0
    expectancy = (win_rate * avg_win - (1.0 - win_rate) * avg_loss) if win_rate is not None else None
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else None)
    bucket_out = [{"confidence_bucket": key, "samples": b["n"], "win_rate": b["wins"] / b["n"] if b["n"] else None, "avg_net_return": b["sum"] / b["n"] if b["n"] else None} for key, b in sorted(buckets.items())]
    return {"samples": n, "wins": wins, "losses": losses, "win_rate": win_rate, "avg_win": avg_win, "avg_loss": avg_loss, "expectancy": expectancy, "profit_factor": profit_factor, "total_compounded_return": equity - 1.0 if n else None, "max_drawdown_proxy": max_dd if n else None, "simulated_cost_bps": float(cost_bps), "confidence_buckets": bucket_out}


def profitability_gate(metrics, min_samples=30):
    """Require both precision and positive expectancy before loosening trade filters."""
    m = metrics or {}; n = int(_f(m.get("samples"), 0))
    if n < min_samples: return False, f"LEARNING — {n}/{min_samples} resolved trade samples"
    wr = m.get("win_rate"); exp = m.get("expectancy"); pf = m.get("profit_factor")
    if wr is None or exp is None: return False, "WAIT — incomplete profitability evidence"
    if _f(exp, -1.0) <= 0: return False, "WAIT — net expectancy is not positive after simulated costs"
    if pf is not None and math.isfinite(_f(pf, 0.0)) and _f(pf, 0.0) < 1.25: return False, f"WAIT — profit factor {_f(pf):.2f} < 1.25"
    if _f(wr, 0.0) < 0.58: return False, f"WAIT — trade win rate {_f(wr):.1%} < 58%"
    return True, "PROFITABILITY GATE PASSED"


_DEFAULT_DB_PATH = "btc_ai_command_center.db"

def _db_path():
    return os.environ.get("BTC_AI_DB_PATH", _DEFAULT_DB_PATH)


def lifetime_directional_accuracy(db_path=None):
    """Lifetime resolved SCALP/LOCK W/L accuracy; HOLD/WAIT excluded."""
    path = db_path or _db_path()
    if not os.path.exists(path): return None, 0, 0
    try:
        with sqlite3.connect(path, timeout=1.0) as conn:
            row = conn.execute("""SELECT SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END), SUM(CASE WHEN correct=0 THEN 1 ELSE 0 END) FROM predictions WHERE resolved=1 AND correct IS NOT NULL AND UPPER(TRIM(action)) IN ('SCALP UP','SCALP DOWN','LOCK UP','LOCK DOWN')""").fetchone()
        wins = int((row[0] if row else 0) or 0); losses = int((row[1] if row else 0) or 0); total = wins + losses
        return ((wins / total) if total else None), wins, losses
    except Exception:
        return None, 0, 0


def latest_kalshi_call_entry(db_path=None):
    path = db_path or _db_path()
    if not os.path.exists(path): return None, None
    try:
        with sqlite3.connect(path, timeout=1.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT side, entry_price FROM kalshi_paper_positions WHERE entry_price IS NOT NULL ORDER BY opened_at DESC, id DESC LIMIT 1").fetchone()
        if not row: return None, None
        price = float(row["entry_price"])
        if not math.isfinite(price): return None, None
        if price > 1.0: price /= 100.0
        return max(0.0, min(1.0, price)), str(row["side"] or "").upper().strip() or None
    except Exception:
        return None, None


def _walk_values(value, depth=0):
    if depth > 5: return
    if isinstance(value, dict):
        for item in value.values():
            yield item; yield from _walk_values(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield item; yield from _walk_values(item, depth + 1)


def _profitability_hold_active(st_module):
    try:
        values = []
        for value in st_module.session_state.values():
            values.append(value); values.extend(_walk_values(value))
        for value in values:
            if isinstance(value, str):
                text = value.upper()
                if "SKIPPED PAPER SCALP" in text and "PROJECTED EXIT" in text and "GROSS-RETURN TARGET" in text:
                    return True
    except Exception:
        pass
    return False


def _install_dashboard_adapter():
    try:
        import streamlit as st
        from streamlit.delta_generator import DeltaGenerator
    except Exception:
        return
    if getattr(DeltaGenerator, "_btc_profitability_dashboard_adapter", False): return
    original_metric = DeltaGenerator.metric; original_markdown = DeltaGenerator.markdown

    def metric_adapter(self, label, value, *args, **kwargs):
        label_text = str(label or "")
        if label_text.strip().lower() == "spot feed":
            entry, side = latest_kalshi_call_entry()
            if entry is None: return original_metric(self, "Kalshi Call Entry", "N/A", *args, **kwargs)
            side_text = f" {side}" if side else ""
            return original_metric(self, "Kalshi Call Entry", f"{entry * 100:.0f}% / {entry * 100:.0f}c{side_text}", *args, **kwargs)
        normalized = label_text.strip().lower().replace("-", " ")
        # The visible main-page box is literally labeled "24h" in app.py.
        if normalized in {"24h", "24 h", "24h quote volume", "24 h quote volume", "24h volume"}:
            accuracy, wins, losses = lifetime_directional_accuracy()
            shown = "N/A" if accuracy is None else f"{accuracy * 100:.1f}%"
            if kwargs.get("help") is None:
                kwargs["help"] = f"Lifetime resolved directional calls: {wins} wins, {losses} losses. HOLD/WAIT excluded from win/loss accuracy."
            return original_metric(self, "Lifetime Accuracy", shown, *args, **kwargs)
        return original_metric(self, label, value, *args, **kwargs)

    def markdown_adapter(self, body, *args, **kwargs):
        rendered = body
        if isinstance(rendered, str) and _profitability_hold_active(st):
            rendered = rendered.replace(">SCALP UP<", ">HOLD SCALP UP<").replace(">SCALP DOWN<", ">HOLD SCALP DOWN<")
        return original_markdown(self, rendered, *args, **kwargs)

    DeltaGenerator.metric = metric_adapter; DeltaGenerator.markdown = markdown_adapter
    DeltaGenerator._btc_profitability_dashboard_adapter = True


_install_dashboard_adapter()
