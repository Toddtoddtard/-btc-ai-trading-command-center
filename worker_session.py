"""Repeat the existing learner pipeline in one bounded GitHub runner session."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_cycle_deadline = None


def command(*args, cwd=None, env=None, timeout=180):
    if _cycle_deadline is not None:
        timeout = min(timeout, _cycle_deadline - time.monotonic())
        if timeout <= 0:
            raise TimeoutError('Worker cycle exceeded its overall time budget')
    return subprocess.run(args, cwd=cwd, env=env, check=True, timeout=timeout,
                          text=True, stdout=subprocess.PIPE).stdout


def publish_state():
    """Publish only the checkpoint, retaining main code and other branch files."""
    source = Path(os.environ.get('LEARNING_STATE_OUTPUT', '/tmp/learning_state.json')).resolve()
    previous = Path(os.environ.get('LEARNING_STATE_INPUT', '/tmp/previous_learning_state.json'))
    expected = json.loads(previous.read_text())
    command('git', 'config', 'user.name', 'btc-ai-learning-bot')
    command('git', 'config', 'user.email', 'actions@users.noreply.github.com')
    with tempfile.TemporaryDirectory(prefix='btc-publication-') as directory:
        tree = str(Path(directory) / 'state')
        command('git', 'fetch', '--depth=1', 'origin',
                '+learning-state:refs/remotes/origin/learning-state')
        command('git', 'worktree', 'add', '--detach', tree, 'origin/learning-state')
        try:
            if json.loads((Path(tree) / 'learning_state.json').read_text()) != expected:
                raise RuntimeError('Authoritative learning state changed during this cycle; refusing to overwrite it')
            # Whitespace is not learning data. Publish the same complete state
            # compactly so every phone/dashboard downloads fewer bytes.
            compact = json.dumps(json.loads(source.read_text()), separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False)
            (Path(tree) / 'learning_state.json').write_text(compact, encoding='utf-8')
            command('git', 'add', 'learning_state.json', cwd=tree)
            if not command('git', 'diff', '--cached', '--name-only', cwd=tree).strip():
                return
            command('git', 'commit', '-m', 'Update BTC AI learning state', cwd=tree)
            # Rebase only unrelated branch updates; conflicting model/ledger
            # writes fail visibly instead of overwriting a newer checkpoint.
            for attempt in range(3):
                try:
                    command('git', 'push', 'origin', 'HEAD:learning-state', cwd=tree)
                    return
                except subprocess.CalledProcessError:
                    if attempt == 2:
                        raise
                    command('git', 'fetch', 'origin', 'learning-state', cwd=tree)
                    remote = json.loads(command('git', 'show', 'FETCH_HEAD:learning_state.json', cwd=tree))
                    if remote != expected:
                        raise RuntimeError('Authoritative learning state changed before publication retry')
                    command('git', 'rebase', 'FETCH_HEAD', cwd=tree)
        finally:
            subprocess.run(['git', 'worktree', 'remove', '--force', tree], check=True, timeout=30)


def run_cycle():
    env = dict(os.environ)
    output = Path(env.get('LEARNING_STATE_OUTPUT', '/tmp/learning_state.json'))
    previous = Path(env.get('LEARNING_STATE_INPUT', '/tmp/previous_learning_state.json'))
    shutil.copyfile(output, previous)
    env.update(LEARNING_STATE_INPUT=str(previous), LEARNING_STATE_OUTPUT=str(output))
    command(sys.executable, 'learner_v31.py', env=env)
    enriched = output.with_name('learning_state_v4.json')
    command(sys.executable, 'bot_intelligence_report.py',
            env={**env, 'LEARNING_STATE_INPUT': str(output), 'LEARNING_STATE_OUTPUT': str(enriched)})
    enriched.replace(output)
    for script in ('enrich_learning_state_v5.py', 'audit_scorecard_v7.py', 'background_paper.py'):
        command(sys.executable, script, env=env)
    command(sys.executable, 'multi_asset_paper.py', '--state', str(output), env=env)
    command(sys.executable, 'scripts/validate_learning_state.py', env=env)
    publish_state()
    print('Published continuous-session learning and paper checkpoint.', flush=True)


def run_session(minutes, cycle=run_cycle, clock=time.monotonic, sleep=time.sleep, cycle_budget=480):
    global _cycle_deadline
    if not 0 < minutes <= 120:
        raise ValueError('Worker session must be between 0 and 120 minutes')
    deadline = clock() + minutes * 60
    while clock() + cycle_budget <= deadline:
        started = clock()
        _cycle_deadline = time.monotonic() + cycle_budget
        try:
            cycle()
        finally:
            _cycle_deadline = None
        # The existing paper pass evaluates four times, 30 seconds apart.
        # Start the next full learning pass on a 150-second cadence.
        remaining = min(deadline - clock(), started + 150 - clock())
        if remaining > 0:
            sleep(remaining)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--minutes', type=float, default=55)
    parser.add_argument('--publish-only', action='store_true')
    args = parser.parse_args()
    publish_state() if args.publish_only else run_session(args.minutes)
