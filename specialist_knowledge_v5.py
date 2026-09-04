"""Specialist self-learning and prior knowledge for BTC AI v5.

This module never invents accuracy. It converts existing graded specialist history
and optional historical walk-forward priors into conservative Bayesian posteriors.
The posterior then calibrates each specialist's confidence and influence.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from council_v4 import council_vote

TARGET_PRECISION = 0.90
PRIOR_STRENGTH = 24.0
MIN_LIVE_SAMPLES = 20


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


def _historical_prior(state, name):
    """Return (accuracy, samples) only from a real walk-forward report if present."""
    report = (state or {}).get("historical_knowledge_v5", {}) or {}
    bots = report.get("specialists", {}) or {}
    item = bots.get(name, {}) or {}
    acc = item.get("accuracy")
    samples = int(_f(item.get("samples"), 0))
    if acc is None or samples <= 0:
        return 0.50, 0
    return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples


def specialist_posterior(state, name, regime=None):
    rows = _history_rows(state, name)
    if regime:
        regime_rows = [r for r in rows if str(r.get("regime", "")) == str(regime)]
        if len(regime_rows) >= 12:
            rows = regime_rows

    hist_acc, hist_n = _historical_prior(state, name)
    prior_n = min(hist_n, 5000)
    # Compress large backtests into a finite prior so live behavior can take over.
    effective_prior = min(PRIOR_STRENGTH + math.sqrt(max(prior_n, 0)), 120.0)
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
    # Normal approximation is conservative enough here and avoids scipy dependency.
    var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
    lower95 = float(np.clip(mean - 1.96 * math.sqrt(max(var, 0.0)), 0.0, 1.0))
    avg_edge = edge_sum / live_n if live_n else 0.0
    reliability = float(np.clip(0.55 + (mean - 0.50) * 1.8 + np.tanh(avg_edge * 4.0) * 0.12, 0.35, 1.65))

    return {
        "name": name,
        "posterior_accuracy": float(mean),
        "lower95_accuracy": lower95,
        "historical_samples": int(hist_n),
        "live_samples": int(live_n),
        "live_hits": int(live_hits),
        "avg_signed_edge": float(avg_edge),
        "reliability_multiplier": reliability,
        "mature": bool(live_n >= MIN_LIVE_SAMPLES or hist_n >= 100),
    }


def knowledge_adjust_results(results, state, regime="UNKNOWN"):
    adjusted = {}
    knowledge = {}
    for name, item in (results or {}).items():
        if not isinstance(item, dict):
            continue
        k = specialist_posterior(state, name, regime)
        knowledge[name] = k
        score = float(np.clip(_f(item.get("score"), 0.0) * k["reliability_multiplier"], -1.0, 1.0))
        raw_conf = float(np.clip(_f(item.get("confidence"), 0.5), 0.05, 0.99))
        skill_conf = float(np.clip(0.35 + k["posterior_accuracy"] * 0.65, 0.35, 0.99))
        # Immature bots remain conservative; mature proven bots can carry more confidence.
        blend = 0.30 if not k["mature"] else 0.55
        confidence = (1.0 - blend) * raw_conf + blend * skill_conf
        out = dict(item)
        out["score"] = score
        out["confidence"] = float(np.clip(confidence, 0.05, 0.99))
        out["knowledge"] = k
        adjusted[name] = out
    return adjusted, knowledge


def precision_gate(vote, knowledge, target_precision=TARGET_PRECISION):
    """Selective-trading gate aimed at high precision, not high trade frequency."""
    action = str((vote or {}).get("action", "WAIT"))
    if action == "WAIT":
        return False, "WAIT — council edge below threshold"

    directional = []
    sign = 1 if "UP" in action else -1
    for name, k in (knowledge or {}).items():
        if not k.get("mature"):
            continue
        directional.append(k)

    if len(directional) < 3:
        return False, "WAIT — not enough mature specialist evidence"

    # Use the lower bound of the strongest mature specialists, not the average claim.
    lowers = sorted((k["lower95_accuracy"] for k in directional), reverse=True)
    top = lowers[: min(5, len(lowers))]
    evidence_floor = float(np.mean(top)) if top else 0.0
    consensus = _f(vote.get("consensus"), 0.0)
    confidence = _f(vote.get("confidence"), 0.0)

    # We do not pretend this guarantees 90%; it is a strict abstention rule.
    required_floor = max(0.62, min(float(target_precision) - 0.10, 0.80))
    if evidence_floor < required_floor:
        return False, f"WAIT — evidence floor {evidence_floor:.1%} < {required_floor:.1%}"
    if consensus < 0.62:
        return False, f"WAIT — council consensus {consensus:.1%} < 62%"
    if confidence < 0.68:
        return False, f"WAIT — calibrated confidence {confidence:.1%} < 68%"
    return True, "PRECISION GATE PASSED"


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
