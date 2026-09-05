from pathlib import Path
import re

p = Path("app.py")
s = p.read_text(encoding="utf-8")
original = s

# Version marker.
s = re.sub(
    r'APP_VERSION = "[^"]+"',
    'APP_VERSION = "2026.09.05-r44-journal-confidence-repair"',
    s,
    count=1,
)

# Make the custom Confidence card visually match the other top metric cards.
confidence_css = '''    .confidence-metric-card {
        width:100%;
        min-height:92px;
        box-sizing:border-box;
        padding:.72rem 1rem;
        border:1px solid #1687ff;
        border-radius:13px;
        background:linear-gradient(180deg,rgba(11,27,47,.96),rgba(7,20,35,.96));
        box-shadow:0 10px 28px rgba(0,0,0,.18), 0 0 0 1px rgba(22,135,255,.10) inset;
        display:flex;
        flex-direction:column;
        align-items:flex-start;
        justify-content:flex-start;
        gap:.30rem;
    }'''
s, n_css = re.subn(
    r'    \.confidence-metric-card \{.*?\n    \}',
    confidence_css,
    s,
    count=1,
    flags=re.S,
)
if n_css != 1:
    raise SystemExit("confidence card CSS anchor not found")

new_resolver = '''def resolve_predictions(hist, current_price=None):
    """Resolve journal rows at the BTC candle nearest each row's target time."""
    now_ts = int(time.time())
    if hist is None or hist.empty:
        return 0

    hist2 = hist.copy()
    hist2["_ts"] = pd.to_datetime(hist2["time"], utc=True, errors="coerce")
    hist2 = hist2.dropna(subset=["_ts"])
    if hist2.empty:
        return 0

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

            target_dt = pd.to_datetime(int(row["target_ts"]), unit="s", utc=True)
            nearest = hist2.iloc[(hist2["_ts"] - target_dt).abs().argsort()[:1]]
            if nearest.empty:
                continue

            resolved_price = safe_float(nearest.iloc[0]["close"])
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
                # HOLD/WAIT remain tracked and resolved, but do not count as wins/losses.
                correct = None

            conn.execute(
                "UPDATE predictions SET resolved=1,resolved_price=?,return_pct=?,correct=? WHERE id=?",
                (resolved_price, ret, correct, int(row["id"])),
            )
            updated += 1

        conn.commit()
    return updated
'''
s, n_resolve = re.subn(
    r'def resolve_predictions\(current_price\):.*?(?=\ndef recent_predictions\(limit=100\):)',
    new_resolver + '\n',
    s,
    count=1,
    flags=re.S,
)
if n_resolve != 1:
    raise SystemExit("prediction resolver anchor not found")

new_stats = '''def prediction_stats():
    with db_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved_n,
                      SUM(CASE WHEN resolved=1 AND action NOT IN ('HOLD','WAIT') THEN 1 ELSE 0 END) AS trade_resolved_n,
                      SUM(CASE WHEN resolved=1 AND action NOT IN ('HOLD','WAIT') AND correct=1 THEN 1 ELSE 0 END) AS correct_n,
                      SUM(CASE WHEN resolved=1 AND action IN ('HOLD','WAIT') THEN 1 ELSE 0 END) AS wait_resolved_n,
                      AVG(CASE WHEN resolved=1 THEN ABS(return_pct) END) AS avg_abs_move
               FROM predictions"""
        ).fetchone()
    n = int(row["n"] or 0)
    resolved_n = int(row["resolved_n"] or 0)
    trade_resolved_n = int(row["trade_resolved_n"] or 0)
    correct_n = int(row["correct_n"] or 0)
    wait_resolved_n = int(row["wait_resolved_n"] or 0)
    return {
        "n": n,
        "resolved": resolved_n,
        "trade_resolved": trade_resolved_n,
        "wait_resolved": wait_resolved_n,
        "accuracy": correct_n / trade_resolved_n if trade_resolved_n else np.nan,
        "avg_abs_move": safe_float(row["avg_abs_move"]),
    }
'''
s, n_stats = re.subn(
    r'def prediction_stats\(\):.*?(?=\n# ============================================================\n# WALK-FORWARD BACKTEST)',
    new_stats + '\n',
    s,
    count=1,
    flags=re.S,
)
if n_stats != 1:
    raise SystemExit("prediction stats anchor not found")

s, n_call = re.subn(
    r'    resolve_predictions\(price\)',
    '    resolve_predictions(hist, price)',
    s,
    count=1,
)
if n_call != 1:
    raise SystemExit("resolve_predictions call anchor not found")

old_metrics = '''        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Predictions", stats["n"])
        j2.metric("Resolved", stats["resolved"])
        j3.metric("Accuracy", "N/A" if pd.isna(stats["accuracy"]) else f"{stats['accuracy']*100:.1f}%")
        j4.metric("Avg |15m move|", "N/A" if pd.isna(stats["avg_abs_move"]) else f"{stats['avg_abs_move']:.3f}%")'''
new_metrics = '''        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Predictions", stats["n"])
        j2.metric("Trade calls resolved", stats["trade_resolved"])
        j3.metric("Trade-call accuracy", "N/A" if pd.isna(stats["accuracy"]) else f"{stats['accuracy']*100:.1f}%")
        j4.metric("HOLD/WAIT resolved", stats["wait_resolved"])
        st.caption(
            "Win/loss accuracy counts only SCALP/LOCK calls. HOLD/WAIT decisions are still recorded and resolved for learning, but are not treated as wins or losses."
        )'''
if old_metrics not in s:
    raise SystemExit("journal metrics anchor not found")
s = s.replace(old_metrics, new_metrics, 1)

needle = '''                journal_view = journal_df.copy()

                def _journal_action_badge(value):'''
replacement = '''                journal_view = journal_df.copy()
                _journal_actions = journal_view["action"].astype(str).str.upper().str.strip()
                _journal_resolved = pd.to_numeric(journal_view["resolved"], errors="coerce").fillna(0).astype(int)
                journal_view.loc[_journal_actions.isin(["HOLD", "WAIT"]), "correct"] = "NO TRADE"
                journal_view.loc[_journal_resolved != 1, "correct"] = "OPEN"

                def _journal_action_badge(value):'''
if needle not in s:
    raise SystemExit("journal view anchor not found")
s = s.replace(needle, replacement, 1)

new_badge = '''                def _journal_result_badge(value):
                    label = str(value).upper().strip()
                    if label == "NO TRADE":
                        return '<span class="journal-result journal-neutral">NO TRADE</span>'
                    if label == "OPEN" or pd.isna(value):
                        return '<span class="journal-result journal-pending">OPEN</span>'
                    try:
                        return (
                            '<span class="journal-result journal-win">✓ CORRECT</span>'
                            if int(float(value)) == 1
                            else '<span class="journal-result journal-loss">✕ WRONG</span>'
                        )
                    except Exception:
                        return '<span class="journal-result journal-pending">OPEN</span>'

'''
s, n_badge = re.subn(
    r'                def _journal_result_badge\(value\):.*?(?=                def _journal_resolved_badge\(value\):)',
    new_badge,
    s,
    count=1,
    flags=re.S,
)
if n_badge != 1:
    raise SystemExit("journal result badge anchor not found")

if s == original:
    raise SystemExit("no changes made")

p.write_text(s, encoding="utf-8")
print("Applied coordinated journal + confidence repairs")
