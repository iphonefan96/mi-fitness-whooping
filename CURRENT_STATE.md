# Current State

Last verified: 2026-10-07. Repository baseline: `a0250f9` (`chore: import legacy Mi Fitness baseline`); workflow documentation: `8d93233` (`docs: add project development workflow`); Phase 1 characterization: `ebf425b` (`test: characterize legacy sleep contracts`).

## Working in the immutable Legacy snapshot

- `Legacy/` is a read-only code snapshot, documented by `Legacy/LEGACY_EXPORT_REPORT.md`. It contains no personal source or production database.
- The production ETL remains `Legacy/mi_fitness_etl.py`, invoked by the installed macOS wrapper and LaunchAgent. It incrementally writes external `health.sqlite` and `state.json` from staged Xiaomi DB copies.
- Legacy analytics reads `health.sqlite`, builds nightly/daily features, stores revisioned results in separate external `analytics.sqlite`, and offers `init`, `validate`, `run` and `status` JSON commands.
- Implemented analytics include sleep stage duration/efficiency/regularity, Sleep Score, fixed-target Sleep Need, fourteen-night Sleep Debt, vendor and nocturnal RHR, reduced-mode Xiaomi Recovery, qualified SpO2/respiratory metrics, daily vendor stress, steps/activity/energy feature fields, baselines/trends and non-diagnostic physiological monitoring. Workouts are imported and adaptable but are not consumed by the analytics runner. Distance is stored by ETL but withheld from analytics pending unit verification. Current Xiaomi HRV is unavailable.
- Source exports, `health.sqlite`, `analytics.sqlite`, populated profiles and generated personal research outputs remain outside Git.

## Implemented but not production

`Legacy/mi_fitness_reconcile.py` is a tested reconciliation candidate. It keeps physical alternatives, conflict decisions, history and a canonical mirror in a disposable `health-rebuild.sqlite`. It has not replaced the installed incremental ETL or its scheduler. Its different source discovery and conflict handling must not be described as current production behavior.

## In progress / not implemented

Phase 1 of the first behavior-preserving migration has synthetic characterization tests outside `Legacy/`. Phase 2 provides canonical Sleep Core input/output types in `src/mi_fitness_whooping/domain/sleep/contracts.py`. Phase 3 provides pure Score, Need and Debt calculations in `src/mi_fitness_whooping/analytics/sleep/core.py`, with synthetic differential tests against Legacy. Phase 4A/B adapters in `src/mi_fitness_whooping/integration/sleep/` convert active nightly features/profile values to canonical input and results back to the existing Legacy `MetricDraft` persistence interface. Phase 4C1 moved these modules under one distinct target package and proved the persisted synthetic path. Phase 4C2 now adds a Sleep-only orchestrator in `src/mi_fitness_whooping/orchestration/sleep.py` and a temporary Legacy storage bridge; they are exercised only on synthetic data. No production wiring, target-owned storage, full runner or presentation implementation exists. No production data migration is underway.

ADR-003 now defines the **proposed** target analytics result-storage boundary: compatible writes to the current schema, target-owned fingerprints/revisions/selections, and a caller-owned transaction session. This task created documentation only. `src/mi_fitness_whooping/storage/`, target storage contracts, a target writer and production activation do not exist.

## Current public contracts and storage

The existing ETL/analytics CLIs, profile JSON v1, source/analytics SQLite schemas, persistent filenames, typed analytics interfaces, metric names/statuses and lineage metadata are the compatibility surface. `docs/features/sleep-core-v1.md` identifies the first migration's locked subset. Schemas remain inline in Legacy and have not been changed.

## Test status

- Standalone `Legacy/test_incremental.py`: **5/5 PASS** on synthetic temporary SQLite data.
- `unittest` reconciliation plus five analytics modules: **62/62 PASS** on synthetic data.
- Sleep-core characterization outside `Legacy/`: **20/20 PASS** on synthetic data, including no-night selection and mid-run rollback.
- Canonical Sleep Core contract tests: **10/10 PASS** on synthetic domain objects.
- Pure Sleep Core differential tests: **6/6 PASS** across representative synthetic score, need, debt and lineage cases.
- Sleep Core input adapter tests: **9/9 PASS** on synthetic Legacy-shaped active features and profile values.
- Sleep Core output adapter/fingerprint/persistence compatibility tests: **7/7 PASS** on temporary synthetic analytics databases.
- Package coexistence and full synthetic storage seam: **4/4 PASS**, including both import-root orders, default/configured float targets, reruns and historical correction.
- Synthetic Sleep orchestration: **5/5 PASS**, including profile revision, no-night modes, rollback and transaction ownership.
- Failing: 0 in these runs. Skipped: 0 reported. No personal database was required.
- The five ETL checks are a standalone script and are not included in the 123 unittest tests. Target tests use `PYTHONPATH=src:Legacy` as a source-root configuration; the coexistence test proves neither root order controls which package is imported.

## Known problems and risks

- ETL, orchestration and CLI mix multiple concerns; storage imports algorithm-specific result dataclasses; monitoring consumes foundation metric drafts.
- Production and candidate reconciliation semantics differ. Production per-DB overlap does not establish complete detection of arbitrary old corrections.
- Source/change and freshness handling spans several layers; full CLI output compatibility and installed scheduling are not comprehensively characterized by automated tests.
- Sleep-core characterization found that a stored metric can retain `FRESH` after query-time status becomes `STALE`; a freshness-only persistence call reselects the existing row without changing its label. This is recorded behavior, not an authorized policy change.
- Legacy's incremental replay removes active sleep selections when the current night disappears, while its full replay retains them; both leave historical rows. The synthetic Sleep orchestrator requires an explicit cleanup mode to preserve this observed distinction. Its temporary storage bridge owns an isolated single-date transaction and cannot be nested in a caller's transaction.
- The old top-level package collision is resolved: `Legacy/analytics` and `src/mi_fitness_whooping` import together under their distinct names. Legacy runner still directly imports its old sleep function and is immutable. The 4C1/4C2 path is synthetic only; no target production runner, lock or CLI exists. `FeatureRecord`, `MetricDraft`, `put_result()` and selection-cleanup SQL in the integration bridge are temporary migration debt.
- Absolute paths and macOS/POSIX assumptions remain in Legacy deployment files. The snapshot has no real-data fixtures or package manifest.

## Next architectural boundary

The next bounded task is **Storage Phase A**: define minimum target-owned result-storage contracts and synthetic tests against the behavior documented in ADR-003. Phase B can then implement a compatible writer; only later may the synthetic Sleep path switch away from Legacy storage. Phase 4C3's production-switch review remains pending; target-owned storage, full runner, lock and CLI do not exist. Freshness changes remain separate. See `docs/features/sleep-core-v1.md`, `docs/plans/active/sleep-core-v1.md` and `docs/adr/ADR-001-freshness-ownership.md` through `ADR-003-target-analytics-storage.md`.

Update this file when a substantial feature completes, public behavior changes, architecture changes materially or an audit finds drift. Proposed boundaries in `ARCHITECTURE.md` must not be reported here as implemented until they exist.
