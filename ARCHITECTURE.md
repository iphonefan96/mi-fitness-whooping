# Architecture

Last verified: 2026-10-07 against the immutable `Legacy/` snapshot and synthetic tests. This document separates the **current implementation** from **proposed target boundaries**. Canonical Sleep Core contracts, a pure calculator, input/output adapters, a Sleep-only synthetic orchestrator and target storage **contracts only** exist under `src/mi_fitness_whooping/`. No target ingestion, database writer, production runner or presentation implementation exists.

## A. Current architecture

### Runtime data flow

Xiaomi `DataBase/**/*.db` (+ SQLite sidecars) → stable staging copy and SQLite backup → `mi_fitness_etl.py` generic/raw and normalized tables in `health.sqlite` + `state.json` → `analytics.adapters.xiaomi.XiaomiAdapter` → nightly/daily features → foundation, sleep, recovery and monitoring calculations → revisioned `analytics.sqlite` → analytics JSON CLI.

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

These are coarse responsibilities, not a requirement for one file per metric. `src/mi_fitness_whooping/domain/sleep/contracts.py` establishes Sleep Core's canonical input/output types; `src/mi_fitness_whooping/analytics/sleep/core.py` calculates Score, Need and Debt without runtime Legacy, storage or clock dependencies; the input/output adapters under `src/mi_fitness_whooping/integration/sleep/` cross the current feature/result compatibility boundary. `src/mi_fitness_whooping/orchestration/sleep.py` now coordinates one already-loaded date with explicit run context and a canonical-result sink, without SQL, Legacy imports, formulas or clock reads. The temporary `integration/sleep/legacy_persistence.py` bridge adapts and writes through Legacy `put_result()`, owns a single-date transaction and reproduces incremental sleep-selection cleanup with narrow SQL. It rejects an already-open transaction; a future full runner must decide transaction composition. Tests prove synthetic behavior, not production activation. All other boundaries in the table remain proposed.

**Target analytics storage contracts exist; the writer does not.** `src/mi_fitness_whooping/storage/contracts.py` defines selected-feature lineage, a persistence-facing result, explicit write context, post-write identity/outcome, and repository/session protocols. `integration/sleep/storage_contract_adapter.py` projects canonical Sleep results into these types without Legacy imports or writes. The existing `SleepResultSink` and `LegacySleepStore` remain the active synthetic publishing path. ADR-003 specifies the future target-owned writer against existing analytics SQLite schema v3; it will own fingerprinting, row identity/revisions, supersession, active selection and clearing. The future outer runner owns shared transaction lifetime, lock, replay policy and run-record lifecycle. Phase A has added no fingerprint algorithm, SQL, schema or production wiring. See `docs/adr/ADR-003-target-analytics-storage.md`.

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

The arrows denote allowed knowledge of contracts: **analytics/sleep imports canonical-domain contracts**, while the canonical domain does not import sleep calculations. The target calculator consumes these types, and only the synthetic target orchestrator calls it. The input adapter projects already active Legacy-shaped nightly records and loaded profile values into `SleepCoreInput` without importing Legacy or storage. The output adapter resolves canonical lineage to the **original** `FeatureRecord` objects. Legacy `FeatureRecord`, `MetricDraft` and `put_result()` imports occur only in the two outer integration modules; each is **temporary migration debt**, not a permanent target dependency. The orchestrator uses a canonical-result sink and imports none of these Legacy symbols. Existing storage retains result fingerprints, revisions and active selection; presentation retains query-time status. No target module is wired into production. Independent analytics features may share canonical input contracts, but should not import one another's implementation-specific result types.

**Phases 4C1/4C2 implement only a synthetic Sleep slice:** Legacy remains `analytics`, while target code is the distinct `mi_fitness_whooping` package. A clean subprocess imports both in either source-root order; `PYTHONPATH=src:Legacy` is the explicit test source-root configuration. The Sleep-only orchestrator accepts active nights/profile and explicit run context; its compatibility sink writes atomically and applies the Legacy incremental-versus-full-replay cleanup distinction. The Legacy runner still imports its own sleep calculation directly and is immutable. There is no target production runner/CLI, installer or lock; Phase 4C3 requires separate full-runner and CLI parity before activation. See `docs/adr/ADR-002-target-package-and-integration-seam.md` and `docs/plans/active/sleep-core-v1.md`.

Forbidden target dependencies:

- Analytics → CLI, UI, API or presentation formatting.
- Pure analytics → direct SQLite access or platform paths.
- One feature → another feature's private calculation or `MetricDraft` implementation.
- Storage → algorithm implementation types where a canonical result contract suffices.
- Target storage → Legacy `FeatureRecord`, `MetricDraft`, `put_result()` or fingerprint helpers as permanent dependencies. The current integration bridge is explicitly temporary.
- Canonical domain → ingestion, storage, presentation or platform code.
- Pure analytics → wall-clock freshness policy. Freshness ownership is decided in `docs/adr/ADR-001-freshness-ownership.md`; Legacy does not yet realize this separation completely.

An orchestrator may know feature interfaces and ordering. It should not alter formulas to satisfy a storage or presentation concern.

## Architectural guards and change rule

Future phases should add tests for source read-only behavior, schema/output compatibility, import direction, deterministic metric examples, rerun/replay safety and privacy of test fixtures. They are proposed guards, not tests already present. Material changes to boundaries, storage ownership or public interfaces require an update here and a reconciliation against feature specifications. `Legacy/` remains immutable throughout migration.
