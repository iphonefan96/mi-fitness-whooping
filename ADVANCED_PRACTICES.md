# ADVANCED_PRACTICES.md

Additional practices for AI-assisted software development.

These rules complement `AGENTS.md` and `EXECUTION_PROCESS.md`.

The purpose is to reduce context drift, accidental coupling, unsafe broad changes, and repeated rework.

---

# 1. Keep Root Context Small

The root agent instruction file should be a map, not an encyclopedia.

`AGENTS.md` should contain:

- core workflow rules
- important invariants
- build/test commands
- pointers to deeper documentation

Detailed knowledge belongs in dedicated files under `docs/`.

Avoid continuously growing `AGENTS.md`.

When documentation becomes domain-specific, move it closer to the relevant module or feature.

---

# 2. Use Local Instructions for Complex Areas

Large repositories may have local agent instructions near important subsystems.

Example:

```text
AGENTS.md

src/
  ingestion/
    AGENTS.md

  analytics/
    AGENTS.md

  storage/
    AGENTS.md
```

A local instruction file should only contain rules that differ from or refine repository-wide rules.

Do not duplicate the root rules everywhere.

Useful local rules include:

- module-specific invariants
- allowed dependencies
- module test commands
- storage restrictions
- expected input/output models

---

# 3. Prefer Tests Before Implementation for High-Risk Behavior

For behavior with clear expected inputs and outputs, consider this workflow:

1. define expected behavior
2. write regression/contract tests
3. confirm the tests fail for the expected reason
4. checkpoint/commit the tests
5. implement the feature
6. do not weaken the tests to make implementation pass
7. run independent review after tests pass

This is especially valuable for:

- calculation algorithms
- database migrations
- parsing
- backward compatibility
- bug fixes
- public contracts

Not every trivial change requires TDD.

---

# 4. Separate Builder and Reviewer Roles

For important changes, the same implementation session should not be the only reviewer.

Use a separate AUDIT or REVIEW pass whose job is to find problems rather than continue implementation.

Reviewer questions:

- Does the implementation actually satisfy the original feature spec?
- Did public contracts drift?
- Were tests weakened?
- Is there hidden coupling?
- Are edge cases missing?
- Did the implementation solve the test rather than the problem?
- Was unrelated code modified?

The reviewer should inspect the final repository state rather than trusting the implementation report.

---

# 5. Limit Blast Radius

Each task should have an explicit allowed change area.

Example:

```text
Expected scope:
- src/analytics/sleep/**
- tests/analytics/sleep/**

Possible integration change:
- src/orchestration/analytics_pipeline.py

Do not modify:
- ingestion
- source database schema
- unrelated analytics modules
```

If a task suddenly requires broad changes outside its expected scope, stop and reconcile before proceeding.

Large unexpected blast radius is an architecture signal.

---

# 6. Prefer Reversible Changes

Where practical, structure changes so they can be rolled back independently.

Prefer:

- small commits
- feature branches
- isolated migrations
- compatibility layers
- additive schema changes before destructive changes

Avoid mixing:

- refactor
- migration
- new feature
- unrelated cleanup

inside one irreversible change.

---

# 7. Use Mechanical Guards

Important architecture rules should not exist only in prose.

Where practical, encode them as checks.

Examples:

- tests asserting source DB is read-only
- dependency/import boundary tests
- schema compatibility checks
- lint rules
- type checks
- migration tests
- CI checks
- generated schema diffs

If an invariant matters repeatedly, automate its verification.

---

# 8. Automate Routine Verification

Agents should not have to remember common checks manually.

Where supported, use hooks, scripts, CI, or task runners to automatically execute:

- formatter
- linter
- type checker
- targeted tests
- schema validation
- import-boundary checks

Typical commands should be documented in the repository.

A coding task should end with a deterministic verification command whenever possible.

---

# 9. Context Should Follow the Task

Do not inject every project document into every task.

A task should read:

1. repository-level rules
2. current project state
3. architecture
4. the relevant feature spec
5. only the domain documentation required for that task

For example, a sleep scoring task normally should not need detailed documentation about UI rendering or unrelated ingestion internals.

Relevant context is better than maximum context.

---

# 10. Treat Generated Documentation Separately

Some documentation should be generated from code rather than manually maintained.

Examples:

- database schema
- CLI command reference
- dependency graph
- API schema
- configuration reference

Put generated material under a clearly labeled directory such as:

```text
docs/generated/
```

Do not manually edit generated artifacts.

Regenerate them when their source changes.

---

# 11. Track Documentation Freshness

Documentation drift is an engineering bug.

For critical docs, record:

- last verified date
- related module
- current status
- relevant commit when useful

Audit stale documentation during major feature work.

Delete obsolete guidance instead of accumulating contradictory instructions.

---

# 12. Use Explicit Risk Levels

Before implementation classify work approximately as:

LOW
- local change
- strong tests
- no persistent data change

MEDIUM
- multiple modules
- public interface change
- orchestration change

HIGH
- destructive migration
- persistent data compatibility
- security/privacy boundary
- broad architecture change

Higher risk should increase:

- design effort
- test requirements
- checkpoints
- review independence
- rollback planning

---

# 13. Do Not Parallelize Coupled Work Prematurely

Parallel agents are useful only when tasks have stable boundaries.

Good parallel work:

- independent feature modules behind fixed contracts
- documentation and test fixture preparation
- independent audits

Bad parallel work:

- two agents editing the same unstable interface
- architecture and implementation happening simultaneously without a contract
- multiple migrations changing the same schema

Stabilize shared contracts first.

---

# 14. Use Integration Tasks Explicitly

Do not assume independent modules automatically form a working feature.

Create explicit integration tasks.

An integration task should verify:

- contracts match
- data moves correctly across boundaries
- orchestration order is correct
- errors propagate correctly
- persistence is correct
- end-to-end behavior works

Integration is a first-class implementation phase.

---

# 15. Preserve Known-Good Behavior With Characterization Tests

When restructuring legacy or poorly understood code, first capture current behavior.

Use characterization/regression tests before refactoring.

This allows architecture to change while making accidental behavioral changes visible.

Especially useful when:

- existing code works but is messy
- formulas are already trusted
- historical outputs must remain reproducible
- documentation is incomplete

---

# 16. Prefer Migration Over Rewrite

For a working project, default to incremental migration rather than a complete rewrite.

Suggested sequence:

1. inventory current behavior
2. add tests around important behavior
3. define target boundary
4. introduce new contract
5. move one coherent capability
6. integrate
7. audit
8. repeat

A full rewrite requires unusually strong justification.

---

# 17. Maintain a Decision Log

Use ADRs for decisions likely to matter later.

Do not create ADRs for every small coding preference.

Good ADR candidates:

- storage ownership
- module boundary
- public data model
- migration strategy
- orchestration architecture
- compatibility policy

An ADR should record:

- context
- decision
- alternatives
- consequences

---

# 18. Separate Product Truth From Implementation Truth

Use different documents for different questions.

`PROJECT_SPEC.md`
What are we building and why?

`ARCHITECTURE.md`
How is the current system organized?

`CURRENT_STATE.md`
What actually works today?

`docs/features/*.md`
What does a particular feature promise?

`docs/plans/*.md`
How are we currently implementing it?

`docs/adr/*.md`
Why did we choose important architectural decisions?

Do not merge all of these into one permanent mega-document.

---

# 19. Require Evidence in Completion Reports

An agent saying "done" is not evidence.

A completion report should contain concrete verification such as:

- test command + result
- relevant output
- files changed
- contracts changed
- known deviations
- unresolved risks

For critical changes, inspect the repository/tests rather than relying only on the summary.

---

# 20. Optimize the Environment, Not Just Prompts

When the same mistake happens repeatedly, do not merely add another sentence to prompts.

Ask whether the environment should prevent the error.

Possible fixes:

- better module boundary
- test
- type
- lint rule
- script
- CI check
- local AGENTS.md
- better fixture
- clearer interface
- simpler repository structure

Repeated prompt reminders are often a sign that the repository needs a mechanical guard.

---

# Recommended Repository Knowledge Layout

```text
PROJECT/
├── AGENTS.md
├── README.md
├── PROJECT_SPEC.md
├── ARCHITECTURE.md
├── CURRENT_STATE.md
├── BACKLOG.md
├── EXECUTION_PROCESS.md
├── ADVANCED_PRACTICES.md
│
├── docs/
│   ├── features/
│   ├── plans/
│   │   ├── active/
│   │   └── completed/
│   ├── adr/
│   ├── generated/
│   └── design/
│
├── src/
├── tests/
└── scripts/
```

Do not create directories that the project does not need.

Start simple and add structure when complexity justifies it.
