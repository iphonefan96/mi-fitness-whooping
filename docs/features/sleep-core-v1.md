# Feature: Sleep Core v1

## Status

**Phases 1–3, Phase 4A/B characterization, Phase 4C1/4C2, Storage Phases A–C and selected-night read integration complete synthetically; Phase 4C3 not implemented.** Canonical types, a pure calculator, input/storage projections, a Sleep-only synthetic orchestrator, target-owned result persistence and an active-night reader exist under `src/mi_fitness_whooping/`. Production still uses Legacy. Legacy remains the behavioral reference until full migration integration and audit pass.

## Goal

Move only the source-independent behavior of Legacy `sleep.score`, `sleep.need_min` and `sleep.debt_min` behind explicit typed nightly/history contracts. This is initially a **behavior-preserving migration**: the new implementation must reproduce Legacy calculation, status and consumer-visible metadata behavior. Formula or policy changes require a later, separate feature specification.

## User / consumer

The analytics orchestrator supplies dated inputs and receives metric results. Existing analytics storage persists those results. The CLI currently reads the persisted metrics for a freshness-aware sleep headline; a future UI/API may consume the same published results.

## Inputs

Legacy source for this contract: `Legacy/analytics/algorithms/sleep.py:calculate_sleep_day`, receiving a `date`, a `dict[date, FeatureRecord]` of nightly features, and profile JSON from `load_profile`. These remain the production interfaces. `SleepCoreInput` and `calculate_sleep_core()` are implemented but not connected to them.

| Input | Required for | Existing meaning |
|---|---|---|
| Metric date and a main `nightly` feature for that date | All three outputs | No current-night feature → empty result list. Night selection and stage validation belong upstream and are outside this migration. |
| `tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min`, `stage_coverage`, `bedtime_local_min` | Score | Complete staged sleep and valid values are required. `stage_coverage` must be `COMPLETE`; missing/invalid input prevents a score. |
| Up to 14 preceding dated nightly features with valid local bedtimes | Score | At least five prior bedtimes are required; the current bedtime is not counted as prior history. |
| Effective-dated `sleep_target_min` from profile v1 | Need and debt | Missing value uses fixed 480-minute fallback. A configured target must be within 300–720 minutes. |
| Current night plus preceding 13 dated nightly features and their effective targets | Debt | Each date in the 14-calendar-night ledger contributes target and, only with complete stages and positive valid TST, measured sleep. Missing dates remain missing, not zero. |
| Feature identity/lineage required by existing persistence | All outputs | Existing `MetricDraft.inputs` includes current/prior feature records as described below; migration cannot silently change result fingerprints or provenance. |

This feature does not read Xiaomi tables or SQLite. Source freshness is supplied or evaluated by surrounding orchestration/presentation; it is not a sleep formula input.

## Reconciled domain boundary

**Inside pure Sleep Core V1:** deterministic, dated sleep inputs and bounded history; the three existing calculations; calculation status and reproducible component/ledger metadata; algorithm identity and pass-through input lineage needed to identify what was calculated. For the same canonical input, the output must be identical without consulting the clock or a database.

**Outside pure Sleep Core V1:** Xiaomi decoding, main-session choice and stage construction; profile file loading and resolution of effective-dated entries into a per-date target; source change detection; orchestration/replay; SQLite access, revision IDs and active selection; wall-clock freshness, `FRESH`/`STALE` headline decisions, CLI rendering and scheduling. Existing orchestration/storage/presentation adapters remain responsible for their compatibility behavior during V1.

Legacy currently crosses some of these proposed boundaries: `calculate_sleep_day()` resolves profile entries itself and returns `MetricDraft` objects shared with storage, while runner and CLI split freshness decisions. An adapter must supply resolved targets and map a canonical result back to the existing persistence shape when later phases integrate. The boundary therefore requires an explicit compatibility adapter; it cannot be achieved by merely moving `sleep.py` unchanged.

## Canonical input contract

The concrete Phase 2 types live in `src/mi_fitness_whooping/domain/sleep/contracts.py`. `SleepCoreInput` holds the target date, a tuple of `SelectedNight` values ordered by date, `EffectiveSleepTarget` values for the debt ledger, and an opaque profile revision for reproducibility. With a current night, targets cover exactly 14 dates; without one, an empty target tuple is allowed because Legacy returns no metrics before inspecting profile targets. Up to 14 prior nights plus the current night can be represented. `SelectedNight` carries the selected main night's required observations and `stage_complete`; `NightReference` carries immutable source lineage. The contract does not select a main sleep session or resolve a profile file.

| Category | Minimum information and semantics |
|---|---|
| Required for calculation | Target `date`; presence/absence of a selected main night; current night's TST, deep, REM, WASO, awakening durations and local bedtime; valid local bedtimes from the preceding 14 calendar dates for Score; current plus preceding 13 dated TST values for Debt; effective target minutes and whether the 480-minute fallback was used for each of those 14 ledger dates. Keep absent nights distinct from measured zero. |
| Required for status/gating | Stage coverage/completeness for each debt night and the current score night; `None` versus numeric values; score-valid ranges, positive TST, valid bedtime and awakening inputs; explicit dated history so the five-prior-bedtime, ten-valid-night and maximum-two-gap rules are reproducible. Invalid configured targets remain rejected rather than silently replaced. |
| Required for provenance | Stable, ordered references to the used nightly inputs. Each reference must carry enough identity/quality to reproduce current persisted lineage: date, feature identity/fingerprint, source count and source IDs hash, measurement interval and quality flags. The effective target snapshot and a profile revision or equivalent external configuration identity must be available to the integration adapter. Score references current night then valid prior-bedtime nights in date order; Need references current night; Debt references valid ledger nights in date order. |
| Not part of pure sleep input | Raw Xiaomi rows, SQLite connection or row IDs, profile file path/JSON parsing, current time or `as_of`, stored `freshness_status`, CLI headline fields, run ID, release channel or active-selection ID. |

These types group facts differently from Legacy `FeatureRecord`, `SleepScoreInput`, `SleepNeedInput` and `SleepDebtInput`. Negative/out-of-range sleep observations remain representable, as does zero: the Phase 3 calculator applies the existing quality/status gates rather than silently treating those observations as valid. Resolved targets are validated to 300–720 minutes; the default flag is paired with the existing 480-minute fallback. Other nightly fields such as HR, SpO2, respiration, sleep session vendor score and activity are unnecessary for these three calculations.

## Outputs and existing observable behavior

All three results are currently `MetricDraft` objects persisted as `derived_metric_results` with active selection. The target contract may use a new canonical type, but integration must preserve the stored names, values, units, statuses, algorithm identity/version, lineage and metadata consumed today. The current algorithm version is `sleep-1`; `source_type` is `OUR_DERIVED` and default confidence is `MEDIUM` for these drafts. Score provenance is Open Wearables commit `fd78bdd3b8ed162e6716ba9c5fa2613dac005a40`; Need provenance is Vitals commit `fb3a837a017567b0fbc3c0c2b5666f8db4acad21`; Debt has no upstream project/commit in Legacy.

| Metric | Unit; algorithm ID | Value and status | Metadata that must remain compatible |
|---|---|---|---|
| `sleep.score` | `score`; `sleep.open_wearables_four_pillar_v1` | Integer weighted score when all four components are available: duration 40%, stages 20%, consistency 20%, interruptions 20%; `VALID`. Otherwise `None`: `INSUFFICIENT_DATA` if stage coverage is incomplete or one of `tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min` is `None`; otherwise `CALIBRATING` for fewer than five valid prior bedtimes; otherwise `INVALID` for remaining invalid component inputs. A missing bedtime or zero TST with sufficient history is `INVALID`, not `INSUFFICIENT_DATA`. | `mode` (`FULL` or `None`), `components` (component score map or `None`), `history_count`, `required_history_count: 5`, `history_window_calendar_nights: 14`. Current provenance names Open Wearables and its pinned upstream commit. Inputs are current night plus valid prior-bedtime nights. |
| `sleep.need_min` | `min`; `sleep.fixed_target_v1` | Effective target value; `VALID` for a configured target, `REDUCED` for the fixed 480-minute fallback. It is explicitly **not** a physiological estimate. | `mode` (`USER_TARGET` or `PROVISIONAL_DEFAULT`), `default_target`, `physiological_estimate: false`. Input is the current night. Current provenance names Vitals and its pinned upstream commit. |
| `sleep.debt_min` | `min`; `sleep.signed_14_calendar_night_ledger_v1` | For a ready ledger, `max(0, -sum(TST - target))`: `VALID` if all ledger targets were configured, `REDUCED` if any used fallback. Otherwise value `None`, status `CALIBRATING`. Surplus is retained in the signed balance metadata, while exposed debt is nonnegative. | `mode`, `default_target`, `signed_balance_min`, `history_count`, `required_history_count: 10`, `longest_missing_gap`, `window_calendar_nights: 14`. Inputs are only ledger nights with valid positive complete-stage TST. |

The existing score component details, rounding and validity gates in `score_components()` are part of the behavior to preserve, not an invitation to redesign them. Existing `sleep_headline()` only exposes current numeric values when freshness is `FRESH`; historical statuses remain visible. Result-level `freshness_status` is managed by runner/storage and must not be silently conflated with score validity.

Characterization shows two separate clock policies. On a calculation run, the runner labels metric results `HISTORICAL` for a date before local today, `FRESH` for today and `STALE` for a future date. A no-input-change rerun returns early and does not refresh stored labels. The status/headline path separately evaluates the last night's date/end against query time with a 36-hour maximum age: it can hide current values as `STALE` while a stored metric row still says `FRESH`. Direct `put_result()` with only a changed freshness label also reselects the existing fingerprinted row without updating that stored label. This observed discrepancy is **not** a new desired policy; preserve existing presentation output in this migration and resolve a new freshness policy only through a separate contract decision.

## Canonical output contract

`SleepMetricResult` is the single immutable result shape for the closed `SleepMetric` identities and `CalculationStatus` values. Its metadata is one of `ScoreMetadata`, `NeedMetadata` or `DebtMetadata`; Score component diagnostics use `ScoreComponents`. `NightReference` instances are kept in an ordered tuple for lineage. The result type checks metric/unit/metadata pairing, the observed status/value combinations and value ranges; it does not calculate a result.

For each present current night, produce one dated result for each of `sleep.score`, `sleep.need_min` and `sleep.debt_min`; with no current night, produce none. Each result has metric name, value or `None`, unit, calculation status, algorithm ID/version, source type, upstream project/commit where present, confidence and the compatible metadata keys/meanings in the table above. The ordered lineage references and resolved-target/configuration identity must make its input set reproducible. `components`, `signed_balance_min`, history counts and gate diagnostics remain output metadata because they are stored and consumer-visible today.

The domain result may expose an opaque deterministic calculation-input identity, but the **persisted** `input_fingerprint` is currently computed by `analytics.storage.db.put_result()` from metric name/date, ordered feature fingerprints, metadata, status, value, profile revision and normalization/algorithm/implementation/contract versions. Source-policy version and release channel also participate in storage selection outside that digest. The canonical contract must carry sufficient information for the integration adapter to reproduce existing identity and unchanged-input revision behavior. The pure result does **not** own `result_id`, `supersedes_result_id`, active selection, release channel, run ID, database schema or `freshness_status`. Exact fingerprint encoding and storage keys remain a compatibility concern of the adapter, not a pure sleep formula.

## Contract classification for V1

| Class | Items |
|---|---|
| **LOCKED BEHAVIOR** | The three metric names, formulas/rounding, units, status branch order, history/quality gates, 480-minute fallback, target range rejection, relevant metadata meanings, current headline visibility and current persistent compatibility. No formula or freshness redesign in V1. |
| **STABLE CONTRACT** | Dated current/history measurements, per-date effective targets and fallback flags, stage completeness, missing-versus-zero distinction, ordered input lineage, calculation result fields and algorithm/provenance identity, represented by the Phase 2 types in `src/mi_fitness_whooping/domain/sleep/contracts.py` and consumed by the Phase 3 calculator. Phase 4A/B adapters and a synthetic integration test exist but are not wired to production. |
| **INTERNAL IMPLEMENTATION DETAIL** | Legacy private helpers and dataclass layout, dictionary construction strategy, SQLite query implementation and numeric `result_id` values. Existing database schema and observable active-selection behavior are still locked at integration. |
| **DEFERRED DECISION** | A new freshness persistence/query policy; optional domain hash representation; future physiological Sleep Need, formula improvements, other sleep metrics and broader storage redesign. |

## Module ownership and dependencies

The target analytics/sleep boundary owns the pure calculator and the canonical domain owns input/output contracts. The input adapter maps already selected Legacy-shaped features to canonical inputs. The result projection maps canonical outputs to target-owned storage contracts; the old Legacy draft adapter is retained only under tests as a reference. A Sleep-only target orchestrator now coordinates an already-loaded date with explicit run context and a target result-storage sink. Full history/replay orchestration and presentation remain proposed target responsibilities; no target production integration exists.

Pure analytics may import canonical date/quality/lineage contracts and receive effective profile values through an explicit boundary. It must not access SQLite, CLI/presentation, Xiaomi-specific records/paths or another feature's implementation-specific `MetricDraft`. Target runtime result persistence no longer imports Legacy `MetricDraft`; test-only comparison code may still use it as the behavioral oracle.

## Public contracts

- **EXISTING:** `calculate_sleep_day(day, nights, profile)` returns current `MetricDraft` objects; runner, storage and CLI consume the resulting metrics.
- **NEW, Phase 2 contract types and Phase 3 calculation:** `SleepCoreInput`, `SelectedNight`, `EffectiveSleepTarget`, `NightReference`, `SleepMetricResult`, metric/status enums and metric-specific metadata types are consumed by pure `calculate_sleep_core(SleepCoreInput)`. These are not yet production interfaces. Any material contract change requires reconciliation.

## Locked contracts

- Names `sleep.score`, `sleep.need_min`, `sleep.debt_min`; units; algorithm IDs and `sleep-1` version; status/value behavior; metadata keys and meanings listed above; relevant upstream provenance; persistence and active-selection compatibility; the current sleep headline's freshness behavior.
- Profile JSON v1 semantics, effective-dated `sleep_target_min`, 480-minute fallback, 300–720 configured target range, date assignment supplied by upstream nightly features, and source/analytics database schemas and CLI behavior.
- Current formula rules remain locked for V1. Legacy is the comparison oracle until migration audit passes. Freshness ownership follows `docs/adr/ADR-001-freshness-ownership.md`; this migration does not change existing freshness output.

If preservation requires changing a locked contract, stop that part and reconcile the feature specification before implementation.

## Invariants

- Given the same dated nightly inputs and profile, value, status and metadata are reproducible independent of run time.
- No night yields no sleep-core result. Missing sleep data is not treated as measured zero.
- Score requires complete stage coverage, valid component inputs and at least five valid prior bedtimes in the preceding 14 calendar nights.
- Need remains a fixed target/fallback, not a learned physiological calculation.
- Debt uses a 14-calendar-night ledger including the current date, requires at least ten valid nights and a longest missing run of at most two nights. It keeps a signed balance and reports nonnegative debt.
- Invalid or incomplete stage data is never used as valid TST for debt.
- Reruns with unchanged inputs **and unchanged freshness status** preserve active result identity under the existing storage behavior; corrections can revise affected future results. The clock-dependent freshness transition needs separate characterization.
- Legacy source files and personal databases remain untouched.

## Non-goals

No ingestion/reconciliation migration; no sleep stage parsing or main-session selection migration; no new score/need/debt formula; no recovery, activity, vitals or monitoring work; no schema, CLI or UI change; no production deployment; no real personal-data fixture.

## Acceptance criteria

- [x] Phase 1 records representative Legacy outputs before target calculation code is written, including exact values, statuses, metadata and lineage-sensitive cases.
- [x] Typed input/output contracts cover only necessary sleep-core fields and represent missing versus measured zero distinctly.
- [x] New pure calculation matches Legacy score components, weighted score, fallback target and debt ledger on synthetic differential cases, including invalid/cold-start cases.
- [ ] Integration emits the same three metric names, units, statuses, algorithm IDs/version, provenance and relevant metadata through existing orchestration/storage interfaces without schema or CLI changes.
- [ ] Unchanged reruns and historical corrections exhibit the same active-result behavior; source DB remains read-only.
- [ ] Existing 5 ETL checks and 62 unittest tests remain passing; new contract/regression/integration tests pass without personal data.
- [ ] Independent audit compares the final repository to this specification and confirms no unrelated boundary or behavior changed.

## Test strategy

Phase 1 characterized Legacy using synthetic nightly `FeatureRecord`s/profile v1 entries. It covers no current night; full score; missing/invalid components; stage incomplete; measured zero versus missing; five versus four prior bedtimes; 14-night window; configured and fallback need; target range rejection; debt with 9/10 valid nights, two/three missing in a row, surplus repayment, a changed historical night, and effective-dated targets. It pins metadata/status branches, storage fingerprint/active selection and fixed-time headline behavior. Later phases must compare new results against this oracle without editing Legacy. No real personal data is needed.

## Integration and compatibility

Orchestration should adapt existing nightly features/profile values into the new contract and return outputs to the existing result persistence interface. Database schema, names and CLI JSON remain unchanged for this migration. Preserve existing input lineage so the revision/fingerprint policy is comparable; investigate any difference before accepting it. Characterization precedes contract design, pure migration, integration and independent audit.

The Phase 4A input adapter accepts a structural dated active `nightly` map: persisted synthetic scenarios now supply target `SelectedSleepFeature` values, while characterization tests can still supply Legacy `FeatureRecord` fixtures. Profile v1 data and its revision remain loaded at the caller boundary. The adapter projects only the requested date and previous 14 nights into `SelectedNight` values, converts `stage_coverage == "COMPLETE"` to `stage_complete`, retains each source feature's identity/quality fields in `NightReference`, and resolves the current plus previous 13 effective targets with Legacy's 480-minute fallback and 300–720 validation. Resolved target minutes are `float`, as in Legacy `_target()`: using an integer could alter the JSON value in storage's fingerprint even when the numeric value compares equal. It returns an empty-current-night input without evaluating per-date targets, preserving Legacy's early return. It does not read SQLite or choose the main session; feature building and active selection remain upstream.

Phase 4B originally adapted each `SleepMetricResult` to a Legacy `MetricDraft` using original active `FeatureRecord` objects and verified their lineage. That mapping now lives only in `tests/integration/reference_legacy_output.py` for regression comparison. The active target path validates the same selected-feature identity, projects ordered lineage to `StoredFeatureRef`, and publishes `PersistableMetricResult` through target storage. It does not use Legacy drafts or `put_result()`.

The current adapters live in `src/mi_fitness_whooping/integration/sleep/`. ADR-002's distinct package identity is implemented; the earlier 4C1 seam remains test-only historical evidence. Phase 4C2's Sleep-only orchestrator still accepts loaded nights, profile and explicit run context. Storage Phase C changes only its sink: `TargetSleepStore` now opens a target storage session, projects results and applies the caller's cleanup policy through the target repository. Incremental replay clears obsolete active Sleep selections when a night disappears; full replay retains them. Both modes preserve historical rows, as characterized. The synthetic path is not the production runner. Phase 4C3 separately addresses any production switch. `Legacy/` and its installed runner remain immutable.

ADR-003 defines target-owned analytics result storage. Its schema-v3-compatible writer now preserves the current fingerprint, row uniqueness, rerun/reselection, supersession and active-selection behavior on tested synthetic cases. It receives canonical results and ordered selected-feature lineage rather than Legacy `MetricDraft`/`FeatureRecord`, and the synthetic Sleep sink owns one date's transaction. The future full runner must own the broader transaction. A freshness-only write can still report change while reselecting an old row whose stored freshness is unchanged. The incremental/full-replay selection difference remains an explicit compatibility policy input, not a Sleep formula. Production remains on Legacy.

## Selected input implemented; profile boundary remains proposed

Persisted synthetic target callers now use `SqliteActiveNightReader` to obtain active `nightly` rows from existing schema-v3 `active_features`/`features` for the calculation date and previous 14 dates. `SelectedSleepFeature` carries seven raw Sleep observations plus `StoredFeatureRef`, without copying all of `FeatureRecord` or exposing numeric `feature_id` to Sleep Core. The reader preserves gaps and stored identity/provenance, reads through a supplied session without committing, and never builds a night, chooses a main session, recalculates a fingerprint or reads Xiaomi tables. Legacy `active_feature_records()` remains only in synthetic reference/fixture code. The profile is still loaded by Legacy `load_profile()` at the synthetic boundary; the target package imports neither Legacy function.

| Legacy `FeatureRecord` field | Classification | Target handling |
|---|---|---|
| `kind`, `day` | Storage identity / domain date | Reader filters `kind="nightly"`; date keys the selected map and lineage. No arbitrary feature kind enters Sleep Core. |
| `values.tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min`, `bedtime_local_min`, `stage_coverage` | Domain data | Preserve raw `None`, zero, invalid numeric and list content until the existing adapter/calculator gates; only `stage_coverage == "COMPLETE"` becomes canonical `stage_complete`. Current night and bounded history use different subsets. |
| `fingerprint` | Storage identity / provenance | Copy existing `features.input_fingerprint` unchanged into lineage; ordered references determine result fingerprints. |
| `source_count`, `source_ids_hash`, `measurement_start`, `measurement_end`, `quality_flags` | Provenance | Preserve exact selected-row values in ordered `StoredFeatureRef`/`NightReference`; result storage uses them for coverage, signals, bounds and flags. |
| `feature_id`, feature row versions, `quality_status`, feature freshness and other `values` keys | Legacy/storage-only for this Sleep slice | The reader needs `feature_id` internally to follow active selection, but Sleep calculation/result contracts do not consume it. Do not mistake discarded Sleep fields for permission to alter persisted feature rows or other metrics. |
| Run ID, profile revision, source policy, stored freshness, replay cleanup | Orchestration context, not feature fields | Continue supplying them explicitly; do not infer them from the nightly row. |

The profile boundary is a target-owned v1 loader plus dated target resolver. File reading/parsing and full-document revision calculation belong to platform/config; the resolved 14-date `EffectiveSleepTarget` ledger belongs to Sleep input assembly. Legacy `load_profile(None)` or a nonexistent path returns `{"schema_version": 1, "values": []}` and hashes that whole document. A present file requires schema v1/list entries, allowed fields, valid dates/intervals and nonoverlap per field; intervals include both endpoints. The loader only checks positive numeric `sleep_target_min`, while the Sleep resolver rejects configured values outside 300–720 or nonfinite/bool values and uses 480.0 when no effective target exists. Preserve this two-stage behavior and the current error path; do not replace invalid configuration with a fallback. The profile revision must remain the hash of the **whole** v1 document, including fields irrelevant to Sleep, because it participates in persisted identity. With no current selected night, Sleep emits nothing before resolving target dates, while runner-level profile loading/validation still occurs at run entry.

The full runner's date/replay, lock, run-record and transaction lifecycle is separate from this input boundary. Existing `SleepRunContext` covers a single invocation's date, profile revision, run ID, source policy, stored freshness and cleanup decision. It is not a full-runner contract: it does not carry source generation/checkpoints, global lock, shared session or other feature outcomes. `run_sleep_day()` can coordinate a date with preloaded inputs, but `TargetSleepStore` currently opens and commits its own session. It must later accept a caller-owned session before it can join the production transaction. Incremental missing-night cleanup and full-replay retention remain locked behavior.

## Risks

- **Low:** isolated formula evaluation on synthetic typed inputs.
- **Medium:** preserving metadata, provenance, profile effective dates, history ordering and storage fingerprints while changing internal types.
- **High if scope expands:** changing schema, CLI output, source ingestion or user history. Such expansion is outside this feature and requires reconciliation.
- **High for production integration:** synthetic full-row fingerprint/JSON, older-row reselection and one-date rollback now match Legacy, but the full runner's transaction, feature read/write lifecycle, source replay, lock and CLI remain unproven in the target package.

## Reconciliation log

### 2026-10-06 — Phase 1 characterization

Observed reality: 17 synthetic tests outside `Legacy/` now execute the Legacy sleep algorithm, profile loading, storage identity, runner and freshness/headline helpers. They pin all three metric shapes and representative gates. The score status decision uses a narrower missing-field check than the earlier prose implied: missing bedtime is `INVALID` after history warm-up. Stored result freshness and query-time headline freshness can diverge without source changes; a freshness-only `put_result()` call does not create a new row or update the stored label.

Plan adjustment: clarified the score status branch and separated calculation-time, stored and query-time freshness behavior. A future contract decision must address the freshness discrepancy before any deliberate change to it. Phase 2 remains high-level and has not begun.

Reason: the migration must preserve observed behavior and must not silently reinterpret status or revision identity.

### 2026-10-06 — Formal contract reconciliation

Observed reality: the 17 tests and inspected Legacy code support a pure calculation boundary, but current `calculate_sleep_day()` also resolves profile JSON and emits storage-facing `MetricDraft` references. Persistence fingerprints depend on ordered input identities and result metadata. Freshness decisions remain outside the calculation, with known divergence between stored and query-time labels.

Plan adjustment: settled the conceptual canonical input/output semantics, including ordered lineage and resolved effective targets; left exact target type names and hash representation for Phase 2. Created ADR-001 for freshness ownership. Phase 2 may establish contracts only; algorithm migration stays in Phase 3.

Reason: this keeps the behavior-preserving boundary explicit without freezing Legacy dataclass layout or accidentally moving wall-clock/storage policy into pure sleep analytics.

### 2026-10-06 — Phase 2 contract implementation

Observed reality: the minimal domain package now contains immutable typed inputs, ordered lineage, resolved target snapshots, a closed three-metric result identity, compatible calculation statuses and metric-specific metadata. Ten focused contract tests confirm missing-versus-zero, incomplete stages, fallback, history ordering/bounds, output identity and absence of forbidden imports. Review against Legacy's no-current-night early return showed that targets must be optional when no current night exists; the contract permits this case. No calculator or integration code was introduced.

Plan adjustment: exact type names and path are now established; Phase 3 can consume these contracts after this task's verification and reconciliation. The existing formulas, fingerprint storage implementation, freshness policy and CLI remain untouched.

Reason: the types make the agreed boundary executable without prematurely moving algorithms or storage.

### 2026-10-06 — Phase 3 and integration-boundary reconciliation

Observed reality: six differential tests pass alongside ten contract and seventeen Legacy characterization tests. `calculate_sleep_core()` returns only canonical results and has no SQLite, Legacy runtime, wall-clock or persistence dependency. The runner supplies active nightly `FeatureRecord` values, loaded profile v1 data, profile revision and a separate run-time freshness label. Storage derives result identity, aggregate lineage/coverage and active selection from `MetricDraft.inputs`. Legacy `_target()` always returns `float`, while the canonical target contract permits `int`; exact storage fingerprints therefore require float normalization in the adapter. These details require compatibility adapters outside pure analytics. The two `analytics` packages conflict under ordinary import resolution, and immutable Legacy prevents a direct edit to its runner.

Plan adjustment: corrected this file's outdated Phase 2 status, recorded input/output adapter responsibilities and kept the package-loading and orchestration seam as explicit Phase 4 prerequisites. No behavioral contract changed. Phase 4 is split into input adaptation, output/persistence compatibility and a separately gated wiring step.

Reason: the pure calculation matches Legacy, but production identity and CLI compatibility depend on preserving exact feature references and runner/storage ownership.

### 2026-10-06 — Phase 4B and Phase 4C seam design reconciliation

Observed reality: the input and output adapters exist, and synthetic `put_result()` comparisons establish exact draft/fingerprint compatibility for representative cases. Both current `analytics` packages are regular packages; either `PYTHONPATH` order hides one. The immutable Legacy runner imports its sleep calculator directly and offers no sleep injection point.

Plan adjustment: ADR-002 selects `mi_fitness_whooping` as the future target package and an external seam using the existing active-night map and storage. Phase 4C is split into package/seam proof, a synthetic orchestration wrapper, and a separately gated production switch. No target package rename, orchestration entrypoint or production switch has occurred. No locked behavioral contract changed.

Reason: package identity and runner lifecycle must be explicit before a behavior-preserving integration can be claimed.

### 2026-10-07 — Phase 4C1 package and synthetic seam proof

Observed reality: target contracts, pure calculation and both adapters now import as `mi_fitness_whooping.*`; old target package locations were removed. A clean subprocess loads Legacy `analytics` and the new package in either source-root order. Temporary databases seeded through unchanged `put_feature()` and read through `active_feature_records()` demonstrate Legacy-equal drafts and persisted results for default 480.0 and effective-dated 450.0 targets, first write, unchanged rerun and historical correction. The test fixture supplies run ID, profile revision, source policy and stored `HISTORICAL` status explicitly; the adapters and pure calculator read no clock.

Plan adjustment: Phase 4C1 is complete. The proof establishes sleep persistence compatibility on synthetic active features but does not implement a runner, source replay, lock, obsolete-selection cleanup or CLI path. Phase 4C2/4C3 remain separate. No locked formula, schema, freshness or presentation contract changed.

Reason: the tested import and storage boundary is now concrete, while full orchestration remains unimplemented.

### 2026-10-07 — Phase 4C2 synthetic Sleep orchestration

Observed reality: Legacy runner characterization confirms two no-current-night outcomes. Incremental replay clears active sleep selections; full replay skips obsolete cleanup and retains them. Neither deletes historical result rows. A failure during sleep metric persistence rolls back the runner's in-flight transaction; its separate run record becomes `FAILED`. Profile revision participates in every stored sleep fingerprint, so a changed profile revision can revise all three metrics even if Score's value is unchanged.

Plan adjustment: a target Sleep-only orchestrator now accepts already-loaded nights/profile and explicit date, profile revision, run ID, source policy, stored freshness and cleanup mode. A temporary Legacy storage bridge adapts results, owns an isolated single-date transaction and applies only sleep-selection cleanup. It rejects an already-open caller transaction. The target still lacks source replay, global lock/run records, target-owned storage, CLI and production wiring. Existing formulas and locked contracts did not change.

Reason: this reproduces the observed synthetic Sleep lifecycle without treating Legacy storage or types as permanent target architecture.

### 2026-10-07 — Storage Phase C synthetic result-persistence switch

Observed reality: target `TargetSleepStore` now publishes canonical Score, Need and Debt through the target schema-v3 repository/session. It imports no Legacy storage, `MetricDraft` or SQLite. The old output mapping was moved to test-only reference code, and `LegacySleepStore` was removed from the target package. Synthetic full-path tests compare every persisted result column and active selection with Legacy under a fixed timestamp for first/unchanged/corrected/profile-revision and no-current-night replay cases. A target writer failure rolls back the one-date transaction. Input fixtures still use Legacy-shaped selected `FeatureRecord`s; feature read/write and profile loading are not migrated.

Plan adjustment: Storage Phase C is complete for synthetic Sleep only. Reconcile the remaining input/feature and full-runner boundaries before any production switch. No formula, schema, freshness, profile or CLI contract changed.

Reason: target result persistence is now independently usable without making the production runner depend on a partially migrated pipeline.

### 2026-10-07 — Input/profile and runner design reconciliation

Observed: the target Sleep package has no Legacy runtime imports, but synthetic callers still supply active `FeatureRecord` data and a full-document profile revision from Legacy. The seven Sleep observation keys plus existing `StoredFeatureRef` lineage suffice for a narrow target read model; feature row IDs and unrelated nightly values are not Sleep Core inputs. Legacy profile validation and target resolution have separate gates, and its revision hashes the entire v1 document. The current one-date sink transaction does not satisfy future full-runner atomicity.

Decision: first migrate only selected active-night reading over unchanged schema v3, with differential tests. Keep profile file loading/resolution and runner session composition for later bounded tasks. The current formula, public metric contracts, result persistence, production path and Legacy snapshot are unchanged.

### 2026-10-07 — Selected active-night read boundary

Observed: schema v3's `active_features.feature_id` is the selected row identity. `SqliteActiveNightReader` joins that selection to `features`, projects only the seven Sleep fields plus stored fingerprint/provenance, and reads day−14…day inside an existing `AnalyticsSession`. Synthetic tests cover active and older reselected rows, deleted selections despite retained history, bounds/gaps, same-session visibility and full persisted result/selection equivalence with Legacy after historical/current corrections, profile revision and current-night removal. The target synthetic path no longer calls `active_feature_records()`; reference tests still do. No schema, profile loader, feature builder, formula, production or Legacy code changed.

Next: keep profile v1 loader/revision compatibility and future outer-runner transaction composition as separate boundaries. The read step does not establish production readiness.

## Audit result

Canonical contracts, pure target calculation and synthetic target result persistence exist. Production integration and final feature audit have not started.
