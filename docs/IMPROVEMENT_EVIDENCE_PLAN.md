# Measurable improvement — 2026-10-26

Goal: stop equating code fixes with predictive gains. Compare frozen forecasts
on the same contract, at the same time, against both the previous execution
probability and Kalshi's contemporaneous midpoint. Record the producing code
revision. Keep independent raw forecasts as challengers, not an unvalidated
headline probability that contradicts the production decision.

Implementation:

- Add failing tests for paired results, duplicate/late-label protection, empty
  cohorts, immutable captures, version identity and display/decision agreement.
- Extend existing settlement captures with compact, versioned probabilities and
  asks; reuse their official resolution and checkpoint selection. Do not backfill
  unknown historical production forecasts.
- Report accuracy, 95% Wilson uncertainty, paired Brier gain with an approximate
  95% interval, matched sample counts and first/latest capture times. Report
  10m, 5m and 1m checkpoints separately. First assessment after 100 independent
  markets; an uncertain interval is inconclusive. A 70% target is verified only
  if its lower accuracy bound reaches 70%. Monitoring does not promote a model.
- Show actual net paper P/L and wins/losses for tagged new-version trades only;
  a forecast comparison is not a paper fill or a profitability claim.
- Make the settlement headline use the actual production probability and name
  the baseline/source. Preserve independent model outputs for learning/testing.
- Stamp worker state/captures/trades with revision and policy identity. Verify
  a real published checkpoint, not just a running workflow or old build label.
- Run targeted/full tests, independent review and hosted checks before merge.

Research already performed: fixed-ridge logistic market calibration and a
specialist/depth residual were compared causally on development data. The
development-selected market calibration failed to beat Kalshi Brier on the
held-out final 100 contracts (gain -0.0002485; market-clustered bootstrap 95%
interval -0.00399..0.00348). Reject this candidate for execution. Do not advertise
its 71.3% mixed-timing accuracy as a 15-minute edge; market baseline was 70.3%,
and the probability score was worse. Further tuning on that holdout would make
it development data, not fresh validation.

The retained chart path lost to persistence over 200 prospective checks
(MAE $61.14 vs $59.23). Do not replace the requested non-flat chart with an
invented claim of improvement. Its separate error report stays visible.

Experiment specification: market log-odds offset; ridge=10, up to 10 Newton
steps, last 300 already-observed markets per timing bucket, minimum training
100. Candidate A uses intercept/market-logit calibration; candidate B also uses
base-minus-market logit, council score and order-book pressure. Corrections are
bounded to +/-0.5 log-odds. Select on chronological development Brier, then
evaluate only the selected algorithm on the final 100-contract holdout.
Input snapshot SHA-256: `51932f0f623d997784834838974c68891f971629dcaf3553146db401b6ae25a1`.

Review fix: isolate all displayed forecasts and actual paper results to the
exact producing code revision; missing revisions and other builds are excluded.
The worker publishes the comparison after paper cycles on every checkpoint,
not only when somebody opens the dashboard.
