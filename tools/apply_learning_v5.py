#!/usr/bin/env python3
from pathlib import Path

p = Path('.github/workflows/learn.yml')
s = p.read_text()

# Trigger learner when v5 intelligence changes.
anchor = "      - 'bot_intelligence_report.py'\n"
add = "      - 'bot_intelligence_report.py'\n      - 'specialist_knowledge_v5.py'\n      - 'enrich_learning_state_v5.py'\n      - 'profitability_v5.py'\n"
if "specialist_knowledge_v5.py" not in s:
    if anchor not in s:
        raise SystemExit('learn trigger anchor not found')
    s = s.replace(anchor, add)

old_compile = 'run: python -m py_compile learner.py learner_v3.py learner_v31.py reliability_v31.py ai_core.py council_v4.py bot_intelligence_report.py'
new_compile = 'run: python -m py_compile learner.py learner_v3.py learner_v31.py reliability_v31.py ai_core.py council_v4.py bot_intelligence_report.py specialist_knowledge_v5.py enrich_learning_state_v5.py profitability_v5.py'
s = s.replace(old_compile, new_compile)

v4_step = '''      - name: Run Bot Intelligence v4 contribution analysis\n        env:\n          LEARNING_STATE_INPUT: /tmp/learning_state.json\n          LEARNING_STATE_OUTPUT: /tmp/learning_state_v4.json\n        run: |\n          python bot_intelligence_report.py\n          mv /tmp/learning_state_v4.json /tmp/learning_state.json\n'''
v5_step = v4_step + '''      - name: Enrich specialist self-learning v5 knowledge\n        env:\n          LEARNING_STATE_OUTPUT: /tmp/learning_state.json\n        run: python enrich_learning_state_v5.py\n'''
if 'Enrich specialist self-learning v5 knowledge' not in s:
    if v4_step not in s:
        raise SystemExit('v4 learner step anchor not found')
    s = s.replace(v4_step, v5_step)

validate_anchor = "          assert data.get('status', {}).get('bot_intelligence_v4_ok') is True\n"
validate_add = validate_anchor + "          assert data.get('status', {}).get('specialist_self_learning_v5') is True\n          assert data.get('status', {}).get('intelligence_version') == 5\n          assert 'specialist_knowledge_v5' in data\n          assert isinstance(data.get('specialist_knowledge_v5', {}).get('bots', {}), dict)\n"
if "specialist_self_learning_v5" not in s:
    if validate_anchor not in s:
        raise SystemExit('validation anchor not found')
    s = s.replace(validate_anchor, validate_add)

s = s.replace('Update BTC AI learning state with Bot Intelligence v4', 'Update BTC AI learning state with Specialist Intelligence v5')
p.write_text(s)
print('learning workflow v5 integration applied')
