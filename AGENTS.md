# AGENTS.md

This repository is developed with AI coding agents. The current priority is a usable, local, WHOOP-like baseline on existing Mi Fitness data and existing Legacy calculations. Read `PROJECT_SPEC.md`, `CURRENT_STATE.md`, `ARCHITECTURE.md` and the active plan before changing code; inspect the actual implementation. The repository, not an earlier prompt or report, is the source of truth.

## Working rule

Deliver a working vertical slice: existing data → calculation → stored or queryable result → existing CLI or another minimal consumer. Preserve relevant behavior and verify it with synthetic fixtures. Use the smallest change that achieves the current user outcome. Do not create a new abstraction, migration phase or document merely to satisfy a process template.

For a bounded change, design, implementation, tests and documentation can happen in one coherent task and commit. Split work only when a real compatibility, data-integrity or integration risk needs a separate checkpoint. A standalone audit is appropriate before production activation or after a substantial cross-module change, not after every class or adapter.

## Current scope

- Inventory and reuse or adapt calculations already implemented in `Legacy/`: sleep, recovery, available heart-rate/RHR, SpO2, respiratory, stress and activity outputs. Distinguish calculated results from source-only fields. Do not invent formulas or pretend Xiaomi heart-rate samples provide HRV.
- Keep personal data and populated databases out of Git. Use synthetic tests and disposable database copies. Do not mutate the source exports or production `health.sqlite` by hand.
- The local `mi_fitness_whooping run` now uses the target runtime. The installed ETL, analytics job and LaunchAgent remain Legacy until a deliberate deployment decision.
- Put optional enhancements and unrelated debt in `BACKLOG.md`. Do not implement them as part of the baseline unless they block correct operation.

## Contracts and verification

Preserve deployed source formats, persistent schemas and paths, profile JSON v1, metric identities/statuses/metadata, and existing CLI behavior unless the current task explicitly authorizes a change. A proposed target interface is not an implemented contract. If a locked contract must change, explain the evidence and scope before changing it.

Tests should protect observable behavior and real risks: missing data, reruns, selected revisions, historical corrections, rollback and compatibility where the change touches them. Avoid tests that merely repeat implementation logic. Run the relevant existing suite; use a full suite at an integration checkpoint. Keep `Legacy/` unchanged while it serves as the behavior oracle unless the user explicitly changes that policy.

After a task, report what works end to end, contracts changed, tests run, remaining risks and the next *necessary* step. Update `CURRENT_STATE.md` when implementation changes; update architecture/specifications only when their factual contracts change. Historical ADRs record past decisions and should not be rewritten to make them look current.

## Agent handoff

At every new session, identify the current worktree, branch and HEAD. Read `ARCHITECTURE.md`, `CURRENT_STATE.md`, the active plan and `docs/WORKBOARD.md`; inspect the actual code before acting. Determine the last accepted base and the handoff branch from the workboard. Review that branch's HEAD and diff from the accepted base first. Fix confirmed defects in your own branch and verify them before taking the next workboard task. Do not treat a previous report as proof.

Only one agent writes at a time. A writer may complete a substantial stage in several related commits without pausing between them. At a handoff, leave the worktree clean and report the exact commit range from the last accepted base, changed behavior, tests and remaining blockers. The receiving agent independently reviews that exact range before building on it. Pause after handing off; do not start the next stage in the same turn.

Use separate branches and worktrees for implementation and review. The writer owns the current task; the reviewer checks a named commit SHA without editing the other branch. The writer records its own handoff (range, status, next item) in `docs/WORKBOARD.md`. Only the integrator records a new accepted base after an independent PASS, moves reviewed commits to the shared branch, and pushes it. Use synthetic data or separate disposable SQLite copies; never share a live analytics database between agents.

## Source-of-truth priority

1. Explicit current user/task instruction
2. Actual code, data contracts and verified behavior
3. Feature specification and locked invariants
4. `ARCHITECTURE.md` and `PROJECT_SPEC.md`
5. `CURRENT_STATE.md` and the active plan
6. Older plans, ADR context and comments
