# Settlement execution and scoring repair — 2026-10-26

Implement the user's approved diagnosis repairs in the existing Python app and worker.
Preserve paper-only operation, ledger history, confidence floors, entry caps, fee
checks, immutable LOCK sides and prospective validation. No new dependencies.

## Tasks

- [x] Add failing regressions for official versus proxy scoring, settlement
  model qualification by time remaining, delayed labels, stale evidence, and
  propagation to both app and worker execution.
- [x] Extend contract calibration with independent settlement-average candidates
  by time bucket. Fit on the base estimate, one market per bucket, using only
  already observed official labels. Retain existing promotion thresholds and
  market fallback; expose the reason when no validated edge exists.
- [x] Reuse the same calibrated probability selector in the dashboard and
  worker. Freeze the first published decision for official scoring. Keep
  candle-path and council-specific learning separate.
- [x] Correct scorecard and dashboard labels and denominators. Add explicit
  official-decision scoring without rewriting old outcomes or paper history.
- [x] Run targeted and full offline regressions; replay the retained snapshot
  diagnostically without promoting a strategy from an in-sample result.
- [ ] Review the whole diff, publish a focused PR, verify hosted CI, integrate
  the authorized repair and report deployment/validation limits honestly.

## Review focus

Stale or wrong-contract forecasts cannot authorize entries. Models validated at
one horizon cannot authorize another. Delayed outcome labels cannot leak into
earlier predictions. Neutral decisions do not become wins/losses. Missing or
unproven probability must leave a clear no-edge reason, never manufacture profit.

Baseline: 462 offline tests passed, one skipped. Fresh isolated clone on branch
`fix/settlement-execution-and-scoring`; source `main` fetched during clone.

Verification: 474 offline tests run, zero failures, one skipped; compile and diff
checks passed. Independent reviewer found no blocking issues and ran 26 focused
checks. Diagnostic qualification took about 0.22 seconds; all retained settlement
buckets remain unqualified. Paper ledger was unchanged by fitting/scoring.

The user explicitly approved publication and merge on 2026-10-26 after the
automatic approval review requested confirmation. Hosted verification and
integration are the remaining steps. Local implementation commit: e1596fc.
