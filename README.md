# Mi Fitness Whooping: existing-data baseline

This repository has a local daily path owned by `mi_fitness_whooping`. It reads the existing Mi Fitness `health.sqlite`, calculates the already supported indicators, writes a **separate** schema-v3 analytics SQLite file, and returns selected results for a date. The calculation behavior was carried over from Legacy and checked against it; Sleep Score, Need and Debt use the target Sleep Core and active-night reader. The installed ETL and LaunchAgent are unchanged.

## What is available

| Area | Calculated or selected today | Source only / unavailable |
|---|---|---|
| Sleep | Stage minutes and shares, TST, efficiency, regularity, `sleep.score`, fixed-target `sleep.need_min`, 14-night `sleep.debt_min`. | Xiaomi's own sleep score is source data, separate from this project's score. |
| Recovery | `recovery.score`; Xiaomi can reach `REDUCED` mode with enough complete sleep and vendor RHR history. | Confirmed RR/IBI/HRV is absent from the current adapter; no HRV is inferred from heart-rate samples. |
| Heart and breathing | Nocturnal RHR, vendor daily RHR, qualified nightly SpO₂ distribution and vendor respiratory mean; existing baselines, trends and monitoring. | Individual HR and SpO₂ samples are in `health.sqlite`. SpO₂ is optical oxygen saturation, not a blood test. |
| Stress | Vendor stress summary in the selected daily feature and existing trend. | No independent diagnostic stress metric. |
| Activity | Selected daily steps, energy, active minutes and standing count; existing steps trend. | Source distance has unverified units and is withheld as `distance_m=null`. Workouts are stored but not used by the current analytics run. |

The exact availability on a date depends on source coverage and existing quality/calibration gates. A metric can be selected with a `null` value and an explanatory status.

## Commands

From the repository root, use the included local launcher. It puts `src/` on the
import path itself, so no installation or manual `PYTHONPATH` is needed. Python
3.11 or newer must be available as `python3`.

In the baseline, analytics is run manually with this command; no schedule is
installed for it. `--source` and `--db` are required. `--profile` is optional;
without it, profile v1 uses its built-in defaults. The target command can continue an analytics database written by the Legacy analytics CLI,
and Legacy can continue one written by target; both take the same `<db>.lock`.

Run the existing calculations and show a date:

```sh
./mi-fitness-whooping run \
  --source /path/to/health.sqlite --db /path/to/analytics.sqlite \
  --day 2026-09-25
```

Omit `--day` to show the latest selected night, or the latest selected date if there is no night. The target runner writes only to the separate analytics destination. It does not change `health.sqlite`.
It rejects the same file as `--source` and `--db`. The target runner owns one
analytics lock and transaction for features, metrics, selections and state.

Rebuild canonical source history from a Mi Fitness export into a separate directory (never the installed ETL output). The CN/RU selection policy defaults to the accepted `unresolved_exclude`; the equivalence rule must always be given (`strict-v2` for new histories; `candidate-v1`/`strict-v1` reproduce earlier checks):

```sh
./mi-fitness-whooping reconcile --source /path/to/export --output /path/to/rebuild \
  --equivalence strict-v2 --rebuild-from-source
```

Every result reports `conflict_policy_version`. If a source database recorded in the published history is missing from the export, the command prints `SOURCE_INCOMPLETE` with the missing database, exits with code 3 and leaves the published history unchanged; a source that changes while being copied is `SKIPPED`/`SOURCE_BUSY` (exit 0, retry later). The result `health-rebuild.sqlite` can be used as `run --source`; its change log lets incremental analytics follow corrections, deletions and tombstones.

Read a date or inclusive history without running calculations:

```sh
./mi-fitness-whooping day --db /path/to/analytics.sqlite --day 2026-09-25
./mi-fitness-whooping history --db /path/to/analytics.sqlite --from 2026-09-21 --to 2026-09-25
```

These commands require an existing analytics schema v3 and open it read only. They return JSON with `sleep`, `recovery`, `vitals`, `other_metrics`, and selected daily-feature `activity`/`stress`. Calculation `status` and `stored_freshness` are separate; freshness is the stored label from the calculation run, not a new query-time assessment. Missing calendar dates appear as `MISSING` in history. All paths must point outside Git when they contain personal data.

The launcher uses only the target package at runtime. Legacy is retained as a
test reference; it is not imported or launched by `run`. This local command is
not a change to the installed ETL or LaunchAgent.

Example selected fields from a **synthetic** run (the command also returns provenance and metadata):

```json
{
  "date": "2026-09-25",
  "sleep.score": {"value": 97.0, "status": "VALID"},
  "sleep.need_min": {"value": 480.0, "status": "REDUCED"},
  "sleep.debt_min": {"value": null, "status": "CALIBRATING"},
  "recovery.score": {"value": 70.0, "status": "REDUCED", "active_components": ["rhr", "sleep"]},
  "spo2.nightly_mean": {"value": 97.0, "status": "VALID"},
  "respiratory.nightly_mean": {"value": 16.0, "status": "REDUCED"},
  "steps": 0,
  "distance_m": null
}
```

This excerpt is flattened for readability; the command's JSON groups metrics and carries their names, quality, provenance and metadata. Further optional work is tracked in `BACKLOG.md`.
