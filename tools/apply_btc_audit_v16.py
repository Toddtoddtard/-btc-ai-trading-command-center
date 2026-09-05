#!/usr/bin/env python3
"""Apply the v16 BTC decision fixes to app.py without breaking newer policies.

This updater is intentionally idempotent. The app may already contain the v16
policy or a newer policy (for example the hold-balance thresholds). In those
cases the script validates the required safety logic and exits successfully
instead of failing on an obsolete source-code anchor.
"""
from pathlib import Path

path = Path("app.py")
s = path.read_text()

old_up = '''        strong_move_up = (
            base_score >= policy["edge_floor"]
            and forecast_move >= max(atr * 0.50, px * 0.0007)
            and consensus >= 0.30
        )
        strong_move_down = (
            base_score <= -policy["edge_floor"]
            and forecast_move <= -max(atr * 0.50, px * 0.0007)
            and consensus >= 0.30
        )

        up_price_favorable = (
            pd.notna(up_prob)
            and 0.18 <= up_prob <= 0.72
        )
        down_price_favorable = (
            pd.notna(down_prob)
            and 0.18 <= down_prob <= 0.72
        )
'''
new_up = '''        # BTC scalp calls are directional market calls. The prior thresholds
        # accidentally required roughly a 0.56 council score in low-volatility
        # conditions, far above the learned edge floor, so valid setups almost
        # never reached SCALP. Align movement/consensus with the learned policy.
        strong_move_up = (
            base_score >= policy["edge_floor"]
            and forecast_move >= max(atr * 0.22, px * 0.00022)
            and consensus >= 0.22
        )
        strong_move_down = (
            base_score <= -policy["edge_floor"]
            and forecast_move <= -max(atr * 0.22, px * 0.00022)
            and consensus >= 0.22
        )

        # Kalshi is context/confirmation for BTC scalps, not the instrument being
        # scalp-traded. Only an extreme opposing prediction-market signal blocks
        # the call; a high same-direction probability is confirmation, not a veto.
        up_market_conflict = pd.notna(up_prob) and up_prob < 0.20
        down_market_conflict = pd.notna(down_prob) and down_prob < 0.20
'''

# Only apply the legacy transformation when its exact old block is present.
if old_up in s:
    s = s.replace(old_up, new_up, 1)

    s = s.replace(
        'elif strong_move_up and up_price_favorable and confidence >= policy["trade_confidence_floor"]:',
        'elif strong_move_up and not up_market_conflict and confidence >= policy["trade_confidence_floor"]:',
        1,
    )
    s = s.replace(
        'elif strong_move_down and down_price_favorable and confidence >= policy["trade_confidence_floor"]:',
        'elif strong_move_down and not down_market_conflict and confidence >= policy["trade_confidence_floor"]:',
        1,
    )

    s = s.replace(
        '    # v5 selective-precision gate: the live app must not take a trade merely\n'
        '    # because the older threshold fired. The Bayesian evidence floor must pass.\n',
        '    # Learned precision layer is a final safety veto only. It must not duplicate\n'
        '    # the council trade gate or permanently deadlock otherwise-valid calls.\n',
        1,
    )

    path.write_text(s)
    print("Applied BTC audit v16 decision fixes")
else:
    # Newer policy revisions intentionally changed the numeric thresholds. Require
    # the safety behavior introduced by v16, but do not downgrade newer tuning.
    required = (
        "strong_move_up = (",
        "strong_move_down = (",
        "up_market_conflict",
        "down_market_conflict",
        "not up_market_conflict",
        "not down_market_conflict",
    )
    missing = [token for token in required if token not in s]
    if missing:
        raise SystemExit(
            "BTC decision policy is neither legacy-v16 nor a compatible newer policy; "
            f"missing: {', '.join(missing)}"
        )
    print("Compatible newer BTC decision policy already installed; no changes needed")
