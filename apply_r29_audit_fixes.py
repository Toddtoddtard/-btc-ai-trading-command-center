from pathlib import Path
import re

p = Path('app.py')
s = p.read_text()

# Shared core import: one source of truth for dashboard + 24/7 learner.
needle = 'import streamlit.components.v1 as components\n'
shared_import = 'import streamlit.components.v1 as components\n\nfrom ai_core import enrich_history_core, forecast_path_core, run_specialists_core\n'
if 'from ai_core import enrich_history_core' not in s:
    if needle not in s:
        raise SystemExit('streamlit components import anchor missing')
    s = s.replace(needle, shared_import, 1)

s = s.replace('APP_VERSION = "2026.09.04-single-file-r28-aligned-direction-metrics"', 'APP_VERSION = "2026.09.04-single-file-r29-audit-fixed"')
s = s.replace('"Event AI": 0.55,', '"Kalshi Context AI": 0.55,')

# Use exact same indicator math in app and worker.
pattern = re.compile(r'def enrich_history\(df\):\n.*?\n\ndef specialist\(', re.S)
replacement = '''def enrich_history(df):\n    return enrich_history_core(df)\n\n\ndef specialist('''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit(f'enrich_history replacement failed: {n}')

# Use exact same specialist engine in app and worker.
pattern = re.compile(r'def run_specialists\(hist, agg, futures, kalshi\):\n.*?\n    return out\n\n# ============================================================\n# MASTER AI \+ RISK', re.S)
replacement = '''def run_specialists(hist, agg, futures, kalshi):\n    px = float(hist["close"].iloc[-1])\n    kctx = stable_kalshi_contract(kalshi, px)\n    return run_specialists_core(hist, agg, futures, kctx)\n\n# ============================================================\n# MASTER AI + RISK'''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit(f'run_specialists replacement failed: {n}')

# Use exact same forecast path in app and worker.
pattern = re.compile(r'def python_forecast_path\(rows, target=None, state=None\):\n.*?\n\n\ndef register_forecast_window', re.S)
replacement = '''def python_forecast_path(rows, target=None, state=None):\n    return forecast_path_core(rows, target, state or get_learning_state())\n\n\ndef register_forecast_window'''
s, n = pattern.subn(replacement, s, count=1)
if n != 1:
    raise SystemExit(f'python_forecast_path replacement failed: {n}')

# Remote learning-state migration: preserve learned Event AI history/weight under accurate name.
s = s.replace(
    'item = specialists.get(name, {})',
    'item = specialists.get(name, specialists.get("Event AI", {}) if name == "Kalshi Context AI" else {})',
)

# Local SQLite migration for Streamlit sessions that already learned Event AI.
anchor = '    # Ensure each known specialist has a persistent learning row.\n'
migration = '''    # Migrate the old misleading Event AI label without discarding learned state.\n    old_event = conn.execute(\n        "SELECT adaptive_weight,samples,direction_hits,ewma_accuracy,ewma_edge,ewma_calibration,updated_at "\n        "FROM specialist_learning_state WHERE specialist='Event AI'"\n    ).fetchone()\n    if old_event is not None:\n        conn.execute(\n            "INSERT OR IGNORE INTO specialist_learning_state "\n            "(specialist,adaptive_weight,samples,direction_hits,ewma_accuracy,ewma_edge,ewma_calibration,updated_at) "\n            "VALUES ('Kalshi Context AI',?,?,?,?,?,?,?)",\n            tuple(old_event),\n        )\n\n    # Ensure each known specialist has a persistent learning row.\n'''
if migration not in s:
    if anchor not in s:
        raise SystemExit('specialist migration anchor missing')
    s = s.replace(anchor, migration, 1)

# Surface official Kalshi settlement accuracy from the worker state.
old_defaults = '''                "avg_path_error": 0.0,\n            }'''
new_defaults = '''                "avg_path_error": 0.0,\n                "kalshi_samples": 0,\n                "kalshi_hits": 0,\n            }'''
if old_defaults in s:
    s = s.replace(old_defaults, new_defaults, 1)

old_caption = '''        f"avg final-price error ${_learning_state['avg_abs_error']:,.2f} • "\n        f"avg path error ${_learning_state['avg_path_error']:,.2f}"\n    )'''
new_caption = '''        f"avg final-price error ${_learning_state['avg_abs_error']:,.2f} • "\n        f"avg path error ${_learning_state['avg_path_error']:,.2f}"\n        + (\n            f" • official Kalshi accuracy {_learning_state.get('kalshi_hits', 0) / _learning_state.get('kalshi_samples', 1) * 100:.1f}% "\n            f"({_learning_state.get('kalshi_samples', 0)} settled)"\n            if _learning_state.get('kalshi_samples', 0) else ""\n        )\n    )'''
if old_caption in s:
    s = s.replace(old_caption, new_caption, 1)

compile(s, 'app.py', 'exec')
p.write_text(s)
print('R29 audit fixes applied: shared AI core, accurate Kalshi Context naming, official settlement stats.')
# trigger workflow after workflow file exists
