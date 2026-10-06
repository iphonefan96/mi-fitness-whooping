# Current State

Last verified: 2026-10-06. Repository baseline: `a0250f9` (`chore: import legacy Mi Fitness baseline`); workflow documentation: `8d93233` (`docs: add project development workflow`). These identify the state before this documentation checkpoint.

## Working in the immutable Legacy snapshot

- `Legacy/` is a read-only code snapshot, documented by `Legacy/LEGACY_EXPORT_REPORT.md`. It contains no personal source or production database.
- The production ETL remains `Legacy/mi_fitness_etl.py`, invoked by the installed macOS wrapper and LaunchAgent. It incrementally writes external `health.sqlite` and `state.json` from staged Xiaomi DB copies.
- Legacy analytics reads `health.sqlite`, builds nightly/daily features, stores revisioned results in separate external `analytics.sqlite`, and offers `init`, `validate`, `run` and `status` JSON commands.
- Implemented analytics include sleep stage duration/efficiency/regularity, Sleep Score, fixed-target Sleep Need, fourteen-night Sleep Debt, vendor and nocturnal RHR, reduced-mode Xiaomi Recovery, qualified SpO2/respiratory metrics, daily vendor stress, steps/activity/energy feature fields, baselines/trends and non-diagnostic physiological monitoring. Workouts are imported and adaptable but are not consumed by the analytics runner. Distance is stored by ETL but withheld from analytics pending unit verification. Current Xiaomi HRV is unavailable.
- Source exports, `health.sqlite`, `analytics.sqlite`, populated profiles and generated personal research outputs remain outside Git.

## Implemented but not production

`Legacy/mi_fitness_reconcile.py` is a tested reconciliation candidate. It keeps physical alternatives, conflict decisions, history and a canonical mirror in a disposable `health-rebuild.sqlite`. It has not replaced the installed incremental ETL or its scheduler. Its different source discovery and conflict handling must not be described as current production behavior.

## In progress / not implemented

This checkpoint establishes documentation and the first behavior-preserving migration specification. No target `src/` package, target module boundary, migrated calculation, target integration or new presentation layer exists. No production data migration is underway.

## Current public contracts and storage

The existing ETL/analytics CLIs, profile JSON v1, source/analytics SQLite schemas, persistent filenames, typed analytics interfaces, metric names/statuses and lineage metadata are the compatibility surface. `docs/features/sleep-core-v1.md` identifies the first migration's locked subset. Schemas remain inline in Legacy and have not been changed.

## Test status

- Standalone `Legacy/test_incremental.py`: **5/5 PASS** on synthetic temporary SQLite data.
- `unittest` reconciliation plus five analytics modules: **62/62 PASS** on synthetic data.
- Failing: 0 in these runs. Skipped: 0 reported. No personal database was required.
- The five ETL checks are a standalone script and are not included in the 62 unittest count.

## Known problems and risks

- ETL, orchestration and CLI mix multiple concerns; storage imports algorithm-specific result dataclasses; monitoring consumes foundation metric drafts.
- Production and candidate reconciliation semantics differ. Production per-DB overlap does not establish complete detection of arbitrary old corrections.
- Source/change and freshness handling spans several layers; full CLI output compatibility and installed scheduling are not comprehensively characterized by automated tests.
- Absolute paths and macOS/POSIX assumptions remain in Legacy deployment files. The snapshot has no real-data fixtures or package manifest.

## Next architectural boundary

The first proposed migration is the source-independent **sleep core**: `sleep.score`, `sleep.need_min`, `sleep.debt_min` and only their required typed nightly/history inputs. The next authorized work, after this documentation checkpoint, is Phase 1 characterization/contract testing. It must precede implementation and must preserve the current formulas and outputs. See `docs/features/sleep-core-v1.md` and `docs/plans/active/sleep-core-v1.md`.

Update this file when a substantial feature completes, public behavior changes, architecture changes materially or an audit finds drift. Proposed boundaries in `ARCHITECTURE.md` must not be reported here as implemented until they exist.
