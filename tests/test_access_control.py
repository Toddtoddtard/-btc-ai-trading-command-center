import unittest
from pathlib import Path


class AccessControlSourceTests(unittest.TestCase):
    def test_login_supports_enter_and_keeps_unlock_button(self):
        source = (Path(__file__).resolve().parents[1] / "access_control.py").read_text()
        self.assertIn('with st.form("private_access_form"', source)
        self.assertIn('st.form_submit_button(', source)
        self.assertIn('"Unlock"', source)
        self.assertNotIn('st.button("Unlock"', source)

    def test_login_displays_the_deployed_build_when_provided(self):
        source = (Path(__file__).resolve().parents[1] / "access_control.py").read_text()
        app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text()
        self.assertIn('DEPLOYED_BUILD = "2026.09.23-r87-parity-cadence-risk"', source)
        self.assertIn('st.caption(f"Deployed build: {DEPLOYED_BUILD}")', source)
        self.assertIn("require_owner_approval()", app_source)


if __name__ == "__main__":
    unittest.main()
