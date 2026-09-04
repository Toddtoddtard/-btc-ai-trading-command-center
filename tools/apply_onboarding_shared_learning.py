from pathlib import Path

APP = Path("app.py")
text = APP.read_text(encoding="utf-8")

# Imports.
anchor = "from access_control import require_owner_approval\n"
imports = (
    "from access_control import require_owner_approval\n"
    "from market_guide import render_market_guide\n"
    "from shared_learning import fetch_shared_learning_state\n"
)
if "from market_guide import render_market_guide" not in text:
    if anchor not in text:
        raise SystemExit("access-control import anchor not found")
    text = text.replace(anchor, imports, 1)

# Replace private-repo-unsafe remote learner loader with resilient shared loader.
start = text.find("def fetch_remote_learning_state(ttl=20.0):\n")
end_marker = "\n# ============================================================\n# DATABASE\n# ============================================================\n"
end = text.find(end_marker, start)
if start == -1 or end == -1:
    raise SystemExit("remote learning function boundaries not found")
replacement = (
    "def fetch_remote_learning_state(ttl=20.0):\n"
    "    \"\"\"Compatibility wrapper around the private-repo-safe shared loader.\"\"\"\n"
    "    return fetch_shared_learning_state(ttl=ttl)\n\n"
)
text = text[:start] + replacement + text[end:]

# Add the guide immediately after the main title/caption block.
caption = (
    "st.caption(f\"Single-file build {APP_VERSION} • Kalshi BTC multi-AI self-learning engine • "
    "24/7 remote learner • rolling 100/500/1000-window accuracy • paper-only\")\n"
)
if "render_market_guide()" not in text:
    if caption not in text:
        raise SystemExit("main caption anchor not found")
    text = text.replace(caption, caption + "render_market_guide()\n", 1)

# Version bump.
text = text.replace(
    'APP_VERSION = "2026.09.04-r38-private-access"',
    'APP_VERSION = "2026.09.04-r39-onboarding-shared-learning"',
    1,
)

required = [
    "from market_guide import render_market_guide",
    "from shared_learning import fetch_shared_learning_state",
    "render_market_guide()",
    "return fetch_shared_learning_state(ttl=ttl)",
    'APP_VERSION = "2026.09.04-r39-onboarding-shared-learning"',
]
for marker in required:
    if marker not in text:
        raise SystemExit(f"missing required marker: {marker}")

APP.write_text(text, encoding="utf-8")
print("Applied onboarding + shared-learning upgrade")
