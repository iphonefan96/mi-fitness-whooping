# Active plan: usable analytics baseline

Updated: 2026-10-08 on `agent/claude-target-run` (component stages below); earlier sections from 2026-10-07 on `feature/sleep-core-v1`. This plan records the local target-runtime integration after `a17250615ac1c09997f978765bffd819656da1c1`; it does not prescribe a new metric or a production scheduler switch. The detailed behavior contract for the three migrated Sleep metrics remains `docs/features/sleep-core-v1.md`.

## Goal and current result

The local `./mi-fitness-whooping run|day|history` path exposes existing Mi Fitness sleep, Recovery, available vitals, stress and activity behavior without a Legacy runtime import. The installed ETL still creates `health.sqlite`; its wrapper and LaunchAgent have not changed. The target runner reads that source, builds the same nightly/daily features, loads profile v1, computes existing metrics, writes schema-v3 results and serves a dated JSON response. Sleep Score, Need and Debt use target Sleep Core and active-night reader; the other baseline calculations are behavior-preserving ports. No HRV or new formula is invented.

The runner owns one analytics lock and transaction. `TargetSleepStore` accepts that existing session, so Sleep results commit or roll back with features, other results and state. Its standalone session remains for isolated tests. Pure calculations do not read SQLite or the clock. `day`/`history` remain read-only presentations of active selections and stored freshness.

## Verification completed in this task

- Synthetic Legacy differential scenarios cover normal days, a missing calendar date, incomplete stages, an effective-dated target, unchanged repeat, historical correction, removed current night and a forced mid-run failure. Feature rows, result rows, active selections and full dated/history responses are compared, excluding only operational timestamps and run UUIDs.
- A target-only subprocess runs with `src/` as the sole project import root; no `analytics` Legacy package is loaded.
- Independent Legacy and target runs on two disposable copies of an external analytics database produced matching run summaries, 4,000 feature rows, 98,473 result rows, both active-selection tables, a dated answer and seven-day history. A repeat returned `NO NEW ANALYTICS INPUT`. No personal values were emitted.
- The switched local CLI was rehearsed on fresh disposable copies: `run`, repeat, `day` and `history` passed without Legacy on its import path. Both copied databases passed integrity checks; the source-copy hash was unchanged and read-only responses did not change the analytics-copy hash.

## Current stage: Recovery/vitals component (2026-10-08)

The baseline above is complete and runs manually. The next architectural result is an independent Recovery/vitals component built from the **existing** calculations, in the same shape as Sleep Core: typed domain input → pure calculation → integration adapter → runner-owned persistence.

- **In scope:** `recovery.score` and the direct vitals `rhr.nightly`, `rhr.vendor_daily`, `spo2.nightly_{count,span_min,mean,min,p10}` and `respiratory.nightly_mean`.
- **Out of scope for this stage:** vitals baselines/deviations (`baseline.{rhr,spo2,respiratory}.*`, `*.deviation`) because monitoring consumes them as foundation drafts; trends (shared across all series); monitoring/CUSUM; any formula, status, unit, metadata, version or HRV change.
- **Boundary:** the calculation has no SQLite, CLI, clock, profile parsing, Legacy or `baseline` import. Profile target resolution and feature-record mapping live in the integration adapter. The runner keeps the lock, transaction and persistence order.
- **Acceptance:** complete feature/result/selection rows still equal Legacy in the existing differential scenarios (first run, rerun, missing date, correction, removed night, effective profile target, rollback); a direct characterization compares the component with Legacy `calculate_recovery_day` and `direct_metrics` on varied synthetic histories, including measured-HRV inputs the Xiaomi source does not provide; an import guard proves calculation independence.

**Result:** implemented in `domain/recovery_vitals`, `analytics/recovery_vitals` and `integration/recovery_vitals`; `baseline/recovery.py` is removed and the vitals branch of `baseline.foundations.direct_metrics` calls the component. All acceptance checks pass; no stored value, status, unit, metadata, version or result order changed.

**Activity finding:** Legacy has no dedicated activity calculation. Daily activity and vendor stress are presented from the selected daily feature; `trend.steps.*` and `trend.stress_vendor.*` come from the shared trend function used by vitals and sleep series. An Activity component would therefore be a new abstraction without its own calculation. Extracting the shared baselines/deviations/trends family (and with it the monitoring coupling) is the remaining analytics boundary and needs a user decision before it starts.

## Current stage: shared series statistics and vitals monitoring (2026-10-08)

Selected by the user after the Recovery/vitals stage. Existing calculations only; schema v3, formulas, values, statuses, units, metadata, versions and persistence order stay unchanged.

- **Series component** (`domain|analytics|integration/series`): `baseline.{rhr,sleep_tst,spo2,respiratory}.{band_mean,ewma}`, `{rhr,spo2,respiratory}.deviation` and `trend.{rhr,sleep_tst,spo2,respiratory,steps,stress_vendor}.{14,30,90}d.theilsen`. Input is a per-series map of dated observations with lineage; the adapter owns the feature-field mapping.
- **Vitals monitoring** moves into the Recovery/vitals component: `anomaly.{rhr,spo2,respiratory}`, `health_signal.physiological_watch` and `anomaly.rhr_cusum`. It receives a typed personal band per signal instead of foundation `MetricDraft`s; the adapter maps the series `band_mean` result to that band. This removes the private monitoring/foundation-draft coupling.
- **Shared domain types:** `FeatureLineage` and the calculated `MetricResult` move to `domain/metrics.py`; result projection to the target writer becomes one shared integration function.
- **Stays in `baseline`:** sleep duration/stage/efficiency metrics and `sleep.regularity` (sleep family, not in this stage), source, features, feature store, runner. No Activity component: steps and vendor stress keep their existing trends through the series component.
**Result:** implemented in `domain|analytics|integration/series`, `analytics/recovery_vitals/monitoring.py`, `domain/metrics.py` and `integration/metric_results.py`; `baseline/monitoring.py` and the foundation baselines/trends are removed. All acceptance checks below pass with no stored-row difference. Remaining analytics in `baseline` are the sleep duration/stage/efficiency metrics and `sleep.regularity`.

- **Acceptance:** existing full-table Legacy differential scenarios unchanged; randomized synthetic characterization of series and monitoring against Legacy `baselines`, `trends`, `calculate_monitoring_day` and `calculate_cusum_series`, including CUSUM state carry-over and stale/calibrating bands; import guards for every pure module; a disposable real-data copy comparison.

## Current stage: sleep stage metrics and regularity (2026-10-08)

The last calculations still in `baseline.foundations` are the existing sleep stage family: `sleep.{time_in_bed,total_sleep_time,awake,light,deep,rem}_min`, `sleep.efficiency_pct`, `sleep.{deep,rem,light,awake}_pct` and `sleep.regularity`. Move them into the Sleep area as separate modules (`domain/sleep/observations.py`, `analytics/sleep/stages.py`) without touching the locked Sleep Core V1 contracts or calculator. Then every calculation returns `MetricResult`; the private `MetricDraft` and its persistence adapter are removed, and `baseline.foundations` keeps only the per-date assembly order and `FeatureRecord`.

**Result:** implemented in `domain/sleep/observations.py`, `analytics/sleep/stages.py` and `integration/sleep/stages_adapter.py`; `MetricDraft` and `baseline/result_adapter.py` are removed. All acceptance checks pass with no stored-row difference. The analytics migration out of `baseline` is complete: what remains there is source, features, feature store, profile, per-date assembly and the runner.

- **Unchanged:** formulas, SENSOR_GAP/stage-coverage/consistency gates, statuses, units, metadata, `foundation-2` version and persistence order.
- **Acceptance:** existing full-table Legacy differential scenarios unchanged; randomized characterization against Legacy `direct_metrics` (sleep branch) and `regularity`, including incomplete stages, SENSOR_GAP, inconsistent TST/TIB, bedtime wrap-around and short history; import guard.

## Current stage: ordinary run on realistic source copies (2026-10-08, `agent/claude-skeleton`)

Traced the ordinary `./mi-fitness-whooping run` end to end: launcher → `basic.run_and_read` → `baseline.runner` (lock, profile v1, source adapter, change discovery, features, feature store) → `baseline.foundations` assembly → Sleep Core, sleep stages, Recovery/vitals, series and monitoring components → `storage.sqlite` writer and active selection → `basic` read. No Legacy module is loaded. The first blocker for running this path on real data was the source guard rejecting every WAL-mode copy (the form all natural copies take). Fixed in `baseline/source.py`; see `CURRENT_STATE.md`. No formula, status, result/feature fingerprint, revision or schema changed.

## Current stage: canonical source history barrier (2026-10-08, `agent/claude-source-history`)

The rebuild candidate already provides corrections, CN/RU alternatives with provenance, deletion/tombstone tracking and an idempotent, diffable rebuild; it was not re-implemented. The barrier gap was downstream: analytics could not see candidate corrections of daily aggregates or deletions. Fixed by consuming the candidate's change log in the target runner. Remaining acceptance actions are listed in `BACKLOG.md`.

## Current stage: target-owned ingestion boundary (2026-10-08, `agent/claude-ingestion`)

Ported the verified reconciliation candidate into `mi_fitness_whooping.ingestion` and exposed it as `mi-fitness-whooping reconcile`, so the target import → canonical history → analytics → `day`/`history` path runs without `Legacy/` code. Selection policy and CN/RU equivalence rule are explicit inputs with no defaults. Parity with the candidate is proven by its own test suite, synthetic scenario digests and the local-export digest. Open: the two contract decisions and the NAS/disk checks in `BACKLOG.md`; the installed ETL is not switched.

## Current stage: source contract (2026-10-09, `agent/claude-source-contract`)

`unresolved_exclude` accepted; `strict-v2` added (declared-default schema equivalence, `candidate-v1`/`strict-v1` kept for reproducibility); a missing expected source database stops reconcile with `SOURCE_INCOMPLETE` before any write. Verified on synthetic cases and a fresh NAS snapshot (`CURRENT_STATE.md`). The skeleton is handed to independent review; no new BACKLOG item is started.

## Next necessary boundary

The current handoff branch, accepted base and next writer are recorded only in `docs/WORKBOARD.md`. A receiving agent reviews the previous branch's exact HEAD before continuing this boundary.

The analytics component extraction above is complete and needs independent review of its whole commit range before anything builds on it. No further analytics extraction is planned: what remains in `baseline` (source adapter, feature builders, feature store, profile loading, per-date assembly and the runner's lifecycle/change-discovery SQL) is ingestion/orchestration, and moving it is not required for the baseline. Any next product step (scheduling, freshness policy, UI/API) needs a user decision.

The installed-job compatibility check is complete (see `CURRENT_STATE.md`). By the 2026-10-08 decision, the baseline runs analytics manually through the local target command; scheduling is deferred to `BACKLOG.md` and is not a request to add metrics, rebuild ingestion or rewrite the runner again. Existing old-correction limits and optional product work stay in `BACKLOG.md`.

Earlier rehearsal copies were set to DELETE journal mode because the guard tripped on WAL sidecars; since the WAL fix target runs on WAL-mode copies directly. Read-only backup can update live `-shm` metadata; no live main database or personal values were changed or added to Git.
