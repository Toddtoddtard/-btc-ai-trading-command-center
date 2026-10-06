import base64
import json
import time
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import streamlit as st

REPO = "Toddtoddtard/-btc-ai-trading-command-center"
BRANCH = "learning-state"
PATH = "learning_state.json"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{PATH}?ref={BRANCH}"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{PATH}"

# Safe baseline so a private-repo fetch failure never leaves approved users with
# an empty learning policy. This is intentionally conservative and paper-only.
BASELINE_STATE = {
    "learning_version": 31,
    "forecast": {
        "samples": 0,
        "direction_hits": 0,
        "kalshi_samples": 0,
        "kalshi_hits": 0,
        "avg_abs_error": 0.0,
        "avg_path_error": 0.0,
        "robust_abs_error": 0.0,
        "robust_path_error": 0.0,
        "ewma_direction_accuracy": 0.5,
        "ewma_brier": 0.25,
        "bias": 0.0,
        "learning_rate": 0.08,
        "momentum_scale": 2.2,
        "target_influence": 0.18,
        "w_ret3": 0.46,
        "w_ret8": 0.34,
        "w_ret15": 0.20,
    },
    "champion_challenger": {
        "minimum_samples": 20,
        "minimum_margin": 0.05,
        "max_error_multiplier": 1.10,
        "required_streak": 3,
        "qualification_streak": 0,
        "promoted": False,
    },
    "confidence_model": {},
    "data_quality": {"fallback_baseline": True},
    "master_history": [],
    "prediction_snapshots": [],
}

_CACHE = {"ts": 0.0, "data": None, "source": "baseline"}


def _secret_token():
    """Read an optional GitHub token from Streamlit Secrets without requiring it."""
    try:
        token = st.secrets.get("github_token")
        if token:
            return str(token).strip()
        github = st.secrets.get("github", {})
        if isinstance(github, dict):
            token = github.get("token")
            if token:
                return str(token).strip()
    except Exception:
        pass
    return ""


def _fetch_private(token):
    req = Request(
        API_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "BTC-AI-Command-Center/shared-learning",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=3.5) as response:
        wrapper = json.loads(response.read().decode("utf-8"))
    raw = base64.b64decode(wrapper["content"]).decode("utf-8")
    return json.loads(raw)


def _fetch_public(cache_key=None):
    url = RAW_URL + (f"?v={int(cache_key)}" if cache_key is not None else "")
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "BTC-AI-Command-Center/shared-learning",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(req, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _worker_state_url():
    url = os.getenv('CONTINUOUS_WORKER_STATE_URL', '').strip()
    if not url:
        try:
            url = str(st.secrets.get('continuous_worker_state_url', '')).strip()
        except Exception:
            pass
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Continuous worker URL must be a plain HTTPS endpoint without credentials')
    return url


def _fetch_worker(url):
    request = Request(url, headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
    with urlopen(request, timeout=3.0) as response:
        state = json.loads(response.read().decode('utf-8'))
    if state.get('version') != 31 or state.get('background_paper', {}).get('paper_only') is not True:
        raise ValueError('Invalid continuous paper state')
    return state


def fetch_shared_learning_state(ttl=20.0):
    now = time.monotonic()
    cached = _CACHE.get("data")
    if isinstance(cached, dict) and now - float(_CACHE.get("ts", 0.0)) < ttl:
        return cached

    token = _secret_token()
    try:
        public_key = int(time.time() // max(float(ttl), 1.0))
        worker_url = _worker_state_url()
        payload = _fetch_worker(worker_url) if worker_url else (_fetch_private(token) if token else _fetch_public(public_key))
        if isinstance(payload, dict):
            payload.setdefault("data_quality", {})
            payload["data_quality"]["shared_learning_source"] = "continuous-worker" if worker_url else ("private-github" if token else "github-raw")
            _CACHE.update({"ts": now, "data": payload, "source": payload["data_quality"]["shared_learning_source"]})
            return payload
    except Exception:
        pass

    if isinstance(cached, dict):
        _CACHE["ts"] = now
        return cached

    baseline = json.loads(json.dumps(BASELINE_STATE))
    baseline["data_quality"]["shared_learning_source"] = "conservative-baseline"
    _CACHE.update({"ts": now, "data": baseline, "source": "conservative-baseline"})
    return baseline


def shared_learning_source():
    return str(_CACHE.get("source") or "baseline")
