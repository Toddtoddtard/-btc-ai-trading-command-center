# BTC AI Trading Command Center — Architecture

For focused maintenance, start with [the code map](docs/CODE_MAP.md) and
`python tools/code_map.py <file.py> --symbol <name>`.

The Streamlit entrypoint is `app.py`. Kalshi's public event chart supplies its
main BTC chart and current-price cards. Binance supplies technical candles,
aggregate trades and derivatives context. `live_feeds.py` coordinates concurrent
reads, while `dashboard_ui.py` owns presentation helpers.

Shared specialist and forecast functions live in `ai_core.py`. The council,
reliability checks and contract calibration feed the dashboard and scheduled
learner. `lock_focus.py` owns LOCK qualification; paper execution uses shared
strategy and fee helpers in `kalshi_paper_engine.py`.

`council_accounting.py` also fits `council_confidence.py` from independent
official outcomes and frozen formula confidence. Confidence-band residuals are
shrunk and bounded; both overall chronological evidence and each applied band's
own validation must qualify before a correction is used. The dashboard and
worker consume the same council confidence without a second geometry blend or
calibration penalty. If the selected settlement side opposes the council, its
confidence is the complement; neutral council evidence supplies no advantage.
Contract fair value and fee-aware entry remain separate.

New LOCK entries require validated terminal probability and positive expected
settlement proceeds after entry fees. Council confidence is a separate measure
and cannot substitute for contract probability. An immutable LOCK direction
does not freeze authorization: current probability and reliability evidence
must still approve an unfilled call. Promotion of existing SCALP exposure also
requires current approval and a validated advantage to holding versus selling.
Pending LOCK wait status follows that current authorization; independent live
research calls retain their own action and veto rather than being relabeled as
the original LOCK. The shared entry-quote check tolerates only floating-point
subtraction noise in binary complementary quotes, while rejecting crossed ticks.
The scheduled worker anchors terminal probabilities and technical forecast moves
to a fresh, matching Kalshi event-chart price, as the dashboard does. Binance
candles remain the technical signal and path-learning source; a missing, stale,
future or mismatched Kalshi reference vetoes entry rather than substituting USDT.
For active markets, an unusable execution book on the first public host is
retried on the backup host before simulated fills are rejected. Both failed
depth reads still block fills; official closed-market settlement reads continue.

The active scheduled entrypoint is `learner_v31.py`, supported by `learner.py`
and `learner_v3.py`. `.github/workflows/learn.yml` runs learning, enrichment and
`background_paper.py`, then publishes the persistent ledger and model state to
`learning-state`. The dashboard reads that state through `shared_learning.py`.
After its first validated publication, `worker_session.py` repeats the same
pipeline for a bounded 55-minute session, starting cycles every 150 seconds
and publishing each validated checkpoint. Publication uses a separate Git
worktree, so runner code remains on its original main revision and unrelated
state files are preserved. Ordinary pushes and bounded rebase retries retain
concurrent unrelated branch updates; conflicting ledger writes fail visibly.
Before a successful main worker finishes, it calls `worker_watchdog.py` with
its own run ID to dispatch one successor directly. The active-run check ignores
only that finishing run and retains any other active or queued learner; workflow
concurrency serializes ledger writers. Main push runs use an 12-minute session
to exercise the first handoff promptly; subsequent workers use 55 minutes.
Five-minute cron requests and the stale-state watchdog remain recovery backups.
GitHub runner startup is still best effort; source timestamps determine freshness,
and a queued successor is never reported as proof of a fresh publication.

The market chart mounts once outside the live fragments. The dashboard's refresh
cadence (one second by default) sends a compact same-origin data packet from a
zero-height Streamlit component into that retained chart. Plotly updates traces
in place, retaining zoom and the selected prediction horizon. The server chart
feed is cached for one second; browser-side Kalshi polling remains a fallback.
Only the forming candle incorporates the latest observed tick. Closed history
and learning/paper source timestamps retain their original meaning; a one-second
display update does not imply a new completed outcome or worker publication.

Only the selected dashboard tab builds its charts, tables and HTML. Native
state-tracking tabs require Streamlit 1.55 or newer; tab selection lives inside
the dashboard fragment, preserving the separately mounted market chart. All
specialist evaluation, decision safeguards and journal/learning work remain
outside the tab gates. Initial chart setup reads technical history and the
canonical contract concurrently without waiting for unrelated spot/composite
reads; those feeds still load for full dashboard analysis.

Chart packets project learned state to exactly the scalar coefficients,
horizon-enabled flags and latest horizon probabilities consumed by the browser.
Training rows, model diagnostics and pending labels stay on the server; this
does not remove them from learning. Missing probabilities remain absent rather
than becoming a numeric zero in JavaScript. Concurrent fragments share one
learning-state download under a process lock, retaining existing source-age and
failure reporting. The worker publishes the complete validated learning JSON
without formatting whitespace; consumers and concurrent-publication checks
continue comparing decoded state.


## Shared-model guarantee

`app.py` and the learner stack reuse specialist and forecast implementations from `ai_core.py`. Shared formulas reduce drift, but input sources and eligibility paths still need parity checks; reuse alone does not prove identical decisions.

Independent horizon models live in `horizon_models.py`. Their 21-feature schema combines 14 short-horizon features with seven scale-normalized higher-timeframe returns. `multi_timeframe.py` rejects the currently forming candle; historical training reconstructs the same features only after each bar's close boundary. Predictions are persisted before their labels exist, graded in timestamp order, and updated only after grading. Offline candidates use chronological train/calibration/untouched-test partitions. They must pass historical validation plus repeated live Brier-score gates before a bounded 25% blend can influence the forecast. Until then they are diagnostic shadow models.

Kalshi depth is read from the unauthenticated public order-book endpoint. `kalshi_microstructure.py` reconstructs asks from the opposite bid side and exposes midpoint, spread, depth imbalance, and microprice. No credentials or order endpoints are present.

## Specialist council

Pattern AI version 3 shares the candle learner's 20-bar high/low sweep definition:
an excursion beyond the prior range followed by a completed close back inside
the breached boundary. A low-only sweep adds bullish evidence; a high-only sweep
adds bearish evidence. A bar sweeping both sides supplies no directional sweep
vote. The 0.50 raw pattern contribution is an experimental heuristic, not a
calibrated probability. Named sweep observations also enter the existing official
Kalshi settlement signal scorecard, including WAIT observations. Candle-model
features and saved weights keep their existing definitions and ordering. Older
Pattern votes remain archived but cannot train version 3 reliability or its
contribution multiplier; other specialists and paper ledgers are retained.

The shared specialist council contains Trend, Momentum, Volume, Pattern, Support/Resistance, Volatility, Market Regime, Whale, Liquidity, Derivatives, Kalshi Context, Historical Pattern, and Combination AI.

`Kalshi Context AI` is intentionally named this way because its inputs are Kalshi market probability and BTC distance from the active target; it is not a news/event feed.

Council contribution analysis tests gated council subdecisions using prior
available official outcomes, with WAIT excluded from win rates. It is a controlled
comparison without contribution multipliers in either arm, not a replay of
Master fills. `contribution_evidence.py` requires active-market evidence,
multiple-comparison correction and persistence over new outcomes before a bounded
weight change. `outcome_timing.py` uses recorded observation times, or an explicitly
assumed two-minute legacy settlement lag. See `docs/COUNCIL_REVIEW.md` for scope
and limitations.

`contract_probability.py` supplies the existing execution probability using strike distance measured in remaining-window volatility, the council score, and weighted order-book pressure. Kalshi's midpoint remains the dominant anchor until independent walk-forward evidence proves incremental Brier value.

`settlement_predictor.py` is a separate shadow challenger for the exact active KXBTC15M contract: the rounded final 60-second reference average must be at least its target for YES. It uses fresh matching Kalshi event-chart ticks and closed reference candles, accounts for the already observed final-minute prefix, and approximates remaining average uncertainty with arithmetic Brownian motion. Missing prefix seconds, unsupported strike rules, stale data and contract mismatches return unavailable. Timestamped worker and dashboard quotes must be at most 30 seconds old. Legacy observations without quote timestamps remain identifiable; they are not retroactively certified fresh.

Each full worker pass freezes a settlement observation independently of research-phase deduplication and trade approval, preserving WAIT calls, specialist votes, timestamps, target/rule, and unavailable reasons. Only official binary results read after expiry resolve these observations; unresolved labels are retained. The last 3,000 settled captures supplement the existing research history. Earliest-per-contract observations train the bounded ridge residual, but it remains disabled until at least 100 chronological validation markets follow at least 100 training markets and beat both the uncorrected model and Kalshi midpoint by 0.0005 Brier overall, with nonnegative recent paired improvement. Each validation fit uses only outcomes observed before its forecast. No retrospective refitting changes a stored prediction.

The settlement evidence panel shows independent accuracy, Brier, log loss, calibration and the paired market/coin-flip benchmarks. Its 10-, 5- and 1-minute checkpoints select the closest capture before each checkpoint within 150 seconds; they never borrow later forecasts. Sampling is limited by worker cadence, not the one-second screen refresh. Coverage describes retained observed markets and unavailable captures, not continuous uptime or unobserved outage windows. The experimental model never changes paper execution approval. Legacy Binance snapshots are not backfilled as official reference features.

The persistent paper reader fetches current public order-book depth. New entries consume no more than the observed selected-side best ask size, with fees recomputed for that size; failed depth or stale quotes block simulated fills. A SCALP exit requires sufficient fresh best-bid size for the full position; otherwise it remains open until another quote or official settlement. This conservative full-fill model does not simulate partial exits, latency or queue priority, and depth availability is not a guarantee of real execution. New positions record `OBSERVED_TOP_OF_BOOK`; injected legacy quote-only snapshots record `LEGACY_QUOTE_ONLY`. Historical ledger results are preserved, not reclassified as depth-validated performance. Contract-versus-market research Brier comparisons use the same subset of markets and display its own sample count and accuracy.

## Kalshi target handling

The current KXBTC15M contract is chosen deterministically and then re-fetched by exact ticker. The target remains pinned to that contract until expiration. The app, chart, decision engine, and learner use the same target semantics.

The main chart and current-price cards use the Kalshi event chart feed. Technical candle/path learning uses Binance closed-minute data and keeps price errors separate from binary correctness. Official Kalshi market `result` values determine contract outcomes and council calibration; see `docs/ACCURACY_LEARNING.md` for the October 12 accounting repair.

## Learning state

GitHub Actions runs `.github/workflows/learn.yml` every five minutes. The worker writes version-31 state to the `learning-state` branch. `.github/workflows/train-horizon-models.yml` retrains horizon candidates weekly. State includes bounded forecast weights, specialist adaptive weights, rolling history, real 15-candle path error, official Kalshi settlement accuracy, horizon-model evidence, and a paper-only research lab.

The research lab can record one independent shadow call in each `OPEN`, `MIDDLE`, `FINAL 5`, and `FINAL 2` phase. It grades model Brier score against the contemporaneous Kalshi midpoint, counterfactual WAIT outcomes, fee-aware one-contract paper P/L, and simultaneous entry-policy candidates. Specialist lifecycle labels are advisory and never disable execution.

Evaluation also publishes an independent-market scorecard that retains only the earliest forecast per ticker. This prevents multiple refreshes or phase observations from being misreported as independent samples. The scorecard reports directional accuracy, Brier score, log loss, calibration bins, and paired edge versus Kalshi.

Research calibration uses one earliest valid capture per ticker and only labels
observed before that capture. The legacy rolling champion/challenger comparison
is explicitly retrospective and cannot promote parameters; ordinary outcome
learning continues. Horizon promotion requires new graded samples at each
checkpoint. Historical replay shares one validated archive reader, skips missing
exact deadlines, and excludes incomplete higher-frame context and time gaps.
Archived BTC direction results are distinct from official Kalshi settlements.

## Safety boundary

The application remains paper trading only. There are no live exchange order endpoints, no private exchange credentials, and no real-money execution path in this architecture.

The background paper engine appends idempotent lifecycle events and reconciles cash against positions and settlements. A mismatch is surfaced in both the Paper Trading and Kalshi Execution Validation tabs rather than being hidden by a derived UI total.

## Rolling chart curve and display time (2026-10-17)

`forecast_curve.py` builds a separate research forecast of official Kalshi chart
prices at each of the next fifteen minute closes. It uses only valid, contiguous,
completed candles from that source. A regularized direct regression fits each
minute separately; chronological validation refits at each origin using only
labels already complete then. Eight non-overlapping validation paths, aggregate
and recent error improvements over both no-change and the legacy momentum
center are required before the internal method is marked validated. Otherwise
the fitted path is displayed as a model forecast, with experimental status kept
in metadata, or a momentum baseline is shown if it beats flat.
No fitted model means warming up, with no price path. The flat benchmark never
replaces a fitted path with an artificial horizontal line. The error envelope
uses errors from the displayed method. Validation selection is retrospective; prospective
frozen path scores are recorded separately and do not certify a trading edge.

`learner_v31.py` reuses its refreshed `settlement_reference` candles to retain up
to 360 official bars and frozen 15-minute paths in `chart_forecast`. The dashboard
seeds its session from this durable history and recomputes after a new candle
closes. `publish_market_chart_update` sends only the compact fifteen-point curve;
the browser never invents oscillations, attracts prices toward a strike, or cuts
the rolling price path off at the current contract expiry. Stale and wrong-source
curves are hidden. Ranges are empirical price-error envelopes, not future candle
high/low predictions or calibrated probability intervals. Missing observed labels
remain unscored. The curve is independent of the existing execution signal,
settlement model and future-market outlooks; their historical counters are unchanged.

`display_time.py` owns Eastern presentation (`America/New_York`, automatic EST/EDT).
Stored timestamps, feed coordinates, expiry checks and API parameters remain UTC.
Python tables/figures and the persistent browser chart format labels/hover in ET.

## Hourly specialist forecasts and independent learning (2026-10-18)

`hourly_forecast.py` replaces the hourly dashboard's static blend. Each active
specialist projects a BTC target using its signed signal, the existing hourly
move scale and the actual fraction of the hour remaining. The combined target
is the confidence-weighted mean of these targets. Technical signals are reused;
`ai_core.kalshi_context_result` rebuilds Kalshi Context against the selected
hourly contract instead of borrowing the 15-minute strike. Neutral and inactive
bots remain visible but abstain. Combination AI is retained as a diagnostic
summary without a second council vote. Signal confidence is not measured accuracy.

The scheduled `learner_v31.py` runs `update` each cycle, independently of paper
entry approval. It captures the first observed supported strike nearest BTC for
each hourly event, saves each specialist target and YES/NO/HOLD forecast before
expiry, and retains unresolved captures across restarts. Only that contract's
official post-expiry YES/NO result resolves it. Multiple strikes and repeated
refreshes cannot multiply the independent sample count. Greater/less contracts
are supported; unsupported settlement rules do not supply labels. Captures store
compact audit fields and the last 1,000 resolved events; older hourly evidence
is not fabricated from 15-minute records or exchange-price proxies.

Hourly influence uses only previously observed hourly labels for the specialist's
current model version. After 20 directional outcomes, a shrunk hit rate and
frozen leave-one-out contribution adjust its base weight within 0.5–1.5 times
base. Abstentions are excluded from accuracy and training. The scorecard also
retains paired market-midpoint and no-price-change directional comparisons.
The dashboard reads this persistent state and exposes every bot's current target,
call, influence, sample count and measured hourly accuracy. A failed hourly data
refresh is recorded without discarding pending labels or changing the existing
15-minute learning, execution policy or paper ledger. No hourly orders are added,
and neither functional tests nor weight adaptation establish an accuracy gain.
