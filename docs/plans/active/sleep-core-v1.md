# Execution Plan: Sleep Core v1

Status: **Phase 1 complete; reconcile before Phase 2. Target implementation not started.** Feature specification: [`../../features/sleep-core-v1.md`](../../features/sleep-core-v1.md). The repository, feature specification and locked contracts outrank this provisional plan.

## Current phase

Phase 1 characterization tests pass. Reconcile their findings with the feature specification before detailing Phase 2. Do not migrate formulas yet.

## Rolling-wave phases

1. **Characterization / contract tests.** Detailed below. Capture current values, statuses, metadata and lineage with synthetic inputs while `Legacy/` stays immutable.
2. **Canonical sleep input/output contracts.** Define the smallest typed nightly/history and result interfaces justified by Phase 1; reconcile the feature specification if an assumption was wrong.
3. **Pure sleep calculation migration.** Reproduce score, need and debt behind those contracts. Keep formulas and quality gates unchanged.
4. **Integration behind existing orchestration/storage contracts.** Adapt current feature/history input and persist compatible result drafts without schema or CLI changes.
5. **Regression comparison against Legacy.** Compare characterized cases and relevant synthetic end-to-end runs, including reruns and historical correction.
6. **Audit.** Independently check the feature specification, dependency direction, compatibility, tests and change scope.

Only Phase 1 is detailed. Reconcile before detailing later phases; do not create a whole-project migration schedule from this plan.

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

- [ ] Reconcile the Phase 1 contract findings and detail Phase 2 only after this checkpoint.
- [ ] Phases 2–6 as high-level work above.

## Risks and reconciliation log

The main risk is accidentally treating a proposed typed contract as already implemented or preserving only numeric formulas while losing statuses, metadata or revision identity. Stored result freshness can remain `FRESH` after the query-time headline becomes `STALE`; changing that policy is outside this behavior-preserving migration without a separate contract decision. `Legacy/` is the behavior oracle and remains immutable.

### 2026-10-06 — Phase 1 evidence

Observed: Legacy-backed tests confirmed score status branch order, effective-dated fallback, the 14-night debt ledger, result fingerprint/version behavior and the two freshness layers. A freshness-only persistence call reports a change but keeps the existing stored row/label.

Plan changes: Phase 1 is complete; Phase 2 stays high-level pending explicit reconciliation of the observed contracts. No production implementation or schema task has been added.

Reason: the observed freshness discrepancy and status details must be visible before defining target contracts.
