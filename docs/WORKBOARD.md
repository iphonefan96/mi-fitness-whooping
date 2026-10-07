# Workboard

This is the current handoff for the usable Mi Fitness analytics baseline. Project behavior is recorded in `CURRENT_STATE.md`; optional work stays in `BACKLOG.md`. Only the integrator edits this board.

- **Last accepted base:** `a9e7f9955a7cf03ce1235559e27106ede8205a8e` (Claude target-run cleanup fix; Codex review PASS).
- **Handing off from:** `agent/codex-review`. The receiver obtains the handoff SHA from that branch's HEAD and the handoff report; it is intentionally not embedded here.
- **Receiving branch:** `agent/claude-target-run`. Review the setup diff from the accepted base before writing. If it passes, fast-forward this branch to the reviewed handoff SHA; do not reset or force-update it.
- **Next task:** Verify the installed analytics wrapper, CLI/status output, profile and database path contracts against the local target `run` using synthetic fixtures and separate disposable SQLite copies. Record the precise compatibility gaps and the decision needed before any scheduled switch. Do not change the installed ETL, LaunchAgent or live databases, and do not add metrics.
- **Blocker:** Scheduled activation needs its own reviewed deployment decision; the installed job remains unchanged.

At the next stop, leave one coherent commit and report its SHA, changed files/behavior, tests, remaining dependencies and PASS/FIX findings. The next receiver reviews that exact commit before continuing. One agent writes at a time.
