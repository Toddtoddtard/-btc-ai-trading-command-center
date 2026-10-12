"""Run regression tests with all outbound sockets disabled, including imports."""
import socket
import sys
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def deny_network(*args, **kwargs):
    raise OSError('Network disabled for offline regression tests')


def discover_offline_suite():
    suite = unittest.defaultTestLoader.discover('tests', pattern='test_*.py')
    # unittest discovers TestCase methods but silently skips standalone tests.
    # Keep the existing no-dependency gate and include both repository styles.
    for path in sorted(Path('tests').glob('test_*.py')):
        module = sys.modules.get(path.stem)
        if module is not None:
            for name, function in inspect.getmembers(module, inspect.isfunction):
                if name.startswith('test_') and function.__module__ == module.__name__:
                    suite.addTest(unittest.FunctionTestCase(function))
    return suite

if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', deny_network), patch.object(socket.socket, 'connect_ex', deny_network), patch('socket.create_connection', deny_network):
        suite = discover_offline_suite()
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
