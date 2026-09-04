#!/usr/bin/env python3
"""Generate milestone scorecards for post-Audit-v6 live predictions."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASELINE_SAMPLES = 15
MILESTONES = (25, 50, 100, 250, 500, 1000)
PATH = Path(os.getenv("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json"))


def _mean(rows, key):
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    return (sum(float(v) for v in vals) / len(vals)) if vals else None


def _score(rows):
    if not rows:
        return {"samples": 0}
    return {
        "samples": len(rows),
        "direction_accuracy": _mean(rows, "direction_correct"),
        "kalshi_accuracy": _mean(rows, "kalshi_correct"),
        "avg_abs_error": _mean(rows, "abs_error"),
        "avg_path_error": _mean(rows, "path_error"),
        "avg_confidence": _mean(rows, "master_confidence"),
    }


def main():
    state = json.loads(PATH.read_text())
    history = state.get("master_history", []) or []
    baseline_rows = history[:BASELINE_SAMPLES]
    post_rows = history[BASELINE_SAMPLES:]
    achieved = {}
    for m in MILESTONES:
        if len(post_rows) >= m:
            achieved[str(m)] = _score(post_rows[:m])
    state["audit_v6_scorecard"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_total_samples": BASELINE_SAMPLES,
        "baseline": _score(baseline_rows),
        "post_audit_live_samples": len(post_rows),
        "current_post_audit": _score(post_rows),
        "milestones": list(MILESTONES),
        "achieved": achieved,
        "next_milestone": next((m for m in MILESTONES if len(post_rows) < m), None),
    }
    PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps(state["audit_v6_scorecard"], indent=2))


if __name__ == "__main__":
    main()
