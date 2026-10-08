# Backlog

Optional work and known risks outside the current usable-baseline task. A checked inventory item is not a promise to implement a new metric. Promote an item only when it blocks correctness or the user explicitly selects it.

## Data correctness and production integration

- [ ] Scheduled analytics (deferred; the baseline is run manually). No analytics job is installed; the LaunchAgent runs ETL only. A schedule needs a reviewed decision on: trigger (after ETL in the same wrapper, or a separate LaunchAgent); explicit `--source`/`--db`/`--profile`; a pinned Python ≥ 3.11 (launchd's `/usr/bin/python3` is 3.9 and fails); log destination; whether Legacy `status`/`validate` stay the status surface or target needs an equivalent; rollback. Re-inspect the host for other schedulers before activation.
- [ ] Accept target-owned reconciliation (`mi-fitness-whooping reconcile`) as the canonical source history after independent review. Settled 2026-10-09: policy `unresolved_exclude`; equivalence `strict-v2` (proven upload flag `isUploaded` ignored; an absent column equals only its declared default); missing expected database → `SOURCE_INCOMPLETE`, exit 3, nothing published. Verified on a fresh NAS snapshot. Remaining: confirm the phone→NAS sync was complete for that snapshot; decide whether other service flags (e.g. `binaryIsUpload`) are provably ignorable; an explicit, reviewed way to retire a source database deliberately (today only a new output directory); peak disk (~1.5 GB per target) and runtime (~4–10 min); scheduling stays deferred.
- [ ] Validate full import/rebuild and replay on disposable copies before any production promotion; compare counts, conflicts and active results. The baseline `run`/rerun/day/history copy rehearsal is complete, but it is not a full rebuild or replay audit. Do not run a production backfill as incidental cleanup.
- [ ] Check stored-versus-query-time freshness behavior before changing it; `FRESH` stored rows can have a `STALE` headline at query time.

## Verification gaps

- [ ] Add a synthetic full path for reselecting an old *feature* revision through reader → Sleep → stored result when the changed integration path warrants it. Reader-only reselection, corrected-night full path and writer reselection are already tested; the audit at `2999c21` called this gap non-blocking.
- [ ] Assess dependency-graph over-invalidation and stored revision growth against actual benefit. Do not optimize it as part of the baseline unless it blocks use.

## Later product work

- [ ] Additional Sleep features or formula changes after the existing baseline is usable; specify and validate them separately.
- [ ] New wearable source adapters, including a real WHOOP device if desired. The current goal is WHOOP-like analytics on Mi Fitness data, not WHOOP ingestion.
- [ ] UI/API, dashboards and additional presentation once the date/history result is stable.
- [ ] HRV-based analytics only if a future source actually provides validated RR/IBI/HRV data. Do not derive HRV from ordinary heart-rate samples.
- [ ] Verify distance units before exposing the currently withheld distance field as analytics.

## Rule

Keep this list short and evidence-based. Do not implement an item just because it appears here. Reassess it when the current baseline reveals an actual need.
