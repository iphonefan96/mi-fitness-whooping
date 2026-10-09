# Workboard

This board records the current handoff for the Mi Fitness analytics. The writer records its handoff here; only the integrator records a new accepted base after an independent PASS. Project behavior belongs in `CURRENT_STATE.md`; deferred work belongs in `BACKLOG.md`.

- **Last accepted base:** `444f1799406e5913bb2aa421fd55217ba7c00ab8` from `agent/claude-target-run` — **PASS** after independent Codex review (recorded by the integrator in `73a45459d3f1cf0085af03b2d70e4749d5338ab1`).
- **Handing off from:** `agent/claude-target-run` (Claude, writer). **Review range:** `73a45459d3f1cf0085af03b2d70e4749d5338ab1..HEAD` of that branch; the exact HEAD SHA is in the handoff report. Not yet independently reviewed:
  1. `1cc9701` Manual-run decision: scheduling deferred to `BACKLOG.md`; README states Python ≥ 3.11 and no path defaults. Docs only.
  2. `ef807ea` Recovery/vitals component: `recovery.score` and direct vitals in `domain|analytics|integration/recovery_vitals`; `baseline/recovery.py` removed.
  3. `939b78a` Handoff rules for multi-commit stages (`AGENTS.md`, `EXECUTION_PROCESS.md`).
  4. `9e4e6b5` Shared `domain/metrics.py` (`FeatureLineage`, `MetricResult`) and `integration/metric_results.py`. No behavior change.
  5. `5a46d09` Series component (`baseline.*`, `*.deviation`, `trend.*`) and vitals monitoring (`anomaly.*`, watch, CUSUM) on typed `VitalsBand`; `baseline/monitoring.py` and the monitoring/foundation-draft coupling removed.
  6. `05df7ba` Sleep stage metrics and regularity in `analytics/sleep/stages.py`; `MetricDraft` and `baseline/result_adapter.py` removed; `baseline.foundations` is assembly/order only.
  7. Final docs/handoff commit (this board, plan, dates).
- **Contracts:** no change to schema v3, profile v1, metric names/values/statuses/units/metadata/versions, active selection, persistence order or CLI. Locked Sleep Core V1 contracts untouched.
- **Evidence from the writer:** full suite 169 passed / 7,947 subtests. Randomized and boundary characterization against Legacy for every moved calculation; deliberate mutations of weights, gates and thresholds were caught (surviving mutants led to added boundary cases). Existing full-table Legacy differential scenarios unchanged. Three disposable real-data copies (removed afterwards): Legacy and target tables equal on first run, repeat `NO NEW ANALYTICS INPUT`, after a historical RHR correction and after removing a historical main night. No live database, ETL, LaunchAgent or schedule was changed.
- **Status:** analytics component extraction complete; waiting for independent review of the range.
- **Next item:** Codex reviews the range. After PASS, no further analytics extraction is planned; scheduling, freshness policy and UI/API stay in `BACKLOG.md` until the user selects one. No Activity component (no dedicated existing calculation).

The receiving agent reviews the exact range before writing. One agent writes at a time.
