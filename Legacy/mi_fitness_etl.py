#!/usr/bin/env python3
"""Incremental, local-only ETL for Xiaomi Mi Fitness SQLite data.

The source directory is treated as read-only. Database files and their SQLite
sidecars are copied into a stable temporary staging directory before WAL-aware
snapshots are opened.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


EXTRACTOR_VERSION = "1.0.0"
SCHEMA_VERSION = 1
DEFAULT_OVERLAP_HOURS = 48.0
STAGING_RETRIES = 4

KNOWN_HEALTH_TABLES = {
    "MIWDBSportSummaryTable",
    "MIWDBSportTable",
    "blood_pressure",
    "blood_sugar",
    "body_momentum",
    "calories",
    "calories_day",
    "dietary_daily_consumption",
    "dietary_daily_diary",
    "dynamic",
    "ecg",
    "energy",
    "energy_day",
    "floors",
    "floors_day",
    "goal_day",
    "grade_prediction",
    "health",
    "heart_rate",
    "heart_rate_day",
    "intensity",
    "intensity_day",
    "lactate_threshold",
    "mc_blood_pressure",
    "mc_ecg",
    "menstrual_symptoms",
    "menstruation",
    "noise",
    "one_click_physical_examination",
    "pai",
    "performance_status",
    "physical_fitness_status",
    "red_dot_day",
    "running_ability_index",
    "sleep",
    "sleep_day",
    "sleep_diary",
    "sleep_hr_Spo2_binary",
    "sleep_incomplete",
    "sleep_original_data",
    "sleep_wake_circle",
    "snail_snore",
    "spo2",
    "spo2_day",
    "sport_justdance_song",
    "steps",
    "steps_day",
    "stress",
    "stress_day",
    "temperature",
    "temperature_characteristic",
    "temperature_local_day",
    "temperature_trend",
    "third_synapsor_blood_glucose",
    "training_load",
    "valid_stand",
    "valid_stand_day",
    "vitality",
    "vo2_max",
    "watch_daytime_sleep",
    "watch_night_sleep",
    "weight",
}

HEALTH_NAME_FRAGMENTS = (
    "heart", "hrv", "rmssd", "sdnn", "pnn", "rr_interval", "ibi",
    "pulse", "cardio", "sleep", "spo2", "oxygen", "stress", "breath",
    "respir", "recovery", "readiness", "energy", "fatigue", "vital",
    "pai", "temperature", "weight", "body", "blood", "glucose", "ecg",
    "step", "calorie", "distance", "activity", "intensity", "stand",
    "sedent", "floor", "elevation", "workout", "sport", "training",
    "vo2", "running", "walking", "pace", "speed", "cadence", "menstr",
    "fitness", "health", "dynamic", "momentum", "noise",
)

HIGH_VOLUME_SAMPLE_TABLES = {
    "heart_rate", "spo2", "stress", "steps", "calories", "intensity",
    "valid_stand", "sleep",
}

METRIC_GROUPS = {
    "heart_rate": "Heart rate",
    "heart_rate_day": "Heart rate",
    "spo2": "SpO2",
    "spo2_day": "SpO2",
    "stress": "Stress",
    "stress_day": "Stress",
    "sleep": "Sleep sessions",
    "sleep_day": "Sleep sessions",
    "steps": "Activity",
    "steps_day": "Activity",
    "calories": "Activity",
    "calories_day": "Activity",
    "intensity": "Activity",
    "intensity_day": "Activity",
    "valid_stand": "Activity",
    "valid_stand_day": "Activity",
    "MIWDBSportTable": "Workouts",
    "training_load": "Training load",
    "vitality": "Vitality",
}

SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS schema_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS etl_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    source_root TEXT NOT NULL,
    overlap_hours REAL NOT NULL,
    window_start_utc INTEGER,
    window_end_utc INTEGER,
    rows_new INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    warnings INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS source_databases (
    source_db_id INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    last_fingerprint TEXT NOT NULL,
    max_source_timestamp INTEGER,
    last_seen_at TEXT NOT NULL,
    is_health_database INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS source_table_catalog (
    source_db_id INTEGER NOT NULL REFERENCES source_databases(source_db_id),
    table_name TEXT NOT NULL,
    columns_json TEXT NOT NULL,
    primary_key_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (source_db_id, table_name)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS raw_records (
    record_id TEXT PRIMARY KEY,
    source_db_id INTEGER NOT NULL REFERENCES source_databases(source_db_id),
    source_table TEXT NOT NULL,
    source_pk_json TEXT NOT NULL,
    source_sid TEXT,
    source_key TEXT,
    source_timestamp INTEGER,
    source_local_timestamp INTEGER,
    utc_offset_seconds INTEGER,
    local_date TEXT,
    source_deleted INTEGER NOT NULL DEFAULT 0,
    value_json TEXT,
    record_json TEXT NOT NULL,
    content_hash BLOB NOT NULL,
    first_imported_at TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_records_time_idx
    ON raw_records(source_table, source_timestamp);

CREATE TABLE IF NOT EXISTS raw_blobs (
    record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    column_name TEXT NOT NULL,
    data BLOB NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (record_id, column_name)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS record_provenance (
    record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    source_db_id INTEGER NOT NULL REFERENCES source_databases(source_db_id),
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (record_id, source_db_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS heart_rate (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    bpm REAL NOT NULL,
    kind TEXT NOT NULL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS heart_rate_time_idx ON heart_rate(timestamp_utc);

CREATE TABLE IF NOT EXISTS heart_rate_events (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    start_timestamp_utc INTEGER,
    end_timestamp_utc INTEGER,
    local_date TEXT,
    sample_count INTEGER NOT NULL DEFAULT 0,
    min_bpm REAL,
    max_bpm REAL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS heart_rate_event_samples (
    source_record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    sample_index INTEGER NOT NULL,
    timestamp_utc INTEGER,
    bpm REAL,
    PRIMARY KEY (source_record_id, sample_index)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS hr_event_sample_time_idx
    ON heart_rate_event_samples(timestamp_utc);

CREATE TABLE IF NOT EXISTS spo2 (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    value REAL NOT NULL,
    kind TEXT NOT NULL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS spo2_time_idx ON spo2(timestamp_utc);

CREATE TABLE IF NOT EXISTS stress (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    value REAL NOT NULL,
    kind TEXT NOT NULL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS stress_time_idx ON stress(timestamp_utc);

CREATE TABLE IF NOT EXISTS activity_samples (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    steps INTEGER,
    distance REAL,
    calories REAL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS activity_samples_time_idx ON activity_samples(timestamp_utc);

CREATE TABLE IF NOT EXISTS calorie_samples (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    calories REAL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS intensity_samples (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    timestamp_utc INTEGER NOT NULL,
    local_timestamp INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS standing_intervals (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    start_timestamp_utc INTEGER,
    end_timestamp_utc INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sleep_sessions (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    sleep_start_utc INTEGER,
    sleep_end_utc INTEGER,
    local_date TEXT,
    utc_offset_seconds INTEGER,
    duration_minutes REAL,
    deep_minutes REAL,
    light_minutes REAL,
    rem_minutes REAL,
    awake_minutes REAL,
    sleep_score REAL,
    sleep_efficiency REAL,
    avg_hr REAL,
    min_hr REAL,
    max_hr REAL,
    avg_spo2 REAL,
    min_spo2 REAL,
    max_spo2 REAL,
    avg_respiratory_rate REAL,
    breathing_quality REAL,
    awake_count INTEGER,
    has_stages INTEGER,
    has_rem INTEGER,
    is_nap_inferred INTEGER NOT NULL DEFAULT 0,
    algorithm_version TEXT,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sleep_sessions_end_idx ON sleep_sessions(sleep_end_utc);

CREATE TABLE IF NOT EXISTS sleep_stages (
    source_record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    stage_index INTEGER NOT NULL,
    stage TEXT NOT NULL,
    raw_state INTEGER,
    start_timestamp_utc INTEGER NOT NULL,
    end_timestamp_utc INTEGER NOT NULL,
    duration_minutes REAL NOT NULL,
    PRIMARY KEY (source_record_id, stage_index)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS sleep_stages_time_idx ON sleep_stages(start_timestamp_utc);

CREATE TABLE IF NOT EXISTS daily_summary (
    local_date TEXT PRIMARY KEY,
    steps INTEGER,
    distance REAL,
    step_calories REAL,
    total_calories REAL,
    activity_duration_minutes REAL,
    standing_count INTEGER,
    resting_hr REAL,
    avg_hr REAL,
    min_hr REAL,
    max_hr REAL,
    abnormal_hr_count INTEGER,
    avg_spo2 REAL,
    min_spo2 REAL,
    max_spo2 REAL,
    low_spo2_count INTEGER,
    avg_stress REAL,
    min_stress REAL,
    max_stress REAL,
    sleep_total_minutes REAL,
    deep_sleep_minutes REAL,
    light_sleep_minutes REAL,
    rem_sleep_minutes REAL,
    awake_minutes REAL,
    nap_minutes REAL,
    sleep_score REAL,
    avg_respiratory_rate REAL,
    breathing_quality REAL,
    vitality REAL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS workouts (
    source_record_id TEXT PRIMARY KEY REFERENCES raw_records(record_id) ON DELETE CASCADE,
    start_timestamp_utc INTEGER,
    end_timestamp_utc INTEGER,
    local_date TEXT,
    workout_type TEXT,
    sport_type TEXT,
    duration_seconds REAL,
    calories REAL,
    avg_hr REAL,
    min_hr REAL,
    max_hr REAL,
    training_load REAL,
    recovery_time REAL,
    aerobic_effect REAL,
    anaerobic_effect REAL,
    vitality REAL,
    imported_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS derived_metrics (
    source_record_id TEXT NOT NULL REFERENCES raw_records(record_id) ON DELETE CASCADE,
    source_table TEXT NOT NULL,
    field_path TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    timestamp_utc INTEGER,
    local_date TEXT,
    numeric_value REAL,
    text_value TEXT,
    origin TEXT NOT NULL DEFAULT 'xiaomi_derived',
    imported_at TEXT NOT NULL,
    PRIMARY KEY (source_record_id, field_path)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS derived_metric_name_idx
    ON derived_metrics(metric_name, timestamp_utc);

CREATE TABLE IF NOT EXISTS quality_warnings (
    warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES etl_runs(run_id),
    source_record_id TEXT,
    warning_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_epoch(value: int | None) -> str:
    if value is None:
        return "FULL HISTORY"
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def local_date_from_epoch(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def quick_file_signature(path: Path) -> dict[str, Any]:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        digest.update(handle.read(65536))
        if stat.st_size > 65536:
            handle.seek(max(0, stat.st_size - 65536))
            digest.update(handle.read(65536))
    return {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "edge_sha256": digest.hexdigest(),
    }


def database_group_files(base: Path) -> list[Path]:
    candidates = [base, Path(str(base) + "-wal"), Path(str(base) + "-shm"), Path(str(base) + "-journal")]
    return [path for path in candidates if path.is_file()]


def database_fingerprint(base: Path) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {}
    for file_path in database_group_files(base):
        details[file_path.name] = quick_file_signature(file_path)
    encoded = json_dumps(details).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), details


def discover_candidate_databases(source_root: Path) -> list[Path]:
    database_root = source_root / "DataBase"
    if not database_root.is_dir():
        raise FileNotFoundError(f"Mi Fitness DataBase directory not found: {database_root}")
    candidates = sorted(path for path in database_root.rglob("*") if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"})
    if not candidates:
        raise FileNotFoundError(f"No candidate databases found under: {database_root}")
    return candidates


class SourceSnapshotBusyError(RuntimeError):
    """The read-only source could not be snapshotted consistently yet."""


def stable_stage_database(source_db: Path, staging_root: Path) -> Path:
    """Copy a SQLite database group without touching source; verify it stayed stable."""
    last_error: Exception | None = None
    for attempt in range(STAGING_RETRIES):
        attempt_dir = staging_root / f"copy-{attempt}"
        if attempt_dir.exists():
            shutil.rmtree(attempt_dir)
        attempt_dir.mkdir(parents=True)
        try:
            before_hash, before = database_fingerprint(source_db)
            for source_file in database_group_files(source_db):
                shutil.copy2(source_file, attempt_dir / source_file.name)
            after_hash, after = database_fingerprint(source_db)
            if before_hash != after_hash or before != after:
                raise RuntimeError("source changed while staging")
            staged_db = attempt_dir / source_db.name
            snapshot = attempt_dir / "snapshot.sqlite"
            source_conn = sqlite3.connect(staged_db, timeout=30.0)
            destination_conn = sqlite3.connect(snapshot)
            try:
                source_conn.execute("PRAGMA busy_timeout=30000")
                source_conn.backup(destination_conn)
                result = destination_conn.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise sqlite3.DatabaseError(f"snapshot integrity_check failed: {result}")
            finally:
                destination_conn.close()
                source_conn.close()
            return snapshot
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < STAGING_RETRIES:
                time.sleep(1.0 + attempt)
    raise SourceSnapshotBusyError(f"could not create stable snapshot of {source_db}: {last_error}")


def sqlite_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def table_info(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return [
        {"cid": row[0], "name": row[1], "type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]}
        for row in rows
    ]


def is_health_database(connection: sqlite3.Connection) -> bool:
    names = set(sqlite_tables(connection))
    anchors = {"heart_rate", "sleep", "steps", "spo2", "stress"}
    return len(names & anchors) >= 3


def is_relevant_table(name: str, columns: Sequence[str]) -> bool:
    if name in KNOWN_HEALTH_TABLES:
        return True
    lowered = name.lower()
    if any(fragment in lowered for fragment in HEALTH_NAME_FRAGMENTS):
        return True
    column_text = " ".join(column.lower() for column in columns)
    return any(fragment in column_text for fragment in ("hrv", "rmssd", "sdnn", "pnn50", "rr_interval", "inter_beat", "ibi"))


def canonicalize_record(row: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, bytes], str | None]:
    scalars: dict[str, Any] = {}
    blobs: dict[str, bytes] = {}
    value_json: str | None = None
    separately_stored = {
        "sid", "key", "time", "value", "zone_offset", "time_zero",
        "zone_name", "deleted", "isUploaded",
    }
    for key in row.keys():
        value = row[key]
        if isinstance(value, bytes):
            blobs[key] = value
            scalars[key] = {"__blob__": key, "length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
        else:
            if key == "value" and isinstance(value, str):
                parsed = parse_json(value)
                if parsed is not None:
                    value_json = json_dumps(parsed)
                else:
                    value_json = value
                continue
            if key not in separately_stored:
                scalars[key] = value
    return scalars, blobs, value_json


def record_identity(table: str, row: Mapping[str, Any], info: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    pk_columns = [item["name"] for item in sorted(info, key=lambda item: item["pk"]) if item["pk"]]
    if not pk_columns:
        preferred = [name for name in ("sid", "key", "time", "project_id", "category", "tag") if name in row.keys()]
        pk_columns = preferred or [name for name in row.keys() if not isinstance(row[name], bytes)]
    pk = {name: row[name] for name in pk_columns}
    pk_json = json_dumps(pk)
    # 128 bits is ample for a local deterministic key and halves every FK/index
    # compared with a 64-character SHA-256 hex string.
    digest = hashlib.blake2b((table + "\0" + pk_json).encode("utf-8"), digest_size=16).hexdigest()
    return digest, pk_json


def content_hash(row: Mapping[str, Any], value_json: str | None) -> bytes:
    """Compact canonical hash of the complete source row."""
    digest = hashlib.blake2b(digest_size=16)
    for name in sorted(row.keys()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        value = row[name]
        if isinstance(value, bytes):
            digest.update(value)
        elif name == "value" and value_json is not None:
            digest.update(value_json.encode("utf-8"))
        else:
            digest.update(json_dumps(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.digest()


def open_target(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=60.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=60000")
    connection.executescript(SCHEMA_SQL)
    connection.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
    connection.execute("INSERT OR REPLACE INTO schema_info(key,value) VALUES('extractor_version',?)", (EXTRACTOR_VERSION,))
    connection.commit()
    return connection


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"extractor_version": EXTRACTOR_VERSION, "databases": {}}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("state.json is not a JSON object")
    data.setdefault("databases", {})
    return data


def write_state_atomic(path: Path, state: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def insert_warning(
    target: sqlite3.Connection,
    run_id: str,
    record_id: str | None,
    warning_type: str,
    message: str,
    now: str,
) -> None:
    target.execute(
        "INSERT INTO quality_warnings(run_id,source_record_id,warning_type,message,created_at) VALUES(?,?,?,?,?)",
        (run_id, record_id, warning_type, message, now),
    )


def daily_upsert(target: sqlite3.Connection, local_date: str | None, values: Mapping[str, Any], now: str) -> None:
    if not local_date or not values:
        return
    columns = [key for key, value in values.items() if value is not None]
    if not columns:
        return
    quoted = ",".join(quote_identifier(column) for column in columns)
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{quote_identifier(column)}=excluded.{quote_identifier(column)}" for column in columns)
    sql = (
        f"INSERT INTO daily_summary(local_date,{quoted},updated_at) VALUES(?,{placeholders},?) "
        f"ON CONFLICT(local_date) DO UPDATE SET {updates},updated_at=excluded.updated_at"
    )
    target.execute(sql, [local_date, *(values[column] for column in columns), now])


def flatten_scalars(value: Any, prefix: str = "", depth: int = 0) -> Iterator[tuple[str, Any]]:
    if depth > 4:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_scalars(child, path, depth + 1)
    elif isinstance(value, list):
        # Large arrays (sleep items and value series) remain losslessly in raw storage.
        return
    elif value is None or isinstance(value, (str, int, float, bool)):
        yield prefix, value


def replace_derived_metrics(
    target: sqlite3.Connection,
    record_id: str,
    table: str,
    payload: Any,
    timestamp: int | None,
    local_date: str | None,
    now: str,
) -> None:
    target.execute("DELETE FROM derived_metrics WHERE source_record_id=?", (record_id,))
    if not isinstance(payload, dict):
        return
    for field_path, value in flatten_scalars(payload):
        if not field_path or field_path in {"time", "date_time", "start_time", "end_time"}:
            continue
        numeric = float(value) if isinstance(value, (int, float, bool)) else None
        text = value if isinstance(value, str) else None
        target.execute(
            """INSERT INTO derived_metrics(
                   source_record_id,source_table,field_path,metric_name,timestamp_utc,
                   local_date,numeric_value,text_value,imported_at
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (record_id, table, field_path, f"{table}.{field_path}", timestamp, local_date, numeric, text, now),
        )


def normalize_record(
    target: sqlite3.Connection,
    table: str,
    row: Mapping[str, Any],
    record_id: str,
    payload: Any,
    now: str,
) -> None:
    source_time = as_int(row.get("time"))
    local_time = as_int(row.get("time_zero"))
    offset = as_int(row.get("zone_offset"))
    if local_time is None and source_time is not None:
        local_time = source_time + (offset or 0)
    local_date = local_date_from_epoch(local_time if local_time is not None else source_time)
    key = str(row.get("key") or "")
    data = payload if isinstance(payload, dict) else {}

    if table == "heart_rate":
        if key in {"heart_rate", "single_heart_rate"}:
            timestamp = as_int(data.get("time")) or source_time
            bpm = as_float(data.get("bpm"))
            if timestamp is not None and bpm is not None:
                target.execute(
                    """INSERT INTO heart_rate VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_record_id) DO UPDATE SET
                       timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                       local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                       bpm=excluded.bpm,kind=excluded.kind,imported_at=excluded.imported_at""",
                    (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset, bpm, key, now),
                )
        elif key in {"low_heart_rate", "high_heart_rate", "abnormal_heart_rate"}:
            items = data.get("items") if isinstance(data.get("items"), list) else []
            values = [as_float(item.get("value")) for item in items if isinstance(item, dict)]
            values = [value for value in values if value is not None]
            start_time = as_int(data.get("start_time"))
            end_time = as_int(data.get("end_time")) or source_time
            target.execute(
                """INSERT INTO heart_rate_events VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   event_type=excluded.event_type,start_timestamp_utc=excluded.start_timestamp_utc,
                   end_timestamp_utc=excluded.end_timestamp_utc,local_date=excluded.local_date,
                   sample_count=excluded.sample_count,min_bpm=excluded.min_bpm,
                   max_bpm=excluded.max_bpm,imported_at=excluded.imported_at""",
                (record_id, key, start_time, end_time, local_date, len(items), min(values) if values else None, max(values) if values else None, now),
            )
            target.execute("DELETE FROM heart_rate_event_samples WHERE source_record_id=?", (record_id,))
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                target.execute(
                    "INSERT INTO heart_rate_event_samples VALUES(?,?,?,?)",
                    (record_id, index, as_int(item.get("time")), as_float(item.get("value"))),
                )
        elif key in {"resting_heart_rate", "min_heart_rate", "max_heart_rate"}:
            day = local_date_from_epoch(as_int(data.get("date_time")) or source_time)
            bpm = as_float(data.get("bpm"))
            field = {"resting_heart_rate": "resting_hr", "min_heart_rate": "min_hr", "max_heart_rate": "max_hr"}[key]
            daily_upsert(target, day, {field: bpm if bpm != 0 else None}, now)

    elif table == "heart_rate_day":
        daily_upsert(target, local_date, {
            "resting_hr": (as_float(data.get("avg_rhr")) if as_float(data.get("avg_rhr")) not in {0.0} else None),
            "avg_hr": as_float(data.get("avg_hr")),
            "min_hr": as_float(data.get("min_hr")),
            "max_hr": as_float(data.get("max_hr")),
            "abnormal_hr_count": as_int(data.get("abnormal_hr_count")),
        }, now)

    elif table == "spo2":
        timestamp = as_int(data.get("time")) or source_time
        value = as_float(data.get("spo2"))
        if timestamp is not None and value is not None:
            target.execute(
                """INSERT INTO spo2 VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                   local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                   value=excluded.value,kind=excluded.kind,imported_at=excluded.imported_at""",
                (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset, value, key, now),
            )

    elif table == "spo2_day":
        daily_upsert(target, local_date, {
            "avg_spo2": as_float(data.get("avg_spo2")),
            "min_spo2": as_float(data.get("min_spo2")),
            "max_spo2": as_float(data.get("max_spo2")),
            "low_spo2_count": as_int(data.get("lack_spo2_count")),
        }, now)

    elif table == "stress":
        timestamp = as_int(data.get("time")) or source_time
        value = as_float(data.get("stress"))
        if timestamp is not None and value is not None:
            target.execute(
                """INSERT INTO stress VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                   local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                   value=excluded.value,kind=excluded.kind,imported_at=excluded.imported_at""",
                (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset, value, key, now),
            )

    elif table == "stress_day":
        daily_upsert(target, local_date, {
            "avg_stress": as_float(data.get("avg_stress")),
            "min_stress": as_float(data.get("min_stress")),
            "max_stress": as_float(data.get("max_stress")),
        }, now)

    elif table == "steps":
        timestamp = as_int(data.get("time")) or source_time
        if timestamp is not None:
            target.execute(
                """INSERT INTO activity_samples VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                   local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                   steps=excluded.steps,distance=excluded.distance,calories=excluded.calories,
                   imported_at=excluded.imported_at""",
                (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset,
                 as_int(data.get("steps")), as_float(data.get("distance")), as_float(data.get("calories")), now),
            )

    elif table == "steps_day":
        daily_upsert(target, local_date, {
            "steps": as_int(data.get("steps")),
            "distance": as_float(data.get("distance")),
            "step_calories": as_float(data.get("calories")),
        }, now)

    elif table == "calories":
        timestamp = as_int(data.get("time")) or source_time
        if timestamp is not None:
            target.execute(
                """INSERT INTO calorie_samples VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                   local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                   calories=excluded.calories,imported_at=excluded.imported_at""",
                (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset,
                 as_float(data.get("calories")), now),
            )

    elif table == "calories_day":
        daily_upsert(target, local_date, {"total_calories": as_float(data.get("calories"))}, now)

    elif table == "intensity":
        timestamp = as_int(data.get("time")) or source_time
        if timestamp is not None:
            target.execute(
                """INSERT INTO intensity_samples VALUES(?,?,?,?,?,?)
                   ON CONFLICT(source_record_id) DO UPDATE SET
                   timestamp_utc=excluded.timestamp_utc,local_timestamp=excluded.local_timestamp,
                   local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
                   imported_at=excluded.imported_at""",
                (record_id, timestamp, timestamp + (offset or 0), local_date_from_epoch(timestamp + (offset or 0)), offset, now),
            )

    elif table == "intensity_day":
        daily_upsert(target, local_date, {"activity_duration_minutes": as_float(data.get("duration"))}, now)

    elif table == "valid_stand":
        target.execute(
            """INSERT INTO standing_intervals VALUES(?,?,?,?,?,?)
               ON CONFLICT(source_record_id) DO UPDATE SET
               start_timestamp_utc=excluded.start_timestamp_utc,end_timestamp_utc=excluded.end_timestamp_utc,
               local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
               imported_at=excluded.imported_at""",
            (record_id, as_int(data.get("start_time")), as_int(data.get("end_time")), local_date, offset, now),
        )

    elif table == "valid_stand_day":
        daily_upsert(target, local_date, {"standing_count": as_int(data.get("count"))}, now)

    elif table == "sleep":
        stages = data.get("items") if isinstance(data.get("items"), list) else []
        start_time = as_int(data.get("bedtime")) or as_int(data.get("device_bedtime"))
        end_time = as_int(data.get("wake_up_time")) or source_time
        has_stages = 1 if data.get("has_stage") is True or stages else 0
        duration = as_float(data.get("duration"))
        is_nap = 1 if not has_stages and duration is not None and duration < 240 else 0
        target.execute(
            """INSERT INTO sleep_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_record_id) DO UPDATE SET
               sleep_start_utc=excluded.sleep_start_utc,sleep_end_utc=excluded.sleep_end_utc,
               local_date=excluded.local_date,utc_offset_seconds=excluded.utc_offset_seconds,
               duration_minutes=excluded.duration_minutes,deep_minutes=excluded.deep_minutes,
               light_minutes=excluded.light_minutes,rem_minutes=excluded.rem_minutes,
               awake_minutes=excluded.awake_minutes,sleep_score=excluded.sleep_score,
               sleep_efficiency=excluded.sleep_efficiency,avg_hr=excluded.avg_hr,min_hr=excluded.min_hr,
               max_hr=excluded.max_hr,avg_spo2=excluded.avg_spo2,min_spo2=excluded.min_spo2,
               max_spo2=excluded.max_spo2,avg_respiratory_rate=excluded.avg_respiratory_rate,
               breathing_quality=excluded.breathing_quality,awake_count=excluded.awake_count,
               has_stages=excluded.has_stages,has_rem=excluded.has_rem,
               is_nap_inferred=excluded.is_nap_inferred,algorithm_version=excluded.algorithm_version,
               imported_at=excluded.imported_at""",
            (record_id, start_time, end_time, local_date, offset, duration,
             as_float(data.get("sleep_deep_duration")), as_float(data.get("sleep_light_duration")),
             as_float(data.get("sleep_rem_duration")), as_float(data.get("sleep_awake_duration")),
             as_float(data.get("sleep_score")), as_float(data.get("sleep_efficiency")),
             as_float(data.get("avg_hr")), as_float(data.get("min_hr")), as_float(data.get("max_hr")),
             as_float(data.get("avg_spo2")), as_float(data.get("min_spo2")), as_float(data.get("max_spo2")),
             as_float(data.get("avg_breath")), as_float(data.get("breath_quality")), as_int(data.get("awake_count")),
             has_stages, 1 if data.get("has_rem") is True else 0, is_nap,
             str(data.get("sleep_algorithm_version") if data.get("sleep_algorithm_version") is not None else data.get("version") or ""), now),
        )
        target.execute("DELETE FROM sleep_stages WHERE source_record_id=?", (record_id,))
        stage_names = {2: "deep", 3: "light", 4: "rem", 5: "awake"}
        for index, stage in enumerate(stages):
            if not isinstance(stage, dict):
                continue
            raw_state = as_int(stage.get("state"))
            start = as_int(stage.get("start_time"))
            end = as_int(stage.get("end_time"))
            if start is None or end is None:
                continue
            target.execute(
                "INSERT INTO sleep_stages VALUES(?,?,?,?,?,?,?)",
                (record_id, index, stage_names.get(raw_state, f"unknown_{raw_state}"), raw_state, start, end, (end - start) / 60.0),
            )

    elif table == "sleep_day":
        segments = data.get("segment_details") if isinstance(data.get("segment_details"), list) else []
        breath_values = [as_float(item.get("avg_breath")) for item in segments if isinstance(item, dict)]
        breath_values = [value for value in breath_values if value is not None]
        daily_upsert(target, local_date, {
            "sleep_total_minutes": as_float(data.get("total_duration")),
            "deep_sleep_minutes": as_float(data.get("sleep_deep_duration")),
            "light_sleep_minutes": as_float(data.get("sleep_light_duration")),
            "rem_sleep_minutes": as_float(data.get("sleep_rem_duration")),
            "awake_minutes": as_float(data.get("sleep_awake_duration")),
            "nap_minutes": as_float(data.get("sleep_nap_duration")),
            "sleep_score": as_float(data.get("sleep_score")),
            "avg_respiratory_rate": (sum(breath_values) / len(breath_values)) if breath_values else as_float(data.get("avg_breath")),
            "breathing_quality": as_float(data.get("breath_quality")),
            "avg_hr": as_float(data.get("avg_hr")),
            "min_hr": as_float(data.get("min_hr")),
            "max_hr": as_float(data.get("max_hr")),
            "avg_spo2": as_float(data.get("avg_spo2")),
            "min_spo2": as_float(data.get("min_spo2")),
            "max_spo2": as_float(data.get("max_spo2")),
        }, now)

    elif table == "vitality":
        daily_upsert(target, local_date, {"vitality": as_float(data.get("latest_accumulated_vitality"))}, now)

    elif table == "MIWDBSportTable":
        start = as_int(data.get("start_time")) or source_time
        end = as_int(data.get("end_time"))
        target.execute(
            """INSERT INTO workouts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_record_id) DO UPDATE SET
               start_timestamp_utc=excluded.start_timestamp_utc,end_timestamp_utc=excluded.end_timestamp_utc,
               local_date=excluded.local_date,workout_type=excluded.workout_type,sport_type=excluded.sport_type,
               duration_seconds=excluded.duration_seconds,calories=excluded.calories,avg_hr=excluded.avg_hr,
               min_hr=excluded.min_hr,max_hr=excluded.max_hr,training_load=excluded.training_load,
               recovery_time=excluded.recovery_time,aerobic_effect=excluded.aerobic_effect,
               anaerobic_effect=excluded.anaerobic_effect,vitality=excluded.vitality,imported_at=excluded.imported_at""",
            (record_id, start, end, local_date, key or str(row.get("category") or ""), str(data.get("sport_type") or ""),
             as_float(data.get("duration")), as_float(data.get("calories") or data.get("total_cal")),
             as_float(data.get("avg_hrm")), as_float(data.get("min_hrm")), as_float(data.get("max_hrm")),
             as_float(data.get("train_load")), as_float(data.get("recover_time")), as_float(data.get("train_effect")),
             as_float(data.get("anaerobic_train_effect")), as_float(data.get("vitality")), now),
        )

    if table not in HIGH_VOLUME_SAMPLE_TABLES:
        replace_derived_metrics(target, record_id, table, payload, source_time, local_date, now)


def process_table(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    source_db_id: int,
    table: str,
    info: Sequence[Mapping[str, Any]],
    cutoff: int | None,
    now: str,
    run_id: str,
    counts: Counter[str],
    group_counts: dict[str, Counter[str]],
    fail_after: int | None,
    processed_counter: list[int],
) -> int | None:
    columns = [item["name"] for item in info]
    timestamp_column = next((name for name in ("time", "date_time", "start_timestamp") if name in columns), None)
    sql = f"SELECT * FROM {quote_identifier(table)}"
    parameters: tuple[Any, ...] = ()
    if cutoff is not None and timestamp_column:
        sql += f" WHERE {quote_identifier(timestamp_column)} >= ?"
        parameters = (cutoff,)
    sql += f" ORDER BY {quote_identifier(timestamp_column)}" if timestamp_column else ""
    source.row_factory = sqlite3.Row
    max_timestamp: int | None = None
    group_name = METRIC_GROUPS.get(table, "Other health data")
    for sqlite_row in source.execute(sql, parameters):
        row = dict(sqlite_row)
        timestamp = as_int(row.get(timestamp_column)) if timestamp_column else None
        if timestamp is not None and (max_timestamp is None or timestamp > max_timestamp):
            max_timestamp = timestamp
        canonical, blobs, value_json = canonicalize_record(row)
        record_id, pk_json = record_identity(table, row, info)
        checksum = content_hash(row, value_json)
        existing = target.execute("SELECT content_hash FROM raw_records WHERE record_id=?", (record_id,)).fetchone()
        status = "unchanged"
        if existing is None:
            status = "new"
        elif existing[0] != checksum:
            status = "updated"

        local_epoch = as_int(row.get("time_zero"))
        source_timestamp = as_int(row.get("time")) or timestamp
        offset = as_int(row.get("zone_offset"))
        if local_epoch is None and source_timestamp is not None:
            local_epoch = source_timestamp + (offset or 0)
        local_date = local_date_from_epoch(local_epoch if local_epoch is not None else source_timestamp)

        stored_pk_json = pk_json
        try:
            pk_names = set(json.loads(pk_json).keys())
            if pk_names and pk_names <= {"sid", "key", "time"}:
                stored_pk_json = "{}"
        except (ValueError, AttributeError):
            pass

        if status != "unchanged":
            target.execute(
                """INSERT INTO raw_records(
                       record_id,source_db_id,source_table,source_pk_json,source_sid,source_key,
                       source_timestamp,source_local_timestamp,utc_offset_seconds,local_date,
                       source_deleted,value_json,record_json,content_hash,first_imported_at,imported_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(record_id) DO UPDATE SET
                       source_db_id=excluded.source_db_id,source_sid=excluded.source_sid,
                       source_key=excluded.source_key,source_timestamp=excluded.source_timestamp,
                       source_local_timestamp=excluded.source_local_timestamp,
                       utc_offset_seconds=excluded.utc_offset_seconds,local_date=excluded.local_date,
                       source_deleted=excluded.source_deleted,value_json=excluded.value_json,
                       record_json=excluded.record_json,content_hash=excluded.content_hash,
                       imported_at=excluded.imported_at""",
                (record_id, source_db_id, table, stored_pk_json, str(row.get("sid")) if row.get("sid") is not None else None,
                 str(row.get("key")) if row.get("key") is not None else None, source_timestamp, local_epoch, offset,
                 local_date, as_int(row.get("deleted")) or 0, value_json, json_dumps(canonical), checksum, now, now),
            )
            target.execute("DELETE FROM raw_blobs WHERE record_id=?", (record_id,))
            for name, data in blobs.items():
                target.execute(
                    "INSERT INTO raw_blobs VALUES(?,?,?,?)",
                    (record_id, name, sqlite3.Binary(data), hashlib.sha256(data).hexdigest()),
                )
            payload = parse_json(value_json) if value_json is not None else None
            normalize_record(target, table, row, record_id, payload, now)
            counts[status] += 1
            group_counts[group_name][status] += 1

        processed_counter[0] += 1
        if fail_after is not None and processed_counter[0] >= fail_after:
            raise RuntimeError(f"simulated failure after {processed_counter[0]} source rows")
    return max_timestamp


def run_sanity_checks(target: sqlite3.Connection, run_id: str, now: str) -> int:
    checks = [
        ("heart_rate_range", "SELECT source_record_id,bpm FROM heart_rate WHERE bpm < 25 OR bpm > 240", "BPM outside 25..240"),
        ("spo2_range", "SELECT source_record_id,value FROM spo2 WHERE value < 50 OR value > 100", "SpO2 outside 50..100"),
        ("stress_range", "SELECT source_record_id,value FROM stress WHERE value < 0 OR value > 100", "Stress outside 0..100"),
        ("sleep_order", "SELECT source_record_id,sleep_end_utc FROM sleep_sessions WHERE sleep_start_utc IS NOT NULL AND sleep_end_utc < sleep_start_utc", "sleep_end before sleep_start"),
        ("sleep_duration", "SELECT source_record_id,duration_minutes FROM sleep_sessions WHERE duration_minutes < 0", "negative sleep duration"),
        ("sleep_stage_order", "SELECT source_record_id,end_timestamp_utc FROM sleep_stages WHERE end_timestamp_utc < start_timestamp_utc", "sleep stage end before start"),
    ]
    warning_count = 0
    for warning_type, sql, message in checks:
        for record_id, value in target.execute(sql):
            insert_warning(target, run_id, record_id, warning_type, f"{message}: {value}", now)
            warning_count += 1
    now_epoch = int(time.time())
    lower = 946684800  # 2000-01-01
    upper = now_epoch + 366 * 86400
    for table, id_column, timestamp_column in (
        ("heart_rate", "source_record_id", "timestamp_utc"),
        ("spo2", "source_record_id", "timestamp_utc"),
        ("stress", "source_record_id", "timestamp_utc"),
        ("sleep_sessions", "source_record_id", "sleep_end_utc"),
    ):
        sql = f"SELECT {id_column},{timestamp_column} FROM {table} WHERE {timestamp_column} IS NOT NULL AND ({timestamp_column} < ? OR {timestamp_column} > ?)"
        for record_id, value in target.execute(sql, (lower, upper)):
            insert_warning(target, run_id, record_id, "timestamp_range", f"timestamp outside expected range: {value}", now)
            warning_count += 1
    integrity = target.execute("PRAGMA quick_check").fetchone()
    if not integrity or integrity[0] != "ok":
        raise sqlite3.DatabaseError(f"target quick_check failed: {integrity}")
    return warning_count


def source_database_row(
    target: sqlite3.Connection,
    relative_path: str,
    fingerprint: str,
    now: str,
    is_health: bool,
) -> int:
    target.execute(
        """INSERT INTO source_databases(relative_path,last_fingerprint,last_seen_at,is_health_database)
           VALUES(?,?,?,?)
           ON CONFLICT(relative_path) DO UPDATE SET
           last_fingerprint=excluded.last_fingerprint,last_seen_at=excluded.last_seen_at,
           is_health_database=excluded.is_health_database""",
        (relative_path, fingerprint, now, 1 if is_health else 0),
    )
    return int(target.execute("SELECT source_db_id FROM source_databases WHERE relative_path=?", (relative_path,)).fetchone()[0])


def overall_source_fingerprint(fingerprints: Mapping[str, str]) -> str:
    return hashlib.sha256(json_dumps(fingerprints).encode("utf-8")).hexdigest()


def compact_group_lines(group_counts: Mapping[str, Counter[str]]) -> list[str]:
    preferred = ["Heart rate", "SpO2", "Stress", "Sleep sessions", "Activity", "Vitality", "Training load", "Workouts", "Other health data"]
    lines: list[str] = []
    for name in preferred:
        counter = group_counts.get(name)
        if not counter or not (counter["new"] or counter["updated"]):
            continue
        lines.extend([f"{name}:", f"  new: {counter['new']}", f"  updated: {counter['updated']}"])
    return lines


def process(args: argparse.Namespace) -> int:
    started_monotonic = time.monotonic()
    started = utc_now()
    source_root = Path(args.source).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"source directory not found: {source_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    health_path = output_root / "health.sqlite"
    state_path = output_root / "state.json"
    state = load_state(state_path)
    candidates = discover_candidate_databases(source_root)

    fingerprints: dict[str, str] = {}
    fingerprint_details: dict[str, Any] = {}
    for database in candidates:
        relative = database.relative_to(source_root).as_posix()
        fingerprint, details = database_fingerprint(database)
        fingerprints[relative] = fingerprint
        fingerprint_details[relative] = details
    current_overall = overall_source_fingerprint(fingerprints)
    previous_overall = state.get("source_fingerprint")
    if not args.force and health_path.exists() and previous_overall == current_overall:
        print("Mi Fitness ETL")
        print("Source changed: NO")
        print("NO NEW SOURCE DATA")
        print(f"Duration: {time.monotonic() - started_monotonic:.2f} sec")
        print("Status: SUCCESS")
        return 0

    previous_databases = state.get("databases", {})
    changed = [
        database for database in candidates
        if args.force or previous_databases.get(database.relative_to(source_root).as_posix(), {}).get("fingerprint") != fingerprints[database.relative_to(source_root).as_posix()]
    ]
    # A missing/empty target always requires a full import from every database.
    if not health_path.exists() or not previous_databases:
        changed = candidates

    prior_max_values = [as_int(item.get("max_source_timestamp")) for item in previous_databases.values()]
    prior_max_values = [value for value in prior_max_values if value is not None]
    global_previous_max = max(prior_max_values) if prior_max_values else None
    overlap_seconds = int(args.overlap_hours * 3600)
    display_window_start = global_previous_max - overlap_seconds if global_previous_max is not None else None
    run_id = str(uuid.uuid4())
    now = iso_utc(started)
    counts: Counter[str] = Counter()
    group_counts: dict[str, Counter[str]] = defaultdict(Counter)
    processed_counter = [0]
    next_database_state = dict(previous_databases)
    target = open_target(health_path)

    try:
        target.execute("BEGIN IMMEDIATE")
        target.execute(
            """INSERT INTO etl_runs(run_id,started_at,status,source_root,overlap_hours,window_start_utc,window_end_utc)
               VALUES(?,?,?,?,?,?,?)""",
            (run_id, now, "RUNNING", str(source_root), args.overlap_hours, display_window_start, None),
        )
        with tempfile.TemporaryDirectory(prefix=".mi-fitness-stage-", dir=output_root) as temporary:
            staging_root = Path(temporary)
            for index, database in enumerate(changed):
                relative = database.relative_to(source_root).as_posix()
                snapshot = stable_stage_database(database, staging_root / f"db-{index}")
                source = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True, timeout=30.0)
                source.row_factory = sqlite3.Row
                try:
                    health_database = is_health_database(source)
                    source_db_id = source_database_row(target, relative, fingerprints[relative], now, health_database)
                    db_state = previous_databases.get(relative, {})
                    previous_max = as_int(db_state.get("max_source_timestamp"))
                    cutoff = None
                    if previous_max is not None and health_database:
                        cutoff = previous_max - overlap_seconds
                        # Include the full UTC bucket day containing the overlap boundary.
                        cutoff = (cutoff // 86400) * 86400
                    database_max = previous_max
                    if health_database:
                        for table in sqlite_tables(source):
                            info = table_info(source, table)
                            columns = [item["name"] for item in info]
                            if not is_relevant_table(table, columns):
                                continue
                            target.execute(
                                """INSERT INTO source_table_catalog VALUES(?,?,?,?,?)
                                   ON CONFLICT(source_db_id,table_name) DO UPDATE SET
                                   columns_json=excluded.columns_json,primary_key_json=excluded.primary_key_json,
                                   observed_at=excluded.observed_at""",
                                (source_db_id, table, json_dumps(info),
                                 json_dumps([item["name"] for item in sorted(info, key=lambda item: item["pk"]) if item["pk"]]), now),
                            )
                            table_max = process_table(
                                source, target, source_db_id, table, info, cutoff, now, run_id,
                                counts, group_counts, args.fail_after, processed_counter,
                            )
                            if table_max is not None and (database_max is None or table_max > database_max):
                                database_max = table_max
                    next_database_state[relative] = {
                        "fingerprint": fingerprints[relative],
                        "files": fingerprint_details[relative],
                        "is_health_database": health_database,
                        "max_source_timestamp": database_max,
                    }
                    target.execute(
                        "UPDATE source_databases SET max_source_timestamp=? WHERE source_db_id=?",
                        (database_max, source_db_id),
                    )
                finally:
                    source.close()

        warnings = run_sanity_checks(target, run_id, now)
        max_values = [as_int(item.get("max_source_timestamp")) for item in next_database_state.values()]
        max_values = [value for value in max_values if value is not None]
        maximum_source_timestamp = max(max_values) if max_values else None
        finished = utc_now()
        duration = time.monotonic() - started_monotonic
        target.execute(
            """UPDATE etl_runs SET finished_at=?,status='SUCCESS',window_end_utc=?,rows_new=?,
               rows_updated=?,warnings=?,duration_seconds=? WHERE run_id=?""",
            (iso_utc(finished), maximum_source_timestamp, counts["new"], counts["updated"], warnings, duration, run_id),
        )
        target.commit()

        next_state = {
            "extractor_version": EXTRACTOR_VERSION,
            "schema_version": SCHEMA_VERSION,
            "last_successful_run": iso_utc(finished),
            "maximum_source_timestamp": maximum_source_timestamp,
            "source_fingerprint": current_overall,
            "source_root": str(source_root),
            "overlap_hours": args.overlap_hours,
            "databases": next_database_state,
            "last_run_counts": {
                "new": counts["new"],
                "updated": counts["updated"],
                "unchanged_scanned": processed_counter[0] - counts["new"] - counts["updated"],
                "warnings": warnings,
                "by_group": {name: dict(counter) for name, counter in group_counts.items()},
            },
        }
        write_state_atomic(state_path, next_state)

        print("Mi Fitness ETL")
        print("Source changed: YES")
        print(f"Window: {format_epoch(display_window_start)} -> {format_epoch(maximum_source_timestamp)}")
        for line in compact_group_lines(group_counts):
            print(line)
        if not compact_group_lines(group_counts):
            print("Rows:")
            print("  new: 0")
            print("  updated: 0")
        print(f"Warnings: {warnings}")
        print(f"Duration: {duration:.2f} sec")
        print("Status: SUCCESS")
        return 0
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Incremental local ETL for Xiaomi Mi Fitness data")
    parser.add_argument("--source", required=True, help="read-only Mi Fitness export directory")
    parser.add_argument("--output", required=True, help="directory for health.sqlite and state.json")
    parser.add_argument("--overlap-hours", type=float, default=DEFAULT_OVERLAP_HOURS, help="incremental overlap window (default: 48)")
    parser.add_argument("--force", action="store_true", help="process stable snapshots even when source fingerprint is unchanged")
    parser.add_argument("--fail-after", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=EXTRACTOR_VERSION)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.overlap_hours < 0:
        parser.error("--overlap-hours must be non-negative")
    try:
        return process(args)
    except SourceSnapshotBusyError as exc:
        print("Mi Fitness ETL")
        print("SKIPPED: Mi Fitness NAS source changed during staging")
        print(f"Reason: {exc}")
        print("Status: SKIPPED")
        return 0
    except Exception as exc:
        print("Mi Fitness ETL", file=sys.stderr)
        print(f"Status: FAILED", file=sys.stderr)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
