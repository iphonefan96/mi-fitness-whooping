# Feature: Sleep Core v1

## Status

**Design; Phase 1 characterization complete.** First migration boundary. No target implementation exists.

## Goal

Move only the source-independent behavior of Legacy `sleep.score`, `sleep.need_min` and `sleep.debt_min` behind explicit typed nightly/history contracts. This is initially a **behavior-preserving migration**: the new implementation must reproduce Legacy calculation, status and consumer-visible metadata behavior. Formula or policy changes require a later, separate feature specification.

## User / consumer

The analytics orchestrator supplies dated inputs and receives metric results. Existing analytics storage persists those results. The CLI currently reads the persisted metrics for a freshness-aware sleep headline; a future UI/API may consume the same published results.

## Inputs

Legacy source for this contract: `Legacy/analytics/algorithms/sleep.py:calculate_sleep_day`, receiving a `date`, a `dict[date, FeatureRecord]` of nightly features, and profile JSON from `load_profile`. The future typed contract is **not yet implemented** and must carry only the fields below.

| Input | Required for | Existing meaning |
|---|---|---|
| Metric date and a main `nightly` feature for that date | All three outputs | No current-night feature → empty result list. Night selection and stage validation belong upstream and are outside this migration. |
| `tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min`, `stage_coverage`, `bedtime_local_min` | Score | Complete staged sleep and valid values are required. `stage_coverage` must be `COMPLETE`; missing/invalid input prevents a score. |
| Up to 14 preceding dated nightly features with valid local bedtimes | Score | At least five prior bedtimes are required; the current bedtime is not counted as prior history. |
| Effective-dated `sleep_target_min` from profile v1 | Need and debt | Missing value uses fixed 480-minute fallback. A configured target must be within 300–720 minutes. |
| Current night plus preceding 13 dated nightly features and their effective targets | Debt | Each date in the 14-calendar-night ledger contributes target and, only with complete stages and positive valid TST, measured sleep. Missing dates remain missing, not zero. |
| Feature identity/lineage required by existing persistence | All outputs | Existing `MetricDraft.inputs` includes current/prior feature records as described below; migration cannot silently change result fingerprints or provenance. |

This feature does not read Xiaomi tables or SQLite. Source freshness is supplied or evaluated by surrounding orchestration/presentation; it is not a sleep formula input.

## Outputs and existing observable behavior

All three results are currently `MetricDraft` objects persisted as `derived_metric_results` with active selection. The target contract may use a new canonical type, but integration must preserve the stored names, values, units, statuses, algorithm identity/version, lineage and metadata consumed today. The current algorithm version is `sleep-1`; `source_type` is `OUR_DERIVED` and default confidence is `MEDIUM` for these drafts. Score provenance is Open Wearables commit `fd78bdd3b8ed162e6716ba9c5fa2613dac005a40`; Need provenance is Vitals commit `fb3a837a017567b0fbc3c0c2b5666f8db4acad21`; Debt has no upstream project/commit in Legacy.

| Metric | Unit; algorithm ID | Value and status | Metadata that must remain compatible |
|---|---|---|---|
| `sleep.score` | `score`; `sleep.open_wearables_four_pillar_v1` | Integer weighted score when all four components are available: duration 40%, stages 20%, consistency 20%, interruptions 20%; `VALID`. Otherwise `None`: `INSUFFICIENT_DATA` if stage coverage is incomplete or one of `tst_min`, `deep_min`, `rem_min`, `waso_min`, `awakening_durations_min` is `None`; otherwise `CALIBRATING` for fewer than five valid prior bedtimes; otherwise `INVALID` for remaining invalid component inputs. A missing bedtime or zero TST with sufficient history is `INVALID`, not `INSUFFICIENT_DATA`. | `mode` (`FULL` or `None`), `components` (component score map or `None`), `history_count`, `required_history_count: 5`, `history_window_calendar_nights: 14`. Current provenance names Open Wearables and its pinned upstream commit. Inputs are current night plus valid prior-bedtime nights. |
| `sleep.need_min` | `min`; `sleep.fixed_target_v1` | Effective target value; `VALID` for a configured target, `REDUCED` for the fixed 480-minute fallback. It is explicitly **not** a physiological estimate. | `mode` (`USER_TARGET` or `PROVISIONAL_DEFAULT`), `default_target`, `physiological_estimate: false`. Input is the current night. Current provenance names Vitals and its pinned upstream commit. |
| `sleep.debt_min` | `min`; `sleep.signed_14_calendar_night_ledger_v1` | For a ready ledger, `max(0, -sum(TST - target))`: `VALID` if all ledger targets were configured, `REDUCED` if any used fallback. Otherwise value `None`, status `CALIBRATING`. Surplus is retained in the signed balance metadata, while exposed debt is nonnegative. | `mode`, `default_target`, `signed_balance_min`, `history_count`, `required_history_count: 10`, `longest_missing_gap`, `window_calendar_nights: 14`. Inputs are only ledger nights with valid positive complete-stage TST. |

The existing score component details, rounding and validity gates in `score_components()` are part of the behavior to preserve, not an invitation to redesign them. Existing `sleep_headline()` only exposes current numeric values when freshness is `FRESH`; historical statuses remain visible. Result-level `freshness_status` is managed by runner/storage and must not be silently conflated with score validity.

Characterization shows two separate clock policies. On a calculation run, the runner labels metric results `HISTORICAL` for a date before local today, `FRESH` for today and `STALE` for a future date. A no-input-change rerun returns early and does not refresh stored labels. The status/headline path separately evaluates the last night's date/end against query time with a 36-hour maximum age: it can hide current values as `STALE` while a stored metric row still says `FRESH`. Direct `put_result()` with only a changed freshness label also reselects the existing fingerprinted row without updating that stored label. This observed discrepancy is **not** a new desired policy; preserve existing presentation output in this migration and resolve a new freshness policy only through a separate contract decision.

## Module ownership and dependencies

Proposed primary owner: target analytics/sleep boundary. The canonical domain owns input/output contracts; orchestration assembles history and invokes calculation; storage maps canonical results to the unchanged persistence contract; presentation displays published results. These owners are proposals, not existing modules.

Allowed: canonical date/quality/lineage contracts and effective profile values supplied through an explicit boundary. Forbidden: direct SQLite access, CLI/presentation imports, Xiaomi-specific record or path assumptions, and imports of another feature's implementation-specific `MetricDraft`.

## Public contracts

- **EXISTING:** `calculate_sleep_day(day, nights, profile)` returns current `MetricDraft` objects; runner, storage and CLI consume the resulting metrics.
- **NEW, to define after characterization:** typed, source-independent nightly/history input and result contracts. They must be sufficient to preserve Legacy behavior and lineage without making algorithms depend on SQLite rows or presentation models. No signature or package path is locked before Phase 2.

## Locked contracts

- Names `sleep.score`, `sleep.need_min`, `sleep.debt_min`; units; algorithm IDs and `sleep-1` version; status/value behavior; metadata keys and meanings listed above; relevant upstream provenance; persistence and active-selection compatibility; the current sleep headline's freshness behavior.
- Profile JSON v1 semantics, effective-dated `sleep_target_min`, 480-minute fallback, 300–720 configured target range, date assignment supplied by upstream nightly features, and source/analytics database schemas and CLI behavior.

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

Before implementation, characterize Legacy using synthetic nightly `FeatureRecord`s/profile v1 entries. Cover no current night; full score; each missing component; stage incomplete; measured zero versus missing; five versus four prior bedtimes; 14-night window; configured and fallback need; target range rejection; debt with 9/10 valid nights, two/three missing in a row, surplus repayment, a changed historical night, and effective-dated target changes. Pin exact metadata and status branches, including `INVALID`, not only numeric values. Include storage fingerprint/active-selection and stale-headline compatibility at integration time. Compare against Legacy without editing it. No real personal data is needed.

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

## Audit result

No target implementation or integration exists. Final feature audit: not started.
