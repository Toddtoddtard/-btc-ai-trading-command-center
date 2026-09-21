"""Normalize keyless, read-only public BTC perpetual-market data."""

from __future__ import annotations

import math


def _finite(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def parse_bybit_futures_snapshot(ticker_payload, orderbook_payload):
    """Return council fields from Bybit V5 ticker and order-book responses."""
    ticker_rows = ((ticker_payload or {}).get("result") or {}).get("list") or []
    ticker = ticker_rows[0] if ticker_rows else {}
    book = (orderbook_payload or {}).get("result") or {}
    bids = sum(
        (_finite(row[0], 0.0) or 0.0) * (_finite(row[1], 0.0) or 0.0)
        for row in (book.get("b") or [])
        if isinstance(row, (list, tuple)) and len(row) >= 2
    )
    asks = sum(
        (_finite(row[0], 0.0) or 0.0) * (_finite(row[1], 0.0) or 0.0)
        for row in (book.get("a") or [])
        if isinstance(row, (list, tuple)) and len(row) >= 2
    )
    denominator = bids + asks
    funding = _finite(ticker.get("fundingRate"))
    mark = _finite(ticker.get("markPrice"))
    open_interest = _finite(ticker.get("openInterest"))
    if funding is None or mark is None or open_interest is None or not denominator:
        raise ValueError("Incomplete Bybit public futures snapshot")
    return {
        "funding_rate": funding,
        "mark_price": mark,
        "open_interest": open_interest,
        "bid_notional": bids,
        "ask_notional": asks,
        "book_imbalance": (bids - asks) / denominator,
        "source": "Bybit public BTCUSDT perpetual",
        "ok": True,
    }
