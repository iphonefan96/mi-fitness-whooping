# Current State

Last verified by reported synthetic implementation/audit: 2026-10-07 at `2999c21`; production behavior was not reverified in this documentation update. Repository baseline: `a0250f9` (`chore: import legacy Mi Fitness baseline`); workflow documentation: `8d93233` (`docs: add project development workflow`); Phase 1 characterization: `ebf425b` (`test: characterize legacy sleep contracts`).

## Working in the immutable Legacy snapshot

- `Legacy/` is a read-only code snapshot, documented by `Legacy/LEGACY_EXPORT_REPORT.md`. It contains no personal source or production database.
- The production ETL remains `Legacy/mi_fitness_etl.py`, invoked by the installed macOS wrapper and LaunchAgent. It incrementally writes external `health.sqlite` and `state.json` from staged Xiaomi DB copies.
- Legacy analytics reads `health.sqlite`, builds nightly/daily features, stores revisioned results in separate external `analytics.sqlite`, and offers `init`, `validate`, `run` and `status` JSON commands.
- Implemented analytics include sleep stage duration/efficiency/regularity, Sleep Score, fixed-target Sleep Need, fourteen-night Sleep Debt, vendor and nocturnal RHR, reduced-mode Xiaomi Recovery, qualified SpO2/respiratory metrics, daily vendor stress, steps/activity/energy feature fields, baselines/trends and non-diagnostic physiological monitoring. Workouts are imported and adaptable but are not consumed by the analytics runner. Distance is stored by ETL but withheld from analytics pending unit verification. Current Xiaomi HRV is unavailable.
- Source exports, `health.sqlite`, `analytics.sqlite`, populated profiles and generated personal research outputs remain outside Git.

## Implemented but not production

An additive basic daily command now provides `run`, `day` and `history` under `python -m mi_fitness_whooping`. `run` calls the unchanged Legacy analytics runner at an outer compatibility edge, then returns selected schema-v3 results for an explicit date or the latest active night. `day` and `history` read analytics SQLite without writes or migration, preserving missing dates and stored calculation statuses/freshness. Selected daily activity/vendor-stress values are shown as feature observations, not new metrics. Synthetic end-to-end tests compare the complete selected metric set with a separate Legacy run. This is not a target Sleep Core production switch; pure Sleep/storage modules remain Legacy-free, while the basic command intentionally reuses Legacy. See `README.md` for commands and output.

`Legacy/mi_fitness_reconcile.py` is a tested reconciliation candidate. It keeps physical alternatives, conflict decisions, history and a canonical mirror in a disposable `health-rebuild.sqlite`. It has not replaced the installed incremental ETL or its scheduler. Its different source discovery and conflict handling must not be described as current production behavior.

## In progress / not implemented

Phase 1 of the first behavior-preserving migration has synthetic characterization tests outside `Legacy/`. Phase 2 provides canonical Sleep Core input/output types in `src/mi_fitness_whooping/domain/sleep/contracts.py`. Phase 3 provides pure Score, Need and Debt calculations in `src/mi_fitness_whooping/analytics/sleep/core.py`, with synthetic differential tests against Legacy. Phases 4C1/4C2 established the target package and Sleep-only orchestrator. Storage Phases A–C added target result contracts, a compatible writer and the synthetic Sleep result sink. **A target active-night reader now supplies selected schema-v3 nightly inputs to persisted synthetic Sleep scenarios.** The input adapter accepts these narrow values through its structural interface; older tests retain Legacy-shaped fixtures. The old result adapter is test reference only. No replacement production runner or target Sleep production wiring exists. No production data migration is underway.

ADR-003 defines target analytics result-storage ownership. Phase A provides contracts and a write-free Sleep projection. Phase B adds `storage/fingerprint.py` and `storage/sqlite.py`: target-owned compatible digest, schema-v3 result writes, active selection/clearing and explicit caller-owned transactions. Phase C adds `integration/sleep/target_persistence.py`, which validates selected lineage, supplies storage context, opens one Sleep-date session and publishes through the target repository. The `LegacySleepStore` and runtime Legacy `MetricDraft` output adapter have been removed from `src/`. The writer has no production activation and has not touched personal data.

`SelectedSleepFeature` and `SqliteActiveNightReader` now read only active `nightly` rows for a supplied date and its preceding 14 days through an existing analytics session. They preserve stored fingerprint/provenance and seven raw Sleep observations, omit unrelated feature fields and do not commit or build features. The synthetic Legacy branch still supplies `active_feature_records()` as a differential oracle and uses `load_profile()` for profile input. No target profile loader or feature writer exists.

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
- Target storage Phase A contracts and Sleep field mapping: **6/6 PASS** on synthetic data.
- Target storage Phase B differential writer: **5/5 PASS** with full schema-v3 row/selection comparisons.
- Target Sleep orchestration with target persistence: **7/7 PASS**, including two Phase C tests for complete-row full-path equivalence and no Legacy writer call.
- Target active-night reader: **6/6 PASS** for active/reselected revisions, bounded gaps, raw missing/zero values, provenance, same-session visibility and full-path result equivalence; the synthetic package seam now uses it on its target branch.
- Basic daily compatibility path: **4/4 PASS** with temporary synthetic source/analytics databases, including multiple nights, a missing day, incomplete stages, activity-only latest date, selected historical result and unchanged rerun. These four are additional to the previously reported 142 unittest tests.
- Failing: 0 in these runs. Skipped: 0 reported. No personal database was required.
- The five ETL checks are a standalone script. Target tests use `PYTHONPATH=src:Legacy` as a source-root configuration; the coexistence test proves neither root order controls which package is imported. The new `day`/`history` commands work with `PYTHONPATH=src` alone. A manual read-only schema-v3 response check on an existing external analytics DB succeeded; no personal values or database copies were added to Git.

## Known problems and risks

- ETL, orchestration and CLI mix multiple concerns; storage imports algorithm-specific result dataclasses; monitoring consumes foundation metric drafts.
- Production and candidate reconciliation semantics differ. Production per-DB overlap does not establish complete detection of arbitrary old corrections.
- Source/change and freshness handling spans several layers; full CLI output compatibility and installed scheduling are not comprehensively characterized by automated tests.
- Sleep-core characterization found that a stored metric can retain `FRESH` after query-time status becomes `STALE`; a freshness-only persistence call reselects the existing row without changing its label. This is recorded behavior, not an authorized policy change.
- Legacy's incremental replay removes active sleep selections when the current night disappears, while its full replay retains them; both leave historical rows. The target synthetic Sleep sink uses the same explicit cleanup mode. Its target storage session owns only a single-date transaction and cannot be nested in a caller's transaction.
- The old top-level package collision is resolved: `Legacy/analytics` and `src/mi_fitness_whooping` import together under their distinct names. Legacy runner still directly imports its old sleep function and is immutable. The target Sleep migration path is synthetic only; no replacement production runner or lock exists. The additive basic CLI reuses the Legacy runner. Target persisted synthetic Sleep callers read selected nights without Legacy; Legacy feature building/writing, profile loading and test-reference imports remain. Target result persistence has no Legacy import.
- Absolute paths and macOS/POSIX assumptions remain in Legacy deployment files. The snapshot has no real-data fixtures or package manifest.

## Current delivery priority and next task

The user changed the priority on 2026-10-07: deliver a usable baseline from existing Mi Fitness data and Legacy calculations for sleep, Recovery and available heart-rate/RHR, SpO2, respiratory, stress and activity outputs. The basic daily command now supplies that compatibility path. SpO2 is optical oxygen saturation; HRV is unavailable. No new formulas, devices or UI were added. Profile migration is not the next mandatory standalone phase.

The selected-night reader is implemented and synthetically verified. The reported independent audit at `2999c21` found no blocking defects for further work; its non-blocking full-path old-feature-reselection gap is in `BACKLOG.md`. Production still uses Legacy. The future target runner would need an outer lock and shared transaction: current `TargetSleepStore` opens/commits an isolated one-date session and cannot join it as-is. Profile loading, feature building/writing, replay/checkpoints, other metrics and CLI remain Legacy-owned. Treat these as integration constraints to resolve when needed, not as a predetermined sequence of separate phases. Do not call the synthetic slice production.

Before any production switch, use disposable database copies for a rehearsal and independently review the end-to-end result. Keep source exports and live databases untouched by automated tests. See the active plan and ADR-001 through ADR-003 for behavior and historical decisions.

Update this file when a substantial feature completes, public behavior changes, architecture changes materially or an audit finds drift. Proposed boundaries in `ARCHITECTURE.md` must not be reported here as implemented until they exist.
