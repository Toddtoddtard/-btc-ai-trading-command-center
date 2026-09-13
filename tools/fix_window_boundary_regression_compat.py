from pathlib import Path

p = Path('kalshi_paper_engine.py')
s = p.read_text(encoding='utf-8')

old = '''    return {
        "event": True,
        "message": (
            f"Settled PAPER {row['strategy']} {row['side']} {row['ticker']} "
            f"@ {exit_price:.2f} | P/L {pnl:+.2f}"
        ),
    }
'''
new = '''    label = "Settled" if str(reason).startswith("OFFICIAL_SETTLEMENT:") else "Closed"
    return {
        "event": True,
        "message": (
            f"{label} PAPER {row['strategy']} {row['side']} {row['ticker']} "
            f"@ {exit_price:.2f} | P/L {pnl:+.2f}"
        ),
    }
'''
if old not in s:
    raise SystemExit('close-message compatibility anchor missing')
s = s.replace(old, new, 1)

s = s.replace(
    '"Window ended — settlement pending: " + str(row["ticker"])',
    '"Window ended — Awaiting official Kalshi settlement: " + str(row["ticker"])',
    1,
)

# Keep the long-standing public history shape stable. Pending rows can still be
# identified by status/result without exposing a new ticker key to callers.
s = s.replace('                    "ticker": item.get("ticker"),\n', '', 1)

p.write_text(s, encoding='utf-8')
print('Applied boundary-fix regression compatibility adjustments.')
