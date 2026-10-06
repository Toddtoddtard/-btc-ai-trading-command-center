"""BTC AI Council v4.

Centralizes specialist weighting, consensus, confidence, trade gating, and
leave-one-specialist-out contribution analysis. This module is deliberately
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
    "FVG / MACD AI": 0.92,
    # New Internet-derived hypotheses begin conservatively and must earn more
    # influence through the same live outcome grading as every other bot.
    "Cross-Market Research AI": 0.58,
}

# Combination AI is intentionally excluded from the source council so the
# system cannot double-count its own aggregate vote.
EXCLUDED_FROM_COUNCIL = {"Combination AI"}


def specialist_active(name, item):
    """Abstention keeps a specialist available without diluting today's vote."""
    if name in EXCLUDED_FROM_COUNCIL or not isinstance(item, dict):
        return False
    if name == "Political Event Watch AI" and item.get("event_status", "INACTIVE") != "ACTIVE":
        return False
    if name == "Cross-Market Research AI" and item.get("research_status", "INACTIVE") != "ACTIVE":
        return False
    return abs(_safe_float(item.get("score"))) > 0.03


def _safe_float(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _specialist_state(state, name):
    state = state if isinstance(state, dict) else {}
    return (state.get("specialists", {}) or {}).get(name, {}) or {}


def _contribution_multiplier(state, name):
    """Softly reward useful bots and suppress proven harmful ones.

    Bot Intelligence v4 measures leave-one-out contribution. We shrink the
    multiplier toward 1.0 until enough live samples exist, then let repeated
    harmful flips reduce influence instead of waiting for global accuracy alone.
    """
    state = state if isinstance(state, dict) else {}
    intel = state.get("bot_intelligence_v4", {}) if isinstance(state.get("bot_intelligence_v4", {}), dict) else {}
    if intel.get("label_basis") != "official_kalshi_directional_calls_v1":
        return 1.0
    ranking = intel.get("ranking", []) if isinstance(intel.get("ranking", []), list) else []
    row = next((r for r in ranking if isinstance(r, dict) and r.get("name") == name), None)
    if not row:
        return 1.0
    samples = max(0, int(_safe_float(row.get("directional_calls"), 0)))
    contribution = float(np.clip(_safe_float(row.get("contribution_score"), 0.0), -0.75, 0.50))
    # At 20 samples the contribution signal has full effect; before that it is
    # intentionally shrunk to reduce overreaction to a tiny early sample.
    shrink = min(1.0, samples / 20.0)
    adjustment = float(np.clip(2.0 * contribution, -0.60, 0.30))
    return float(np.clip(1.0 + shrink * adjustment, 0.40, 1.30))


def specialist_weight(name, state=None, regime="UNKNOWN"):
    base = _safe_float(BASE_WEIGHTS.get(name), 0.75)
    learned = regime_specialist_weight(base, _specialist_state(state, name), regime or "UNKNOWN")
    return float(np.clip(learned * _contribution_multiplier(state or {}, name), 0.20, 2.35))


def council_vote(results, state=None, regime="UNKNOWN", exclude=None):
    """Return one authoritative weighted council decision.

    Scores are weighted by static domain importance, learned global reliability,
    regime-specific reliability, contribution value, and each specialist's own
    confidence.
    """
    results = results or {}
    exclude = set(exclude or ()) | EXCLUDED_FROM_COUNCIL
    weighted_sum = 0.0
    denominator = 0.0
    directional_weight = 0.0
    directional_signed = 0.0
    members = []

    for name, item in results.items():
        if name in exclude or not specialist_active(name, item):
            continue
        if name == "Political Event Watch AI" and str(item.get("event_status", "INACTIVE")).upper() != "ACTIVE":
            continue
        if name == "Cross-Market Research AI" and str(item.get("research_status", "INACTIVE")).upper() != "ACTIVE":
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
            "contribution_multiplier": _contribution_multiplier(state or {}, name),
        })

    for member in members:
        member["vote_share"] = member["effective_weight"] / denominator if denominator else 0.0
        member["signed_contribution"] = member["score"] * member["vote_share"]
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
    score it again with one specialist removed. This exposes redundancy and
    harmful specialists instead of rewarding raw agreement alone.
    """
    state = state if isinstance(state, dict) else {}
    from council_accounting import official_snapshots
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

    for snap, outcome in official_snapshots(state):
        ticker = str(snap.get("ticker") or "")
        specialists = ((snap.get("snapshot") or {}).get("specialists") or {})
        if not specialists:
            continue

        actual_dir = 1 if outcome["kalshi_result"] == "yes" else -1
        from specialist_knowledge_v5 import knowledge_adjust_results
        adjusted, _ = knowledge_adjust_results(specialists, state, str((snap.get("snapshot") or {}).get("regime") or "UNKNOWN"))
        regime = str((snap.get("snapshot") or {}).get("regime") or "UNKNOWN")
        full = council_vote(adjusted, state, regime)
        full_dir = _direction(full["base_score"])
        full_hit = int(full_dir != 0 and full_dir == actual_dir)
        evaluated += 1

        for name, call in specialists.items():
            if name in EXCLUDED_FROM_COUNCIL:
                continue
            st = stats[name]
            st["samples"] += 1
            call_dir = _direction((call or {}).get("score")) if specialist_active(name, call) else 0
            if call_dir:
                st["standalone_calls"] += 1
                st["standalone_hits"] += int(call_dir == actual_dir)
            st["score_abs_sum"] += abs(_safe_float((call or {}).get("score"), 0.0))
            st["full_hits"] += full_hit

            without = council_vote(adjusted, state, regime, exclude={name})
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
        confidence_shrink = min(1.0, st["standalone_calls"] / max(float(min_samples), 1.0))
        contribution_score = confidence_shrink * (marginal + 0.50 * saves - 0.65 * harms)
        if st["standalone_calls"] < min_samples:
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
            "directional_calls": st["standalone_calls"],
            "standalone_hits": st["standalone_hits"],
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
        "label_basis": "official_kalshi_directional_calls_v1",
        "evaluation_mode": "retrospective_current_policy_ablation",
        "evaluated_snapshots": evaluated,
        "minimum_samples_for_verdict": int(min_samples),
        "ranking": ranking,
    }
