# Work context — BTC AI Trading Command Center

Use this file as the first-pass map for future maintenance/audits so the active runtime does not have to be rediscovered from the full repository history.

## Authoritative runtime path

1. `app.py` — Streamlit UI, live orchestration, master decision display, and calls into the paper engine.
2. `ai_core.py` — shared specialist/forecast logic used by the app and learner.
3. `kalshi_paper_engine.py` — authoritative Streamlit-side SQLite paper-contract ledger and SCALP/LOCK lifecycle.
4. `background_paper.py` — scheduled learner's persistent paper-only mirror stored in learning state; shares constants/fee helpers from `kalshi_paper_engine.py`.
5. `learner.py` — scheduled learning/grade loop and learning-state updates.
6. `bot_intelligence_dashboard.py` — bot/specialist review UI.
7. `.github/workflows/learn.yml` — scheduled learner execution and learning-state branch writes.

## Primary regression coverage

- `tests/test_contract_regressions.py` — contract-entry/exit, fee, LOCK/SCALP, persistence and app integration regressions.
- `tests/test_settlement_rollover.py` — stale-expiry/current-ticker rollover settlement regressions.
- `tests/test_background_paper.py` — scheduled/background paper-ledger behavior.
- `.github/workflows/integration-regressions.yml` — compile + offline regression gate.

## Maintenance rules

- Keep the project PAPER ONLY. Do not add private exchange credentials or real-money order endpoints.
- Treat official Kalshi `yes`/`no` settlement as authoritative for binary contract resolution. Never infer settlement from BTC spot.
- Preserve SQLite schema/data compatibility when refactoring `kalshi_paper_engine.py`.
- Preserve the shared-model guarantee: app and learner should use the same specialist/forecast implementations from `ai_core.py`.
- Preserve the immutable one-direction-per-market LOCK behavior and the configured Kalshi entry/exit safeguards unless a separate explicit strategy change is requested.
- Prefer small helpers and regression tests over duplicating lifecycle logic in `app.py`.

## Historical/support files

Many versioned files under `tools/` and `.github/workflows/` are one-off migration, UI patch, audit or historical validation artifacts. They are not automatically part of the current runtime path. Before editing or deleting one, confirm it is still referenced by an active workflow or current source file. Do not load all of them for routine questions unless the issue specifically points there.

## Fast path for common questions

- Paper trade stuck OPEN / wrong P&L / entry or exit rule: inspect `kalshi_paper_engine.py`, then contract regressions.
- Bot prediction or specialist disagreement: inspect `ai_core.py`, `learner.py`, and the intelligence dashboard.
- Live display/layout issue: inspect `app.py` only after checking whether the displayed value is already wrong upstream.
- Scheduled/background behavior differs from Streamlit: compare `background_paper.py` with `kalshi_paper_engine.py` and `learner.py`.
