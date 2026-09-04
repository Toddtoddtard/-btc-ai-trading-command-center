"""BTC AI Council v4.

Centralizes specialist weighting, consensus, confidence, trade gating, and
leave-one-specialist-out contribution analysis.  This module is deliberately
pure: callers supply specialist results and learning state, which makes the
same council logic reusable by the live app, learner, and backtests.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from reliability_v31 import (
    calibrate_confidence,
    learned_policy,
    learned_trade_gate,
    regime_specialist_weight,
    source_health_from_specialists,
)

BASE_WEIGHTS = {
    "Trend AI": 1.10,
    "Momentum AI": 1.05,
    "Volume AI": 0.90,
    "Pattern AI": 0.72,
    "Support/Resistance AI": 0.92,
    "Volatility AI": 0.82,
    "Market Regime AI": 1.05,
    "Whale AI": 1.08,
    "Liquidity AI": 1.02,
    "Derivatives AI": 1.02,
    "Kalshi Context AI": 0.88,
    "Historical Pattern AI": 0.76,
}

# Combination AI is intentionally excluded from the source council so the
# system cannot double-count its own aggregate vote.
EXCLUDED_FROM_COUNCIL = {"Combination AI"}


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _specialist_state(state, name):
    state = state if isinstance(state, dict) else {}
    return (state.get("specialists", {}) or {}).get(name, {}) or {}


def specialist_weight(name, state=None, regime="UNKNOWN"):
    base = _safe_float(BASE_WEIGHTS.get(name), 0.75)
    return regime_specialist_weight(base, _specialist_state(state, name), regime or "UNKNOWN")


def council_vote(results, state=None, regime="UNKNOWN", exclude=None):
    """Return one authoritative weighted council decision.

    Scores are weighted by static domain importance, learned global reliability,
    regime-specific reliability, and each specialist's own confidence.
    """
    results = results or {}
    exclude = set(exclude or ()) | EXCLUDED_FROM_COUNCIL
    weighted_sum = 0.0
    denominator = 0.0
    directional_weight = 0.0
    directional_signed = 0.0
    members = []

    for name, item in results.items():
        if name in exclude or not isinstance(item, dict):
            continue
        score = float(np.clip(_safe_float(item.get("score"), 0.0), -1.0, 1.0))
        confidence = float(np.clip(_safe_float(item.get("confidence"), 0.5), 0.05, 0.99))
        weight = specialist_weight(name, state, regime)
        effective = weight * (0.45 + 0.55 * confidence)
        weighted_sum += score * effective
        denominator += effective
        if abs(score) >= 0.08:
            directional_weight += effective
            directional_signed += (1.0 if score > 0 else -1.0) * effective
        members.append({
            "name": name,
            "score": score,
            "confidence": confidence,
            "weight": weight,
            "effective_weight": effective,
        })

    base_score = weighted_sum / denominator if denominator else 0.0
    consensus = abs(directional_signed) / directional_weight if directional_weight else 0.0
    raw_confidence = float(np.clip(0.46 + abs(base_score) * 0.34 + consensus * 0.18, 0.40, 0.96))
    health = source_health_from_specialists(results)
    policy = learned_policy(state or {}, regime or "UNKNOWN")
    confidence = calibrate_confidence(raw_confidence, consensus, policy, health, state or {})

    if base_score >= policy["edge_floor"]:
        proposed = "SCALP UP"
    elif base_score <= -policy["edge_floor"]:
        proposed = "SCALP DOWN"
    else:
        proposed = "WAIT"

    allowed, gated_action = learned_trade_gate(
        proposed,
        confidence,
        base_score,
        consensus,
        policy,
        source_health=health,
    )
    action = gated_action if allowed else "WAIT"

    return {
        "action": action,
        "proposed_action": proposed,
        "base_score": float(base_score),
        "confidence": float(confidence),
        "raw_confidence": raw_confidence,
        "consensus": float(consensus),
        "source_health": float(health),
        "policy": policy,
        "members": members,
    }


def _direction(score):
    score = _safe_float(score, 0.0)
    if score > 0.03:
        return 1
    if score < -0.03:
        return -1
    return 0


def analyze_bot_contributions(state, min_samples=12):
    """Measure each bot's independent value using historical snapshots.

    For every graded prediction snapshot, score the complete council and then
    score it again with one specialist removed.  This exposes redundancy and
    harmful specialists instead of rewarding raw agreement alone.
    """
    state = state if isinstance(state, dict) else {}
    snapshots = state.get("prediction_snapshots", []) or []
    history = state.get("master_history", []) or []
    outcomes = {str(row.get("ticker")): row for row in history if row.get("ticker")}
    stats = defaultdict(lambda: {
        "samples": 0,
        "standalone_hits": 0,
        "standalone_calls": 0,
        "full_hits": 0,
        "without_hits": 0,
        "unique_saves": 0,
        "harmful_flips": 0,
        "score_abs_sum": 0.0,
    })
    evaluated = 0

    for snap in snapshots:
        ticker = str(snap.get("ticker") or "")
        outcome = outcomes.get(ticker)
        if not outcome or outcome.get("direction_correct") is None:
            continue
        specialists = ((snap.get("snapshot") or {}).get("specialists") or {})
        if not specialists:
            continue

        # master_history stores whether the production forecast direction hit.
        # For v4 contribution analysis we reconstruct actual direction from the
        # saved realized return when present, otherwise infer from the production hit.
        realized = outcome.get("realized_return")
        if realized is None:
            continue
        actual_dir = 1 if _safe_float(realized, 0.0) >= 0 else -1
        regime = str((snap.get("snapshot") or {}).get("regime") or "UNKNOWN")
        full = council_vote(specialists, state, regime)
        full_dir = _direction(full["base_score"])
        full_hit = int(full_dir != 0 and full_dir == actual_dir)
        evaluated += 1

        for name, call in specialists.items():
            if name in EXCLUDED_FROM_COUNCIL:
                continue
            st = stats[name]
            st["samples"] += 1
            call_dir = _direction((call or {}).get("score"))
            if call_dir:
                st["standalone_calls"] += 1
                st["standalone_hits"] += int(call_dir == actual_dir)
            st["score_abs_sum"] += abs(_safe_float((call or {}).get("score"), 0.0))
            st["full_hits"] += full_hit

            without = council_vote(specialists, state, regime, exclude={name})
            without_dir = _direction(without["base_score"])
            without_hit = int(without_dir != 0 and without_dir == actual_dir)
            st["without_hits"] += without_hit
            if full_hit and not without_hit:
                st["unique_saves"] += 1
            if (not full_hit) and without_hit:
                st["harmful_flips"] += 1

    ranking = []
    for name, st in stats.items():
        n = st["samples"]
        if n <= 0:
            continue
        standalone_acc = st["standalone_hits"] / st["standalone_calls"] if st["standalone_calls"] else None
        full_acc = st["full_hits"] / n
        without_acc = st["without_hits"] / n
        marginal = full_acc - without_acc
        saves = st["unique_saves"] / n
        harms = st["harmful_flips"] / n
        confidence_shrink = min(1.0, n / max(float(min_samples), 1.0))
        contribution_score = confidence_shrink * (marginal + 0.50 * saves - 0.65 * harms)
        if n < min_samples:
            verdict = "LEARNING"
        elif contribution_score >= 0.025:
            verdict = "HIGH VALUE"
        elif contribution_score <= -0.020:
            verdict = "HURTING COUNCIL"
        elif abs(marginal) < 0.005 and saves < 0.01:
            verdict = "REDUNDANT"
        else:
            verdict = "USEFUL"
        ranking.append({
            "name": name,
            "samples": n,
            "standalone_accuracy": standalone_acc,
            "full_council_accuracy": full_acc,
            "without_bot_accuracy": without_acc,
            "marginal_accuracy": marginal,
            "unique_save_rate": saves,
            "harmful_flip_rate": harms,
            "avg_abs_score": st["score_abs_sum"] / n,
            "contribution_score": contribution_score,
            "verdict": verdict,
        })

    ranking.sort(key=lambda row: (row["contribution_score"], row["samples"]), reverse=True)
    return {
        "version": 4,
        "evaluated_snapshots": evaluated,
        "minimum_samples_for_verdict": int(min_samples),
        "ranking": ranking,
    }
