# PROJECT_SPEC.md

## PROJECT

<project name>

## PURPOSE

What problem does this project solve?

## PRIMARY USER / CONSUMER

Who uses the system?

## CORE OUTCOMES

- ...
- ...
- ...

## NON-GOALS

- ...
- ...

## HIGH-LEVEL DATA FLOW

source
→ ingestion
→ canonical/domain representation
→ feature modules
→ orchestration
→ storage/output
→ presentation

Adapt this to the actual project.

## GLOBAL INVARIANTS

- ...
- ...
- ...

## GLOBAL LOCKED CONTRACTS

- ...
- ...

## QUALITY REQUIREMENTS

Examples:

- deterministic processing where applicable
- idempotent reruns
- backward compatibility
- explicit module boundaries
- test coverage for critical behavior
- reproducible analytics/results

## DEFINITION OF PROJECT SUCCESS

- ...
- ...
- ...

## DOCUMENTATION RULE

This specification defines the long-term project goal.

It should change rarely.

Current implementation state belongs in `CURRENT_STATE.md`.
Architecture details belong in `ARCHITECTURE.md`.
Feature-specific behavior belongs in `docs/features/`.
