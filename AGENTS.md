# Working on BTC AI Trading Command Center

## Start with the smallest useful context

- Inspect `git status --short` and the current branch before editing. Preserve existing work; use an isolated worktree when needed. Fetch `main` before basing new changes on an old checkout.
- Read `docs/CODE_MAP.md` for the affected area. Use `python tools/code_map.py <file.py> --symbol <name>` to locate definitions and direct imports/importers from current source. Then read the relevant function and callers with `rg` and bounded file ranges.
- `WORK_CONTEXT.md` contains dated history; load the relevant section, not the whole log. Current code and active workflow entrypoints determine current behavior. Old reported metrics are not current measurements.
- Reuse evidence already collected in this session until code or source data changes. Batch independent reads. Keep tool output bounded; show summaries of large JSON or test logs.

## Make focused changes

- Reuse existing helpers and dependencies. Fix the cause in its owning module; avoid unrelated refactors, abstractions or new services.
- Keep the project free on GitHub/Streamlit and paper-only. Preserve configured strategy rules, ledger history, authentication and approval boundaries unless the user explicitly requests the relevant change.
- Distinguish official Kalshi chart prices, technical Binance candles and official settlement labels. Preserve chronology and avoid look-ahead in learning. A code test passing is not evidence of trading accuracy or profitability.
- If an entrypoint or data source changes, update the affected row in `docs/CODE_MAP.md` and the relevant architecture paragraph. The navigation command reads current files, so it needs no generated index or external API.

## Verify in proportion to the change

- For documentation, inspect the diff and verify paths/commands. Do not run trading simulations for wording edits.
- For isolated behavior fixes, reproduce the issue and run the relevant regression files first. Add a test only for a real failure mode or important contract.
- Broaden to `python tools/run_offline_tests.py` when shared decision, learning, accounting or cross-module behavior changes, or an existing CI gate requires it. Do not rerun an unchanged suite without a concrete reason.
- Keep existing CI gates intact. Report local tests separately from hosted CI and deployment verification. Poll ongoing jobs at sensible intervals and stop once the required result is known.
- Record a concise outcome: what changed, verification, remaining limitation. Never promise a token-saving percentage without a measured baseline.

These instructions guide project maintenance; they do not install third-party plugins, change the assistant provider, or expand account usage limits.
