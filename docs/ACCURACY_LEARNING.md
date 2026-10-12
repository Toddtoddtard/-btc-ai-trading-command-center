# Official-outcome calibration repair — 2026-10-12

Council confidence previously learned from the candle path's Binance expiry
label, even when the council's captured direction disagreed. On the retained
October 12 checkpoint, 86 of 447 directional council observations had a
different official correctness label. Low-volatility regime EWMA was 99.54%
under the proxy accounting; rebuilding from the council's captured side and
official Kalshi results yields 66.34%. This is a correction of training evidence,
not a claim of improved live accuracy.

`reconcile_master_learning` archives the prior calibration once, then rebuilds
confidence and regime evidence from immutable, pre-expiry prediction snapshots.
Unresolved outcomes and neutral council scores do not train it. Candle price
error learning remains separate. Repeated recovery runs cannot double-count
observations or change the paper ledger.

Specialist contribution replay now reconstructs its weights from earlier,
already-ended markets. It cannot use today's fitted weights or contribution
ranking, which already contain the observation being tested. Retrospective
ablation reports no longer supply production contribution multipliers. All
specialists remain available; their independent official-outcome accounting
continues to learn.

`contract_calibration` evaluates the terminal probability correction using one
first captured observation per ticker, sorted by capture time. Training excludes
markets that had not expired at the validation capture. A bounded ridge residual
may influence calls only after 100 training markets and at least 100 chronological
validation markets, an overall Brier improvement of at least 0.002, no overall
directional degradation, and nonnegative Brier/accuracy improvement over the
last 100 validation markets. No new fees, subscriptions, or external host.

The retained checkpoint has 859 matched markets: Kalshi midpoint accuracy
77.88%, original terminal blend 76.02%; Brier 0.15380 versus 0.15864 (lower is
better). The fitted correction failed its separate causal validation gate:
759 validation markets, candidate Brier 0.15450 versus market 0.15385.
It therefore uses the current midpoint while continuing to capture and learn
the raw terminal model. These are historical comparisons, not a profitability
promise or post-deployment result.

Both live dashboard and scheduled learner apply this same correction gate.
Background paper scalp projections receive the same probability fields and
cannot manufacture a separate optimistic exit from old candle geometry. With
no validated price advantage, a scalp may fail its existing profit test. LOCK
remains available under its existing qualification checks, and an established
LOCK cannot reverse. The 93% LOCK / 75% SCALP caps remain in force.

Focused regression checks cover label disagreement, official-only evidence,
idempotent migration, chronological purging, phase deduplication, helpful/harmful
candidate gates, contribution leakage, probability propagation, ledger handling,
and LOCK persistence. The GitHub learner runs the new calibration checks before
publishing a checkpoint.

GitHub Actions scheduling remains best effort. This change does not make its
cron a guaranteed continuous worker, and delayed runs cannot recreate missed
live order-book observations. The candle catch-up learner remains responsible
for recovering closed-minute price history.
