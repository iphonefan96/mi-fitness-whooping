# ARCHITECTURE.md

## OVERVIEW

Describe the current architecture as it exists now.

Do not document aspirational architecture here unless clearly labeled.

## MODULES

### <module name>

Responsibility:

Inputs:

Outputs:

Allowed dependencies:

Forbidden dependencies:

Public contracts:

## DATA FLOW

Describe the actual system flow.

Example:

source
→ ingestion
→ canonical/domain
→ analytics/features
→ storage
→ orchestration
→ presentation

## DEPENDENCY RULES

Allowed:

- ...

Forbidden:

- ...

## ORCHESTRATION

Describe how modules are coordinated.

The orchestrator may depend on feature interfaces.

Independent feature modules should avoid unnecessary direct coupling.

## STORAGE

Describe each storage system:

- ownership
- read/write responsibility
- schemas
- migration policy
- safety guarantees

## PUBLIC CONTRACTS

List important stable interfaces.

Mark contracts as:

- ACTIVE
- LOCKED
- DEPRECATED
- EXPERIMENTAL

## GLOBAL INVARIANTS

- ...
- ...

## ARCHITECTURAL TESTS / GUARDS

- ...
- ...

## KNOWN ARCHITECTURAL DEBT

- ...
- ...

## CHANGE RULE

When module boundaries, dependency direction, storage ownership or public interfaces materially change, update this document in the same change.
