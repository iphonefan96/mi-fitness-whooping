# Active plan: usable analytics baseline

Updated: 2026-10-07. This plan supersedes the earlier rolling-wave Sleep-only migration schedule. The previous phases remain visible in Git history and the Sleep feature specification; they are not a queue of mandatory next tasks. Current branch: `feature/sleep-core-v1`; baseline implementation commit: `787c8eee22cdf415d6be078e104c961160df4906`.

## Goal

Make the existing Mi Fitness data useful through a small, local, WHOOP-like analytics path. Reuse and cleanly adapt **existing Legacy calculations** for sleep, Recovery and the supported heart-rate/RHR, SpO2, respiratory, stress and activity outputs. First make a date and history result usable; additional sleep features come later. SpO2 is oxygen saturation, not laboratory blood analysis. Xiaomi HRV is unavailable, so do not invent it.

Do not start a new algorithm, UI, device adapter, schema or general framework for this baseline. Preserve current formulas and observable statuses/metadata unless a separate behavior change is explicitly approved. List optional ideas and technical debt in `BACKLOG.md`.

## What exists now

- Production ETL, analytics runner and JSON CLI are still in immutable `Legacy/`; they operate on external `health.sqlite`, `analytics.sqlite` and profile v1. The installed pipeline has not switched to the target package.
- Legacy already builds nightly/daily features and calculates Sleep Score, fixed-target Sleep Need, 14-night Sleep Debt, reduced-mode Recovery, foundation/vitals/activity signals and monitoring outputs. Some fields are source-only or withheld: verify their actual availability before promising them in a result.
- The target package has pure Sleep Core, a synthetic Sleep orchestrator, target schema-v3 result storage and `SqliteActiveNightReader`. The reader follows `active_features.feature_id` for day−14…day; synthetic full-row comparisons of all three Sleep results with Legacy passed. It does not build features or run production.
- The last reported audit at `2999c21` returned **GO** for the implemented reader. Its one non-blocking test gap (reselecting an old feature revision through the entire reader→Sleep→stored-results path) belongs in `BACKLOG.md`. There is no need to repeat the completed reader task.
- Target profile loading, feature building/writing, full runner transaction/lock/replay/checkpoints and other analytics are not migrated. The additive local `run|day|history` CLI uses the Legacy runner for calculation and schema-v3 selected-result reading for presentation. `TargetSleepStore` still commits one date itself. Treat this as a production-integration constraint, not as a mandatory list of separate phases.

## Current checkpoint and next use

The baseline inventory and vertical path are implemented. A local launcher now runs the CLI without manual import-path setup. Synthetic tests cover the launcher, source-to-result path, selected revisions, missing days and unchanged reruns. A disposable-copy rehearsal of the external databases confirmed a successful run, no-op repeat, selected-result parity, inclusive history, a real missing date, source-copy integrity and unchanged live main-database file metadata. SQLite read-only backup updated live `-shm` coordination-file metadata. The source copy required DELETE journal mode after backup to keep the Legacy source-file fingerprint stable; this was a copy-only preparation step.

For ordinary local use, supply the existing external source and a separate schema-v3 analytics destination to `./mi-fitness-whooping run`, or use its read-only `day`/`history` commands. Keep the installed ETL and LaunchAgent untouched. The target Sleep Core remains a separate synthetic path; no target production runner is being activated. Before any scheduled or production switch, confirm the intended profile/path and independently review a copy-based full response for the user's own environment.

## Baseline acceptance

- A user can request a date and recent history and see the existing supported sleep, Recovery and available vitals/activity outputs with their units, status/quality and freshness. The report distinguishes calculated metrics, vendor values and missing inputs.
- Existing formula behavior and locked persistent/CLI contracts remain compatible, or an explicitly approved deviation is documented. An unchanged rerun does not create duplicate active results.
- Synthetic integration tests pass for the changed path. A copy-based rehearsal has passed; independent end-to-end review still precedes any production activation. Source exports and production databases are not modified by tests.
- The result and remaining limitations are understandable without reading the migration history.

## Deferred, not blocking this task

Target profile loader and full-document revision parity; general source reconciliation for old corrections, `cn`/`ru` collisions and deletions; broad runner/CLI rewrite; new sleep formulas, HRV, new devices, UI and historical revision optimization. Some may become necessary for a safe production switch; investigate that from the implemented baseline rather than pre-scheduling separate migration phases. See `BACKLOG.md`.

`docs/features/sleep-core-v1.md` remains the detailed behavior contract for the existing three Sleep metrics. ADR-001 through ADR-003 document historical decisions and do not by themselves mandate the old task order.
