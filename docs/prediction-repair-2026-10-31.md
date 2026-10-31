# Probability integrity and controlled model experiment — October 31, 2026

## Verified defects repaired

1. `terminal_above_probability` clipped the recorded market probability to
   .01–.99. Applying the unvalidated fallback consequently turned a .999 market
   quote into .99, although the selector claimed it was the market baseline.
   Numerical clipping now stays inside log-odds calculations; baseline quotes
   remain exact, invalid quotes become missing, and reported raw edge matches
   the returned raw probability. No execution authorization is added.
2. All three Kalshi readers requested an unlimited order book although their
   features use only the top five levels. The background reader returned no
   depth during diagnosis; an explicit depth=5 response returned a usable
   259-byte, ten-level book in 2.576 seconds. Requests now use depth=5. App and
   background reads use bounded four-second budgets and try the backup on an
   empty book; learner retains its existing bounded per-host timeout. Freshness
   and actual selected-side size are still required. A network timeout is still
   possible and must block fills, not fabricate liquidity.
3. Separate SCALP research only accepted SCALP-labeled outlooks. A frozen LOCK
   outlook could consequently prevent that market from teaching the independent
   bid-path study. Research now accepts either directional outlook, records the
   source action, and exposes missing/stale depth. It cannot execute or promote
   a strategy, change a LOCK, or turn final settlement into an early-exit label.

Official endpoint contract (depth=0 means every level; bounded depth1–100):
https://docs.kalshi.com/api-reference/market/get-market-orderbook

## Controlled experiment and rejection

`settlement_benchmark.py` is a read-only experiment, not a new execution model.
It evaluates exactly three predeclared market-offset logistic forms: intercept
only, intercept plus market-odds shape, and those plus frozen independent
probability/council/pressure features. Ridge penalty10, at most500 prior markets,
minimum150 training markets, and a bounded10-point probability correction are
fixed. Each fit sees only official labels already observed before its forecast.
Observations must match the exact ticker, expiry, reference and quote timestamps.
One contract earns one observation per remaining-time group.

The same latest100 contracts are reserved across all horizons. At least100
preceding development predictions select the algorithm; reserved outcomes cannot
select it. Parameters then update causally during the reserved period. This is
an experiment on reused retained data, not a virgin data source, new live
accuracy, fee-aware paper simulation or an automatically promotable result.

The development-selected shape candidate was rejected:

| Remaining time group | Reserved markets | Candidate accuracy | Market accuracy | Candidate Brier | Market Brier |
| --- | ---: | ---: | ---: | ---: | ---: |
| 10–15 minutes | 100 | 62% | 58% | .238947 | .233281 |
| 5–10 minutes | 100 | 71% | 73% | .190695 | .186749 |
| 1–5 minutes | 100 | 86% | 86% | .089408 | .088515 |

Lower Brier is better. Higher accuracy on one timing slice did not establish
better probability estimates. No candidate was promoted. The model-advantage,
positive fee-adjusted P/L, paired superiority, drawdown and three-evaluation
promotion requirements remain intact. No accuracy/profitability improvement is
claimed for these repairs.

Full results and source SHA-256 are in `settlement-benchmark-2026-10-31.json`.
The source was the learning-state snapshot with
`updated_at=2026-10-31T18:54:31.491575+00:00` (learning-state commit
`e1ee6a1455e20bb7497d220c07e004d9f1536a65`). Reproduce from that JSON:

```
python settlement_benchmark.py /tmp/state.json --as-of 1793472871.491575 --output /tmp/report.json
```

Run `python tools/run_offline_tests.py` for regression verification. Tests cover
exact tail baselines, invalid probabilities, bounded depth and backup recovery,
research capture/immutability, official observation chronology, deduplication,
selection independence from reserved labels, and cross-horizon holdout isolation.
