# Continuous paper worker — prepared, not activated

This service removes dependence on GitHub cron while preserving the existing
paper strategy and official-settlement rules. It attempts a fresh full pass
every minute; slow network calls can delay a pass. It cannot guarantee zero
outages or replay missed executable quotes.

## Proposed host

Paid always-on Linux web service, Python 3.12, one instance, persistent disk.
Render's 512 MB / $7 compute tier plus a 1 GB disk ($0.25/month) is a starting
option, subject to a memory smoke test and usage charges. Dockerfile:
`deploy/Dockerfile.worker`. Mount disk at `/var/data` and check `/healthz`.
Default activation is off. No new trading credentials are needed.

## Required cutover (not performed)

1. Obtain hosting and cost approval; provision the service and disk without
   enabling `CONTINUOUS_PAPER_ENABLED`.
2. Pause the existing GitHub learner and its watchdog's recovery dispatch.
   Wait for any in-progress writer to finish. Retain a final GitHub snapshot.
3. Copy that exact `learning_state.json`, `horizon_models.json`, and
   `historical_specialist_knowledge_v7.json` into `/var/data/btc`. Never use
   a freshly initialized state or reset the bankroll.
4. Configure the Streamlit application's shared-state reader to use the new
   HTTPS `/learning_state.json` endpoint via the optional Streamlit secret
   `continuous_worker_state_url`. Until configured, the reader uses GitHub.
   Worker-feed failures retain the cached state rather than switching writers.
   Do not run two
   independent authoritative paper ledgers. Retain the existing login guard.
5. Enable `CONTINUOUS_PAPER_ENABLED=true`. Verify two market rollovers, fresh
   timestamps, official settlement, restart recovery, and ledger reconciliation.
6. Keep GitHub for source, regression tests and offline research. Arrange
   periodic state backups and an independent external health monitor before
   declaring the service ready for unattended operation. Do not use the old
   GitHub learner as a second writer or automatic fallback.

The server publishes only the already-public learning-state document plus a
health response. It has no write API and never serves arbitrary files.

## Rollback

Stop the continuous worker first. Copy its final reconciled snapshot back to
GitHub's learning-state branch, restore the dashboard feed, then re-enable
GitHub learning and recovery. Preserve that snapshot; do not revert bankroll
or model history to the original import.
