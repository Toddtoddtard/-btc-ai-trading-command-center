from pathlib import Path

p = Path('app.py')
s = p.read_text()

# 1) Imports.
old = "from ai_core import enrich_history_core, forecast_path_core, run_specialists_core\nfrom reliability_v31 import ("
new = "from ai_core import enrich_history_core, forecast_path_core, run_specialists_core\nfrom council_v4 import council_vote\nfrom bot_intelligence_dashboard import render_bot_intelligence_dashboard\nfrom reliability_v31 import ("
if old in s and 'from council_v4 import council_vote' not in s:
    s = s.replace(old, new, 1)

# 2) Replace the legacy master council weighting loop with the v4 authoritative council.
old_block = '''    remote_learning = fetch_remote_learning_state() or {}
    regime_name = detect_regime(hist)
    policy = learned_policy(remote_learning, regime_name)
    weighted_sum = 0.0
    total_weight = 0.0
    signs = []

    for name, result in results.items():
        weight = adaptive_specialist_weight(name, regime_name)
        weighted_sum += result["score"] * result["confidence"] * weight
        total_weight += result["confidence"] * weight
        signs.append(np.sign(result["score"]))

    base_score = clamp(weighted_sum / total_weight if total_weight else 0.0)
    directional = [s for s in signs if s != 0]
    consensus = abs(sum(directional)) / len(directional) if directional else 0.0
'''
new_block = '''    remote_learning = fetch_remote_learning_state() or {}
    regime_name = detect_regime(hist)
    policy = learned_policy(remote_learning, regime_name)

    # Bot Intelligence v4 is the single authoritative source-council vote.
    # It excludes Combination AI to avoid double-counting the council's own
    # aggregate, and applies learned + regime-specific specialist reliability.
    v4_council = council_vote(results, remote_learning, regime_name)
    base_score = clamp(v4_council["base_score"])
    consensus = float(v4_council["consensus"])
    council_confidence = float(v4_council["confidence"])
'''
if old_block in s:
    s = s.replace(old_block, new_block, 1)
elif 'v4_council = council_vote(results, remote_learning, regime_name)' not in s:
    raise SystemExit('Could not locate legacy master weighting block')

# 3) Blend the target-aware master confidence with calibrated v4 source-council confidence.
old_conf = '''        confidence = min(
            0.97,
            max(
                0.45,
                0.49
                + abs(score) * 0.28
                + consensus * 0.13
                + distance_strength * 0.10,
            ),
        )
'''
new_conf = '''        target_confidence = min(
            0.97,
            max(
                0.45,
                0.49
                + abs(score) * 0.28
                + consensus * 0.13
                + distance_strength * 0.10,
            ),
        )
        # Never let target geometry erase the reliability calibration learned
        # by v4. Blend both views and cap at the safer of their high extremes.
        confidence = float(np.clip(
            0.58 * target_confidence + 0.42 * council_confidence,
            0.40,
            min(0.97, max(target_confidence, council_confidence)),
        ))
'''
if old_conf in s:
    s = s.replace(old_conf, new_conf, 1)

# 4) Add Bot Intelligence v4 panel immediately after the verdict/reason, before
# the legacy live-signal table. This creates a quick scorecard plus expandable
# evidence without disrupting existing table/UI behavior.
anchor = '''        st.info(decision["reason"])

        rows = []
'''
insert = '''        st.info(decision["reason"])

        try:
            _bot_learning_state = fetch_remote_learning_state() or {}
            _bot_regime = detect_regime(hist)
            render_bot_intelligence_dashboard(
                results,
                _bot_learning_state,
                _bot_regime,
                dark_mode=dark_mode,
            )
        except Exception as _bot_ui_exc:
            st.caption(f"Bot Intelligence v4 panel temporarily unavailable: {_bot_ui_exc}")

        st.markdown("### Live specialist signals")
        rows = []
'''
if anchor in s:
    s = s.replace(anchor, insert, 1)
elif 'render_bot_intelligence_dashboard(' not in s:
    raise SystemExit('Could not locate AI Council insertion anchor')

# 5) Bump visible build version exactly once.
s = s.replace('APP_VERSION = "2026.09.04-r41-consistent-dark-tables"',
              'APP_VERSION = "2026.09.04-r42-bot-intelligence-v4"', 1)

p.write_text(s)
print('Bot Intelligence v4 integration applied to app.py')
