"""When an official settlement label was available to this learner."""
import math
from datetime import datetime

LEGACY_SETTLEMENT_LAG_SECONDS = 120


def timestamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None
            value = stamp.timestamp()
        except (TypeError, ValueError):
            return None
    return value if math.isfinite(value) else None


def outcome_available_at(row, expires_at):
    expiry = timestamp(expires_at)
    if expiry is None:
        return float('inf')
    value = row.get('official_observed_at', row.get('result_observed_at'))
    if value is not None:
        observed = timestamp(value)
        return max(expiry, observed) if observed is not None else float('inf')
    # Older records cannot establish the real poll time. This is explicitly an
    # assumption for legacy replay, not evidence of an instantaneous settlement.
    return expiry + LEGACY_SETTLEMENT_LAG_SECONDS
