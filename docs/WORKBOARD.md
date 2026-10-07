# Workboard

This board records the current handoff for the Mi Fitness analytics. The writer records its handoff here; only the integrator records a new accepted base after an independent PASS. Project behavior belongs in `CURRENT_STATE.md`; deferred work belongs in `BACKLOG.md`.

- **Last accepted base:** `444f1799406e5913bb2aa421fd55217ba7c00ab8` from `agent/claude-target-run` — **PASS** after independent Codex review (recorded by the integrator in `73a45459d3f1cf0085af03b2d70e4749d5338ab1`).
- **Handing off from:** `agent/claude-target-run` (Claude, writer). **Review range:** `73a45459d3f1cf0085af03b2d70e4749d5338ab1..HEAD` of that branch; the exact HEAD SHA is in the handoff report. Not yet independently reviewed:
  1. Manual-run decision: scheduling deferred to `BACKLOG.md`; README states Python ≥ 3.11 and that `--source`/`--db`/`--profile` have no defaults. Docs only.
  2. Independent Recovery/vitals component (`domain|analytics|integration/recovery_vitals`): `recovery.score` and direct vitals moved out of `baseline`; `baseline/recovery.py` removed. No stored value, status, unit, metadata, version or result order changed.
  3. Handoff rules for multi-commit stages (`AGENTS.md`, `EXECUTION_PROCESS.md`, this board).
- **Evidence from the writer:** full suite 159 passed / 2,764 subtests; randomized Legacy characterization of the component (mutations of a weight and a sample gate were caught); existing full-table Legacy differential scenarios unchanged; one disposable real-data copy: Legacy and target tables equal, repeat `NO NEW ANALYTICS INPUT`, copy removed. No live database, ETL, LaunchAgent or schedule was changed.
- **Status:** Recovery/vitals stage complete; waiting for independent review of the range.
- **Next item (needs user decision):** Activity has no dedicated existing calculation (vendor daily fields plus shared trends), so no Activity component was created. The remaining analytics boundary is the shared baselines/deviations/trends family together with the monitoring coupling; start it only if the user selects it. Scheduling remains in `BACKLOG.md`.

The receiving agent reviews the exact range before writing. One agent writes at a time.
