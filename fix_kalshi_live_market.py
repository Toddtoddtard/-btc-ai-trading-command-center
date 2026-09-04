from pathlib import Path
import re

p = Path('app.py')
s = p.read_text()

# Ensure ZoneInfo is available for deterministic Kalshi 15m ticker construction.
if 'from zoneinfo import ZoneInfo' not in s:
    import_anchor = 'from datetime import datetime, timezone'
    if import_anchor in s:
        s = s.replace(import_anchor, import_anchor + '\nfrom zoneinfo import ZoneInfo', 1)
    else:
        s = 'from zoneinfo import ZoneInfo\n' + s

pattern = re.compile(
    r'@st\.cache_data\(ttl=3, show_spinner=False\)\ndef fetch_kalshi_bitcoin_markets\(\):\n.*?\n\ndef kalshi_probability\(',
    re.S,
)
m = pattern.search(s)
if not m:
    raise SystemExit('Kalshi market function anchor not found')

replacement = '''def _kalshi_15m_boundary(now_ts=None):
    """Return the next Kalshi 15m close boundary in America/New_York."""
    now_ts = time.time() if now_ts is None else float(now_ts)
    ny = datetime.fromtimestamp(now_ts, tz=ZoneInfo("America/New_York"))
    minute = ((ny.minute // 15) + 1) * 15
    if minute >= 60:
        close_ny = ny.replace(minute=0, second=0, microsecond=0) + pd.Timedelta(hours=1)
    else:
        close_ny = ny.replace(minute=minute, second=0, microsecond=0)
    return close_ny


def _kalshi_15m_ticker(close_ny):
    mon = close_ny.strftime("%b").upper()
    return f"KXBTC15M-{close_ny.strftime('%y')}{mon}{close_ny.strftime('%d%H%M')}-{close_ny.strftime('%M')}"


@st.cache_data(ttl=3, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
    """Resolve the active KXBTC15M contract robustly.

    Primary path: construct the exact active ticker from the next 15-minute
    New York boundary and fetch that exact market directly. This avoids Kalshi
    list/status lag. Secondary path: series-list discovery for resilience.
    """
    now_ts = time.time()
    errors = []

    # Deterministic exact-ticker path. Try the expected active close first,
    # then adjacent boundaries in case Kalshi publishes a few seconds early/late.
    expected_close = _kalshi_15m_boundary(now_ts)
    for offset_min in (0, 15, -15):
        close_ny = expected_close + pd.Timedelta(minutes=offset_min)
        ticker = _kalshi_15m_ticker(close_ny)
        exact = fetch_exact_kalshi_market(ticker)
        if not exact:
            continue
        exact_close_ts = kalshi_close_timestamp(exact)
        if pd.isna(exact_close_ts):
            exact_close_ts = float(close_ny.timestamp())
        if exact_close_ts <= now_ts:
            continue
        target = kalshi_numeric_target(exact)
        row = dict(exact)
        row["ticker"] = ticker
        row["_close_ts"] = exact_close_ts
        row["_seconds_remaining"] = max(0, int(exact_close_ts - now_ts))
        row["_target"] = target
        return {
            "ok": True,
            "markets": [row],
            "current": row,
            "feed_ms": np.nan,
            "error": None,
            "resolution": "deterministic-exact-ticker",
        }

    # Fallback: discover from the KXBTC15M series list, but never require target
    # fields in the list response. Canonical target still comes from exact ticker.
    for base in KALSHI_BASES:
        for params in (
            {"limit": 100, "status": "open", "series_ticker": "KXBTC15M"},
            {"limit": 100, "series_ticker": "KXBTC15M"},
        ):
            try:
                payload, ms = http_json(base + "/markets", params, timeout=3.0)
                markets = payload.get("markets", []) if isinstance(payload, dict) else []
                hits = []
                for market in markets:
                    ticker = str(market.get("ticker") or "")
                    if not ticker.upper().startswith("KXBTC15M-"):
                        continue
                    close_ts = kalshi_close_timestamp(market)
                    if pd.isna(close_ts) or close_ts <= now_ts:
                        continue
                    row = dict(market)
                    row["_close_ts"] = close_ts
                    row["_seconds_remaining"] = max(0, int(close_ts - now_ts))
                    row["_target"] = kalshi_numeric_target(market)
                    hits.append(row)
                if not hits:
                    continue
                current = min(hits, key=lambda row: (row["_close_ts"], str(row.get("ticker", ""))))
                exact = fetch_exact_kalshi_market(current.get("ticker", ""))
                if exact:
                    merged = dict(current)
                    merged.update(exact)
                    target = kalshi_numeric_target(exact)
                    exact_close_ts = kalshi_close_timestamp(exact)
                    if pd.notna(target) and target > 0:
                        merged["_target"] = float(target)
                    if pd.notna(exact_close_ts):
                        merged["_close_ts"] = exact_close_ts
                        merged["_seconds_remaining"] = max(0, int(exact_close_ts - now_ts))
                    current = merged
                return {
                    "ok": True,
                    "markets": hits[:25],
                    "current": current,
                    "feed_ms": ms,
                    "error": None,
                    "resolution": "series-fallback",
                }
            except Exception as exc:
                errors.append(str(exc))

    # Last-resort timer seed: even if Kalshi API is temporarily unreachable,
    # the 15m countdown remains usable from the official quarter-hour schedule.
    close_ny = expected_close
    synthetic_close = float(close_ny.timestamp())
    ticker = _kalshi_15m_ticker(close_ny)
    row = {
        "ticker": ticker,
        "title": "BTC price up in next 15 mins?",
        "close_time": close_ny.astimezone(timezone.utc).isoformat(),
        "_close_ts": synthetic_close,
        "_seconds_remaining": max(0, int(synthetic_close - now_ts)),
        "_target": np.nan,
    }
    return {
        "ok": True,
        "markets": [row],
        "current": row,
        "feed_ms": np.nan,
        "error": " | ".join(errors[-4:]),
        "resolution": "schedule-only-fallback",
    }


def kalshi_probability('''

s = s[:m.start()] + replacement + s[m.end():]
s = re.sub(
    r'APP_VERSION\s*=\s*"[^"]+"',
    'APP_VERSION = "2026.09.04-r33-deterministic-kalshi-market"',
    s,
    count=1,
)
compile(s, 'app.py', 'exec')
p.write_text(s)
print('R33 applied: deterministic KXBTC15M ticker + exact target + schedule timer fallback.')
