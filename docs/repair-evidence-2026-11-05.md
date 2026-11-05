# BTC Trader Busa implementation evidence — November 5, 2026

Scope: Issue #95 and confirmed reliability/performance defects. Paper only. This is not a claim that the system is profitable or that all nine requested priorities have completed prospective validation.

## Confirmed defects and implemented changes

- Dashboard live Master/Outlook calculations and persistent pending decisions could disagree. Added `decision_snapshot.py`, a versioned content-identified worker snapshot. `learner_v31.py` publishes refreshed pending evidence; dashboard and executor consume it. Ordinary forecasts/SCALP vocabulary become WAIT for execution. Explicit LOCK UP maps to YES and LOCK DOWN to NO. Existing LOCK side cannot reverse.
- Cached signals could survive repeated paper retries without a new observation. Every worker paper pass now recomputes through the existing learner path using current feeds; missing/stale/future/mismatched evidence fails closed. Both fills and SCALP-to-LOCK promotions validate the snapshot. Existing positions continue their own ticker/expiry lifecycle during prediction outages.
- Many early returns exposed only an awaiting-checks placeholder. Every result now records the concrete reason, decision ID/time, and actual position separately from the latest forecast and fill. New fills, signal attempts and lifecycle events carry decision IDs.
- A missing old balance-reset marker could archive existing trades. Runtime no longer invokes historical reset/void migrations on existing accounts. Missing/unsupported account versions are rejected without replacing funded state. Migration helpers remain available for their historical explicit repair tests; no authoritative ledger was rewritten here.
- Automatic scalping was still marked enabled in source and the state validator. Restored explicit LOCK_FIRST/disabled mode, preserving directional forecast and shadow research functionality. Updated the validator and existing mode assertions.
- Missing 8m/2m timing rows: added them to independent and paired scorecards using only original observed pre-checkpoint forecasts and official labels. No missed forecasts were reconstructed.
- Full state download was 45,738,313 bytes. Lossless gzip measured 4,240,087 bytes (90.7% smaller). Worker publication and the legacy ledger-repair workflow now atomically update JSON and gzip; public clients use gzip with original JSON fallback. Entire history/model state remains intact.
- Availability watchdog browser job failed before reaching the app: GitHub run 42014063879 / job 127200015026 reported Playwright 1.55 does not support Ubuntu 26.04. Pinned the availability browser job and smooth-chart browser job to Ubuntu 24.04. The first PR chart run 42055714738 reproduced the same dependency failure before its chart test; this follow-up fixes that runner too. Learner recovery in the same run succeeded.

## Verification

- Hosted full-audit run 42055922424 passed its tests but failed a legacy BALANCED_CALLS-only source check. Updated it to verify the shared LOCK_FIRST path and use the full offline runner, which also includes standalone tests.

- Baseline: 580 offline tests passed before changes.
- Final implementation suite: 595 offline tests passed; Python compilation and whitespace checks passed. New failure reproductions were run before their fixes. Two obsolete assertions for enabled scalping/balanced copy were updated to the user's explicit LOCK-first requirement.
- Independent review found stale SCALP promotion, unsupported-version account replacement, and alternate JSON publisher/gzip divergence. All were addressed; stale promotion and version replacement reproductions now pass.
- Actual mobile chart browser smoke test passed six updates: retained chart node, changing prices, retained zoom/horizon, Eastern tick labels within mobile budget, server forecast and no page errors.
- Public deployed app was asleep; wake requested and private access gate rendered at r114. Authenticated live dashboard unavailable without its access code. New build identity is r115-shared-worker-outlook; hosted CI, merge and worker/deployment observations are recorded separately in the final handoff.

## Authoritative retained state and economics

Source: learning-state JSON updated 2026-11-05T15:06:26.418354+00:00 (10:06 AM Eastern), producing revision cbd723e. Download was parsed completely; the ledger reconciled. Subsequent runtime statistics may change.

| Metric | Verified value |
| --- | ---: |
| Starting paper balance | $500.00 |
| Cash/equity, no open/pending positions | $466.365 |
| Closed trades | 159 |
| Wins / losses | 92 / 67 |
| Trading win rate | 57.86% |
| Recorded fee-adjusted P&L | -$33.635 (-6.727%) |
| Profit factor | 0.9157 |
| Mean entry price | 62.39 cents |
| Mean winning / losing trade | +$3.97 / -$5.96 |
| Recorded entry + exit fees | $47.42 |
| Learner graded samples | 4,113 |
| Candle-learning backlog | 0 minutes |

Winning more than half is insufficient: average losing trades exceed average winning trades, and recorded fees exceed the gross pre-fee gain. Existing validated-edge, confidence, price, liquidity and quarantine gates remain in force. The old P&L is not a backtest of the new decision plumbing.

## Official forecast evidence (not paper-trading returns)

The independent archive has 519 distinct officially resolved markets: 59.73% accuracy; Brier 0.23119 versus market 0.22289 (lower is better). These retained forecasts include WAIT and multiple historical builds. Each timing row deduplicates contracts separately; rows must not be added together.

| Checkpoint | Distinct markets | Independent accuracy | Model Brier | Market Brier |
| --- | ---: | ---: | ---: | ---: |
| 10m | 510 | 67.84% | 0.20847 | 0.20416 |
| 8m | 512 | 70.90% | 0.19879 | 0.18482 |
| 5m | 510 | 74.71% | 0.16547 | 0.15347 |
| 2m | 508 | 84.45% | 0.11423 | 0.09808 |
| Final pre-settlement checkpoint (1m) | 507 | 89.35% | 0.08647 | 0.06510 |

Checkpoint tolerance remains 150 seconds BEFORE the checkpoint: the final row is not an exact last-second observation. Increasing late accuracy does not establish a fee-adjusted trading edge.

The exact current producing revision's paired production cohort has only 56 settled markets: 73.21% accuracy, 95% Wilson interval 60.41–83.04%, identical to market baseline probability selection (Brier gain zero). This does not verify the 70% target or a profitable advantage. No execution calibrator was active in the retained state; explicit no-validated-edge vetoes are expected.

## Chronological candidate experiment

`docs/settlement-benchmark-2026-11-05.json` records the existing fixed bias/shape/context experiment with source SHA256. Latest 100 contracts reserved across timing groups; only 99 eligible observations per reported timing group. Candidate selected using development results only. Bias candidate early accuracy 72.73% versus market 70.71%, but Brier gain -0.00013 with interval -0.00234 to +0.00208. Other timing intervals also cross zero. This reuses retained data and does not represent untouched prospective performance, simulated fills, or profitability. No candidate promoted and no safeguard relaxed.

## Remaining verification

- Hosted CI and observed post-merge worker/snapshot publication, compression and deployed build identity.
- At least 100 distinct officially settled markets produced after this deployment, including matched decision/fill provenance. Pre-deployment forecasts cannot satisfy this cohort.
- Authenticated deployed dashboard/mobile execution display, because the public gate requires an unavailable access code.
- Exact last-seconds forecast coverage remains bounded by worker cadence. The one-second chart does not imply a one-second learner or worker.
- No model has demonstrated reliable superiority to market probabilities. All specialists remain available and existing chronology/rare-specialist tests remain active; no speculative indicators or strategy promotion were added.
- Existing one-LOCK cap, calibrated confidence/validation checks, fee-aware margin, risk limits, reference/depth freshness and official own-ticker settlement safeguards remain. Real-money permissions were not modified.
