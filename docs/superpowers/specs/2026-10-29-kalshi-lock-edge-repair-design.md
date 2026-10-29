# Kalshi LOCK edge repair design

## Problem

The authoritative post-fix paper ledger has more than 100 distinct settled
Kalshi markets, but its profit factor, after-fee expectancy, and maximum
drawdown all fail the saved validation thresholds. The loss is concentrated in
LOCK entries, especially contracts bought in the 65-75 cent range. The current
LOCK path deliberately bypasses the ordinary profitability gate and accepts a
calibrated probability that clears the executable ask by only enough to cover
the entry fee. That is too small a margin for forecast error.

## Approaches considered

1. Lower the fixed LOCK price cap. This is simple, but it conflicts with the
   configured 93-cent backstop and cannot distinguish a genuinely strong
   high-price forecast from a weak one.
2. Disable LOCK or weak specialists. This would hide the failure instead of
   measuring it, and would violate the requirement to keep rare-event
   specialists active.
3. Add an evidence quarantine plus a price-aware net-edge floor. This keeps all
   calls and specialists observable, prevents new failing-cohort LOCK fills,
   and requires any future eligible LOCK to clear executable cost by a
   meaningful probability margin. This is the selected approach.

## Design

- Add a shared LOCK validation policy using the stated proof thresholds:
  at least 100 distinct completed markets, profit factor at least 1.15,
  positive after-fee expectancy, and maximum drawdown no greater than 10%.
- Apply that policy to the authoritative persistent paper worker before a new
  LOCK fill. A failed mature cohort blocks the fill and records the directional
  call as `BLOCKED`; it does not disable LOCK decisions, specialists, or
  official-outcome learning. A cohort below 100 markets keeps collecting and
  does not deadlock initial evidence gathering.
- Strengthen `expected_lock_net_pnl` with a five-percentage-point probability
  safety margin above executable entry cost. The existing calibrated
  settlement probability, recorded Kalshi fee, quote validation, 93-cent hard
  cap, confidence floor, and one-LOCK-per-market rule remain required.
- Reuse the shared edge calculation in SQLite paper execution, the persistent
  worker, and the pro-trade preview so the UI cannot advertise a fill that an
  engine rejects.
- Keep the application paper-only. Do not change settlement truth, balances,
  historical trades, specialist activation, SCALP recovery, or LOCK direction
  immutability.

## Verification

- Regression tests reproduce a 73-cent weak-edge LOCK that currently opens and
  prove that it is rejected in all execution/preview paths.
- Regression tests prove a sufficiently strong calibrated edge remains
  eligible when the scorecard is collecting or passing.
- Regression tests prove a mature failed 100-market scorecard blocks only the
  LOCK fill while preserving the call record and SCALP behavior.
- Run the focused tests, the complete offline suite, the repository audit
  workflows available locally, hosted CI, and the deployed Streamlit health
  check before merging.

## Limitation

This repair reduces exposure to the observed failure mode. It does not prove or
guarantee future profitability; only new prospective settled markets can do
that.
