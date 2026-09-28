"""Reproduce Streamlit rerunning app.py with pre-update modules cached."""
import ast
import importlib
from pathlib import Path
import unittest


class RuntimeImportTests(unittest.TestCase):
    def test_entrypoint_refreshes_stale_exports_and_entry_caps(self):
        import live_feeds
        import lock_focus
        import kalshi_paper_engine
        import background_paper
        tree = ast.parse(Path('app.py').read_text())
        refresh = next(n for n in tree.body if isinstance(n, ast.For)
                       and isinstance(n.target, ast.Name) and n.target.id == '_runtime_module')
        live_feeds.parallel_calls = None
        del live_feeds.parallel_calls
        lock_focus.LOCK_MAX_ENTRY_PRICE = .75
        del kalshi_paper_engine.entry_price_limit
        try:
            with self.assertRaises(ImportError):
                exec('from live_feeds import load_live_feeds, parallel_calls', {})
            exec(compile(ast.Module(body=[refresh], type_ignores=[]), 'app.py', 'exec'),
                 {'importlib': importlib})
            namespace = {}
            exec('from live_feeds import load_live_feeds, parallel_calls', namespace)
            self.assertTrue(callable(namespace['parallel_calls']))
            self.assertEqual(namespace['parallel_calls']({'x': lambda: 7}), {'x': 7})
            self.assertEqual(kalshi_paper_engine.entry_price_limit('LOCK'), .93)
            self.assertEqual(background_paper.entry_price_limit('LOCK'), .93)
            self.assertEqual(background_paper.entry_price_limit('SCALP'), .75)
            self.assertTrue(lock_focus.AUTO_SCALPING_ENABLED)
        finally:
            for module in (lock_focus, kalshi_paper_engine, background_paper, live_feeds):
                importlib.reload(module)

    def test_full_app_starts_at_private_access_without_import_error(self):
        # Some historical installer jobs intentionally install only numpy/pandas.
        # Full integration CI installs requirements.txt and must run this check.
        from importlib.metadata import PackageNotFoundError, version
        import subprocess
        import sys
        try:
            version("streamlit")
        except PackageNotFoundError:
            self.skipTest("Streamlit startup requires the application dependencies")
        result = subprocess.run([sys.executable, "-c", """
import socket
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
def offline(*args, **kwargs):
    raise OSError('Network disabled for startup test')
with patch.object(socket.socket, 'connect', offline), patch('socket.create_connection', offline):
    app = AppTest.from_file('app.py')
    app.secrets['access_codes'] = {'test-owner': '0' * 64}
    app.run(timeout=20)
    assert len(app.exception) == 0, [e.message for e in app.exception]
    assert any('Private Access' in title.value for title in app.title)
"""], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
