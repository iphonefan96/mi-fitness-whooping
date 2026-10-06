# Architecture

Last verified: 2026-10-06 against the immutable `Legacy/` snapshot and its synthetic tests. This document separates the **current implementation** from **proposed target boundaries**. No target package or `src/` tree exists yet.

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

## B. Proposed target boundaries — not implemented

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

These are coarse responsibilities, not a requirement for one file per metric. Ownership and interfaces must be reconciled against actual code before each implementation phase.

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

The arrows denote allowed knowledge of contracts. Concrete adapters and storage are composed by orchestration. Independent analytics features may share canonical input contracts, but should not import one another's implementation-specific result types.

Forbidden target dependencies:

- Analytics → CLI, UI, API or presentation formatting.
- Pure analytics → direct SQLite access or platform paths.
- One feature → another feature's private calculation or `MetricDraft` implementation.
- Storage → algorithm implementation types where a canonical result contract suffices.
- Canonical domain → ingestion, storage, presentation or platform code.

An orchestrator may know feature interfaces and ordering. It should not alter formulas to satisfy a storage or presentation concern.

## Architectural guards and change rule

Future phases should add tests for source read-only behavior, schema/output compatibility, import direction, deterministic metric examples, rerun/replay safety and privacy of test fixtures. They are proposed guards, not tests already present. Material changes to boundaries, storage ownership or public interfaces require an update here and a reconciliation against feature specifications. `Legacy/` remains immutable throughout migration.
