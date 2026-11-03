"""Exercise the Market tab controls without the failing slider component."""
import ast
from pathlib import Path
import unittest

class MacdControlsTests(unittest.TestCase):
    def test_history_and_horizon_work_without_slider_assets(self):
        try:
            from streamlit.testing.v1 import AppTest
        except ModuleNotFoundError:
            self.skipTest('UI integration requires the application dependencies')
        tree = ast.parse(Path('app.py').read_text())
        controls = next(node for node in ast.walk(tree)
                        if isinstance(node, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == '_macd_control_cols'
                                for t in node.targets))
        parent = next(node for node in ast.walk(tree)
                      if isinstance(getattr(node, 'body', None), list)
                      and controls in node.body)
        start = parent.body.index(controls)
        block = ast.Module(body=parent.body[start:start + 3], type_ignores=[])
        source = ('import streamlit as st\n' + ast.unparse(block)
                  + '\nst.text(str((_macd_history_minutes, _macd_projection_minutes)))')
        app = AppTest.from_string(source).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.select_slider), 0,
                         'MACD controls still require the failing slider asset')
        self.assertEqual([w.value for w in app.selectbox], [180, 15])
        for history, horizon in ((30, 1), (60, 5), (120, 15), (180, 15)):
            app.selectbox(key='macd_history_minutes').select(history)
            app.selectbox(key='macd_projection_minutes').select(horizon)
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([w.value for w in app.selectbox], [history, horizon])
            self.assertEqual(app.text[-1].value, f'({history}, {horizon})')
