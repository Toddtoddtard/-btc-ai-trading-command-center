# Settlement learning v2 — 2026-10-30 Eastern

The goal is better official Kalshi outcome probabilities, rather than faster
data downloads or artificially higher confidence. All work remains free and
paper-only. No specialist, strategy threshold, balance or historical label is
removed or reset.

## Algorithm changes

The independent final-average model previously fitted its correction to each
market's earliest observation, then reused that correction at every remaining
time. It now selects one independent observation per market in the **same**
10–15, 5–10, 1–5, or final-minute group. Expiry and actual official-label
observation times still control which outcomes can be learned from.

The legacy execution calibrator forces symmetry around 50% and cannot learn an
intercept. A new fixed ridge model learns a residual around the Kalshi midpoint
using `[1, market - .5, independent_base - market]`, penalty 2, the last 500
already-observed markets and at least 100 training markets. The intercept can
correct persistent directional bias. The total live correction is bounded to
15 percentage points; probabilities remain within .001–.999.

The incumbent remains the default. The new model must satisfy all existing
chronological gates: 100 validation markets, at least .002 Brier gain over the
paired market, no accuracy loss, and no recent-100 Brier/accuracy harm. It must
also improve incumbent Brier overall without recent Brier harm. Fitting and
validation use the same deduplicated, time-specific cohort.

Additionally, promotion requires at least 100 **new frozen** official candidate
forecasts in that time group, a positive paired Brier interval against Kalshi
and a nonnegative paired accuracy interval, with no Brier loss to the frozen
independent forecast. `improvement_evidence.paired` owns those comparisons.
No candidate outputs are backfilled from today's fitted coefficients.

Each candidate capture records algorithm identity, training cutoff, capture
time, horizon, candidate and independent probabilities. Same-contract identity,
fresh quote/reference times, capture/expiry matching and actual observed labels
are checked before scoring. Pending and duplicate outcomes cannot inflate the
count. Candidate scoring is a forecast evaluation, not a simulated fill.

The shared production selector applies the learned intercept identically for
dashboard and worker when promoted. Existing LOCK quarantine, fee checks,
freshness, confidence, depth and per-market rules still apply independently.
The independent base model/version and its four residual features are
unchanged; `correction_version=horizon-residual-v2` identifies the new
time-specific training policy. Production comparisons remain revision-specific.

## Alternatives and retained-snapshot diagnostic

A larger fixed model using all individual specialist scores was rejected: on
the saved chronological replay it worsened market Brier by .002505 at 10m+,
.003673 at 5m+, and .002358 at 1m+. Additional inputs did not establish an edge.

The simpler bias correction addresses a specific limitation with three
parameters. It also remains **unpromoted** on the retained snapshot:

| Time group | Validation markets | Legacy Brier | Bias candidate Brier | Paired Kalshi Brier |
| --- | ---: | ---: | ---: | ---: |
| 10–15 minutes | 419 | .233931 | .233516 | .234546 |
| 5–10 minutes | 419 | .180411 | .179320 | .178797 |
| 1–5 minutes | 420 | .098724 | .098786 | .097786 |
| Final minute | 0 | — | — | — |

Lower Brier is better. Early/middle candidate improvement versus the old fit is
small; the late candidate is worse. The early candidate's full validation
accuracy is 60.62% versus market 61.10%, so it fails qualification. Its most
recent 100 score 63% versus market 62%; that does not establish an improvement.
Zero newly frozen candidate settlements existed at implementation time.

Snapshot: `updated_at=2026-10-30T23:54:19.169740+00:00`;
SHA-256 `a342ea98473fcfc3fbc2edba36c58fed0b87d1fe95a261fd8b76389f95d5eb62`.
These are reused development diagnostics, not an untouched holdout, new live
accuracy, or profitability evidence. Serial market dependence, repeated
monitoring and multiple timing comparisons limit approximate paired intervals.

## Verification and navigation

Run `python -m unittest tests.test_settlement_learning -v`, then the existing
`python tools/run_offline_tests.py` gate. The new suite covers directional bias,
causal label availability, bounded inference, shared settlement selection,
incumbent preservation, the prospective promotion requirement, horizon isolation,
immutable captures, official resolution, duplicate suppression and no backfill.

To reproduce the retained-state model report, load the JSON snapshot and call
`contract_calibration.fit_settlement(state, as_of=1793404459)`; each
`by_horizon` entry retains its `bias_challenger` diagnostics. The dashboard's
“Learning algorithm — new official results” panel reports the separate live
cohort. Worker publication/deployment must be verified from a new revision-stamped
checkpoint, separately from code checks.
