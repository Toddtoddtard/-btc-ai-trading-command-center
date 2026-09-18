"""Concurrent loading for independent dashboard market-data feeds."""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd


def load_live_feeds(
    fetch_spot_ticker,
    fetch_klines,
    fetch_agg_trades,
    fetch_futures_snapshot,
    fetch_kalshi_markets,
    fetch_hourly_kalshi_markets,
    enrich_history,
    fetch_kalshi_reference=None,
):
    """Load independent feeds concurrently and return normalized results.

    The callables are injected so the orchestration can be tested without
    network access. Feed freshness, values, and exception behavior match the
    former inline implementation in ``app.py``.
    """
    errors = []
    with ThreadPoolExecutor(max_workers=7, thread_name_prefix="live-feed") as pool:
        jobs = {
            "ticker": pool.submit(fetch_spot_ticker),
            "klines": pool.submit(fetch_klines, "1m", 500),
            "trades": pool.submit(fetch_agg_trades, 600),
            "futures": pool.submit(fetch_futures_snapshot),
            "kalshi": pool.submit(fetch_kalshi_markets),
            "hourly_kalshi": pool.submit(fetch_hourly_kalshi_markets),
        }
        if fetch_kalshi_reference is not None:
            jobs["kalshi_reference"] = pool.submit(fetch_kalshi_reference)

        try:
            ticker = jobs["ticker"].result()
        except Exception as exc:
            ticker = {
                "price": np.nan,
                "change_24h": np.nan,
                "quote_volume_24h": np.nan,
                "feed_ms": np.nan,
                "source": "Unavailable",
            }
            errors.append(f"Spot ticker: {exc}")

        try:
            raw_history, kline_ms = jobs["klines"].result()
            history = enrich_history(raw_history)
        except Exception as exc:
            history, kline_ms = pd.DataFrame(), np.nan
            errors.append(f"Klines: {exc}")

        try:
            aggregate_trades, aggregate_ms = jobs["trades"].result()
        except Exception as exc:
            aggregate_trades, aggregate_ms = pd.DataFrame(), np.nan
            errors.append(f"Aggregate trades: {exc}")

        futures = jobs["futures"].result()
        kalshi = jobs["kalshi"].result()
        hourly_kalshi = jobs["hourly_kalshi"].result()
        try:
            kalshi_reference = (
                jobs["kalshi_reference"].result()
                if "kalshi_reference" in jobs else {}
            )
        except Exception as exc:
            kalshi_reference = {
                "available": False,
                "healthy": False,
                "price": np.nan,
                "source": "Kalshi reference unavailable",
            }
            errors.append(f"Kalshi reference: {exc}")

    return {
        "ticker": ticker,
        "history": history,
        "kline_ms": kline_ms,
        "aggregate_trades": aggregate_trades,
        "aggregate_ms": aggregate_ms,
        "futures": futures,
        "kalshi": kalshi,
        "hourly_kalshi": hourly_kalshi,
        "kalshi_reference": kalshi_reference,
        "errors": errors,
    }
