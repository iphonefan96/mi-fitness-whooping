# Backlog

Optional work and known risks outside the current usable-baseline task. A checked inventory item is not a promise to implement a new metric. Promote an item only when it blocks correctness or the user explicitly selects it.

## Data correctness and production integration

- [ ] Determine the minimum safe transaction/lock integration for target analytics before production activation. Current `TargetSleepStore` owns a one-date commit and cannot join the Legacy runner's outer transaction.
- [ ] Reconcile old source corrections beyond the installed ETL's 48-hour overlap, `cn`/`ru` identity collisions and source deletions/tombstones. The separate `mi_fitness_reconcile.py` is a candidate, not the installed production ETL.
- [ ] Validate full import/rebuild and replay on disposable copies before any production promotion; compare counts, conflicts and active results. Do not run a production backfill as incidental cleanup.
- [ ] Decide how to replace remaining Legacy profile v1 loading, feature building/writing, runner/checkpoints and CLI when a target production switch actually requires them. Preserve full-document profile revision and effective-dated sleep targets.
- [ ] Check stored-versus-query-time freshness behavior before changing it; `FRESH` stored rows can have a `STALE` headline at query time.

## Verification gaps

- [ ] Add a synthetic full path for reselecting an old *feature* revision through reader → Sleep → stored result when the changed integration path warrants it. Reader-only reselection, corrected-night full path and writer reselection are already tested; the audit at `2999c21` called this gap non-blocking.
- [ ] Characterize installed wrapper/LaunchAgent and full CLI JSON/status compatibility before a production switch.
- [ ] Assess dependency-graph over-invalidation and stored revision growth against actual benefit. Do not optimize it as part of the baseline unless it blocks use.

## Later product work

- [ ] Additional Sleep features or formula changes after the existing baseline is usable; specify and validate them separately.
- [ ] New wearable source adapters, including a real WHOOP device if desired. The current goal is WHOOP-like analytics on Mi Fitness data, not WHOOP ingestion.
- [ ] UI/API, dashboards and additional presentation once the date/history result is stable.
- [ ] HRV-based analytics only if a future source actually provides validated RR/IBI/HRV data. Do not derive HRV from ordinary heart-rate samples.
- [ ] Verify distance units before exposing the currently withheld distance field as analytics.

## Rule

Keep this list short and evidence-based. Do not implement an item just because it appears here. Reassess it when the current baseline reveals an actual need.
