"""Free, Kalshi-aligned BTC/USD reference-price estimator.

KXBTC15M settles from CF Benchmarks' BRTI, not Binance BTCUSDT.  The official
BRTI stream requires a licensed key, so the paper dashboard uses a robust
median of public BTC/USD venues as a clearly-labelled estimate.  Binance data
remains useful for candles, futures and order flow, but must not be treated as
the Kalshi settlement price.
"""
from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median
from urllib.request import Request, urlopen


VENUES = {
    "Coinbase USD": "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
    "Kraken USD": "https://api.kraken.com/0/public/Ticker?pair=XBTUSD",
    "Bitstamp USD": "https://www.bitstamp.net/api/v2/ticker/btcusd/",
    "Gemini USD": "https://api.gemini.com/v1/pubticker/btcusd",
}


def _finite_price(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 1_000 else None
    except Exception:
        return None


def _read_json(url, timeout=2.2):
    request = Request(url, headers={"User-Agent": "BTC-AI-Command-Center/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_price(name, payload):
    if name == "Coinbase USD":
        return _finite_price(payload.get("price"))
    if name == "Kraken USD":
        result = payload.get("result") or {}
        row = next(iter(result.values()), {})
        close = row.get("c") or []
        return _finite_price(close[0] if close else None)
    return _finite_price(payload.get("last"))


def fetch_kalshi_reference(fetch_json=None, max_deviation=0.005):
    """Return a robust public BTC/USD proxy for BRTI with feed diagnostics."""
    started = time.perf_counter()
    fetch_json = fetch_json or _read_json
    quotes = {}
    errors = {}

    def load(name, url):
        return name, _parse_price(name, fetch_json(url))

    with ThreadPoolExecutor(max_workers=len(VENUES), thread_name_prefix="btc-usd") as pool:
        jobs = [pool.submit(load, name, url) for name, url in VENUES.items()]
        for job in as_completed(jobs):
            try:
                name, price = job.result()
                if price is not None:
                    quotes[name] = price
                else:
                    errors[name] = "invalid price"
            except Exception as exc:
                errors[getattr(exc, "venue", "venue")] = str(exc)

    if not quotes:
        return {
            "available": False,
            "price": None,
            "source": "Kalshi reference unavailable",
            "samples": 0,
            "dispersion_pct": None,
            "healthy": False,
            "quotes": {},
            "errors": errors,
            "feed_ms": (time.perf_counter() - started) * 1000.0,
        }

    center = median(quotes.values())
    filtered = {
        name: value for name, value in quotes.items()
        if abs(value / center - 1.0) <= max_deviation
    }
    if not filtered:
        filtered = quotes
    price = float(median(filtered.values()))
    dispersion = (
        (max(filtered.values()) - min(filtered.values())) / price
        if len(filtered) > 1 else 0.0
    )
    healthy = len(filtered) >= 2 and dispersion <= 0.0035
    return {
        "available": True,
        "price": price,
        "source": f"Kalshi BRTI proxy ({len(filtered)} USD venues)",
        "samples": len(filtered),
        "dispersion_pct": float(dispersion),
        "healthy": healthy,
        "quotes": filtered,
        "errors": errors,
        "feed_ms": (time.perf_counter() - started) * 1000.0,
    }
