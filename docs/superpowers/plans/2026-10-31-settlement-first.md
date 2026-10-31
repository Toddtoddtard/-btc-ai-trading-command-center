# Settlement-first paper decisions

Goal: make forecast, paper approval and evidence distinguishable without manufacturing a trading edge.

Architecture: retain the existing specialist and settlement selectors; add one pure final assessment consumed by preview and persistent execution. Position lifecycle, depth, official settlement and immutable LOCKs retain their existing owners. All model changes remain subject to existing causal validation and promotion requirements.

Constraints: free/public feeds; paper-only; preserve ledgers and locks; no credentials or private orders; no shadow promotion without official samples, net profitability, paired superiority, acceptable drawdown and three qualifying evaluations.

- [x] Add tested shared assessment: exact ticker/side, fresh reference, validated probability, exact fee-aware LOCK economics, explicit blocked-paper action, separate SCALP evidence requirement.
- [x] Correct confidence corroboration for overlapping price families, retaining every specialist and contribution evidence gates. Label confidence as a heuristic signal score and isolate changed-formula calibration cohorts.
- [x] Add prospective, non-executing SCALP bid-path research; freeze entry/target/stop before outcomes, retain official settlement separately, disclose sampling/censoring and never equate terminal probability with early-exit probability.
- [x] Wire assessment into worker, paper engine and dashboard; show outlook, paper action, economics, input availability and revision-specific evidence. Mark unavailable futures explicitly instead of neutral numeric evidence.
- [ ] Run focused red/green tests, full offline suite, compile checks and diff review. Commit/push main if clean; verify hosted regression and fresh revision-stamped worker publication. Inspect deployed public UI; retain the authenticated-dashboard limitation.

Review focus: immutable opposite-side LOCKs; stale/mismatched evidence; unavailable feeds; expired/censored SCALP paths; unsupported legacy inputs must not acquire execution authority. No historical ledger or accuracy rewriting.
