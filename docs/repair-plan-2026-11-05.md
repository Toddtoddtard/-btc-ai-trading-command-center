# BTC Trader Busa repair implementation plan

Scope: implement the user's nine-priority request, beginning with Issue #95. Current code at main cbd723e is the baseline. Preserve all financial safeguards, specialists, trained state and ledger; paper only. Experimental prediction changes require prospective evidence before promotion.

1. Reproduce existing failures with the full offline runner. Trace learner, worker, dashboard and publication boundaries.
2. Add regression tests and a shared versioned decision snapshot: exact ticker/expiry, immutable revision and original LOCK side, current qualification, probability, reference time and decision time. Missing, stale, conflicting or WAIT snapshots cannot authorize new production entries. Existing positions retain their lifecycle.
3. Route worker entries and dashboard authoritative Outlook through that snapshot. Keep local forecasts explicitly labeled as previews. Record snapshot IDs on assessments and fills; record concrete vetoes on every return.
4. Add the requested 8-minute and 2-minute checkpoint evidence alongside 10/5/final observations. Keep frozen chronological comparisons and official-only labels.
5. Investigate worker recovery/publication, state retrieval cost, council learning and strategy economics. Apply only reproduced fixes, with regression checks. Keep unvalidated alternatives in shadow research.
6. Run focused tests, full offline tests, UI/chart smoke checks and independent whole-change review. Publish a feature PR through the GitHub connector, verify hosted CI before merge, then inspect deployment/worker identity and current official evidence.

Review focus: stale timestamps must never be renewed by retries; wrong-market results must never settle another position; changed forecasts cannot reverse an existing LOCK; ordinary directional forecasts cannot become LOCK fills; missing state must never reset balances.

Execution note: direct GitHub clone is unavailable in this environment. All 274 baseline files were retrieved through the connector and verified against their Git blob hashes. Local git is an exact source snapshot; remote publication must be based on the real main parent SHA through GitHub's Git Data API.
