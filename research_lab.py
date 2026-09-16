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
    lab["version"] = 2
    lab.setdefault("paper_only", True)
    lab.setdefault("affects_execution", False)
    lab.setdefault("pending", [])
    lab.setdefault("history", [])
    lab.setdefault("calibration", {"samples": 0, "model_brier": None, "market_brier": None})
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
        "model_yes_probability": model_yes,
        "market_yes_probability": max(0.01, min(0.99, (yes_bid + yes_ask) / 2.0)),
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
            bucket = lab["policies"].setdefault(name, {})
            update_policy_bucket(bucket, won, pnl)
        grade_teacher_calls(lab, row, result)
        row.update({"result": result, "won": won, "paper_pnl": pnl, "model_brier": model_brier, "market_brier": market_brier})
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
