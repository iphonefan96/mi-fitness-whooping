# Active plan: usable analytics baseline

Updated: 2026-10-07 on `feature/sleep-core-v1`. This plan records the local target-runtime integration after `a17250615ac1c09997f978765bffd819656da1c1`; it does not prescribe a new metric or a production scheduler switch. The detailed behavior contract for the three migrated Sleep metrics remains `docs/features/sleep-core-v1.md`.

## Goal and current result

The local `./mi-fitness-whooping run|day|history` path exposes existing Mi Fitness sleep, Recovery, available vitals, stress and activity behavior without a Legacy runtime import. The installed ETL still creates `health.sqlite`; its wrapper and LaunchAgent have not changed. The target runner reads that source, builds the same nightly/daily features, loads profile v1, computes existing metrics, writes schema-v3 results and serves a dated JSON response. Sleep Score, Need and Debt use target Sleep Core and active-night reader; the other baseline calculations are behavior-preserving ports. No HRV or new formula is invented.

The runner owns one analytics lock and transaction. `TargetSleepStore` accepts that existing session, so Sleep results commit or roll back with features, other results and state. Its standalone session remains for isolated tests. Pure calculations do not read SQLite or the clock. `day`/`history` remain read-only presentations of active selections and stored freshness.

## Verification completed in this task

- Synthetic Legacy differential scenarios cover normal days, a missing calendar date, incomplete stages, an effective-dated target, unchanged repeat, historical correction, removed current night and a forced mid-run failure. Feature rows, result rows, active selections and full dated/history responses are compared, excluding only operational timestamps and run UUIDs.
- A target-only subprocess runs with `src/` as the sole project import root; no `analytics` Legacy package is loaded.
- Independent Legacy and target runs on two disposable copies of an external analytics database produced matching run summaries, 4,000 feature rows, 98,473 result rows, both active-selection tables, a dated answer and seven-day history. A repeat returned `NO NEW ANALYTICS INPUT`. No personal values were emitted.
- The switched local CLI was rehearsed on fresh disposable copies: `run`, repeat, `day` and `history` passed without Legacy on its import path. Both copied databases passed integrity checks; the source-copy hash was unchanged and read-only responses did not change the analytics-copy hash.

## Next necessary boundary

The current handoff branch, accepted base and next writer are recorded only in `docs/WORKBOARD.md`. A receiving agent reviews the previous branch's exact HEAD before continuing this boundary.

Keep the local target command available. Before changing the installed analytics job, verify its intended profile and database paths, compare its complete output/operational status contract, and review deployment/rollback with the installed ETL and LaunchAgent. This is a deployment decision, not a request to add metrics, rebuild ingestion or rewrite the runner again. Existing old-correction limits and optional product work stay in `BACKLOG.md`.

The source copy used for rehearsal was set to DELETE journal mode after SQLite backup so sidecar creation did not trip the source fingerprint guard. Read-only backup can update live `-shm` metadata; no live main database or personal values were changed or added to Git.
