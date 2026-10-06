import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from continuous_worker import atomic_save, run_pass


def seed():
    return {'version': 31, 'background_paper': {'paper_only': True, 'worker_ok': True,
            'cash': 543.21, 'reconciliation': {'ok': True}},
            'multi_asset_paper': {'real_money_execution': False}}


class ContinuousWorkerTests(unittest.TestCase):
    def test_later_stage_failure_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            target = directory / 'learning_state.json'
            atomic_save(target, seed())
            calls = []
            def run(command, **kwargs):
                calls.append(command[1])
                if command[1] == 'multi_asset_paper.py':
                    raise subprocess.TimeoutExpired(command, 90)
                path = Path(kwargs['env']['LEARNING_STATE_OUTPUT'])
                state = json.loads(path.read_text())
                if command[1] == 'background_paper.py':
                    state['background_paper']['cash'] = 540
                path.write_text(json.dumps(state))
            with self.assertRaises(subprocess.TimeoutExpired):
                run_pass(directory, run=run)
            self.assertEqual(json.loads(target.read_text())['background_paper']['cash'], 540)

    def test_bad_candidate_does_not_replace_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'learning_state.json'
            atomic_save(path, seed())
            state = seed()
            state['background_paper']['reconciliation']['ok'] = False
            with self.assertRaises(ValueError):
                atomic_save(path, state)
            self.assertEqual(json.loads(path.read_text()), seed())

    def test_no_implicit_bankroll_initialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                run_pass(Path(tmp))
