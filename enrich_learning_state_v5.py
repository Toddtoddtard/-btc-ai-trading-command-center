#!/usr/bin/env python3
"""Attach specialist knowledge to the live learning-state payload."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ai_core import SPECIALIST_NAMES
from specialist_knowledge_v5 import specialist_posterior

PATH = Path(os.getenv("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json"))
HISTORICAL_SPECIALIST_INPUT = Path(os.getenv("HISTORICAL_SPECIALIST_INPUT", "/tmp/historical_specialist_knowledge_v7.json"))


def resolve_current_regime(state):
    """Resolve the freshest real regime label available in the state."""
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else {}
    regime = str((pending or {}).get("regime") or "").strip()
    if regime and regime != "UNKNOWN":
        return regime
    status = state.get("status") if isinstance(state.get("status"), dict) else {}
    regime = str((status or {}).get("current_regime") or "").strip()
    if regime and regime != "UNKNOWN":
        return regime
    history = state.get("master_history") if isinstance(state.get("master_history"), list) else []
    for row in reversed(history):
        if not isinstance(row, dict):
            continue
        regime = str(row.get("regime") or "").strip()
        if regime and regime != "UNKNOWN":
            return regime
    return "UNKNOWN"


def load_historical_specialist_prior(state):
    """Load a validated historical report when the workflow supplied one."""
    if not HISTORICAL_SPECIALIST_INPUT.exists():
        return False
    try:
        report = json.loads(HISTORICAL_SPECIALIST_INPUT.read_text())
    except Exception:
        return False
    if not isinstance(report, dict) or report.get("version") not in {7, 9, 10} or report.get("walk_forward") is not True:
        return False
    specialists = report.get("specialists")
    if not isinstance(specialists, dict) or not specialists:
        return False
    state["historical_specialist_knowledge_v7"] = report
    return True


def main():
    state = json.loads(PATH.read_text())
    historical_loaded = load_historical_specialist_prior(state)
    regime = resolve_current_regime(state)
    names = [n for n in SPECIALIST_NAMES if n != "Combination AI"]
    knowledge = {}
    for name in names:
        knowledge[name] = specialist_posterior(state, name, regime)
    ranked = sorted(
        knowledge.values(),
        key=lambda x: (x["lower95_accuracy"], x["posterior_accuracy"], x["live_samples"]),
        reverse=True,
    )
    state["specialist_knowledge_v5"] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regime": regime,
        "target_precision": 0.90,
        "method": "Bayesian posterior from graded live history plus optional long-history regime-specific holdout priors",
        "historical_specialist_v7_loaded": historical_loaded,
        "bots": knowledge,
        "ranking": [x["name"] for x in ranked],
        "warning": "90% is a target, not a guaranteed or reported accuracy. Precision gate may abstain heavily.",
    }
    state.setdefault("status", {})["intelligence_version"] = (
        int(state.get("historical_specialist_knowledge_v7", {}).get("version", 9))
        if historical_loaded else 6
    )
    state["status"]["specialist_self_learning_v5"] = True
    state["status"]["specialist_knowledge_regime"] = regime
    state["status"]["historical_specialist_v7_loaded"] = historical_loaded
    PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps({
        "intelligence_version": state["status"]["intelligence_version"],
        "regime": regime,
        "historical_specialist_v7_loaded": historical_loaded,
        "top_bots": state["specialist_knowledge_v5"]["ranking"][:5],
    }, indent=2))


if __name__ == "__main__":
    main()
