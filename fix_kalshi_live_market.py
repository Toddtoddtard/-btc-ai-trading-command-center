from pathlib import Path
import re

p = Path('app.py')
s = p.read_text()

pattern = re.compile(
    r'@st\.cache_data\(ttl=3, show_spinner=False\)\ndef fetch_kalshi_bitcoin_markets\(\):\n.*?\n\ndef kalshi_probability\(',
    re.S,
)
m = pattern.search(s)
if not m:
    raise SystemExit('Kalshi market function anchor not found')

replacement = '''@st.cache_data(ttl=3, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
    """Find the active KXBTC15M contract first, then exact-fetch its target."""
    errors = []
    for base in KALSHI_BASES:
        for params in (
            {"limit": 100, "status": "open", "series_ticker": "KXBTC15M"},
            {"limit": 100, "series_ticker": "KXBTC15M"},
        ):
            try:
                payload, ms = http_json(base + "/markets", params, timeout=3.0)
                markets = payload.get("markets", []) if isinstance(payload, dict) else []
                now_ts = time.time()
                hits = []

                for market in markets:
                    ticker = str(market.get("ticker") or "")
                    if not ticker.upper().startswith("KXBTC15M-"):
                        continue
                    close_ts = kalshi_close_timestamp(market)
                    row = dict(market)
                    row["_close_ts"] = close_ts
                    row["_seconds_remaining"] = (
                        max(0, int(close_ts - now_ts)) if pd.notna(close_ts) else np.nan
                    )
                    row["_target"] = kalshi_numeric_target(market)
                    hits.append(row)

                future = [
                    row for row in hits
                    if pd.notna(row["_close_ts"]) and row["_close_ts"] > now_ts
                ]
                if not future:
                    continue

                current = min(
                    future,
                    key=lambda row: (row["_close_ts"], str(row.get("ticker", ""))),
                )

                exact = fetch_exact_kalshi_market(current.get("ticker", ""))
                if exact:
                    merged = dict(current)
                    merged.update(exact)
                    exact_target = kalshi_numeric_target(exact)
                    exact_close_ts = kalshi_close_timestamp(exact)
                    if pd.notna(exact_target) and exact_target > 0:
                        merged["_target"] = float(exact_target)
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
                }
            except Exception as exc:
                errors.append(str(exc))

    return {
        "ok": False,
        "markets": [],
        "current": None,
        "feed_ms": np.nan,
        "error": " | ".join(errors[-4:]),
    }


def kalshi_probability('''

s = s[:m.start()] + replacement + s[m.end():]
s = s.replace(
    'APP_VERSION = "2026.09.04-r31-kalshi-timer-reliable"',
    'APP_VERSION = "2026.09.04-r32-kalshi-live-market-fix"',
)
compile(s, 'app.py', 'exec')
p.write_text(s)
print('R32 app repair applied: active ticker first, exact Kalshi target second.')
