# Execution Plan: Sleep Core v1

Status: **Phases 1–3 and Phase 4A/B adapters complete; Phase 4C not started.** ADR-002 resolves its package/seam design, not its implementation. Feature specification: [`../../features/sleep-core-v1.md`](../../features/sleep-core-v1.md). The repository, feature specification and locked contracts outrank this provisional plan.

## Current phase

Phase 3's pure calculator consumes the Phase 2 contracts and has differential tests against the immutable Legacy oracle. Phase 4A projects active nightly records and loaded profile values into `SleepCoreInput`. Phase 4B converts results back to Legacy-compatible `MetricDraft` values and proves synthetic persistence fingerprints match. Production still uses Legacy. ADR-002 chooses the target package identity and external seam; implement and verify them in 4C1 before considering a wrapper or production wiring.

## Rolling-wave phases

1. **Characterization / contract tests.** Detailed below. Capture current values, statuses, metadata and lineage with synthetic inputs while `Legacy/` stays immutable.
2. **Canonical sleep input/output contracts.** Implement only the smallest typed nightly/history and result interfaces justified by Phase 1, with contract tests. Details below.
3. **Pure sleep calculation migration.** Reproduce score, need and debt behind those contracts. Keep formulas and quality gates unchanged.
4. **Integration behind existing orchestration/storage contracts.** Adapt current feature/history input and persist compatible result drafts without schema or CLI changes.
5. **Regression comparison against Legacy.** Compare characterized cases and relevant synthetic end-to-end runs, including reruns and historical correction.
6. **Audit.** Independently check the feature specification, dependency direction, compatibility, tests and change scope.

Completed Phases 1–3 and Phase 4A/B, plus the immediate Phase 4C boundary, are detailed. Phases 5–6 remain high-level. This plan does not schedule the whole project.

## Phase 4 integration boundary — design only

**Current path.** `XiaomiAdapter` reads the external health mirror. `build_nightly()` selects one `main` sleep session for a date, validates stage coverage, computes sleep measurements and lineage, and returns a `Feature`. `put_feature()` stores it in `features` and updates `active_features`; `active_feature_records()` reconstructs the active dated `FeatureRecord` map. The runner loads profile v1 and its revision, calculates dirty/replay dates, then passes the map and profile to `calculate_sleep_day()`. That function resolves dated targets and produces three `MetricDraft`s when a current night exists. The runner assigns stored freshness per metric date and calls `put_result()`. Storage fingerprints result content and ordered feature inputs, writes or reselects a result revision and updates `active_metric_selection`; incremental runs also remove obsolete selections. `status` reads active results and independently evaluates current sleep freshness for its JSON headline.

### Phase 4A — input adapter and tests

**Responsibility/input/output:** a compatibility adapter outside pure sleep takes `(day, nights: dict[date, FeatureRecord], loaded_profile_v1: dict, profile_revision: str)` from orchestration and returns one `SleepCoreInput`. It performs no SQLite read and no main-session selection. It includes only active nightly records from day−14 through day, sorted ascending; all raw sleep observations (`tst_min`, `deep_min`, `rem_min`, `waso_min`, awakening durations, local bedtime) keep `None`, zero and invalid values distinct. It uses exactly `stage_coverage == "COMPLETE"`; the string's other values map to `False`. Each `NightReference` copies date, feature fingerprint, source count/IDs hash, measurement interval and quality flags from the original record. The orchestrator retains the original map for output adaptation.

**Targets and errors:** if the current day has no active night, return an input with no targets and do not inspect any effective target; `load_profile()` has already validated the profile file at runner entry. Otherwise resolve the current target first, then each date day−13…day with the existing `effective_values()` semantics: absent/`None` means 480.0 minutes and default, configured values must be numeric, finite and 300–720 minutes, with the current `sleep_target_min must be within 300..720` error contract. Normalize every resolved target to `float`, matching Legacy `_target()`; `int` would compare numerically equal but could change storage's JSON fingerprint. Produce the complete ordered target ledger. Structural contract errors must surface before calculation; do not silently replace invalid configured targets. A missing active night in the ledger remains a calendar gap, not a zero night. Profile revision is carried unchanged for storage identity; the pure formula does not inspect it.

**Import constraint and design decision:** `Legacy/analytics` and `src/analytics` are regular packages with the same top-level name; `PYTHONPATH=Legacy:src` hides target `analytics.sleep`, while `PYTHONPATH=src:Legacy` hides Legacy `analytics.algorithms`. Tests currently import the target as `src.analytics.sleep.core` while Legacy owns `analytics`, which is not a durable product identity. ADR-002 chooses the future `mi_fitness_whooping` top-level package. No rename has occurred. Phase 4C1 must migrate target imports/tests together and prove normal combined imports without runtime `sys.path` tricks or modifying Legacy.

**Phase 4A result:** `src/integration/sleep/input_adapter.py` defines a structural `NightlyFeature` interface and `adapt_sleep_input(day, nights, profile, profile_revision)`. It imports only canonical sleep contracts and standard-library modules. When the current date has no active night it returns `SleepCoreInput(day, (), (), profile_revision)` before reading profile or prior-night contents, matching Legacy's early return. With a current night it resolves that day's target first, maps the bounded history in ascending date order, then resolves the complete 14-date target ledger. Target values are `float`; observations retain missing, zero and invalid values for the pure calculator's gates. The adapter creates `NightReference` values from original feature identity/quality fields and does not load source files, access SQLite, calculate metrics or create persistence IDs.

**Phase 4A verification:** nine synthetic tests in `tests/integration/test_sleep_input_adapter.py` cover current/absent nights, no-current malformed profile/history, ordered bounded history and references, stage coverage, missing versus zero, effective dates/defaults, float target representation, invalid target rejection, deterministic output and import/clock guards. They compare targets and selected observable cases with immutable Legacy code; existing tests remain unchanged. The output adapter and production wiring have not begun.

### Phase 4B — output adapter and persistence compatibility tests

**Responsibility/input/output:** take a `SleepMetricResult` plus the original active-night `FeatureRecord` map used for its input. Return a Legacy-compatible `MetricDraft` for existing `put_result()`. Map metric enum → `name`, calculation status enum → status string, and copy date, value, unit, algorithm ID/version, `OUR_DERIVED`, upstream project/commit and `MEDIUM` confidence. Convert `ScoreMetadata`/`ScoreComponents`, `NeedMetadata` and `DebtMetadata` to the exact current dictionaries, including `None` keys. Resolve each ordered `NightReference` to the original `FeatureRecord` using date and fingerprint, verify the copied lineage fields, and preserve that order in `inputs`. A mismatch fails closed; never substitute a different active revision or synthesize a feature fingerprint.

**Storage ownership:** `put_result()` remains responsible for `input_fingerprint` from metric/date, ordered feature fingerprints, metadata, status, value, profile revision and normalization/algorithm/implementation/contract versions. Its current identity context includes `NORMALIZATION_VERSION="xiaomi-normalization-1"`, `IMPLEMENTATION_VERSION="0.5.0"`, `input_contract_version="foundation-output-1"`, runner `source_policy_version="primary-v1"`, `source_scope="primary"`, `release_channel="production"` and stored `quality_gate_version="foundation-gates-1"`; migration must preserve the existing values and ownership. Storage also owns `source_signals_json` (including nightly `kind`), `input_coverage_json`, unioned flags, measurement bounds, calculation timestamp, run ID, `supersedes_result_id` and `active_metric_selection`. The output adapter does not create IDs, hashes, SQL rows or freshness labels. The runner must continue supplying `profile_revision`, `run_id`, `source_policy_version` and the existing stored `freshness_status` to `put_result()`.

**Phase 4B result:** `src/integration/sleep/output_adapter.py` imports the existing Legacy `FeatureRecord`/`MetricDraft` types solely for this compatibility boundary. `adapt_sleep_result(result, nights)` maps every direct result field, converts metric-specific metadata with `dataclasses.asdict()` (including nested Score components and explicit `None` keys), and resolves each `NightReference` to its **original active nightly `FeatureRecord` object** by date plus all copied identity/quality fields. Missing, changed or non-nightly lineage fails closed. It does not import storage, read a clock, create fingerprints, persist rows or select revisions. This narrow Legacy type dependency remains isolated outside pure analytics and canonical domain.

| Phase 4B field source | Persistence-facing fields / responsibility |
|---|---|
| **DIRECT FROM `SleepMetricResult`** | `metric.value → name`, `day`, `value`, `unit`, `status.value`, `algorithm_id`, `algorithm_version`, `source_type`, `upstream_project`, `upstream_commit`, `confidence`. No numeric or status rewriting. |
| **DERIVED BY OUTPUT ADAPTER** | `metadata = asdict(result.metadata)` with exact nested keys/types and explicit `None`; ordered `inputs` obtained by resolving each `NightReference` to the original active `FeatureRecord`, validating date, fingerprint, source count/hash, bounds and flags. No newly fabricated feature object. |
| **SUPPLIED BY ORCHESTRATION** | Original active-night map, `profile_revision`, `run_id`, `source_policy_version`, calculation-date stored `freshness_status`, metric-date replay scope and produced-name cleanup. Only the map is an argument to this adapter; the remaining values go to unchanged storage separately. |
| **SUPPLIED BY STORAGE** | `input_fingerprint`, normalization/implementation/quality-gate/input-contract versions, source scope and release channel, `source_signals_json`, `input_coverage_json`, unioned quality flags/measurement bounds, `calculated_at`, `source_updated_at`, `result_id`, `supersedes_result_id`, active metric selection and database row creation. |
| **NOT APPLICABLE TO OUTPUT ADAPTER** | Query-time freshness/headline formatting, SQLite connections/paths, main-night selection, profile parsing, formula gates and score/debt calculations. |

**Phase 4B fingerprint and persistence evidence:** seven new synthetic tests compare Legacy and adapted `MetricDraft`s for valid Score, calibration, insufficient Score, default/effective-dated Need, valid and calibrating Debt, metadata `None`/nested components, ordered original object identity and mismatched lineage. The tests call the real `put_result()` in separate temporary analytics DBs and compare the three `input_fingerprint` values, metadata/source-signal/coverage JSON, flags, measurement bounds and key result columns. Fingerprints match for all three metrics across the representative cases. Initial insert, unchanged rerun, corrected historical input, revision chain, active selection and freshness-only reselection also match. No storage function or schema was changed; these tests do not establish whole-runner or real-data equivalence.

### Phase 4C — external seam, staged and gated

ADR-002 records the package identity and external seam. The installed Legacy runner imports `calculate_sleep_day()` directly and has no sleep injection hook. The new path begins **outside immutable `Legacy/`**, after `active_feature_records()` provides the original active-night map and before the resulting drafts reach unchanged `put_result()`. Do not monkey-patch the Legacy runner, edit its files, or post-process sleep results in the production database. Keep the production runner and CLI on Legacy.

**4C1 — exact next task: package separation and synthetic seam proof.** Move only current target domain/analytics/integration modules under `src/mi_fitness_whooping/` and update their imports/tests as one bounded change. Choose minimal packaging/source-root configuration and prove a clean subprocess can import both `analytics.algorithms.foundations` from Legacy and `mi_fitness_whooping.analytics.sleep.core` from target, independent of path order. On a temporary synthetic analytics DB, seed active nightly features using existing storage; load a synthetic profile with `load_profile()`; read original nights with `active_feature_records()`; run input adapter → pure Sleep Core → output adapter → real `put_result()` with explicit fixed run ID, profile revision, source policy and stored freshness. Compare Legacy and target drafts, fingerprints, stored fields, ordered provenance, unchanged rerun, corrected-night revision and active selection. Keep no-current-night and changed-profile cases in scope where they can be proven without runner replacement. Use no personal data or production entrypoint. Re-run all 111 current unittest checks and five ETL checks. Do not alter locked contracts or schemas.

**4C2 — target orchestration wrapper, after 4C1 reconciliation.** Add a bounded external sleep caller with explicit run context and transaction ownership on synthetic data. Verify no-night obsolete-selection cleanup, profile revision, clock-controlled stored freshness, rollback and lock/error behavior. Decide how this wrapper composes with unchanged non-sleep calculations and replay before widening it. A sleep-only wrapper does not establish full runner or CLI parity.

**4C3 — production switch, separately gated.** Reconcile the entire existing runner lifecycle: source generation/checkpoints, dirty-date expansion and 90-day/CUSUM replay, feature writes, all metric ordering, lock and transaction, run records, obsolete selection, counters/errors and current CLI JSON/headline. Choose an opt-in activation and rollback only after full synthetic regression. Do not copy the whole runner blindly or change the installed ETL. No implementation detail for 4C3 is locked by this plan.

**Proof limit:** 4C1 can prove the three sleep metrics' names, statuses, units, versions, metadata, exact input fingerprints, revision chain and active selection through real storage in synthetic cases. It cannot prove production source detection, full runner counters, query-time freshness or CLI-visible output. Stored freshness is passed explicitly by the outer caller and stays outside pure calculation per ADR-001. A later feature may migrate Recovery, Monitoring or Activity into the same project package and outer seam; none is part of 4C1.

### Field ownership at this boundary

| Classification | Required fields and owner |
|---|---|
| **DOMAIN** | Date; selected-night presence; TST, deep, REM, WASO, awakening durations, local bedtime, stage completeness; dated effective target/default; `NightReference` date/fingerprint/source count/source IDs hash/measurement bounds/quality flags; metric name, value, unit, calculation status, algorithm ID/version, upstream provenance, confidence, result metadata and ordered lineage. These are represented by canonical contracts. |
| **ORCHESTRATION** | Active dated-night map and selected date/replay scope; loaded profile v1 and profile revision; no-current-night decision; invocation/order of foundation, sleep, recovery and monitoring; run ID, source-policy context and calculation-date `today` used for stored freshness; obsolete-selection cleanup. The profile revision is carried through `SleepCoreInput` for identity but does not affect the pure formula. |
| **PERSISTENCE** | Original `FeatureRecord` reference used as `MetricDraft.inputs`; `features`/`active_features`, `derived_metric_results`/`active_metric_selection`; `input_fingerprint`, normalization/implementation/quality-gate versions, source scope, release channel, source signals/coverage JSON, unioned flags and interval bounds, `calculated_at`, `source_updated_at`, result ID and superseded ID. Storage receives the runner's run ID, profile revision, source policy and stored freshness. |
| **PRESENTATION** | Query-time `current_sleep_freshness`, `sleep_headline` value visibility, `last_historical_statuses`, status counts and CLI JSON format. These read published active results and do not enter the calculator or adapters. |
| **DEFERRED / LEGACY-ONLY** | `FeatureRecord.kind="nightly"` and extra `values` fields retained in original records for compatibility; Legacy `MetricDraft` type behind the output adapter; raw Xiaomi rows, SQLite paths, profile file path, DB IDs and a redesigned freshness policy. These are not new canonical Sleep Core fields. |

### Freshness and compatibility gate

No freshness field is needed by either adapter. The runner must keep supplying stored `HISTORICAL`/`FRESH`/`STALE` to `put_result()` after calculation; the unchanged-input fast path and current `put_result()` fingerprint/reselection behavior remain as characterized. Query-time freshness and the 36-hour headline rule remain in the status/presentation path. Preserve the three metric identities, units, status strings, algorithm/version/provenance, exact nested metadata, ordered lineage, input fingerprint and active revision semantics, and CLI-visible values/status. Exact compatibility is not yet demonstrated for the production runner: the shared package name and immutable runner are integration blockers, and no real-data fixtures exist.

### Phase 4 test strategy and remaining checks

- **Unit adapter tests — implemented for 4A/B:** synthetic active `FeatureRecord` map → canonical input equality for 15-date reach, absent/current night, valid/invalid bedtime, missing/zero stages, 14 dated targets, default/effective-dated profile changes, invalid target, float target values and lineage identity; canonical result → exact `MetricDraft` equality, including nested metadata and original ordered `inputs`; reject stale or mismatched lineage. Combined package-loading path remains to be tested for 4C.
- **Integration tests — partially implemented for 4B:** temporary synthetic analytics DB comparison of Legacy and adapted drafts' `put_result()` fingerprints, stored columns, source signals/coverage, active selection and revision chain under unchanged rerun, changed historical night and freshness-only reselection. Profile-revision compatibility is still covered by Phase 1 characterization; compare it through the eventual integration path. Compare no-current-night obsolete selection behavior through the eventual orchestration seam.
- **Regression tests:** run the synthetic pipeline through old and newly wired orchestration paths and compare metric identities/statuses, counts, CLI `status` JSON/headline under fixed times, stored-vs-query freshness divergence and other existing outputs. Keep the 17 characterization, 10 contract, 6 differential, 62 Legacy unittest and 5 ETL checks unchanged.

## Completed task — SLEEP-PURE-03

**Scope:** `src/analytics/sleep/core.py` reproduces Legacy Score, fixed-target Need and signed 14-night Debt through `SleepCoreInput` → three `SleepMetricResult` values. It has no Legacy runtime import, SQLite, clock, CLI or orchestration dependency. With no current night it returns an empty tuple before reading targets.

**Verification:** `tests/analytics/test_sleep_core.py` compares observable values, statuses, units, algorithm/provenance identity, metric-specific metadata and ordered lineage with Legacy across synthetic normal, calibration, invalid and historical cases. It checks forbidden dependencies and clock reads. Existing contract and characterization suites remain unchanged.

**Reconciliation:** the existing types carry the required observations and result metadata. Effective-dated profile resolution and invalid profile rejection occur before pure calculation, as designed; Phase 4 must provide that adapter without changing profile v1 semantics. No locked behavioral contract conflict was found. The feature specification's stale Phase 2 status is corrected in this reconciliation.

## Completed task — SLEEP-CONTRACT-02

**Goal:** establish the minimal, immutable, source-independent canonical Sleep Core input/output types and their validation/identity semantics. This phase creates contracts only; it does not calculate Score, Need or Debt.

**Scope:** choose a coarse canonical-domain location; define a dated selected-night input, bounded history/target snapshot, ordered lineage reference and three-metric calculation-result contract corresponding to the conceptual tables in the feature specification. Make absent night and missing value distinct from measured zero. Represent stage completeness and fallback use explicitly. Carry only the provenance/quality fields needed to reproduce the existing stored result through a later adapter. Define validation for dates, value presence and invalid configured targets without parsing profile files or Xiaomi rows.

**Files used:** `src/domain/sleep/contracts.py` with minimal package initializers; `tests/contracts/test_sleep_contracts.py`; feature, plan, architecture and current-state documentation. No target calculator, SQLite repository, CLI, orchestration adapter or schema change in this phase.

**Locked contracts:** all Sleep Core V1 behaviors and output compatibility in the feature specification; profile v1 semantics; unchanged source/analytics schemas and CLI; immutable Legacy and Phase 1 tests. ADR-001 keeps wall-clock freshness outside pure calculation.

**Verification:** ten contract tests show that the types represent ordered source references, effective targets/fallbacks, missing versus zero, incomplete stages, statuses and provenance; reject malformed structural history/targets and impossible result status/value combinations. The lightweight dependency guard confirms the contract module imports no SQLite, CLI, clock, Xiaomi adapter, orchestration, storage or Legacy implementation. Phase 1 characterization and Legacy synthetic suites remain unchanged.

**Result:** contract semantics match `docs/features/sleep-core-v1.md`; no formulas or result persistence were migrated. The concrete types are `SleepCoreInput`, `SelectedNight`, `EffectiveSleepTarget`, `NightReference`, `SleepMetricResult`, `SleepMetric`, `CalculationStatus`, and metric-specific metadata classes. Invalid raw sleep observations remain representable for Phase 3 quality gates. No locked behavior mismatch was found.

## Completed active task — SLEEP-CHAR-01

**Goal:** establish an executable behavior baseline for `sleep.score`, `sleep.need_min` and `sleep.debt_min` before target implementation.

**Scope:** add non-personal characterization/contract tests outside `Legacy/`. Import or invoke frozen Legacy code as the oracle without changing it. Capture exact output fields that consumers/persistence depend on, not merely formula totals. A fixture helper may construct dated `FeatureRecord` values; avoid a production module or new schema.

**Cases to pin:**

- No current night and a valid complete night.
- Four versus five valid prior bedtimes within the preceding 14 dates; bedtime/score component boundaries, score rounding, complete versus incomplete stages and absent/invalid component inputs. Record `VALID`, `CALIBRATING`, `INSUFFICIENT_DATA` and reachable `INVALID` behavior.
- Configured effective-dated targets versus 480-minute fallback, valid target bounds and invalid target rejection; preserve `REDUCED`/`VALID` need status and `physiological_estimate: false`.
- Debt ledger over 14 calendar dates: 9 versus 10 valid staged nights; longest missing run of two versus three; measured zero versus missing; signed balance, nonnegative displayed debt, repayment and profile target changes.
- Exact metric names, units, algorithm IDs/version, upstream provenance where present, metadata keys/values, and `MetricDraft.inputs` identities/order relevant to persistence fingerprints.
- Where practical, a synthetic runner/storage example for unchanged rerun and one historical correction, without reading external personal DBs.

**Files used:** `tests/characterization/test_legacy_sleep_core.py` outside `Legacy/`. This plan does not prescribe a target package layout.

**Contracts affected:** tests characterize existing behavior; no production public interface changes. **Locked:** Legacy code, database schemas, CLI/output, profile v1 semantics, the three metric names/statuses/metadata and existing formulas.

**Verification result:** 17 characterization tests, 62 existing unittest tests and the standalone 5 ETL checks passed with bytecode writing disabled. Fixtures are synthetic; `Legacy/` remains unchanged and no target implementation appeared. Captured expectations were compared with `Legacy/analytics/algorithms/sleep.py` and `docs/features/sleep-core-v1.md`.

**Result:** 17 passing Legacy-backed tests pin the existing behavior. The feature specification now distinguishes missing bedtime from missing stage values and records the stored-versus-query-time freshness discrepancy. No target implementation exists. Do not weaken these tests to match a future implementation.

## Completed tasks

- [x] Factual Legacy architectural inventory completed in the preceding design task.
- [x] Project, architecture, current-state, feature and rolling-wave plan documentation established in this documentation checkpoint.
- [x] SLEEP-CHAR-01 characterization and contract tests, with synthetic inputs and immutable Legacy oracle.

## Remaining tasks

- [x] Reconcile Phase 1 findings, settle the conceptual domain boundary and record freshness ownership in ADR-001.
- [x] SLEEP-CONTRACT-02: Phase 2 canonical contract types and tests only.
- [x] Reconcile Phase 2 evidence and implement SLEEP-PURE-03 against the canonical contracts.
- [x] Reconcile Phase 3 evidence and define the Phase 4 adapter boundary.
- [x] Phase 4A input adapter and tests; stable combined import-path choice deferred by explicit Phase 4A scope.
- [x] Phase 4B output adapter and synthetic persistence compatibility tests.
- [ ] Phase 4C1 package separation and synthetic seam proof per ADR-002; then reconcile 4C2 wrapper scope.
- [ ] Phase 4C2 synthetic orchestration wrapper and separately gated 4C3 production switch.
- [ ] Phases 5–6 as high-level work above.

## Risks and reconciliation log

The main risk is accidentally treating a proposed typed contract as already implemented or preserving only numeric formulas while losing statuses, metadata or revision identity. Stored result freshness can remain `FRESH` after the query-time headline becomes `STALE`; changing that policy is outside this behavior-preserving migration without a separate contract decision. `Legacy/` is the behavior oracle and remains immutable.

### 2026-10-06 — Phase 1 evidence

Observed: Legacy-backed tests confirmed score status branch order, effective-dated fallback, the 14-night debt ledger, result fingerprint/version behavior and the two freshness layers. A freshness-only persistence call reports a change but keeps the existing stored row/label.

Plan changes: Phase 1 is complete; Phase 2 stays high-level pending explicit reconciliation of the observed contracts. No production implementation or schema task has been added.

Reason: the observed freshness discrepancy and status details must be visible before defining target contracts.

### 2026-10-06 — Contract and freshness ownership reconciliation

Observed: score/need/debt calculations need only dated sleep measurements, effective target snapshots and ordered input references; current profile loading and `MetricDraft`/SQLite wiring are integration concerns. Runner and CLI implement different freshness decisions outside the sleep formula.

Plan changes: Phase 1 RECONCILE is complete. Phase 2 now has a bounded contract-only task. Phase 3 remains the first formula migration; Phases 3–6 stay high-level. ADR-001 assigns target freshness ownership outside pure analytics without changing Legacy behavior.

Reason: the stable semantic boundary is supported by characterization, while exact target type names and storage adaptation must be validated incrementally.

### 2026-10-06 — Phase 2 contract checkpoint

Observed: a narrow `src/domain/sleep/` package now defines immutable input, result, status, lineage and metadata types. It represents the current 15-date score history reach and 14-date debt target ledger without pulling in Legacy or platform code. When no current night exists, an empty target ledger is allowed to preserve Legacy's early return. Ten new tests pass. Durations are retained as observed, including invalid values, for the later Legacy-compatible gate; effective target values and result status/value combinations are validated now.

Plan changes: Phase 2 contract work is complete. Phase 3 remains high-level and unstarted; its detailed design must be reconciled against the concrete types and Phase 1 oracle before formulas move.

Reason: the contract boundary is now executable, while calculation and persistence integration remain separate tasks.

### 2026-10-06 — Phase 3 pure calculation checkpoint

Observed: differential tests reproduce Score, Need and Debt outputs on shared synthetic data, including invalid and cold-start statuses, effective targets, debt gaps/balance, metadata and lineage. A target calculator exists but is not called by the production runner. The target input already distinguishes raw invalid measurements from resolved valid targets.

Plan changes: Phase 3 is implemented. Phase 4 remains a separate integration task; profile resolution, result adaptation and persistence compatibility require reconciliation before its detailed plan. Phases 5–6 remain high-level.

Reason: preserving the existing profile and persistence contracts requires an adapter at the boundary, not logic inside pure calculations.

### 2026-10-06 — Phase 3 reconciliation and Phase 4 design

Observed: current runner/storage uses active `FeatureRecord` instances, not merely their identity strings. `put_result()` reads ordered records to derive fingerprint, aggregate lineage/coverage, quality flags and measurement bounds. The canonical result has sufficient references to resolve those original records but cannot recreate them alone. Legacy target resolution yields floats; canonical target inputs can contain integers, which could change serialized fingerprint content. The runner owns run-time freshness and the CLI owns query-time headline freshness. A direct in-place runner edit is barred by immutable Legacy, and ordinary imports cannot load both `analytics` packages in one process by path order alone.

Plan changes: Phase 4A/B are separately testable adapters; Phase 4C is gated on a reviewed external orchestration seam. Fixed the feature specification's Phase 2 status and recorded the exact input/output mapping and ownership table. No formula, schema, CLI, freshness or behavioral contract changed.

Reason: these concrete dependencies determine whether a behavior-preserving integration can keep revision identity and active selection stable.

### 2026-10-06 — Phase 4A input adapter checkpoint

Observed: the input adapter can consume Legacy-shaped `FeatureRecord` instances through a structural interface without importing Legacy or target analytics. Its no-current-night branch avoids profile/history inspection; its target resolver matches Legacy's effective dates, 480.0 fallback, validation message and float representation. Nine new synthetic tests pass. No contract field was missing for provenance.

Plan changes: Phase 4A is complete. The earlier proposed Phase 4A import-path decision is deferred because the current task explicitly excluded solving the two-package conflict and the adapter does not require it. Phase 4B remains output conversion and persistence compatibility tests; Phase 4C still requires a stable combined import path and an external orchestration seam. The feature specification still describes Phase 4 as designed but unimplemented; this task leaves its status wording unchanged under the explicit instruction to edit that file only for a mapping-contract clarification. No formula, schema, CLI, freshness or production runner behavior changed.

Reason: this preserves the bounded input boundary while keeping unrelated packaging and production integration decisions separate.

### 2026-10-06 — Phase 4A reconcile and Phase 4B checkpoint

Observed: Phase 4A maps observations and resolves profile targets without calculation formulas or persistence work. `SleepCoreInput` contains no DB row IDs, revision IDs or active-selection state; its ordered `NightReference` values carry enough identity to locate the original active features. The Phase 4B adapter uses those exact objects and produces `MetricDraft` values equal to Legacy. Real `put_result()` fingerprints and selected persistence columns match across synthetic cases for all three sleep metrics. Repeated writes and one historical correction preserve the characterized revision/selection behavior. The stored-freshness-only reselection quirk also remains unchanged.

Plan changes: Phase 4B is complete; Phase 4C remains unstarted. The direct Legacy `MetricDraft` import is confined to `src/integration/sleep/output_adapter.py`. Neither storage nor canonical/pure sleep code changed. The two `analytics` packages still conflict under ordinary import ordering, and immutable Legacy provides no direct runner hook. The feature specification's Phase 4 status prose remains intentionally unchanged because this task authorized editing it only for a newly discovered persistence contract; none was found.

Reason: exact storage identity is proven for synthetic drafts, but production orchestration and packaging compatibility require their own task and regression checks.

### 2026-10-06 — Phase 4C import and seam design

Observed: two read-only import checks confirm that `Legacy:src` resolves `analytics` to Legacy and cannot import target `analytics.sleep`, while `src:Legacy` resolves it to target and cannot import Legacy `analytics.algorithms`. Existing mixed tests use `src.analytics.sleep.core` only because the repository root is on `sys.path`; no install/package manifest establishes that as a product import. The Legacy runner binds `calculate_sleep_day()` at import and exposes no calculator argument. Its surrounding source, replay, lock, transaction, freshness and cleanup responsibilities cannot be replaced by a sleep-only function call.

Plan changes: ADR-002 chooses `mi_fitness_whooping` and an external seam between selected active features and existing storage. Phase 4C is divided into 4C1 combined-import and temporary-DB proof, 4C2 synthetic orchestration wrapper, and a separately reconciled 4C3 production switch. Earlier wording that left package identity/seam undecided described the prior state; the choices are now documented but unimplemented. Feature scope, formulas, schemas, Legacy code, CLI and freshness contracts remain unchanged.

Reason: a narrow proof can validate sleep result persistence without claiming runner parity or mutating the installed path.
