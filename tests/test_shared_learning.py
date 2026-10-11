import base64
from datetime import datetime, timezone
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
    def setUp(self):
        shared_learning._CACHE.update({"ts": 0.0, "data": None, "source": "baseline"})

    def test_large_private_state_loads_blob_on_same_host(self):
        payload = {"forecast": {"samples": 123}, "updated_at": "2026-10-11T19:00:00Z"}
        sha = "a" * 40
        wrappers = [{"encoding": "none", "content": "", "sha": sha},
                    {"encoding": "base64", "content": base64.b64encode(json.dumps(payload).encode()).decode()}]
        requests = []
        def fake_open(request, timeout):
            requests.append(request)
            response = _Response()
            value = wrappers.pop(0)
            response.read = lambda: json.dumps(value).encode()
            return response
        with patch.object(shared_learning, "urlopen", side_effect=fake_open):
            self.assertEqual(shared_learning._fetch_private("test-only"), payload)
        self.assertEqual(requests[1].full_url, f"https://api.github.com/repos/{shared_learning.REPO}/git/blobs/{sha}")
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer test-only")

    def test_failed_download_keeps_age_and_recovery_clears_warning(self):
        payload = {"updated_at": "2026-10-11T19:00:00Z", "background_paper": {"last_cycle_at": "2026-10-11T19:01:00Z"}}
        with patch.object(shared_learning, "_secret_token", return_value=""), patch.object(shared_learning, "_fetch_public", return_value=payload):
            first = shared_learning.fetch_shared_learning_state(ttl=0)
        success = first["data_quality"]["shared_learning_last_success_at"]
        with patch.object(shared_learning, "_secret_token", return_value=""), patch.object(shared_learning, "_fetch_public", side_effect=TimeoutError):
            cached = shared_learning.fetch_shared_learning_state(ttl=0)
        self.assertEqual(cached["updated_at"], "2026-10-11T19:00:00Z")
        self.assertEqual(cached["data_quality"]["shared_learning_last_success_at"], success)
        now = datetime(2026, 10, 11, 19, 30, tzinfo=timezone.utc).timestamp()
        health = shared_learning.learning_freshness(cached, now=now)
        self.assertEqual(health["status"], "CACHED / DOWNLOAD FAILED")
        self.assertEqual(health["learning_age_seconds"], 1800)
        with patch.object(shared_learning, "_secret_token", return_value=""), patch.object(shared_learning, "_fetch_public", return_value=payload):
            restored = shared_learning.fetch_shared_learning_state(ttl=0)
        self.assertFalse(restored["data_quality"]["shared_learning_fetch_failed"])
        self.assertEqual(shared_learning.learning_freshness(restored, now=now)["status"], "STALE")

    def test_fresh_download_cannot_hide_old_paper_cycle(self):
        now = datetime(2026, 10, 11, 19, 30, tzinfo=timezone.utc).timestamp()
        state = {"updated_at": "2026-10-11T19:29:00Z", "background_paper": {"last_cycle_at": "2026-10-11T17:00:00Z"}}
        self.assertEqual(shared_learning.learning_freshness(state, now)["status"], "STALE")
        state["background_paper"]["last_cycle_at"] = "2026-10-11T19:29:00Z"
        self.assertEqual(shared_learning.learning_freshness(state, now)["status"], "CURRENT")
        self.assertEqual(shared_learning.learning_freshness(state, now+600)["status"], "DELAYED")
        for stamp in (None, "bad", "2026-10-11T19:29:00", "2026-10-11T20:00:00Z"):
            state["updated_at"] = stamp
            self.assertEqual(shared_learning.learning_freshness(state, now)["status"], "UNAVAILABLE")

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
