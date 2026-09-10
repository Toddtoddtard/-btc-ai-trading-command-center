#!/usr/bin/env python3
"""Fast static validator for Specialist Intelligence v7 integration."""
from pathlib import Path

required = {
    "historical_specialist_backtest_v7.py": ["ELIGIBLE", "detect_regime", "directional_calls", "evaluated_windows", "overall_council", "qualified_ohlcv_council", "holdout"],
    "specialist_knowledge_v5.py": ["historical_specialist_knowledge_v7", "historical_regime", "regimes"],
    "enrich_learning_state_v5.py": ["HISTORICAL_SPECIALIST_INPUT", "historical_specialist_v7_loaded"],
    "audit_scorecard_v7.py": ["BASELINE_SAMPLES = 15", "25, 50, 100, 250, 500, 1000"],
    ".github/workflows/learn.yml": ["historical_specialist_knowledge_v7.json", "audit_scorecard_v7.py"],
    ".github/workflows/historical-specialist-v7.yml": ["historical_specialist_backtest_v7.py", "evaluated_windows", "HISTORICAL_YEARS", "version') == 10"],
}

for filename, anchors in required.items():
    text = Path(filename).read_text()
    for anchor in anchors:
        assert anchor in text, (filename, anchor)
print("Specialist Intelligence v7 static validation passed")
