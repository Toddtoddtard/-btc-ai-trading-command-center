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

## Paper recovery (2026-09-28)

- Both paper engines use `scalp_execution_policy` in `kalshi_paper_engine.py`.
- The SCALP gate uses SCALP fills only; the visible overall scorecard still includes LOCKs. The previous background gate incorrectly used all strategies and paused at 50 total fills despite only 46 SCALPs.
- After 50 SCALPs, weak profitability enters PAPER RECOVERY: at most 0.5% cash per entry and one SCALP per market. The latest 50 completed SCALPs decide recovery; historical maximum drawdown above 10% remains a hard pause requiring review.
- Confidence, signal-strength, and strategy-specific price ceilings remain in force. Both entry paths require positive projected SCALP P/L after rounded entry/exit fees.
- The background worker checks market status and expiry after reads and immediately before entry. No fills or historical results are fabricated or reset.
- `tests/test_paper_recovery.py` covers recovery, limits, mixed-strategy accounting, fees, and expiry crossed during a fetch.

## Entry caps (user update 2026-09-28)

- LOCK calls and paper entries accept asks up to and including 93%; SCALPs remain capped at 75%. `entry_price_limit` is shared by both execution paths and the ticket. Confidence and immutable LOCK settlement behavior are unchanged.

## Horizon learning labels (2026-10-01)

- The 1m/5m/15m online models now use the last candle closed at or before their deadline, less than 60 seconds old. The previous nearest-candle lookup could use a later or still-forming candle and train on the wrong direction.
- Missing deadline coverage stays pending. Delayed grading cannot borrow later prices. Tests cover all three horizons, a direction-flipping future candle, missing coverage, and no duplicate training.
- Existing weights and historical metrics are preserved; old scores are not retroactively corrected. This fixes feedback quality, not a demonstrated win-rate increase. The broader forecast-chart learning upgrade remains separate unfinished work.

## Complete-minute candle learning (2026-10-05)

- `candle_learning.py` paginates closed Binance candles from a durable cursor, learns each consecutive minute with delayed 1/5/15m outcomes, and records replay separately from live forecasts. Missing data blocks catch-up explicitly.
- `horizon_models.candle_learning` holds the models and coverage. `learner_v31.py` runs it; the Bot Intelligence coverage expander reports backlog, training and live evidence.
- `docs/CANDLE_LEARNING.md` records source definitions, features, promotion gates and limitations. A qualified model can feed the shared Python forecast's existing bounded horizon component. No replay paper fills or invented order-book data.
- `tests/test_candle_learning.py` covers pagination, gap recovery, duplicate prevention, chunk equivalence, future exclusion and live/replay separation.

## Council parity and official scoring (2026-10-06)

- Dashboard and learner use `knowledge_council_vote`. Combination is excluded; neutral/inactive specialists abstain rather than dilute the denominator. Vote shares are returned by the shared function and displayed as percentages.
- `council_accounting.py` rebuilds specialist counters and regime history from retained immutable prediction snapshots with official yes/no outcomes. Former counters are archived in `legacy_specialist_accounting`; the new scope is retained snapshots, not lifetime. Unknown settlements remain ungraded.
- Old mixed-label contribution multipliers are ignored. Contribution analysis uses official outcomes and the shared knowledge-adjusted scores, labeled retrospective current-policy ablation rather than prospective performance. Spot-direction historical priors are not mixed into official-target reliability.
- Neutral specialists receive no loss in regime learning. Interim spot-based target grading remains provisional; the published authoritative specialist counters use official outcomes. No paper trades or balances are reset.


## Persistent prediction journal (2026-10-09)

- `prediction_journal.py` stores one observed-market row in `learning_state.json`, independent of Streamlit uptime. The learner records the current master action, allows WAIT to become a signal and a SCALP to become the first LOCK, and never reverses that LOCK.
- The dashboard metrics and table read the same shared snapshot. Retained historical forecasts are recovered as FORECAST rows when the old execution action is unknown; they are excluded from signal-call accuracy. Existing dashboard-local rows remain in a separate legacy expander.
- Only official Kalshi yes/no outcomes resolve shared journal rows. Unknown results remain pending; three extra result lookups per run bound retry overhead. No missed windows, paper fills, or historical execution actions are fabricated.
- Persisted journal rows survive source-history truncation. Worker scheduling is still best effort; this change fixes journal persistence and reporting, not scheduler availability.
- `tests/test_persistent_journal.py` covers restart recovery, deduplication, LOCK immutability, official scoring, WAIT exclusion, honest historical recovery and bounded/fair retries.
