#!/usr/bin/env python3
"""Apply v16 BTC decision fixes to app.py.

This is intentionally narrow: it does not touch live-money execution. It fixes
three deadlock conditions discovered in the audit:
1) scalp move threshold was effectively ~0.56 council score in low-volatility BTC,
2) Kalshi contract price was incorrectly used as a hard BTC scalp veto,
3) comments still described the precision layer as a second trade gate.
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
if old_up not in s:
    raise SystemExit("v16 scalp threshold anchor not found")
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
