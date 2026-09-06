"""Run regression tests with all outbound sockets disabled, including imports."""
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def deny_network(*args, **kwargs):
    raise OSError('Network disabled for offline regression tests')

if __name__ == '__main__':
    with patch.object(socket.socket, 'connect', deny_network), patch.object(socket.socket, 'connect_ex', deny_network), patch('socket.create_connection', deny_network):
        suite = unittest.defaultTestLoader.discover('tests', pattern='test_*.py')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
