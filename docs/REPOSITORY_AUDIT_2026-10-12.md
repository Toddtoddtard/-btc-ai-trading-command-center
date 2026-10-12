# Repository audit and repairs — October 12, 2026

Base: `9296ec2` (main, through merged PR #75). Branch:
`audit/repository-reliability-2026-10-12`. Intended deployed build: r98.
This is an audit pass and implemented repair set, not a certification that the
project is flawless or profitable. The PR and final delivery record supply the
hosted CI, merge, and deployment status.

## Scope and evidence

Read AGENTS.md, CODE_MAP.md and current architecture before editing. Checked
merged PRs #68–75 and matched Graphify's index to the source commit. Surveyed
the complete 212-file tree (158 Python files, about 29,800 lines), imports,
runtime entrypoints, workflows, dependencies and tests. Deep checks followed
the affected workflows; this does not claim a manual line-by-line review of
every historical installer. No paid dependency, hosting service or real order
endpoint was introduced. Authentication, 16 specialists, all market pages,
paper ledger history, one-way LOCK behavior and configured price caps remain.

| Area reviewed | Owning files and verification scope |
| --- | --- |
| Specialists/indicators/council | ai_core, MACD/FVG, council_v4, reliability_v31, specialist_knowledge_v5, contribution_evidence; indicator and council regressions |
| Official labels/calibration | council_accounting, outcome_timing, contract_calibration, contract_probability, research_lab; capture/observation chronology and same-market exclusion |
| Learning/training/predicted paths | learner stack, candle_learning, horizon_models, train_horizon_models, multi_timeframe, forward_outlook; input validity, deadlines, model promotion, saved state |
| Historical evaluation | historical_backtest, historical_specialist_backtest_v7, council_backtest_v4; gated ablation, exact labels, gaps, shared archive parsing |
| Paper execution/accounting | background_paper, kalshi_paper_engine, pro_trade_ticket, prediction_journal, profitability helpers; fees, quote/expiry guards, immutable LOCK, original forecast labels |
| Feeds/chart/UI | live_feeds, public_futures, kalshi_microstructure, kalshi_reference, kalshi_chart_data, app/shared_learning/dashboard modules; source parser, freshness, chart JavaScript, deployed access screen |
| Workers/recovery/integrations | learn/train/watchdog workflows, worker_watchdog, enrichment and checkpoint helpers, multi-asset pages/paper modules; entrypoints, persistence and failure handling |
| Complexity/dependencies | Entire tree/import references; redundant archive parsers and unused page shell; preserve invoked installers and current free providers |

## Confirmed problems and implemented corrections

| Problem/root cause | Correction and affected production files |
| --- | --- |
| RSI divides by a missing denominator when average losses are zero, neutralizing a rising market | Conventional rising 100/falling 0/flat 50 boundaries, retaining first-row warmup; ai_core.py |
| Research calibration uses insertion order and ignores outcome observation time | Chronological earliest capture per ticker; train only from available official labels at each capture; research_lab.py |
| Repeated research phases inflate activation samples | One independent market per training/validation sample; phase/policy observations remain separate; research_lab.py |
| Malformed OHLC, volume and persisted features can poison horizon model weights | Reject nonfinite/nonpositive inputs and malformed pending evidence without compressing candle time; horizon_models.py |
| Pending storage order changes horizon SGD updates | Deterministic deadline ordering within each resolved batch; horizon_models.py |
| Rechecking identical sample counts advances promotion streak | Require newly graded evidence; candidate replacement resets checkpoint; horizon_models.py |
| Learned configurations are retrospectively fitted/evaluated and can auto-promote from reused rolling candles | Mark rolling challenger replay shadow-only and prohibit promotion until an untouched prospective comparison exists; learner_v31.py |
| Missing market/terminal probabilities default to zero, implying certain DOWN | Preserve unavailable probability, edge and target values; learner.py, learner_v31.py |
| Network work can create a shadow call after expiry | Validate deadline before and after fetches; learner_v31.py |
| Existing LOCK freezes old probability/approval and can fill after a fresh veto | Preserve locked direction/geometry while refreshing execution evidence; require matching fresh LOCK qualification for new fills; learner_v31.py |
| Orderbook guessing converts legacy 1 cent to $1 and invalid dollar levels into cents | Units follow dollars-field versus legacy-field schema; empty fixed-point sides remain empty; kalshi_microstructure.py |
| Learner legacy quotes yield a fabricated 50% midpoint; exact ticker mismatch is accepted | Derive midpoint from parsed bid/ask, reject mismatched or expired/closed exact market; learner.py |
| LOCK entries have no fee-aware expected settlement-return check | Shared validated-probability economics and valid noncrossed quote guards in both engines; kalshi_paper_engine.py, background_paper.py |
| SQLite can fill after expiry during allocation/database work; explicit reliability veto is ignored | Final pre-debit deadline check and explicit veto guard; kalshi_paper_engine.py |
| Vetoed or unvalidated call can promote SCALP to LOCK, removing reversal/stop behavior | Current approval plus validated hold-versus-liquidation economics; background_paper.py/shared helpers |
| Ticket can advertise READY for entries execution rejects | Share quote/economic helpers, report confidence/reliability, deadline and fee/projection blockers; pro_trade_ticket.py |
| Winning executed paper side relabels an opposite original forecast and inflates rewards/hits | Official result scores original persisted settlement direction; unknown direction stays unknown; proxy reward/hit counters remain untouched; background_paper.py |
| Historical council ablation ignores WAIT and reconstructs other votes at arbitrary confidence | Preserve original specialist metadata, apply full/without council gates, call-only accuracy and paired decision utility; council_backtest_v4.py |
| Missing archive deadline uses a later price; time gaps contaminate warmup/lag features | Exact deadline only, reset/require contiguous history and timestamp-based sample eligibility; all three replays, train_horizon_models.py |
| Offline constant-volume feature differs from live feature; partially populated higher-frame bars are treated as complete | Neutral constant-volume value and complete-bar context requirement; train_horizon_models.py |
| Streamlit module cache can retain changed AI/research/horizon code | Refresh changed stateless modules before importing exports; app.py; r98 build label in access_control.py |
| Offline gate silently ignores 15 standalone tests | Include FunctionTestCase discovery; correct one newly exposed stale assertion to current weighted council consensus; tools/run_offline_tests.py |

Every behavioral repair has a reproduction that failed before its correction.
Focused checks precede the broad offline gate. UI appearance is retained.

## Simplification and efficiency

Deleted the unused 154-line market_command_center_shell.py after whole-tree
reference search confirmed active pages use multi_asset_command_center instead.
The council and specialist archive replays now reuse historical_backtest's
month iteration, URL and validated ZIP/CSV parser. This removes duplicated
network/parsing logic and gives all archive consumers the same validation.
Shared execution economics avoid independently reinvented LOCK calculations.
No dependency was added or removed; all four existing app dependencies remain.
Final production Python diff is 383 added / 394 removed lines (net 11 fewer),
excluding tests and documentation. New regression coverage accounts for much
of the total PR growth; useful functionality was not removed to shrink it.

Correct chronological research fitting costs more CPU: on the same 1,000-row
retained input, three-run median was 41.17 ms before and 54.06 ms after. This is
a roughly 13 ms correctness cost, not a claimed latency improvement. No live
API latency, memory reduction or dashboard throughput improvement was measured.

## Honest retained-data evaluation

Source state commit: `8560609317f32ace1cc63718fd7d21ac5c1319ed`;
learning snapshot 2026-10-12 18:11:43 UTC, paper cycle 18:13:29 UTC.
Reproducible numeric evidence is in audit-evidence-2026-10-12.json. These are
historical measurements from that checkpoint, not post-deployment outcomes.

| Measurement | Result and meaning |
| --- | --- |
| Raw terminal blend, 865 independent official markets | 76.18% directional accuracy; Brier 0.15774 |
| Contemporaneous Kalshi midpoint, same 865 markets | 78.03% accuracy; Brier 0.15300; baseline beats raw blend |
| Chronological terminal correction, 765 validation markets | 78.04% candidate versus 78.17% midpoint; Brier 0.15360 versus 0.15294; correction remains inactive |
| Repaired research correction, 838 causal validation markets | Brier 0.15280 versus midpoint 0.15142; correction remains inactive |
| Research sample-accounting change on identical input | Training 1,000 phase rows becomes 898 markets; validation 940 phase rows becomes 838 causal markets. Changed denominators are not predictive gains |
| Recorded directional-call journal | 39 resolved calls; 61.54% accuracy. Total retained rows 1,041 includes legacy forecasts; this is not execution win rate or complete coverage |
| Authoritative closed paper ledger | 95 trades; 61 wins/34 losses; 64.21% win rate; $15.583 net simulated P/L; $515.583 equity from $500 |
| Paper fees / drawdown / profit factor | $24.69 fees; 9.26% recorded maximum drawdown; 1.056 profit factor |

WAIT/HOLD remains outside directional accuracy. Different evaluation scopes and
targets above must not be combined. No improvement in future accuracy or
profitability is established by fixing bookkeeping or passing tests.

An inactive terminal correction falls back to midpoint. Buying at an ask above
that midpoint plus fees has no validated positive expected return. Consequently
the new LOCK economics guard can block new entries until independent evidence
supports an edge. The Master can still publish its call; the bot must not force
trades to produce activity. Existing LOCK positions retain their strategy.

## Verification and remaining limitations

Baseline offline suite: 298 tests, no failures, one Streamlit dependency skip.
Final local offline gate: 369 tests in 3.40 seconds, 368 passed and one skipped
because local Streamlit is absent. Hosted CI installs the app dependencies and
must exercise the startup test before merge. Python compilation, whitespace,
chart JavaScript and focused integration checks passed. Deliberate malformed
optional-state recovery and tiny replay publication-minimum fixtures print
diagnostics; these are successful failure-handling tests, not ignored errors.

Live browser inspection reached Private Access and observed r97 before merge.
Authentication is retained; charts, current target, countdown, journals and
signed-in dashboard are not end-to-end verified behind that gate. GitHub
publication and observed deployed build are reported separately from tests.
Direct public-feed verification succeeded at 19:21:15 UTC for
KXBTC15M-26OCT121530-30: target $82,276.26, YES 0.78/0.79, official event chart
price $82,325.30 with source age about 1.9 seconds. This verifies the public
parser/pipeline observation, not the authenticated dashboard. Public series
metadata reported quadratic fees with multiplier 1; simulated fees remain
estimates, not recorded venue fills.

- No new 5–10-year download was run. Existing archive summaries do not contain
  historical Kalshi reference ticks, executable books, fills or complete original
  Master decisions; they cannot prove an improved strategy's fee-aware P/L.
- No new predictor was promoted: retained chronological evidence did not beat
  midpoint. Forecast and specialist learning continue; model candidates stay
  behind their existing validation requirements.
- Older proxy rewards/counters already rewritten without original values cannot
  be reconstructed honestly. Future paper outcomes no longer contaminate them.
- Legacy settlement poll times remain an explicit 120-second assumption when
  absent. Retained 500-snapshot/1,000-shadow limits restrict long-term evidence.
- Live horizon registration can use an observed forming candle; archived training
  uses completed bars. This input-distribution parity remains unproven; current
  horizon models in the checkpoint are disabled with only 22–23 live samples.
- GitHub scheduling is best effort, not guaranteed continuous capture. Closed
  candle catch-up cannot reconstruct missed live books or event observations.
- Volume AI's low-volume amplification and FVG reuse after an intervening fill
  are unvalidated strategy hypotheses. They were not changed without chronological
  comparative evidence; pattern names are not guarantees.
- Original historical artifacts remain historical results from their own code
  versions; corrected evaluators must be rerun before replacing those figures.

The tree survey and implemented fixes are substantial progress. Full predictive
quality, uninterrupted operation and authenticated live UI accuracy remain
empirical checks, not claims inferred from a green test suite.
