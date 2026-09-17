from threading import Barrier

import pandas as pd

from live_feeds import load_live_feeds


def _load(**overrides):
    calls = {
        "fetch_spot_ticker": lambda: {"price": 100.0},
        "fetch_klines": lambda interval, limit: (
            pd.DataFrame([{"close": 100.0}]),
            11.0,
        ),
        "fetch_agg_trades": lambda limit: (
            pd.DataFrame([{"price": 101.0}]),
            12.0,
        ),
        "fetch_futures_snapshot": lambda: {"funding_rate": 0.0},
        "fetch_kalshi_markets": lambda: {"market": "15m"},
        "fetch_hourly_kalshi_markets": lambda: {"market": "hourly"},
        "enrich_history": lambda frame: frame.assign(enriched=True),
    }
    calls.update(overrides)
    return load_live_feeds(**calls)


def test_load_live_feeds_preserves_normalized_values():
    feeds = _load()

    assert feeds["ticker"]["price"] == 100.0
    assert feeds["kline_ms"] == 11.0
    assert feeds["aggregate_ms"] == 12.0
    assert feeds["history"]["enriched"].all()
    assert feeds["futures"] == {"funding_rate": 0.0}
    assert feeds["kalshi"] == {"market": "15m"}
    assert feeds["hourly_kalshi"] == {"market": "hourly"}
    assert feeds["errors"] == []


def test_load_live_feeds_keeps_existing_optional_feed_fallbacks():
    def fail_ticker():
        raise RuntimeError("ticker offline")

    def fail_trades(_limit):
        raise RuntimeError("trades offline")

    feeds = _load(
        fetch_spot_ticker=fail_ticker,
        fetch_agg_trades=fail_trades,
    )

    assert feeds["ticker"]["source"] == "Unavailable"
    assert feeds["aggregate_trades"].empty
    assert feeds["aggregate_ms"] != feeds["aggregate_ms"]  # NaN
    assert feeds["errors"] == [
        "Spot ticker: ticker offline",
        "Aggregate trades: trades offline",
    ]


def test_load_live_feeds_starts_independent_reads_concurrently():
    barrier = Barrier(6, timeout=1.0)

    def synchronized(value):
        def fetch(*_args):
            barrier.wait()
            return value
        return fetch

    _load(
        fetch_spot_ticker=synchronized({"price": 100.0}),
        fetch_klines=synchronized((pd.DataFrame([{"close": 100.0}]), 1.0)),
        fetch_agg_trades=synchronized((pd.DataFrame(), 1.0)),
        fetch_futures_snapshot=synchronized({}),
        fetch_kalshi_markets=synchronized({}),
        fetch_hourly_kalshi_markets=synchronized({}),
    )
