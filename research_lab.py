"""Paper-only research instrumentation for KXBTC15M decisions.

This module never places orders and never changes the production execution gate.
It records one shadow observation per contract and grades it only from Kalshi's
official binary result so candidate policies can be compared safely.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from kalshi_paper_engine import kalshi_taker_fee


POLICIES = (
    {"name": "Value 70 / 5", "max_entry": 0.70, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Current 75 / 5", "max_entry": 0.75, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Explore 80 / 5", "max_entry": 0.80, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Selective 75 / 10", "max_entry": 0.75, "min_edge": 0.10, "min_confidence": 0.65},
)


def _f(value, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _iso(ts):
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def window_phase(opened_at, expires_at):
    lead = max(0.0, _f(expires_at, 0.0) - _f(opened_at, 0.0))
    if lead <= 120:
        return "FINAL 2"
    if lead <= 300:
        return "FINAL 5"
    if lead <= 600:
        return "MIDDLE"
    return "OPEN"


def ensure_research_lab(state):
    lab = state.setdefault("research_lab", {})
    lab.setdefault("version", 1)
    lab.setdefault("paper_only", True)
    lab.setdefault("affects_execution", False)
    lab.setdefault("pending", [])
    lab.setdefault("history", [])
    lab.setdefault("calibration", {"samples": 0, "model_brier": None, "market_brier": None})
    lab.setdefault("wait_counterfactual", {"samples": 0, "avoided_losses": 0, "missed_wins": 0, "net_if_traded": 0.0})
    lab.setdefault("phases", {})
    lab.setdefault("policies", {p["name"]: {**p, "samples": 0, "wins": 0, "net_pnl": 0.0} for p in POLICIES})
    lab.setdefault("specialist_lifecycle", {})
    return lab


def enrich_rationales(results):
    """Add auditable evidence, counterargument and invalidation to every seat."""
    results = results or {}
    for name, row in results.items():
        score = _f((row or {}).get("score"), 0.0)
        opponents = [
            other for other_name, other in results.items()
            if other_name != name and _f((other or {}).get("score"), 0.0) * score < 0
        ]
        opponent = max(opponents, key=lambda x: abs(_f(x.get("score"), 0.0)), default=None)
        row["evidence"] = str(row.get("reason") or "No evidence supplied")
        row["counterargument"] = (
            str(opponent.get("reason") or "Opposing signal detected")
            if opponent else "No material opposing specialist signal in this snapshot"
        )
        row["invalidation"] = (
            "Re-evaluate if the next market-data snapshot removes or reverses the cited evidence"
        )
    return results


def _yes_probability(pending):
    base = max(-1.0, min(1.0, _f(pending.get("master_base_score"), 0.0)))
    return max(0.01, min(0.99, 0.5 + 0.49 * base))


def register_shadow(state, pending, market_info):
    if not pending or not market_info:
        return False
    lab = ensure_research_lab(state)
    ticker = str(pending.get("ticker") or "")
    opened_at = _f(pending.get("opened_at"), 0.0)
    expires_at = _f(pending.get("expires_at"), opened_at)
    phase_name = window_phase(opened_at, expires_at)
    if not ticker or any(
        str(x.get("ticker")) == ticker and str(x.get("phase")) == phase_name
        for x in lab["pending"] + lab["history"]
    ):
        return False
    yes_bid = _f(market_info.get("yes_bid"))
    yes_ask = _f(market_info.get("yes_ask"))
    if yes_bid is None or yes_ask is None:
        return False
    no_ask = _f(market_info.get("no_ask"), 1.0 - yes_bid)
    model_yes = _yes_probability(pending)
    direction = "YES" if model_yes >= 0.5 else "NO"
    side_probability = model_yes if direction == "YES" else 1.0 - model_yes
    ask = yes_ask if direction == "YES" else no_ask
    action = str(pending.get("master_action") or "WAIT").upper()
    policies = {}
    confidence = _f(pending.get("master_confidence"), 0.5)
    for policy in POLICIES:
        eligible = bool(
            ask is not None
            and ask <= policy["max_entry"]
            and side_probability >= ask * (1.0 + policy["min_edge"])
            and confidence >= policy["min_confidence"]
        )
        policies[policy["name"]] = {"eligible": eligible}
    lab["pending"].append({
        "ticker": ticker,
        "opened_at": opened_at,
        "opened_at_utc": _iso(opened_at),
        "expires_at": expires_at,
        "expires_at_utc": _iso(expires_at),
        "phase": phase_name,
        "action": action,
        "direction": direction,
        "confidence": confidence,
        "model_yes_probability": model_yes,
        "market_yes_probability": max(0.01, min(0.99, (yes_bid + yes_ask) / 2.0)),
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "selected_ask": ask,
        "policies": policies,
    })
    lab["pending"] = lab["pending"][-200:]
    return True


def _running_average(old, value, n):
    return value if n == 1 or old is None else old + (value - old) / n


def resolve_shadows(state, result_reader):
    lab = ensure_research_lab(state)
    unresolved = []
    resolved = 0
    for row in lab["pending"]:
        result = str(result_reader(row["ticker"]) or "").lower()
        if result not in {"yes", "no"}:
            unresolved.append(row)
            continue
        outcome = 1.0 if result == "yes" else 0.0
        model_brier = (row["model_yes_probability"] - outcome) ** 2
        market_brier = (row["market_yes_probability"] - outcome) ** 2
        calibration = lab["calibration"]
        calibration["samples"] += 1
        n = calibration["samples"]
        calibration["model_brier"] = _running_average(calibration.get("model_brier"), model_brier, n)
        calibration["market_brier"] = _running_average(calibration.get("market_brier"), market_brier, n)
        calibration["model_edge_vs_market"] = calibration["market_brier"] - calibration["model_brier"]

        won = row["direction"].lower() == result
        ask = _f(row.get("selected_ask"), 1.0)
        pnl = (1.0 if won else 0.0) - ask - kalshi_taker_fee(1, ask)
        phase = lab["phases"].setdefault(row["phase"], {"samples": 0, "wins": 0, "net_pnl": 0.0})
        phase["samples"] += 1
        phase["wins"] += int(won)
        phase["net_pnl"] += pnl

        if row["action"] in {"WAIT", "HOLD"}:
            wait = lab["wait_counterfactual"]
            wait["samples"] += 1
            wait["avoided_losses"] += int(pnl < 0)
            wait["missed_wins"] += int(pnl > 0)
            wait["net_if_traded"] += pnl

        for name, decision in row.get("policies", {}).items():
            if not decision.get("eligible"):
                continue
            bucket = lab["policies"].setdefault(name, {"samples": 0, "wins": 0, "net_pnl": 0.0})
            bucket["samples"] += 1
            bucket["wins"] += int(won)
            bucket["net_pnl"] += pnl
        row.update({"result": result, "won": won, "paper_pnl": pnl, "model_brier": model_brier, "market_brier": market_brier})
        lab["history"].append(row)
        resolved += 1
    lab["pending"] = unresolved[-200:]
    lab["history"] = lab["history"][-1000:]
    return resolved


def update_lifecycles(state):
    lab = ensure_research_lab(state)
    lifecycle = {}
    for name, learned in (state.get("specialists") or {}).items():
        samples = int(learned.get("samples") or 0)
        accuracy = (int(learned.get("direction_hits") or 0) / samples) if samples else None
        brier = _f(learned.get("brier_ewma"), 0.25)
        if samples < 30:
            status, reason = "UNCALIBRATED", "Fewer than 30 directional samples"
        elif samples < 60:
            status, reason = "SHADOW", "Evidence is building; specialist remains active"
        elif samples >= 150 and accuracy < 0.43 and brier > 0.30:
            status, reason = "MUTED", "Persistent weak accuracy and calibration; advisory only"
        elif accuracy < 0.48 or brier > 0.29:
            status, reason = "BENCH", "Below live-quality threshold; continue shadow grading"
        else:
            status, reason = "LIVE", "Meets minimum sample, accuracy and calibration checks"
        lifecycle[name] = {
            "status": status, "samples": samples, "accuracy": accuracy,
            "brier": brier, "reason": reason, "affects_execution": False,
        }
    lab["specialist_lifecycle"] = lifecycle
    return lifecycle
