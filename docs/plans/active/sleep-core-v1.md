# Execution Plan: Sleep Core v1

Status: **Phases 1–3, Phase 4A/B characterization, Phase 4C1/4C2, Storage Phases A–C and selected-night reading complete synthetically; Phase 4C3 pending.** Feature specification: [`../../features/sleep-core-v1.md`](../../features/sleep-core-v1.md). The repository, feature specification and locked contracts outrank this provisional plan.

## Current phase

Phase 3's pure calculator consumes Phase 2 contracts and has differential tests against immutable Legacy. The input adapter now accepts target selected-night values in persisted synthetic scenarios; profile loading still uses Legacy at the test/caller edge. The former 4B Legacy result adapter is test-only reference code. The Sleep-only orchestrator coordinates one date with explicit run context; target storage owns result writing and selected-night reading. The next input boundary is profile v1 loading/revision, followed separately by broader runner composition. Production still uses Legacy; 4C3 remains separately gated.

## Rolling-wave phases

1. **Characterization / contract tests.** Detailed below. Capture current values, statuses, metadata and lineage with synthetic inputs while `Legacy/` stays immutable.
2. **Canonical sleep input/output contracts.** Implement only the smallest typed nightly/history and result interfaces justified by Phase 1, with contract tests. Details below.
3. **Pure sleep calculation migration.** Reproduce score, need and debt behind those contracts. Keep formulas and quality gates unchanged.
4. **Integration behind existing orchestration/storage contracts.** Adapt current feature/history input and persist compatible result drafts without schema or CLI changes.
5. **Regression comparison against Legacy.** Compare characterized cases and relevant synthetic end-to-end runs, including reruns and historical correction.
6. **Audit.** Independently check the feature specification, dependency direction, compatibility, tests and change scope.

Completed Phases 1–3, Phase 4A/B/C1/C2 and Storage Phases A–C are described below. The 4A/B/C checkpoint descriptions preserve historical design evidence; current ownership is summarized here and in `CURRENT_STATE.md`. Phase 4C3, remaining feature-input migration and Phases 5–6 remain high-level until reconciliation. This plan does not schedule the whole project.

## Target analytics storage migration — design checkpoint

ADR-003 documents current Sleep-visible result/feature identity, exact fingerprint inputs and canonicalization, row uniqueness, revision/reselection, active selection, freshness, provenance serialization and runner atomicity. **Current:** `TargetSleepStore` maps canonical Sleep results to Phase A target storage contracts and publishes through the independently verified Phase B schema-v3 writer, using one target session per synthetic date. The former `LegacySleepStore` and runtime `MetricDraft` adapter are removed. **Target:** a future outer runner owns the broader transaction, run lock and replay decision; selected feature storage/readout and profile loading still need target ownership. Legacy deletion remains an explicit project milestone.

1. **Storage Phase A — contracts and tests, complete:** immutable `StoredFeatureRef`, `PersistableMetricResult`, explicit `ResultWriteContext`, post-persistence `ResultIdentity`/`ActiveResult`/`WriteOutcome`, and narrow repository/session protocols. `to_persistable_sleep_result()` maps canonical Sleep results to these fields without importing Legacy or writing. Six synthetic tests cover field equivalence to Legacy drafts, ordered lineage, metadata immutability, missing versus zero, context/result separation, protocol shape and forbidden imports. Exact fingerprint bytes, row identity and rollback still require Phase B differential tests; no algorithm or SQLite writer was implemented.
2. **Storage Phase B — compatible target writer, complete:** `storage/fingerprint.py` reproduces Legacy's current canonical digest without a Legacy import. `storage/sqlite.py` accepts only an existing schema-v3 connection, opens explicit `BEGIN IMMEDIATE` sessions, writes/reselects result rows, reports identity/outcome, reads and clears active selections, and never commits per result. Its injectable operational timestamp controls `calculated_at`; stored freshness comes from context. Five new differential tests compare every row column and selection with Legacy under fixed timestamps for first/unchanged/corrected/profile/reselected states, source-policy and freshness quirks, cross-scope clearing, rollback and forbidden imports. No schema/user data or production path changed.
3. **Storage Phase C — synthetic Sleep switch, complete:** `integration/sleep/target_persistence.py` now validates lineage against the already selected night map, projects canonical results, supplies explicit write context, opens one target session, persists three metrics and clears only requested obsolete selections. It rolls back partial writes on failure. The old bridge was removed; test-only Legacy comparison code remains under `tests/integration/`. Two new orchestration tests compare every result/selection column with the Legacy reference path under fixed time across first, unchanged, corrected, changed-profile and both no-current-night cleanup modes, and prove the target path does not call Legacy `put_result()`. Existing orchestration rollback/no-night tests now exercise the target sink. No production runner or CLI change.
4. **Selected-night read boundary — complete for synthetic Sleep:** the persisted target caller uses `SqliteActiveNightReader` on existing active schema-v3 feature rows, returning `SelectedSleepFeature` values; the Legacy branch retains `active_feature_records()` solely as reference. Profile loading is still Legacy-owned. Result persistence remains target-owned. This is not a claim that feature building or non-Sleep Legacy dependencies are gone.

### Selected-night read boundary implemented; profile and runner handoff remain design

**Completed implementation:** `SqliteActiveNightReader.selected_nights(session, day)` reads active `nightly` selections from day−14 through day in the caller's transaction. `SelectedSleepFeature` contains seven raw observations and a `StoredFeatureRef` with unchanged selected-row identity/provenance. The existing structural input adapter and sink accept it without changing `run_sleep_day()`. Tests compare target-read nights with Legacy `active_feature_records()` and all three stored Sleep metrics/active selections across initial, unchanged, historical/current correction, configured profile and missing-current scenarios. The reader does not write features, load profiles, change schema or switch production.

**Profile boundary after that task:** a target v1 loader must read the complete document, validate supported fields/intervals and compute the Legacy-compatible revision from all fields, then a dated resolver supplies `EffectiveSleepTarget` values and fallback flags. The parser may keep the existing JSON layout; it must not generate a Sleep-only revision. The current input adapter's target resolution is the behavioral baseline, not evidence that target file loading exists. Profile loading still occurs at runner entry even if a later requested Sleep date lacks a current night.

| Minimum proposed contract | Role; current status |
|---|---|
| `SelectedSleepFeature` | Implemented storage/read-model value for one active nightly feature: seven raw Sleep observations plus `StoredFeatureRef`; it exposes a narrow structural view to the existing adapter. |
| `ActiveNightReader.selected_nights(session, day)` / `SqliteActiveNightReader` | Implemented protocol and schema-v3 reader. Returns the inclusive day−14…day active-night map using `active_features.feature_id`; accepts an existing session, does not commit or build features. SQLite stays in storage. |
| `ProfileSnapshot` (working name) | Supported validated profile-v1 entries plus a revision computed from the full original v1 document, including tolerated extra content. The dated resolver returns the already implemented `EffectiveSleepTarget` values. **Loader/snapshot not implemented.** |
| `SleepRunContext`, `AnalyticsSession`, `SleepCoreInput`, `StoredFeatureRef`, `EffectiveSleepTarget` | Existing narrow contracts to reuse. No general `RunnerContext` is justified yet; source checkpoints and other feature outcomes belong to later full-runner design. |

**Future runner minimum contract:** select dates; hold the existing global analytics lock; begin a shared analytics transaction/session; obtain/build and select features; obtain a validated profile and full-document revision; supply run ID, source policy, stored freshness and replay cleanup; call Sleep alongside other metrics; update run/state/checkpoints; commit or roll back. The `RUNNING` run record commits before the data transaction, `SUCCESS` commits with it, and `FAILED` is recorded after rollback. Do not put Sleep formulas or its result SQL into this runner. Current `run_sleep_day()` already separates calculation from run policy, but `TargetSleepStore` owns a one-date session; future integration must remove that local transaction ownership so repository operations join the runner session.

| Observed Legacy behavior | Migration classification | Owner / compatibility rule |
|---|---|---|
| Source generation/file fingerprint and import/max-timestamp checkpoints; 48-hour measurement overlap and ±1-day expansion for changed dates | Runner policy with locked observed effects | Future runner/source boundary computes dirty dates and updates checkpoints; no Sleep formula change. |
| Profile/normalization/implementation change forces full feature rebuild; metric algorithm version change forces full metric replay | Runner policy with locked observed effects | Preserve dates, revision identities and replay choice; the current `metric_force_full` flag also suppresses obsolete-selection cleanup. |
| Incremental metric replay spans changed feature dates through +90 days; CUSUM may extend until state rejoins | Runner policy with cross-feature dependency | Full-runner reconciliation must keep this behavior for all metrics; a Sleep-only reader must not duplicate it. |
| Main-night choice, stage completeness, nightly values/fingerprint | Feature policy | Existing feature builder/writer remains Legacy-owned in the next task; read the selected row verbatim. |
| Incremental missing night clears active Sleep selections; full replay missing night retains them; historical rows stay | Locked migration behavior, caller-chosen runner policy | Runner supplies `cleanup_obsolete`; Sleep sink requests clear only in incremental mode; repository executes it. |
| Private helper names, direct `source._db()` queries, SQL statement layout and in-memory collection shape | Legacy implementation detail | Replace later only with equivalent observable results; do not copy into Sleep Core. |

**Legacy removal checkpoint after the read task:** `active_feature_records()`/`FeatureRecord` have left the persisted target synthetic Sleep input path; older adapter/characterization tests still use Legacy fixtures. Legacy `load_profile()` still supplies the profile and revision; Legacy feature building/writing, source ingestion/ETL, dirty-date/checkpoint logic, global lock/transaction/run records, other metrics and CLI remain. Differential tests continue to import Legacy as the oracle. This read task does not authorize a production switch.

Reconcile between phases; later details remain high-level. Phase 4C3 cannot be treated as a simple sink replacement: full-runner shared transaction/run record, lock, dirty-date/replay, non-Sleep metrics, checkpoints and CLI behavior still require separate design and regression proof.

## Phase 4 integration boundary — synthetic Sleep lifecycle implemented

**Current path.** `XiaomiAdapter` reads the external health mirror. `build_nightly()` selects one `main` sleep session for a date, validates stage coverage, computes sleep measurements and lineage, and returns a `Feature`. `put_feature()` stores it in `features` and updates `active_features`; `active_feature_records()` reconstructs the active dated `FeatureRecord` map. The runner loads profile v1 and its revision, calculates dirty/replay dates, then passes the map and profile to `calculate_sleep_day()`. That function resolves dated targets and produces three `MetricDraft`s when a current night exists. The runner assigns stored freshness per metric date and calls `put_result()`. Storage fingerprints result content and ordered feature inputs, writes or reselects a result revision and updates `active_metric_selection`; incremental runs also remove obsolete selections. `status` reads active results and independently evaluates current sleep freshness for its JSON headline.

### Phase 4A — input adapter and tests

**Responsibility/input/output:** a compatibility adapter outside pure sleep takes `(day, nights: dict[date, FeatureRecord], loaded_profile_v1: dict, profile_revision: str)` from orchestration and returns one `SleepCoreInput`. It performs no SQLite read and no main-session selection. It includes only active nightly records from day−14 through day, sorted ascending; all raw sleep observations (`tst_min`, `deep_min`, `rem_min`, `waso_min`, awakening durations, local bedtime) keep `None`, zero and invalid values distinct. It uses exactly `stage_coverage == "COMPLETE"`; the string's other values map to `False`. Each `NightReference` copies date, feature fingerprint, source count/IDs hash, measurement interval and quality flags from the original record. The orchestrator retains the original map for target-sink lineage validation.

**Targets and errors:** if the current day has no active night, return an input with no targets and do not inspect any effective target; `load_profile()` has already validated the profile file at runner entry. Otherwise resolve the current target first, then each date day−13…day with the existing `effective_values()` semantics: absent/`None` means 480.0 minutes and default, configured values must be numeric, finite and 300–720 minutes, with the current `sleep_target_min must be within 300..720` error contract. Normalize every resolved target to `float`, matching Legacy `_target()`; `int` would compare numerically equal but could change storage's JSON fingerprint. Produce the complete ordered target ledger. Structural contract errors must surface before calculation; do not silently replace invalid configured targets. A missing active night in the ledger remains a calendar gap, not a zero night. Profile revision is carried unchanged for storage identity; the pure formula does not inspect it.

**Import boundary:** before 4C1, `Legacy/analytics` and `src/analytics` collided and mixed tests used `src.analytics.sleep.core`. Phase 4C1 moved the target modules to `src/mi_fitness_whooping/` and removed the old target-package locations. A clean subprocess now imports Legacy `analytics` and target `mi_fitness_whooping` with either `Legacy:src` or `src:Legacy`; no moved test or target runtime module mutates `sys.path` for this. The explicit source-root test command is `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:Legacy python3 -m unittest discover -s tests/integration -q`. No package installer or production entrypoint exists yet.

**Phase 4A result:** `src/mi_fitness_whooping/integration/sleep/input_adapter.py` defines a structural `NightlyFeature` interface and `adapt_sleep_input(day, nights, profile, profile_revision)`. It imports only canonical sleep contracts and standard-library modules. When the current date has no active night it returns `SleepCoreInput(day, (), (), profile_revision)` before reading profile or prior-night contents, matching Legacy's early return. With a current night it resolves that day's target first, maps the bounded history in ascending date order, then resolves the complete 14-date target ledger. Target values are `float`; observations retain missing, zero and invalid values for the pure calculator's gates. The adapter creates `NightReference` values from original feature identity/quality fields and does not load source files, access SQLite, calculate metrics or create persistence IDs.

**Phase 4A verification:** nine synthetic tests in `tests/integration/test_sleep_input_adapter.py` cover current/absent nights, no-current malformed profile/history, ordered bounded history and references, stage coverage, missing versus zero, effective dates/defaults, float target representation, invalid target rejection, deterministic output and import/clock guards. They compare targets and selected observable cases with immutable Legacy code; existing tests remain unchanged. The output adapter and production wiring have not begun.

### Phase 4B — output adapter and persistence compatibility tests

**Responsibility/input/output:** take a `SleepMetricResult` plus the original active-night `FeatureRecord` map used for its input. Return a Legacy-compatible `MetricDraft` for existing `put_result()`. Map metric enum → `name`, calculation status enum → status string, and copy date, value, unit, algorithm ID/version, `OUR_DERIVED`, upstream project/commit and `MEDIUM` confidence. Convert `ScoreMetadata`/`ScoreComponents`, `NeedMetadata` and `DebtMetadata` to the exact current dictionaries, including `None` keys. Resolve each ordered `NightReference` to the original `FeatureRecord` using date and fingerprint, verify the copied lineage fields, and preserve that order in `inputs`. A mismatch fails closed; never substitute a different active revision or synthesize a feature fingerprint.

**Storage ownership:** `put_result()` remains responsible for `input_fingerprint` from metric/date, ordered feature fingerprints, metadata, status, value, profile revision and normalization/algorithm/implementation/contract versions. Its current identity context includes `NORMALIZATION_VERSION="xiaomi-normalization-1"`, `IMPLEMENTATION_VERSION="0.5.0"`, `input_contract_version="foundation-output-1"`, runner `source_policy_version="primary-v1"`, `source_scope="primary"`, `release_channel="production"` and stored `quality_gate_version="foundation-gates-1"`; migration must preserve the existing values and ownership. Storage also owns `source_signals_json` (including nightly `kind`), `input_coverage_json`, unioned flags, measurement bounds, calculation timestamp, run ID, `supersedes_result_id` and `active_metric_selection`. The output adapter does not create IDs, hashes, SQL rows or freshness labels. The runner must continue supplying `profile_revision`, `run_id`, `source_policy_version` and the existing stored `freshness_status` to `put_result()`.

**Phase 4B historical result:** the former `src/mi_fitness_whooping/integration/sleep/output_adapter.py` imported Legacy `FeatureRecord`/`MetricDraft` for the compatibility proof. Its `adapt_sleep_result(result, nights)` mapping and original-object validation now live at `tests/integration/reference_legacy_output.py` only. The active target path uses `storage_contract_adapter.py` plus `target_persistence.py` to validate lineage and publish target-owned results. The historical tests still compare the old draft shape and do not weaken the migration baseline.

| Phase 4B field source | Persistence-facing fields / responsibility |
|---|---|
| **DIRECT FROM `SleepMetricResult`** | `metric.value → name`, `day`, `value`, `unit`, `status.value`, `algorithm_id`, `algorithm_version`, `source_type`, `upstream_project`, `upstream_commit`, `confidence`. No numeric or status rewriting. |
| **DERIVED BY OUTPUT ADAPTER** | `metadata = asdict(result.metadata)` with exact nested keys/types and explicit `None`; ordered `inputs` obtained by resolving each `NightReference` to the original active `FeatureRecord`, validating date, fingerprint, source count/hash, bounds and flags. No newly fabricated feature object. |
| **SUPPLIED BY ORCHESTRATION** | Original active-night map, `profile_revision`, `run_id`, `source_policy_version`, calculation-date stored `freshness_status`, metric-date replay scope and produced-name cleanup. Only the map is an argument to this adapter; the remaining values go to unchanged storage separately. |
| **SUPPLIED BY STORAGE** | `input_fingerprint`, normalization/implementation/quality-gate/input-contract versions, source scope and release channel, `source_signals_json`, `input_coverage_json`, unioned quality flags/measurement bounds, `calculated_at`, `source_updated_at`, `result_id`, `supersedes_result_id`, active metric selection and database row creation. |
| **NOT APPLICABLE TO OUTPUT ADAPTER** | Query-time freshness/headline formatting, SQLite connections/paths, main-night selection, profile parsing, formula gates and score/debt calculations. |

**Phase 4B fingerprint and persistence evidence:** seven new synthetic tests compare Legacy and adapted `MetricDraft`s for valid Score, calibration, insufficient Score, default/effective-dated Need, valid and calibrating Debt, metadata `None`/nested components, ordered original object identity and mismatched lineage. The tests call the real `put_result()` in separate temporary analytics DBs and compare the three `input_fingerprint` values, metadata/source-signal/coverage JSON, flags, measurement bounds and key result columns. Fingerprints match for all three metrics across the representative cases. Initial insert, unchanged rerun, corrected historical input, revision chain, active selection and freshness-only reselection also match. No storage function or schema was changed; these tests do not establish whole-runner or real-data equivalence.

### Phase 4C — external seam, staged and gated

ADR-002 records the package identity and the originally tested external seam. The installed Legacy runner imports `calculate_sleep_day()` directly and has no sleep injection hook. The current synthetic path begins **outside immutable `Legacy/`**, after an already selected active-night map is supplied, and publishes through target result storage. The earlier `active_feature_records()` → Legacy `put_result()` seam remains only test/reference history. Do not monkey-patch the Legacy runner, edit its files, or post-process sleep results in the production database. Keep the production runner and CLI on Legacy.

**4C1 — completed package separation and synthetic seam proof.** Target domain/analytics/integration modules now live under `src/mi_fitness_whooping/`, with the old target locations removed. A clean subprocess imports both `analytics.algorithms.foundations` from Legacy and `mi_fitness_whooping.analytics.sleep.core` from target in either source-root order. Four new tests exercise a temporary analytics DB seeded through existing `put_feature()`, read original nights with `active_feature_records()`, load profile v1 with `load_profile()`, run input adapter → pure Sleep Core → output adapter → real `put_result()` with explicit synthetic run ID, profile revision, `primary-v1` source policy and fixed stored `HISTORICAL` freshness. They compare Legacy and target drafts and stored fields for default 480.0 and effective-dated 450.0 targets, first insert, unchanged rerun and corrected historical input. No personal data, production entrypoint, formula, schema or CLI changed.

**4C2 — completed synthetic Sleep orchestrator.** `src/mi_fitness_whooping/integration/sleep/run_context.py` defines the Legacy-independent `SleepRunContext(day, profile_revision, run_id, source_policy_version, stored_freshness, cleanup_obsolete)` shared by orchestration and its sink. `src/mi_fitness_whooping/orchestration/sleep.py` exposes that context and `run_sleep_day(nights, profile, context, sink)`. It accepts already-loaded nightly features, adapts inputs, calls the pure calculator and publishes canonical results. It imports no Legacy type, SQLite, CLI or clock. At the 4C2 checkpoint its temporary bridge used Legacy storage; Phase C has since replaced and removed that bridge. The current target sink/repository retain one-date rollback and cleanup behavior without Legacy persistence imports.

Three Legacy characterization tests pin the missing-night and rollback rules. Incremental replay deletes active sleep selections when the current night disappears; full replay (`metric_force_full`) skips cleanup and retains those selections. Both preserve historical result rows. A failure on the second sleep metric rolls back the Legacy runner's in-flight feature/metric transaction; its separate run record becomes `FAILED`. Seven orchestrator tests now exercise target result storage: Legacy/target first/unchanged/corrected/profile states, both no-night modes, rollback, transaction ownership, full-row equivalence and no Legacy writer call. They prove only a synthetic Sleep-date boundary, not the global runner run-record behavior. `cleanup_obsolete` is supplied by the caller; the orchestrator does not infer dirty/replay policy or read a clock. Locking belongs to a future outer runner.

**4C3 — production switch, separately gated.** Reconcile the entire existing runner lifecycle: source generation/checkpoints, dirty-date expansion and 90-day/CUSUM replay, feature writes, all metric ordering, lock and transaction, run records, obsolete selection, counters/errors and current CLI JSON/headline. Choose an opt-in activation and rollback only after full synthetic regression. Do not copy the whole runner blindly or change the installed ETL. No implementation detail for 4C3 is locked by this plan.

**Proof limit:** 4C1/4C2 and Storage Phases A–C prove the three sleep metrics' names, statuses, units, versions, metadata, exact input fingerprints, revision chain, active selection, missing-night behavior and isolated Sleep-date rollback in tested synthetic cases, now through target result persistence. They do not prove production source detection, global runner transaction/run records, dirty-date replay, lock, query-time freshness or CLI-visible output. Stored freshness is supplied explicitly and stays outside pure calculation per ADR-001. A later feature may migrate Recovery, Monitoring or Activity into the same project package; none is part of Phase C.

### Field ownership at this boundary

| Classification | Required fields and owner |
|---|---|
| **DOMAIN** | Date; selected-night presence; TST, deep, REM, WASO, awakening durations, local bedtime, stage completeness; dated effective target/default; `NightReference` date/fingerprint/source count/source IDs hash/measurement bounds/quality flags; metric name, value, unit, calculation status, algorithm ID/version, upstream provenance, confidence, result metadata and ordered lineage. These are represented by canonical contracts. |
| **ORCHESTRATION** | Active dated-night map and selected date/replay scope; loaded profile v1 and profile revision; no-current-night decision; invocation/order of foundation, sleep, recovery and monitoring; run ID, source-policy context and calculation-date `today` used for stored freshness; obsolete-selection cleanup. The profile revision is carried through `SleepCoreInput` for identity but does not affect the pure formula. |
| **PERSISTENCE** | Target `StoredFeatureRef` ordered lineage and `PersistableMetricResult`; `derived_metric_results`/`active_metric_selection`; `input_fingerprint`, normalization/implementation/quality-gate versions, source scope, release channel, source signals/coverage JSON, unioned flags and interval bounds, `calculated_at`, `source_updated_at`, result ID and superseded ID. Storage receives run ID, profile revision, source policy and stored freshness from explicit context. `features`/`active_features` are still Legacy-owned in production and are outside this target result writer. |
| **PRESENTATION** | Query-time `current_sleep_freshness`, `sleep_headline` value visibility, `last_historical_statuses`, status counts and CLI JSON format. These read published active results and do not enter the calculator or adapters. |
| **DEFERRED / LEGACY-ONLY** | Legacy-shaped selected `FeatureRecord` inputs and extra `values` fields remain at the synthetic input boundary; `MetricDraft` now appears only in test/reference code. Raw Xiaomi rows, profile file path, feature DB IDs and a redesigned freshness policy remain outside canonical Sleep Core. |

### Freshness and compatibility gate

Freshness is outside pure Sleep Core and input/result projection. The target sink supplies stored `HISTORICAL`/`FRESH`/`STALE` through `ResultWriteContext`; target storage preserves the characterized unchanged-input and freshness-only reselection behavior. Legacy production runner still supplies freshness to its own `put_result()`. Query-time freshness and the 36-hour headline rule remain in the status/presentation path. Preserve the three metric identities, units, status strings, algorithm/version/provenance, exact nested metadata, ordered lineage, input fingerprint and active revision semantics, and CLI-visible values/status. Exact compatibility is not yet demonstrated for the production runner: its immutable direct sleep call still requires a separately designed full-runner path, and no real-data fixtures exist.

### Phase 4 test strategy and remaining checks

- **Unit adapter tests — implemented for 4A/B:** synthetic active `FeatureRecord` map → canonical input equality for 15-date reach, absent/current night, valid/invalid bedtime, missing/zero stages, 14 dated targets, default/effective-dated profile changes, invalid target, float target values and lineage identity; canonical result → exact `MetricDraft` equality, including nested metadata and original ordered `inputs`; reject stale or mismatched lineage. Phase 4C1 now tests combined package loading separately.
- **Integration tests — implemented through Storage Phase C:** historical 4B/C1 test-only reference drafts retain fingerprint and lineage comparison; current synthetic Sleep orchestration publishes through target storage and compares complete schema-v3 result/selection rows with Legacy under fixed time for first/unchanged/corrected/profile and no-night cases. It also tests rollback, nested transaction rejection and absence of Legacy writer calls. Full runner/CLI compatibility remains unproven.
- **Regression tests:** before any production switch, compare full synthetic runner paths, metric identities/statuses, counts, CLI `status` JSON/headline under fixed times, stored-vs-query freshness divergence and other existing outputs. Keep the 20 characterization, 10 contract, 6 differential, 62 Legacy unittest and 5 ETL checks unchanged.

## Completed task — SLEEP-PURE-03

**Scope:** `src/mi_fitness_whooping/analytics/sleep/core.py` reproduces Legacy Score, fixed-target Need and signed 14-night Debt through `SleepCoreInput` → three `SleepMetricResult` values. It has no Legacy runtime import, SQLite, clock, CLI or orchestration dependency. With no current night it returns an empty tuple before reading targets.

**Verification:** `tests/analytics/test_sleep_core.py` compares observable values, statuses, units, algorithm/provenance identity, metric-specific metadata and ordered lineage with Legacy across synthetic normal, calibration, invalid and historical cases. It checks forbidden dependencies and clock reads. Existing contract and characterization suites remain unchanged.

**Reconciliation:** the existing types carry the required observations and result metadata. Effective-dated profile resolution and invalid profile rejection occur before pure calculation, as designed; Phase 4 must provide that adapter without changing profile v1 semantics. No locked behavioral contract conflict was found. The feature specification's stale Phase 2 status is corrected in this reconciliation.

## Completed task — SLEEP-CONTRACT-02

**Goal:** establish the minimal, immutable, source-independent canonical Sleep Core input/output types and their validation/identity semantics. This phase creates contracts only; it does not calculate Score, Need or Debt.

**Scope:** choose a coarse canonical-domain location; define a dated selected-night input, bounded history/target snapshot, ordered lineage reference and three-metric calculation-result contract corresponding to the conceptual tables in the feature specification. Make absent night and missing value distinct from measured zero. Represent stage completeness and fallback use explicitly. Carry only the provenance/quality fields needed to reproduce the existing stored result through a later adapter. Define validation for dates, value presence and invalid configured targets without parsing profile files or Xiaomi rows.

**Files used:** `src/mi_fitness_whooping/domain/sleep/contracts.py` with minimal package initializers; `tests/contracts/test_sleep_contracts.py`; feature, plan, architecture and current-state documentation. No target calculator, SQLite repository, CLI, orchestration adapter or schema change in this phase.

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
- [x] Phase 4C1 package separation and synthetic seam proof per ADR-002; then reconcile 4C2 wrapper scope.
- [x] Phase 4C2 synthetic Sleep-only orchestration and transaction/cleanup characterization.
- [x] Reconcile target analytics storage ownership and compatibility in ADR-003 (design only).
- [x] Storage Phase A minimum contracts and synthetic contract tests.
- [x] Storage Phase B compatible target writer and full-row synthetic differential tests.
- [x] Storage Phase C synthetic Sleep sink switched to target result persistence.
- [x] Reconcile remaining selected-feature/profile input and full-runner boundaries in documentation.
- [x] Implement target-owned active-night read boundary only; keep profile and production unchanged.
- [ ] Reconcile target profile v1 loading/revision implementation scope before coding it.
- [ ] Separately gated 4C3 production-switch design and implementation.
- [ ] Phases 5–6 as high-level work above.

## Temporary Legacy dependency and removal map

**Legacy deletion is an explicit project milestone.** The target Sleep execution package now has **zero runtime Legacy imports**. The items below are remaining **input compatibility or test-reference dependencies**, plus Legacy-owned production boundaries. None is a permanent target result-persistence dependency. Removal milestones are ownership boundaries, not a detailed schedule for the whole project.

| Current Legacy symbol or behavior | Why required now | Target replacement owner | Removal milestone |
|---|---|---|---|
| `FeatureRecord` in characterization/older adapter tests | Test-only fixtures and historical oracle; persisted target synthetic callers now use target selected-night values. | Target `SelectedSleepFeature`/`SqliteActiveNightReader` already owns the persisted synthetic read path. | Retain fixture tests until final audit; no runtime removal remains for this read path. |
| `MetricDraft`, `put_result()` and old output mapping in tests | Test-only Legacy oracle for exact draft/fingerprint and full-row comparison; no active target result path uses them. | Retain as characterization until independent audit; target storage already owns runtime result writes. | Remove test scaffolding only when no longer needed for regression. |
| `cleanup_obsolete` run-context mode | Preserves incremental versus full-replay selection distinction; now executed through target repository. | Future full-runner replay policy and target storage selection repository. | Reconcile when full runner owns selection policy; preserve V1 behavior. |
| `load_profile()` in synthetic callers; `active_feature_records()` in Legacy-reference branches | Profile supplies validated full-document revision; Legacy feature reader supplies the comparison oracle only. Target orchestration imports neither symbol. | Target platform/config profile loader/resolver; target selected-night reader already implemented. | Profile migration before production replacement; keep Legacy oracle through audit. |
| Legacy source adapter, feature builders, dirty-date/checkpoint/replay, run records, lock and transaction | Current production runner owns full pipeline; none is imported by 4C2 orchestration. | Target ingestion, feature preparation, orchestration and platform/config. | Full target runner lifecycle before any production switch. |
| Legacy `__main__` CLI/status and ETL/source ingestion | Installed analytics presentation and source import remain Legacy-owned. | Target presentation and ingestion, respectively. | Separate presentation/ingestion migrations before Legacy deletion. |

No dependency above is classified as permanent. `TargetSleepStore` owns an isolated target one-date session and rejects nesting; it cannot substitute for the runner's broader transaction. Lock acquisition and source replay remain outside the synthetic slice. A 4C3 production switch cannot proceed by importing the old runner as a structural target dependency; reconcile full pipeline parity and removal sequencing first.

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

Observed: a narrow `src/mi_fitness_whooping/domain/sleep/` package now defines immutable input, result, status, lineage and metadata types. It represents the current 15-date score history reach and 14-date debt target ledger without pulling in Legacy or platform code. When no current night exists, an empty target ledger is allowed to preserve Legacy's early return. Ten new tests pass. Durations are retained as observed, including invalid values, for the later Legacy-compatible gate; effective target values and result status/value combinations are validated now.

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

Plan changes: Phase 4B is complete; Phase 4C remains unstarted. The direct Legacy `MetricDraft` import is confined to `src/mi_fitness_whooping/integration/sleep/output_adapter.py`. Neither storage nor canonical/pure sleep code changed. The two `analytics` packages still conflict under ordinary import ordering, and immutable Legacy provides no direct runner hook. The feature specification's Phase 4 status prose remains intentionally unchanged because this task authorized editing it only for a newly discovered persistence contract; none was found.

Reason: exact storage identity is proven for synthetic drafts, but production orchestration and packaging compatibility require their own task and regression checks.

### 2026-10-06 — Phase 4C import and seam design

Observed: two read-only import checks confirm that `Legacy:src` resolves `analytics` to Legacy and cannot import target `analytics.sleep`, while `src:Legacy` resolves it to target and cannot import Legacy `analytics.algorithms`. Existing mixed tests use `src.analytics.sleep.core` only because the repository root is on `sys.path`; no install/package manifest establishes that as a product import. The Legacy runner binds `calculate_sleep_day()` at import and exposes no calculator argument. Its surrounding source, replay, lock, transaction, freshness and cleanup responsibilities cannot be replaced by a sleep-only function call.

Plan changes: ADR-002 chooses `mi_fitness_whooping` and an external seam between selected active features and existing storage. Phase 4C is divided into 4C1 combined-import and temporary-DB proof, 4C2 synthetic orchestration wrapper, and a separately reconciled 4C3 production switch. Earlier wording that left package identity/seam undecided described the prior state; the choices are now documented but unimplemented. Feature scope, formulas, schemas, Legacy code, CLI and freshness contracts remain unchanged.

Reason: a narrow proof can validate sleep result persistence without claiming runner parity or mutating the installed path.

### 2026-10-07 — Phase 4C1 package separation and synthetic integration proof

Observed: all target modules now import under `mi_fitness_whooping`; the old `src/{domain,analytics,integration}` packages are absent. A subprocess imports both the immutable Legacy `analytics` package and target package in either source-root order. New tests seed active nightly features through Legacy `put_feature()`, reconstruct the original `FeatureRecord`s with `active_feature_records()`, load profile v1, calculate and adapt all three target results, and write them with unchanged `put_result()`. Separate temporary databases produce equal Legacy/target stored fields (excluding only clock-generated `calculated_at`), input fingerprints, full revision histories and active selections on first insert, unchanged rerun and corrected historical night. Need reaches storage as 480.0 or effective-dated 450.0, both `float`. Four new 4C1 tests, 16 prior adapter tests, six pure tests, ten contract tests, 17 characterization tests, 62 Legacy unittest tests and five ETL checks pass.

Plan changes: Phase 4C1 is complete. The immediate next step is reconciliation of the 4C2 external sleep wrapper's transaction, no-night cleanup, profile revision, fixed-time freshness and error/lock responsibilities. Keep 4C3 production entrypoint/CLI activation separately gated; no target runner, scheduler or source replay path exists. ADR-002's approved package identity and seam were followed without a material decision change.

Reason: a persisted synthetic vertical slice proves the import and sleep storage boundary, while production runner lifecycle remains outside this phase.

### 2026-10-07 — Phase 4C1 reconcile and Phase 4C2 synthetic orchestrator

Observed: ADR-002's distinct package identity works without import aliases. Canonical domain and pure Sleep Core still import no Legacy; only the output/persistence adapters use compatibility types. Phase 4C1 persisted fingerprints, revisions and active selections match Legacy. Newly characterized Legacy runner behavior adds an explicit replay-mode distinction: after a current night disappears, incremental replay clears active sleep selections while full replay retains them; historical rows remain. Failure during a sleep metric write rolls back the runner's in-flight transaction, with the separately committed run record marked `FAILED`. A changed profile revision revises all three sleep result identities even if a formula output is unchanged.

Plan changes: 4C2 now owns only one already-loaded Sleep date. `SleepRunContext` supplies date, profile revision, run ID, source policy, stored freshness and cleanup mode; the orchestrator coordinates adapters and pure calculation with no formula, SQL, clock or Legacy import. The temporary `LegacySleepStore` bridge owns output adaptation, unchanged `put_result()`, an isolated transaction and sleep-only obsolete-selection cleanup. It cannot be nested in a caller transaction. No global lock, source replay, run-record lifecycle, CLI or production switch was added. The Legacy dependency/removal table above is the explicit migration debt; Legacy deletion is a milestone, not an implicit permanent compatibility layer.

Reason: the synthetic lifecycle is now testable while keeping the future target storage and full runner boundaries distinct from Legacy.

### 2026-10-07 — Target analytics storage design reconciliation

Observed: Legacy `put_result()` derives a digest from metric/date, ordered feature fingerprints, metadata/status/value and profile/algorithm/normalization/input-contract/implementation versions; source policy is in the database uniqueness key but not the digest. Its active digest/freshness fast path means a source-policy-only change can return unchanged before consulting that uniqueness key. It can report `True` on a freshness-only reselection of the same historical row without updating that row's freshness or run ID. New rows link `supersedes_result_id` to the previously selected row; previously existing rows retain their original link. The runner's global transaction and prior committed `RUNNING` record exceed 4C2's isolated Sleep-date transaction. Incremental missing-night selection clearing and full-replay retention remain observed compatibility behavior.

Plan changes: ADR-003 chooses an existing-schema-compatible first target writer, target ownership of fingerprint/revision/selection logic, and an outer-runner-owned session. Storage Phase A contracts/tests now precede implementation, then a compatible writer, a synthetic Sleep switch and the Legacy type exit. No target storage module, schema, production runner or CLI was added. This design does not begin Storage Phase A or approve 4C3.

Reason: persistent personal history and current readers make a new schema plus writer migration an unnecessarily large first cutover; explicit contracts and differential tests lower the risk of replacing `put_result()` without changing behavior.

### 2026-10-07 — Storage Phase A contract checkpoint

Observed: every field in the three Legacy Sleep `MetricDraft`s and their ordered `FeatureRecord` lineage can be represented by target `PersistableMetricResult` and `StoredFeatureRef` without importing Legacy into target storage contracts. The projection preserves nested metadata and the distinction between missing and measured zero. Run/profile/source/freshness/version values live in `ResultWriteContext`, while database IDs and supersession appear only in post-write identity/outcome types. The repository protocol receives an outer-owned session and exposes explicit active-selection clearing; it has no commit method. `LegacySleepStore` remains the active synthetic sink.

Plan changes: mark Phase A complete. Phase B must implement compatible fingerprinting and result persistence against schema v3, including the source-policy-only early return, freshness-only reselection, historical revision selection and rollback under an outer-owned session. Compare complete synthetic stored rows and selection state with Legacy before considering Phase C. No target writer, schema change, production switch or formula change was made here.

Reason: target storage contracts now represent the observed data without carrying Legacy model classes or prematurely duplicating the fingerprint algorithm.

### 2026-10-07 — Storage Phase B compatible writer checkpoint

Observed: the target-owned canonical digest exactly matches Legacy for all three Sleep metrics in the tested first, unchanged, historical-correction, profile-revision and older-row-reselection cases. Against separate temporary schema-v3 databases with the same injected operational timestamp, every persisted result column and active-selection row matches after each scenario. The writer preserves the source-policy-only early return and freshness-only reselection of an old row, including unchanged stored freshness/run ID. Explicit clear removes requested production selections across scopes while retaining history; a caller-owned transaction rolls back multiple partial Sleep writes. Storage modules have no Legacy runtime or Sleep formula imports.

Plan changes: mark Phase B complete. Phase C should adapt only the synthetic Sleep orchestrator's sink to the target repository and session, preserving explicit cleanup policy and comparing end-to-end states with the existing Legacy bridge. Keep Phase 4C3 production runner/CLI activation separately gated. No ADR-003 decision, schema or locked contract changed.

Reason: the compatible result writer is now independently proven at its database boundary; orchestration integration is a separate concern.

### 2026-10-07 — Storage Phase C synthetic Sleep switch

Observed: `run_sleep_day()` retains its orchestration signature, but its active synthetic sink is now `TargetSleepStore`. That sink validates selected-night lineage, maps canonical results to `PersistableMetricResult`, constructs explicit storage context and publishes through the target repository in one target session. It clears missing-night selections only when the caller requests incremental cleanup and rolls back partial writes on failure. The runtime `LegacySleepStore` and `MetricDraft` output adapter were removed; the latter's exact comparison logic moved to `tests/integration/reference_legacy_output.py`. Tests import Legacy only for fixture input, schema initialization and differential reference. A fixed-time full-path test compares every result and selection column across first/unchanged/corrected/profile and both no-night modes; a guard proves no target call to Legacy `put_result()`.

Plan changes: Phase C is complete for synthetic Sleep result persistence. The next task is reconciliation of selected-feature/profile input ownership and the broader runner transaction, replay, lock, non-Sleep and CLI boundaries before any production switch. No formula, schema, freshness rule, Legacy snapshot or production entrypoint changed.

Reason: result persistence can now be owned by the target package without coupling the synthetic Sleep path to Legacy storage, while remaining migration boundaries stay explicit.

### 2026-10-07 — Selected inputs, profile and runner boundary reconciliation

Observed: target runtime Sleep code has no Legacy imports, yet synthetic callers still obtain `FeatureRecord` maps and a profile/revision from Legacy. `active_feature_records()` reconstructs selected rows from `active_features`/`features`; Sleep uses seven observation keys plus stored identity/provenance, not feature row IDs or the remaining nightly values. `load_profile()` validates a full v1 document and hashes all of it, while Sleep target resolution applies a later 300–720 gate and 480.0 fallback. The runner's lock, dirty dates, source checkpoints, run records and shared transaction remain Legacy-owned. The target sink's one-date commit cannot compose inside that transaction.

Plan changes: define the next single implementation task as a target-owned selected-night read boundary over unchanged schema v3, with Legacy differential proof. Keep target profile loading/resolution and full-runner session handoff as separately reconciled later work; do not advance 4C3. No source, schema, formula, Legacy, test or production code changed in this design pass.

Reason: removing the `FeatureRecord` read dependency is a coherent, testable slice, while combining it with profile hashing or global runner replacement would enlarge the compatibility surface before that slice is proven.

### 2026-10-07 — Active-night read implementation checkpoint

Observed: `active_features.feature_id` is the schema-v3 selection key; reading the latest `features` row would be wrong after reselecting an older revision or deleting the active choice. The new target reader uses the selected join in a supplied analytics session and projects seven raw Sleep fields plus the stored lineage. Dedicated synthetic tests prove bounds, gaps, active/reselected revisions, no historical fallback, missing-versus-zero and incomplete-stage values, same-session reads and identity/provenance; a fixed-time full-path test compares every stored result and selection column against Legacy across first/unchanged/corrected/profile/missing-current states. The older package-seam target branch now also reads and writes only through target code. All 142 unittest tests and five ETL checks pass.

Plan changes: mark selected-night reading complete for the synthetic target path. Keep target profile v1 loading/revision and the shared runner transaction as separate later boundaries. No formula, feature builder/writer, schema, production runner, CLI or Legacy snapshot changed.

Reason: the selected feature identity can be migrated independently of profile and runner policy while retaining the existing result fingerprint and revision contract.
