"""Closed-candle resolution only; never borrow a future or distant price."""
import pandas as pd

def closed_price_at(hist, expires_at):
    if hist is None or hist.empty:
        return None
    ends = pd.to_datetime(hist['time'], utc=True, errors='coerce') + pd.Timedelta(minutes=1)
    expiry = pd.Timestamp(expires_at)
    expiry = expiry.tz_localize('UTC') if expiry.tzinfo is None else expiry.tz_convert('UTC')
    age = (expiry - ends).dt.total_seconds()
    eligible = hist.loc[(age >= 0) & (age < 60)].copy()
    if eligible.empty:
        return None
    value = float(eligible.iloc[-1]['close'])
    return value if pd.notna(value) and 0 < value < float('inf') else None
