# Architecture

Last verified: 2026-10-07 against code, synthetic differential tests and disposable database copies. This document distinguishes the **installed pipeline** from the **local target runtime**.

## A. Current architecture

### Installed ingestion and analytics

Xiaomi `DataBase/**/*.db` and SQLite sidecars → stable staging copy → installed incremental `Legacy/mi_fitness_etl.py` → external `health.sqlite` and `state.json`. The installed macOS wrapper and LaunchAgent are unchanged. The separate `Legacy/mi_fitness_reconcile.py` is a candidate, not the installed ETL. Legacy's own `analytics` CLI remains available as a separate reference; no installed job was switched to the local target command.

### Local target `run|day|history`

```text
health.sqlite (read-only)
  → baseline.source.XiaomiAdapter
  → baseline.features.build_nightly/build_daily
  → baseline.feature_store (features + active_features, schema v3)
  → baseline.foundations (per-date assembly)
    + analytics.sleep.{core,stages} + analytics.series.core
    + analytics.recovery_vitals.core/monitoring
  → storage.sqlite (results + active_metric_selection, schema v3)
  → basic.day_report/history_report → JSON CLI
```

`baseline.runner` owns the `.lock`, source fingerprint/checkpoints, dirty-date selection, profile v1 loading/revision hash, run record, stored freshness and one shared `BEGIN IMMEDIATE` transaction. It commits feature, result, active-selection and state changes together, or rolls them back and marks the separately committed run record `FAILED`. `SqliteActiveNightReader` reads active nightly rows for day−14…day inside that session; target Sleep Core computes the three locked Sleep metrics. `TargetSleepStore` accepts the runner's session without committing it. Its original standalone one-date session remains for isolated synthetic use. Independent components calculate over shared `domain.metrics` lineage/result types: `analytics.recovery_vitals.core` (Recovery and direct vitals `rhr.nightly`, `rhr.vendor_daily`, `spo2.nightly_*`, `respiratory.nightly_mean`), `analytics.recovery_vitals.monitoring` (`anomaly.*`, `health_signal.physiological_watch`, `anomaly.rhr_cusum`) and `analytics.series.core` (`baseline.*`, `*.deviation`, `trend.*` for RHR, sleep TST, SpO2, respiratory, steps and vendor stress). Integration adapters map selected features to their inputs, resolve the profile v1 sleep target, map a series `band_mean` result to the typed `VitalsBand` monitoring input, and project results to the target writer (`integration.metric_results`). `analytics.sleep.stages` calculates the existing sleep duration/stage/efficiency metrics and `sleep.regularity`, separate from the locked Sleep Core V1 calculator. `baseline.foundations` only maps selected features to component inputs once per run and keeps the existing per-date persistence order; every calculation returns `MetricResult`, and the former private `MetricDraft` is gone. The calculations they do not open SQLite, format CLI output or read the wall clock. Result identity and fingerprints are written through the target schema-v3 repository. `basic.py` performs only selected-result presentation after the run; `day`/`history` open the analytics file read-only.

The local launcher places only `src/` on the import path. Target runtime has no Legacy import or subprocess invocation. Legacy is used by tests to create reference results and synthetic fixtures. Differential tests compare complete schema-v3 rows and active selections, excluding operational timestamps and run UUIDs. A copied-data rehearsal compared the existing stored corpus and a new run with Legacy. This is a **local target run switch**, not an installed ETL/LaunchAgent or production scheduling switch.

### Current ownership

| Boundary | Implemented owner | Current limits |
|---|---|---|
| Ingestion | Installed Legacy ETL | Incremental source overlap; reconciliation candidate not installed. |
| Source and profile | `baseline.source`, `baseline.profile` | Read-only health adapter and profile JSON v1, copied behavior. |
| Canonical inputs | `baseline.models`, `baseline.normalization`, Sleep domain contracts | Existing source-signal and feature identity; Sleep has narrow typed input. |
| Features | `baseline.features`, `baseline.feature_store` | Nightly/daily features and active selection in unchanged schema v3. |
| Analytics | `analytics.sleep.{core,stages}`, `analytics.recovery_vitals.{core,monitoring}`, `analytics.series.core` | Existing formulas only; `baseline.foundations` is assembly/order only. |
| Result storage | `storage.sqlite`, `storage.fingerprint`, Sleep result projection | Target-owned fingerprints, revisions, active selections and caller-owned session. |
| Orchestration | `baseline.runner`, `orchestration.sleep` | One local full run and one Sleep-date coordinator. |
| Presentation | `basic.py`, `__main__.py`, repository launcher | JSON date/history response; stored freshness, no new headline policy. |

`health.sqlite` is ETL-owned source history and must remain read-only to analytics. `analytics.sqlite` is derived history with schema v3: `analytics_runs`, `analytics_state`, profile/source revisions, `features`, `active_features`, `derived_metric_results` and `active_metric_selection`. Source exports, populated profiles and personal databases remain outside Git. Profile v1, schema v3, metric identities, status/metadata and active-selection semantics are compatibility contracts.

## B. Dependency direction and remaining boundaries

The working local path is intentionally narrow. Pure calculations consume dated values and return result drafts or canonical Sleep results. The runner may depend on source, profile, feature storage, analytics and result storage. Presentation reads selected rows and does not decide formulas. SQLite access belongs to the read-only source adapter, feature/result storage, and the runner's current lifecycle and change-discovery code; it does not belong to pure analytics. Storage owns feature and metric result rows and their active-selection semantics. The runner still issues schema-v3 SQL for checkpoints, run records, date discovery and generic obsolete-result cleanup; moving that existing SQL is not part of the local target-run switch. New active-selection rules should be implemented in storage, not independently in a calculation. Sleep Core and the Recovery/vitals core have no CLI, SQLite, clock, profile-parsing, `baseline` or Legacy dependency. Independent analytics share canonical inputs and `domain.metrics` types rather than another feature's private draft type; monitoring receives typed bands, so the former monitoring/foundation-draft coupling is removed.

The coarse long-term boundaries remain ingestion, canonical domain, storage, analytics/sleep, analytics/recovery-vitals, analytics/activity, orchestration, presentation and platform/config. They are ownership guidance, not a mandate to add one module per metric or rewrite the installed ETL. The local target runner currently preserves Legacy's source-change policy, POSIX lock, run-record lifecycle and stored-freshness rule. Improving old-correction detection, query-time freshness, installed scheduling or UI/API requires separate evidence and scope. No HRV is inferred from heart-rate samples, and source distance is withheld until its units are verified.

## Architectural guards

- Do not import or execute Legacy from target runtime; Legacy remains the differential test oracle.
- Do not make pure calculations read SQLite, wall-clock time or CLI state.
- Do not change schema v3, profile v1, metric identity/fingerprint rules or active selection without a separate compatibility decision.
- Keep the full runner transaction/lock outside per-metric calculation and storage projection. A nested Sleep-date commit would break rollback.
- Keep ETL and source history separate from analytics. Adapters and feature builders prepare inputs; calculations must not import SQLite, CLI or wall-clock services. Metrics must not depend on another metric's private implementation type.
- Keep source health data and personal derived history outside Git.
