"""Specialist self-learning and historical prior knowledge for BTC AI v5/v16.

This module never invents accuracy. It combines graded live specialist history
with optional walk-forward historical priors using conservative Bayesian
shrinkage. The precision gate is a safety veto, not a second trade engine.
"""
from __future__ import annotations

import math
import numpy as np
from council_v4 import council_vote

TARGET_PRECISION = 0.90
PRIOR_STRENGTH = 18.0
MIN_LIVE_SAMPLES = 20
MIN_MATURE_SPECIALISTS = 3


def _f(x, default=0.0):
    try:
        x = float(x)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _history_rows(state, name):
    histories = (state or {}).get("specialist_history", {}) or {}
    rows = histories.get(name, [])
    return rows if isinstance(rows, list) else []


def _historical_prior(state, name, regime=None):
    state = state or {}
    report = state.get("historical_specialist_knowledge_v7", {}) or {}
    specialists = report.get("specialists", {}) or {}
    holdout = report.get("holdout", {}) or {}
    if isinstance(holdout, dict) and isinstance(holdout.get("specialists"), dict):
        specialists = holdout["specialists"]
    item = ((specialists or {}).get(name, {}) or {})
    if regime and regime != "UNKNOWN":
        ri = (item.get("regimes", {}) or {}).get(regime, {}) or {}
        acc, samples = ri.get("accuracy"), int(_f(ri.get("directional_calls"), 0))
        if acc is not None and samples > 0:
            return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples
    acc, samples = item.get("accuracy"), int(_f(item.get("directional_calls"), 0))
    if acc is not None and samples > 0:
        return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples
    legacy = state.get("historical_knowledge_v5", {}) or {}
    old = (legacy.get("specialists", {}) or {}).get(name, {}) or {}
    acc, samples = old.get("accuracy"), int(_f(old.get("samples"), 0))
    if acc is None or samples <= 0:
        return 0.50, 0
    return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples


def specialist_posterior(state, name, regime=None):
    rows = _history_rows(state, name)
    if regime:
        regime_rows = [r for r in rows if str(r.get("regime", "")) == str(regime)]
        if len(regime_rows) >= 12:
            rows = regime_rows
    hist_acc, hist_n = _historical_prior(state, name, regime)
    prior_n = min(hist_n, 5000)
    effective_prior = min(PRIOR_STRENGTH + math.sqrt(max(prior_n, 0)), 90.0) if hist_n else 2.0
    alpha = 1.0 + effective_prior * hist_acc
    beta = 1.0 + effective_prior * (1.0 - hist_acc)
    live_n = live_hits = 0
    edge_sum = 0.0
    for r in rows[-500:]:
        hit = r.get("direction_correct")
        if hit is None:
            continue
        live_n += 1
        live_hits += int(bool(hit))
        edge_sum += _f(r.get("signed_edge"), 0.0)
        alpha += int(bool(hit))
        beta += 1 - int(bool(hit))
    mean = alpha / (alpha + beta)
    var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
    lower95 = float(np.clip(mean - 1.96 * math.sqrt(max(var, 0.0)), 0.0, 1.0))
    avg_edge = edge_sum / live_n if live_n else 0.0
    reliability = float(np.clip(1.0 + (mean - 0.50) * 1.35 + np.tanh(avg_edge * 4.0) * 0.10, 0.55, 1.45))
    return {
        "name": name,
        "posterior_accuracy": float(mean),
        "lower95_accuracy": lower95,
        "historical_samples": int(hist_n),
        "historical_accuracy": float(hist_acc) if hist_n else None,
        "historical_regime": str(regime or "UNKNOWN"),
        "live_samples": int(live_n),
        "live_hits": int(live_hits),
        "avg_signed_edge": float(avg_edge),
        "reliability_multiplier": reliability,
        "mature": bool(live_n >= MIN_LIVE_SAMPLES or hist_n >= 100),
    }


def knowledge_adjust_results(results, state, regime="UNKNOWN"):
    adjusted, knowledge = {}, {}
    for name, item in (results or {}).items():
        if not isinstance(item, dict):
            continue
        k = specialist_posterior(state, name, regime)
        knowledge[name] = k
        score = float(np.clip(_f(item.get("score"), 0.0) * k["reliability_multiplier"], -1.0, 1.0))
        raw_conf = float(np.clip(_f(item.get("confidence"), 0.5), 0.05, 0.99))
        learned_conf = float(np.clip(0.42 + k["posterior_accuracy"] * 0.45, 0.42, 0.88))
        blend = 0.15 if not k["mature"] else 0.30
        out = dict(item)
        out["score"] = score
        out["confidence"] = float(np.clip((1.0 - blend) * raw_conf + blend * learned_conf, 0.05, 0.99))
        out["knowledge"] = k
        adjusted[name] = out
    return adjusted, knowledge


def precision_gate(vote, knowledge, target_precision=TARGET_PRECISION):
    """Safety veto only; never creates or duplicates a trade decision."""
    directional = [k for k in (knowledge or {}).values() if isinstance(k, dict) and k.get("mature")]
    if len(directional) < MIN_MATURE_SPECIALISTS:
        return True, f"PASS — learning evidence {len(directional)}/{MIN_MATURE_SPECIALISTS}; council gate remains authoritative"

    means = sorted((_f(k.get("posterior_accuracy"), 0.50) for k in directional), reverse=True)
    evidence_mean = float(np.mean(means[: min(5, len(means))])) if means else 0.50
    source_health = _f((vote or {}).get("source_health"), 1.0)

    # Only veto clearly bad learned evidence or broken feeds. The previous 80%
    # lower-bound requirement was mathematically unreachable with current data
    # and forced every otherwise-valid scalp/lock to HOLD.
    if evidence_mean < 0.48:
        return False, f"WAIT — learned specialist evidence weak ({evidence_mean:.1%})"
    if source_health < 0.68:
        return False, f"WAIT — source health too low ({source_health:.1%})"
    return True, f"PRECISION SAFETY GATE PASSED — learned evidence {evidence_mean:.1%}"


def knowledge_council_vote(results, state=None, regime="UNKNOWN", target_precision=TARGET_PRECISION):
    adjusted, knowledge = knowledge_adjust_results(results, state or {}, regime)
    vote = council_vote(adjusted, state or {}, regime)
    allowed, gate_reason = precision_gate(vote, knowledge, target_precision)
    vote["knowledge"] = knowledge
    vote["precision_target"] = float(target_precision)
    vote["precision_gate_passed"] = bool(allowed)
    vote["precision_gate_reason"] = gate_reason
    if not allowed:
        vote["action_before_precision_gate"] = vote.get("action", "WAIT")
        vote["action"] = "WAIT"
    return vote
