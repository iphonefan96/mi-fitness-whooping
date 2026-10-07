# Workboard

This board records the current handoff for the Mi Fitness analytics baseline. Only the integrator edits it. Project behavior belongs in `CURRENT_STATE.md`; deferred work belongs in `BACKLOG.md`.

- **Last accepted Claude commit:** `1cc97017b720d0089c2b583ddd9760ea1a8a752f` from `agent/claude-target-run` — **PASS after one documentation correction** in the reviewer branch. The correction states the actual CLI contract: `--source` and `--db` are required; `--profile` is optional and uses built-in profile v1 defaults when omitted.
- **Review evidence:** the Claude diff is documentation only, `git diff --check` passed, and the existing synthetic integration suite passed on the accepted history. No production database, ETL or schedule was run.
- **Handing off from:** `agent/codex-review`. The receiving agent obtains the final handoff SHA from that branch's HEAD and report, not from this file.
- **Status:** The local analytics baseline remains manual. Scheduling is deferred; no schedule or installed ETL/LaunchAgent change is authorized in this handoff.
- **Verification limit:** The known installed ETL files and repository do not prove that no other scheduler exists on the host; inspect deployment state before any future activation.

At the next handoff, review the previous branch's exact commit before writing. Leave one coherent commit and report its SHA, changed files, tests and remaining blockers. One agent writes at a time.
