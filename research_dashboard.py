"""Streamlit renderer for the paper-only KXBTC15M research lab."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def _pct(value):
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def render_research_dashboard(learning_state):
    lab = (learning_state or {}).get("research_lab", {}) or {}
    st.markdown("### Shadow Research Lab")
    st.caption(
        "Official Kalshi settlement, executable asks and paper fees only. "
        "These trials teach the learner but cannot place trades or alter the current execution rules."
    )
    if not lab:
        st.info("The research lab will appear after the upgraded learner publishes its first state.")
        return

    calibration = lab.get("calibration", {}) or {}
    wait = lab.get("wait_counterfactual", {}) or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Settled shadows", int(calibration.get("samples") or 0))
    c2.metric("Model Brier", "—" if calibration.get("model_brier") is None else f"{calibration['model_brier']:.3f}")
    c3.metric("Kalshi baseline", "—" if calibration.get("market_brier") is None else f"{calibration['market_brier']:.3f}")
    edge = calibration.get("model_edge_vs_market")
    c4.metric("Brier edge", "—" if edge is None else f"{edge:+.3f}", "positive beats market")

    league = lab.get("strategy_league", {}) or {}
    policies = []
    for row in league.get("ranking") or []:
        profit_factor = row.get("profit_factor")
        policies.append({
            "Rank": int(row.get("rank") or 0),
            "Shadow strategy": row.get("name"),
            "Status": row.get("status"),
            "Samples": int(row.get("samples") or 0),
            "Score": float(row.get("score") or 0.0),
            "Win rate": None if row.get("win_rate") is None else float(row["win_rate"]) * 100,
            "Bayesian win rate": float(row.get("bayesian_win_rate") or 0.0) * 100,
            "Net paper P/L": float(row.get("net_pnl") or 0.0),
            "Average trade": float(row.get("avg_pnl") or 0.0),
            "Profit factor": None if profit_factor is None else (999.0 if profit_factor == float("inf") else float(profit_factor)),
            "Max drawdown": float(row.get("max_drawdown") or 0.0),
            "Recent average": float(row.get("recent_avg_pnl") or 0.0),
        })
    if policies:
        st.markdown("#### Strategy League — simultaneous shadow trials")
        st.caption(
            "Eight virtual entry policies learn from each official settlement. "
            "LEADER requires at least 40 fee-aware samples and positive net P/L; rankings never place trades."
        )
        frame = pd.DataFrame(policies)
        st.dataframe(frame, use_container_width=True, hide_index=True, column_config={
            "Score": st.column_config.NumberColumn(format="%.1f"),
            "Win rate": st.column_config.NumberColumn(format="%.1f%%"),
            "Bayesian win rate": st.column_config.NumberColumn(format="%.1f%%"),
            "Net paper P/L": st.column_config.NumberColumn(format="$%.2f"),
            "Average trade": st.column_config.NumberColumn(format="$%.3f"),
            "Profit factor": st.column_config.NumberColumn(format="%.2f"),
            "Max drawdown": st.column_config.NumberColumn(format="$%.2f"),
            "Recent average": st.column_config.NumberColumn(format="$%.3f"),
        })

    phases = []
    for name, row in (lab.get("phases") or {}).items():
        n = int(row.get("samples") or 0)
        phases.append({"Window phase": name, "Samples": n, "Win rate": (int(row.get("wins") or 0) / n * 100) if n else None, "Net paper P/L": float(row.get("net_pnl") or 0.0)})
    if phases:
        st.markdown("#### Performance by call timing")
        st.dataframe(pd.DataFrame(phases), use_container_width=True, hide_index=True)

    st.caption(
        f"WAIT counterfactuals: {int(wait.get('samples') or 0)} settled • "
        f"avoided losses {int(wait.get('avoided_losses') or 0)} • "
        f"missed wins {int(wait.get('missed_wins') or 0)} • "
        f"net if traded ${float(wait.get('net_if_traded') or 0.0):+.2f}."
    )

    lifecycle = []
    for name, row in (lab.get("specialist_lifecycle") or {}).items():
        lifecycle.append({
            "Specialist": name, "Lifecycle": row.get("status"), "Samples": int(row.get("samples") or 0),
            "Accuracy": _pct(row.get("accuracy")), "Brier": row.get("brier"), "Reason": row.get("reason"),
        })
    with st.expander("Specialist lifecycle and audit rationale", expanded=False):
        if lifecycle:
            st.dataframe(pd.DataFrame(lifecycle), use_container_width=True, hide_index=True)
        else:
            st.info("Lifecycle evidence is still initializing.")
        st.caption("Lifecycle labels are advisory. Rare-event specialists continue running and collecting shadow evidence.")

    recent = []
    for row in list(lab.get("history") or [])[-12:][::-1]:
        recent.append({
            "Ticker": row.get("ticker"), "Phase": row.get("phase"), "Call": row.get("action"),
            "Direction": row.get("direction"), "Opened UTC": row.get("opened_at_utc"),
            "Expires UTC": row.get("expires_at_utc"), "Official result": row.get("result"),
            "Paper P/L": float(row.get("paper_pnl") or 0.0),
        })
    with st.expander("Recent settled shadow journal (UTC)", expanded=False):
        if recent:
            st.dataframe(pd.DataFrame(recent), use_container_width=True, hide_index=True)
        else:
            st.info("No shadow calls have reached official settlement yet.")
