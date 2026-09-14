"""Streamlit control for launching the existing historical BTC backtest.

The historical replay can take several minutes and downloads multiple years of
Binance Vision archives.  Running it synchronously inside a Streamlit button
would freeze the dashboard, so this module launches the repository's existing
``historical_backtest.py`` in a background child process and shows status/results.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
REPORT_PATH = Path(os.getenv("DASHBOARD_BACKTEST_REPORT", "/tmp/btc_dashboard_historical_backtest.json"))
STATE_PATH = Path(os.getenv("DASHBOARD_BACKTEST_STATE", "/tmp/btc_dashboard_historical_backtest_state.json"))
LOG_PATH = Path(os.getenv("DASHBOARD_BACKTEST_LOG", "/tmp/btc_dashboard_historical_backtest.log"))


def _load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def _pid_running(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _current_state():
    state = _load_json(STATE_PATH, {}) or {}
    pid = state.get("pid")
    state["running"] = _pid_running(pid)
    if not state["running"] and pid:
        report = _load_json(REPORT_PATH)
        if report:
            state["status"] = "complete"
            state["finished_at"] = report.get("generated_at") or state.get("finished_at")
        elif state.get("status") == "running":
            state["status"] = "stopped"
        _save_json(STATE_PATH, state)
    return state


def _start_backtest():
    state = _current_state()
    if state.get("running"):
        return False, "A historical backtest is already running."

    try:
        REPORT_PATH.unlink(missing_ok=True)
    except Exception:
        pass

    env = os.environ.copy()
    env["HISTORICAL_BACKTEST_OUTPUT"] = str(REPORT_PATH)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_PATH, "w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "historical_backtest.py")],
            cwd=str(ROOT),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()

    payload = {
        "pid": process.pid,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "report_path": str(REPORT_PATH),
        "log_path": str(LOG_PATH),
    }
    _save_json(STATE_PATH, payload)
    return True, "5-year historical backtest started. It will continue in the background."


def _render_report(report):
    overall = (report or {}).get("overall") or {}
    accuracy = overall.get("direction_accuracy")
    samples = overall.get("samples")
    median_error = overall.get("median_abs_error")
    mean_error = overall.get("mean_abs_error")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Backtest Accuracy", "N/A" if accuracy is None else f"{float(accuracy) * 100:.1f}%")
    c2.metric("Resolved Windows", "N/A" if samples is None else f"{int(samples):,}")
    c3.metric("Median Error", "N/A" if median_error is None else f"${float(median_error):,.2f}")
    c4.metric("Mean Error", "N/A" if mean_error is None else f"${float(mean_error):,.2f}")

    runtime = report.get("runtime_seconds")
    months_loaded = report.get("months_loaded") or []
    months_failed = report.get("months_failed") or []
    generated = report.get("generated_at") or "unknown"
    st.caption(
        f"Latest 5-year walk-forward result • generated {generated} • "
        f"{len(months_loaded)} months loaded • {len(months_failed)} failed"
        + ("" if runtime is None else f" • runtime {float(runtime):.0f}s")
    )


def render_dashboard_backtest():
    """Render the runnable backtest control inside the existing Backtest tab."""
    st.subheader("Historical Backtest Runner")
    st.caption(
        "Runs the repository's existing 5-year BTC 1-minute walk-forward replay using free Binance Vision data. "
        "It is evaluation-only and does not place trades or change live parameters automatically."
    )

    state = _current_state()
    running = bool(state.get("running"))

    left, right = st.columns([2, 1])
    with left:
        if st.button(
            "▶ Run 5-Year Backtest",
            key="run_historical_backtest_from_dashboard",
            type="primary",
            disabled=running,
            use_container_width=True,
        ):
            ok, message = _start_backtest()
            if ok:
                st.success(message)
            else:
                st.warning(message)
            state = _current_state()
            running = bool(state.get("running"))

    with right:
        if st.button("Refresh Status", key="refresh_historical_backtest_status", use_container_width=True):
            state = _current_state()
            running = bool(state.get("running"))

    if running:
        started = state.get("started_at") or "unknown"
        st.info(f"Backtest is running in the background (PID {state.get('pid')}). Started {started}.")
    else:
        status = str(state.get("status") or "idle").lower()
        if status == "stopped" and not REPORT_PATH.exists():
            st.warning("The previous backtest stopped before producing a report. You can run it again.")

    report = _load_json(REPORT_PATH)
    if report:
        _render_report(report)

    if LOG_PATH.exists():
        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(lines[-16:])
            if tail:
                with st.expander("Backtest log", expanded=False):
                    st.code(tail, language="text")
        except Exception:
            pass
