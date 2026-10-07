# ADR-002: Target package identity and Sleep Core integration seam

Status: **Accepted for target design** (2026-10-06). At decision time this ADR changed no runtime imports, runner, database or CLI. Phase 4C implementation and production activation required separate verification.

Implementation note (2026-10-07): the package move and synthetic seam described below have been completed. Storage Phases A–C replaced the synthetic Legacy result bridge with target-owned result persistence. The context, proposed seam and component-disposition table below record the **decision-time baseline**, not current runtime dependencies. Selected-night/profile input and full-runner boundaries remain; production remains Legacy. See `ARCHITECTURE.md` and the active Sleep plan for current ownership.

## Context and evidence

`Legacy/analytics/__init__.py` and `src/analytics/__init__.py` make `analytics` two distinct regular packages. Python selects the first parent directory on `sys.path`; it does not combine their subpackages. A read-only import check with `PYTHONPATH=Legacy:src` loaded Legacy `analytics` and failed on `analytics.sleep`; reversing it loaded target `analytics` and failed on `analytics.algorithms`. The current differential tests avoid this by putting the repository root on `sys.path` and importing the target as `src.analytics.sleep.core`, while `analytics` resolves to Legacy. `src` has no `__init__.py`, no package/install manifest exists, and this test-only `src.analytics` route is not the intended durable product identity.

Legacy's `analytics.__main__` imports `analytics.runners.runner.run`; the runner imports `calculate_sleep_day` at module load. Its path is source adapter → nightly/daily feature building and active feature storage → `active_feature_records()` → profile and replay context → Legacy sleep, foundation, recovery and monitoring drafts → `put_result()` → active selection and obsolete-selection cleanup. It owns the lock, run record, source generation/checkpoints, transaction, stored freshness and status counts. It has no public sleep-calculator injection hook. The installed ETL wrapper is separate from this analytics CLI. The Legacy snapshot is immutable.

## Decision: package identity

Use **`mi_fitness_whooping`** as the one project-specific top-level package for future target domain, analytics, integration, orchestration and presentation code. In Phase 4C1, migrate the current `src/domain`, `src/analytics` and `src/integration` modules into this namespace and update their tests/imports together. Keep `Legacy/analytics` unchanged and import its compatibility APIs as `analytics.*` only at the outer integration/storage edge. A normal installed or configured source root must expose `mi_fitness_whooping` and `analytics` as distinct packages in the same process. Test both imports in a clean subprocess, without test-time `src.analytics` aliases, `sys.modules` surgery or runtime path mutation. The packaging/install mechanism can be chosen in 4C1; do not encode a fragile path order as the product contract.

This package name belongs to the entire future project, rather than to Sleep alone, and is distinct from the generic Legacy `analytics` and common third-party package names. It does not alter Legacy's public Python import path.

## Import strategies considered

| Strategy | Maintenance, safety and testability | Packaging, present churn and Legacy impact |
|---|---|---|
| **A. Project-specific target package — chosen** | Clear ownership and stable imports; low accidental Legacy selection; ordinary import and dependency tests. | Requires a bounded rename of current target modules/tests in 4C1 and explicit package configuration. Legacy remains immutable. |
| **B. Keep `src/analytics` with package-root/install ordering** | The two regular packages still collide. Installing or ordering roots merely chooses which `analytics` hides the other; combined imports fail. | Little immediate churn, but no viable same-process product packaging without extra aliasing or a namespace refactor. Legacy untouched, integration untestable through normal imports. |
| **C. Bootstrap entrypoint that edits `sys.path` or aliases modules** | Depends on startup order and `sys.modules` state; easy to load the wrong algorithm or split type identity. Hard to audit and test across CLI, jobs and direct imports. | Small immediate churn, high recurring operational risk; no Legacy edit, but a fragile production contract. Rejected. |
| **D. Separate subprocesses/services** | Avoids Python name collision, but requires a new serialization/provenance protocol and coordinating transaction, lock, errors and freshness across processes. | Larger immediate and long-term packaging/operation cost; preserves Legacy but unnecessary for one calculator. Rejected for V1. |

## Decision: external integration seam

The smallest direct seam is **after** existing `active_feature_records()` has selected and reconstructed the original nightly `FeatureRecord` map and **before** each sleep `MetricDraft` reaches existing `put_result()`. A target-owned caller outside `Legacy/` will eventually pass `(day, nights, loaded profile, profile revision)` to `adapt_sleep_input`, then `calculate_sleep_core`, then `adapt_sleep_result(result, same original nights)`. It passes the resulting drafts to unchanged `put_result()` with the runner-equivalent run ID, profile revision, source policy and calculation-date stored freshness. Storage continues to own fingerprinting, revisions and active selection. Neither adapter owns clock, SQL or presentation behavior.

The current Legacy runner cannot invoke this path through its existing `run()` API. Do not monkey-patch its imported function, overwrite `analytics` modules or run Legacy and then overwrite its sleep results in the production database. The external seam begins as a **synthetic integration path**, not a production switch. Production activation later requires a target-owned orchestration entrypoint that accounts for the whole runner lifecycle: lock, source read/generation, dirty dates and replay, feature writes, non-sleep calculations, transaction/run records, obsolete selections, checkpoints, error handling and unchanged CLI output. Reuse existing compatibility functions where safe; do not copy the whole runner blindly. Reconcile that larger scope before authorizing activation.

## Legacy component disposition for this migration

| Component | Disposition | Reason |
|---|---|---|
| `FeatureRecord`, `MetricDraft`, `active_feature_records()`, `put_result()` | **REUSE AS COMPATIBILITY DEPENDENCY** | Preserve original lineage, fingerprint and selection rules; keep imports at the outer boundary. |
| `connect()` / `migrate()` and profile `load_profile()` | **REUSE AS COMPATIBILITY DEPENDENCY** | Keep schema and profile v1 semantics. Use temporary DB/profile in proof; no schema migration change. |
| Source `XiaomiAdapter`, `build_nightly()` / `build_daily()`, `put_feature()` | **WRAP** if a later production orchestrator needs them | Reuse existing behavior through explicit calls; no ingestion migration in Sleep Core V1. Not required for 4C1's preseeded active-feature proof. |
| Dirty-date, checkpoint and source-generation logic; `exclusive_lock()`; private run records/transaction; obsolete selection cleanup | **REIMPLEMENT LATER** behind owned boundaries after characterization | These are tightly coupled runner responsibilities, many private to `runner.py`, not a callable sleep hook. Do not extract or duplicate them in 4C1; preserve their observable behavior at any later switch. |
| Foundation, Recovery and Monitoring calculations | **REUSE AS COMPATIBILITY DEPENDENCY** during a future full runner replacement | Preserve ordering and outputs until those features receive their own migration. Not invoked by the sleep-only 4C1 proof. |
| Legacy `run()` / `__main__.py` CLI helpers | **DO NOT COPY** | Keep the existing production CLI/runner untouched. A future target CLI needs a separate compatibility review before any switch. |

## Rolling Phase 4C boundary

1. **4C1 — package separation and seam proof.** Rename only current target modules/imports under `mi_fitness_whooping`; verify ordinary simultaneous Legacy/target imports. With a temporary synthetic analytics DB containing active nightly features and a synthetic profile, use existing `active_feature_records()`/`load_profile()` and the two adapters plus pure calculator to produce drafts, then call real `put_result()` with explicit fixed run/freshness context. Compare Legacy drafts and persisted identity, revision and active selection for initial, unchanged and corrected inputs. No production entrypoint or personal DB.
2. **4C2 — target orchestration wrapper on synthetic data.** Define a bounded external caller for the sleep path and its explicit context/transaction/cleanup ownership, using existing compatibility storage. Test no-night/obsolete selection, profile revision, fixed-time freshness and failure/rollback. Decide how it composes with other metrics and the existing lock before broadening. Do not claim runner or CLI parity from a sleep-only wrapper.
3. **4C3 — production switch, separately gated.** Only after reconciliation and regression of the complete runner lifecycle and CLI, choose an opt-in target entrypoint/rollback approach. Preserve installed ETL and current Legacy analytics until equivalence is demonstrated. This ADR does not approve activation or prescribe copying the runner.

4C1 can prove metric names, units, statuses, versions, metadata, ordered lineage, fingerprints, `put_result()` revisions and active selection for synthetic cases. It cannot prove source-generation/checkpoint behavior, whole-runner counters, obsolete cleanup across all metrics, installed CLI JSON, or wall-clock presentation behavior. The same named target package and outer orchestration seam can later host Recovery, Monitoring and Activity behind their own contracts without repeating the `analytics` collision.

## Consequences and review trigger

There is bounded import/test churn in 4C1. The output adapter will continue to depend on Legacy `MetricDraft` until storage migration is separately specified. A full production switch remains higher risk than a synthetic sleep proof because Legacy offers no calculator injection point. Revisit this ADR if the repo gains a supported runner injection API, a package installer changes the import model, or complete runner parity cannot be achieved without a locked-contract change. ADR-001 continues to govern freshness ownership.
