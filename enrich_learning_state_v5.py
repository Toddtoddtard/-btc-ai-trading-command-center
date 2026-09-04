#!/usr/bin/env python3
"""Attach v5 specialist knowledge to the existing v3.1 learning-state payload."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ai_core import SPECIALIST_NAMES
from specialist_knowledge_v5 import specialist_posterior

PATH = Path(os.getenv("LEARNING_STATE_OUTPUT", "/tmp/learning_state.json"))


def resolve_current_regime(state):
    """Resolve the freshest real regime label available in the state.

    Older v5 code looked for validation.current_regime, but walk-forward validation
    does not emit that field, so the knowledge layer silently fell back to UNKNOWN.
    Prefer the active pending window, then learner status, then the latest graded row.
    """
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


def main():
    state = json.loads(PATH.read_text())
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
        "method": "Bayesian posterior from graded specialist history plus optional walk-forward priors",
        "bots": knowledge,
        "ranking": [x["name"] for x in ranked],
        "warning": "90% is a target, not a guaranteed or reported accuracy. Precision gate may abstain heavily.",
    }
    state.setdefault("status", {})["intelligence_version"] = 5
    state["status"]["specialist_self_learning_v5"] = True
    state["status"]["specialist_knowledge_regime"] = regime
    PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(json.dumps({
        "intelligence_version": 5,
        "regime": regime,
        "top_bots": state["specialist_knowledge_v5"]["ranking"][:5],
    }, indent=2))


if __name__ == "__main__":
    main()
