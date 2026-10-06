# Execution Plan: Sleep Core v1

Status: **Active design plan; implementation not started.** Feature specification: [`../../features/sleep-core-v1.md`](../../features/sleep-core-v1.md). The repository, feature specification and locked contracts outrank this provisional plan.

## Current phase

Phase 1 — characterize existing Legacy behavior and pin contract tests. Do not migrate formulas until this phase passes and its observations are reconciled with the feature specification.

## Rolling-wave phases

1. **Characterization / contract tests.** Detailed below. Capture current values, statuses, metadata and lineage with synthetic inputs while `Legacy/` stays immutable.
2. **Canonical sleep input/output contracts.** Define the smallest typed nightly/history and result interfaces justified by Phase 1; reconcile the feature specification if an assumption was wrong.
3. **Pure sleep calculation migration.** Reproduce score, need and debt behind those contracts. Keep formulas and quality gates unchanged.
4. **Integration behind existing orchestration/storage contracts.** Adapt current feature/history input and persist compatible result drafts without schema or CLI changes.
5. **Regression comparison against Legacy.** Compare characterized cases and relevant synthetic end-to-end runs, including reruns and historical correction.
6. **Audit.** Independently check the feature specification, dependency direction, compatibility, tests and change scope.

Only Phase 1 is detailed. Reconcile before detailing later phases; do not create a whole-project migration schedule from this plan.

## Active task — SLEEP-CHAR-01 (next task, not executed by this documentation change)

**Goal:** establish an executable behavior baseline for `sleep.score`, `sleep.need_min` and `sleep.debt_min` before target implementation.

**Scope:** add non-personal characterization/contract tests outside `Legacy/`. Import or invoke frozen Legacy code as the oracle without changing it. Capture exact output fields that consumers/persistence depend on, not merely formula totals. A fixture helper may construct dated `FeatureRecord` values; avoid a production module or new schema.

**Cases to pin:**

- No current night and a valid complete night.
- Four versus five valid prior bedtimes within the preceding 14 dates; bedtime/score component boundaries, score rounding, complete versus incomplete stages and absent/invalid component inputs. Record `VALID`, `CALIBRATING`, `INSUFFICIENT_DATA` and reachable `INVALID` behavior.
- Configured effective-dated targets versus 480-minute fallback, valid target bounds and invalid target rejection; preserve `REDUCED`/`VALID` need status and `physiological_estimate: false`.
- Debt ledger over 14 calendar dates: 9 versus 10 valid staged nights; longest missing run of two versus three; measured zero versus missing; signed balance, nonnegative displayed debt, repayment and profile target changes.
- Exact metric names, units, algorithm IDs/version, upstream provenance where present, metadata keys/values, and `MetricDraft.inputs` identities/order relevant to persistence fingerprints.
- Where practical, a synthetic runner/storage example for unchanged rerun and one historical correction, without reading external personal DBs.

**Likely files:** a new test location outside `Legacy/` selected in the next task. This plan does not prescribe a target package layout.

**Contracts affected:** tests characterize existing behavior; no production public interface changes. **Locked:** Legacy code, database schemas, CLI/output, profile v1 semantics, the three metric names/statuses/metadata and existing formulas.

**Verification:** run the new characterization tests, the existing 62 unittest tests, and the standalone 5 ETL checks with bytecode writing disabled. Confirm all fixtures are synthetic, `Legacy/` is unchanged and no target implementation appeared. Review the captured expectations against `Legacy/analytics/algorithms/sleep.py` and `docs/features/sleep-core-v1.md`.

**Expected result:** a failing or passing oracle-backed specification of existing behavior that future migration must satisfy, plus a concise reconciliation note if a documented expectation differs from actual Legacy behavior. Do not weaken tests to match a future implementation.

## Completed tasks

- [x] Factual Legacy architectural inventory completed in the preceding design task.
- [x] Project, architecture, current-state, feature and rolling-wave plan documentation established in this documentation checkpoint.

## Remaining tasks

- [ ] SLEEP-CHAR-01 characterization and contract tests.
- [ ] Reconcile findings and detail Phase 2 only after Phase 1 evidence.
- [ ] Phases 2–6 as high-level work above.

## Risks and reconciliation log

The main risk is accidentally treating a proposed typed contract as already implemented or preserving only numeric formulas while losing statuses, metadata or revision identity. `Legacy/` is the behavior oracle and remains immutable. No implementation reconciliation has occurred yet.
