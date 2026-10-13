# Exact Kalshi 15-minute settlement predictor

The user-facing prediction answers YES or NO for the exact active KXBTC15M
contract, against its pinned target and expiry. The supported current rule is
`greater_or_equal`: Kalshi compares the final minute's reference average, rounded
to cents, with the target. A single terminal Bitcoin price is a different event.

## Implementation

- `settlement_predictor.py` forecasts the final-minute arithmetic average using
  fresh, matching Kalshi chart prices and closed official reference candles.
  Its Brownian uncertainty approximation includes covariance among the future
  average samples; observed final-minute seconds contribute their actual prices.
- Unknown elapsed reference seconds, stale feeds, wrong contract identity,
  missing targets/quotes, insufficient history and unsupported rules produce
  Unavailable. There is no silent Binance substitution.
- After 100 independent officially resolved markets, a regularized bounded
  correction can learn from market probability, council score and book pressure.
  A label is usable only after its recorded official observation time.
- The existing scheduled worker and research journal persist frozen predictions,
  features and coefficients. Restarting does not lose training data or rewrite
  earlier probabilities with later weights.
- The dashboard shows the predicted outcome, YES/NO probabilities, target,
  contract, close time, market comparison and independent settlement scorecard.
  The scorecard counts the earliest valid forecast per market, even for WAIT.
  Those forecasts measure event prediction accuracy, not directional trade wins.
- Paper execution remains governed by existing approved probabilities and fee
  safeguards. The new model is explicitly experimental and affects no orders.

## Evidence and limits

Nine focused regressions cover the average/spot distinction, cent threshold,
identity/freshness/rule rejection, missing final-minute seconds, closed candles,
frozen independent scoring, label chronology, persistence and malformed state.
Local repository runner: 378 tests, one skipped Streamlit startup dependency
check, no failures. The hosted suite must verify that startup check before merge.

A live public-data smoke check returned a valid exact-contract prediction from
3,601 one-second reference ticks and 60 candles. This verifies connectivity and
input semantics; it does not demonstrate prediction quality.

No old Binance snapshot is relabeled as official reference training data.
No retrospective accuracy, profitability or performance gain is claimed.
Prospective official settlements must establish accuracy, Brier calibration and
incremental value over contemporaneous Kalshi probability. A separate reviewed
promotion change would be required before this model can authorize paper trades.

Automated reviewer delegation was attempted but unavailable because its usage
limit was reached. The implementation received a manual code/diff review and
the regression checks instead.
