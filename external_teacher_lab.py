"""Transparent, paper-only teacher strategies for the BTC research lab.

The teachers reproduce public *method categories* used by systematic trading
platforms.  They do not call, scrape, or claim to reproduce any vendor's
proprietary model.  Every call remains isolated from execution and is graded
only from Kalshi's official binary settlement with executable asks and fees.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from kalshi_paper_engine import kalshi_taker_fee


TEACHER_MIN_SAMPLES = 100
TEACHER_REQUIRED_STREAK = 3
TEACHER_MAX_DRAWDOWN = 5.0

TEACHERS = (
    {
        "name": "Composer-inspired Conditional Symphony",
        "source": "Composer by SoFi public strategy concepts",
        "source_url": "https://www.sofi.com/invest/composer/",
        "method": "Transparent ANY/ALL regime, trend and momentum conditions",
    },
    {
        "name": "Freqtrade-inspired Trend Challenger",
        "source": "Freqtrade public strategy concepts",
        "source_url": "https://www.freqtrade.io/en/stable/strategy-customization/",
        "method": "Trend, momentum, MACD and multi-horizon confirmation",
    },
    {
        "name": "Freqtrade-inspired Mean Reversion Challenger",
        "source": "Freqtrade public strategy concepts",
        "source_url": "https://www.freqtrade.io/en/stable/backtesting/",
        "method": "Support/resistance, volatility stretch and candle reversal",
    },
    {
        "name": "FinRL-inspired Risk-Aware Ensemble",
        "source": "FinRL public research framework concepts",
        "source_url": "https://github.com/AI4Finance-Foundation/FinRL",
        "method": "Diversified specialist vote penalized for disagreement",
    },
    {
        "name": "Hummingbot-inspired Microstructure Challenger",
        "source": "Hummingbot public market-microstructure concepts",
        "source_url": "https://hummingbot.org/strategies/",
        "method": "Whale flow, liquidity imbalance, volume and derivatives",
    },
)


def _f(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _clip(value, low=-1.0, high=1.0):
    return max(low, min(high, _f(value)))


def _score(specialists, name):
    return _clip(((specialists or {}).get(name) or {}).get("score"), -1.0, 1.0)


def _available(specialists, name):
    row = ((specialists or {}).get(name) or {})
    reason = str(row.get("reason") or "").lower()
    return bool(row) and not any(
        phrase in reason
        for phrase in ("unavailable", "no qualifying event", "not configured")
    )


def _weighted_score(specialists, weights):
    total = 0.0
    weight_sum = 0.0
    parts = []
    for name, weight in weights.items():
        if name not in (specialists or {}):
            continue
        value = _score(specialists, name)
        total += value * weight
        weight_sum += abs(weight)
        parts.append(value)
    score = _clip(total / weight_sum) if weight_sum else 0.0
    agreement = 0.0
    directional = [value for value in parts if abs(value) >= 0.12]
    if directional and abs(score) >= 0.01:
        direction = 1 if score > 0 else -1
        agreement = sum(1 for value in directional if value * direction > 0) / len(directional)
    return score, agreement


def _teacher_signal(name, specialists):
    if name == "Composer-inspired Conditional Symphony":
        weights = {
            "Trend AI": 0.30,
            "Momentum AI": 0.25,
            "Market Regime AI": 0.25,
            "Combination AI": 0.20,
        }
        score, agreement = _weighted_score(specialists, weights)
        trend = _score(specialists, "Trend AI")
        momentum = _score(specialists, "Momentum AI")
        regime = _score(specialists, "Market Regime AI")
        same_direction = sum(
            1 for value in (trend, momentum, regime)
            if abs(value) >= 0.12 and value * score > 0
        )
        active = abs(score) >= 0.14 and same_direction >= 2
        rule = f"ANY/ALL conditions: {same_direction}/3 core branches agree"
    elif name == "Freqtrade-inspired Trend Challenger":
        weights = {
            "Trend AI": 0.35,
            "Momentum AI": 0.25,
            "FVG / MACD AI": 0.25,
            "Historical Pattern AI": 0.15,
        }
        score, agreement = _weighted_score(specialists, weights)
        trend = _score(specialists, "Trend AI")
        macd = _score(specialists, "FVG / MACD AI")
        active = abs(score) >= 0.14 and trend * macd > 0 and abs(trend) >= 0.12 and abs(macd) >= 0.12
        rule = "Trend and adaptive MACD must confirm the same direction"
    elif name == "Freqtrade-inspired Mean Reversion Challenger":
        weights = {
            "Support/Resistance AI": 0.40,
            "Volatility AI": 0.35,
            "Pattern AI": 0.25,
        }
        score, agreement = _weighted_score(specialists, weights)
        support = _score(specialists, "Support/Resistance AI")
        volatility = _score(specialists, "Volatility AI")
        active = abs(score) >= 0.14 and support * volatility > 0
        rule = "Price-location and volatility-stretch branches must agree"
    elif name == "FinRL-inspired Risk-Aware Ensemble":
        weights = {
            "Trend AI": 0.16,
            "Momentum AI": 0.14,
            "Volume AI": 0.10,
            "Pattern AI": 0.08,
            "Support/Resistance AI": 0.10,
            "Volatility AI": 0.08,
            "Market Regime AI": 0.14,
            "Historical Pattern AI": 0.10,
            "FVG / MACD AI": 0.10,
        }
        raw, agreement = _weighted_score(specialists, weights)
        # Disagreement is treated as risk, not silently averaged away.
        score = _clip(raw * (0.45 + 0.55 * agreement))
        active = abs(score) >= 0.14 and agreement >= 0.60
        rule = f"Risk-adjusted ensemble agreement {agreement:.0%}"
    else:
        weights = {
            "Whale AI": 0.40,
            "Liquidity AI": 0.30,
            "Volume AI": 0.15,
            "Derivatives AI": 0.15,
        }
        score, agreement = _weighted_score(specialists, weights)
        sources = ("Whale AI", "Liquidity AI")
        source_count = sum(1 for source in sources if _available(specialists, source))
        active = abs(score) >= 0.14 and source_count == len(sources)
        rule = f"Verified microstructure sources {source_count}/{len(sources)}"
    return score, agreement, active, rule


def ensure_teacher_lab(lab):
    teacher_lab = lab.setdefault("external_teacher_lab", {})
    teacher_lab["version"] = 1
    teacher_lab["paper_only"] = True
    teacher_lab["affects_execution"] = False
    teacher_lab["minimum_samples"] = TEACHER_MIN_SAMPLES
    teacher_lab["required_streak"] = TEACHER_REQUIRED_STREAK
    teacher_lab["maximum_drawdown"] = TEACHER_MAX_DRAWDOWN
    teacher_lab.setdefault("leader", None)
    teacher_lab.setdefault("ranking", [])
    teacher_lab.setdefault("qualification_streaks", {})
    teacher_lab.setdefault("last_streak_samples", {})
    buckets = teacher_lab.setdefault("teachers", {})
    for definition in TEACHERS:
        bucket = buckets.setdefault(definition["name"], {})
        for field, value in definition.items():
            bucket.setdefault(field, value)
        for field, value in {
            "samples": 0,
            "wins": 0,
            "net_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "equity": 0.0,
            "peak_equity": 0.0,
            "max_drawdown": 0.0,
            "brier_sum": 0.0,
            "ewma_pnl": None,
        }.items():
            bucket.setdefault(field, value)
    return teacher_lab


def build_teacher_calls(lab, pending, market_info):
    ensure_teacher_lab(lab)
    specialists = (pending or {}).get("specialists") or {}
    yes_bid = _f((market_info or {}).get("yes_bid"), None)
    yes_ask = _f((market_info or {}).get("yes_ask"), None)
    no_ask = _f((market_info or {}).get("no_ask"), None)
    if no_ask is None and yes_bid is not None:
        no_ask = 1.0 - yes_bid
    calls = {}
    for definition in TEACHERS:
        score, agreement, active, rule = _teacher_signal(definition["name"], specialists)
        model_yes = max(0.01, min(0.99, 0.5 + 0.49 * score))
        direction = "YES" if score >= 0 else "NO"
        ask = yes_ask if direction == "YES" else no_ask
        side_probability = model_yes if direction == "YES" else 1.0 - model_yes
        confidence = max(0.50, min(0.92, 0.50 + abs(score) * 0.34 + agreement * 0.08))
        eligible = bool(
            active
            and ask is not None
            and ask <= 0.75
            and confidence >= 0.58
            and side_probability >= ask * 1.05
        )
        calls[definition["name"]] = {
            "action": direction if eligible else "WAIT",
            "direction": direction,
            "eligible": eligible,
            "score": score,
            "confidence": confidence,
            "agreement": agreement,
            "model_yes_probability": model_yes,
            "selected_ask": ask,
            "expected_edge": None if ask is None else side_probability - ask,
            "rule": rule,
        }
    return calls


def _update_bucket(bucket, won, pnl, brier):
    bucket["samples"] = int(bucket.get("samples") or 0) + 1
    bucket["wins"] = int(bucket.get("wins") or 0) + int(bool(won))
    bucket["net_pnl"] = _f(bucket.get("net_pnl")) + pnl
    bucket["gross_profit"] = _f(bucket.get("gross_profit")) + max(0.0, pnl)
    bucket["gross_loss"] = _f(bucket.get("gross_loss")) + min(0.0, pnl)
    equity = _f(bucket.get("equity")) + pnl
    peak = max(_f(bucket.get("peak_equity")), equity)
    bucket["equity"] = equity
    bucket["peak_equity"] = peak
    bucket["max_drawdown"] = max(_f(bucket.get("max_drawdown")), peak - equity)
    bucket["brier_sum"] = _f(bucket.get("brier_sum")) + brier
    old = bucket.get("ewma_pnl")
    bucket["ewma_pnl"] = pnl if old is None else 0.82 * _f(old) + 0.18 * pnl


def grade_teacher_calls(lab, observation, result):
    teacher_lab = ensure_teacher_lab(lab)
    outcome = 1.0 if result == "yes" else 0.0
    graded = 0
    for name, call in (observation.get("external_teachers") or {}).items():
        if not call.get("eligible"):
            continue
        direction = str(call.get("direction") or "")
        won = direction.lower() == result
        ask = _f(call.get("selected_ask"), 1.0)
        pnl = (1.0 if won else 0.0) - ask - kalshi_taker_fee(1, ask)
        model_yes = max(0.01, min(0.99, _f(call.get("model_yes_probability"), 0.5)))
        brier = (model_yes - outcome) ** 2
        _update_bucket(teacher_lab["teachers"][name], won, pnl, brier)
        call.update({"won": won, "paper_pnl": pnl, "brier": brier})
        graded += 1
    return graded


def teacher_leaderboard(lab):
    teacher_lab = ensure_teacher_lab(lab)
    old_streaks = teacher_lab.get("qualification_streaks") or {}
    old_counts = teacher_lab.get("last_streak_samples") or {}
    next_streaks = {}
    next_counts = {}
    rows = []
    for name, bucket in teacher_lab["teachers"].items():
        samples = int(bucket.get("samples") or 0)
        wins = int(bucket.get("wins") or 0)
        pnl = _f(bucket.get("net_pnl"))
        gross_loss = abs(_f(bucket.get("gross_loss")))
        gross_profit = _f(bucket.get("gross_profit"))
        profit_factor = gross_profit / gross_loss if gross_loss > 1e-12 else (float("inf") if gross_profit > 0 else None)
        drawdown = _f(bucket.get("max_drawdown"))
        bayes_win = (wins + 2.0) / (samples + 4.0)
        avg_pnl = pnl / samples if samples else 0.0
        brier = _f(bucket.get("brier_sum")) / samples if samples else None
        qualifies = bool(
            samples >= TEACHER_MIN_SAMPLES
            and pnl > 0.0
            and profit_factor is not None
            and profit_factor > 1.0
            and bayes_win > 0.50
            and drawdown <= TEACHER_MAX_DRAWDOWN
        )
        previous = int(old_streaks.get(name, 0))
        if samples > int(old_counts.get(name, 0)):
            streak = previous + 1 if qualifies else 0
        else:
            streak = previous
        next_streaks[name] = streak
        next_counts[name] = samples
        evidence = min(1.0, math.sqrt(samples / TEACHER_MIN_SAMPLES)) if samples else 0.0
        quality = (
            0.35 * ((bayes_win - 0.5) * 2.0)
            + 0.35 * math.tanh(avg_pnl / 0.12)
            + 0.20 * math.tanh(_f(bucket.get("ewma_pnl")) / 0.12)
            - 0.10 * math.tanh(drawdown / 1.5)
        )
        rows.append({
            "name": name,
            "source": bucket.get("source"),
            "method": bucket.get("method"),
            "samples": samples,
            "wins": wins,
            "win_rate": wins / samples if samples else None,
            "bayesian_win_rate": bayes_win,
            "net_pnl": pnl,
            "avg_pnl": avg_pnl,
            "profit_factor": profit_factor,
            "max_drawdown": drawdown,
            "brier": brier,
            "qualification_streak": streak,
            "qualifies_now": qualifies,
            "score": 50.0 + 50.0 * evidence * max(-1.0, min(1.0, quality)),
            "status": "LEARNING",
        })
    rows.sort(key=lambda row: (row["score"], row["net_pnl"], row["samples"]), reverse=True)
    qualified = [
        row for row in rows
        if row["qualifies_now"] and row["qualification_streak"] >= TEACHER_REQUIRED_STREAK
    ]
    leader = qualified[0]["name"] if qualified else None
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        if row["name"] == leader:
            row["status"] = "ADVISORY LEADER"
        elif row["qualifies_now"]:
            row["status"] = f"QUALIFYING {row['qualification_streak']}/{TEACHER_REQUIRED_STREAK}"
        elif row["samples"] >= 25:
            row["status"] = "TRACKING"
    teacher_lab.update({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "leader": leader,
        "ranking": rows,
        "qualification_streaks": next_streaks,
        "last_streak_samples": next_counts,
        "affects_execution": False,
    })
    return teacher_lab
