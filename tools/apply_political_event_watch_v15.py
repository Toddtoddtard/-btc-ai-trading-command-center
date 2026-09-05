#!/usr/bin/env python3
from pathlib import Path

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
print("Political Event Watch AI integrated into ai_core.py")
