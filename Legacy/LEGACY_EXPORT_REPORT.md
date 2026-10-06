# LEGACY EXPORT REPORT

Collection-only snapshot of the Mi Fitness ETL and wearable analytics code. The copied files are byte-for-byte copies, not a refactoring or a runnable copy of personal data. Inspection and copying took place on 2026-10-06. The installed production ETL and the reconciliation candidate are both represented, but the candidate is not an installed replacement.

## SOURCE LOCATIONS

- `/Users/rus/Documents/Codex/mi_fitness_etl/`: authoritative project source, tests, scripts and documentation; this is the source of all copied files.
- `/Users/rus/Library/Application Support/MiFitnessETL/app/` and `/Users/rus/Library/LaunchAgents/com.rus.mifitness.etl.plist`: installed ETL/scripts and LaunchAgent. The three installed scripts and installed plist match the corresponding project files byte-for-byte; duplicate installed copies were not added.
- `/Users/rus/Library/Application Support/MiFitnessETL/data/`, `/Users/rus/Documents/temp/mi_fitness_analytics/`, `/Users/rus/Documents/temp/mi_fitness_final_review/`, `/Users/rus/Documents/temp/mi_fitness_reconciliation/`, `/Users/rus/Documents/temp/mi_fitness_etl_test_*/`, `/Users/rus/Documents/temp/mi_fitness_analysis/`: production and generated analysis/test data, inspected by filename/size only for this export.
- `/Volumes/home/miFitness/` and `/Users/rus/Documents/Codex/Documents/`: current NAS source and older local Xiaomi export. They are input data, not code, and were not copied.
- `/Users/rus/Documents/temp/wearable_research/`: downloaded third-party research repositories referenced by the public-research document. They are not imported or called by the runtime and were not copied.
- A filename search under `/Users/rus/Documents/Codex/` found no additional Mi Fitness project Python package outside the main project; the other Xiaomi-named tree there is the raw export above.

## COPIED

41 original files, preserving their relative positions:

- Root Python: `mi_fitness_etl.py` (ETL and base health schema), `mi_fitness_reconcile.py` (separate reconciliation candidate and its extra schema), `reconciliation_digest.py` (read-only comparison helper), `test_incremental.py`, `test_reconciliation.py`.
- Complete `analytics/` Python package, including `__init__.py`, CLI, models, adapters, normalization, feature construction, algorithms, profile handling, runner, storage schema/migrations and all five test modules. Synthetic fixtures are defined inside those tests; there is no separate fixture data file.
- `research/*.py`: three project-owned read-only profiling/capability utilities. Their generated inputs and outputs are excluded.
- `run_mi_fitness_etl.sh`, `run_production_macos.sh`, `com.rus.mifitness.etl.plist`: unchanged run/lock/mount/scheduling definitions.
- `profile.template.json`: empty, non-personal profile template (`values: []`).
- `README.md`: operational documentation and base health schema/table map.
- `WEARABLE_ANALYTICS_RESEARCH.md`: public upstream research and provenance; no personal health export is embedded.

SQLite schema SQL and migrations are inline in `mi_fitness_etl.py`, `mi_fitness_reconcile.py` and `analytics/storage/db.py`. No standalone `.sql`, requirements file, `pyproject.toml` or package installer exists in the project root.

## EXCLUDED

- All `__pycache__/` and `*.pyc`: regenerable bytecode.
- `.git`, environments, caches, downloaded packages, logs, staging directories and lock files: not source. No such project-root environment, standalone SQL or requirements file was found.
- `final_reconciliation_review.json` and `rebuild_diff.json`: generated comparison reports derived from personal source/analytics data.
- The following existing Markdown files were **not copied** because they contain actual personal health aggregates, comparisons, date coverage or source-specific measurements, or could not confidently be classified as free of them. They remain untouched in the original directory: `ANALYTICS_ALGORITHM_DECISIONS.md`, `ANALYTICS_ARCHITECTURE.md`, `ANALYTICS_IMPLEMENTATION_STEP5.md`, `ANALYTICS_IMPLEMENTATION_STEP6.md`, `ANALYTICS_IMPLEMENTATION_STEP7.md`, `ANALYTICS_IMPLEMENTATION_STEP8.md`, `ANALYTICS_IMPLEMENTATION_STEP9.md`, `ANALYTICS_REBUILD_DIFF.md`, `CONFLICT_POLICY.md`, `DB_SIZE_ANALYSIS.md`, `ETL_RECONCILIATION_DESIGN.md`, `ETL_RECONCILIATION_IMPLEMENTATION.md`, `FINAL_RECONCILIATION_REVIEW.md`, `FULL_PROJECT_AUDIT.md`, `HEALTH_REBUILD_DIFF.md`, `IMPLEMENTATION_REPORT.md`, `NAS_ANALYTICS_REBUILD_DIFF.md`, `NAS_HEALTH_REBUILD_DIFF.md`, `XIAOMI_DATA_CAPABILITY_MAP.md`.
- Actual local/NAS Xiaomi exports, all production and review SQLite files, state/logs and generated research JSON: personal or potentially personal data. See below.

The omission of empirical documents is intentional: copying or editing/redacting them would conflict with the instruction to exclude uncertain personal data and preserve the old files exactly. Consequently the snapshot contains all identified project **code**, but not every historical project document.

## DATA FILES

None of the following was copied. Sizes are approximate file sizes at inspection, not a stable source manifest; NAS synchronization can change them. `R`/`W` describe application access, not filesystem permissions.

| Original path / files | Approximate size | Purpose and application access | Personal? / runtime role / synthetic replacement |
|---|---:|---|---|
| `/Volumes/home/miFitness/DataBase/1630397613/cn/1630397613.db` plus `-wal`/`-shm` | DB 29 MiB; WAL 4 MiB | Current Xiaomi source; main ETL and candidate read by staging copy, never intentionally write source. | Yes, raw health; required input for actual user history. Synthetic source DB is built by `test_incremental.py`/`test_reconciliation.py`. |
| `/Volumes/home/miFitness/DataBase/1630397613/ru/1630397613.db` plus sidecars | DB 71 MiB; WAL 4 MiB | Same source path, RU region. | Yes; actual-history input, synthetic tests available. |
| `/Volumes/home/miFitness/DataBase/1630397613/ru/*.conflict-*.db` plus sidecars | About 69–71 MiB per DB; six conflict-named DBs observed | Synology conflict copies. Main ETL's discovery may read them; reconciliation candidate intentionally excludes them. | Yes; not needed in Legacy. Synthetic conflict cases exist in reconciliation tests. |
| `/Volumes/home/miFitness/DataBase/notlogin/**/*.db` and sidecars | 4 KiB and 492 KiB DBs plus small sidecars | Additional Xiaomi export DBs scanned/identified by ETL/candidate; not the health record source. | Potentially personal metadata; input only. Synthetic tests use smaller source trees. |
| `/Users/rus/Documents/Codex/Documents/` including `DataBase/**/*.db`, `manifest.sqlite*`, other app files | Older export tree; primary CN/RU DBs about 29/69 MiB | Historical local Mi Fitness export and non-health manifests; past analysis input, not imported by a hard-coded current runtime path. | Yes or uncertain; not runtime-required when NAS source exists. Synthetic tests available for ETL behavior. |
| `/Users/rus/Library/Application Support/MiFitnessETL/data/health.sqlite` | 340 MiB | Installed normalized source; main ETL W; `XiaomiAdapter`/analytics CLI R. Schema owned by `mi_fitness_etl.py`. | Yes; required for analytics against real history, not needed for synthetic tests. |
| `/Users/rus/Library/Application Support/MiFitnessETL/data/state.json` | 4 KiB | ETL watermark/fingerprints; main ETL R/W. | Source metadata; required for existing incremental continuity, not for a fresh synthetic run. |
| `/Users/rus/Documents/temp/mi_fitness_analytics/analytics.sqlite` and historical `analytics-precompact-20260925.sqlite` | 143 and 179 MiB | Derived-feature/result storage; runner W, CLI status R/W through storage connection. | Yes, derived personal health; existing runtime output, not required for a fresh synthetic run. |
| `/Users/rus/Documents/temp/mi_fitness_final_review/run_*/` health/analytics SQLite; remaining `run_d/health-reconcile-nas.sqlite` | Remaining health candidate about 1.40 GiB; replay DBs about 41 MiB each | Disposable candidate/replay outputs; candidate W, analytics runner W, digest helper R. | Yes; review output, not runtime-required. Synthetic reconciliation tests available. |
| `/Users/rus/Documents/temp/mi_fitness_reconciliation/{health-rebuild,analytics-rebuild}.sqlite` | About 1.49 GiB / 41 MiB | Older disposable reconciliation/replay outputs. | Yes; review output, not runtime-required. |
| `/Users/rus/Documents/temp/mi_fitness_etl_test_*/health.sqlite` and `state.json`; `/Users/rus/Documents/temp/mi_fitness_analysis/**/*.db` | DBs range from small cache files to about 772 MiB | Earlier real-data ETL tests, snapshots and analysis copies; no hard-coded runtime dependency. | Yes/uncertain; exclude. Current tests generate synthetic temporary replacements. |
| `/Users/rus/Documents/temp/xiaomi_data_profile.json`, `xiaomi_db_inventory.json`, `xiaomi_coverage_requirements.json` | About 542 KiB, 488 KiB, 13 KiB | Generated research outputs read by historical documentation/workflows, not runtime analytics. | Derived personal-data risk; exclude. Research scripts accept explicit input/output paths. |

Source-folder manifests, WAL/SHM, generated logs, populated profile files and other app-cache data are likewise excluded. The only JSON copied is the empty `profile.template.json`.

## EXTERNAL DEPENDENCIES

- Python standard library: `sqlite3`, `argparse`, `json`, `datetime`, `zoneinfo`, `fcntl`, etc. No third-party Python runtime import was found in the collected code. `StrEnum` and other annotations mean the combined analytics package needs a modern Python (at least 3.11), even though the ETL README says 3.9+ for the ETL alone.
- SQLite with WAL support; the CLI's status query uses SQLite JSON functions (`json_extract`).
- macOS/POSIX runtime assumptions: `launchd`, `/bin/sh`, `flock` via Python `fcntl`, `smbfs` mount output, shell tools and an executable Python at the configured absolute location.
- Installed ETL copies in `/Users/rus/Library/Application Support/MiFitnessETL/app/` and the installed LaunchAgent are deployment duplicates, not different imported code. They are not brought into Legacy again.
- The NAS share and user-owned health/analytics SQLite databases are deliberately external runtime data. No external local Python module is imported by any collected source file.
- The upstream repositories named in `WEARABLE_ANALYTICS_RESEARCH.md` are references, not vendored code or runtime dependencies. Research clones under `/Users/rus/Documents/temp/wearable_research/` are not required to run this project.
- `research/build_capability_summary.py` expects inventory, coverage and a report as explicit CLI input files. Those generated, possibly personal files are not bundled.

## HARD-CODED PATHS

No path was changed. `Copied?` concerns the **referenced resource**, not whether its containing source file is copied.

| File and line/context | Referenced path/resource | Copied? | Future external configuration? |
|---|---|---|---|
| `run_production_macos.sh:6–8` | `/Volumes/home/miFitness`, mount `/Volumes/home`, exact SMB share `//RR@JDS._smb._tcp.local/home`; NAS raw source. | No | Yes, for another machine/share; retain exact-mount safety. |
| `run_production_macos.sh:9–11` | `/Users/rus/Library/Application Support/MiFitnessETL/{app,data,logs}` via `RUNTIME_ROOT`; deployed code, health DB, state, logs. | No deployed data; equivalent source scripts copied | Yes. |
| `run_production_macos.sh:12` | `/opt/homebrew/bin/python3` executable. | No | Yes, or verify same interpreter on destination. |
| `run_production_macos.sh:17–25` | `/bin/mkdir`, `/usr/bin/find`, `/bin/date`, `/usr/bin/printf`, `/usr/bin/tee`, `/sbin/mount`, `/usr/bin/awk`; OS utilities. | No | Platform assumption; configure only if porting. |
| `run_mi_fitness_etl.sh:64` | `/bin/ps`; OS utility for stale-lock check. | No | Platform assumption. |
| `com.rus.mifitness.etl.plist:9` | `/Users/rus/Library/Application Support/MiFitnessETL/app/run_production_macos.sh`; installed run script. | Installed target no; project equivalent yes | Yes, if installing elsewhere. |
| `analytics/__main__.py:14–15` | Default production `health.sqlite` and `/Users/rus/Documents/temp/mi_fitness_analytics/analytics.sqlite`. | No databases | Yes; CLI `--source`/`--db` already override defaults. |
| `mi_fitness_reconcile.py:433` | `/Users/rus/Library/Application Support/MiFitnessETL`; safety guard forbidding candidate output under installed production root. | No target | Yes, for another user's production root; do not silently remove the guard. |
| `test_reconciliation.py:414` | `/Users/rus/Library/Application Support/MiFitnessETL/data`; synthetic test of the above guard, not a data read. | No target | Yes if the guard changes. |
| `README.md:20–21,99–105` | Example NAS path, production data path, exact share, `$HOME/Library/.../app` script. | No data/deployment | Documentation must be reviewed after relocation. |
| `WEARABLE_ANALYTICS_RESEARCH.md:20` | `/Users/rus/Documents/temp/wearable_research/`; downloaded research checkouts. | No | Not required at runtime; review citation context only. |
| `mi_fitness_etl.py:1198–1199,1249` | `health.sqlite`, `state.json`, `.mi-fitness-stage-*` relative to CLI `--output`. | No output files | Base directory already configurable; filenames are existing contracts. |
| `mi_fitness_reconcile.py:36,489` | `health-rebuild.sqlite` default target and `.mi-fitness-stage-*` under CLI `--output`. | No output files | Output directory/target name already configurable; default remains a contract. |
| `run_mi_fitness_etl.sh:55,89–95` | `.mi_fitness_etl.lock`, `logs/mi_fitness_etl-*.log` under `--output` or `MI_FITNESS_LOG_DIR`. | No runtime files | Base path configurable; names/rotation are existing behavior. |
| `analytics/runners/runner.py:110` | `<analytics.sqlite>.lock`. | No | Follows configurable analytics DB path. |
| `analytics/tests/*`, `test_incremental.py` | `health.sqlite`, `analytics.sqlite`, `state.json` under `tempfile` directories. | No generated files | No; synthetic test-local paths. |

The `#!/usr/bin/env python3` and `#!/bin/sh` shebangs depend on interpreter/shell availability, not a bundled executable. Documentation excluded above contains further historical absolute paths; it is not part of the runnable Legacy tree and was not altered.

## TEST STATUS

Run **from the original project directory**, with `/opt/homebrew/bin/python3 -B` to avoid bytecode writes:

- `test_incremental.py`: A–E, **5/5 PASS**. It creates a synthetic source, WAL and target in `tempfile.TemporaryDirectory()`.
- `python3 -m unittest test_reconciliation analytics.tests.test_foundations analytics.tests.test_step6_metrics analytics.tests.test_step7_sleep analytics.tests.test_step8_recovery analytics.tests.test_step9_monitoring`: **62/62 PASS**, 1.929 s. Reconciliation and analytics integration tests use synthetic temporary SQLite databases; they do not open production/NAS paths. The hard-coded production path in one test is passed to a rejection guard, not opened.

No test was run against personal health data for this export. Tests were not run from `Legacy/`, to honor the request to test from the original project location.

## MISSING OR UNCERTAIN

- Historical implementation/design/audit reports listed under EXCLUDED may be useful to understand decisions, but they contain or may contain derived personal health data. Review manually before moving any of them.
- No separate dependency manifest or LICENSE/NOTICE bundle exists in this project tree. The research document cites upstream source and licenses; their repositories are not copied. Redistribution/licensing should be checked independently if the snapshot leaves private use.
- The snapshot has no actual profile, source data or databases. It can execute synthetic tests and create a fresh ETL/analytics target only when explicitly supplied a suitable source.
- The reconciliation candidate is copied as code but has not been promoted to the installed scheduler. The installed ETL and candidate differ in source-discovery/conflict behavior; the snapshot does not resolve that difference.

## LEGACY TREE

```text
Legacy/
├── LEGACY_EXPORT_REPORT.md
├── README.md
├── WEARABLE_ANALYTICS_RESEARCH.md
├── mi_fitness_etl.py
├── mi_fitness_reconcile.py
├── reconciliation_digest.py
├── test_incremental.py
├── test_reconciliation.py
├── run_mi_fitness_etl.sh
├── run_production_macos.sh
├── com.rus.mifitness.etl.plist
├── profile.template.json
├── analytics/
│   ├── __init__.py, __main__.py, models.py
│   ├── adapters/{__init__.py,base.py,xiaomi.py}
│   ├── algorithms/{__init__.py,foundations.py,monitoring.py,recovery.py,sleep.py}
│   ├── features/{__init__.py,foundations.py}
│   ├── normalization/{__init__.py,core.py}
│   ├── profile/{__init__.py,config.py}
│   ├── runners/{__init__.py,runner.py}
│   ├── storage/{__init__.py,db.py}
│   └── tests/{__init__.py,test_foundations.py,test_step6_metrics.py,
│              test_step7_sleep.py,test_step8_recovery.py,test_step9_monitoring.py}
└── research/{build_capability_summary.py,coverage_requirements.py,profile_health_db.py}
```

## REPRODUCTION RISKS

- Direct production launch from an unmodified copied wrapper/plist still points at the old user's NAS, home directory, installed app path and Homebrew Python. Do not register the plist or run the production wrapper on a new machine without reviewing those references.
- No real data is bundled by design. The ETL requires a compatible Xiaomi export; analytics requires a compatible `health.sqlite`, which the included ETL can generate from suitable input.
- External personal research outputs and empirical reports were intentionally omitted, so historical numerical comparisons cannot be reproduced from Legacy alone. Synthetic tests remain self-contained.
- The source tree contains no packaging/dependency manifest. Python version, SQLite functions and macOS tools must be verified in the destination.
- Code is frozen as found, including known differences between production ETL and reconciliation candidate; this export does not repair or validate production promotion.

## RECOMMENDED NEXT ACTION

After manually copying `Legacy/` into the new repository, inspect the absolute paths, interpreter/platform assumptions and omitted-document list against that repository's intended environment before running the production wrapper. Keep personal databases and raw exports outside the repository.

## FINAL VERIFICATION

- Original project files were **not modified** and **not deleted**; copied source files were checked byte-for-byte against their originals.
- **No personal database or raw export was copied** into `Legacy/`.
- No credential, token, secret or populated personal profile was copied; the included code/template were inspected for credential assignments/private-key markers. Absolute local account/share names in unchanged scripts are paths, not authentication secrets.
- **No refactoring, schema change, algorithm change, renaming or behavior change** was performed.
- `Legacy/` is a faithful code snapshot of the identified old implementation, with privacy-driven exclusions explicitly recorded above.
