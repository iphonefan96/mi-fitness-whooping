# Current State

Last verified: 2026-10-07, installed-job compatibility check on top of accepted base `a9e7f9955a7cf03ce1235559e27106ede8205a8e`. The installed macOS ETL and LaunchAgent were not changed.

## What runs locally

`./mi-fitness-whooping run` now executes entirely through `mi_fitness_whooping`; the launcher needs only `src/` on its Python path. It does not import, call or spawn the Legacy runner. The target path is: external `health.sqlite` → read-only Xiaomi source adapter → nightly/daily feature builder → selected schema-v3 features → existing foundation, recovery and monitoring calculations plus pure target Sleep Core → target schema-v3 result writer → active selection → `day`/`history` JSON. The target runner owns the analytics `.lock`, incremental-date policy, run records, one shared feature/result/state transaction, rollback and stored freshness. `TargetSleepStore` can publish into that caller-owned session; its original single-date mode remains available to synthetic tests. Calculations do not own SQLite, CLI formatting or wall-clock freshness.

`day` and `history` still read the existing analytics database without migration or writes. The selected daily feature presents vendor activity and stress observations; these are not new derived metrics. Missing dates, calculation statuses and stored freshness are explicit. No new metric or formula was introduced. Sleep Score, fixed-target Sleep Need and 14-night Sleep Debt use the target Sleep Core and active-night reader. Recovery, vitals, activity/foundation and monitoring behavior was ported from Legacy with the same names, versions, profile gates and metadata.

`Legacy/` remains immutable and serves as the independent test reference. Its analytics CLI remains available separately, but the local target command has no runtime dependency on it. The installed incremental `Legacy/mi_fitness_etl.py` still prepares `health.sqlite`; the reconciliation candidate has not replaced it. The installed analytics job/LaunchAgent has not been switched to this local command.

## Persistent contracts

The existing `health.sqlite` source schema, analytics SQLite schema v3, profile JSON v1, metric/result identity, active feature/result selection and file locations remain unchanged. Target feature storage and target result storage write the same revisioned tables. Real source exports, health/analytics databases, populated profiles and generated reports stay outside Git. Xiaomi HRV is unavailable; distance remains withheld because its source unit is unverified. SpO₂ is optical oxygen saturation, not a blood test.

## Verification

Synthetic differential tests compare target and Legacy across first run, unchanged rerun, missing date, incomplete stages, configured effective sleep target, historical correction and removed current night. They compare complete feature/result rows and active selections, excluding only operational timestamps and run UUIDs. They also cover an algorithm-version rerun with a removed night, where Sleep Core cleanup now follows the runner's `metric_force_full` gate like every other metric, and a target run continuing a Legacy-produced analytics database. A forced second result-write failure proves feature/result/selection rollback and a `FAILED` run record. A separate process imports and runs target with only `src/` on `PYTHONPATH` and no Legacy module loaded. The local launcher is also tested outside the repository without manually setting `PYTHONPATH`.

On disposable SQLite backups of the external databases, independent Legacy and target runs returned the same run summary, selected feature/result rows, active selections, dated answer and seven-day history. An unchanged repeat returned `NO NEW ANALYTICS INPUT`. A separate CLI rehearsal on fresh copies passed `run`, repeat, `day` and `history` without Legacy on the import path. Copies passed SQLite integrity checks; the source-copy hash was stable, and read commands left the analytics-copy hash stable. No personal values or copies entered Git. The source copy was changed to DELETE journal mode after backup so SQLite sidecar creation could not trip the source-file fingerprint guard. Read-only backup can update live `-shm` coordination-file metadata; the live main database files retained their metadata.

## Installed job compatibility (read-only check, 2026-10-07)

- **No scheduled analytics job is installed.** The only LaunchAgent, `com.rus.mifitness.etl`, runs `run_production_macos.sh` → `run_mi_fitness_etl.sh` → `mi_fitness_etl.py` every 6 h with `/opt/homebrew/bin/python3`; stdout/stderr go to `/dev/null`, and the wrapper tees ETL output into `~/Library/Application Support/MiFitnessETL/logs`. The installed plist and three scripts are byte-identical to `Legacy/`. Analytics is run manually through Legacy `python -m analytics`.
- **Paths:** Legacy analytics defaults `--source` to `~/Library/Application Support/MiFitnessETL/data/health.sqlite` and `--db` to `/Users/rus/Documents/temp/mi_fitness_analytics/analytics.sqlite`. Target `run` has no defaults and requires both flags. Both use `<db>.lock` with the same `flock`, so they exclude each other on one database.
- **Database continuity, both directions (synthetic):** target continuing a Legacy-produced database returns `NO NEW ANALYTICS INPUT` and then matches Legacy after a correction. Legacy `run` on a target-produced database returns `NO NEW ANALYTICS INPUT`, and Legacy `status` reads it as `READY` with zero sanity warnings, so rollback to Legacy needs no migration.
- **Profile:** the same profile v1 loader, optional `--profile`, built-in defaults when omitted.
- **CLI output:** Legacy `run` prints only the run summary; target `run` prints `{"run": summary, "day": selected day}`. Target has `run`/`day`/`history`; Legacy also has `init`, `validate` and `status` (query-time freshness headlines, sanity counts, last run), which target does not provide. Missing source is `SKIPPED` with exit 0 in both. Fixed: target `run` now reports environmental `OSError`s (e.g. unwritable destination) as JSON `FAILED` with exit 1, like Legacy, instead of a traceback.
- **Interpreter:** target needs Python ≥ 3.11 (`enum.StrEnum`). The launcher calls `python3` from `PATH`; under a launchd-style minimal `PATH` this is `/usr/bin/python3` 3.9.6 and the import fails. A scheduled job must pin a ≥ 3.11 interpreter, as the installed ETL already does.

## Remaining risks and work

- Decision 2026-10-08: the baseline runs analytics manually with `./mi-fitness-whooping run`. Scheduling is deferred to `BACKLOG.md`; the installed ETL/LaunchAgent is unchanged and runs ETL only.
- Legacy-preserved cleanup gap: a date that loses both nightly and daily features, or loses a night during an algorithm-version rerun, keeps its previous active metric selections.
- Legacy-compatible incremental discovery uses source-file fingerprint and a 48-hour overlap; arbitrary old source corrections and deletions may need separate reconciliation. The candidate reconciliation ETL is not installed.
- Stored freshness is assigned at calculation time. Historical rows can retain an old label on an unchanged rerun; the local `day`/`history` commands report stored freshness and do not replace Legacy's query-time headline policy.
- The target runner is a behavior-preserving port of the existing baseline, including its POSIX `flock` and schema-v3 assumptions. Optional refinements remain in `BACKLOG.md`.
