import unittest
import base64
import json
import os
from pathlib import Path
from unittest.mock import patch
from worker_watchdog import recovery_needed, state_age

class WatchdogTests(unittest.TestCase):
    def test_shared_state_queue_cannot_replace_pending_model_publication(self):
        workflows = Path(__file__).resolve().parents[1] / '.github' / 'workflows'
        for name in ('learn.yml', 'train-horizon-models.yml'):
            source = (workflows / name).read_text()
            block = source.split('group: btc-ai-learning-state\n', 1)[1].split('\n\n', 1)[0]
            with self.subTest(workflow=name):
                self.assertIn('queue: max', block)
                self.assertIn('cancel-in-progress: false', block)

    def test_periodic_recovery_checks_before_dispatch_instead_of_queueing_learners(self):
        workflows = Path(__file__).resolve().parents[1] / '.github' / 'workflows'
        learner = (workflows / 'learn.yml').read_text().split('\npermissions:', 1)[0]
        watchdog = (workflows / 'health-watchdog.yml').read_text()
        self.assertNotIn('\n  schedule:', learner)
        self.assertIn("cron: '4-59/5 * * * *'", watchdog)
        self.assertIn('run: python worker_watchdog.py', watchdog)

    def test_fresh_state_never_dispatches(self):
        self.assertFalse(recovery_needed({'updated_at': '1970-01-01T00:15:00+00:00'}, [], 1000))

    def test_stale_state_requests_recovery(self):
        self.assertFalse(recovery_needed({'updated_at': '1970-01-01T00:00:00+00:00'}, [], 599))
        self.assertTrue(recovery_needed({'updated_at': '1970-01-01T00:00:00+00:00'}, [], 600))
        self.assertTrue(recovery_needed({'updated_at': '1970-01-01T00:00:00+00:00'}, [], 1200))

    def test_stale_state_is_not_fresh_just_because_job_is_active(self):
        state = {'updated_at': '1970-01-01T00:00:00+00:00'}
        self.assertFalse(recovery_needed(state, [{'head_branch': 'main', 'status': 'queued'}], 3600))
        self.assertEqual(state_age(state, 3600), 3600)

    def test_active_learner_prevents_duplicate_dispatch(self):
        for status in ('queued', 'pending', 'waiting', 'requested', 'in_progress'):
            self.assertFalse(recovery_needed({}, [{'head_branch': 'main', 'status': status}], 2000))
        self.assertTrue(recovery_needed({}, [{'head_branch': 'main', 'status': 'completed'}], 2000))

    def test_future_or_naive_timestamp_fails_visibly(self):
        for stamp in ('1970-01-01T00:00:00', '2099-01-01T00:00:00+00:00'):
            with self.assertRaises(ValueError):
                recovery_needed({'updated_at': stamp}, [], 2000)

    def test_finishing_worker_hands_off_even_when_checkpoint_is_fresh(self):
        state = {'updated_at': '1970-01-01T00:15:00+00:00'}
        runs = [{'id': 42, 'head_branch': 'main', 'status': 'in_progress'}]
        self.assertTrue(recovery_needed(state, runs, 1000, handoff_run_id='42'))

    def test_handoff_does_not_duplicate_a_successor_already_queued(self):
        for status in ('queued', 'pending', 'waiting', 'requested', 'in_progress'):
            runs = [{'id': 42, 'head_branch': 'main', 'status': 'in_progress'},
                    {'id': 43, 'head_branch': 'main', 'status': status}]
            self.assertFalse(recovery_needed({}, runs, 1000, handoff_run_id='42'))

    def test_live_handoff_posts_one_dispatch_from_finishing_run(self):
        from datetime import datetime, timezone
        from worker_watchdog import main
        from io import BytesIO
        state = {'updated_at': datetime.now(timezone.utc).isoformat()}
        requests = []
        def respond(request, timeout):
            requests.append(request)
            if '/contents/' in request.full_url:
                body = {'encoding': 'base64', 'content': base64.b64encode(json.dumps(state).encode()).decode()}
            elif request.data:
                body = None
            else:
                body = {'workflow_runs': [{'id': 42, 'head_branch': 'main', 'status': 'in_progress'}]}
            return BytesIO(json.dumps(body).encode() if body is not None else b'')
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'owner/repo', 'GH_TOKEN': 'test',
                                    'WORKER_HANDOFF_RUN_ID': '42'}, clear=True), \
                patch('worker_watchdog.urlopen', side_effect=respond):
            main()
        posts = [request for request in requests if request.data]
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0].full_url.endswith('/actions/workflows/learn.yml/dispatches'))
        self.assertEqual(json.loads(posts[0].data), {'ref': 'main'})

    def run_with_api_errors(self, failures, failed_method='GET'):
        from datetime import datetime, timezone
        from worker_watchdog import main
        from io import BytesIO
        requests = []
        def respond(request, timeout):
            requests.append(request)
            if request.get_method() == failed_method and failures:
                raise failures.pop(0)
            if '/contents/' in request.full_url:
                body = {'encoding': 'base64', 'content': base64.b64encode(json.dumps(
                    {'updated_at': datetime.now(timezone.utc).isoformat()}).encode()).decode()}
            elif request.data:
                body = None
            else:
                body = {'workflow_runs': [{'id': 42, 'head_branch': 'main', 'status': 'in_progress'}]}
            return BytesIO(json.dumps(body).encode() if body is not None else b'')
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'owner/repo', 'GH_TOKEN': 'test',
                                     'WORKER_HANDOFF_RUN_ID': '42'}, clear=True), \
             patch('worker_watchdog.urlopen', side_effect=respond), patch('time.sleep'):
            try:
                main()
            finally:
                self.api_requests = requests
        return requests

    def test_temporary_read_failure_does_not_break_successor_handoff(self):
        from urllib.error import HTTPError
        requests = self.run_with_api_errors([HTTPError('https://api.github.com', 502, 'Bad Gateway', {}, None)])
        self.assertEqual(sum('/contents/' in r.full_url for r in requests), 2)
        self.assertEqual(sum(r.get_method() == 'POST' for r in requests), 1)

    def test_read_retries_are_bounded_and_never_dispatch_without_run_checks(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError):
            self.run_with_api_errors([HTTPError('https://api.github.com', 502, 'Bad Gateway', {}, None) for _ in range(3)])
        self.assertEqual(len(self.api_requests), 3)
        self.assertTrue(all(r.get_method() == 'GET' for r in self.api_requests))

    def test_permission_errors_are_not_retried(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError):
            self.run_with_api_errors([HTTPError('https://api.github.com', 403, 'Forbidden', {}, None)])
        self.assertEqual(len(self.api_requests), 1)

    def test_ambiguous_dispatch_failure_is_not_retried(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError):
            self.run_with_api_errors([HTTPError('https://api.github.com', 502, 'Bad Gateway', {}, None)], 'POST')
        self.assertEqual(sum(r.get_method() == 'POST' for r in self.api_requests), 1)
