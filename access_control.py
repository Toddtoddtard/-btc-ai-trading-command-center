import hashlib
import hmac
import time

import streamlit as st

# Deployment touch: keep Streamlit synced to the latest private-access build.
DEPLOYED_BUILD = "2026.11.05-r116-compressed-state-recovery"


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def require_owner_approval():
    """Block the app unless a user enters an owner-issued access code.

    Codes are stored only in Streamlit secrets under [access_codes].
    Nothing sensitive is committed to GitHub.
    """
    if st.session_state.get("access_granted") is True:
        return

    codes = st.secrets.get("access_codes", {})
    if not codes:
        st.error("Private access is not configured yet. The owner must add approved access codes in Streamlit Secrets.")
        st.stop()

    st.title("🔒 Private Access")
    st.caption("This BTC AI Command Center is private. Access requires approval from the owner.")
    st.caption(f"Deployed build: {DEPLOYED_BUILD}")

    failures = int(st.session_state.get("access_failures", 0))
    locked_until = float(st.session_state.get("access_locked_until", 0.0))
    now = time.time()

    if now < locked_until:
        st.warning("Too many failed attempts. Try again shortly.")
        st.stop()

    # Streamlit forms submit when Enter is pressed in either field while also
    # keeping the visible Unlock button available for mouse/touch users.
    with st.form("private_access_form", clear_on_submit=False):
        name = st.text_input("Approved user name", key="access_name")
        code = st.text_input("Access code", type="password", key="access_code")
        unlock_subm…2953 tokens truncated…ty. Cron requests are best effort; verify actual snapshot and paper-cycle ages.
- Older patch installers under `tools/` are not the main runtime. Some are still invoked by workflows, so verify references before touching them.
- `tools/run_offline_tests.py` executes both `unittest.TestCase` methods and standalone `test_*` functions with sockets disabled. Bare unittest discovery does not include the latter.
- `WORK_CONTEXT.md` is the dated handoff log. `ARCHITECTURE.md` explains component relationships. Avoid duplicating numeric strategy settings here; inspect the current constants and explicit user instructions.

