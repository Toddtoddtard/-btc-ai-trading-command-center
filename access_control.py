import hashlib
import hmac
import time

import streamlit as st

# Deployment touch: keep Streamlit synced to the latest private-access build.


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
        unlock_submitted = st.form_submit_button(
            "Unlock",
            use_container_width=True,
        )

    if unlock_submitted:
        submitted = _hash_code(code.strip()) if code else ""
        matched_user = None
        for approved_name, approved_hash in codes.items():
            if name.strip().lower() == str(approved_name).strip().lower() and hmac.compare_digest(submitted, str(approved_hash).strip().lower()):
                matched_user = approved_name
                break

        if matched_user:
            st.session_state["access_granted"] = True
            st.session_state["access_user"] = str(matched_user)
            st.session_state["access_failures"] = 0
            st.rerun()

        failures += 1
        st.session_state["access_failures"] = failures
        if failures >= 5:
            st.session_state["access_locked_until"] = now + 300
            st.session_state["access_failures"] = 0
        st.error("Access denied. Ask the owner for approval and a valid access code.")

    st.info("No access code? Ask the owner. Only approved users can enter.")
    st.stop()
