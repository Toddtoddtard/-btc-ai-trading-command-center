# Kalshi LOCK edge repair implementation plan

**Spec:** `docs/superpowers/specs/2026-10-29-kalshi-lock-edge-repair-design.md`

## Global constraints

- Paper trading only; no credentials or live order path.
- Preserve SCALP, LOCK immutability, the 93-cent LOCK cap, and every specialist.
- Do not rewrite historical ledger rows or balances.
- Use official Kalshi settlement only; never BTC spot as simulated settlement.

## Task 1: Shared price-aware LOCK edge

**Files:** `tests/test_lock_expected_return.py`, `kalshi_paper_engine.py`,
`pro_trade_ticket.py`, `background_paper.py`.

1. Add tests showing that a calibrated probability with less than five points
   of net edge over a 73-cent executable ask is rejected by SQLite execution,
   the persistent worker, and the preview.
2. Run them and confirm they fail because the weak LOCK currently opens.
3. Add one shared helper/constant and use it in all three paths.
4. Prove weak-edge rejection and strong-edge acceptance.

## Task 2: Authoritative 100-market LOCK quarantine

**Files:** `tests/test_lock_expected_return.py`, `background_paper.py`,
`kalshi_paper_engine.py`.

1. Add tests for collecting, passing, and failed mature scorecards using
   distinct completed market IDs.
2. Confirm the failed mature cohort currently opens a LOCK.
3. Add the shared policy and enforce it only for new persistent LOCK fills.
4. Prove the failed call remains recorded as blocked and that SCALP is not
   disabled by this LOCK-specific quarantine.

## Task 3: Documentation and full verification

**Files:** `docs/CODE_MAP.md`, `WORK_CONTEXT.md`.

1. Document the owning helper, evidence quarantine, and limitations.
2. Run focused regression tests, `python tools/run_offline_tests.py`, compile
   checks, and repository audit commands.
3. Review the complete diff, commit, push the feature branch, run hosted CI,
   merge to `main`, and verify the public Streamlit dashboard reports the new
   build without weakening paper-only safeguards.

## Review focus

- Any execution path that can bypass the new net-edge requirement.
- Distinct-market counting versus multiple fills in one market.
- Whether a failed mature cohort accidentally disables specialists, signals,
  SCALP, existing-position settlement, or historical records.
- Fee rounding and YES/NO symmetry near the edge boundary.
