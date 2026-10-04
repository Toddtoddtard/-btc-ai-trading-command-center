import unittest
from worker_watchdog import recovery_needed

class WatchdogTests(unittest.TestCase):
    def test_fresh_state_never_dispatches(self):
        self.assertFalse(recovery_needed({'updated_at': '1970-01-01T00:15:00+00:00'}, [], 1000))

    def test_stale_state_requests_recovery(self):
        self.assertTrue(recovery_needed({'updated_at': '1970-01-01T00:00:00+00:00'}, [], 1200))

    def test_active_learner_prevents_duplicate_dispatch(self):
        for status in ('queued', 'pending', 'waiting', 'requested', 'in_progress'):
            self.assertFalse(recovery_needed({}, [{'head_branch': 'main', 'status': status}], 2000))
        self.assertTrue(recovery_needed({}, [{'head_branch': 'main', 'status': 'completed'}], 2000))

    def test_future_or_naive_timestamp_fails_visibly(self):
        for stamp in ('1970-01-01T00:00:00', '2099-01-01T00:00:00+00:00'):
            with self.assertRaises(ValueError):
                recovery_needed({'updated_at': stamp}, [], 2000)
