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

- Hosted browser run 42056258938 then timed out while apt waited on azure.archive.ubuntu.com, before launching the chart. Browser jobs now install Chromium using runner-provided libraries, verified by actual browser launch; the mandatory chart test remains unchanged.

- Hosted full-audit run 42055922424 passed its tests but failed a legacy BALANCED_CALLS-only source check. Updated it to verify the shared LOCK_FIRST path and use the full offline runner, which also includes standalone tests.

- Baseline: 580 offline tests passed before changes.
- Initial repair suite: 595 offline tests passed; compressed API recovery follow-up: 598 passed; Python compilation and whitespace checks passed. New failure reproductions were run before their fixes. Two obsolete assertions for enabled scalping/balanced copy were updated to the user's explicit LOCK-first requirement.
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


## Live deployment verification and CDN recovery follow-up

- PR #96 merged as `22c651f1fc216e9dd1666913af63de3199e8b5a6`; all five final hosted CI workflows passed, including the browser chart check and full audit. The deployed private-access gate rendered r115. Availability browser and learner-recovery jobs also passed after merge.
- PR #97 merged as `4eaea0ab47f95f99a4f452bf09eaa03a8eb2fbd8`. Historical ledger repair is now manual-only, uses the shared non-replacing state-writer queue and shallow checkout. The merge-triggered old repair found an already-present correction marker; the original 159 rows and exact cash are unchanged in the verified new worker state.
- The old worker completed successfully. New worker run `42057983451` passed its startup/regression checks and published revision `22c651f...`. The first rollover checkpoint safely rejected an expired contract; the next published a valid current-market snapshot.
- Immutable learning-state commit `ab58c706d4980656d18cbe1b293014b9b8b2ed15` contains a fresh-at-capture decision for `KXBTC15M-26NOV051115-15`: ID `622af3590cb83fe6ab06fedb`, capture 2026-11-05 16:03:30 UTC. Snapshot, paper assessment and dashboard selector IDs match. Action WAIT, forecast YES probability 59.5%, approval false, no fill. LOCK_FIRST and automatic scalping=false were confirmed in persisted state. Worker healthy; 4,117 graded samples; zero candle backlog; ledger reconciles at $466.365 with 159 unchanged closed rows.
- The new producing revision has only **one** officially settled forecast market (including WAIT), no new closed paper trades, and no proven advantage over the market baseline. This is insufficient evidence for the 70% target or profitability. The existing accuracy automation now requires a distinct prospective deployment cohort and preserves LOCK-only safeguards.
- Direct public branch downloads continued serving the older 15:49 checkpoint after the new worker publication. Verification used the immutable state commit to avoid attributing stale CDN data to the new build. The reader follow-up prefers gzip for authenticated/API recovery too, and allows stale decisions to trigger the existing five-minute-bounded recovery before general learning staleness. Corrupt/truncated gzip, including invalid DEFLATE data, falls back to original JSON. Authentication remains on constructed GitHub API URLs with validated blob SHA; recovery stays capped at 12 attempts/hour (worst-case 48 Contents/blob requests with both fallbacks).
- Follow-up build label: r116-compressed-state-recovery. Its final hosted results and deployed gate verification are recorded in the PR/final handoff; authenticated dashboard remains untested without an access code. This changes data retrieval, not prediction formulas, financial safeguards or model promotion.

## Complete changed-file inventory

- `.github/workflows/btc-audit-v16.yml`
- `.github/workflows/health-watchdog.yml`
- `.github/workflows/learn.yml`
- `.github/workflows/repair-observed-paper-win.yml`
- `.github/workflows/smooth-chart.yml`
- `ARCHITECTURE.md`
- `access_control.py`
- `app.py`
- `background_paper.py`
- `decision_dashboard.py`
- `decision_snapshot.py`
- `docs/CODE_MAP.md`
- `docs/repair-evidence-2026-11-05.md`
- `docs/repair-plan-2026-11-05.md`
- `docs/settlement-benchmark-2026-11-05.json`
- `improvement_evidence.py`
- `learner_v31.py`
- `lock_focus.py`
- `scripts/validate_learning_state.py`
- `settlement_predictor.py`
- `shared_learning.py`
- `tests/test_contract_regressions.py`
- `tests/test_decision_snapshot.py`
- `tests/test_improvement_evidence.py`
- `tests/test_lock_focus.py`
- `tests/test_runtime_imports.py`
- `tests/test_shared_learning.py`
- `tests/test_worker_session.py`
- `worker_session.py`
