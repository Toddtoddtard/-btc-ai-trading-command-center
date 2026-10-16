import base64
import json
import time
from datetime import datetime, timezone
import re
from threading import Lock
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

_CACHE = globals().get("_CACHE", {"ts": 0.0, "data": None, "source": "baseline"})
_PUBLIC_API_RETRY_AT = globals().get("_PUBLIC_API_RETRY_AT", float("-inf"))
_CACHE_LOCK = globals().get('_CACHE_LOCK', Lock())


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
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "BTC-AI-Command-Center/shared-learning",
        "Cache-Control": "no-cache",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(API_URL, headers=headers)
    with urlopen(req, timeout=3.5) as response:
        wrapper = json.loads(response.read().decode("utf-8"))
    # GitHub's Contents API omits content for files larger than 1 MB.
    # Learning history has crossed that boundary; fetch the same blob instead.
    if wrapper.get("encoding") != "base64" or not wrapper.get("content"):
        sha = str(wrapper.get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Learning-state blob SHA missing")
        blob_request = Request(
            f"https://api.github.com/repos/{REPO}/git/blobs/{sha}",
            headers=dict(req.header_items()),
        )
        with urlopen(blob_request, timeout=3.5) as response:
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


def fetch_shared_learning_state(ttl=20.0):
    # Sidebar, chart and dashboard fragments share a process cache. Recheck
    # its TTL under one lock instead of downloading the same large state twice.
    with _CACHE_LOCK:
        return _fetch_shared_learning_state(ttl)


def _fetch_shared_learning_state(ttl):
    global _PUBLIC_API_RETRY_AT
    now = time.monotonic()
    cached = _CACHE.get("data")
    if isinstance(cached, dict) and now - float(_CACHE.get("ts", 0.0)) < ttl:
        return cached

    token = _secret_token()
    try:
        public_key = int(time.time() // max(float(ttl), 1.0))
        payload = _fetch_private(token) if token else _fetch_public(public_key)
        source = "private-github" if token else "github-raw"
        if isinstance(payload, dict):
            # Raw branch URLs can lag a successful publication despite cache busting.
            # Bound unauthenticated API recovery to at most 24 requests/hour
            # (Contents + blob), and never replace a newer saved snapshot.
            if not token and learning_freshness(payload)["warning"] and now - _PUBLIC_API_RETRY_AT >= 300:
                _PUBLIC_API_RETRY_AT = now
                try:
                    recovered = _fetch_private("")
                    if snapshot_timestamp(recovered) > snapshot_timestamp(payload):
                        payload, source = recovered, "github-api"
                except Exception:
                    pass
            if isinstance(cached, dict) and snapshot_timestamp(cached) > snapshot_timestamp(payload):
                payload = json.loads(json.dumps(cached))
                source = payload.get("data_quality", {}).get("shared_learning_source", source)
            payload.setdefault("data_quality", {})
            payload["data_quality"]["shared_learning_source"] = source
            payload["data_quality"]["shared_learning_fetch_failed"] = False
            payload["data_quality"]["shared_learning_last_success_at"] = datetime.now(timezone.utc).isoformat()
            _CACHE.update({"ts": now, "data": payload, "source": payload["data_quality"]["shared_learning_source"]})
            return payload
    except Exception:
        pass

    if isinstance(cached, dict):
        _CACHE["ts"] = now  # Retry throttle, not a successful-download timestamp.
        cached.setdefault("data_quality", {})["shared_learning_fetch_failed"] = True
        return cached

    baseline = json.loads(json.dumps(BASELINE_STATE))
    baseline["data_quality"]["shared_learning_source"] = "conservative-baseline"
    _CACHE.update({"ts": now, "data": baseline, "source": "conservative-baseline"})
    return baseline


def shared_learning_source():
    return str(_CACHE.get("source") or "baseline")


def learning_freshness(state, now=None):
    """Describe source age separately from fetch time; never relabel a retry fresh."""
    now = time.time() if now is None else float(now)
    state = state or {}
    quality = state.get("data_quality") or {}
    def age(stamp):
        try:
            parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.timestamp() > now + 60:
                return None
            return max(0.0, now - parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
    learning_age = age(state.get("updated_at"))
    paper_age = age((state.get("background_paper") or {}).get("last_cycle_at"))
    unavailable = bool(quality.get("fallback_baseline")) or learning_age is None
    fetch_failed = bool(quality.get("shared_learning_fetch_failed"))
    def label(seconds):
        return "unknown age" if seconds is None else f"{seconds / 60:.1f} minutes old"
    status = "UNAVAILABLE" if unavailable else (
        "STALE" if learning_age >= 1200 or paper_age is None or paper_age >= 1200 else
        "DELAYED" if learning_age >= 600 or paper_age >= 600 else "CURRENT"
    )
    if fetch_failed:
        status = "CACHED / DOWNLOAD FAILED"
    message = f"{status} — learning snapshot {label(learning_age)}; paper cycle {label(paper_age)}."
    if status != "CURRENT":
        message += " Saved balances, calls and accuracy below are historical snapshots, not proof the worker is running now."
    return {"status": status, "message": message, "warning": status != "CURRENT",
            "learning_age_seconds": learning_age, "paper_age_seconds": paper_age,
            "fetch_failed": fetch_failed}


def snapshot_timestamp(state):
    """Order snapshots by publication time, not by when a CDN returned them."""
    try:
        stamp = datetime.fromisoformat(str(state.get("updated_at")).replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.timestamp() > time.time() + 60:
            return float("-inf")
        return stamp.timestamp()
    except (AttributeError, TypeError, ValueError, OverflowError):
        return float("-inf")
