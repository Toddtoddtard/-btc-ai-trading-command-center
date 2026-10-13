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

New LOCK entries require validated terminal probability and positive expected
settlement proceeds after entry fees. Council confidence is a separate measure
and cannot substitute for contract probability. An immutable LOCK direction
does not freeze authorization: current probability and reliability evidence
must still approve an unfilled call. Promotion of existing SCALP exposure also
requires current approval and a validated advantage to holding versus selling.

The active scheduled entrypoint is `learner_v31.py`, supported by `learner.py`
and `learner_v3.py`. `.github/workflows/learn.yml` runs learning, enrichment and
`background_paper.py`, then publishes the persistent ledger and model state to
`learning-state`. The dashboard reads that state through `shared_learning.py`.
Scheduled requests are every five minutes, but actual GitHub execution is best
effort; source timestamps determine whether a displayed snapshot is current.


## Shared-model guarantee

`app.py` and the learner stack reuse specialist and forecast implementations from `ai_core.py`. Shared formulas reduce drift, but input sources and eligibility paths still need parity checks; reuse alone does not prove identical decisions.

Independent horizon models live in `horizon_models.py`. Their 21-feature schema combines 14 short-horizon features with seven scale-normalized higher-timeframe returns. `multi_timeframe.py` rejects the currently forming candle; historical training reconstructs the same features only after each bar's close boundary. Predictions are persisted before their labels exist, graded in timestamp order, and updated only after grading. Offline candidates use chronological train/calibration/untouched-test partitions. They must pass historical validation plus repeated live Brier-score gates before a bounded 25% blend can influence the forecast. Until then they are diagnostic shadow models.

Kalshi depth is read from the unauthenticated public order-book endpoint. `kalshi_microstructure.py` reconstructs asks from the opposite bid side and exposes midpoint, spread, depth imbalance, and microprice. No credentials or order endpoints are present.

## Specialist council

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

`settlement_predictor.py` is a separate shadow challenger for the exact active KXBTC15M contract: the rounded final 60-second reference average must be at least its target for YES. It uses fresh matching Kalshi event-chart ticks and closed reference candles, accounts for the already observed final-minute prefix, and approximates remaining average uncertainty with arithmetic Brownian motion. Missing prefix seconds, unsupported strike rules, stale data and contract mismatches return unavailable. The worker freezes its probability/features into existing research observations; only official results with an observed timestamp can train a bounded ridge residual after 100 distinct markets. Stored forecasts supply an independent earliest-per-market accuracy/Brier/calibration scorecard. This experimental model never changes paper execution approval. Legacy Binance snapshots are not backfilled as official reference features, and the new predictor has no historical performance claim.

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
