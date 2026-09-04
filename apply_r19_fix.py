from pathlib import Path
import ast

p = Path('app.py')
text = p.read_text()

text = text.replace(
    'APP_VERSION = "2026.09.04-single-file-r18-remote-24x7-learning"',
    'APP_VERSION = "2026.09.04-single-file-r19-canonical-kalshi-target"'
)

anchor = '@st.cache_data(ttl=3, show_spinner=False)\ndef fetch_kalshi_bitcoin_markets():\n'
helpers = '''def kalshi_numeric_target(market):
    """Return the numeric settlement strike exactly as Kalshi exposes it."""
    if not isinstance(market, dict):
        return np.nan
    strike_type = str(market.get("strike_type") or "").lower()
    preferred = (
        ("cap_strike", "floor_strike")
        if strike_type in {"less", "less_equal", "less-than", "less_than"}
        else ("floor_strike", "cap_strike")
    )
    for key in preferred:
        value = safe_float(market.get(key))
        if pd.notna(value) and value > 0:
            return float(value)
    return np.nan


def kalshi_close_timestamp(market):
    if not isinstance(market, dict):
        return np.nan
    raw_close = (
        market.get("close_time")
        or market.get("expiration_time")
        or market.get("expected_expiration_time")
    )
    if not raw_close:
        return np.nan
    try:
        return float(pd.Timestamp(raw_close).timestamp())
    except Exception:
        return np.nan


def fetch_exact_kalshi_market(ticker):
    """Read one exact Kalshi market by ticker to canonicalize its strike."""
    if not ticker:
        return None
    for base in KALSHI_BASES:
        try:
            payload, _ = http_json(base + "/markets/" + str(ticker), timeout=3.0)
            market = payload.get("market") if isinstance(payload, dict) else None
            if isinstance(market, dict):
                return market
        except Exception:
            continue
    return None


@st.cache_data(ttl=3, show_spinner=False)
def fetch_kalshi_bitcoin_markets():
'''
assert anchor in text
text = text.replace(anchor, helpers, 1)

old = '''                target = safe_float(market.get("floor_strike"))
                if pd.isna(target) or target <= 0:
                    target = safe_float(market.get("cap_strike"))
                if pd.isna(target) or target <= 0:
                    continue

                raw_close = (
                    market.get("close_time")
                    or market.get("expiration_time")
                    or market.get("expected_expiration_time")
                )
                close_ts = np.nan
                if raw_close:
                    try:
                        close_ts = pd.Timestamp(raw_close).timestamp()
                    except Exception:
                        pass
'''
new = '''                target = kalshi_numeric_target(market)
                if pd.isna(target) or target <= 0:
                    continue

                close_ts = kalshi_close_timestamp(market)
'''
assert old in text
text = text.replace(old, new, 1)

old = '''            current = (
                min(future, key=lambda row: row["_close_ts"])
                if future else (hits[0] if hits else None)
            )

            return {
'''
new = '''            current = (
                min(future, key=lambda row: (row["_close_ts"], str(row.get("ticker", ""))))
                if future else (hits[0] if hits else None)
            )

            if current:
                exact = fetch_exact_kalshi_market(current.get("ticker", ""))
                if exact:
                    exact_target = kalshi_numeric_target(exact)
                    exact_close_ts = kalshi_close_timestamp(exact)
                    merged = dict(current)
                    merged.update(exact)
                    if pd.notna(exact_target):
                        merged["_target"] = exact_target
                    if pd.notna(exact_close_ts):
                        merged["_close_ts"] = exact_close_ts
                        merged["_seconds_remaining"] = max(0, int(exact_close_ts - now_ts))
                    current = merged

            return {
'''
assert old in text
text = text.replace(old, new, 1)

start = text.index('def stable_kalshi_contract(kalshi, spot_price):')
end = text.index('\n\n@st.cache_data(ttl=10, show_spinner=False)', start)
newfunc = '''def stable_kalshi_contract(kalshi, spot_price):
    """Return one canonical Kalshi 15-minute contract for the whole app.

    Exact ticker + strike stay paired until expiry so chart, metrics,
    LOCK/SCALP decisions, paper trading and learning cannot drift apart.
    """
    live = current_kalshi_context(kalshi, spot_price)
    cached = st.session_state.get("kalshi_contract_snapshot")
    now_ts = time.time()

    def cache_expired(snapshot):
        if not snapshot:
            return True
        raw = snapshot.get("close_time")
        if not raw:
            return False
        try:
            return pd.Timestamp(raw).timestamp() <= now_ts
        except Exception:
            return False

    should_replace = (
        cached is None
        or pd.isna(cached.get("target", np.nan))
        or cache_expired(cached)
    )

    if live.get("available") and should_replace:
        cached = {
            "available": True,
            "ticker": live.get("ticker", ""),
            "title": live.get("title", "BTC 15 min"),
            "target": live.get("target", np.nan),
            "close_time": live.get("close_time"),
            "market": live.get("market"),
        }
        st.session_state["kalshi_contract_snapshot"] = cached

    if cached:
        result = dict(cached)
        if live.get("available") and live.get("ticker") == result.get("ticker"):
            result["up_probability"] = live.get("up_probability", np.nan)
            result["market"] = live.get("market", result.get("market"))
        else:
            result["up_probability"] = kalshi_probability(result.get("market"))

        try:
            close_ts = pd.Timestamp(result.get("close_time")).timestamp()
            result["seconds_remaining"] = max(0, int(close_ts - now_ts))
        except Exception:
            result["seconds_remaining"] = np.nan

        result["distance"] = (
            spot_price - result["target"]
            if pd.notna(result.get("target", np.nan)) else np.nan
        )
        result["distance_pct"] = (
            result["distance"] / result["target"]
            if pd.notna(result.get("distance", np.nan)) and result.get("target")
            else np.nan
        )
        result["available"] = True
        return result

    return live
'''
text = text[:start] + newfunc + text[end:]

js_start = text.index('        async function fetchKalshiTarget() {{')
js_end = text.index('\n\n        async function updateCandles() {{', js_start)
newjs = '''        function numericKalshiTarget(m) {{
            if (!m) return NaN;
            const strikeType = String(m.strike_type || "").toLowerCase();
            const preferCap = ["less", "less_equal", "less-than", "less_than"].includes(strikeType);
            const first = Number(preferCap ? m.cap_strike : m.floor_strike);
            const second = Number(preferCap ? m.floor_strike : m.cap_strike);
            if (Number.isFinite(first) && first > 0) return first;
            if (Number.isFinite(second) && second > 0) return second;
            return NaN;
        }}

        async function exactKalshiMarket(ticker) {{
            if (!ticker) return null;
            try {{
                const url = "https://external-api.kalshi.com/trade-api/v2/markets/" + encodeURIComponent(ticker);
                const resp = await fetch(url, {{cache:"no-store"}});
                if (!resp.ok) return null;
                const payload = await resp.json();
                return payload && payload.market ? payload.market : null;
            }} catch (e) {{ return null; }}
        }}

        async function fetchKalshiTarget() {{
            const url =
                "https://external-api.kalshi.com/trade-api/v2/markets" +
                "?limit=100&status=open&series_ticker=KXBTC15M";

            try {{
                const resp = await fetch(url, {{cache:"no-store"}});
                if (!resp.ok) return null;
                const payload = await resp.json();
                const markets = Array.isArray(payload.markets) ? payload.markets : [];
                const now = Date.now();

                const parsed = markets.map(m => {{
                    const closeRaw = m.close_time || m.expiration_time || m.expected_expiration_time;
                    return {{
                        raw: m,
                        ticker: String(m.ticker || ""),
                        target: numericKalshiTarget(m),
                        closeMs: parseTime(closeRaw)
                    }};
                }}).filter(m =>
                    Number.isFinite(m.target) && m.target > 0 &&
                    Number.isFinite(m.closeMs) && m.closeMs > now
                );

                const pinned = parsed.find(m => m.ticker === currentTicker);
                let selected = pinned || null;
                if (!selected) {{
                    parsed.sort((a,b) => (a.closeMs - b.closeMs) || a.ticker.localeCompare(b.ticker));
                    selected = parsed.length ? parsed[0] : null;
                }}
                if (!selected) return null;

                const exact = await exactKalshiMarket(selected.ticker);
                if (exact) {{
                    const exactTarget = numericKalshiTarget(exact);
                    const exactClose = parseTime(exact.close_time || exact.expiration_time || exact.expected_expiration_time);
                    if (Number.isFinite(exactTarget) && exactTarget > 0) selected.target = exactTarget;
                    if (Number.isFinite(exactClose)) selected.closeMs = exactClose;
                }}
                return selected;
            }} catch (e) {{ return null; }}
        }}'''
text = text[:js_start] + newjs + text[js_end:]

text = text.replace(
    'f"Live Kalshi market: {kctx[\'ticker\']} • target comes "\n                "from Kalshi. The candles use this app\'s Binance 1-minute feed "',
    'f"Live Kalshi market: {kctx[\'ticker\']} • target is fetched from "\n                "that exact Kalshi ticker and shared by the chart, LOCK/SCALP engine, "\n                "paper signals, and learner. The candles use this app\'s Binance 1-minute feed "'
)

ast.parse(text)
p.write_text(text)
print('app.py r19 patch applied and syntax checked')
