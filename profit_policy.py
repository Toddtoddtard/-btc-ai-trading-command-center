"""Shared paper eligibility economics; forecasts are estimates, never guarantees."""
import math

MIN_NET_EDGE = 0.01  # dollars per contract, after fees
GENERAL_TAKER_FEE_RATE = 0.07


def probability(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and 0 <= value <= 1 else None
    except (TypeError, ValueError):
        return None


def selected_probability(probability_up, side):
    p = probability(probability_up)
    return None if p is None or side not in {'YES', 'NO'} else p if side == 'YES' else 1-p


def taker_fee(contracts, price):
    return math.ceil(GENERAL_TAKER_FEE_RATE * contracts * price * (1-price) * 100 - 1e-12) / 100


def entry_economics(strategy, contracts, entry, value):
    """LOCK value is settlement probability; SCALP value is projected exit bid.

    Ask already includes the entry spread. SCALPs pay both fees. The extra cent
    is a margin for execution/model error, not a claim of calibrated certainty.
    """
    entry, value = probability(entry), probability(value)
    valid = contracts > 0 and entry is not None and 0 < entry < 1 and value is not None
    if not valid:
        return {'approved': False, 'net_pnl': None, 'required_value': None,
                'reason': 'valid price and selected-side forecast required'}
    fee = taker_fee(contracts, entry)
    if strategy == 'SCALP':
        fee += taker_fee(contracts, value)
    net = contracts * (value-entry) - fee
    required = entry + fee/contracts + MIN_NET_EDGE
    return {'approved': net > 0 and net + 1e-12 >= contracts * MIN_NET_EDGE,
            'net_pnl': net, 'required_value': required,
            'reason': 'expected net profit must cover fees plus 1 cent per contract'}
