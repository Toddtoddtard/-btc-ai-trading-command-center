# Work context — BTC AI Trading Command Center

Start with `AGENTS.md` and `docs/CODE_MAP.md` for focused maintenance. This file is the dated handoff history; read the sections relevant to the task. Current code and workflows supersede older historical descriptions.

## Learned council confidence (2026-10-21)

- Added confidence-band residual learning from deduplicated, timestamped official
  council outcomes. Each chronological validation prediction uses only labels
  observed before capture. Corrections require 100 prior markets, 100 validation
  calls, at least .002 overall Brier improvement, and nonnegative recent-100
  improvement. Each applied band also needs 30 corrected validation observations
  and its own improvement; thin, harmful and malformed bands retain the formula.
- Frozen formula confidence is retained separately from corrected confidence to
  prevent repeated correction learning from its previous output. Changes are
  capped at 15 percentage points; no outcome or trade history is rewritten.
- Dashboard confidence now matches the shared council used by the worker instead
  of blending target geometry and applying penalties twice. Contract probability,
  strategy thresholds, fees and all specialists remain separate and intact.
- Confidence follows the selected settlement side: an opposite call receives
  the complement of council confidence, including an immutable dashboard LOCK.
  It cannot borrow an 80% DOWN forecast to authorize an 80% UP entry.
- The retained Oct 21 snapshot yielded 351 chronological candidate comparisons:
  Brier .232851 versus formula .236881; recent 100 .227950 versus .230501.
  These retrospective calibration results do not prove increased live accuracy,
  trading frequency or profitability. New official settlements remain necessary.

## Authoritative runtime path

1. `app.py` — Streamlit UI, live orchestration, master decision display, and calls into the paper engine.
2. `ai_core.py` — shared specialist/forecast logic used by the app and learner.
3. `kalshi_paper_engine.py` — SQLite contract engine and shared lifecycle/fee/strategy helpers; its local totals are not the displayed persistent ledger.
4. `background_paper.py` — authoritative persistent paper ledger stored in learning state and consumed by the dashboard; shares constants/fee helpers from `kalshi_paper_engine.py`.
5. `learner_v31.py` — active scheduled learning/grade entrypoint; imports `learner.py` and `learner_v3.py` for supporting functionality.
6. `bot_intelligence_dashboard.py` — bot/specialist review UI.
7. `research_lab.py` / `research_dashboard.py` — official-settlement shadow trials, calibration baseline, phase results, advisory lifecycle, and UI.
8. `.github/workflows/learn.yml` — scheduled learner execution and learning-state branch writes.
9. `multi_timeframe.py` / `horizon_models.py` / `train_horizon_models.py` — closed-candle 30m through 1M context, causal horizon prediction, live promotion gates, and chronological offline training.
10. `kalshi_microstructure.py` — public order-book parsing; read-only and credential-free.

## Supporting modules extracted from `app.py`

- `dashboard_ui.py` — display formatting, directional badges, and themed table rendering. It has no trading logic.
- `live_feeds.py` — concurrent orchestration of independent live reads. Feed functions are injected so failures and timing can be tested offline.

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

- Persistent paper trade stuck OPEN / wrong P&L: inspect `background_paper.py`, its saved source timestamps, and shared helpers in `kalshi_paper_engine.py`.
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

## Chart clarity and active-window bounds (2026-10-10)

- Label the dashboard BTC/USD median estimate separately from Binance BTC/USDT chart candles; these are different price sources, not interchangeable settlement values. No execution or settlement logic changed.
- Browser forecasts stop at the current UTC quarter-hour close and hide once their input candle is more than two minutes old. Selected 1m/5m/15m horizons remain maximum lengths.
- Allow the chart status to wrap, reserve axis/control space, shorten the legend and hide the desktop toolbar on mobile. Use USD in the learning-error caption to prevent Markdown math rendering.
- Chart execution tests reproduce the 21:54 screenshot, check the 22:00 cutoff, and cover stale paths and target rollover.

## Kalshi-native chart feed (2026-10-11)

- Main chart and primary BTC price card now read Kalshi public `/live_data/events/{event_ticker}?range=1h`, using `live_data.details.candlesticks["1M"]` and timestamped `timeseries` values. The endpoint was observed returning live `crypto`/`BTC` data without credentials. No paid feed or trading key is added.
- Reject mismatched events, historical/expired/future windows, and price ticks older than 30 seconds. Never substitute Binance or the USD composite in this chart/card. The server refreshes the chart every five seconds, browser every two seconds.
- Other analysis inputs and the paper learner remain unchanged. Historical path metrics are explicitly labeled as Binance-based; old entry dots without matching price provenance are omitted from this chart.
- Official docs: https://docs.kalshi.com/api-reference/live-data/get-event-live-data . Tests exercise Python and browser parsing, stale data, rollover and no-exchange-fallback behavior.


## 2026-10-11 — r94 dashboard freshness

- Current BTC cards and target-distance metrics now use one Kalshi chart snapshot per dashboard refresh. Missing official quotes show Unavailable; new dashboard LOCK qualification requires a fresh official feed. Technical candles, order flow and 24h metrics explicitly identify Binance.
- Forecast weights, accuracy summary and sidebar paper status reload during fragment refreshes. Saved learning and paper cycles show their own source ages; delayed, stale and failed-download snapshots carry warnings. Enabled paper mode does not imply a currently running worker.
- GitHub authenticated learning-state downloads follow the validated blob SHA when the Contents response omits large-file content. Failed downloads preserve the actual source age and last successful download time.
- Expired cached Kalshi contracts no longer expose a target or probability as active during feed outages.
- Investigation found successful learner runs separated by long GitHub scheduling delays; watchdog recovery dispatch is functioning. GitHub cron remains best effort, so the UI reports delays rather than promising uninterrupted updates.
- Regression coverage includes large-state loading, cache failure/recovery, independent paper-cycle age, summary refresh and contract expiry.

### r95 publication-cache follow-up
Live verification found raw.githubusercontent.com still returning the prior snapshot after a successful learner publication. Added rate-limited public Contents/blob recovery when source data is delayed and monotonic snapshot selection so a stale CDN response cannot roll back newer cached data. Recovery is limited to one attempt per five minutes to respect unauthenticated API limits.

## Efficient maintenance navigation (2026-10-12)

Added concise repository instructions in `AGENTS.md`, task-to-module/test routing in `docs/CODE_MAP.md`, and `tools/code_map.py` for bounded, on-demand source definition/import navigation. Corrected stale architecture and runtime ownership guidance. This is a local standard-library tool, not an installation of Ponytail, OmniRoute or Graphify; no external provider, API cost or runtime trading changes. Token savings are not measured. Validate navigation with a few representative commands; retain existing CI gates.

## Settlement evidence and paper fill reliability (2026-10-16)

- Added independent worker settlement captures, including WAIT and unavailable forecasts, frozen specialist votes and source timestamps. Official outcomes resolve only after expiry; new pending/history state survives subsequent cycles. Legacy history remains intact.
- Learned settlement corrections now require chronological, paired improvement over both the reference-average base and Kalshi. Saved-state diagnostics do not establish post-change performance; new official settlements must supply that evidence.
- Added separately scored 10/5/1-minute checkpoints (nearest capture before each checkpoint within 150 seconds), log loss, calibration, coin-flip and paired market benchmarks, plus unavailable-capture coverage. Coverage cannot certify windows the worker never observed. Fixed contract research comparisons that previously mixed different sample subsets.
- Refreshed same-contract quotes/reference after slow specialist requests. Freshness checks retain source timestamps. New persistent paper fills use observed top-of-book sizes and fees; insufficient fresh exit depth keeps the position open. Historical quote-only ledger outcomes are preserved, not certified as depth-validated results.
- Verification: 405 offline tests passed, including full Streamlit private-access startup; evidence panel rendered with saved-state data; live public Kalshi market/reference prediction and order-book depth reads succeeded. Independent code review's quote-age orchestration finding was fixed and covered by a 40-second-delay regression. No paid feed, API key, strategy-threshold change, balance reset or live orders.
- Live deployment/version verification and newly settled performance must be checked separately from these local checks. GitHub/Streamlit scheduling and real execution latency/queue priority remain limitations.

## Dashboard latency and download size (2026-10-16)

- Native tracked tabs build only the selected panel; all specialists, decisions and safety work still run before the panels. Startup loads its required history and canonical contract concurrently and drops unused startup spot/composite reads.
- Live chart packets contain only the browser's forecast inputs. Exact Node comparisons preserve all forecast candles at 1/5/15 minutes, including enabled learned horizons. Missing probabilities remain missing. The saved-state sample's learning payload shrank from 506,499 to 433 bytes; this is the learning portion, not total websocket traffic.
- Simultaneous fragment requests share one learning download. Publication keeps the full validated learning object and removes JSON formatting whitespace; the sample shrank from 18,754,322 to 13,160,714 bytes without deleting records. Existing source timestamps and failure warnings are preserved.
- A local AppTest harness with fixed 500-candle inputs and outbound sockets disabled measured warm full-render times of 709/699/840 ms before and 594/470/447 ms after (medians 709 vs 470 ms). Default rendered elements fell from 461 to 167. All eight selected tabs rendered without exceptions. These are local fixed-input render measurements, not guaranteed phone or external-feed latency.
- Streamlit minimum is 1.55 for native tab tracking. Build label: r102-faster-dashboard. Free hosting, feed timeouts and full learning downloads still impose limits; no claim of maximum possible optimization.

## Rolling 15-minute curve and Eastern display (2026-10-17)

- Replaced the chart's endpoint easing, fixed sine/cosine wave, minimum forced
  direction and target attraction with same-source minute-specific forecasts.
  The 15-minute selection now spans the rolling next fifteen minutes across a
  contract boundary; the target line still expires independently.
- Added `forecast_curve.py`: closed-candle direct ridge curves, chronological
  validation against flat/legacy baselines, conservative fallback, empirical error
  ranges, durable official history and prospective non-overlapping frozen paths.
  The worker reuses its existing refreshed official feed; no added network call.
- The chart model does not modify trade decisions, settlement predictions,
  next-market outlooks or their scores. Prospective curve evidence starts at zero;
  old model accuracy is not evidence for this replacement. Missing source history
  and free-host scheduling gaps still limit warm-up and coverage.
- Eastern Time presentation across main/other-market charts, timers, tables and
  journals uses America/New_York with EST/EDT; storage and expiry math remain UTC.
- Verification: 423 offline tests passed, plus a local phone-sized browser check
  with external connections blocked: six live updates, one retained chart node,
  retained zoom/horizon, server forecasts and Eastern tick labels. Live official
  Kalshi data produced a valid fifteen-point baseline with 59 closed candles.
  Local median curve-fit cost was 8.32 ms; repeated tick processing 5.79 ms.
  These are local measurements, not guaranteed phone or feed latency.
- Build label: r103-forecast-curve-eastern. Deployment parity remains a separate
  check. Synthetic turning-series tests prove mechanics, not BTC accuracy.
