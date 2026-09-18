# Work context — BTC AI Trading Command Center

Use this file as the first-pass map for future maintenance/audits so the active runtime does not have to be rediscovered from the full repository history.

## Authoritative runtime path

1. `app.py` — Streamlit UI, live orchestration, master decision display, and calls into the paper engine.
2. `ai_core.py` — shared specialist/forecast logic used by the app and learner.
3. `kalshi_paper_engine.py` — authoritative Streamlit-side SQLite paper-contract ledger and SCALP/LOCK lifecycle.
4. `background_paper.py` — scheduled learner's persistent paper-only mirror stored in learning state; shares constants/fee helpers from `kalshi_paper_engine.py`.
5. `learner.py` — scheduled learning/grade loop and learning-state updates.
6. `bot_intelligence_dashboard.py` — bot/specialist review UI.
7. `research_lab.py` / `research_dashboard.py` — official-settlement shadow trials, calibration baseline, phase results, advisory lifecycle, and UI.
8. `.github/workflows/learn.yml` — scheduled learner execution and learning-state branch writes.
9. `multi_timeframe.py` / `horizon_models.py` / `train_horizon_models.py` — closed-candle 30m through 1M context, causal horizon prediction, live promotion gates, and chronological offline training.
10. `kalshi_microstructure.py` — public order-book parsing; read-only and credential-free.

## Supporting modules extracted from `app.py`

- `dashboard_ui.py` — display formatting, directional badges, and themed table rendering. It has no trading logic.
- `live_feeds.py` — concurrent orchestration of the six independent live reads. Feed functions are injected so failures and timing can be tested offline.

Keep business rules in the authoritative modules above. New display-only helpers belong in
`dashboard_ui.py`; new feed orchestration belongs in `live_feeds.py`. This keeps the Streamlit
entrypoint focused on page composition and makes future audits faster.

## Primary regression coverage

- `tests/test_contract_regressions.py` — contract-entry/exit, fee, LOCK/SCALP, persistence and app integration regressions.
- `tests/test_settlement_rollover.py` — stale-expiry/current-ticker rollover settlement regressions.
- `tests/test_background_paper.py` — scheduled/background paper-ledger behavior.
- `tests/test_research_lab.py` — shadow isolation, official grading, phases, rationale, and lifecycle safeguards.
- `tests/test_live_feeds.py` — concurrent feed orchestration and optional-feed fallbacks.
- `tests/test_dashboard_ui.py` — stable money/percentage and call-badge presentation contracts.
- `.github/workflows/integration-regressions.yml` — compile + offline regression gate.

## Maintenance rules

- Keep the project PAPER ONLY. Do not add private exchange credentials or real-money order endpoints.
- Treat official Kalshi `yes`/`no` settlement as authoritative for binary contract resolution. Never infer settlement from BTC spot.
- Preserve SQLite schema/data compatibility when refactoring `kalshi_paper_engine.py`.
- Preserve the shared-model guarantee: app and learner should use the same specialist/forecast implementations from `ai_core.py`.
- Preserve the immutable one-direction-per-market LOCK behavior and the configured Kalshi entry/exit safeguards unless a separate explicit strategy change is requested.
- Research-lab policy trials and lifecycle labels must stay paper-only and must not alter production execution until independently promoted by a tested strategy change.
- Prefer small helpers and regression tests over duplicating lifecycle logic in `app.py`.

## Historical/support files

Many versioned files under `tools/` and `.github/workflows/` are one-off migration, UI patch, audit or historical validation artifacts. They are not automatically part of the current runtime path. Before editing or deleting one, confirm it is still referenced by an active workflow or current source file. Do not load all of them for routine questions unless the issue specifically points there.

## Fast path for common questions

- Paper trade stuck OPEN / wrong P&L / entry or exit rule: inspect `kalshi_paper_engine.py`, then contract regressions.
- Bot prediction or specialist disagreement: inspect `ai_core.py`, `learner.py`, and the intelligence dashboard.
- Live display/layout issue: inspect `app.py` only after checking whether the displayed value is already wrong upstream.
- Scheduled/background behavior differs from Streamlit: compare `background_paper.py` with `kalshi_paper_engine.py` and `learner.py`.
