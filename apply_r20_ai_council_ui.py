from pathlib import Path

p = Path('app.py')
s = p.read_text()

old = '''        d2.metric("Master score", f"{decision['score']:+.3f}")
        d3.metric("Confidence", f"{decision['confidence']*100:.1f}%")
        d4.metric("Consensus", f"{decision['consensus']*100:.1f}%")
        d5.metric("Risk level", decision["risk_level"])
'''

new = '''        d2.metric("Master score", f"{decision['score']:+.3f}")
        d3.metric("Confidence", f"{decision['confidence']*100:.1f}%")
        d4.metric("Consensus", f"{decision['consensus']*100:.1f}%")
        d5.metric("Risk level", decision["risk_level"])

        # User-friendly AI Council summary
        action = str(decision.get("action", "HOLD"))
        confidence_pct = float(decision.get("confidence", 0.0)) * 100.0
        consensus_pct = float(decision.get("consensus", 0.0)) * 100.0
        score = float(decision.get("score", 0.0))

        if action == "LOCK UP":
            plain_call = "The council expects BTC to finish ABOVE the Kalshi target at expiration."
            call_icon = "🔒⬆️"
        elif action == "LOCK DOWN":
            plain_call = "The council expects BTC to finish BELOW the Kalshi target at expiration."
            call_icon = "🔒⬇️"
        elif action == "SCALP UP":
            plain_call = "The council sees a short-term UP move with enough edge for a paper scalp."
            call_icon = "⚡⬆️"
        elif action == "SCALP DOWN":
            plain_call = "The council sees a short-term DOWN move with enough edge for a paper scalp."
            call_icon = "⚡⬇️"
        else:
            plain_call = "The council does not see a strong enough edge right now. Waiting is the preferred move."
            call_icon = "⏸️"

        if confidence_pct >= 75:
            confidence_word = "Strong"
        elif confidence_pct >= 60:
            confidence_word = "Moderate"
        else:
            confidence_word = "Low"

        if consensus_pct >= 75:
            agreement_word = "Most specialists agree"
        elif consensus_pct >= 55:
            agreement_word = "Council is somewhat split"
        else:
            agreement_word = "Council is heavily divided"

        st.markdown(f"### {call_icon} Council verdict: **{action}**")
        st.write(plain_call)
        s1, s2, s3 = st.columns(3)
        s1.metric("How sure?", f"{confidence_pct:.0f}%", confidence_word)
        s2.metric("How much agreement?", f"{consensus_pct:.0f}%", agreement_word)
        direction_label = "UP" if score > 0.05 else "DOWN" if score < -0.05 else "NEUTRAL"
        s3.metric("Overall lean", direction_label, f"Score {score:+.2f}")

        st.caption(
            "Confidence = how strong the combined signal is. Consensus = how much the specialist AIs agree. "
            "A strong call with low consensus means the council still has meaningful disagreement."
        )
'''

if old not in s:
    raise SystemExit('AI Council insertion point not found')

s = s.replace(old, new, 1)
s = s.replace('APP_VERSION = "2026.09.04-single-file-r19-canonical-kalshi-target"',
              'APP_VERSION = "2026.09.04-single-file-r20-friendly-ai-council"', 1)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R20 AI Council usability patch applied successfully')
