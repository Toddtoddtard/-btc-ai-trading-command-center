"""Exercise app imports with a UI module cached from before deployment."""
import ast
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class DashboardWarmReloadTests(unittest.TestCase):
    def test_new_entrypoint_can_import_ui_exports_from_a_warm_server(self):
        tree = ast.parse(Path('app.py').read_text())
        reload_loop = next(n for n in tree.body if isinstance(n, ast.For)
                           and isinstance(n.target, ast.Name) and n.target.id == '_runtime_module')
        ui_import = next(n for n in tree.body if isinstance(n, ast.ImportFrom)
                         and n.module == 'dashboard_ui')
        cached = ModuleType('dashboard_ui')
        # These exports existed before the mobile-card change.
        for name in ('directional_badge_html', 'fmt_money', 'fmt_pct', 'render_dashboard_table'):
            setattr(cached, name, lambda *args: None)
        real_reload = importlib.reload
        def load(name):
            return cached if name == 'dashboard_ui' else ModuleType(name)
        def reload(module):
            return real_reload(module) if module is cached else module
        code = compile(ast.Module(body=[reload_loop, ui_import], type_ignores=[]), 'app-warm-start', 'exec')
        namespace = {'importlib': SimpleNamespace(import_module=load, reload=reload)}
        with patch.dict(sys.modules, {'dashboard_ui': cached}):
            exec(code, namespace)
        html = namespace['metric_cards_html']([('MACD histogram', '+1.25')])
        self.assertIn('MACD histogram', html)
        self.assertIn('+1.25', html)
