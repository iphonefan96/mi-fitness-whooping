# ADR-003: Target-owned analytics result storage

Status: **Accepted for target design** (2026-10-07). This is a documentation decision. No target storage implementation, schema change, production switch or migration of personal data exists.

## Context and evidence

The Phase 4C2 Sleep-only synthetic orchestrator publishes canonical `SleepMetricResult` values through `LegacySleepStore`. Its output adapter imports Legacy `FeatureRecord` and `MetricDraft`; the bridge imports Legacy `put_result()` and uses SQL to clear obsolete selections. This is temporary migration debt. The pure Sleep calculator and orchestrator do not import Legacy storage. Evidence: `Legacy/analytics/storage/db.py`, `Legacy/analytics/normalization/core.py`, `Legacy/analytics/algorithms/foundations.py`, `Legacy/analytics/runners/runner.py`, the target Sleep contracts/adapters, and the synthetic characterization/integration tests.

### Exact current result identity and write behavior

`put_result()` fixes `source_scope="primary"` and selection channel `production`. It computes `input_fingerprint` as SHA-256 of canonical JSON over:

- `normalized_inputs`: metric name, ISO metric date, **ordered** input feature fingerprints, metadata, calculation status and value;
- profile revision, normalization version (`xiaomi-normalization-1`), algorithm ID/version, input contract version (`foundation-output-1`) and implementation version (`0.5.0`).

`canonical_hash()` recursively converts dataclasses to dictionaries, enums to values, dates/times to ISO strings, dictionaries to string-key-sorted dictionaries, tuples/lists to ordered arrays, sets to sorted arrays, and finite floats to `.17g` strings; it JSON-encodes with `ensure_ascii=False`, sorted keys and compact separators before SHA-256. The result fingerprint excludes unit, source type, upstream provenance, confidence, quality flags, feature source counts/IDs hashes, measurement bounds, source policy, freshness, run ID and wall-clock time **as direct fingerprint fields**. Some excluded information can still affect the digest if it appears inside result metadata or an input feature fingerprint. The feature fingerprint itself is supplied by feature preparation; result storage does not recalculate it.

The `derived_metric_results` uniqueness key is `(metric_date, metric_name, algorithm_id, algorithm_version, implementation_version, normalization_version, source_scope, profile_revision, source_policy_version, input_fingerprint)`. Thus source policy affects **candidate row identity** even though it is absent from the digest. A first write inserts a row and selects it. If the selected row has the same digest **and** stored freshness, `put_result()` returns `False` without a write; this early return also means a source-policy-only change does **not** select a new row. Otherwise it attempts `INSERT OR IGNORE`, selects the row by the uniqueness key, upserts `active_metric_selection` and returns `True`. If the row already exists, its original `calculated_at`, `run_id`, stored freshness, metadata and `supersedes_result_id` are retained. A freshness-only change can therefore return `True` while selecting the same row and retaining its old freshness label. `True` means the writer took the write/reselection path, not necessarily that a new row was inserted or the selected ID changed.

For a newly inserted row, `supersedes_result_id` is the currently selected result ID, or null on first insert. Historical rows are retained. A correction or profile revision may insert a new row and point selection to it; reselecting an older identical row does not rewrite that row's original supersession link. Selection is keyed by metric name, date, source scope and release channel; the current writer uses `primary`/`production`.

The row also records value/unit/status, source type, algorithm/upstream identity, versions, quality-gate version `foundation-gates-1`, source signals, input coverage, confidence, unioned sorted quality flags, min/max measurement bounds, null `source_updated_at`, calculation timestamp, sorted-key metadata JSON and run ID. `source_signals_json` contains a lineage digest of ordered `(kind, ISO date, source_ids_hash)` triples, sorted feature kinds, min/max feature dates and count. `input_coverage_json` contains feature count, summed source reads, and `history_count`/`required_history_count` from metadata. `json.dumps(..., sort_keys=True)` is used for those objects and metadata; flags use sorted JSON. These columns are consumer/persistence compatibility data even where they do not enter the input fingerprint.

`features` has its own identity: `(kind, metric_date, normalization_version, implementation_version, profile_revision, source_policy_version, input_fingerprint)`. `put_feature()` returns `False` when the active feature has the same tuple, otherwise inserts or reselects a historical row and updates `active_features`. `active_feature_records()` reconstructs Legacy records from the selected rows. Active feature deletion removes only the selection. Feature creation/fingerprinting and source normalization remain outside the first result-storage slice.

### Current replay and transaction behavior

The Legacy runner commits a `RUNNING` run record, then opens one `BEGIN IMMEDIATE` transaction for feature changes, all metric writes/selections, replay state and success accounting. On an exception it rolls that transaction back and separately updates the run record to `FAILED`. Its exclusive file lock covers the run. On incremental replay it deletes production active metric selections for names no longer produced on a recalculated date; on full metric replay (`metric_force_full`) it skips that cleanup. A disappeared current night thus clears active Sleep selections incrementally but leaves them selected in a full replay. Historical result rows are not deleted. The 4C2 bridge instead owns only an isolated one-date transaction and rejects an already-open caller transaction. It is not a replacement for the runner's transaction or lock.

### Contract classification for the first compatible writer

| LOCKED BEHAVIOR | LEGACY IMPLEMENTATION DETAIL NOT CARRIED FORWARD |
|---|---|
| Existing schema v3 rows/uniqueness and current result/selection fields; stable digest for the same semantic inputs; ordered lineage; profile and version sensitivity; `primary`/`production` selection behavior. | The `FeatureRecord`/`MetricDraft` Python classes, their module paths and mutable dictionary constructors. |
| First insert, unchanged fast path, historical-row retention, exact reselection and supersession behavior, including the source-policy-only and freshness-only cases above. | Direct SQL inside the current runner, `INSERT OR IGNORE` and `ON CONFLICT` as specific SQL syntax, provided observable outcomes match. |
| Incremental cleanup versus full-replay retention; no-night absence; rollback of partial metric/feature changes; committed run failure record; supplied stored freshness and separate query-time freshness. | Sleep-only bridge's `with db` one-date transaction and its rejection of caller transactions; the future repository instead participates in a caller-owned session. |
| Consumer-visible metadata/provenance columns, JSON content, source-signal/coverage content, integer result IDs and active-selection keys. | Local helper names, internal object construction order, and use of Legacy `canonical_hash()`/`input_fingerprint()` at runtime. |

The current runner's cleanup SQL omits `source_scope` and deletes production selections by date/name/channel across scopes. The first compatible writer must characterize this scope effect before choosing a narrower deletion; it must not silently change observable selections. Internal SQL statements may differ if database state and return semantics stay equivalent.

## Decision

1. `mi_fitness_whooping.storage` will own result fingerprint calculation, compatible row identity, revision insertion/reselection, supersession, active selection/clearing and SQLite serialization. Pure domain/analytics will own none of these. The target storage contract consumes canonical metric results plus ordered, validated feature lineage and explicit persistence context; it does not accept Legacy `MetricDraft` or import Legacy storage. Keep the contract narrow for the three Sleep metrics, while choosing names and shapes that can later serve other analytics without coupling to Sleep internals.
2. The first implementation will write **the existing analytics SQLite schema v3 compatibly**. This preserves personal history, current readers and rollback by reverting the target writer without converting the database. It may open the existing database only after synthetic differential tests establish exact row/selection compatibility. No new schema or in-place data rewrite is authorized by this ADR. A later schema change requires a separate migration decision, backup/rollback design and consumer review.
3. A target-owned, explicitly versioned fingerprint function will reproduce the exact current canonicalization and digest during compatibility mode without importing Legacy at runtime. Its version constants and input contract are explicit inputs/configuration, not inferred from a `MetricDraft` class. The first implementation must compare digests and persisted rows against Legacy on synthetic fixtures, including metadata ordering, floats, profile revision, source policy and freshness-only reselection. Any later digest change requires a new versioned contract and migration policy.
4. The future outer analytics runner will acquire the run lock and own a transaction/session encompassing feature, metric, selection, state and success-record changes. Repository operations use that session and do not commit independently. The `RUNNING` record is committed before the data transaction; after rollback, failure status is committed separately, preserving current observable behavior. Nested transaction ownership must be explicit; the first target repository should reject implicit nesting. The 4C2 one-date bridge remains isolated until this composition exists.
5. The outer runner determines replay mode and supplies an explicit selection-cleanup policy. The repository executes the requested clear operation; it does not infer replay mode from Sleep data. Compatibility mode preserves incremental clearing and full-replay retention, including the observed oddity when a night disappears. A later behavior change needs a separate feature and tests. Stored freshness is supplied by orchestration; query-time freshness remains presentation/query-service responsibility under ADR-001.

## Proposed minimum contracts (design only)

| Concept | Proposed responsibility | Owner |
|---|---|---|
| `StoredFeatureRef` or equivalent | Ordered selected-feature identity: kind/date, feature fingerprint, source count and IDs hash, measurement bounds, quality flags. Allows lineage validation and source-signal construction without carrying an algorithm-specific Legacy object. A database feature ID may be an adapter detail. | Canonical history/lineage contract supplied to storage |
| `PersistableMetricResult` or equivalent | Canonical metric result plus its ordered feature refs and serializable metadata. For Sleep, derive it from existing `SleepMetricResult`/`NightReference`; do not add a second calculator result model without need. | Domain result and a thin storage-facing projection |
| `ResultWriteContext` | Profile revision, source policy, stored freshness, run ID, version constants and `primary`/`production` selection scope for compatibility. Date and algorithm identity come from the result. | Outer orchestration supplies; storage validates/uses |
| `ResultIdentity` | Digest plus the full database uniqueness tuple; distinguish fingerprint from row identity and from integer `result_id`. | Storage |
| `MetricResultRepository` | Store/reselect one result, read its active selection and clear a specified active selection within a caller-owned session. Return a compatibility-relevant write outcome; do not promise `True` means a new row. | Storage |
| `AnalyticsSession` | Explicit transaction context shared by feature/metric/state writes; commit or rollback once at outer-runner boundary. No hidden per-result commit. | Storage mechanism, lifetime owned by outer orchestration |

These names are design vocabulary, not Python interfaces created by this ADR. Phase A should define only the minimum contracts tests can exercise. The existing `SleepResultSink` may adapt to a repository/session in a later phase without exposing SQLite to Sleep orchestration.

## Legacy type exit classification

| Legacy field | Classification and future handling |
|---|---|
| `FeatureRecord.kind`, `.day` | **KEEP IN TARGET DOMAIN** as selected feature kind/date; Sleep requires nightly references. |
| `.values` | **KEEP IN TARGET DOMAIN** only as typed canonical observations needed by calculations; extra Legacy dictionary keys are not a result-storage contract. |
| `.fingerprint` | **KEEP IN TARGET DOMAIN** as opaque lineage identity; **KEEP IN TARGET STORAGE** as selected feature fingerprint used by result identity. The feature writer owns its generation. |
| `.source_count`, `.source_ids_hash`, `.measurement_start`, `.measurement_end`, `.quality_flags` | **KEEP IN TARGET DOMAIN** as provenance/quality on a selected reference and **KEEP IN TARGET STORAGE** as inputs to stored source signals, coverage, bounds and flags. |
| `MetricDraft.name`, `.day`, `.value`, `.unit`, `.status`, `.algorithm_id`, `.algorithm_version` | **KEEP IN TARGET DOMAIN** as canonical result identity/calculation output. |
| `.source_type`, `.upstream_project`, `.upstream_commit`, `.metadata`, `.confidence` | **KEEP IN TARGET DOMAIN** as observable result provenance, quality and metadata; storage serializes them compatibly. |
| `.inputs` | **KEEP IN TARGET DOMAIN** as ordered lineage references; storage validates and uses their fingerprints and provenance fields. The `FeatureRecord` object tuple itself is **DROP AS LEGACY DETAIL**. |
| Legacy dataclass names, mutable `values`/`metadata` dictionaries and constructor/default conventions | **DROP AS LEGACY DETAIL**; target contracts may choose immutable typed representations, provided serialized behavior is preserved. |
| `run_id`, profile revision, source policy, stored freshness, replay cleanup mode | **KEEP IN ORCHESTRATION CONTEXT** as supplied decisions; storage uses the first four and executes the requested selection policy. They are not `MetricDraft` fields and do not belong in pure calculation. |

## Alternatives and consequences

| Alternative | Decision reason |
|---|---|
| New target schema now | Rejected for this first writer: it would combine persistence ownership with a personal-history migration and require dual readers/cutover. It remains possible as a later separately reviewed migration. |
| Continue to call Legacy `put_result()` permanently | Rejected: fingerprints, revisions and selection would remain owned by Legacy and block its deletion. |
| Let each Sleep publication commit itself | Rejected for the future runner: it would allow partial feature/metric updates if a later metric fails. The existing 4C2 bridge is a synthetic proof only. |
| Clear stale selections during every full replay | Deferred: changes observed Legacy behavior when a current night disappears. |

The target writer is a high-risk compatibility change even without a schema change. Phase A should define contracts and synthetic characterization/differential tests; Phase B should implement compatible SQLite writes; Phase C should switch only the synthetic Sleep path to target storage; Phase D should remove Legacy `FeatureRecord`/`MetricDraft` from that path. Production activation remains gated on full-runner transaction, locking, replay and CLI parity. Legacy deletion remains an explicit later milestone.

## Review triggers

Revisit this decision if synthetic comparison finds an unrepresented persisted field, if multiple metric families require a different shared result contract, if schema v3 cannot support required target semantics, or before any production database write/cutover. Do not treat the proposed types as already implemented.
