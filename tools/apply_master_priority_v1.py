from pathlib import Path

path = Path('app.py')
text = path.read_text()

old = '''        if lock_ticker == current_ticker and lock_side in {"UP", "DOWN"}:
            action = f"LOCK {lock_side}"
            locked_side = lock_side

        elif lock_up:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "UP"
            action = "LOCK UP"
            locked_side = "UP"

        elif lock_down:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "DOWN"
            action = "LOCK DOWN"
            locked_side = "DOWN"

        elif strong_move_up and not up_market_conflict and confidence >= policy["trade_confidence_floor"]:
            action = "SCALP UP"
            locked_side = None

        elif strong_move_down and not down_market_conflict and confidence >= policy["trade_confidence_floor"]:
            action = "SCALP DOWN"
            locked_side = None

        else:
            action = "HOLD"
            locked_side = None
'''

new = '''        scalp_up_candidate = (
            strong_move_up
            and not up_market_conflict
            and confidence >= policy["trade_confidence_floor"]
        )
        scalp_down_candidate = (
            strong_move_down
            and not down_market_conflict
            and confidence >= policy["trade_confidence_floor"]
        )
        scalp_candidate = scalp_up_candidate or scalp_down_candidate

        # Compare the quality of the shorter-term scalp thesis against the
        # settlement/target thesis. SCALP is the default when both are valid;
        # LOCK only wins when its evidence is stronger.
        edge_strength = min(1.0, abs(base_score) / max(policy["edge_floor"] * 2.0, 1e-6))
        scalp_likelihood = float(np.clip(
            0.58 * confidence + 0.24 * consensus + 0.18 * edge_strength,
            0.0, 1.0,
        ))
        settlement_urgency = (
            float(np.clip(1.0 - (remaining / 900.0), 0.0, 1.0))
            if pd.notna(remaining) else 0.0
        )
        lock_likelihood = float(np.clip(
            0.58 * confidence + 0.27 * distance_strength + 0.15 * settlement_urgency,
            0.0, 1.0,
        ))

        # Preserve an already-established lock for the active contract.
        if lock_ticker == current_ticker and lock_side in {"UP", "DOWN"}:
            action = f"LOCK {lock_side}"
            locked_side = lock_side

        # New decisions are scalp-first. A lock is selected only when its
        # settlement case is more likely than the competing scalp case.
        elif scalp_candidate and not ((lock_up or lock_down) and lock_likelihood > scalp_likelihood):
            action = "SCALP UP" if scalp_up_candidate else "SCALP DOWN"
            locked_side = None

        elif lock_up:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "UP"
            action = "LOCK UP"
            locked_side = "UP"

        elif lock_down:
            st.session_state["kalshi_lock_ticker"] = current_ticker
            st.session_state["kalshi_lock_side"] = "DOWN"
            action = "LOCK DOWN"
            locked_side = "DOWN"

        elif scalp_candidate:
            action = "SCALP UP" if scalp_up_candidate else "SCALP DOWN"
            locked_side = None

        else:
            action = "HOLD"
            locked_side = None
'''

if new in text:
    print('Master scalp-first priority already installed.')
elif old in text:
    path.write_text(text.replace(old, new, 1))
    print('Installed scalp-first Master priority.')
else:
    raise SystemExit('Expected Master decision block not found; refusing unsafe patch.')
