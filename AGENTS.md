# AGENTS.md

This repository is developed with AI coding agents.

The primary goal is not maximum implementation speed.
The primary goal is predictable, modular development with minimal architectural drift and minimal future refactoring.

## Core Development Rule

Do not treat prompts as the unit of development.

The unit of development is:

CONTRACT
→ IMPLEMENTATION
→ VERIFICATION
→ INTEGRATION

Every significant feature must preserve this structure.

## Development Workflow

For non-trivial work, follow this sequence:

1. FEATURE SPEC
2. DESIGN
3. CONTRACTS
4. IMPLEMENT
5. TEST
6. RECONCILE
7. INTEGRATE
8. AUDIT
9. OPTIONAL REFACTOR

Do not skip directly from an idea to a large implementation.

## Before Changing Code

Before implementing a feature:

1. Read this file.
2. Read `PROJECT_SPEC.md`.
3. Read `ARCHITECTURE.md`.
4. Read `CURRENT_STATE.md`.
5. Read the relevant feature specification.
6. Inspect the actual current code.
7. Identify the contracts that must remain stable.
8. Run relevant existing tests when practical.

Never rely only on an old implementation plan.

The repository is the source of truth.

## Feature Development

Every substantial feature should have a specification describing:

- goal
- user-visible result
- inputs
- outputs
- module ownership
- public contracts
- dependencies
- invariants
- acceptance criteria
- testing requirements
- integration requirements

A feature is not complete merely because its internal code exists.

A feature is complete only when:

- its acceptance criteria pass
- its contracts are respected
- required tests exist
- integration is complete
- architectural audit is complete

## Architecture Rules

Prefer coarse stable modules over many tiny modules.

Modules should communicate through explicit contracts.

Avoid implementation-specific dependencies between independent features.

Prefer:

Feature A
Feature B
Feature C
    ↓
Orchestrator

over:

Feature A → Feature B → Feature C

unless the domain genuinely requires that dependency.

The orchestrator may know feature interfaces.

Features should not know unnecessary implementation details of other features.

## Scope Discipline

Only modify files required for the current task.

Do not perform unrelated refactors.

If unrelated technical debt is discovered:

- document it
- add it to `BACKLOG.md`
- do not fix it unless required for correctness

Avoid "while I am here" changes.

## Locked Contracts

If a task identifies a contract as LOCKED:

DO NOT MODIFY IT.

Examples:

- database schemas
- public CLI interfaces
- public Python APIs
- externally consumed models
- source data formats
- persistent file locations

If implementation appears to require changing a locked contract:

STOP implementation of that part and explain why.

Do not silently change the contract.

## Reconciliation

After several implementation tasks, or whenever the implementation diverges from the original assumptions, perform a RECONCILE pass.

A reconcile pass must:

- inspect the current code
- compare it with the feature specification
- compare it with the architecture
- identify architectural drift
- identify obsolete future tasks
- update the remaining implementation plan

Plans are allowed to change.

Feature goals and explicit contracts are not allowed to drift silently.

## Testing

New features require tests appropriate to their risk.

Tests may include:

- unit tests
- integration tests
- contract tests
- regression tests
- persistence tests
- compatibility tests
- architectural dependency tests

Prefer tests that protect behavior and contracts rather than internal implementation details.

Whenever possible verify:

- old behavior still works
- new behavior works
- reruns are safe
- data integrity is preserved
- module boundaries remain intact

## Audit

After completing a substantial feature, perform a separate audit.

The audit should ignore implementation history and evaluate the final repository against the original feature specification.

Check:

- every acceptance criterion
- contract compatibility
- unintended coupling
- duplicated logic
- architecture violations
- unnecessary complexity
- missing tests
- migration risk
- backward compatibility

Do not consider a feature complete before this audit passes.

## Documentation Updates

When architecture or public behavior changes, update the relevant documentation.

Typical files:

- `ARCHITECTURE.md`
- `CURRENT_STATE.md`
- feature specification
- ADR / architecture decision
- `BACKLOG.md`

Documentation must describe the repository that exists now, not the repository that was originally planned.

## Reporting After Tasks

After implementation, report:

### CHANGED
What changed.

### CONTRACTS
Any public interfaces added or changed.

### TESTS
What was run and the result.

### DEVIATIONS
Differences from the feature specification or implementation plan.

### RISKS
Known remaining risks.

### NEXT
Recommended next task.

If no contracts changed, explicitly say so.

If architecture deviated, explicitly say so.

## Source of Truth Priority

When instructions conflict, use this priority:

1. Explicit current user/task instruction
2. Feature specification
3. Locked contracts / invariants
4. `ARCHITECTURE.md`
5. `PROJECT_SPEC.md`
6. `CURRENT_STATE.md`
7. Existing implementation plan
8. Older comments or assumptions

The implementation plan is never more authoritative than the actual repository state.
