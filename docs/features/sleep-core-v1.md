# Feature: Sleep Core v1

## Status

**Reconciled design; Phase 1 characterization complete.** First migration boundary. No target implementation exists. Legacy remains the behavioral reference until migration integration and audit pass.

## Goal

Move only the source-independent behavior of Legacy `sleep.score`, `sleep.need_min` and `sleep.debt_min` behind explicit typed nightly/history contracts. This is initially a **behavior-preserving migration**: the new implementation must reproduce Legacy calculation, status and consumer-visible metadata behavior. Formula or policy changes require a later, separate feature specification.

## User / consumer

The analytics orchestrator supplies dated inputs and receives metric results. Existing analytics storage persists those results. The CLI currently reads the persisted metrics for a freshness-aware sleep headline; a future UI/API may consume the same published results.

## Inputs

Legacy source for this contract: `Legacy/analytics/algorithms/sleep.py:calculate_sleep_day`, receiving a `date`, a `dict[date, FeatureRecord]` of nightly features, and profile JSON from `load_profile`. These are current interfaces, not the proposed canonical signature. The future typed contract is **not yet implemented** and must carry only the behaviorally required information below.

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

## Canonical input contract — conceptual, not implemented

| Category | Minimum information and semantics |
|---|---|
| Required for calculation | Target `date`; presence/absence of a selected main night; current night's TST, deep, REM, WASO, awakening durations and local bedtime; valid local bedtimes from the preceding 14 calendar dates for Score; current plus preceding 13 dated TST values for Debt; effective target minutes and whether the 480-minute fallback was used for each of those 14 ledger dates. Keep absent nights distinct from measured zero. |
| Required for status/gating | Stage coverage/completeness for each debt night and the current score night; `None` versus numeric values; score-valid ranges, positive TST, valid bedtime and awakening inputs; explicit dated history so the five-prior-bedtime, ten-valid-night and maximum-two-gap rules are reproducible. Invalid configured targets remain rejected rather than silently replaced. |
| Required for provenance | Stable, ordered references to the used nightly inputs. Each reference must carry enough identity/quality to reproduce current persisted lineage: date, feature identity/fingerprint, source count and source IDs hash, measurement interval and quality flags. The effective target snapshot and a profile revision or equivalent external configuration identity must be available to the integration adapter. Score references current night then valid prior-bedtime nights in date order; Need references current night; Debt references valid ledger nights in date order. |
| Not part of pure sleep input | Raw Xiaomi rows, SQLite connection or row IDs, profile file path/JSON parsing, current time or `as_of`, stored `freshness_status`, CLI headline fields, run ID, release channel or active-selection ID. |

The canonical input may group these facts differently from Legacy `FeatureRecord`, `SleepScoreInput`, `SleepNeedInput` and `SleepDebtInput`. Exact class names, package paths and serialization are Phase 2 interface choices; this table fixes semantics. Other nightly fields such as HR, SpO2, respiration, sleep session vendor score and activity are unnecessary for these three calculations.

## Outputs and existing observable behavior

All three results are currently `MetricDraft` objects persisted as `derived_metric_results` with active selection. The target contract may use a new canonical type, but integration must preserve the stored names, values, units, statuses, algorithm identity/version, lineage and metadata consumed today. The current algorithm version is `sleep-1`; `source_type` is `OUR_DERIVED` and default confidence is `MEDIUM` for these drafts. Score provenance is Open Wearables commit `fd78bdd3b8ed162e6716ba9c5fa2613dac005a40`; Need provenance is Vitals commit `fb3a837a017567b0fbc3c0c2b5666f8db4acad21`; Debt has no upstream project/commit in Legacy.

| Metric | Unit; algorithm ID | Value and status | Metadata that must remain compatible |
|---|---|---|---|
| `sleep.score` | `score`; `sleep.open_wearables_four_pillar_v1` | Integer weighted score when all four components are available: duration 40%, stages 20%, consistency 20%, interruptions 20%; `VALID`. Otherwise `None`: `INSUFFICIENT_DATA` if stage coverage is incomplete or one of `tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min` is `None`; otherwise `CALIBRATING` for fewer than five valid prior bedtimes; otherwise `INVALID` for remaining invalid component inputs. A missing bedtime or zero TST with sufficient history is `INVALID`, not `INSUFFICIENT_DATA`. | `mode` (`FULL` or `None`), `components` (component score map or `None`), `history_count`, `required_history_count: 5`, `history_window_calendar_nights: 14`. Current provenance names Open Wearables and its pinned upstream commit. Inputs are current night plus valid prior-bedtime nights. |
| `sleep.need_min` | `min`; `sleep.fixed_target_v1` | Effective target value; `VALID` for a configured target, `REDUCED` for the fixed 480-minute fallback. It is explicitly **not** a physiological estimate. | `mode` (`USER_TARGET` or `PROVISIONAL_DEFAULT`), `default_target`, `physiological_estimate: false`. Input is the current night. Current provenance names Vitals and its pinned upstream commit. |
| `sleep.debt_min` | `min`; `sleep.signed_14_calendar_night_ledger_v1` | For a ready ledger, `max(0, -sum(TST - target))`: `VALID` if all ledger targets were configured, `REDUCED` if any used fallback. Otherwise value `None`, status `CALIBRATING`. Surplus is retained in the signed balance metadata, while exposed debt is nonnegative. | `mode`, `default_target`, `signed_balance_min`, `history_count`, `required_history_count: 10`, `longest_missing_gap`, `window_calendar_nights: 14`. Inputs are only ledger nights with valid positive complete-stage TST. |

The existing score component details, rounding and validity gates in `score_components()` are part of the behavior to preserve, not an invitation to redesign them. Existing `sleep_headline()` only exposes current numeric values when freshness is `FRESH`; historical statuses remain visible. Result-level `freshness_status` is managed by runner/storage and must not be silently conflated with score validity.

Characterization shows two separate clock policies. On a calculation run, the runner labels metric results `HISTORICAL` for a date before local today, `FRESH` for today and `STALE` for a future date. A no-input-change rerun returns early and does not refresh stored labels. The status/headline path separately evaluates the last night's date/end against query time with a 36-hour maximum age: it can hide current values as `STALE` while a stored metric row still says `FRESH`. Direct `put_result()` with only a changed freshness label also reselects the existing fingerprinted row without updating that stored label. This observed discrepancy is **not** a new desired policy; preserve existing presentation output in this migration and resolve a new freshness policy only through a separate contract decision.

## Canonical output contract — conceptual, not implemented

For each present current night, produce one dated result for each of `sleep.score`, `sleep.need_min` and `sleep.debt_min`; with no current night, produce none. Each result has metric name, value or `None`, unit, calculation status, algorithm ID/version, source type, upstream project/commit where present, confidence and the compatible metadata keys/meanings in the table above. The ordered lineage references and resolved-target/configuration identity must make its input set reproducible. `components`, `signed_balance_min`, history counts and gate diagnostics remain output metadata because they are stored and consumer-visible today.

The domain result may expose an opaque deterministic calculation-input identity, but the **persisted** `input_fingerprint` is currently computed by `analytics.storage.db.put_result()` from metric name/date, ordered feature fingerprints, metadata, status, value, profile revision and normalization/algorithm/implementation/contract versions. Source-policy version and release channel also participate in storage selection outside that digest. The canonical contract must carry sufficient information for the integration adapter to reproduce existing identity and unchanged-input revision behavior. The pure result does **not** own `result_id`, `supersedes_result_id`, active selection, release channel, run ID, database schema or `freshness_status`. Exact fingerprint encoding and storage keys remain a compatibility concern of the adapter, not a pure sleep formula.

## Contract classification for V1

| Class | Items |
|---|---|
| **LOCKED BEHAVIOR** | The three metric names, formulas/rounding, units, status branch order, history/quality gates, 480-minute fallback, target range rejection, relevant metadata meanings, current headline visibility and current persistent compatibility. No formula or freshness redesign in V1. |
| **STABLE CONTRACT** | Dated current/history measurements, per-date effective targets and fallback flags, stage completeness, missing-versus-zero distinction, ordered input lineage, calculation result fields and algorithm/provenance identity. This is a semantic contract; no target type exists yet. |
| **INTERNAL IMPLEMENTATION DETAIL** | Legacy private helpers and dataclass layout, dictionary construction strategy, SQLite query implementation and numeric `result_id` values. Existing database schema and observable active-selection behavior are still locked at integration. |
| **DEFERRED DECISION** | Exact target type names/package layout for Phase 2; a new freshness persistence/query policy; optional domain hash representation; future physiological Sleep Need, formula improvements, other sleep metrics and broader storage redesign. |

## Module ownership and dependencies

Proposed primary owner: target analytics/sleep boundary. The canonical domain owns input/output contracts; orchestration assembles history and invokes calculation; storage maps canonical results to the unchanged persistence contract; presentation displays published results. These owners are proposals, not existing modules.

Allowed: canonical date/quality/lineage contracts and effective profile values supplied through an explicit boundary. Forbidden: direct SQLite access, CLI/presentation imports, Xiaomi-specific record or path assumptions, and imports of another feature's implementation-specific `MetricDraft`.

## Public contracts

- **EXISTING:** `calculate_sleep_day(day, nights, profile)` returns current `MetricDraft` objects; runner, storage and CLI consume the resulting metrics.
- **NEW, semantically settled above but not implemented:** typed, source-independent nightly/history input and result contracts. They must preserve Legacy behavior and lineage without making algorithms depend on SQLite rows or presentation models. Phase 2 will choose exact type signatures; package paths are not locked here.

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
- [ ] Typed input/output contracts cover only necessary sleep-core fields and represent missing versus measured zero distinctly.
- [ ] New pure calculation matches Legacy score components, weighted score, fallback target and debt ledger on characterized cases, including invalid/cold-start cases.
- [ ] Integration emits the same three metric names, units, statuses, algorithm IDs/version, provenance and relevant metadata through existing orchestration/storage interfaces without schema or CLI changes.
- [ ] Unchanged reruns and historical corrections exhibit the same active-result behavior; source DB remains read-only.
- [ ] Existing 5 ETL checks and 62 unittest tests remain passing; new contract/regression/integration tests pass without personal data.
- [ ] Independent audit compares the final repository to this specification and confirms no unrelated boundary or behavior changed.

## Test strategy

Phase 1 characterized Legacy using synthetic nightly `FeatureRecord`s/profile v1 entries. It covers no current night; full score; missing/invalid components; stage incomplete; measured zero versus missing; five versus four prior bedtimes; 14-night window; configured and fallback need; target range rejection; debt with 9/10 valid nights, two/three missing in a row, surplus repayment, a changed historical night, and effective-dated targets. It pins metadata/status branches, storage fingerprint/active selection and fixed-time headline behavior. Later phases must compare new results against this oracle without editing Legacy. No real personal data is needed.

## Integration and compatibility

Orchestration should adapt existing nightly features/profile values into the new contract and return outputs to the existing result persistence interface. Database schema, names and CLI JSON remain unchanged for this migration. Preserve existing input lineage so the revision/fingerprint policy is comparable; investigate any difference before accepting it. Characterization precedes contract design, pure migration, integration and independent audit.

## Risks

- **Low:** isolated formula evaluation on synthetic typed inputs.
- **Medium:** preserving metadata, provenance, profile effective dates, history ordering and storage fingerprints while changing internal types.
- **High if scope expands:** changing schema, CLI output, source ingestion or user history. Such expansion is outside this feature and requires reconciliation.

## Reconciliation log

### 2026-10-06 — Phase 1 characterization

Observed reality: 17 synthetic tests outside `Legacy/` now execute the Legacy sleep algorithm, profile loading, storage identity, runner and freshness/headline helpers. They pin all three metric shapes and representative gates. The score status decision uses a narrower missing-field check than the earlier prose implied: missing bedtime is `INVALID` after history warm-up. Stored result freshness and query-time headline freshness can diverge without source changes; a freshness-only `put_result()` call does not create a new row or update the stored label.

Plan adjustment: clarified the score status branch and separated calculation-time, stored and query-time freshness behavior. A future contract decision must address the freshness discrepancy before any deliberate change to it. Phase 2 remains high-level and has not begun.

Reason: the migration must preserve observed behavior and must not silently reinterpret status or revision identity.

### 2026-10-06 — Formal contract reconciliation

Observed reality: the 17 tests and inspected Legacy code support a pure calculation boundary, but current `calculate_sleep_day()` also resolves profile JSON and emits storage-facing `MetricDraft` references. Persistence fingerprints depend on ordered input identities and result metadata. Freshness decisions remain outside the calculation, with known divergence between stored and query-time labels.

Plan adjustment: settled the conceptual canonical input/output semantics, including ordered lineage and resolved effective targets; left exact target type names and hash representation for Phase 2. Created ADR-001 for freshness ownership. Phase 2 may establish contracts only; algorithm migration stays in Phase 3.

Reason: this keeps the behavior-preserving boundary explicit without freezing Legacy dataclass layout or accidentally moving wall-clock/storage policy into pure sleep analytics.

## Audit result

No target implementation or integration exists. Final feature audit: not started.
