from pathlib import Path
import re

p = Path("app.py")
s = p.read_text(encoding="utf-8")
original = s

new_resolver = '''def resolve_predictions(hist, current_price=None):
    """Resolve expired journal rows at the 1m candle nearest each target time.

    Recent targets use the already-loaded dashboard history. Older targets that
    fall outside that window are backfilled directly from Binance around the
    row's exact target timestamp.
    """
    now_ts = int(time.time())

    hist2 = pd.DataFrame()
    if hist is not None and not hist.empty:
        hist2 = hist.copy()
        hist2["_ts"] = pd.to_datetime(hist2["time"], utc=True, errors="coerce")
        hist2 = hist2.dropna(subset=["_ts"])

    def _price_near_target(target_ts):
        target_dt = pd.to_datetime(int(target_ts), unit="s", utc=True)

        # Fast path: use the dashboard's in-memory 1m candles when the target is
        # inside that recent window. Require the nearest candle to be close
        # enough that we do not accidentally grade an old prediction on today's price.
        if not hist2.empty:
            deltas = (hist2["_ts"] - target_dt).abs()
            idx = deltas.idxmin()
            if pd.notna(idx) and deltas.loc[idx] <= pd.Timedelta(minutes=2):
                price = safe_float(hist2.loc[idx, "close"])
                if pd.notna(price) and price > 0:
                    return price

        # Backfill path for legacy/older rows. Ask Binance for a few 1m candles
        # bracketing the exact target time, then choose the closest candle open.
        start_ms = max(0, (int(target_ts) - 120) * 1000)
        end_ms = (int(target_ts) + 120) * 1000
        try:
            rows, _ = try_bases(
                SPOT_BASES,
                "/api/v3/klines",
                {
                    "symbol": SYMBOL,
                    "interval": "1m",
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": 5,
                },
                timeout=3.2,
            )
            if not rows:
                return np.nan

            best_price = np.nan
            best_delta = None
            target_ms = int(target_ts) * 1000
            for candle in rows:
                try:
                    open_ms = int(candle[0])
                    close_price = safe_float(candle[4])
                    if pd.isna(close_price) or close_price <= 0:
                        continue
                    delta = abs(open_ms - target_ms)
                    if best_delta is None or delta < best_delta:
                        best_delta = delta
                        best_price = close_price
                except Exception:
                    continue
            return best_price
        except Exception:
            return np.nan

    with db_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM predictions
               WHERE target_ts<=?
                 AND (
                    resolved=0
                    OR (resolved=1 AND correct IS NULL AND action NOT IN ('HOLD','WAIT'))
                 )
               ORDER BY id ASC LIMIT 250""",
            (now_ts,),
        ).fetchall()

        updated = 0
        for row in rows:
            start_price = safe_float(row["price"])
            if pd.isna(start_price) or start_price <= 0:
                continue

            resolved_price = _price_near_target(int(row["target_ts"]))
            if pd.isna(resolved_price) or resolved_price <= 0:
                continue

            ret = (resolved_price / start_price - 1.0) * 100.0
            action = str(row["action"] or "HOLD").upper().strip()
            strike = safe_float(row["target_price"])

            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)
            else:
                # HOLD/WAIT are resolved observations, not directional wins/losses.
                correct = None

            conn.execute(
                "UPDATE predictions SET resolved=1,resolved_price=?,return_pct=?,correct=? WHERE id=?",
                (resolved_price, ret, correct, int(row["id"])),
            )
            updated += 1

        conn.commit()
    return updated
'''

s, n = re.subn(
    r'def resolve_predictions\(hist, current_price=None\):.*?(?=\ndef recent_predictions\(limit=100\):)',
    new_resolver + '\n',
    s,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit("current prediction resolver anchor not found")

s = re.sub(
    r'APP_VERSION = "[^"]+"',
    'APP_VERSION = "2026.09.05-r45-journal-backfill"',
    s,
    count=1,
)

if s == original:
    raise SystemExit("no changes made")

p.write_text(s, encoding="utf-8")
print("Added historical Binance backfill for expired prediction rows")
