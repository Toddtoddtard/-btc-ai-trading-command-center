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
from outcome_timing import outcome_available_at

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
    "Political Event Watch AI": 0.75,
}

# Combination AI is intentionally excluded from the source council so the
# system cannot double-count its own aggregate vote.
EXCLUDED_FROM_COUNCIL = {"Combination AI"}


def specialist_active(name, item):
    """Abstention keeps a specialist available without diluting today's vote."""
    if name in EXCLUDED_FROM_COUNCIL or not isinstance(item, dict):
        return False
    if name == "Political Event Watch AI" and str(item.get("event_status", "INACTIVE")).upper() != "ACTIVE":
        return False
    if name == "Cross-Market Research AI" and str(item.get("research_status", "INACTIVE")).upper() != "ACTIVE":
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


def specialist_model_matches(state, name, item):
    """Changed pattern definitions cannot inherit older model evidence."""
    version = _safe_float((state or {}).get("pattern_structure_version"), 1)
    return (name != "Pattern AI" or version < 3
            or _safe_float(item.get("model_version"), 1) == version)


def _contribution_multiplier(state, name):
    """Softly reward useful bots and suppress proven harmful ones.

    Bot Intelligence v4 measures leave-one-out contribution. We shrink the
    multiplier toward 1.0 until enough live samples exist, then let repeated
    harmful flips reduce influence instead of waiting for global accuracy alone.
    """
    state = state if isinstance(state, dict) else {}
    intel = state.get("bot_intelligence_v4", {}) if isinstance(state.get("bot_intelligence_v4", {}), dict) else {}
    if (intel.get("label_basis") != "official_kalshi_directional_calls_v1"
            or intel.get("evaluation_mode") != "causal_prior_only_ablation"
            or intel.get("evidence_version") != 2):
        return 1.0
    ranking = intel.get("ranking", []) if isinstance(intel.get("ranking", []), list) else []
    row = next((r for r in ranking if isinstance(r, dict) and r.get("name") == name), None)
    if not row or not specialist_model_matches(state, name, row):
        return 1.0
    if not row.get("evidence_passed") or int(row.get("evidence_streak", 0)) < 3:
        return 1.0
    return float(np.clip(_safe_float(row.get("stable_multiplier"), 1.0), .40, 1.30))


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
    directional = [m["effective_weight"] for m in members if abs(m["score"]) >= .08]
    effective_voters = (sum(directional)**2 / sum(w*w for w in directional)) if directional else 0.0
    # Agreement among one voter is not independent corroboration. Three
    # comparably weighted voters earn the full bonus; inactive rare bots do not
    # dilute the denominator or suppress a normally populated council.
    coverage = min(1.0, max(0.0, (effective_voters-1.0)/2.0))
    raw_confidence = float(np.clip(0.46 + abs(base_score) * 0.34 + consensus * coverage * 0.18, 0.40, 0.96))
    health = source_health_from_specialists(results, exclude=exclude)
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
        "consensus_coverage": coverage,
        "effective_voters": effective_voters,
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


def _action_direction(vote):
    action = str(vote.get("action") or "WAIT").upper()
    if action in {"SCALP UP", "LOCK UP"}:
        return 1
    if action in {"SCALP DOWN", "LOCK DOWN"}:
        return -1
    return 0


def analyze_bot_contributions(state, min_samples=12):
    """Test the gated council subdecision, not Master fills or trade P/L.

    Contribution multipliers are deliberately omitted from both arms. Testing
    their own recursively generated rankings would be circular. Only paired
    decisions justify influence; WAIT has zero decision utility and never counts
    as a lost trade. Opposite-direction flips are reported separately.
    """
    from council_accounting import official_snapshots, reconcile_specialists, reconcile_master_learning
    from specialist_knowledge_v5 import knowledge_adjust_results, precision_gate
    from contribution_evidence import paired_evidence, stable_update, MIN_ACTIVE_MARKETS
    state = state if isinstance(state, dict) else {}
    stats = defaultdict(lambda: defaultdict(int))
    records = sorted(official_snapshots(state), key=lambda pair: _safe_float(pair[0].get("opened_at")))
    evaluated = 0

    def decision(results, knowledge, learned, regime, exclude=None):
        vote = council_vote(results, learned, regime, exclude=exclude)
        kept = {n: k for n, k in knowledge.items() if n not in (exclude or ())}
        if not precision_gate(vote, kept)[0]:
            vote["action"] = "WAIT"
        return _action_direction(vote)

    for index, (snap, outcome) in enumerate(records):
        specialists = (snap.get("snapshot") or {}).get("specialists") or {}
        if not specialists:
            continue
        actual_dir = 1 if outcome["kalshi_result"] == "yes" else -1
        opened = _safe_float(snap.get("opened_at"))
        prior = [(s, o) for s, o in records[:index]
                 if outcome_available_at(o, s.get("expires_at")) <= opened]
        replay_state = {"prediction_snapshots": [s for s, _ in prior],
                        "master_history": [o for _, o in prior], "specialists": {},
                        "pattern_structure_version": state.get("pattern_structure_version", 1)}
        reconcile_specialists(replay_state)
        reconcile_master_learning(replay_state)
        regime = str((snap.get("snapshot") or {}).get("regime") or "UNKNOWN")
        adjusted, knowledge = knowledge_adjust_results(specialists, replay_state, regime)
        full_dir = decision(adjusted, knowledge, replay_state, regime)
        evaluated += 1
        for name, call in specialists.items():
            if name in EXCLUDED_FROM_COUNCIL or not specialist_model_matches(state, name, call):
                continue
            st = stats[name]
            st["samples"] += 1
            if not specialist_active(name, adjusted[name]):
                continue
            st["active_samples"] += 1
            call_dir = _direction(adjusted[name].get("score"))
            st["standalone_hits"] += int(call_dir == actual_dir)
            st["score_abs_sum"] += abs(_safe_float(adjusted[name].get("score")))
            without_dir = decision(adjusted, knowledge, replay_state, regime, exclude={name})
            st["full_calls"] += int(full_dir != 0)
            st["full_hits"] += int(full_dir != 0 and full_dir == actual_dir)
            st["without_calls"] += int(without_dir != 0)
            st["without_hits"] += int(without_dir != 0 and without_dir == actual_dir)
            if full_dir and without_dir:
                st["paired_calls"] += 1
                st["unique_saves"] += int(full_dir == actual_dir and without_dir != actual_dir)
                st["harmful_flips"] += int(full_dir != actual_dir and without_dir == actual_dir)
            elif full_dir or without_dir:
                st["abstention_changes"] += 1
            if full_dir or without_dir:
                st["paired_decisions"] += 1
                full_value = (1 if full_dir == actual_dir else -1) if full_dir else 0
                without_value = (1 if without_dir == actual_dir else -1) if without_dir else 0
                st["beneficial_decisions"] += int(full_value > without_value)
                st["harmful_decisions"] += int(full_value < without_value)
            # Repeated polling of identical evidence cannot advance hysteresis.
            st["last_active_evidence"] = str(snap.get("ticker"))

    previous = state.get("bot_intelligence_v4", {}) or {}
    old = {r["name"]: r for r in previous.get("ranking", [])
           if previous.get("evidence_version") == 2 and specialist_model_matches(state, r["name"], r)}
    ranking = []
    for name, st in stats.items():
        active, paired = st["active_samples"], st["paired_calls"]
        saves, harms = st["unique_saves"], st["harmful_flips"]
        improvements, degradations = st["beneficial_decisions"], st["harmful_decisions"]
        comparisons = st["paired_decisions"]
        marginal = (saves-harms)/paired if paired else 0.
        effect = (improvements-degradations)/comparisons if comparisons else 0.
        evidence = paired_evidence(improvements, degradations, active, len(stats))
        evidence["evidence_passed"] = bool(evidence["evidence_passed"] and active >= max(int(min_samples), MIN_ACTIVE_MARKETS))
        candidate = ("HIGH VALUE" if improvements > degradations else "HURTING COUNCIL") if evidence["evidence_passed"] else "LEARNING"
        row = {"name": name, "samples": st["samples"], "active_samples": active,
               "standalone_accuracy": st["standalone_hits"]/active if active else None,
               "directional_calls": active, "standalone_hits": st["standalone_hits"],
               "full_council_accuracy": st["full_hits"]/st["full_calls"] if st["full_calls"] else None,
               "without_bot_accuracy": st["without_hits"]/st["without_calls"] if st["without_calls"] else None,
               "full_council_calls": st["full_calls"], "without_bot_calls": st["without_calls"],
               "paired_calls": paired, "abstention_changes": st["abstention_changes"],
               "paired_decisions": comparisons, "beneficial_decisions": improvements,
               "harmful_decisions": degradations,
               "beneficial_decision_rate": improvements/comparisons if comparisons else None,
               "harmful_decision_rate": degradations/comparisons if comparisons else None,
               "marginal_accuracy": marginal if paired else None,
               "unique_save_rate": saves/paired if paired else None,
               "harmful_flip_rate": harms/paired if paired else None,
               "unique_saves": saves, "harmful_flips": harms,
               "avg_abs_score": st["score_abs_sum"]/active if active else 0.,
               "contribution_score": effect, "candidate_verdict": candidate, **evidence}
        if name == "Pattern AI":
            row["model_version"] = state.get("pattern_structure_version", 1)
        row.update(stable_update(row, old.get(name), st["last_active_evidence"]))
        row["verdict"] = candidate if row["evidence_streak"] >= 3 else "LEARNING"
        ranking.append(row)
    ranking.sort(key=lambda row: (row["evidence_passed"], row["contribution_score"], row["active_samples"]), reverse=True)
    return {"version": 4, "evidence_version": 2,
            "label_basis": "official_kalshi_directional_calls_v1",
            "evaluation_mode": "causal_prior_only_ablation",
            "decision_basis": "gated_council_subdecision_without_contribution_multiplier",
            "actual_master_execution_replayed": False,
            "evidence_test": "exact_paired_decision_sign_test",
            "decision_utility": "correct +1, incorrect -1, WAIT 0; no trade-profit inference",
            "legacy_outcome_timing": "expiry plus 120 seconds when poll timestamp is unknown",
            "evaluated_snapshots": evaluated,
            "minimum_samples_for_verdict": max(int(min_samples), MIN_ACTIVE_MARKETS),
            "ranking": ranking}
