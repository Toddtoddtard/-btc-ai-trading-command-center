from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")
old = '''            strike = safe_float(row["target_price"])

            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price >= strike) if pd.notna(strike) else int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < strike) if pd.notna(strike) else int(resolved_price < start_price)
            else:
                correct = None
'''
new = '''            # Grade the prediction journal by BTC direction from the call price.
            # Kalshi contract settlement is authoritative only in the paper ledger.
            if action in {"SCALP UP", "LOCK UP"}:
                correct = int(resolved_price > start_price)
            elif action in {"SCALP DOWN", "LOCK DOWN"}:
                correct = int(resolved_price < start_price)
            else:
                correct = None
'''

if old in s:
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print("Repaired journal grading.")
elif (
    'correct = int(resolved_price > start_price)' in s
    and 'correct = int(resolved_price < start_price)' in s
):
    print("Journal grading already repaired.")
else:
    raise SystemExit("Unexpected journal grading block; refusing blind edit.")
