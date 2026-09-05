#!/usr/bin/env python3
from pathlib import Path

# ----- ai_core.py -----
path = Path("ai_core.py")
text = path.read_text()

if "from political_event_watch import political_specialist_result" not in text:
    text = text.replace(
        "import pandas as pd\n",
        "import pandas as pd\n\nfrom political_event_watch import political_specialist_result\n",
        1,
    )

if '    "Political Event Watch AI",\n' not in text:
    text = text.replace(
        '    "Historical Pattern AI",\n    "Combination AI",\n',
        '    "Historical Pattern AI",\n    "Political Event Watch AI",\n    "Combination AI",\n',
        1,
    )

needle = '    out["Combination AI"] = _specialist("Combination AI", combo, f"Cross-specialist directional agreement {agreement*100:.0f}%")\n    return out\n'
replacement = '    out["Combination AI"] = _specialist("Combination AI", combo, f"Cross-specialist directional agreement {agreement*100:.0f}%")\n\n    # Event-driven specialist: zero score/confidence unless a fresh qualifying\n    # political event is active. Added after Combination so an inactive watcher\n    # cannot dilute or distort the normal technical specialist ensemble.\n    out["Political Event Watch AI"] = political_specialist_result(hist)\n    return out\n'
if "out[\"Political Event Watch AI\"]" not in text:
    if needle not in text:
        raise SystemExit("Could not locate Combination AI insertion point")
    text = text.replace(needle, replacement, 1)
path.write_text(text)

# ----- council_v4.py -----
# The council normally gives every member a minimum confidence floor. That is
# correct for ordinary specialists but would let an INACTIVE event watcher dilute
# the denominator. Explicitly skip it unless its trigger state is ACTIVE.
cpath = Path("council_v4.py")
council = cpath.read_text()
loop_needle = '    for name, item in results.items():\n        if name in exclude or not isinstance(item, dict):\n            continue\n'
loop_replacement = '    for name, item in results.items():\n        if name in exclude or not isinstance(item, dict):\n            continue\n        if name == "Political Event Watch AI" and str(item.get("event_status", "INACTIVE")).upper() != "ACTIVE":\n            continue\n'
if 'name == "Political Event Watch AI" and str(item.get("event_status"' not in council:
    if loop_needle not in council:
        raise SystemExit("Could not locate council member loop")
    council = council.replace(loop_needle, loop_replacement, 1)
cpath.write_text(council)

print("Political Event Watch AI integrated with true zero-weight inactive gating")
