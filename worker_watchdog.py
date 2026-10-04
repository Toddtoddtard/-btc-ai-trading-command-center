"""Bounded stale-worker recovery; never reads credentials or places trades."""
import base64
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen

ACTIVE = {'queued', 'in_progress', 'waiting', 'pending', 'requested'}


def state_age(state, now):
    stamp = state.get('updated_at')
    if not stamp:
        return float('inf')
    updated = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if updated.tzinfo is None or updated.timestamp() > now + 60:
        raise ValueError('Learning timestamp is invalid; refusing to report healthy')
    return max(0, now - updated.timestamp())


def recovery_needed(state, runs, now):
    """A stale state may request one run, but never duplicate active work."""
    if any(r.get('head_branch') == 'main' and r.get('status') in ACTIVE for r in runs):
        return False
    return state_age(state, now) >= 10 * 60


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GH_TOKEN']  # Existing, short-lived workflow token only.
    def api(path, payload=None):
        request = Request('https://api.github.com/repos/' + repo + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Authorization': 'Bearer ' + token,
                                   'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2022-11-28'})
        with urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else {}
    content = api('/contents/learning_state.json?ref=learning-state')
    if content.get('encoding') != 'base64' or not content.get('content'):
        content = api('/git/blobs/' + content['sha'])
    state = json.loads(base64.b64decode(content['content']))
    # Query each active status so older queued runs cannot be hidden by pagination.
    runs = []
    for status in sorted(ACTIVE):
        runs.extend(api('/actions/workflows/learn.yml/runs?branch=main&status=' + status + '&per_page=100').get('workflow_runs', []))
    now = datetime.now(timezone.utc).timestamp()
    verify_only = os.getenv('RECOVERY_VERIFY_ONLY') == 'true'
    needed = not verify_only and recovery_needed(state, runs, now)
    if needed:
        api('/actions/workflows/learn.yml/dispatches', {'ref': 'main'})
    message = ('Requested a recovery run; completion is not yet verified.' if needed
               else 'No recovery requested: state is fresh or learner is already active.')
    if verify_only:
        message = 'Post-run freshness check only; scheduled checks handle retries without recursive dispatch.'
    print(message)
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as out:
            out.write(f"Learner state timestamp: {state.get('updated_at')}\n\n{message}\n")
    # An active/queued job is not proof that data is fresh. Mark the check red
    # until a later check observes a fresh publication, even after dispatch.
    if state_age(state, now) >= 20 * 60:
        raise RuntimeError('Learning state is at least 20 minutes stale. Recovery remains unverified.')


if __name__ == '__main__':
    main()
