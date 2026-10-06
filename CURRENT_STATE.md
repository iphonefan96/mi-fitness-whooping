# Current State

Last verified: 2026-10-06. Repository baseline: `a0250f9` (`chore: import legacy Mi Fitness baseline`); workflow documentation: `8d93233` (`docs: add project development workflow`); Phase 1 characterization: `ebf425b` (`test: characterize legacy sleep contracts`).

## Working in the immutable Legacy snapshot

- `Legacy/` is a read-only code snapshot, documented by `Legacy/LEGACY_EXPORT_REPORT.md`. It contains no personal source or production database.
- The production ETL remains `Legacy/mi_fitness_etl.py`, invoked by the installed macOS wrapper and LaunchAgent. It incrementally writes external `health.sqlite` and `state.json` from staged Xiaomi DB copies.
- Legacy analytics reads `health.sqlite`, builds nightly/daily features, stores revisioned results in separate external `analytics.sqlite`, and offers `init`, `validate`, `run` and `status` JSON commands.
- Implemented analytics include sleep stage duration/efficiency/regularity, Sleep Score, fixed-target Sleep Need, fourteen-night Sleep Debt, vendor and nocturnal RHR, reduced-mode Xiaomi Recovery, qualified SpO2/respiratory metrics, daily vendor stress, steps/activity/energy feature fields, baselines/trends and non-diagnostic physiological monitoring. Workouts are imported and adaptable but are not consumed by the analytics runner. Distance is stored by ETL but withheld from analytics pending unit verification. Current Xiaomi HRV is unavailable.
- Source exports, `health.sqlite`, `analytics.sqlite`, populated profiles and generated personal research outputs remain outside Git.

## Implemented but not production

`Legacy/mi_fitness_reconcile.py` is a tested reconciliation candidate. It keeps physical alternatives, conflict decisions, history and a canonical mirror in a disposable `health-rebuild.sqlite`. It has not replaced the installed incremental ETL or its scheduler. Its different source discovery and conflict handling must not be described as current production behavior.

## In progress / not implemented

Phase 1 of the first behavior-preserving migration has synthetic characterization tests outside `Legacy/`. The Phase 1 findings have been reconciled into a conceptual Sleep Core V1 input/output contract and an accepted target-architecture freshness ADR. No target `src/` package, target contract type, migrated calculation, target integration or new presentation layer exists. No production data migration is underway.

## Current public contracts and storage

The existing ETL/analytics CLIs, profile JSON v1, source/analytics SQLite schemas, persistent filenames, typed analytics interfaces, metric names/statuses and lineage metadata are the compatibility surface. `docs/features/sleep-core-v1.md` identifies the first migration's locked subset. Schemas remain inline in Legacy and have not been changed.

## Test status

- Standalone `Legacy/test_incremental.py`: **5/5 PASS** on synthetic temporary SQLite data.
- `unittest` reconciliation plus five analytics modules: **62/62 PASS** on synthetic data.
- Sleep-core characterization outside `Legacy/`: **17/17 PASS** on synthetic data.
- Failing: 0 in these runs. Skipped: 0 reported. No personal database was required.
- The five ETL checks are a standalone script and are not included in the 79 unittest tests.

## Known problems and risks

- ETL, orchestration and CLI mix multiple concerns; storage imports algorithm-specific result dataclasses; monitoring consumes foundation metric drafts.
- Production and candidate reconciliation semantics differ. Production per-DB overlap does not establish complete detection of arbitrary old corrections.
- Source/change and freshness handling spans several layers; full CLI output compatibility and installed scheduling are not comprehensively characterized by automated tests.
- Sleep-core characterization found that a stored metric can retain `FRESH` after query-time status becomes `STALE`; a freshness-only persistence call reselects the existing row without changing its label. This is recorded behavior, not an authorized policy change.
- Absolute paths and macOS/POSIX assumptions remain in Legacy deployment files. The snapshot has no real-data fixtures or package manifest.

## Next architectural boundary

The first proposed migration is the source-independent **sleep core**: `sleep.score`, `sleep.need_min`, `sleep.debt_min` and only their required typed nightly/history inputs. Phase 1 and its design reconciliation are complete. The next task, not yet started, is Phase 2 implementation of canonical input/output contract types and tests only; formulas and integration remain later phases. See `docs/features/sleep-core-v1.md`, `docs/plans/active/sleep-core-v1.md` and `docs/adr/ADR-001-freshness-ownership.md`.

Update this file when a substantial feature completes, public behavior changes, architecture changes materially or an audit finds drift. Proposed boundaries in `ARCHITECTURE.md` must not be reported here as implemented until they exist.
