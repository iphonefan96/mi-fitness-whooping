# FEATURE: <name>

## STATUS

Proposed / Design / Implementation / Reconcile / Integration / Audit / Done

## GOAL

Describe the complete outcome of the feature.

Focus on observable behavior, not implementation.

## USER / CONSUMER

Who or what consumes this feature?

Examples:

- CLI user
- UI
- another analytics module
- scheduler
- API
- storage layer

## INPUTS

List required inputs.

For each input include:

- source
- format/model
- required/optional
- freshness expectations

## OUTPUTS

List outputs.

For each output include:

- format/model
- persistence
- consumer
- compatibility requirements

## MODULE OWNERSHIP

Primary module:

`<module>`

Related modules:

- ...
- ...

Modules that should NOT own this logic:

- ...

## PUBLIC CONTRACTS

Define contracts this feature introduces or consumes.

Mark each contract:

NEW / EXISTING / LOCKED

## DEPENDENCIES

Allowed dependencies:

- ...

Forbidden or undesirable dependencies:

- ...

## INVARIANTS

Examples:

- source database remains read-only
- calculation is deterministic
- reruns are idempotent
- historical results remain reproducible
- CLI compatibility is preserved

## NON-GOALS

Explicitly list what this feature will not attempt to solve.

## ACCEPTANCE CRITERIA

The feature is complete when:

- [ ] ...
- [ ] ...
- [ ] ...
- [ ] ...

Criteria must be objectively verifiable.

## TEST STRATEGY

Required tests:

- unit
- integration
- regression
- contract
- migration
- persistence

Specify important scenarios.

## INTEGRATION

Describe how this feature connects to the rest of the system.

Prefer interface-level integration over implementation coupling.

## MIGRATION / COMPATIBILITY

Existing behavior affected:

- ...

Migration required:

- yes / no

Backward compatibility requirements:

- ...

## RISKS

LOW:
- ...

MEDIUM:
- ...

HIGH:
- ...

## IMPLEMENTATION PHASES

Keep future phases high-level.

### Phase 1
Contracts / prerequisites

### Phase 2
Core implementation

### Phase 3
Persistence / infrastructure

### Phase 4
Integration

### Phase 5
Audit

Detailed tasks should be created only when the relevant phase is reached.

## RECONCILIATION LOG

Record meaningful plan changes.

### <date / checkpoint>

Observed reality:

...

Plan adjustment:

...

Reason:

...

## AUDIT RESULT

Not yet audited.

When complete document:

- acceptance criteria result
- architecture issues
- compatibility result
- test result
- remaining debt
