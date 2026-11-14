# Code map and focused maintenance

Start here for a specific issue. This is a navigation guide, not a current health or accuracy report.

| Area | Start with | Relevant checks |
| --- | --- | --- |
| Current BTC price, active target, main chart | `kalshi_chart_data.py`: active boundary and ticker; `learner.py`: exact market first; `app.py`: boundary-keyed market cache, `stable_kalshi_contract`, `refresh_market_chart`, `publish_market_chart_update`, `persistent_kalshi_market_chart` / browser `easternAxis` retained-range ticks, `live_dashboard` | `test_kalshi_chart_data`, `test_chart_target`, `test_dashboard_freshness`, `test_smooth_chart`, `test_display_time`; `scripts/check_smooth_chart.py` |
| Stale learning or paper figures | `shared_learning.py`; `app.py`: `refresh_learning_summary` | `test_shared_learning`, `test_dashboard_freshness` |
| Specialist votes, council weights, abstentions | `council_v4.py`, `contribution_evidence.py`, `specialist_knowledge_v5.py`, `ai_core.py`, `reliability_v31.py`; `bot_intelligence_dashboard.py`: regime ablation; `docs/COUNCIL_REVIEW.md` | `test_council_v4`, `test_council_parity`, `test_council_evidence`, `test_official_calibration` |
| Official outcome labels and calibration | `council_accounting.py`, `outcome_timing.py`, `council_confidence.py`, `contract_calibration.py`, `contract_probability.py`; `docs/ACCURACY_LEARNING.md` | `test_council_confidence`, `test_official_calibration`, `test_council_evidence`, `test_contract_probability` |
| Read-only model comparison and reserved chronological contracts | `settlement_benchmark.py`; `docs/prediction-repair-2026-10-31.md` | `test_settlement_benchmark`, `test_bounded_depth`, `test_contract_probability` |
| Measured improvement and deployed worker identity | `improvement_evidence.py`: persistent policy-keyed official checkpoints, coverage, paired live and shadow benchmarks; `settlement_predictor.py`: captures/resolution; `learner_v31.py`: code revision; `research_dashboard.py`: comparison panel; `docs/IMPROVEMENT_EVIDENCE_PLAN.md` | `test_improvement_evidence`, `test_settlement_execution`, `test_settlement_evidence` |
| Hourly specialist targets, learned influence and official outcomes | `hourly_forecast.py`: `predict`, `capture`, `resolve`, `update`; `learner_v31.py`: hourly worker capture; `app.py`: `hourly_kalshi_target_ai`; `ai_core.py`: shared `kalshi_context_result` | `test_hourly_forecast`, `test_official_calibration`, `test_worker_session` |
| Exact 15-minute YES/NO settlement and execution qualification | `settlement_predictor.py`: horizon-specific correction, immutable bias candidate captures and `bias_scorecard`; `contract_calibration.py`: incumbent/challenger `fit_settlement` and shared `apply`; `docs/SETTLEMENT_LEARNING_V2.md`; `learner.py` / `learner_v31.py`: frozen official decision scoring; `app.py`: shared selector | `test_settlement_learning`, `test_settlement_execution`, `test_settlement_predictor`, `test_settlement_evidence`, `test_kalshi_chart_data` |
| Live Outlook and persistent paper entry | `decision_snapshot.py`: versioned worker decision, freshness and paper dashboard overlay; `learner_v31.py`: fresh observation and deferred expiry-candle grading at rollover; `improvement_evidence.py`: labeled live preview when the worker forecast is unavailable; `background_paper.py`: fill provenance; `trade_assessment.py`; `decision_dashboard.py`: shared Live Outlook with directional preview and paper status | `test_decision_snapshot`, `test_trade_assessment`, `test_assessment_integration`, `test_decision_dashboard` |
| Corroboration families and failed futures abstention | `council_v4.py`, `council_confidence.py`, `ai_core.py` | `test_council_diversity`, `test_input_availability` |
| LOCK/SCALP qualification | `lock_focus.py`, `pro_trade_ticket.py`; app/learner callers | `test_lock_focus`, `test_entry_caps`, `test_contract_regressions` |
| Persistent paper balance, positions, settlements | `background_paper.py`: live depth reads, backup-host recovery and fill-size checks; shared helpers in `kalshi_paper_engine.py`; `app.py` consumes `shared_paper_summary` | `test_background_paper`, `test_paper_liquidity`, `test_paper_recovery`, `test_state_preservation` |
| Journal correctness and resolved counts | `prediction_journal.py`, `council_accounting.py` | `test_persistent_journal`, `test_journal_integration` |
| Rolling chart curve and prospective path evidence | `forecast_curve.py`; `learner_v31.py`: `current_shadow_call` / worker reference reuse; `app.py`: `refresh_market_chart`, `predictedCandles` | `test_forecast_curve`, `test_chart_curve_integration`, `test_chart_execution`, `test_smooth_chart` |
| Eastern display, tables, chart ticks and hover | `display_time.py`; `app.py` browser `easternTime` / `easternAxis`; `dashboard_ui.py` shared dark/light theme and responsive cards; `decision_dashboard.py` compact preview with complete expandable checks; `research_dashboard.py`, `multi_asset_command_center.py` | `test_display_time`, `test_smooth_chart`, `test_dashboard_ui`, `test_dashboard_warm_reload`, `test_decision_dashboard` |
| Closed-candle catch-up and predicted paths | `candle_learning.py`, `learning_prices.py`, `horizon_models.py`, `ai_core.py` | `test_candle_learning`, `test_learning_prices`, `test_prediction_horizon_v17` |
| Liquidity sweeps and named signal education | `candle_learning.py`: `liquidity_sweep_flags`; `ai_core.py`: Pattern AI; `signal_education.py`; versioned evidence in `council_accounting.py` / `council_v4.py` | `test_liquidity_sweeps`, `test_signal_education`, `test_pattern_structure` |
| MACD and chart presentation | `macd_engine.py`, `technical_fvg_macd.py`, `dashboard_ui.py`: escaped HTML technical metric cards; app render functions and MACD dropdowns | `test_macd_v2`, `test_macd_controls`, `test_dashboard_ui`, `test_dashboard_warm_reload`, `test_chart_execution` |
| Live technical feeds and latency | `live_feeds.py`, `public_futures.py`, `kalshi_reference.py`, `kalshi_microstructure.py`; `learner.py`: concurrent futures and registration inputs; `learner_v31.py`: concurrent startup and specialist inputs | `test_live_feeds`, `test_futures_latency`, `test_learner_feed_latency`, `test_kalshi_reference` |
| Dashboard loading and payload size | `app.py`: `chart_json`, `live_dashboard`; `live_feeds.py`: `load_chart_startup`; `shared_learning.py`: compressed full checkpoint with JSON fallback for public and authenticated/API reads; decision-age-aware bounded CDN recovery; `worker_session.py`: atomic JSON/gzip publication; legacy repair writer updates both | `test_dashboard_performance`, `test_shared_learning`, `test_worker_session`, `test_smooth_chart` |
| Worker schedule, publication and recovery | `.github/workflows/learn.yml` runs `learner_v31.py`, enrichment and `background_paper.py`; `worker_session.py` publishes; final `worker_watchdog.py` pass queues a successor with bounded transient-GET retries; `.github/workflows/health-watchdog.yml` supplies guarded five-minute recovery; learner and horizon publication share a non-replacing queue; `.github/workflows/political-event-watch.yml` retries unrelated state-branch push races | `test_worker_session`, `test_worker_watchdog`, `test_learning_gaps`, `test_event_publication` |
| Other market pages | `pages/`, `multi_asset_command_center.py`, `multi_asset_paper.py` | `test_multi_asset_paper`, `test_multi_market_nav_routes` |
| Login and deployed build label | `app.py` gates before trading imports/reloads; `access_control.py` | `test_access_control` |
| Archive replay, label deadlines, training inputs | Shared `historical_backtest.py` archive reader; `council_backtest_v4.py`, `historical_specialist_backtest_v7.py`, `train_horizon_models.py` | `test_historical_deadlines`, `test_historical_cross_month_v16`, `test_council_backtest_v4`, `test_train_horizon_models` |
| LOCK fee economics, net-edge margin and validation quarantine | `kalshi_paper_engine.py`: `expected_lock_net_pnl`, `lock_edge_is_sufficient`, `lock_validation_policy`; `background_paper.py`: authoritative distinct-market gate and promotion checks; `pro_trade_ticket.py`; `learner_v31.py`: exact-event Kalshi reference | `test_lock_expected_return`, `test_reliability_v31`, `test_pro_trade_ticket` |
| PR #63 bounded cutoff comparison | `cutoff_research.py`: immutable depth-sized paired LOCK scenarios; `background_paper.py`: research observation only; `research_dashboard.py`; `docs/PR63_SHADOW_COMPARISON.md` | `test_cutoff_research` |
| Fee rounding and signed paper cash movements | `kalshi_paper_engine.py`: `kalshi_fill_fees`, `kalshi_taker_fee`; sell callers in `background_paper.py`, `pro_trade_ticket.py`, `scalp_exit_research.py`; `docs/KALSHI_FEE_ROUNDING.md` | `test_kalshi_fee_rounding`, `test_background_paper`, `test_contract_regressions` |

## Source navigation without rereading whole files

```bash
python tools/code_map.py shared_learning.py
python tools/code_map.py app.py --symbol refresh_market_chart
python tools/code_map.py council_v4.py --symbol analyze_bot_contributions
rg -n 'shared_paper_summary|evaluate_lock_focus' app.py background_paper.py learner_v31.py
python -m unittest discover -s tests -p 'test_shared_learning.py' -v
```

The local command uses Python's standard-library AST parser. It reads source without importing or executing app code, prints matching top-level definitions with line ranges, and lists direct local imports/importers. It rebuilds this information in memory on demand. It has no model calls, installation step, credentials, saved graph or network access. Output is bounded with `--limit` (default 30).

This is a small project-specific navigation tool, not Graphify. Static imports are a starting point, not a complete runtime call graph: dynamic imports, injected callbacks, workflows, string-based test references and embedded JavaScript still require targeted inspection. Test names in the table live under `tests/`; they are suggestions, not exhaustive dependency coverage.

## Operational facts to keep separate

- Main chart/current-price cards use Kalshi's public event chart. Technical candles and order flow use Binance; worker price proxies are identified separately from official settlement outcomes.
- The displayed authoritative paper ledger comes from `learning-state` / `background_paper`. The SQLite engine also supplies shared lifecycle, fee and strategy helpers; do not substitute its local totals for the persistent summary.
- `cutoff_research` stores hypothetical cutoff-policy comparisons separately from that ledger. Its first same-contract depth observation freezes both policies; only official settlement resolves them. It has no execution or model-promotion authority.
- Active scheduled entrypoint: `learner_v31.py`, which imports `learner.py` and `learner_v3.py` for supporting functionality. Cron requests are best effort; verify actual snapshot and paper-cycle ages.
- Older patch installers under `tools/` are not the main runtime. Some are still invoked by workflows, so verify references before touching them.
- `tools/run_offline_tests.py` executes both `unittest.TestCase` methods and standalone `test_*` functions with sockets disabled. Bare unittest discovery does not include the latter.
- `WORK_CONTEXT.md` is the dated handoff log. `ARCHITECTURE.md` explains component relationships. Avoid duplicating numeric strategy settings here; inspect the current constants and explicit user instructions.

