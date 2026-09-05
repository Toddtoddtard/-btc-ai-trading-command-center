from pathlib import Path

p = Path("app.py")
text = p.read_text(encoding="utf-8")

old = '''            st.subheader("Active Position")
            p1, p2, p3, p4, p5, p6 = st.columns(6)
            p1.metric("Side", auto_state["side"])
            p2.metric("Entry", fmt_money(entry))
            p3.metric("Current", fmt_money(price))
            p4.metric("Stop", fmt_money(stop))
            p5.metric("Target", fmt_money(target))
            p6.metric("Unrealized", fmt_money(unrealized_dollars))
            st.caption(
                f"Quantity {qty:.6f} BTC • elapsed {elapsed//60:02d}:{elapsed%60:02d} • "
                f"automatic time exit at {PREDICTION_HORIZON_MIN}:00"
            )
'''
new = '''            st.subheader("Active Position")
            bet_size_dollars = qty * entry
            p1, p2, p3, p4, p5, p6, p7 = st.columns(7)
            p1.metric("Side", auto_state["side"])
            p2.metric("Bet Size", fmt_money(bet_size_dollars))
            p3.metric("Entry", fmt_money(entry))
            p4.metric("Current", fmt_money(price))
            p5.metric("Stop", fmt_money(stop))
            p6.metric("Target", fmt_money(target))
            p7.metric("Unrealized", fmt_money(unrealized_dollars))
            st.caption(
                f"Bet ${bet_size_dollars:,.2f} • Quantity {qty:.6f} BTC • elapsed {elapsed//60:02d}:{elapsed%60:02d} • "
                f"automatic time exit at {PREDICTION_HORIZON_MIN}:00"
            )
'''
if old not in text:
    raise SystemExit("Active Position block not found; refusing partial update")
text = text.replace(old, new, 1)

old2 = '''        r1.metric("Approved", "YES" if risk["approved"] else "NO")
        r2.metric("Position size", f"{risk['position_pct']*100:.2f}%")
        r3.metric("Risk score", f"{risk['risk_score']:.2f}")
        r4.metric("Decision", decision["action"])
        st.caption(risk["reason"])
'''
new2 = '''        r1.metric("Approved", "YES" if risk["approved"] else "NO")
        r2.metric("Position size", f"{risk['position_pct']*100:.2f}%")
        r3.metric("Risk score", f"{risk['risk_score']:.2f}")
        r4.metric("Decision", decision["action"])
        next_bet_dollars = max(0.0, float(account["equity"]) * float(risk["position_pct"]))
        st.metric("Next Approved Bet Size", fmt_money(next_bet_dollars) if risk["approved"] else "$0.00")
        st.caption(risk["reason"])
'''
if old2 not in text:
    raise SystemExit("Risk Manager block not found; refusing partial update")
text = text.replace(old2, new2, 1)

text = text.replace(
    'APP_VERSION = "2026.09.05-r47-paper-500-total-pl"',
    'APP_VERSION = "2026.09.05-r48-paper-bet-size"',
    1,
)

p.write_text(text, encoding="utf-8")
