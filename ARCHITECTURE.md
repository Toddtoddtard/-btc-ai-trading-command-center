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

Paper fees use Decimal arithmetic and Kalshi's signed cash-alignment rules:
model fees round upward to six decimal dollars, then the cash change rounds
downward to the configured balance precision. The explicit paper assumption is
non-direct member cent precision (`PAPER_BALANCE_PRECISION`); the shared helper
also accepts direct-member $0.0001 precision and carries a rounding accumulator
across fills of one order. The current full-fill paper model starts a separate
order for each entry or sale, so it does not share accumulators between trades.
Sale, mark-to-market and projected exits pass the sell action; binary settlement
has no exit fee. New entry and exit fees record their model version; historical
entry fees and closed P/L are not recomputed by this change. Sources and the
read-only retained-ledger comparison are in `docs/KALSHI_FEE_ROUNDING.md`.

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
`decision_snapshot.py` freezes one versioned, timestamped worker decision with a
content-derived ID, ticker/expiry, original LOCK side, latest forecast side,
confidence, probability/source, reference time and current approval/veto. The
worker refreshes actual inputs before each paper pass; retries cannot renew a
cached timestamp. New production fills and SCALP-to-LOCK promotions require a
matching snapshot no more than 30 seconds old, plus all existing fee, depth,
reference, confidence, validation and position checks. Ordinary forecasts become
WAIT in the action snapshot. Automatic scalping is disabled. Filled LOCKs keep
their recorded side and official settlement lifecycle, even when evidence changes.
The dashboard shows the active worker decision, timestamp and action reason.
A fresh same-contract local forecast remains visible as a directional preview
during publication gaps. It carries no LOCK label. The dashboard identifies
stale worker or reference data and keeps the last same-contract decision age.
At rollover the worker can defer a missing old expiry candle and register the
current market. Deferred candle grading retries during full learning passes.
Paper LOCK entry requires validated settlement probability, observed ask depth
and the existing five-point fee-adjusted edge margin at the actual fill size.
Validation uses comparable LOCK fills. Prior outlook-follow fills and SCALPs
remain in total ledger results.
Assessments, signal attempts, fills and lifecycle events retain decision IDs.
Existing ledgers with missing/unsupported versions fail closed; missing old
migration markers never authorize a balance reset or history archival.

The publisher commits the complete JSON checkpoint and deterministic gzip copy
atomically; the legacy repair writer updates both. Public dashboard readers try
gzip first and fall back to JSON on unavailable/corrupt compressed content.
Authenticated/API recovery readers also prefer compressed Contents/blob reads,
with original JSON fallback. Stale decision snapshots can trigger bounded API
recovery before the general learning-health warning; a recent download never
renews a decision timestamp or rolls back a newer cached checkpoint. All
model and ledger history survives compression. Alternate future state writers
must publish both copies in the same commit. On the November 5 retained snapshot,
45.7 MB compressed to 4.2 MB with standard-library gzip (about 91% fewer bytes).
The learner reuses `live_feeds.parallel_calls` for independent startup reads,
trade/futures specialist inputs and the futures primary/fallback requests.
All requests in a batch finish before it returns or raises. Partial futures
failures retain the existing fallback and health semantics; same-contract
quote and reference refresh run concurrently after slow specialist reads,
with the same market identity, expiry and timestamp checks.
After its first validated publication, `worker_session.py` repeats the same
pipeline for a bounded 55-minute session, targeting a 105-second start-to-start cadence
and publishing each validated checkpoint. Publication uses a separate Git
worktree, so runner code remains on its original main revision and unrelated
state files are preserved. Ordinary pushes and bounded rebase retries retain
concurrent unrelated branch updates; conflicting ledger writes fail visibly.
Political Event Watch likewise retries its event-file publication up to three
pushes, rebasing onto newer branch state after a rejected push; a conflicting
event-file edit fails rather than overwriting either writer.
Before a successful main worker finishes, it calls `worker_watchdog.py` with
its own run ID to dispatch one successor directly. The active-run check ignores
only that finishing run and retains any other active or queued learner. Transient
GitHub 500/502/503/504 responses on watchdog reads get at most three attempts
with bounded backoff; dispatch POSTs are never automatically retried because
their outcome may be ambiguous. Existing freshness failures stay visible; workflow
concurrency serializes ledger writers. Main push runs use an 12-minute session
to exercise the first handoff promptly; subsequent workers use 55 minutes.
The five-minute stale-state watchdog remains the recovery backup and checks for
active/queued learners before dispatching. The learner has no unconditional cron
starts. Both the learner and horizon publisher use `queue: max` on the shared
`btc-ai-learning-state` group, so a successor cannot replace a pending model
publication. Historical training runs outside that lock; only publication waits.
GitHub runner startup is still best effort; source timestamps determine freshness,
and a queued successor is never reported as proof of a fresh publication.

The market chart mounts once outside the live fragments. The dashboard's refresh
cadence (one second by default) sends a compact same-origin data packet from a
zero-height Streamlit component into that retained chart. Plotly updates traces
in place, retaining zoom and the selected prediction horizon. The server chart
feed is cached for one second; browser-side Kalshi polling remains a fallback.
The full analysis panel refreshes at most every five seconds. Browser target
lookup skips redundant requests while the server chart packets are current.
The dashboard and worker derive the exact ticker from the active Eastern close
using UTC-aligned 15-minute boundaries. The dashboard market cache rotates with
the ticker, and chart refreshes do not wait for contract order-book depth.
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

`settlement_predictor.py` estimates the exact active KXBTC15M contract: the rounded final 60-second reference average must be at least its target for YES. It uses fresh matching Kalshi event-chart ticks and closed reference candles, accounts for the already observed final-minute prefix, and approximates remaining average uncertainty with arithmetic Brownian motion. Missing prefix seconds, unsupported strike rules, stale data and contract mismatches return unavailable. Timestamped worker and dashboard quotes must be at most 30 seconds old. Legacy observations without quote timestamps remain identifiable; they are not retroactively certified fresh.

`contract_calibration.fit_settlement` independently qualifies that frozen base
estimate in four time-remaining buckets (10+ minutes, 5–10, 1–5, final minute).
Each bucket uses one observation per ticker, at least 100 prior training markets
and 100 chronological validation markets. Promotion requires at least .002
overall Brier improvement over contemporaneous Kalshi prices, no accuracy
regression, and nonnegative recent-100 Brier/accuracy differences. Only outcomes
already observed at prediction time train each validation fit. Dashboard and
worker call the same selector with a fresh matching-contract forecast. An
unqualified settlement model falls back to the existing validated terminal model,
then to the market midpoint with an explicit no-validated-edge execution veto.
No safeguard is bypassed to create paper fills. The base model's separately
fitted shadow residual is never recursively reused as execution training data.

`fit_settlement` also evaluates a bounded three-parameter residual around market
odds with a learned intercept. This challenger must pass the unchanged causal
gates, improve the incumbent overall without recent probability-error harm,
and earn paired improvement against Kalshi over at least 100 newly frozen
official markets in the same time group before selection. Candidate predictions
and training cutoffs are saved before outcomes; `bias_scorecard` never backfills
them. The shared selector applies the intercept for both dashboard and worker.
See `docs/SETTLEMENT_LEARNING_V2.md` for diagnostic results and limitations.

The worker freezes the first published directional decision independently of
the Binance path and council snapshot. Official results score this new field;
legacy path outcomes and paper trade history remain unchanged. Dashboard rolling
decision cards exclude old proxy rows and WAIT/HOLD; BTC movement, Binance
settlement proxy, legacy path-versus-official, and new decision accuracy have
separate keys and sample denominators.

`improvement_evidence.py` compares the production probability, previous execution
formula, Kalshi midpoint and independent model frozen in the same settlement
capture. The existing official resolver and checkpoint selector supply labels;
unknown historical production outputs are never reconstructed as live results.
Each timing row counts one contract once. Accuracy has a Wilson interval;
Brier and accuracy differences use approximate paired intervals. These are
descriptive, assume enough independent markets, and do not account for every
market dependence or repeated comparison. Monitoring never authorizes entries.
At least 100 matched markets are required for an initial classification; a
70% accuracy target needs a lower accuracy bound of at least 70%. Actual tagged
new-version closed paper trades supply P/L separately, including their fees.
Worker checkpoints and captures record the real `GITHUB_SHA`, so a running
workflow or stale deployment caption cannot be mistaken for verified new results.
The settlement headline now uses the same production probability as execution;
the independent model and its archival score remain available as challengers.

Each full worker pass freezes a settlement observation independently of research-phase deduplication and trade approval, preserving WAIT calls, specialist votes, timestamps, target/rule, and unavailable reasons. Only official binary results read after expiry resolve these observations; unresolved labels are retained. The last 3,000 full settled captures supplement the existing research history. Compact official checkpoint records preserve timing, result and frozen probabilities independently of this rolling window. Compatible dashboard builds share a forecast policy identifier, with producing build retained for provenance. Coverage counts elapsed 15-minute windows within the observed policy period. The order-book blend is scored prospectively against both the production forecast and market prices. Earliest-per-contract observations within the same remaining-time group train the bounded ridge residual, but it remains disabled until at least 100 chronological validation markets follow at least 100 training markets and beat both the uncorrected model and Kalshi midpoint by 0.0005 Brier overall, with nonnegative recent paired improvement. Each validation fit uses only outcomes observed before its forecast. No retrospective refitting changes a stored prediction.

The settlement evidence panel shows independent accuracy, Brier, log loss, calibration and the paired market/coin-flip benchmarks. Its 10-, 8-, 5-, 2- and 1-minute checkpoints select the closest capture before each checkpoint within 150 seconds; they never borrow later forecasts. Sampling is limited by worker cadence, not the one-second screen refresh. Coverage describes retained observed markets and unavailable captures, not continuous uptime or unobserved outage windows. The displayed raw estimate does not itself approve execution; the independent execution qualification above is required. Legacy Binance snapshots are not backfilled as official reference features.

The persistent paper reader fetches current public order-book depth. New entries consume no more than the observed selected-side best ask size, with fees recomputed for that size; failed depth or stale quotes block simulated fills. A SCALP exit requires sufficient fresh best-bid size for the full position; otherwise it remains open until another quote or official settlement. This conservative full-fill model does not simulate partial exits, latency or queue priority, and depth availability is not a guarantee of real execution. New positions record `OBSERVED_TOP_OF_BOOK`; injected legacy quote-only snapshots record `LEGACY_QUOTE_ONLY`. Historical ledger results are preserved, not reclassified as depth-validated performance. Contract-versus-market research Brier comparisons use the same subset of markets and display its own sample count and accuracy.

## Kalshi target handling

The current KXBTC15M contract is chosen deterministically and then re-fetched by exact ticker. The target remains pinned to that contract until expiration. The app, chart, decision engine, and learner use the same target semantics.

The main chart and current-price cards use the Kalshi event chart feed. Technical candle/path learning uses Binance closed-minute data and keeps price errors separate from binary correctness. Official Kalshi market `result` values determine contract outcomes and council calibration; see `docs/ACCURACY_LEARNING.md` for the October 12 accounting repair.

## Learning state

GitHub Actions runs `.github/workflows/learn.yml` through main code changes, explicit dispatch and the worker's successor handoff. The five-minute `.github/workflows/health-watchdog.yml` checks freshness and requests recovery only when no learner is active or queued. The worker writes version-31 state to the `learning-state` branch. `.github/workflows/train-horizon-models.yml` retrains horizon candidates weekly. State includes bounded forecast weights, specialist adaptive weights, rolling history, real 15-candle path error, official Kalshi settlement accuracy, horizon-model evidence, and a paper-only research lab.

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

## Settlement-first assessment (r106)

`trade_assessment.assess_paper_entry` is the shared final entry-value assessment
used by the current dashboard ticket and persistent paper worker. It identifies
the exact contract and immutable proposed side, checks contemporaneous quotes
and reference timestamps, requires validated terminal probability and existing
reliability approval, and reports rounded-fee break-even and net edge for the
actual fill size. It adds vetoes; existing depth, size, risk, per-market and
settlement lifecycle rules remain in `background_paper.py`. Historical replay
fixtures retain their legacy schema; every real-clock worker entry uses the new
assessment regardless of schema. A displayed directional outlook never means a
paper position was entered. The worker's ledger remains the action authority.

A terminal probability cannot establish the timing or availability of a SCALP
exit. New automatic SCALP fills therefore wait for a separately validated exit
model. `scalp_exit_research` records one prospective one-contract bid-path episode
per market even when entry is blocked. Entry, positive-after-fees target, stop,
smoothed prior probability and revision freeze before outcomes. It records only
exits actually observed with fresh selected-side bid depth. The official final
result is required separately before scoring; windows without an observed exit
are explicitly censored. This is sampled-path research, not continuous-tick
replay, real execution or an eligible strategy promotion. It has no execution
or promotion authority; activation requires additional paired policy evidence
and all previously specified promotion gates. Existing SCALPs remain managed;
profit-taking requires positive actual net proceeds after both fees, while
reversal and stop exits remain available. New-schema calls cannot prolong an
old SCALP on terminal-probability upside alone.

`cutoff_research` compares current LOCK eligibility with a bounded subset of
PR #63 using the same fresh worker depth observation and validated probability.
Each ticker freezes both hypothetical policies, depth/budget-limited quantity,
rounded fees and producing revision once. Its separate research state resolves
only against that ticker's official settlement, with at most three label reads
per cycle. The dashboard reports revision-specific matched markets, blockers,
additional entries, scenario P/L, calibration and uncertainty. These are snapshot
scenarios, not ledger trades or portfolio replay; current reliability approval,
target/data checks and quarantine remain. It cannot change execution or promote
a strategy. Existing SCALP bid-path research stays separate.

The council retains every specialist and all existing contribution evidence
requirements. The confidence corroboration bonus now caps duplicate price-trend
and price-momentum families rather than counting them as independent voters.
Scores/weights are retained. `confidence_policy=evidence-families-v1` tags new
snapshots; changed-formula confidence corrections cannot borrow old validation
samples. This is a conservative confidence safeguard, not a promoted strategy.
Failed futures snapshots explicitly abstain, including when a failed primary
read leaves partial values. Existing free primary/fallback sources remain.

`decision_dashboard.py` distinguishes settlement outlook, actual worker paper
action, current fee-aware preview, probability source and input availability.
Signal strength is explicitly heuristic. Old labels, ledgers, official outcomes,
archives and rare-specialist learning remain intact.

Current-schema decisions cannot open positions through the legacy SQLite adapter; its simulations remain available, but the persistent background ledger is the only current execution path.


## Baseline integrity and bounded depth (r107)

Terminal calibration receives the exact observed market probability, including
sub-cent tail quotes; numerical logit clipping never changes the baseline.
App/learner/background order-book requests explicitly ask for depth5, matching
the feature extractor. App and background use four-second per-read budgets and
recover from empty books through the existing backup; learner retains its
existing timeout. This is bounded REST sampling, not continuous tick coverage.
SCALP research can observe LOCK or SCALP outlooks independently of paper approval;
source action is retained, and missing depth is exposed instead of silent zeros.

`settlement_benchmark.py` provides a reproducible read-only chronological test
with a common reserved-contract set across horizons. It never supplies execution
coefficients, publishes no live win-rate claim and has no promotion authority.
The October31 selected candidate failed its reserved Brier comparison and was
not deployed. See `docs/prediction-repair-2026-10-31.md` for exact scope/results.



### Mobile startup and technical summary cards
The main entrypoint renders owner approval before importing/reloading the trading
stack. An unauthenticated visit therefore does not initialize the council, chart
or learning modules. Approved sessions keep the existing dependency-ordered
reloads and decision flow. The Market tab's four FVG/MACD summary cards use
escaped responsive HTML through dashboard_ui.metric_cards_html, avoiding the
lazy metric component that failed in the user's iPhone screenshot. All indicator
calculations and chart data remain unchanged. This does not repair unrelated
Streamlit asset/network failures or establish an authenticated mobile load time.
The MACD history and prediction-horizon selectors use dropdowns rather than
select sliders after the two slider positions also displayed module-import
errors on iPhone. Choices and defaults remain 30/60/120/180 minutes (180) and
1/5/15 minutes (15). These controls only select chart presentation horizons.

### Calm dashboard presentation
The persistent chart's Eastern tick labels follow Plotly's retained zoom range
on each live update. Compact phone labels omit the timezone suffix; full hover
timestamps and the Time (ET) axis title identify the timezone. Coordinates remain
UTC. Browser checks verify the tick budget and labels across live updates.

`dashboard_ui.dashboard_theme_css` owns the dark/light shell palette. It replaces
two overlapping theme blocks with charcoal surfaces, muted directional accents,
subtle card borders, visible keyboard focus, and two-column mobile metric groups.
Warning/error messages retain distinct severity borders and readable text.
The paper preview uses four compact HTML cards; its full blocker list, futures
availability and explanatory notes remain under Contract details and entry checks.
Open-position status and stale-worker warnings stay visible outside that expander.
Forecast research details share one collapsed section; request latency appears
only when Show diagnostics is enabled. No forecasting, paper-entry, settlement,
worker, ledger or specialist rules change in this presentation update.
