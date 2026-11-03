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
        self.assertRegex(source, r'DEPLOYED_BUILD = "\d{4}\.\d{2}\.\d{2}-r\d+-[a-z-]+"')
        self.assertIn('st.caption(f"Deployed build: {DEPLOYED_BUILD}")', source)
        self.assertIn('from access_control import DEPLOYED_BUILD, require_owner_approval', app_source)
        self.assertIn('APP_VERSION = DEPLOYED_BUILD', app_source)
        self.assertNotIn('APP_VERSION = "', app_source)
        self.assertIn("require_owner_approval()", app_source)


if __name__ == "__main__":
    unittest.main()


class StartupOrderingTests(unittest.TestCase):
    def test_private_gate_precedes_trading_imports_and_runtime_reload(self):
        import ast
        tree = ast.parse(Path('app.py').read_text())
        gate = next(n.lineno for n in tree.body if isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                    and n.value.func.id == 'require_owner_approval')
        expensive = [n.lineno for n in tree.body
                     if (isinstance(n, ast.Import) and any(a.name.split('.')[0] in
                         {'numpy', 'pandas', 'plotly', 'prediction_journal'} for a in n.names))
                     or (isinstance(n, ast.ImportFrom) and n.module in
                         {'prediction_journal', 'shared_learning', 'ai_core'})
                     or (isinstance(n, ast.For) and any(isinstance(x, ast.Call)
                         and isinstance(x.func, ast.Attribute) and x.func.attr == 'reload'
                         for x in ast.walk(n)))]
        self.assertTrue(expensive)
        self.assertTrue(all(gate < line for line in expensive))
