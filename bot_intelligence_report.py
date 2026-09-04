#!/usr/bin/env python3
"""Attach Bot Intelligence v4 contribution analytics to learning state."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from council_v4 import analyze_bot_contributions

INPUT = Path(os.getenv("LEARNING_STATE_INPUT", "/tmp/learning_state.json"))
OUTPUT = Path(os.getenv("LEARNING_STATE_OUTPUT", "/tmp/learning_state_v4.json"))


def main():
    state = json.loads(INPUT.read_text())
    report = analyze_bot_contributions(state)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    state["bot_intelligence_v4"] = report
    state.setdefault("status", {})["bot_intelligence_v4_ok"] = True
    state["status"]["bot_intelligence_v4_samples"] = report.get("evaluated_snapshots", 0)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps({
        "evaluated_snapshots": report.get("evaluated_snapshots", 0),
        "top_bots": report.get("ranking", [])[:5],
    }, indent=2))


if __name__ == "__main__":
    main()
