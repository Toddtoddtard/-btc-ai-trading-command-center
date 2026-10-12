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

`contract_probability.py` converts the settlement question into a calibrated binary probability using strike distance measured in remaining-window volatility, the council score, and weighted order-book pressure. Kalshi's midpoint remains the dominant anchor until independent walk-forward evidence proves incremental Brier value.

## Kalshi target handling

The current KXBTC15M contract is chosen deterministically and then re-fetched by exact ticker. The target remains pinned to that contract until expiration. The app, chart, decision engine, and learner use the same target semantics.

The main chart and current-price cards use the Kalshi event chart feed. Technical candle/path learning uses Binance closed-minute data and keeps price errors separate from binary correctness. Official Kalshi market `result` values determine contract outcomes and council calibration; see `docs/ACCURACY_LEARNING.md` for the October 12 accounting repair.

## Learning state

GitHub Actions runs `.github/workflows/learn.yml` every five minutes. The worker writes version-31 state to the `learning-state` branch. `.github/workflows/train-horizon-models.yml` retrains horizon candidates weekly. State includes bounded forecast weights, specialist adaptive weights, rolling history, real 15-candle path error, official Kalshi settlement accuracy, horizon-model evidence, and a paper-only research lab.

The research lab can record one independent shadow call in each `OPEN`, `MIDDLE`, `FINAL 5`, and `FINAL 2` phase. It grades model Brier score against the contemporaneous Kalshi midpoint, counterfactual WAIT outcomes, fee-aware one-contract paper P/L, and simultaneous entry-policy candidates. Specialist lifecycle labels are advisory and never disable execution.

Evaluation also publishes an independent-market scorecard that retains only the earliest forecast per ticker. This prevents multiple refreshes or phase observations from being misreported as independent samples. The scorecard reports directional accuracy, Brier score, log loss, calibration bins, and paired edge versus Kalshi.

## Safety boundary

The application remains paper trading only. There are no live exchange order endpoints, no private exchange credentials, and no real-money execution path in this architecture.

The background paper engine appends idempotent lifecycle events and reconciles cash against positions and settlements. A mismatch is surfaced in both the Paper Trading and Kalshi Execution Validation tabs rather than being hidden by a derived UI total.
