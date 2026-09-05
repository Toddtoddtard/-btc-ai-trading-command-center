"""Specialist self-learning and historical prior knowledge for BTC AI v5/v16.

This module never invents accuracy. It combines graded live specialist history
with optional walk-forward historical priors using conservative Bayesian
shrinkage. The precision gate is a safety veto, not a second impossible model:
the council's own edge/confidence/feed gates decide whether a trade exists;
this layer only blocks trades when the learned evidence is clearly weak.
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
    """Return (accuracy, samples) from stored walk-forward evidence."""
    state = state or {}
    report = state.get("historical_specialist_knowledge_v7", {}) or {}
    bots = report.get("specialists", {}) or {}
    item = bots.get(name, {}) or {}
    if regime and regime != "UNKNOWN":
        regime_item = (item.get("regimes", {}) or {}).get(regime, {}) or {}
        acc = regime_item.get("accuracy")
        samples = int(_f(regime_item.get("directional_calls"), 0))
        if acc is not None and samples > 0:
            return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples
    acc = item.get("accuracy")
    samples = int(_f(item.get("directional_calls"), 0))
    if acc is not None and samples > 0:
        return float(np.clip(_f(acc, 0.50), 0.01, 0.99)), samples

    legacy = state.get("historical_knowledge_v5", {}) or {}
    old = (legacy.get("specialists", {}) or {}).get(name, {}) or {}
    acc = old.get("accuracy")
    samples = int(_f(old.get("samples"), 0))
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

    # Keep reliability centered near 1.0. Previous code centered near 0.55,
    # which muted almost every specialist even when it was merely unproven.
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
    adjusted = {}
    knowledge = {}
    for name, item in (results or {}).items():
        if not isinstance(item, dict):
            continue
        k = specialist_posterior(state, name, regime)
        knowledge[name] = k
        score = float(np.clip(_f(item.get("score"), 0.0) * k["reliability_multiplier"], -1.0, 1.0))
        raw_conf = float(np.clip(_f(item.get("confidence"), 0.5), 0.05, 0.99))

        # Learned accuracy may fine-tune confidence, but must not collapse a
        # strong live signal simply because historical accuracy is near 50%.
        learned_conf = float(np.clip(0.42 + k["posterior_accuracy"] * 0.45, 0.42, 0.88))
        blend = 0.15 if not k["mature"] else 0.30
        confidence = (1.0 - blend) * raw_conf + blend * learned_conf
        out = dict(item)
        out["score"] = score
        out["confidence"] = float(np.clip(confidence, 0.05, 0.99))
        out["knowledge"] = k
        adjusted[name] = out
    return adjusted, knowledge


def precision_gate(vote, knowledge, target_precision=TARGET_PRECISION):
    """Final safety veto for a trade that already passed the council gate.

    The prior implementation required an ~80% lower confidence bound from
    specialists whose measured accuracy is around chance. That condition could
    never be reached and therefore converted every otherwise-valid SCALP/LOCK
    into WAIT/HOLD. This gate now checks for adequate evidence and rejects only
    clearly poor learned evidence; edge, confidence, consensus and feed health
    remain enforced by ``council_vote``/``learned_trade_gate``.
    """
    action = str((vote or {}).get("action", "WAIT")).upper()
    if action in {"WAIT", "HOLD"}:
        return False, "WAIT — council trade gate did not pass"

    directional = [k for k in (knowledge or {}).values() if isinstance(k, dict) and k.get("mature")]
    if len(directional) < MIN_MATURE_SPECIALISTS:
        # Do not create a permanent deadlock during bootstrapping. The council
        # already has strict edge/confidence/feed checks, so immature knowledge
        # is informational rather than an automatic veto.
        return True, f"PASS — council gate passed; learning evidence {len(directional)}/{MIN_MATURE_SPECIALISTS}"

    means = sorted((_f(k.get("posterior_accuracy"), 0.50) for k in directional), reverse=True)
    top_means = means[: min(5, len(means))]
    evidence_mean = float(np.mean(top_means)) if top_means else 0.50
    consensus = _f(vote.get("consensus"), 0.0)
    confidence = _f(vote.get("confidence"), 0.0)
    source_health = _f(vote.get("source_health"), 1.0)

    # Block only when learned evidence is genuinely poor. A 90% target remains
    # an evaluation objective, not an impossible runtime requirement.
    if evidence_mean < 0.48:
        return False, f"WAIT — learned specialist evidence weak ({evidence_mean:.1%})"
    if consensus < 0.18:
        return False, f"WAIT — council conflict ({consensus:.1%})"
    if confidence < 0.56:
        return False, f"WAIT — calibrated confidence too low ({confidence:.1%})"
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
