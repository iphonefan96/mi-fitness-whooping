# Current State

Last verified: 2026-10-07, after the local target-runner integration built on `a17250615ac1c09997f978765bffd819656da1c1`. The installed macOS ETL and LaunchAgent were not changed.

## What runs locally

`./mi-fitness-whooping run` now executes entirely through `mi_fitness_whooping`; the launcher needs only `src/` on its Python path. It does not import, call or spawn the Legacy runner. The target path is: external `health.sqlite` → read-only Xiaomi source adapter → nightly/daily feature builder → selected schema-v3 features → existing foundation, recovery and monitoring calculations plus pure target Sleep Core → target schema-v3 result writer → active selection → `day`/`history` JSON. The target runner owns the analytics `.lock`, incremental-date policy, run records, one shared feature/result/state transaction, rollback and stored freshness. `TargetSleepStore` can publish into that caller-owned session; its original single-date mode remains available to synthetic tests. Calculations do not own SQLite, CLI formatting or wall-clock freshness.

`day` and `history` still read the existing analytics database without migration or writes. The selected daily feature presents vendor activity and stress observations; these are not new derived metrics. Missing dates, calculation statuses and stored freshness are explicit. No new metric or formula was introduced. Sleep Score, fixed-target Sleep Need and 14-night Sleep Debt use the target Sleep Core and active-night reader. Recovery, vitals, activity/foundation and monitoring behavior was ported from Legacy with the same names, versions, profile gates and metadata.

`Legacy/` remains immutable and serves as the independent test reference. Its analytics CLI remains available separately, but the local target command has no runtime dependency on it. The installed incremental `Legacy/mi_fitness_etl.py` still prepares `health.sqlite`; the reconciliation candidate has not replaced it. The installed analytics job/LaunchAgent has not been switched to this local command.

## Persistent contracts

The existing `health.sqlite` source schema, analytics SQLite schema v3, profile JSON v1, metric/result identity, active feature/result selection and file locations remain unchanged. Target feature storage and target result storage write the same revisioned tables. Real source exports, health/analytics databases, populated profiles and generated reports stay outside Git. Xiaomi HRV is unavailable; distance remains withheld because its source unit is unverified. SpO₂ is optical oxygen saturation, not a blood test.

## Verification

Synthetic differential tests compare target and Legacy across first run, unchanged rerun, missing date, incomplete stages, configured effective sleep target, historical correction and removed current night. They compare complete feature/result rows and active selections, excluding only operational timestamps and run UUIDs. They also cover an algorithm-version rerun with a removed night, where Sleep Core cleanup now follows the runner's `metric_force_full` gate like every other metric, and a target run continuing a Legacy-produced analytics database. A forced second result-write failure proves feature/result/selection rollback and a `FAILED` run record. A separate process imports and runs target with only `src/` on `PYTHONPATH` and no Legacy module loaded. The local launcher is also tested outside the repository without manually setting `PYTHONPATH`.

On disposable SQLite backups of the external databases, independent Legacy and target runs returned the same run summary, selected feature/result rows, active selections, dated answer and seven-day history. An unchanged repeat returned `NO NEW ANALYTICS INPUT`. A separate CLI rehearsal on fresh copies passed `run`, repeat, `day` and `history` without Legacy on the import path. Copies passed SQLite integrity checks; the source-copy hash was stable, and read commands left the analytics-copy hash stable. No personal values or copies entered Git. The source copy was changed to DELETE journal mode after backup so SQLite sidecar creation could not trip the source-file fingerprint guard. Read-only backup can update live `-shm` coordination-file metadata; the live main database files retained their metadata.

## Remaining risks and work

- The installed ETL/LaunchAgent still uses its existing configuration. Switching that job requires a separate reviewed deployment decision and verification of the intended profile and paths.
- Legacy-preserved cleanup gap: a date that loses both nightly and daily features, or loses a night during an algorithm-version rerun, keeps its previous active metric selections.
- Legacy-compatible incremental discovery uses source-file fingerprint and a 48-hour overlap; arbitrary old source corrections and deletions may need separate reconciliation. The candidate reconciliation ETL is not installed.
- Stored freshness is assigned at calculation time. Historical rows can retain an old label on an unchanged rerun; the local `day`/`history` commands report stored freshness and do not replace Legacy's query-time headline policy.
- The target runner is a behavior-preserving port of the existing baseline, including its POSIX `flock` and schema-v3 assumptions. A full installed-job compatibility audit has not been done. Optional refinements remain in `BACKLOG.md`.
