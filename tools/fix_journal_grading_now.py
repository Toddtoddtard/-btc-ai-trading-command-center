from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

old_grade = '''            strike = safe_float(row["target_price"])

            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)
            else:
                correct = None
'''
new_grade = '''            # Grade the prediction journal by BTC direction from the call price.
            # Kalshi contract settlement is authoritative only in the paper ledger.
            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < start_price)
            else:
                correct = None
'''

old_regrade = '''        # Repair legacy resolved directional rows that were graded against the
        # opening spot instead of the Kalshi target. HOLD/WAIT stays untouched.
        conn.execute(
            """UPDATE predictions
               SET correct = CASE
                   WHEN action IN ('SCALP UP','LOCK UP')
                       THEN CASE WHEN resolved_price >= target_price THEN 1 ELSE 0 END
                   WHEN action IN ('SCALP DOWN','LOCK DOWN')
                       THEN CASE WHEN resolved_price < target_price THEN 1 ELSE 0 END
                   ELSE correct
               END
               WHERE resolved=1
                 AND resolved_price IS NOT NULL
                 AND target_price IS NOT NULL
                 AND action IN ('SCALP UP','SCALP DOWN','LOCK UP','LOCK DOWN')"""
        )
'''
new_regrade = '''        # Repair legacy resolved directional rows using the same directional
        # definition as new journal rows. Kalshi settlement truth remains in
        # the paper ledger and must not overwrite BTC direction accuracy.
        conn.execute(
            """UPDATE predictions
               SET correct = CASE
                   WHEN action IN ('SCALP UP','LOCK UP')
                       THEN CASE WHEN resolved_price > price THEN 1 ELSE 0 END
                   WHEN action IN ('SCALP DOWN','LOCK DOWN')
                       THEN CASE WHEN resolved_price < price THEN 1 ELSE 0 END
                   ELSE correct
               END
               WHERE resolved=1
                 AND resolved_price IS NOT NULL
                 AND price IS NOT NULL
                 AND action IN ('SCALP UP','SCALP DOWN','LOCK UP','LOCK DOWN')"""
        )
'''

changed = False
if old_grade in s:
    s = s.replace(old_grade, new_grade, 1)
    changed = True
elif not (
    'correct = int(resolved_price > start_price)' in s
    and 'correct = int(resolved_price < start_price)' in s
):
    raise SystemExit("Unexpected journal grading block; refusing blind edit.")

if old_regrade in s:
    s = s.replace(old_regrade, new_regrade, 1)
    changed = True
elif not (
    "THEN CASE WHEN resolved_price > price THEN 1 ELSE 0 END" in s
    and "THEN CASE WHEN resolved_price < price THEN 1 ELSE 0 END" in s
):
    raise SystemExit("Unexpected legacy regrade block; refusing blind edit.")

if changed:
    p.write_text(s, encoding="utf-8")
    print("Repaired directional journal grading and legacy regrade.")
else:
    print("Journal grading already repaired.")
