# PR #63: prospective cutoff comparison

## Decision

Do not merge the October branch. Current main already checks validated LOCK
expected value. Compare a bounded subset of the old proposal prospectively:
remove LOCK price/confidence/focus cutoffs and reduce the after-fee margin
from five cents to one cent, while preserving current execution approval,
validated probability provenance, source health, target confirmation, window,
fresh reference/forecast/depth, quantity limits and LOCK quarantine.
This deliberately does not reproduce PR #63's removal of learned reliability
gates. It does not authorize SCALPs from a terminal probability.

## Approach and limits

Reuse the background worker's existing depth read and official result reader.
Freeze one paired hypothetical LOCK assessment per ticker on the first fresh
observation. Retain blocked observations, both blocker lists, probability,
revision, quantity and rounded fees. Do not backfill old predictions or create
paper trades. Quantity is capped by observed top-of-book depth and 2% of
current paper cash; this is a snapshot scenario, not portfolio replay.

The alternatives were merging the stale branch (conflicts and weaker controls)
or merely adding more legacy strategy-league rules (different probabilities
and no current final-assessment parity). A separate research-only state key
keeps the experiment versioned and the authoritative ledger unchanged.

Resolve only the captured ticker's official settled/finalized YES/NO result
after expiry. Exclude unknown, delayed and future labels. Compare matched
markets per producing revision, and report added entries, after-fee expectancy,
scenario drawdown, Brier/calibration and approximate paired P/L uncertainty.
At least 100 distinct official markets AND 100 additional candidate entries
are needed for an initial review. No automatic promotion. Serial dependence,
selection, general 0.07 fee assumptions, sampled liquidity and unmodeled fills
limit conclusions. Existing observed SCALP-path research remains separate.

## Implementation plan and verification

- [x] Add failing regressions for paired policy differences, preserved guards,
  finite inputs, depth sizing, immutable capture, official chronology, distinct
  markets, cohort isolation, uncertainty and ledger isolation.
- [x] Implement `cutoff_research.observe`, `resolve` and `scorecard`, called from
  the existing background research block. Publish a dashboard comparison.
- [x] Run focused tests, the full offline suite, compile and diff checks.
- [ ] Review the final diff and publish a replacement PR from current main.
  Merge the research instrumentation only after checks pass; retire #63 once
  its replacement is captured. No production eligibility changes.

The user delegated the choice and implementation after reviewing the proposed
shadow comparison. Work is performed inline on an isolated feature branch.

## Verification and review

Based on main `5ef297f`, including the concurrent worker-queue repair. Fourteen
new regressions cover the trial; full offline runner: 558 tests, one skipped,
no failures. Python compilation and diff checks pass. Independent review found
stale inherited window checks and settlement reads on the execution path; both
were reproduced with failing tests and fixed. Remaining time is recomputed at
capture, and label resolution runs after the current execution cycle. Malformed
tiny prices use bounded binary-search sizing; dropped unresolved observations
are counted separately. No paper ledger, strategy gate or forecast is rewritten.

Hosted CI, merge and first new-version worker capture require separate checks.
Prospective evidence begins empty; no improvement or profitability is claimed.
