# Mi Fitness Whooping: existing-data baseline

This repository currently has a practical daily path for analytics already implemented in Legacy. It reads an existing Mi Fitness `health.sqlite` through the unchanged read-only Xiaomi adapter, runs the existing calculations into a **separate** schema-v3 analytics SQLite file, and returns selected results for a date. The target Sleep Core and selected-night reader remain a separately tested migration path; this command does not activate them in production.

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

Run the existing calculations and show a date:

```sh
PYTHONPATH=src:Legacy python3 -m mi_fitness_whooping run \
  --source /path/to/health.sqlite --db /path/to/analytics.sqlite \
  --day 2026-09-25
```

Omit `--day` to show the latest selected night, or the latest selected date if there is no night. The command writes only through Legacy's existing runner to the separate analytics destination. It does not change `health.sqlite`.
It rejects the same file as `--source` and `--db`.

Read a date or inclusive history without running calculations:

```sh
PYTHONPATH=src python3 -m mi_fitness_whooping day --db /path/to/analytics.sqlite --day 2026-09-25
PYTHONPATH=src python3 -m mi_fitness_whooping history --db /path/to/analytics.sqlite --from 2026-09-21 --to 2026-09-25
```

These commands require an existing analytics schema v3 and open it read only. They return JSON with `sleep`, `recovery`, `vitals`, `other_metrics`, and selected daily-feature `activity`/`stress`. Calculation `status` and `stored_freshness` are separate. Missing calendar dates appear as `MISSING` in history. All paths must point outside Git when they contain personal data.

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
