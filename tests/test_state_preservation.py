import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import background_paper
import learner_v31


class StatePreservationTests(unittest.TestCase):
    def test_explicit_missing_or_invalid_snapshot_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            for raw in (None, '{broken', '{}'):
                if raw is not None:
                    path.write_text(raw)
                with patch.dict(os.environ, {'LEARNING_STATE_INPUT': str(path)}), patch.object(learner_v31.legacy, 'load') as fallback:
                    with self.assertRaises((OSError, ValueError)):
                        learner_v31.load_previous_state()
                    fallback.assert_not_called()

    def test_broken_optional_bundle_preserves_authoritative_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            bundle = Path(directory) / 'bundle.json'
            state.write_text(json.dumps({'forecast': {}, 'background_paper': {'cash': 543.213}}))
            bundle.write_text('{broken')
            with patch.dict(os.environ, {'LEARNING_STATE_INPUT': str(state), 'HORIZON_MODELS_INPUT': str(bundle)}), patch.object(learner_v31.legacy, 'load') as fallback:
                loaded = learner_v31.load_previous_state()
                self.assertEqual(loaded['background_paper']['cash'], 543.213)
                fallback.assert_not_called()

    def test_failed_checkpoint_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{"cash": 543.213}')
            for state in ({'cash': float('nan')}, {'bad': object()}):
                with self.assertRaises((TypeError, ValueError)):
                    background_paper.save_checkpoint(path, state)
                self.assertEqual(json.loads(path.read_text()), {'cash': 543.213})
                self.assertEqual(len(list(Path(directory).iterdir())), 1)
            with patch.object(background_paper.os, 'replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    background_paper.save_checkpoint(path, {'cash': 550})
            self.assertEqual(json.loads(path.read_text()), {'cash': 543.213})
            background_paper.save_checkpoint(path, {'cash': 550})
            self.assertEqual(json.loads(path.read_text()), {'cash': 550})
