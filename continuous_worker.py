"""Single-writer paper worker for an always-on host; not enabled by deployment.

Requires an explicitly imported authoritative state and persistent storage.
Never bootstraps a new bankroll or authenticates to a trading venue.
"""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
STOP = threading.Event()


def validate(state):
    if state.get('version') != 31:
        raise ValueError('An existing version-31 learning state is required')
    paper = state.get('background_paper', {})
    if paper.get('paper_only') is not True or paper.get('reconciliation', {}).get('ok') is not True:
        raise ValueError('Paper-only reconciled ledger is required')
    if state.get('multi_asset_paper', {}).get('real_money_execution') is not False:
        raise ValueError('Multi-asset live execution must remain disabled')


def atomic_save(path, state):
    validate(state)
    data = json.dumps(state, allow_nan=False)
    temporary = path.with_suffix('.next')
    with temporary.open('w') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_pass(directory, run=subprocess.run):
    authoritative = directory / 'learning_state.json'
    state = json.loads(authoritative.read_text())
    validate(state)
    stage = directory / 'working_state.json'
    stage.write_text(json.dumps(state, allow_nan=False))
    env = dict(os.environ, LEARNING_STATE_INPUT=str(stage), LEARNING_STATE_OUTPUT=str(stage),
               HORIZON_MODELS_INPUT=str(directory / 'horizon_models.json'),
               HISTORICAL_SPECIALIST_INPUT=str(directory / 'historical_specialist_knowledge_v7.json'),
               BACKGROUND_PAPER_CYCLES='1', BACKGROUND_PAPER_INTERVAL_SECONDS='0')
    # Serialize all state mutations. Commit a checkpoint after every completed
    # stage; later failures cannot erase a previously recorded paper position.
    commands = [
        ['learner_v31.py'], ['bot_intelligence_report.py'],
        ['enrich_learning_state_v5.py'], ['audit_scorecard_v7.py'],
        ['background_paper.py'], ['multi_asset_paper.py', '--state', str(stage)],
    ]
    for command in commands:
        run([sys.executable, *command], cwd=ROOT, env=env, check=True, timeout=90)
        candidate = json.loads(stage.read_text())
        validate(candidate)
        if command[0] == 'background_paper.py' and not candidate['background_paper'].get('worker_ok'):
            raise RuntimeError('Paper cycle failed; retaining last committed checkpoint')
        atomic_save(authoritative, candidate)


def main():
    # Cutover must be deliberate: pause the GitHub writer, import its final
    # snapshot, wire Streamlit to this state feed, then activate this service.
    if os.getenv('CONTINUOUS_PAPER_ENABLED') != 'true':
        raise SystemExit('Not activated: complete the documented single-writer cutover first')
    directory = Path(os.environ['WORKER_STATE_DIR']).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / 'worker.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state_path = directory / 'learning_state.json'
    validate(json.loads(state_path.read_text()))
    health = {'last_complete': 0.0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/healthz':
                good = time.time() - health['last_complete'] < 180
                body = json.dumps({'ok': good, 'paper_only': True}).encode()
                self.send_response(200 if good else 503)
            elif self.path == '/learning_state.json':
                # The imported learning state is already public in GitHub.
                body = state_path.read_bytes()
                self.send_response(200)
            else:
                self.send_error(404)
                return
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('0.0.0.0', int(os.getenv('PORT', '10000'))), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())
    try:
        while not STOP.is_set():
            started = time.monotonic()
            try:
                run_pass(directory)
                health['last_complete'] = time.time()
            except Exception as error:
                print(f'Worker pass failed safely: {type(error).__name__}: {error}', flush=True)
            STOP.wait(max(5, 60 - (time.monotonic() - started)))
    finally:
        server.shutdown()
        lock.close()


if __name__ == '__main__':
    main()
