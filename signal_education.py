"""Named, causal signal experiments; official outcomes only, no execution.

Definitions and sources: docs/SIGNAL_EDUCATION.md.
"""
import math
import time
import pandas as pd
from candle_learning import closed_frame
from kalshi_paper_engine import kalshi_taker_fee


def detect_signals(rows, now=None):
    now = time.time() if now is None else float(now)
    f = closed_frame(rows, now).tail(120)
    if len(f) < 61 or not (f.time.diff().dropna() == pd.Timedelta(minutes=1)).all():
        return []
    a, b = f.iloc[-1], f.iloc[-2]
    closed_at = a.time.timestamp() + 60
    if now - closed_at > 120:
        return []
    prior = f.iloc[:-1].tail(20)
    mean_volume = float(prior.volume.mean())
    volume_ratio = float(a.volume / mean_volume) if mean_volume > 0 else 0.0
    trend = 'UP' if a.close > f.close.iloc[-16] else 'DOWN' if a.close < f.close.iloc[-16] else 'FLAT'
    signals = []

    def add(name, direction, evidence, invalidation):
        signals.append(dict(name=name, direction=direction, observed_at=now,
                            candle_closed_at=closed_at, trend=trend,
                            volume_ratio=volume_ratio, evidence=evidence,
                            invalidation=invalidation, version=1))

    if b.close < b.open and a.close > a.open and a.open <= b.close and a.close >= b.open:
        add('Bullish engulfing', 'YES', 'Bullish body engulfs the previous bearish body', float(a.low))
    if b.close > b.open and a.close < a.open and a.open >= b.close and a.close <= b.open:
        add('Bearish engulfing', 'NO', 'Bearish body engulfs the previous bullish body', float(a.high))
    macd = f.close.ewm(span=12, adjust=False).mean() - f.close.ewm(span=26, adjust=False).mean()
    hist = macd - macd.ewm(span=9, adjust=False).mean()
    if hist.iloc[-2] <= 0 < hist.iloc[-1]:
        add('Bullish MACD crossover', 'YES', '12/26 MACD crossed above its 9-period signal', float(a.low))
    if hist.iloc[-2] >= 0 > hist.iloc[-1]:
        add('Bearish MACD crossover', 'NO', '12/26 MACD crossed below its 9-period signal', float(a.high))
    if volume_ratio >= 1.5 and a.close > prior.high.max():
        add('Volume breakout up', 'YES', 'Close above prior 20-bar high with at least 1.5x volume', float(prior.high.max()))
    if volume_ratio >= 1.5 and a.close < prior.low.min():
        add('Volume breakout down', 'NO', 'Close below prior 20-bar low with at least 1.5x volume', float(prior.low.min()))
    return signals


def summarize_signals(history):
    """One earliest observation per named signal and market, in retained history.

    YES/NO tests the signal direction against the contract strike, not merely
    spot-price movement. Uncalibrated patterns are never assigned a probability.
    """
    seen = set()
    buckets = {}
    for row in sorted(history, key=lambda x: x.get('opened_at', 0)):
        if row.get('result') not in ('yes', 'no'):
            continue
        for signal in row.get('named_signals', []):
            key = (row.get('ticker'), signal['name'])
            observed = signal.get('observed_at', float('inf'))
            if (key in seen or not row.get('ticker') or
                    not signal.get('candle_closed_at', float('inf')) <= observed <= row.get('opened_at', 0) < row.get('expires_at', 0)):
                continue
            side = signal.get('direction')
            ask = row.get('yes_ask' if side == 'YES' else 'no_ask')
            if side not in ('YES', 'NO') or not isinstance(ask, (int, float)) or not math.isfinite(ask) or not 0 < ask < 1:
                continue
            seen.add(key)
            won = side.lower() == row['result']
            pnl = float(won) - ask - kalshi_taker_fee(1, ask)
            for context in ('ALL', signal.get('trend', 'UNKNOWN') + ' / ' + row.get('phase', 'UNKNOWN')):
                bucket = buckets.setdefault((signal['name'], context), dict(signal=signal['name'], context=context, samples=0, wins=0, net_pnl=0.0))
                bucket['samples'] += 1
                bucket['wins'] += int(won)
                bucket['net_pnl'] += pnl
    for bucket in buckets.values():
        bucket['accuracy'] = bucket['wins'] / bucket['samples']
    return dict(version=1, affects_execution=False, paper_only=True,
                scope='Retained official-settlement research history; one observation per signal per market',
                ranking=sorted(buckets.values(), key=lambda b: (-b['samples'], b['signal'], b['context'])))
