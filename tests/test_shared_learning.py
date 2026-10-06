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
    def test_worker_feed_is_used_without_github_fallback(self):
        shared_learning._CACHE.update({"ts": 0.0, "data": None})
        state = {"version": 31, "background_paper": {"paper_only": True}}
        with patch.object(shared_learning, "_worker_state_url", return_value="https://worker.example/learning_state.json"), patch.object(shared_learning, "_fetch_worker", return_value=state), patch.object(shared_learning, "_fetch_public") as public, patch.object(shared_learning, "_fetch_private") as private:
            result = shared_learning.fetch_shared_learning_state(ttl=0)
        self.assertEqual(result["data_quality"]["shared_learning_source"], "continuous-worker")
        public.assert_not_called()
        private.assert_not_called()

    def test_failed_worker_feed_retains_last_state_without_switching_writer(self):
        state = {"version": 31, "background_paper": {"paper_only": True}}
        shared_learning._CACHE.update({"ts": 0.0, "data": state})
        with patch.object(shared_learning, "_worker_state_url", return_value="https://worker.example/learning_state.json"), patch.object(shared_learning, "_fetch_worker", side_effect=TimeoutError), patch.object(shared_learning, "_fetch_public") as public, patch.object(shared_learning, "_fetch_private") as private:
            result = shared_learning.fetch_shared_learning_state(ttl=0)
        self.assertIs(result, state)
        public.assert_not_called()
        private.assert_not_called()

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
