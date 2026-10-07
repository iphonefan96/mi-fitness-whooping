# Workboard

Shared goal: an independent target `run` for existing Mi Fitness analytics. The local implementation already exists at code baseline `62e4bceaf94a1f97ff2b6473f18d21f1b065d3d4`; installed ETL and LaunchAgent remain unchanged. This board coordinates review and any necessary fixes, not a second rewrite.

| Work | Owner | Branch | Code baseline | Status |
|---|---|---|---|---|
| Target `run` findings and fixes | Claude (executor) | `agent/claude-target-run` | `62e4bceaf94a1f97ff2b6473f18d21f1b065d3d4` | Ready for review/fixes |
| Independent review of exact executor SHA | Codex (reviewer) | `agent/codex-review` | same baseline | Waiting for handoff |

Claude commits only on the executor branch and hands off: **commit SHA; changed behavior/files; test commands and results; remaining Legacy/runtime dependencies; known limits**. Codex reviews that exact SHA from its own worktree and reports **PASS** or **FIX** with file/line and a reproducible reason. Codex does not write to Claude's branch. After PASS, the integrator alone transfers the verified commit to `feature/sleep-core-v1` and pushes it.

Only the integrator edits this board. Agents use synthetic data or their own disposable SQLite copies; they never share a live `analytics.sqlite`. Current behavior and optional work belong in `CURRENT_STATE.md` and `BACKLOG.md`, not here.
