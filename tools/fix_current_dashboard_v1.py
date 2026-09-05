from pathlib import Path
import re

p = Path("app.py")
s = p.read_text(encoding="utf-8")
original = s

new_resolver = '''def resolve_predictions(hist, current_price=None):
    """Resolve every expired journal row from the nearest real 1m BTC candle.

    The resolver is intentionally batch-oriented so a large legacy journal does
    not make hundreds of HTTP requests during one Streamlit rerun. It also
    repairs legacy rows whose stored target_ts is inconsistent by falling back
    to created_ts + the configured prediction horizon.
    """
    now_ts = int(time.time())
    horizon_seconds = int(PREDICTION_HORIZON_MIN * 60)

    # Use the already-loaded dashboard history first.
    candle_points = []
    if hist is not None and not hist.empty and "time" in hist.columns and "close" in hist.columns:
        hist2 = hist[["time", "close"]].copy()
        hist2["_ts"] = pd.to_datetime(hist2["time"], utc=True, errors="coerce")
        hist2["_epoch"] = (hist2["_ts"].astype("int64") // 10**9).where(hist2["_ts"].notna())
        hist2["close"] = pd.to_numeric(hist2["close"], errors="coerce")
        for _, candle in hist2.dropna(subset=["_epoch", "close"]).iterrows():
            px = safe_float(candle["close"])
            if pd.notna(px) and px > 0:
                candle_points.append((int(candle["_epoch"]), float(px)))

    with db_conn() as conn:
        # created_ts is the reliable expiry gate for legacy rows. A prediction is
        # mature once its full configured horizon has elapsed even if an older
        # build stored a malformed target_ts.
        rows = conn.execute(
            """SELECT * FROM predictions
               WHERE created_ts<=?
                 AND (
                    resolved=0
                    OR (resolved=1 AND correct IS NULL AND action NOT IN ('HOLD','WAIT'))
                 )
               ORDER BY id ASC LIMIT 500""",
            (now_ts - horizon_seconds,),
        ).fetchall()

        if not rows:
            return 0

        prepared = []
        missing_targets = []
        for row in rows:
            created_ts = int(row["created_ts"] or 0)
            expected_target = created_ts + horizon_seconds
            stored_target = int(row["target_ts"] or 0)

            # Normal rows should be almost exactly one horizon apart. If not,
            # self-heal the legacy row using its creation timestamp.
            if stored_target <= 0 or abs(stored_target - expected_target) > 300:
                target_ts = expected_target
            else:
                target_ts = stored_target

            action = str(row["action"] or "HOLD").upper().strip()
            prepared.append((row, target_ts, action))

            # HOLD/WAIT can be marked resolved without a directional grade.
            if action not in {"HOLD", "WAIT"}:
                missing_targets.append(target_ts)

        # Fetch missing historical candles in large chronological batches.
        # Binance allows up to 1000 1m candles per call; keep each batch under
        # ~14 hours and only request ranges that contain prediction targets.
        if missing_targets:
            targets = sorted(set(int(x) for x in missing_targets))
            batches = []
            batch_start = targets[0]
            batch_end = targets[0]
            for target in targets[1:]:
                if target - batch_start <= 800 * 60:
                    batch_end = target
                else:
                    batches.append((batch_start, batch_end))
                    batch_start = batch_end = target
            batches.append((batch_start, batch_end))

            for batch_start, batch_end in batches:
                try:
                    market_rows, _ = try_bases(
                        SPOT_BASES,
                        "/api/v3/klines",
                        {
                            "symbol": SYMBOL,
                            "interval": "1m",
                            "startTime": max(0, (batch_start - 120) * 1000),
                            "endTime": (batch_end + 120) * 1000,
                            "limit": 1000,
                        },
                        timeout=4.0,
                    )
                    for candle in market_rows or []:
                        try:
                            open_ts = int(candle[0]) // 1000
                            close_px = safe_float(candle[4])
                            if pd.notna(close_px) and close_px > 0:
                                candle_points.append((open_ts, float(close_px)))
                        except Exception:
                            continue
                except Exception:
                    # Do not corrupt rows if a historical data request fails.
                    # They remain open and will be retried on the next rerun.
                    continue

        if candle_points:
            # Dedupe by timestamp and keep a sorted sequence for nearest lookup.
            candle_map = {}
            for candle_ts, candle_px in candle_points:
                candle_map[int(candle_ts)] = float(candle_px)
            candle_points = sorted(candle_map.items())

        def _nearest_price(target_ts):
            if not candle_points:
                return np.nan
            nearest_ts, nearest_px = min(candle_points, key=lambda item: abs(item[0] - int(target_ts)))
            # Never grade against a candle far away from the intended settlement.
            if abs(nearest_ts - int(target_ts)) > 120:
                return np.nan
            return float(nearest_px)

        updated = 0
        for row, target_ts, action in prepared:
            start_price = safe_float(row["price"])
            if pd.isna(start_price) or start_price <= 0:
                continue

            # HOLD/WAIT is a completed no-trade observation. Keep it outside
            # directional win/loss accuracy, even if historical data is offline.
            if action in {"HOLD", "WAIT"}:
                resolved_price = _nearest_price(target_ts)
                ret = (
                    (resolved_price / start_price - 1.0) * 100.0
                    if pd.notna(resolved_price) and resolved_price > 0
                    else None
                )
                conn.execute(
                    "UPDATE predictions SET target_ts=?,resolved=1,resolved_price=?,return_pct=?,correct=NULL WHERE id=?",
                    (
                        int(target_ts),
                        None if pd.isna(resolved_price) else float(resolved_price),
                        ret,
                        int(row["id"]),
                    ),
                )
                updated += 1
                continue

            resolved_price = _nearest_price(target_ts)
            if pd.isna(resolved_price) or resolved_price <= 0:
                continue

            ret = (resolved_price / start_price - 1.0) * 100.0
            strike = safe_float(row["target_price"])

            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)
            else:
                correct = None

            conn.execute(
                """UPDATE predictions
                   SET target_ts=?,resolved=1,resolved_price=?,return_pct=?,correct=?
                   WHERE id=?""",
                (
                    int(target_ts),
                    float(resolved_price),
                    float(ret),
                    correct,
                    int(row["id"]),
                ),
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
    'APP_VERSION = "2026.09.05-r46-batched-journal-settlement"',
    s,
    count=1,
)

if s == original:
    raise SystemExit("no changes made")

p.write_text(s, encoding="utf-8")
print("Applied batched, self-healing prediction journal settlement")
