# Code map and focused maintenance

Start here for a specific issue. This is a navigation guide, not a current health or accuracy report.

| Area | Start with | Relevant checks |
| --- | --- | --- |
| Current BTC price, active target, main chart | `kalshi_chart_data.py`; `app.py`: `stable_kalshi_contract`, `refresh_market_chart`, `publish_market_chart_update`, `persistent_kalshi_market_chart`, `live_dashboard` | `test_kalshi_chart_data`, `test_chart_target`, `test_dashboard_freshness`, `test_smooth_chart`; `scripts/check_smooth_chart.py` |
| Stale learning or paper figures | `shared_learning.py`; `app.py`: `refresh_learning_summary` | `test_shared_learning`, `test_dashboard_freshness` |
| Specialist votes, council weights, abstentions | `council_v4.py`, `contribution_evidence.py`, `specialist_knowledge_v5.py`, `ai_core.py`, `reliability_v31.py`; `docs/COUNCIL_REVIEW.md` | `test_council_v4`, `test_council_parity`, `test_council_evidence`, `test_official_calibration` |
| Official outcome labels and calibration | `council_accounting.py`, `outcome_timing.py`, `contract_calibration.py`, `contract_probability.py`; `docs/ACCURACY_LEARNING.md` | `test_official_calibration`, `test_council_evidence`, `test_contract_probability` |
| Exact 15-minute YES/NO settlement challenger | `settlement_predictor.py`: independent worker captures, official resolution, correction validation and timing scorecards; `kalshi_chart_data.py`; evidence UI in `research_dashboard.py` and `app.py` | `test_settlement_predictor`, `test_settlement_evidence`, `test_kalshi_chart_data` |
| LOCK/SCALP qualification | `lock_focus.py`, `pro_trade_ticket.py`; app/learner callers | `test_lock_focus`, `test_entry_caps`, `test_contract_regressions` |
| Persistent paper balance, positions, settlements | `background_paper.py`: live depth reads and fill-size checks; shared helpers in `kalshi_paper_engine.py`; `app.py` consumes `shared_paper_summary` | `test_background_paper`, `test_paper_liquidity`, `test_paper_recovery`, `test_state_preservation` |
| Journal correctness and resolved counts | `prediction_journal.py`, `council_accounting.py` | `test_persistent_journal`, `test_journal_integration` |
| Rolling chart curve and prospective path evidence | `forecast_curve.py`; `learner_v31.py`: `current_shadow_call` / worker reference reuse; `app.py`: `refresh_market_chart`, `predictedCandles` | `test_forecast_curve`, `test_chart_curve_integration`, `test_chart_execution`, `test_smooth_chart` |
| Eastern display, tables, chart ticks and hover | `display_time.py`; `app.py` browser `easternTime` / `easternAxis`; `dashboard_ui.py`, `research_dashboard.py`, `multi_asset_command_center.py` | `test_display_time`, `test_smooth_chart` |
| Closed-candle catch-up and predicted paths | `candle_learning.py`, `learning_prices.py`, `horizon_models.py`, `ai_core.py` | `test_candle_learning`, `test_learning_prices`, `test_prediction_horizon_v17` |
| MACD and chart presentation | `macd_engine.py`, `technical_fvg_macd.py`, `dashboard_ui.py`; app render functions | `test_macd_v2`, `test_dashboard_ui`, `test_chart_execution` |
| Live technical feeds and latency | `live_feeds.py`, `public_futures.py`, `kalshi_reference.py`, `kalshi_microstructure.py` | `test_live_feeds`, `test_futures_latency`, `test_kalshi_reference` |
| Dashboard loading and payload size | `app.py`: `chart_json`, `live_dashboard`; `live_feeds.py`: `load_chart_startup`; `shared_learning.py`: serialized cache refresh; `worker_session.py`: compact full-state publication | `test_dashboard_performance`, `test_shared_learning`, `test_worker_session`, `test_smooth_chart` |
| Worker schedule, publication and recovery | `.github/workflows/learn.yml` runs `learner_v31.py`, enrichment and `background_paper.py`; `worker_session.py` publishes; final `worker_watchdog.py` pass queues a successor directly | `test_worker_session`, `test_worker_watchdog`, `test_learning_gaps` |
| Other market pages | `pages/`, `multi_asset_command_center.py`, `multi_asset_paper.py` | `test_multi_asset_paper`, `test_multi_market_nav_routes` |
| Login and deployed build label | `access_control.py` | `test_access_control` |
| Archive replay, label deadlines, training inputs | Shared `historical_backtest.py` archive reader; `council_backtest_v4.py`, `historical_specialist_backtest_v7.py`, `train_horizon_models.py` | `test_historical_deadlines`, `test_historical_cross_month_v16`, `test_council_backtest_v4`, `test_train_horizon_models` |
| LOCK fee economics and fresh execution evidence | `kalshi_paper_engine.py`: `expected_lock_net_pnl`; `learner_v31.py`: `refresh_pending_lock_focus`; `background_paper.py`; `pro_trade_ticket.py` | `test_lock_expected_return`, `test_reliability_v31`, `test_pro_trade_ticket` |

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
- Active scheduled entrypoint: `learner_v31.py`, which imports `learner.py` and `learner_v3.py` for supporting functionality. Cron requests are best effort; verify actual snapshot and paper-cycle ages.
- Older patch installers under `tools/` are not the main runtime. Some are still invoked by workflows, so verify references before touching them.
- `tools/run_offline_tests.py` executes both `unittest.TestCase` methods and standalone `test_*` functions with sockets disabled. Bare unittest discovery does not include the latter.
- `WORK_CONTEXT.md` is the dated handoff log. `ARCHITECTURE.md` explains component relationships. Avoid duplicating numeric strategy settings here; inspect the current constants and explicit user instructions.
