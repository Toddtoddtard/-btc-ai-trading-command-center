import tempfile
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from worker_session import run_session, run_cycle, publish_state


class WorkerSessionTests(unittest.TestCase):
    def test_short_push_session_runs_cycles_with_a_real_advancing_clock(self):
        clock = [0.0]
        starts = []
        def now():
            clock[0] += .01
            return clock[0]
        def cycle():
            starts.append(clock[0])
            clock[0] += 30
        def sleep(seconds):
            clock[0] += seconds
        run_session(12, cycle=cycle, clock=now, sleep=sleep)
        self.assertEqual(len(starts), 2)

    def test_repeated_cycles_publish_without_another_schedule_event(self):
        clock = [0.0]
        cycles = []
        def cycle():
            cycles.append(clock[0])
            clock[0] += 30
        def sleep(seconds):
            clock[0] += seconds
        run_session(6, cycle=cycle, clock=lambda: clock[0], sleep=sleep, cycle_budget=60)
        self.assertEqual(cycles, [0, 150, 300])

    def test_failed_cycle_stops_without_claiming_a_new_checkpoint(self):
        with self.assertRaisesRegex(RuntimeError, 'feed failed'):
            run_session(5, cycle=lambda: (_ for _ in ()).throw(RuntimeError('feed failed')), cycle_budget=60)

    def test_session_reserves_time_for_final_cycle(self):
        clock = [0.0]
        starts = []
        def cycle():
            starts.append(clock[0])
            clock[0] += 480
        run_session(55, cycle=cycle, clock=lambda: clock[0], sleep=lambda seconds: None)
        self.assertLessEqual(clock[0], 55 * 60)
        self.assertEqual(starts[-1], 2400)

    def test_subprocess_timeout_respects_whole_cycle_budget(self):
        from worker_session import command
        with patch('worker_session._cycle_deadline', 105), patch('worker_session.time.monotonic', return_value=100), \
             patch('worker_session.subprocess.run') as run:
            command('python', 'learner.py')
        self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_runtime_is_bounded(self):
        for minutes in (0, -1, 121):
            with self.assertRaises(ValueError):
                run_session(minutes)

    def test_each_cycle_reuses_latest_checkpoint_and_validates_before_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'learning_state.json'
            previous = Path(directory) / 'previous.json'
            output.write_text('current ledger')
            calls = []
            def command(*args, **kwargs):
                calls.append(args[1:])
                if args[1] == 'bot_intelligence_report.py':
                    Path(kwargs['env']['LEARNING_STATE_OUTPUT']).write_text('enriched ledger')
                return ''
            with patch.dict(os.environ, LEARNING_STATE_INPUT=str(previous), LEARNING_STATE_OUTPUT=str(output)), \
                 patch('worker_session.command', side_effect=command), \
                 patch('worker_session.publish_state', side_effect=lambda: calls.append(('publish',))):
                run_cycle()
            self.assertEqual(previous.read_text(), 'current ledger')
            self.assertEqual(output.read_text(), 'enriched ledger')
            self.assertEqual(calls[-2:], [('scripts/validate_learning_state.py',), ('publish',)])

    def test_publication_keeps_runner_on_main_and_preserves_other_state_files(self):
        def git(*args, cwd):
            return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, repo = root / 'remote.git', root / 'repo'
            remote.mkdir()
            repo.mkdir()
            git('init', '--bare', cwd=remote)
            git('init', '-b', 'main', cwd=repo)
            git('config', 'user.name', 'test', cwd=repo)
            git('config', 'user.email', 'test@example.com', cwd=repo)
            (repo / 'worker.py').write_text('runner code')
            git('add', '.', cwd=repo)
            git('commit', '-m', 'main', cwd=repo)
            git('remote', 'add', 'origin', str(remote), cwd=repo)
            git('push', 'origin', 'main', cwd=repo)
            git('checkout', '--orphan', 'learning-state', cwd=repo)
            git('rm', '-rf', '.', cwd=repo)
            (repo / 'learning_state.json').write_text('{"ledger": "old"}')
            (repo / 'political_event_watch.json').write_text('other state')
            git('add', '.', cwd=repo)
            git('commit', '-m', 'state', cwd=repo)
            git('push', 'origin', 'learning-state', cwd=repo)
            git('checkout', 'main', cwd=repo)
            checkpoint = root / 'checkpoint.json'
            checkpoint.write_text('{\n  "ledger": "new"\n}')
            previous = root / 'previous.json'
            previous.write_text('{"ledger": "old"}')
            original_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with patch.dict(os.environ, LEARNING_STATE_OUTPUT=str(checkpoint), LEARNING_STATE_INPUT=str(previous)):
                    publish_state()
                    with self.assertRaisesRegex(RuntimeError, 'changed during this cycle'):
                        publish_state()
            finally:
                os.chdir(original_cwd)
            self.assertEqual(git('branch', '--show-current', cwd=repo).strip(), 'main')
            self.assertEqual((repo / 'worker.py').read_text(), 'runner code')
            self.assertEqual(git('show', 'learning-state:learning_state.json', cwd=remote), '{"ledger":"new"}')
            self.assertEqual(git('show', 'learning-state:political_event_watch.json', cwd=remote), 'other state')
