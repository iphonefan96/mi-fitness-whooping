# Mi Fitness incremental ETL

Локальный ETL без сетевых запросов:

```text
Mi Fitness source -> WAL-aware staging snapshot -> health.sqlite
```

## Требования

- Python 3.9+ со стандартным модулем `sqlite3`;
- никаких дополнительных Python-пакетов;
- source доступен только для чтения;
- достаточно свободного места для временной копии изменившейся health-базы.

## Запуск

```sh
./run_mi_fitness_etl.sh \
  --source "/Volumes/home/miFitness" \
  --output "/Users/rus/Library/Application Support/MiFitnessETL/data" \
  --overlap-hours 48
```

Результаты:

- `health.sqlite` — нормализованная база;
- `state.json` — watermark, fingerprints и счётчики последнего успешного запуска;
- `logs/mi_fitness_etl-*.log` — компактные журналы запусков.

## Структура `health.sqlite`

| Target table | Source |
|---|---|
| `heart_rate` | `heart_rate` keys `heart_rate`, `single_heart_rate` |
| `heart_rate_events`, `heart_rate_event_samples` | `low_heart_rate`, future high/abnormal HR events |
| `spo2` | `spo2` |
| `stress` | `stress` |
| `activity_samples` | `steps` |
| `calorie_samples` | `calories` |
| `intensity_samples` | `intensity` |
| `standing_intervals` | `valid_stand` |
| `sleep_sessions`, `sleep_stages` | `sleep` |
| `daily_summary` | all populated `*_day`, resting/min/max HR, `vitality` |
| `workouts` | `MIWDBSportTable` |
| `derived_metrics` | Xiaomi-derived scalar fields, including future matching metrics |
| `raw_records`, `raw_blobs` | lossless generic layer for every populated health-related source table |

`raw_records` позволяет автоматически сохранить будущие таблицы HRV/RR/IBI,
temperature, recovery/readiness и другие health-типы, если они появятся в Mi
Fitness. Обычный BPM не преобразуется в HRV.

Каждая таблица использует primary key/UPSERT. `raw_records.record_id`
детерминирован из source primary key и не включает путь `cn`/`ru`, поэтому
одна и та же логическая запись не дублируется между региональными базами.

Если metadata/content fingerprint исходных DB/WAL не изменился, extractor выводит
`NO NEW SOURCE DATA` и завершается без staging и без изменения target.

## Безопасность чтения

Extractor не открывает SQLite source для рабочих запросов. Сначала он:

1. вычисляет лёгкий fingerprint DB/WAL;
2. копирует DB, WAL и SHM во временный каталог внутри output;
3. повторно проверяет source fingerprint;
4. применяет WAL только к staging-копии через SQLite backup API;
5. удаляет staging после завершения.

Если source менялся во время копирования, операция повторяется. После четырёх
неудачных попыток запуск завершается как `SKIPPED`, не обновляя `state.json` и
не фиксируя частичный ETL transaction. Следующий запуск попробует source снова.

## Incremental behavior

Первый запуск импортирует полную историю. Затем для каждой изменившейся source
database используется собственный watermark и overlap-window. По умолчанию
перечитываются последние 48 часов, с округлением начала окна до начала UTC-дня,
чтобы не пропустить пересчитанный дневной summary.

Idempotency обеспечивают детерминированные record IDs, primary keys и UPSERT.
Повторное чтение того же окна не создаёт дубликаты.

## Автоматизация macOS

Synology используется только как read-only source. Рабочая копия ETL и
production-данные находятся локально на Mac:

```sh
~/Library/Application Support/MiFitnessETL/
├── app/
├── data/health.sqlite
├── data/state.json
└── logs/
```

LaunchAgent `com.rus.mifitness.etl` запускается при входе и каждые 21600 секунд
(6 часов). Он использует абсолютный Python `/opt/homebrew/bin/python3` и только
точный SMB mount `//RR@JDS._smb._tcp.local/home` в `/Volumes/home`; похожий
`/Volumes/home-1` намеренно не принимается.

Ручной ETL:

```sh
"$HOME/Library/Application Support/MiFitnessETL/app/run_production_macos.sh"
```

Ручной запуск и проверка LaunchAgent:

```sh
launchctl kickstart -k gui/$(id -u)/com.rus.mifitness.etl
launchctl print gui/$(id -u)/com.rus.mifitness.etl
```

Если NAS недоступен, запуск пишет `SKIPPED: Mi Fitness NAS source unavailable`,
завершается с кодом 0 и не меняет `health.sqlite` или `state.json`. Run-логи
старше 30 дней удаляются; health data не затрагиваются.
