import unittest
from pathlib import Path


class AccessControlSourceTests(unittest.TestCase):
    def test_login_supports_enter_and_keeps_unlock_button(self):
        source = (Path(__file__).resolve().parents[1] / "access_control.py").read_text()
        self.assertIn('with st.form("private_access_form"', source)
        self.assertIn('st.form_submit_button(', source)
        self.assertIn('"Unlock"', source)
        self.assertNotIn('st.button("Unlock"', source)


if __name__ == "__main__":
    unittest.main()
