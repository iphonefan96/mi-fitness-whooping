# EXECUTION_PROCESS.md

This document defines the standard AI-assisted development workflow for this repository.

The goal is to minimize architectural drift, hidden coupling, repeated refactoring and desynchronization between sequential coding-agent tasks.

## 1. FEATURE

Start from the complete outcome, not from individual code changes.

Define:

- what the feature does
- who/what consumes it
- inputs
- outputs
- acceptance criteria
- invariants
- integration points
- non-goals

Do not start implementation until the feature boundary is reasonably clear.

## 2. DESIGN

Inspect the current repository before proposing implementation.

Design should answer:

- Which module owns the feature?
- Which existing modules are affected?
- What interfaces are needed?
- What dependencies are allowed?
- What dependencies must be avoided?
- What existing contracts must remain stable?
- What data/storage changes are required?
- What testing strategy is appropriate?

For substantial changes, DESIGN should initially avoid modifying code.

## 3. CONTRACTS

Define stable boundaries before implementing dependent modules.

Examples:

- function signatures
- service interfaces
- domain models
- dataclasses
- database schemas
- events
- API structures
- CLI behavior

Dependent tasks should consume contracts rather than implementation details.

## 4. IMPLEMENT

Implementation tasks should be small and atomic.

Each task should ideally change one architectural concern.

Good:

- implement SleepMetrics model
- implement SleepAnalyzer behind existing interface
- add repository persistence
- connect service to orchestrator

Bad:

- rewrite analytics, database, CLI and scheduler in one task

Do not prematurely implement future tasks.

## 5. VERIFY

Every implementation task should have a verifiable end state.

Verification may include:

- targeted tests
- full test suite
- static checks
- schema checks
- output comparison
- regression fixtures

A task is not complete merely because code compiles.

## 6. RECONCILE

The original implementation plan is provisional.

Perform reconciliation when:

- several implementation tasks have completed
- the repository differs from original assumptions
- new dependencies appear
- an interface changes
- a future task now seems unnecessary
- implementation complexity increases unexpectedly

RECONCILE does not necessarily modify code.

It compares:

ORIGINAL FEATURE SPEC
vs
CURRENT IMPLEMENTATION
vs
REMAINING PLAN

Then updates the remaining plan.

## 7. INTEGRATE

Feature modules should be integrated through explicit boundaries.

Prefer a dedicated orchestration/integration layer where appropriate.

Integration should not force independent feature modules to know unnecessary details about one another.

Integration requires tests.

## 8. AUDIT

Audit is a separate phase after implementation.

Audit the final system as if you were reviewing someone else's implementation.

Do not assume earlier implementation decisions were correct merely because they already exist.

Check:

- feature goal
- acceptance criteria
- contracts
- architecture
- coupling
- backward compatibility
- storage behavior
- error handling
- test coverage
- maintainability

## 9. REFACTOR

Refactoring is optional.

Do not refactor simply because cleanup is possible.

Refactor when it:

- removes verified duplication
- restores architectural boundaries
- simplifies a real complexity
- reduces future implementation risk

Refactoring must preserve behavior and pass existing tests.

## Planning Horizon

Use rolling-wave planning.

Near-term tasks may be detailed.

Long-term tasks should remain high-level until the current architecture exists.

Prefer:

Phase A
Phase B
Phase C

over defining exact Prompt 12 before Prompt 2 has been implemented.

## Standard Task Types

Use four main agent task types:

### DESIGN
Inspect and reason. Usually no code changes.

### IMPLEMENT
Implement one bounded change.

### RECONCILE
Compare actual state to the plan and update future work.

### AUDIT
Evaluate completed work against the specification and architecture.

Additional types may include:

- MIGRATE
- TEST
- REFACTOR
- DOCUMENT

## Git Checkpoints

Prefer commits that correspond to coherent architectural checkpoints.

Example:

1. feature specification
2. contracts
3. core implementation
4. storage
5. integration
6. presentation
7. audit fixes

Do not combine unrelated architectural changes into a single checkpoint.

## Definition of Done

A substantial feature is DONE only when:

- feature specification is satisfied
- acceptance criteria pass
- tests exist and pass
- integration is complete
- public contracts are documented
- architecture documentation reflects reality
- audit is complete
- unresolved issues are documented
