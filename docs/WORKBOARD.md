# Workboard

This board records the current handoff for the Mi Fitness analytics. The writer records its handoff here; only the integrator records a new accepted base after an independent PASS. Project behavior belongs in `CURRENT_STATE.md`; deferred work belongs in `BACKLOG.md`.

- **Last accepted base:** `e388147f240f1e7777e1b3d933cc93781d59a779` — the analytics skeleton chain `73a45459d3f1cf0085af03b2d70e4749d5338ab1..e388147f240f1e7777e1b3d933cc93781d59a779` from `agent/claude-source-contract`, integrated into `feature/sleep-core-v1` by merge. **PASS** for all five ranges, no required fix:
  1. `73a4545..b93a69c` analytics component extraction (`1cc9701` was already integrated via `edfeeed`);
  2. `b93a69c..475ae8a` WAL-mode source copies;
  3. `475ae8a..48df8d4` change-log invalidation of corrected and deleted dates;
  4. `48df8d4..26da697` target-owned reconciliation (`reconcile` subcommand);
  5. `26da697..e388147` `strict-v2`, accepted `unresolved_exclude`, `SOURCE_INCOMPLETE`/`SOURCE_BUSY`.
- **Review independence (limit):** the reviewer was a separate Claude agent of the same model, without the author's context, read-only on detached commits. It is not a different model or a Codex review.
- **Review evidence:** full suite 210 passed; `Legacy/` unchanged; no runtime Legacy import in `src/`. On disposable NAS/export copies (SHA-verified): port `candidate-v1` digest equals the Legacy candidate; `strict-v2` selects the same records as `candidate-v1`; incremental reconcile equals a clean build; target and Legacy analytics tables equal including row order; incremental analytics after corrections/deletions equals a fresh run; `SOURCE_INCOMPLETE` exit 3 leaves the published history unchanged. No live database, ETL, LaunchAgent or schedule was run or changed.
- **Not included:** `agent/claude-freshness` (`a637277`), unreviewed.
- **Open before switching the live path or scheduling:** iPhone → NAS sync completeness is unverified (Synology conflict copies; main `.db` and `-wal` not proven to be one sync); a first build or `--rebuild-from-source` into a new directory has no expected-database list and can publish without a region; retiring an expected source database (including the empty `notlogin` databases) needs a reviewed option; the reconcile output directory has no lock. Other review notes are non-blocking and recorded in `BACKLOG.md`.
- **Status:** accepted and integrated. No next implementation or scheduling task is authorized; the user selects the next step.

The receiving agent reviews the exact range before writing. One agent writes at a time.
