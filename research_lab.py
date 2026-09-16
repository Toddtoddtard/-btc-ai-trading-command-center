"""Paper-only research instrumentation for KXBTC15M decisions.

This module never places orders and never changes the production execution gate.
It records one shadow observation per contract and grades it only from Kalshi's
official binary result so candidate policies can be compared safely.  The
strategy league evaluates many virtual policies from the same settled window,
similar to a copy-trading leaderboard but without copying people or placing
orders.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from external_teacher_lab import (
    build_teacher_calls,
    ensure_teacher_lab,
    grade_teacher_calls,
    teacher_leaderboard,
)
from kalshi_paper_engine import kalshi_taker_fee


POLICIES = (
    {"name": "Conservative 65 / 5", "max_entry": 0.65, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Value 70 / 5", "max_entry": 0.70, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Value 70 / 10", "max_entry": 0.70, "min_edge": 0.10, "min_confidence": 0.65},
    {"name": "Current 75 / 5", "max_entry": 0.75, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Explore 80 / 5", "max_entry": 0.80, "min_edge": 0.05, "min_confidence": 0.58},
    {"name": "Selective 75 / 10", "max_entry": 0.75, "min_edge": 0.10, "min_confidence": 0.65},
    {"name": "Edge 75 / 15", "max_entry": 0.75, "min_edge": 0.15, "min_confidence": 0.65},
    {"name": "High Confidence 75 / 5", "max_entry": 0.75, "min_edge": 0.05, "min_confidence": 0.72},
)

LEAGUE_MIN_SAMPLES = 100
LEAGUE_REQUIRED_STREAK = 3
LEAGUE_MAX_DRAWDOWN = 5.0
ACTIVE_POLICY_NAME = "Current 75 / 5"
LEAGUE_EWMA_ALPHA = 0.18

# The probability model is deliberately conservative.  Kalshi's midpoint is
# the benchmark and a feature, while the independent master score may only
# move that probability after a causal walk-forward test proves incremental
# Brier value.  These limits prevent a short noisy run from creating another
# overconfident 1%/99% forecast.
CALIBRATION_MIN_TRAINING_ROWS = 60
CALIBRATION_MIN_VALIDATION_ROWS = 100
CALIBRATION_LOOKBACK = 300
CALIBRATION_RIDGE = 0.10
CALIBRATION_MIN_EDGE = 0.0005
CALIBRATION_MARKET_SLOPE_BOUNDS = (0.75, 1.25)
CALIBRATION_MODEL_RESIDUAL_BOUNDS = (-0.15, 0.35)


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
    lab["version"] = 3
    lab.setdefault("paper_only", True)
    lab.setdefault("affects_execution", False)
    lab.setdefault("pending", [])
    lab.setdefault("history", [])
    lab.setdefault("calibration", {"samples": 0, "model_brier": None, "market_brier": None})
    calibration = lab["calibration"]
    calibration.setdefault("guarded", {
        "samples": 0,
        "model_brier": None,
        "market_brier": None,
        "model_edge_vs_market": None,
    })
    lab.setdefault("guarded_calibrator", {
        "version": 1,
        "active": False,
        "affects_execution": False,
        "reason": "Waiting for causal walk-forward evidence",
    })
    lab.setdefault("wait_counterfactual", {"samples": 0, "avoided_losses": 0, "missed_wins": 0, "net_if_traded": 0.0})
    lab.setdefault("phases", {})
    policies = lab.setdefault("policies", {})
    for policy in POLICIES:
        bucket = policies.setdefault(policy["name"], {})
        for key, value in policy.items():
            bucket.setdefault(key, value)
        for key, value in {
            "samples": 0, "wins": 0, "net_pnl": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0,
            "equity": 0.0, "peak_equity": 0.0, "max_drawdown": 0.0,
            "ewma_win_rate": None, "ewma_pnl": None,
        }.items():
            bucket.setdefault(key, value)
    lab.setdefault("strategy_league", {
        "updated_at": None, "minimum_samples": LEAGUE_MIN_SAMPLES,
        "required_streak": LEAGUE_REQUIRED_STREAK,
        "maximum_drawdown": LEAGUE_MAX_DRAWDOWN,
        "active_policy": ACTIVE_POLICY_NAME,
        "qualification_streaks": {},
        "affects_execution": False, "leader": None, "ranking": [],
    })
    lab.setdefault("specialist_lifecycle", {})
    ensure_teacher_lab(lab)
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


def _bounded(value, bounds):
    return max(bounds[0], min(bounds[1], float(value)))


def _calibration_row(row):
    market = _f(row.get("market_yes_probability"))
    raw_model = _f(row.get("raw_model_yes_probability"))
    if raw_model is None:
        raw_model = _f(row.get("model_yes_probability"))
    result = str(row.get("result") or "").lower()
    if market is None or raw_model is None or result not in {"yes", "no"}:
        return None
    return {
        "ticker": str(row.get("ticker") or ""),
        "market": max(0.01, min(0.99, market)),
        "raw_model": max(0.01, min(0.99, raw_model)),
        "outcome": 1.0 if result == "yes" else 0.0,
    }


def _fit_calibration_coefficients(rows):
    """Fit a bounded ridge correction to market probability without numpy."""
    rows = list(rows)[-CALIBRATION_LOOKBACK:]
    s11 = s12 = s22 = b1 = b2 = 0.0
    for row in rows:
        x1 = row["market"] - 0.5
        x2 = row["raw_model"] - row["market"]
        target = row["outcome"] - 0.5
        s11 += x1 * x1
        s12 += x1 * x2
        s22 += x2 * x2
        b1 += x1 * target
        b2 += x2 * target
    a11 = s11 + CALIBRATION_RIDGE
    a22 = s22 + CALIBRATION_RIDGE
    determinant = a11 * a22 - s12 * s12
    if abs(determinant) < 1e-12:
        return 1.0, 0.0
    market_slope = (b1 * a22 - b2 * s12) / determinant
    model_residual = (a11 * b2 - s12 * b1) / determinant
    return (
        _bounded(market_slope, CALIBRATION_MARKET_SLOPE_BOUNDS),
        _bounded(model_residual, CALIBRATION_MODEL_RESIDUAL_BOUNDS),
    )


def _candidate_probability(raw_model, market, coefficients):
    market_slope, model_residual = coefficients
    probability = (
        0.5
        + market_slope * (float(market) - 0.5)
        + model_residual * (float(raw_model) - float(market))
    )
    return max(0.02, min(0.98, probability))


def fit_guarded_calibrator(history):
    """Return a causal, walk-forward-tested probability calibrator.

    All observations from one ticker are validated before that ticker is added
    to training, so later phases of a market cannot learn its own settlement.
    If the candidate has not beaten Kalshi both overall and recently, the live
    research forecast falls back exactly to the contemporaneous market price.
    """
    grouped = {}
    for original in history or []:
        row = _calibration_row(original)
        if row is not None:
            grouped.setdefault(row["ticker"] or f"row-{len(grouped)}", []).append(row)

    training = []
    validation = []
    for group in grouped.values():
        if len(training) >= CALIBRATION_MIN_TRAINING_ROWS:
            coefficients = _fit_calibration_coefficients(training)
            for row in group:
                candidate = _candidate_probability(row["raw_model"], row["market"], coefficients)
                validation.append({
                    "candidate_brier": (candidate - row["outcome"]) ** 2,
                    "market_brier": (row["market"] - row["outcome"]) ** 2,
                })
        training.extend(group)

    coefficients = _fit_calibration_coefficients(training) if training else (1.0, 0.0)
    samples = len(validation)
    candidate_brier = (
        sum(row["candidate_brier"] for row in validation) / samples if samples else None
    )
    market_brier = (
        sum(row["market_brier"] for row in validation) / samples if samples else None
    )
    recent = validation[-min(100, samples):]
    recent_edge = (
        sum(row["market_brier"] - row["candidate_brier"] for row in recent) / len(recent)
        if recent else None
    )
    edge = None if samples == 0 else market_brier - candidate_brier
    active = bool(
        samples >= CALIBRATION_MIN_VALIDATION_ROWS
        and edge is not None
        and edge >= CALIBRATION_MIN_EDGE
        and recent_edge is not None
        and recent_edge >= 0.0
    )
    return {
        "version": 1,
        "active": active,
        "affects_execution": False,
        "training_samples": len(training),
        "validation_samples": samples,
        "validation_brier": candidate_brier,
        "validation_market_brier": market_brier,
        "validation_edge": edge,
        "recent_validation_edge": recent_edge,
        "market_slope": coefficients[0],
        "model_residual_weight": coefficients[1],
        "reason": (
            "Walk-forward Brier improvement passed; guarded residual correction enabled"
            if active else
            "Candidate has not passed the walk-forward edge gate; using Kalshi probability fallback"
        ),
    }


def guarded_probability(raw_model, market, calibrator):
    if not (calibrator or {}).get("active"):
        return max(0.01, min(0.99, float(market)))
    return _candidate_probability(
        raw_model,
        market,
        (
            _f(calibrator.get("market_slope"), 1.0),
            _f(calibrator.get("model_residual_weight"), 0.0),
        ),
    )


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
    raw_model_yes = _yes_probability(pending)
    market_yes = max(0.01, min(0.99, (yes_bid + yes_ask) / 2.0))
    calibrator = fit_guarded_calibrator(lab.get("history") or [])
    calibrator["updated_at"] = datetime.now(timezone.utc).isoformat()
    lab["guarded_calibrator"] = calibrator
    model_yes = guarded_probability(raw_model_yes, market_yes, calibrator)
    # Keep the existing strategy-league experiment stable.  The new guarded
    # probability is scored in parallel and cannot silently change historical
    # entry-policy eligibility before it earns its own evidence.
    direction = "YES" if raw_model_yes >= 0.5 else "NO"
    side_probability = raw_model_yes if direction == "YES" else 1.0 - raw_model_yes
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
    observation = {
        "ticker": ticker,
        "opened_at": opened_at,
        "opened_at_utc": _iso(opened_at),
        "expires_at": expires_at,
        "expires_at_utc": _iso(expires_at),
        "phase": phase_name,
        "action": action,
        "direction": direction,
        "confidence": confidence,
        "model_yes_probability": raw_model_yes,
        "raw_model_yes_probability": raw_model_yes,
        "guarded_yes_probability": model_yes,
        "probability_model_version": "guarded-market-residual-v1",
        "calibrator_active": bool(calibrator.get("active")),
        "market_yes_probability": market_yes,
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "selected_ask": ask,
        "policies": policies,
    }
    observation["external_teachers"] = build_teacher_calls(lab, pending, market_info)
    lab["pending"].append(observation)
    lab["pending"] = lab["pending"][-200:]
    return True


def _running_average(old, value, n):
    return value if n == 1 or old is None else old + (value - old) / n


def _ewma(old, value, alpha=LEAGUE_EWMA_ALPHA):
    return value if old is None else (1.0 - alpha) * float(old) + alpha * float(value)


def update_policy_bucket(bucket, won, pnl):
    """Update fee-aware strategy evidence without retaining unbounded trades."""
    bucket["samples"] = int(bucket.get("samples") or 0) + 1
    bucket["wins"] = int(bucket.get("wins") or 0) + int(bool(won))
    bucket["net_pnl"] = _f(bucket.get("net_pnl"), 0.0) + pnl
    bucket["gross_profit"] = _f(bucket.get("gross_profit"), 0.0) + max(0.0, pnl)
    bucket["gross_loss"] = _f(bucket.get("gross_loss"), 0.0) + min(0.0, pnl)
    equity = _f(bucket.get("equity"), 0.0) + pnl
    peak = max(_f(bucket.get("peak_equity"), 0.0), equity)
    bucket["equity"] = equity
    bucket["peak_equity"] = peak
    bucket["max_drawdown"] = max(
        _f(bucket.get("max_drawdown"), 0.0),
        max(0.0, peak - equity),
    )
    bucket["ewma_win_rate"] = _ewma(bucket.get("ewma_win_rate"), float(bool(won)))
    bucket["ewma_pnl"] = _ewma(bucket.get("ewma_pnl"), pnl)
    return bucket


def strategy_leaderboard(lab):
    """Rank shadow policies on profitability, consistency and drawdown.

    Scores are descriptive research evidence only.  A small-sample strategy is
    never labeled LEADER, and this table cannot modify the live execution gate.
    """
    history = [row for row in (lab.get("history") or []) if row.get("result") in {"yes", "no"}]
    active_bucket = (lab.get("policies") or {}).get(ACTIVE_POLICY_NAME, {})
    active_drawdown = _f(active_bucket.get("max_drawdown"), 0.0)
    league = lab.setdefault("strategy_league", {})
    previous_streaks = league.get("qualification_streaks") or {}
    next_streaks = {}
    rows = []
    for name, bucket in (lab.get("policies") or {}).items():
        samples = int(bucket.get("samples") or 0)
        wins = int(bucket.get("wins") or 0)
        pnl = _f(bucket.get("net_pnl"), 0.0)
        avg_pnl = pnl / samples if samples else 0.0
        bayes_win = (wins + 2.0) / (samples + 4.0)
        gross_profit = _f(bucket.get("gross_profit"), 0.0)
        gross_loss = abs(_f(bucket.get("gross_loss"), 0.0))
        profit_factor = gross_profit / gross_loss if gross_loss > 1e-12 else (float("inf") if gross_profit > 0 else None)
        drawdown = _f(bucket.get("max_drawdown"), 0.0)
        recent_pnl = _f(bucket.get("ewma_pnl"), 0.0)
        recent_win = _f(bucket.get("ewma_win_rate"), 0.5)
        evidence = min(1.0, math.sqrt(samples / LEAGUE_MIN_SAMPLES)) if samples else 0.0
        pf_term = 0.0 if profit_factor is None else math.tanh(math.log(max(profit_factor, 1e-6)) / 2.0)
        quality = (
            0.30 * ((bayes_win - 0.50) * 2.0)
            + 0.28 * math.tanh(avg_pnl / 0.12)
            + 0.17 * pf_term
            + 0.15 * math.tanh(recent_pnl / 0.12)
            + 0.10 * ((recent_win - 0.50) * 2.0)
            - 0.18 * math.tanh(drawdown / 1.50)
        )
        candidate_paired_pnl = 0.0
        active_paired_pnl = 0.0
        paired_samples = 0
        for observation in history:
            decisions = observation.get("policies") or {}
            candidate_eligible = bool((decisions.get(name) or {}).get("eligible"))
            active_eligible = bool((decisions.get(ACTIVE_POLICY_NAME) or {}).get("eligible"))
            if not (candidate_eligible or active_eligible):
                continue
            observation_pnl = _f(observation.get("paper_pnl"), 0.0)
            candidate_paired_pnl += observation_pnl if candidate_eligible else 0.0
            active_paired_pnl += observation_pnl if active_eligible else 0.0
            paired_samples += 1
        paired_delta = candidate_paired_pnl - active_paired_pnl
        qualifies = bool(
            name != ACTIVE_POLICY_NAME
            and samples >= LEAGUE_MIN_SAMPLES
            and pnl > 0.0
            and paired_samples >= LEAGUE_MIN_SAMPLES
            and paired_delta > 0.0
            and drawdown <= LEAGUE_MAX_DRAWDOWN
            and drawdown <= max(1.0, active_drawdown)
        )
        streak = int(previous_streaks.get(name, 0)) + 1 if qualifies else 0
        next_streaks[name] = streak
        rows.append({
            "name": name,
            "samples": samples,
            "wins": wins,
            "win_rate": (wins / samples) if samples else None,
            "bayesian_win_rate": bayes_win,
            "net_pnl": pnl,
            "avg_pnl": avg_pnl,
            "profit_factor": profit_factor,
            "max_drawdown": drawdown,
            "recent_win_rate": recent_win,
            "recent_avg_pnl": recent_pnl,
            "paired_samples": paired_samples,
            "paired_net_pnl": candidate_paired_pnl,
            "active_paired_net_pnl": active_paired_pnl,
            "paired_pnl_delta": paired_delta,
            "qualification_streak": streak,
            "qualifies_now": qualifies,
            "score": 50.0 + 50.0 * evidence * max(-1.0, min(1.0, quality)),
            "status": "LEARNING",
        })
    rows.sort(key=lambda row: (row["score"], row["net_pnl"], row["samples"]), reverse=True)
    qualified = [
        row for row in rows
        if row["qualifies_now"] and row["qualification_streak"] >= LEAGUE_REQUIRED_STREAK
    ]
    leader = qualified[0]["name"] if qualified else None
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        if row["name"] == leader:
            row["status"] = "LEADER"
        elif row["qualifies_now"]:
            row["status"] = f"QUALIFYING {row['qualification_streak']}/{LEAGUE_REQUIRED_STREAK}"
        elif row["samples"] >= 10 and row["recent_avg_pnl"] > row["avg_pnl"]:
            row["status"] = "RISING"
        elif row["samples"] >= LEAGUE_MIN_SAMPLES:
            row["status"] = "TRACKING"
    league.update({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "minimum_samples": LEAGUE_MIN_SAMPLES,
        "required_streak": LEAGUE_REQUIRED_STREAK,
        "maximum_drawdown": LEAGUE_MAX_DRAWDOWN,
        "active_policy": ACTIVE_POLICY_NAME,
        "qualification_streaks": next_streaks,
        "affects_execution": False,
        "leader": leader,
        "ranking": rows,
    })
    return league


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
        raw_model_probability = _f(
            row.get("raw_model_yes_probability"),
            _f(row.get("model_yes_probability"), 0.5),
        )
        model_brier = (raw_model_probability - outcome) ** 2
        market_brier = (row["market_yes_probability"] - outcome) ** 2
        calibration = lab["calibration"]
        calibration["samples"] += 1
        n = calibration["samples"]
        calibration["model_brier"] = _running_average(calibration.get("model_brier"), model_brier, n)
        calibration["market_brier"] = _running_average(calibration.get("market_brier"), market_brier, n)
        calibration["model_edge_vs_market"] = calibration["market_brier"] - calibration["model_brier"]

        guarded_probability_value = _f(row.get("guarded_yes_probability"))
        guarded_brier = None
        if guarded_probability_value is not None:
            guarded_brier = (guarded_probability_value - outcome) ** 2
            guarded = calibration.setdefault("guarded", {})
            guarded["samples"] = int(guarded.get("samples") or 0) + 1
            guarded_n = guarded["samples"]
            guarded["model_brier"] = _running_average(
                guarded.get("model_brier"), guarded_brier, guarded_n
            )
            guarded["market_brier"] = _running_average(
                guarded.get("market_brier"), market_brier, guarded_n
            )
            guarded["model_edge_vs_market"] = (
                guarded["market_brier"] - guarded["model_brier"]
            )

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
            bucket = lab["policies"].setdefault(name, {})
            update_policy_bucket(bucket, won, pnl)
        grade_teacher_calls(lab, row, result)
        row.update({
            "result": result,
            "won": won,
            "paper_pnl": pnl,
            "model_brier": model_brier,
            "guarded_brier": guarded_brier,
            "market_brier": market_brier,
        })
        lab["history"].append(row)
        resolved += 1
    lab["pending"] = unresolved[-200:]
    lab["history"] = lab["history"][-1000:]
    strategy_leaderboard(lab)
    teacher_leaderboard(lab)
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
