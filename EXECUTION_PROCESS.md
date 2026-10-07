# Execution process

The current project goal is a usable baseline from existing Mi Fitness data and already implemented Legacy analytics. This process is proportional to the change, not a fixed sequence of separate agent tasks.

## For each task

At a branch handoff, first follow `AGENTS.md` and the current `docs/WORKBOARD.md`: identify your worktree and HEAD, review the previous branch's diff from the accepted base, fix confirmed defects, then continue the recorded next task. This is the same task process, not a separate workflow.

1. **Inspect:** read the active plan and relevant contracts, then inspect code and tests. Identify what already works and what the user will be able to do after this task.
2. **Implement:** make a coherent vertical change. Prefer existing code and stable interfaces; avoid speculative abstractions and unrelated refactors.
3. **Verify:** run targeted behavior/compatibility tests with synthetic data. Check reruns and data integrity when storage or orchestration changes. Use broader tests at integration checkpoints.
4. **Report:** show an example input/command and output when possible; state changed contracts, tests, remaining blockers and the next necessary step. Update current-state documentation and put optional work in `BACKLOG.md`.

These activities may happen in one task and one coherent commit. A feature specification or design-only step is useful when the contract is genuinely unclear or risky; it is not a mandatory prelude to every edit. Reconcile the plan when assumptions change. Perform an independent audit before production activation or after a substantial integration, not after every narrow implementation step.

## Boundaries

- Do not mutate personal source files or production databases while testing. Use disposable copies and synthetic fixtures.
- Preserve locked schemas, profile and CLI behavior unless a separately authorized compatibility change is required.
- Keep `Legacy/` as a comparison oracle during migration. Do not route target runtime imports through Legacy merely to finish a task quickly.
- Do not claim that a synthetic path is production. The local target `run` is available, while the installed ETL and analytics job remain Legacy until explicitly switched and verified.
- Keep optional algorithms, UI, new devices, extensive replay redesign and unrelated cleanup in `BACKLOG.md`.

## Completion

The baseline is ready when a supported input can flow through the existing ingest/history and analytics path to a usable date/history result for the already implemented sleep, recovery and available vitals/activity outputs; missing or stale values are identified honestly; relevant synthetic and integration checks pass; and the production activation decision is made from an end-to-end review. This does not require every future metric or a complete rewrite of all Legacy internals.
