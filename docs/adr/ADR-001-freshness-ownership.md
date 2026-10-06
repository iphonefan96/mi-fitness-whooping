# ADR-001: Freshness ownership

Status: **Accepted for the target architecture** (2026-10-06). This is a design decision, not a change to the running Legacy implementation.

## Context

Phase 1 sleep characterization executes the immutable Legacy calculation, runner, storage and headline code. `calculate_sleep_day()` has no clock input and returns deterministic metric values, calculation statuses and metadata for a fixed dated history/profile. The runner assigns stored metric `freshness_status` from its local date at calculation time. Its unchanged-input fast path does not update that label. The CLI separately computes current sleep freshness from the latest night's date/end and query time (36-hour maximum age) and hides headline values unless `FRESH`. A freshness-only `put_result()` call can report a change while selecting the same fingerprinted row and leaving its old stored label.

Consequently, stored `FRESH` and query-time `STALE` can coexist. This is known Legacy behavior, characterized in `tests/characterization/test_legacy_sleep_core.py`. The source and analytics schemas and CLI output are locked for the behavior-preserving Sleep Core V1 migration.

## Decision

- Pure metric calculations, including Sleep Core, receive no current wall-clock time and perform no `FRESH`/`STALE` headline evaluation. Their `VALID`, `CALIBRATING`, `INSUFFICIENT_DATA`, `INVALID` and `REDUCED` calculation statuses are separate from freshness.
- Freshness evaluation belongs outside pure analytics. Orchestration may attach run-time context; presentation or a query service evaluates current display freshness from an explicit query time and published measurement dates/intervals. Storage persists the result/freshness fields required by existing compatibility contracts.
- Sleep Core V1 preserves current observable calculation, storage and CLI behavior. This ADR does **not** authorize repairing stored freshness, changing the 36-hour rule, revising database identity, or changing headline visibility.
- The stored-versus-query-time divergence remains known debt. Changing freshness persistence or display semantics requires a separate feature specification, contract decision, tests and compatibility assessment.

## Alternatives considered

- Put freshness into each sleep calculation: rejected because it makes identical historical inputs produce different pure results as time passes.
- Treat the stored freshness label as the sole display truth: rejected for V1 because the current CLI intentionally re-evaluates at query time and hides stale headline values.
- Fix the divergence during Sleep Core migration: deferred because it would mix a behavior change with a formula-preserving boundary migration.

## Consequences

The canonical Sleep Core input/output contracts carry dated measurements and calculation status, not `as_of` or a presentation freshness decision. An external adapter must preserve existing storage and CLI behavior during V1. The target separation is not yet implemented: Legacy runner, storage and CLI still share freshness responsibilities. The separate freshness feature must decide how stored labels, result identity and query-time status should interact.

## Evidence and review trigger

Evidence: `Legacy/analytics/algorithms/sleep.py`, `Legacy/analytics/runners/runner.py`, `Legacy/analytics/storage/db.py`, `Legacy/analytics/normalization/core.py`, `Legacy/analytics/__main__.py`, and the Phase 1 characterization tests. Revisit this ADR when a dedicated freshness change is specified or when storage/presentation ownership is redesigned; do not silently change it during Sleep Core V1.
