# Architecture

Last verified: 2026-10-07 against the immutable `Legacy/` snapshot and synthetic tests. This document separates the **current implementation** from **proposed target boundaries**. Canonical Sleep Core contracts, a pure calculator, adapters, a Sleep-only synthetic orchestrator, target analytics result storage and an active-night reader exist under `src/mi_fitness_whooping/`. Persisted synthetic Sleep scenarios use the reader and target result writer on temporary schema-v3 databases. Production still uses Legacy; no target ingestion or replacement production runner exists. An additive basic date/history command is available.

## Current delivery priority

The immediate goal is a usable WHOOP-like baseline from existing Mi Fitness data and Legacy analytics: sleep, Recovery and supported vitals/activity values with honest quality and freshness. Preserve this document's distinction between installed Legacy and the synthetic target Sleep slice. The target-boundary table below describes possible ownership, not a checklist that must be implemented one seam at a time. The active plan now favors the smallest compatible end-to-end result; optional architecture and feature work belongs in `BACKLOG.md`. Production activation still requires a safe transaction/lock boundary and an end-to-end review.

## A. Current architecture

### Runtime data flow

Xiaomi `DataBase/**/*.db` (+ SQLite sidecars) → stable staging copy and SQLite backup → `mi_fitness_etl.py` generic/raw and normalized tables in `health.sqlite` + `state.json` → `analytics.adapters.xiaomi.XiaomiAdapter` → nightly/daily features → foundation, sleep, recovery and monitoring calculations → revisioned `analytics.sqlite` → analytics JSON CLI.

The additive `mi_fitness_whooping` basic command reuses the unchanged Legacy runner for `run` and reads selected schema-v3 results for `day`/`history`. Its read actions do not migrate or write the analytics DB. This is a usable compatibility path for existing indicators; target Sleep Core/reader remain a separate synthetic migration path.

The installed ETL is incremental. `mi_fitness_reconcile.py` is a separate, unpromoted candidate that can build `health-rebuild.sqlite` with physical alternatives, conflict selection and a change log. It is not the production import path. Research utilities read explicit input files and write reports outside the runtime path.

### Current modules and ownership

| Code | Actual responsibility and coupling |
|---|---|
| `Legacy/mi_fitness_etl.py` | Source discovery, stable snapshot, extraction, normalization, health schema, incremental state, warnings and text output. |
| `Legacy/mi_fitness_reconcile.py` | Candidate full scan, physical history, conflict policy and canonical mirror; imports ETL schema and normalization internals. |
| `Legacy/analytics/models.py`, `normalization/core.py` | Signals/provenance/quality/feature types; dates, freshness and fingerprints. |
| `Legacy/analytics/adapters/` | SQLite-to-signal mapping; `XiaomiAdapter` reads `health.sqlite` in a read transaction. |
| `Legacy/analytics/features/foundations.py` | Selects main night and builds `nightly`/`daily` features from adapter reads. |
| `Legacy/analytics/algorithms/` | Foundation metrics, sleep score/need/debt, recovery, personal bands/CUSUM/watch. |
| `Legacy/analytics/storage/db.py` | Analytics schema, migrations, feature/result revisions and active selections; imports algorithm-defined result types. |
| `Legacy/analytics/runners/runner.py` | Lock, source-change discovery, feature/metric calculation order, replay and database transaction. |
| `Legacy/analytics/__main__.py` | `init`, `validate`, `run`, `status`; also SQL reads, freshness/headline policy and JSON output. |
| Shell wrappers and plist | macOS mount check, ETL lock/logging and six-hour launchd schedule. |

### Current storage and interfaces

- External Xiaomi DBs are raw source truth and contain personal data. Production ingestion stages copies; analytics does not read them directly.
- `health.sqlite` is the ETL-owned normalized/raw mirror. Its base schema is inline in `mi_fitness_etl.py`: source/run metadata, `raw_records`/`raw_blobs`, normalized HR, SpO2, stress, activity, sleep, daily summary, workouts, vendor-derived fields and warnings. `state.json` holds incremental fingerprints and watermarks.
- The reconciliation candidate adds physical records/blobs/history, source identities, canonical selection/conflicts, provenance and change log to its separate target. The candidate's schema is not deployed as the production schema.
- `analytics.sqlite` is the runner's derived store. `analytics.storage.db` owns `analytics_runs`, `analytics_state`, profile/source revisions, `features`, `active_features`, `derived_metric_results` and `active_metric_selection` (schema version 3). The CLI's `status` path may call the migration function.
- All databases, source exports, populated profiles and generated reports contain or may reveal personal health data and stay outside Git.
- Current public surfaces include ETL and reconciliation CLIs, analytics `init|validate|run|status` JSON CLI, profile schema version 1, adapter/feature/algorithm Python entry points, metric names/statuses/metadata and persistent schemas. Compatibility classification is feature-specific; `docs/features/sleep-core-v1.md` locks the first migration's observable behavior.

### Current invariants and debt

Synthetic tests support read-only source access, ETL rollback/idempotent overlap, analytics revision selection and historical correction, and candidate reconciliation safety. Full-history real-data completeness and whole-system clock-independent determinism are not established by the snapshot.

Architectural debt: ETL and runner have multiple responsibilities; the candidate imports ETL internals; runner and CLI query SQL directly; storage imports algorithm-specific dataclasses; monitoring consumes foundation `MetricDraft` objects; machine-specific paths live in scripts/CLI. The runner stores date-at-run freshness labels, while CLI status evaluates headline freshness at query time; an unchanged-source rerun does not update stored labels. These are observations, not changes scheduled by this document.

## B. Target boundaries — Sleep Core slice exists; broader architecture remains proposed

| Boundary | Intended ownership | Inputs → outputs |
|---|---|---|
| Ingestion | Safe source discovery, snapshots, import and reconciliation policy | External Xiaomi data → canonical records/change information |
| Canonical domain | Stable signals, provenance, quality, dated feature and result contracts | Source-independent values and statuses |
| Storage | Canonical history and analytics persistence, revisions, transactions and migrations | Domain contracts ↔ external databases |
| Analytics/sleep | Sleep-only calculations from typed nightly/history input | Sleep metric results |
| Analytics/recovery-vitals | Recovery, RHR/HRV, SpO2/respiration and physiological monitoring | Vitals/recovery results |
| Analytics/activity | Activity, steps, energy, vendor stress and eventual workout analytics | Activity results |
| Orchestration | Incremental scope, ordering, replay and integration | Calls ingestion/storage/feature interfaces |
| Presentation | CLI and future UI/API formatting and freshness-aware display | Reads published results/status |
| Platform/config | Paths, profile configuration, locks, scheduling and platform adapters | Configuration/services for outer layers |

These are coarse responsibilities, not a requirement for one file per metric. `src/mi_fitness_whooping/domain/sleep/contracts.py` establishes Sleep Core's canonical input/output types; `src/mi_fitness_whooping/analytics/sleep/core.py` calculates Score, Need and Debt without runtime Legacy, storage or clock dependencies. The input adapter projects already selected feature/profile inputs, and the result projection converts canonical Sleep results to target-owned storage contracts. `src/mi_fitness_whooping/orchestration/sleep.py` coordinates one already-loaded date with explicit run context and a canonical-result sink, without SQL, Legacy imports, formulas or clock reads. `integration/sleep/target_persistence.py` now validates original active-feature lineage, opens a target-owned one-date session, publishes through the target repository and applies caller-supplied incremental cleanup policy. It imports no Legacy storage or SQLite. Tests prove synthetic behavior, not production activation. All other boundaries in the table remain proposed.

**Target result storage and selected-night reading are compatibility-tested only in the synthetic Sleep path.** `src/mi_fitness_whooping/storage/contracts.py` defines selected-feature lineage, `SelectedSleepFeature`, an active-night reader protocol, result/write context and repository/session protocols. `storage/fingerprint.py` owns the result digest; `storage/sqlite.py` implements the schema-v3 result repository, explicit session and `SqliteActiveNightReader`. The reader joins `active_features.feature_id` to `features` for `nightly` rows in day−14…day, projects only seven Sleep observations and stored lineage, and does not choose a feature revision, commit, create or migrate a schema. The result writer and sink retain their Phase C behavior. Synthetic tests compare selected nights and every persisted Sleep result/selection column with Legacy, including corrected and missing nights. The test-only old `MetricDraft` mapping remains under `tests/integration/`; production remains Legacy. A future outer runner still must own global transaction lifetime, lock, replay policy and run-record lifecycle. See ADR-003; no schema or production wiring changed.

### Target dependency direction

```text
presentation ───────────────┐
platform/config ────────────┤
orchestration ───────────────┼──> canonical domain contracts
ingestion ──────────────────┤
storage ────────────────────┤
analytics/sleep ────────────┤
analytics/recovery-vitals ──┤
analytics/activity ─────────┘

orchestration --> ingestion, storage and analytics interfaces
presentation --> published result/query interfaces
ingestion/storage --> external source or persistent databases
```

The arrows denote allowed knowledge of contracts: **analytics/sleep imports canonical-domain contracts**, while the canonical domain does not import sleep calculations. The input adapter accepts target selected-night values or Legacy test fixtures through the same structural interface; profile data in synthetic scenarios still comes from Legacy `load_profile()`. Target persistence consumes `SleepMetricResult` and `StoredFeatureRef`, not `MetricDraft`; pure Sleep/storage runtime has no Legacy imports. The outer basic `run` command lazily imports the Legacy runner as an explicit compatibility dependency. Test-only Legacy types/functions remain reference or fixture dependencies. Presentation still owns query-time status; the basic command reports stored freshness without replacing the deployed CLI. Independent analytics features may share canonical input contracts, but should not import one another's implementation-specific result types.

**The migrated Sleep slice is synthetic only:** Legacy remains `analytics`, while target code is the distinct `mi_fitness_whooping` package. A clean subprocess imports both in either source-root order; `PYTHONPATH=src:Legacy` is the current command/test source-root configuration. The Sleep-only orchestrator accepts active nights/profile and explicit run context; its target sink writes atomically and applies the characterized incremental-versus-full-replay cleanup distinction. The Legacy runner still imports its own sleep calculation directly and is immutable. The additive basic command is not a replacement production runner/CLI; there is no target installer or lock. Any production activation requires verified runner/CLI compatibility and a safe transaction boundary; a separately named 4C3 phase is no longer a mandatory planning step. See ADR-002, ADR-003 and `docs/plans/active/sleep-core-v1.md`.

Forbidden target dependencies:

- Analytics → CLI, UI, API or presentation formatting.
- Pure analytics → direct SQLite access or platform paths.
- One feature → another feature's private calculation or `MetricDraft` implementation.
- Storage → algorithm implementation types where a canonical result contract suffices.
- Target storage → Legacy `FeatureRecord`, `MetricDraft`, `put_result()` or fingerprint helpers. The test-only reference adapter is outside the target runtime package.
- Canonical domain → ingestion, storage, presentation or platform code.
- Pure analytics → wall-clock freshness policy. Freshness ownership is decided in `docs/adr/ADR-001-freshness-ownership.md`; Legacy does not yet realize this separation completely.

An orchestrator may know feature interfaces and ordering. It should not alter formulas to satisfy a storage or presentation concern.

### Selected Sleep input boundary: reader implemented; profile and runner remain proposed

The target Sleep/storage modules have no runtime Legacy imports; the new basic outer command has a lazy Legacy runner import. Persisted synthetic target callers now obtain selected nights from `SqliteActiveNightReader`; their Legacy branch calls `active_feature_records()` only as an oracle. Older adapter/characterization tests still use `FeatureRecord` fixtures. Synthetic profile input still uses Legacy `load_profile()`. Production source ingestion, nightly/daily feature building and writes, dirty-date replay, state/checkpoints, run records, lock, shared transaction, other metrics and the deployed CLI remain Legacy-owned. Target result persistence uses neither `MetricDraft` nor `put_result()`.

The implemented reader uses existing schema-v3 `active_features` joined by `feature_id` to `features`, scoped to `nightly` and **day−14 through day inclusive**. A missing selected date remains absent, even if historical feature rows exist. `SelectedSleepFeature` pairs the stored `StoredFeatureRef` with only seven raw Sleep fields; its structural view feeds the unchanged adapter, which forms `SelectedNight`/`SleepCoreInput`. The reader receives the caller's `AnalyticsSession`, sees uncommitted selected rows in it and does not commit. SQLite stays in storage; canonical domain and pure analytics import no storage. It neither recalculates feature identity nor chooses a Xiaomi session. The current synthetic sink still opens a separate one-date result session after the read session completes.

If profile loading is later moved into the target package, file parsing belongs to platform/config, full-document v1 revision hashing to its loader, effective `sleep_target_min` resolution to a profile service at the Sleep input boundary, and the resolved `EffectiveSleepTarget` ledger to the canonical Sleep input. The loader must preserve the current v1 validation/default-path semantics and hash the **whole loaded document**, including tolerated extra content: unrelated profile fields also change result identity through `profile_revision`. Resolution preserves inclusive intervals, the 480.0-minute fallback and the 300–720-minute calculation gate. The runner supplies one loaded snapshot/revision for a run; pure Sleep does not parse the file. No target profile loader/service exists yet.

The future runner owns date selection, global `.lock`, the outer session/transaction, selected feature/profile acquisition, run/source/freshness context, replay mode, checkpoints and run records, then commits or rolls back. Sleep orchestration owns the feature-specific calculation and publication inside that session; storage executes requested reads/writes/clears without deciding replay. The current `run_sleep_day()` is otherwise a suitable single-date coordinator, but `TargetSleepStore` **opens and commits its own one-date session** and therefore cannot join the future outer transaction as-is. A separate integration change is required before production. The runner's `RUNNING` record currently commits before the data transaction; success/state are committed with data, while failure is marked after rollback. This lifecycle and incremental missing-night clearing versus full-replay retention must remain compatible.

## Architectural guards and change rule

Future phases should add tests for source read-only behavior, schema/output compatibility, import direction, deterministic metric examples, rerun/replay safety and privacy of test fixtures. They are proposed guards, not tests already present. Material changes to boundaries, storage ownership or public interfaces require an update here and a reconciliation against feature specifications. `Legacy/` remains immutable throughout migration.
