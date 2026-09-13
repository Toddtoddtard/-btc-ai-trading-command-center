import json
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("streamlit", types.SimpleNamespace(secrets={}))
import shared_learning


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"forecast": {"samples": 1}}).encode()


class SharedLearningTests(unittest.TestCase):
    def test_public_fetch_uses_bounded_cache_buster(self):
        requests = []

        def fake_open(request, timeout):
            requests.append(request)
            return _Response()

        shared_learning._CACHE.update({"ts": 0.0, "data": None, "source": "baseline"})
        with patch.object(shared_learning, "_secret_token", return_value=""), patch.object(
            shared_learning, "urlopen", side_effect=fake_open
        ), patch.object(shared_learning.time, "time", return_value=105.0):
            result = shared_learning.fetch_shared_learning_state(ttl=20.0)

        self.assertEqual(result["forecast"]["samples"], 1)
        self.assertTrue(requests[0].full_url.endswith("?v=5"))


if __name__ == "__main__":
    unittest.main()
