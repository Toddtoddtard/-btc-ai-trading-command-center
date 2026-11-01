# Kalshi paper fee accounting

The November 1, 2026 rules baseline identified an existing accounting mismatch,
not a newly announced Kalshi rule change. A one-contract purchase at $0.055
previously debited $0.065; the published non-direct-member method debits $0.06.
A sale at $0.955 previously credited $0.945; the correct credit is $0.95.

## Official sources

- [Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding): model fee
  ceiling at $0.000001; signed cash change floors to member balance precision;
  rounding overpayment carries across the fills of the same order. The page
  does not state an effective date.
- [Fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf): current schedule
  marked effective July 7, 2026; standard taker rate 0.07 times contracts times
  price times one minus price. No binary settlement fee.
- [KXBTC15M series](https://api.elections.kalshi.com/trade-api/v2/series/KXBTC15M):
  baseline fee type quadratic, multiplier 1. A future series or event override
  needs separate review; this repair does not assume fee schedules never change.

## Scope

`PAPER_BALANCE_PRECISION = '0.01'` explicitly retains the paper account's
non-direct-member assumption. Direct-member precision is supported by the
shared helper but is not inferred from the user's real account. Money arithmetic
in the helper uses Decimal; existing JSON and SQLite amounts remain floats for
compatibility. The taker wrapper normalizes public quote prices to four decimal
dollars to discard float complement noise.

Each simulated entry or sale is one full taker fill at the observed quote.
The helper exposes fee components and an accumulator for split-fill calculations,
including maker fills, without adding partial-fill or maker execution to the
paper engine. A new simulated order starts with zero accumulated rounding.
All realized sale and liquidation estimates use positive signed revenue;
entries use negative revenue. Official binary settlement continues to pay $0/$1
without an exit fee. Entry caps, confidence thresholds and live-trading settings
are unchanged.

Prospective entries and closes store `entry_fee_model` / `exit_fee_model`.
Legacy entries keep their stored fees and unversioned metadata. Already-closed
ledger rows and stored P/L are not retroactively changed. An older open position
keeps its historical entry cost and uses the new model only for a future sale.

## Retained ledger comparison

A read-only snapshot of `learning-state/learning_state.json` published at
2026-11-01T16:40:08.145740+00:00 contained 160 retained trade rows. Comparing
stored fees with the new single-fill non-direct-member model found differences
in 12 closed rows, with total modeled fees $0.015 lower in aggregate. This is a
counterfactual accounting comparison, not proof of actual exchange fills or an
exhaustive all-time audit. No historical balance, row, official label, win rate
or P/L was rewritten. The small net difference does not explain poor forecasting
accuracy or establish improved strategy performance.

## Verification

Run `python -m unittest discover -s tests -p test_kalshi_fee_rounding.py -v`, then
`python tools/run_offline_tests.py` for shared accounting and runtime regressions.
Cases cover the official example, cent-priced compatibility, signed sales,
explicit direct precision, equivalent precision strings, order rebates, rebate
caps on maker fills, invalid inputs, and preservation of legacy SQLite fees.
