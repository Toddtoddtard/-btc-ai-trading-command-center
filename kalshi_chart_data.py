"""Read the public Kalshi event chart without substituting exchange prices."""
import json
import math
import re
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

BASES = ('https://external-api.kalshi.com/trade-api/v2',
         'https://api.elections.kalshi.com/trade-api/v2')


def event_ticker(market):
    match = re.fullmatch(r'(KXBTC15M-\d{2}[A-Z]{3}\d{6})(?:-\d+)?', str(market or ''))
    return match.group(1) if match else ''


def parse_chart(payload, event, now=None):
    now = time.time() if now is None else now
    live = payload.get('live_data') or {}
    details = live.get('details') or {}
    if (live.get('type') != 'crypto' or live.get('is_historical') is not False
            or details.get('coin') != 'BTC' or details.get('event_ticker') != event):
        raise ValueError('Not the active BTC event chart')
    maturity = float(details.get('maturity_ts_ms', 0)) / 1000
    if not now < maturity <= (int(now // 900) + 1) * 900:
        raise ValueError('Expired or future Kalshi event')
    points = []
    for point in details.get('timeseries') or []:
        try:
            ts, value = float(point['t']) / 1000, float(point['v'])
            if math.isfinite(ts) and math.isfinite(value) and value > 1000 and ts <= now + 5:
                points.append((ts, value))
        except (ValueError, TypeError, KeyError):
            continue
    if not points:
        raise ValueError('Kalshi chart has no valid price ticks')
    timestamp, price = max(points)
    if now - timestamp > 30:
        raise ValueError('Kalshi chart price is stale')
    candles = {}
    for row in (details.get('candlesticks') or {}).get('1M', []):
        try:
            ts = float(row['open_ts_ms']) / 1000
            o, h, l, c = (float(row[k]) for k in ('open', 'high', 'low', 'close'))
            if not all(math.isfinite(v) for v in (ts, o, h, l, c)):
                continue
            if not (0 < ts <= timestamp and min(o, c) >= l > 1000 and h >= max(o, c)):
                continue
            candles[ts] = dict(time=datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                               open=o, high=h, low=l, close=c)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    rows = [candles[t] for t in sorted(candles)][-60:]
    if not rows or timestamp - max(candles) > 120:
        raise ValueError('Kalshi chart candles are missing or stale')
    return dict(available=True, price=price, timestamp=timestamp, candles=rows,
                event_ticker=event, source='Kalshi BTC/USD chart feed')


def fetch_chart(market, fetch_json=None, now=None):
    event = event_ticker(market)
    if not event:
        return dict(available=False, error='Active Kalshi BTC event unavailable')
    def read(url):
        req = Request(url, headers={'User-Agent': 'BTC-AI-Command-Center/1.0', 'Cache-Control': 'no-cache'})
        with urlopen(req, timeout=6) as response:
            return json.load(response)
    errors = []
    for base in BASES:
        try:
            payload = (fetch_json or read)(base + '/live_data/events/' + event + '?range=1h')
            return parse_chart(payload, event, now)
        except Exception as exc:
            errors.append(str(exc))
    return dict(available=False, error='; '.join(errors))
