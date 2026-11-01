"""Exercise the workflow's publication commands against competing local writers."""
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


class EventPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        self.repo = self.root / 'watch'
        self.peer = self.root / 'learner'
        self.git(self.root, 'init', '--bare', str(self.remote))
        self.git(self.root, 'init', '-b', 'learning-state', str(self.repo))
        self.configure(self.repo)
        self.commit(self.repo, 'learning_state.json', {'samples': 1})
        self.commit(self.repo, 'political_event_watch.json', {'version': 1})
        self.git(self.repo, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.repo, 'push', 'origin', 'learning-state')
        self.git(self.root, 'clone', '-b', 'learning-state', str(self.remote), str(self.peer))
        self.configure(self.peer)
        self.commit(self.repo, 'political_event_watch.json', {'version': 2})

    def git(self, cwd, *args):
        return subprocess.check_output(['git', *args], cwd=cwd, text=True,
                                       stderr=subprocess.DEVNULL)

    def configure(self, repo):
        self.git(repo, 'config', 'user.name', 'test')
        self.git(repo, 'config', 'user.email', 'test@example.com')

    def commit(self, repo, path, value):
        (repo / path).write_text(json.dumps(value))
        self.git(repo, 'add', path)
        self.git(repo, 'commit', '-m', 'update '+path)

    def publish(self):
        workflow = Path('.github/workflows/political-event-watch.yml').read_text()
        script = workflow.split("git commit -m 'Update political event watch state' || exit 0\n", 1)[1]
        return subprocess.run(['bash', '-e', '-c', textwrap.dedent(script)],
                              cwd=self.repo, text=True, capture_output=True)

    def remote_file(self, path):
        return json.loads(self.git(self.remote, 'show', 'learning-state:'+path))

    def test_publication_without_competing_writer(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_file('political_event_watch.json'), {'version': 2})

    def test_concurrent_learner_update_is_preserved(self):
        self.commit(self.peer, 'learning_state.json', {'samples': 2, 'cash': 466.365})
        self.git(self.peer, 'push', 'origin', 'learning-state')
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.remote_file('learning_state.json'), {'samples': 2, 'cash': 466.365})
        self.assertEqual(self.remote_file('political_event_watch.json'), {'version': 2})

    def test_conflicting_event_update_fails_without_overwriting_remote(self):
        self.commit(self.peer, 'political_event_watch.json', {'version': 3})
        self.git(self.peer, 'push', 'origin', 'learning-state')
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.remote_file('political_event_watch.json'), {'version': 3})
        self.assertEqual(self.remote_file('learning_state.json'), {'samples': 1})
