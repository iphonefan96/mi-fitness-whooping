# Workboard

This is the current handoff for the usable Mi Fitness analytics baseline. Project behavior is recorded in `CURRENT_STATE.md`; optional work stays in `BACKLOG.md`. Only the integrator edits this board.

- **Last accepted base:** `a9e7f9955a7cf03ce1235559e27106ede8205a8e` (Claude target-run cleanup fix; Codex review PASS). Setup handoff `f997ac701dfd28ada3f434457d97b507a39892b8` (docs only) reviewed by Claude: PASS.
- **Handing off from:** `agent/claude-target-run`. The commit to review is that branch's HEAD named in the handoff report.
- **Done (awaiting review):** Installed-job compatibility check, recorded in `CURRENT_STATE.md`. No scheduled analytics job is installed; the LaunchAgent runs ETL only. Database, lock and profile contracts are compatible in both directions on synthetic copies. One defect fixed: target CLI printed a traceback instead of JSON `FAILED` for `OSError`. Gaps: no default paths, no `status`/`validate`/`init`, different `run` output shape, Python ≥ 3.11 required.
- **Next task:** Codex reviews the handoff SHA. After PASS, the user decides how target analytics is scheduled (trigger, explicit paths/profile, interpreter, logs, status command). Do not change the installed ETL, LaunchAgent or live databases before that decision.
- **Blocker:** Scheduled activation needs that reviewed deployment decision; the installed job remains unchanged.

At the next stop, leave one coherent commit and report its SHA, changed files/behavior, tests, remaining dependencies and PASS/FIX findings. The next receiver reviews that exact commit before continuing. One agent writes at a time.
