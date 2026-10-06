# Execution Plan: Sleep Core v1

Status: **Phases 1–3 implemented; Phase 4 not started.** Feature specification: [`../../features/sleep-core-v1.md`](../../features/sleep-core-v1.md). The repository, feature specification and locked contracts outrank this provisional plan.

## Current phase

Phase 3's pure calculator consumes the Phase 2 contracts and has differential tests against the immutable Legacy oracle. Reconcile this checkpoint before specifying Phase 4 integration details. Production still uses Legacy.

## Rolling-wave phases

1. **Characterization / contract tests.** Detailed below. Capture current values, statuses, metadata and lineage with synthetic inputs while `Legacy/` stays immutable.
2. **Canonical sleep input/output contracts.** Implement only the smallest typed nightly/history and result interfaces justified by Phase 1, with contract tests. Details below.
3. **Pure sleep calculation migration.** Reproduce score, need and debt behind those contracts. Keep formulas and quality gates unchanged.
4. **Integration behind existing orchestration/storage contracts.** Adapt current feature/history input and persist compatible result drafts without schema or CLI changes.
5. **Regression comparison against Legacy.** Compare characterized cases and relevant synthetic end-to-end runs, including reruns and historical correction.
6. **Audit.** Independently check the feature specification, dependency direction, compatibility, tests and change scope.

Only completed Phases 1–3 are detailed. Phases 4–6 remain high-level until reconciliation of the pure calculator and its differential evidence. This plan does not schedule the whole project.

## Completed task — SLEEP-PURE-03

**Scope:** `src/analytics/sleep/core.py` reproduces Legacy Score, fixed-target Need and signed 14-night Debt through `SleepCoreInput` → three `SleepMetricResult` values. It has no Legacy runtime import, SQLite, clock, CLI or orchestration dependency. With no current night it returns an empty tuple before reading targets.

**Verification:** `tests/analytics/test_sleep_core.py` compares observable values, statuses, units, algorithm/provenance identity, metric-specific metadata and ordered lineage with Legacy across synthetic normal, calibration, invalid and historical cases. It checks forbidden dependencies and clock reads. Existing contract and characterization suites remain unchanged.

**Reconciliation:** the existing types carry the required observations and result metadata. Effective-dated profile resolution and invalid profile rejection occur before pure calculation, as designed; Phase 4 must provide that adapter without changing profile v1 semantics. No locked contract or architecture conflict was found. The feature specification's Phase 2 status prose is now stale; this task leaves that file unchanged because no new Legacy behavior required clarification, as the Phase 3 instruction requires. Refresh that status in the next authorized feature-spec reconciliation.

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
- [ ] Reconcile Phase 3 evidence; then detail Phase 4 integration.
- [ ] Phases 4–6 as high-level work above.

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
