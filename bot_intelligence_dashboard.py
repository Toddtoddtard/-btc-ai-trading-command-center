from __future__ import annotations

import math
import pandas as pd
import streamlit as st

from specialist_knowledge_v5 import knowledge_council_vote


def _f(value, default=float("nan")):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except Exception:
        return default


def _pct(value):
    value = _f(value)
    return "—" if pd.isna(value) else f"{value * 100.0:.1f}%"


def _num(value, digits=3):
    value = _f(value)
    return "—" if pd.isna(value) else f"{value:.{digits}f}"


def _verdict_class(verdict):
    verdict = str(verdict or "LEARNING").upper()
    if verdict == "HIGH VALUE":
        return "bot-high"
    if verdict == "USEFUL":
        return "bot-useful"
    if verdict == "HURTING COUNCIL":
        return "bot-harm"
    if verdict == "REDUNDANT":
        return "bot-redundant"
    return "bot-learning"


def _verdict_icon(verdict):
    verdict = str(verdict or "LEARNING").upper()
    return {
        "HIGH VALUE": "★",
        "USEFUL": "+",
        "HURTING COUNCIL": "!",
        "REDUNDANT": "≈",
        "LEARNING": "…",
    }.get(verdict, "…")


def build_bot_intelligence_rows(results, learning_state, regime):
    intel = (learning_state or {}).get("bot_intelligence_v4", {}) or {}
    ranking = (intel.get("ranking", []) or []) if intel.get("label_basis") == "official_kalshi_directional_calls_v1" else []
    by_name = {str(row.get("name")): row for row in ranking if isinstance(row, dict)}
    specialist_state = (learning_state or {}).get("specialists", {}) or {}

    vote = knowledge_council_vote(results, learning_state or {}, regime)
    members = {m["name"]: m for m in vote["members"]}
    rows = []
    for name, live in (results or {}).items():
        if name == "Combination AI":
            continue
        learned = specialist_state.get(name, {}) or {}
        contribution = by_name.get(name, {})
        verdict = contribution.get("verdict", "LEARNING")
        rows.append({
            "Specialist": name,
            "Status": verdict,
            "Live signal": str((live or {}).get("signal", "NEUTRAL")),
            "Live score": _f((live or {}).get("score"), 0.0),
            "Live confidence": _f((live or {}).get("confidence"), 0.0),
            "Council weight": members.get(name, {}).get("vote_share", 0.0),
            "Samples": int(contribution.get("directional_calls", 0)),
            "Standalone accuracy": _f(contribution.get("standalone_accuracy")),
            "Marginal accuracy": _f(contribution.get("marginal_accuracy")),
            "Contribution score": _f(contribution.get("contribution_score")),
            "Unique saves": _f(contribution.get("unique_save_rate")),
            "Harmful flips": _f(contribution.get("harmful_flip_rate")),
            "Reason": str((live or {}).get("reason", "")),
        })

    order = {"HIGH VALUE": 0, "USEFUL": 1, "LEARNING": 2, "REDUNDANT": 3, "HURTING COUNCIL": 4}
    rows.sort(key=lambda r: (order.get(r["Status"], 9), -_f(r["Contribution score"], -999.0), r["Specialist"]))
    return rows, intel


def render_bot_intelligence_dashboard(results, learning_state, regime, dark_mode=True):
    rows, intel = build_bot_intelligence_rows(results, learning_state, regime)
    evaluated = int(intel.get("evaluated_snapshots") or 0)
    minimum = int(intel.get("minimum_samples_for_verdict") or 12)

    st.markdown("### Bot Intelligence v4")
    st.caption(
        "Accuracy uses active directional predictions and official Kalshi outcomes. Contribution is a retrospective comparison using current weights, not a live win rate. "
        f"Current regime: {regime} • official-result snapshots reviewed: {evaluated:,} • verdict minimum: {minimum} samples."
    )

    candle_lab = (learning_state.get("horizon_models") or {}).get("candle_learning", {})
    if candle_lab:
        with st.expander("Candle and wick learning coverage"):
            st.caption("Replayed candles train the models. Live scores count only forecasts captured before their outcomes. These are BTC direction scores, not Kalshi trade wins.")
            st.write(f"Closed minutes studied: {candle_lab.get('minutes_observed', 0):,} · 15-minute boundaries covered: {candle_lab.get('windows_observed', 0):,} · Backlog: {candle_lab.get('backlog_minutes', 'unknown')} minutes")
            if candle_lab.get("error") or candle_lab.get("blocked_at"):
                st.warning("Candle catch-up is blocked; missing data has not been counted as learned.")
            records = []
            for horizon, model in candle_lab.get("models", {}).items():
                live = model.get("live_metrics", {})
                replay = model.get("replay_metrics", {})
                records.append({"Horizon": f"{horizon}m", "Training labels": model.get("trained", 0),
                                "Live samples": live.get("samples", 0),
                                "Live accuracy": f"{live['hit']:.1%}" if live.get("samples") else "Collecting",
                                "Replay accuracy": f"{replay['hit']:.1%}" if replay.get("samples") else "Collecting",
                                "Forecast influence": "Qualified" if model.get("enabled") else "Learning"})
            st.dataframe(records, hide_index=True)

    if not rows:
        st.info("Bot contribution history is still building. Live specialists continue to run normally while the learner gathers enough graded snapshots.")
        return

    high = sum(r["Status"] == "HIGH VALUE" for r in rows)
    useful = sum(r["Status"] == "USEFUL" for r in rows)
    learning = sum(r["Status"] == "LEARNING" for r in rows)
    harmful = sum(r["Status"] == "HURTING COUNCIL" for r in rows)
    redundant = sum(r["Status"] == "REDUNDANT" for r in rows)

    best = max(rows, key=lambda r: _f(r["Contribution score"], -999.0))
    top_weight = max(rows, key=lambda r: _f(r["Council weight"], 0.0))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("High value", high)
    c2.metric("Useful", useful)
    c3.metric("Still learning", learning)
    c4.metric("Needs review", harmful + redundant, f"{harmful} harmful • {redundant} redundant")
    c5.metric("Top contributor", best["Specialist"], _num(best["Contribution score"], 3))

    if harmful:
        names = ", ".join(r["Specialist"] for r in rows if r["Status"] == "HURTING COUNCIL")
        st.warning(f"Contribution testing currently flags: {names}. The learner reduces influence through learned/regime weights; this is a review signal, not an automatic deletion.")
    elif evaluated >= minimum:
        st.success("No specialist currently meets the threshold for HURTING COUNCIL.")
    else:
        st.info("The contribution model is still accumulating enough resolved windows for strong verdicts. Early rankings should be treated as provisional.")

    cards = sorted(rows, key=lambda r: _f(r["Council weight"], 0.0), reverse=True)[:6]
    card_html = []
    for row in cards:
        verdict = row["Status"]
        cls = _verdict_class(verdict)
        icon = _verdict_icon(verdict)
        signal = row["Live signal"].upper()
        sig_cls = "sig-up" if signal == "BULLISH" else "sig-down" if signal == "BEARISH" else "sig-flat"
        card_html.append(
            f'<div class="bot-card {cls}">'
            f'<div class="bot-card-top"><span class="bot-name">{row["Specialist"]}</span><span class="bot-verdict">{icon} {verdict}</span></div>'
            f'<div class="bot-live {sig_cls}">{signal} {row["Live score"]:+.2f}</div>'
            f'<div class="bot-card-grid"><span>Vote share <b>{row["Council weight"]:.1%}</b></span><span>Accuracy <b>{_pct(row["Standalone accuracy"])}</b></span>'
            f'<span>Contribution <b>{_num(row["Contribution score"], 3)}</b></span><span>Samples <b>{row["Samples"]:,}</b></span></div>'
            f'</div>'
        )

    st.markdown(
        """
        <style>
        .bot-intel-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:.35rem 0 .7rem 0}
        .bot-card{border:1px solid #2b3b52;border-radius:12px;padding:12px;background:linear-gradient(180deg,#0d1727,#09111d);min-height:136px}
        .bot-card.bot-high{border-color:rgba(0,230,179,.72);box-shadow:0 0 16px rgba(0,230,179,.08)}
        .bot-card.bot-useful{border-color:rgba(22,135,255,.70)}
        .bot-card.bot-harm{border-color:rgba(255,73,100,.85);box-shadow:0 0 16px rgba(255,73,100,.10)}
        .bot-card.bot-redundant{border-color:rgba(255,193,7,.55)}
        .bot-card.bot-learning{border-color:rgba(140,160,190,.45)}
        .bot-card-top{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
        .bot-name{font-weight:800;color:#eaf2ff}.bot-verdict{font-size:.74rem;font-weight:800;color:#9fb2ce;text-align:right}
        .bot-live{display:inline-block;margin:10px 0 8px;padding:4px 8px;border-radius:7px;font-weight:900;font-size:.82rem}
        .sig-up{color:#00f0b5;background:rgba(0,240,181,.12)}.sig-down{color:#ff6278;background:rgba(255,73,100,.12)}.sig-flat{color:#c2d1e6;background:rgba(140,160,190,.11)}
        .bot-card-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px 12px;color:#9fb2ce;font-size:.78rem}.bot-card-grid b{color:#eaf2ff}
        @media(max-width:900px){.bot-intel-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:560px){.bot-intel-grid{grid-template-columns:1fr}}
        </style>
        <div class="bot-intel-grid">""" + "".join(card_html) + "</div>",
        unsafe_allow_html=True,
    )

    st.caption(f"Highest current vote share: {top_weight['Specialist']} at {top_weight['Council weight']:.1%} in {regime}.")

    detail = pd.DataFrame(rows)
    detail["Live confidence %"] = detail["Live confidence"] * 100.0
    detail["Council vote share %"] = detail["Council weight"] * 100.0
    detail["Standalone accuracy %"] = detail["Standalone accuracy"] * 100.0
    detail["Marginal accuracy %"] = detail["Marginal accuracy"] * 100.0
    detail["Unique saves %"] = detail["Unique saves"] * 100.0
    detail["Harmful flips %"] = detail["Harmful flips"] * 100.0
    detail = detail[[
        "Specialist", "Status", "Live signal", "Live score", "Live confidence %", "Council vote share %",
        "Samples", "Standalone accuracy %", "Marginal accuracy %", "Contribution score",
        "Unique saves %", "Harmful flips %", "Reason",
    ]]

    with st.expander("Detailed bot contribution table", expanded=False):
        st.dataframe(
            detail,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Live score": st.column_config.NumberColumn(format="%+.3f"),
                "Live confidence %": st.column_config.NumberColumn(format="%.1f%%"),
                "Council vote share %": st.column_config.NumberColumn(format="%.1f%%"),
                "Standalone accuracy %": st.column_config.NumberColumn(format="%.1f%%"),
                "Marginal accuracy %": st.column_config.NumberColumn(format="%+.2f%%"),
                "Contribution score": st.column_config.NumberColumn(format="%+.3f"),
                "Unique saves %": st.column_config.NumberColumn(format="%.2f%%"),
                "Harmful flips %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        st.caption(
            "Marginal accuracy compares the full council with the same historical windows after removing that bot. "
            "Unique saves are windows the full council got right but would have missed without the bot. Harmful flips are the reverse."
        )
