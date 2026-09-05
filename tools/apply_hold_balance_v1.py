from pathlib import Path

path = Path("app.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        'and forecast_move >= max(atr * 0.22, px * 0.00022)\n            and consensus >= 0.22',
        'and forecast_move >= max(atr * 0.14, px * 0.00014)\n            and consensus >= 0.12',
    ),
    (
        'and forecast_move <= -max(atr * 0.22, px * 0.00022)\n            and consensus >= 0.22',
        'and forecast_move <= -max(atr * 0.14, px * 0.00014)\n            and consensus >= 0.12',
    ),
]

changed = False
for old, new in replacements:
    if old in text:
        text = text.replace(old, new, 1)
        changed = True

# Risk layer should use the same feed-health floor as the learned gate so an
# approved directional call is not immediately blocked by a stale stricter floor.
old_risk = 'if source_health < 0.68:\n        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "Market-data health below reliability floor"}'
new_risk = 'if source_health < 0.60:\n        return {"approved": False, "position_pct": 0.0, "risk_score": 1.0, "reason": "Market-data health below reliability floor"}'
if old_risk in text:
    text = text.replace(old_risk, new_risk, 1)
    changed = True

if not changed:
    print("HOLD-balance policy already installed or source changed.")
else:
    path.write_text(text, encoding="utf-8")
    print("Installed HOLD-balance decision policy.")
