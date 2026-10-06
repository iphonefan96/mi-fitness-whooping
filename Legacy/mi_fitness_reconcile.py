#!/usr/bin/env python3
"""Disposable, authoritative Mi Fitness reconciliation candidate (schema v2).

This never writes a source DB or the installed production health.sqlite. It
builds/updates only ``health-rebuild.sqlite`` under an explicit output directory.
No network or third-party packages are used.
"""

from __future__ import annotations

import argparse
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
from collections import Counter
from pathlib import Path

from mi_fitness_etl import (
    SCHEMA_SQL, SourceSnapshotBusyError, as_int, canonicalize_record,
    content_hash, database_fingerprint, database_group_files,
    discover_candidate_databases, is_health_database, is_relevant_table,
    json_dumps, local_date_from_epoch, normalize_record, parse_json,
    quote_identifier, record_identity, run_sanity_checks,
    sqlite_tables, stable_stage_database, table_info,
)

RECONCILE_VERSION = "2.1.0-candidate"
CONFLICT_POLICY_VERSION = "physiology-v1"
TARGET_NAME = "health-rebuild.sqlite"
DEEP_INTERVAL_HOURS = 24

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS reconcile_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_database_identities (
  source_db_id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE,
  relative_path TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_generations (
  generation_id TEXT PRIMARY KEY, scanned_at TEXT NOT NULL,
  authoritative_manifest_sha256 TEXT NOT NULL,
  source_database_count INTEGER NOT NULL, physical_row_count INTEGER NOT NULL,
  conflict_policy_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS physical_records (
  physical_record_id TEXT PRIMARY KEY,
  logical_record_id TEXT NOT NULL,
  source_db_id INTEGER NOT NULL REFERENCES source_database_identities(source_db_id),
  source_table TEXT NOT NULL, source_pk_json TEXT NOT NULL,
  source_timestamp INTEGER, local_date TEXT,
  row_json TEXT NOT NULL, value_json TEXT,
  content_hash BLOB NOT NULL, source_deleted INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK(status IN ('ACTIVE','TOMBSTONE','MISSING')),
  first_seen_at TEXT NOT NULL, version_from TEXT NOT NULL, last_seen_at TEXT NOT NULL,
  last_seen_generation TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS physical_logical_idx ON physical_records(logical_record_id,status);
CREATE INDEX IF NOT EXISTS physical_source_seen_idx ON physical_records(source_db_id,last_seen_generation);
CREATE TABLE IF NOT EXISTS physical_blobs (
  physical_record_id TEXT NOT NULL REFERENCES physical_records(physical_record_id),
  column_name TEXT NOT NULL, data BLOB NOT NULL, sha256 TEXT NOT NULL,
  PRIMARY KEY(physical_record_id,column_name)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS physical_record_history (
  history_id INTEGER PRIMARY KEY, physical_record_id TEXT NOT NULL,
  content_hash BLOB NOT NULL, status TEXT NOT NULL,
  row_json TEXT NOT NULL, value_json TEXT,
  active_from TEXT NOT NULL, active_to TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS physical_blob_archive (
  physical_record_id TEXT NOT NULL, column_name TEXT NOT NULL,
  sha256 TEXT NOT NULL, data BLOB NOT NULL,
  PRIMARY KEY(physical_record_id,column_name,sha256)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS physical_history_id_idx ON physical_record_history(physical_record_id);
CREATE TABLE IF NOT EXISTS canonical_selection (
  logical_record_id TEXT PRIMARY KEY, physical_record_id TEXT NOT NULL,
  content_hash BLOB NOT NULL, source_db_id INTEGER NOT NULL,
  source_table TEXT NOT NULL, source_timestamp INTEGER, local_date TEXT,
  conflict_status TEXT NOT NULL, conflict_policy_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_conflicts (
  conflict_id TEXT PRIMARY KEY, logical_record_id TEXT NOT NULL,
  table_name TEXT NOT NULL, physical_ids_json TEXT NOT NULL,
  payload_hashes_json TEXT NOT NULL, selected_physical_id TEXT NOT NULL,
  selection_reason TEXT NOT NULL, status TEXT NOT NULL,
  detected_at TEXT NOT NULL, conflict_policy_version TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS normalized_provenance (
  logical_record_id TEXT NOT NULL, physical_record_id TEXT NOT NULL,
  source_db_id INTEGER NOT NULL, source_table TEXT NOT NULL,
  source_pk_json TEXT NOT NULL, role TEXT NOT NULL,
  generation_id TEXT NOT NULL, conflict_policy_version TEXT NOT NULL,
  PRIMARY KEY(logical_record_id,physical_record_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS normalized_change_log (
  change_id INTEGER PRIMARY KEY, generation_id TEXT NOT NULL,
  source_table TEXT NOT NULL, logical_record_id TEXT NOT NULL,
  old_hash TEXT, new_hash TEXT,
  change_type TEXT NOT NULL CHECK(change_type IN
    ('INSERT','UPDATE','DELETE','CONFLICT_CHANGE')),
  affected_timestamp INTEGER, affected_local_date TEXT,
  old_timestamp INTEGER, old_local_date TEXT,
  new_timestamp INTEGER, new_local_date TEXT,
  detected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS normalized_change_gen_idx ON normalized_change_log(generation_id);
CREATE INDEX IF NOT EXISTS normalized_change_date_idx ON normalized_change_log(affected_local_date);
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _group_full_manifest(base: Path) -> dict[str, str]:
    return {p.name: _sha256_file(p) for p in database_group_files(base)}


def _source_key(source_root: Path, path: Path) -> str:
    relative = path.relative_to(source_root)
    if path.parent.name.lower() in {"cn", "ru"}:
        # Mi Fitness's filename is the account namespace; region is the DB
        # namespace. Moving the enclosing export folder does not change either.
        return f"xiaomi-account:{path.stem}:region:{path.parent.name.lower()}"
    return "xiaomi-relative:" + relative.as_posix()


def _authoritative_databases(source_root: Path) -> list[Path]:
    """Ignore Synology conflict copies; they are historical forks, not live DBs."""
    return [path for path in discover_candidate_databases(source_root)
            if ".conflict-" not in path.name.lower()]


def _source_id(key: str) -> int:
    # Stable positive SQLite INTEGER, independent of discovery order.
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") & ((1 << 63) - 1)


def _physical_id(source_key: str, logical_id: str) -> str:
    return hashlib.sha256((source_key + "\0" + logical_id).encode()).hexdigest()[:40]


def _read_state(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM reconcile_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO reconcile_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _init_db(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript(SCHEMA_SQL)
    db.executescript(EXTRA_SCHEMA)
    for table in ("source_generations", "canonical_selection", "source_conflicts",
                  "normalized_provenance"):
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if "conflict_policy_version" not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN conflict_policy_version TEXT NOT NULL DEFAULT 'legacy-ru-compat'")
    columns = {row[1] for row in db.execute("PRAGMA table_info(normalized_change_log)")}
    for name, kind in (("old_timestamp", "INTEGER"), ("old_local_date", "TEXT"),
                       ("new_timestamp", "INTEGER"), ("new_local_date", "TEXT")):
        if name not in columns:
            db.execute(f"ALTER TABLE normalized_change_log ADD COLUMN {name} {kind}")
    db.execute("INSERT OR REPLACE INTO schema_info VALUES('schema_version','2')")
    db.execute("INSERT OR REPLACE INTO schema_info VALUES('extractor_version',?)", (RECONCILE_VERSION,))
    db.commit()


def _scan_database(db: sqlite3.Connection, source: sqlite3.Connection, source_key: str,
                   relative: str, generation: str, now: str, snapshot_sha: str,
                   counters: Counter) -> None:
    sid = _source_id(source_key)
    existing = db.execute("SELECT source_key FROM source_database_identities WHERE source_db_id=?", (sid,)).fetchone()
    if existing and existing[0] != source_key:
        raise RuntimeError("source database identity hash collision")
    db.execute("""INSERT INTO source_database_identities VALUES(?,?,?,?,?)
      ON CONFLICT(source_db_id) DO UPDATE SET relative_path=excluded.relative_path,
      last_seen_at=excluded.last_seen_at""", (sid, source_key, relative, now, now))
    db.execute("""INSERT INTO source_databases
      (source_db_id,relative_path,last_fingerprint,max_source_timestamp,last_seen_at,is_health_database)
      VALUES(?,?,?,?,?,?) ON CONFLICT(source_db_id) DO UPDATE SET
      relative_path=excluded.relative_path,last_fingerprint=excluded.last_fingerprint,
      last_seen_at=excluded.last_seen_at,is_health_database=excluded.is_health_database""",
      (sid, relative, snapshot_sha, None, now, int(is_health_database(source))))
    max_ts = None
    if is_health_database(source):
        for table in sqlite_tables(source):
            info = table_info(source, table)
            columns = [item["name"] for item in info]
            if not is_relevant_table(table, columns):
                continue
            db.execute("""INSERT INTO source_table_catalog VALUES(?,?,?,?,?)
              ON CONFLICT(source_db_id,table_name) DO UPDATE SET
              columns_json=excluded.columns_json,primary_key_json=excluded.primary_key_json,
              observed_at=excluded.observed_at""",
              (sid, table, json_dumps(info), json_dumps([i["name"] for i in info if i["pk"]]), now))
            timestamp_col = next((x for x in ("time", "date_time", "start_timestamp") if x in columns), None)
            for source_row in source.execute(f"SELECT * FROM {quote_identifier(table)}"):
                row = dict(source_row)
                logical_id, pk_json = record_identity(table, row, info)
                physical_id = _physical_id(source_key, logical_id)
                canonical, blobs, value_json = canonicalize_record(row)
                digest = content_hash(row, value_json)
                timestamp = as_int(row.get(timestamp_col)) if timestamp_col else None
                if timestamp is not None:
                    max_ts = timestamp if max_ts is None else max(max_ts, timestamp)
                local_epoch = as_int(row.get("time_zero"))
                if local_epoch is None and timestamp is not None:
                    local_epoch = timestamp + (as_int(row.get("zone_offset")) or 0)
                local_date = local_date_from_epoch(local_epoch if local_epoch is not None else timestamp)
                deleted = int(as_int(row.get("deleted")) == 1)
                status = "TOMBSTONE" if deleted else "ACTIVE"
                # BLOB values are stored separately; a marker makes round-trip
                # reconstruction unambiguous without embedding base64 in JSON.
                row_json = json_dumps({k: ({"__physical_blob__": k} if isinstance(v, bytes) else v)
                                       for k, v in row.items()})
                old = db.execute("SELECT content_hash,status,row_json,value_json,first_seen_at,version_from FROM physical_records WHERE physical_record_id=?", (physical_id,)).fetchone()
                if old and (old[0] != digest or old[1] != status):
                    db.execute("INSERT INTO physical_record_history(physical_record_id,content_hash,status,row_json,value_json,active_from,active_to) VALUES(?,?,?,?,?,?,?)",
                               (physical_id, old[0], old[1], old[2], old[3], old[5], now))
                    counters["physical_updated"] += 1
                elif old is None:
                    counters["physical_added"] += 1
                version_from = now if old is None or old[0] != digest or old[1] != status else old[5]
                db.execute("""INSERT INTO physical_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(physical_record_id) DO UPDATE SET
                  source_db_id=excluded.source_db_id,source_table=excluded.source_table,
                  source_pk_json=excluded.source_pk_json,source_timestamp=excluded.source_timestamp,
                  local_date=excluded.local_date,row_json=excluded.row_json,value_json=excluded.value_json,
                  content_hash=excluded.content_hash,source_deleted=excluded.source_deleted,
                  status=excluded.status,version_from=excluded.version_from,
                  last_seen_at=excluded.last_seen_at,
                  last_seen_generation=excluded.last_seen_generation""",
                  (physical_id, logical_id, sid, table, pk_json, timestamp, local_date,
                   row_json, value_json, digest, deleted, status, old[4] if old else now,
                   version_from, now, generation))
                if old is None or old[0] != digest:
                    if old is not None:
                        db.execute("""INSERT OR IGNORE INTO physical_blob_archive
                          SELECT physical_record_id,column_name,sha256,data FROM physical_blobs
                          WHERE physical_record_id=?""", (physical_id,))
                    db.execute("DELETE FROM physical_blobs WHERE physical_record_id=?", (physical_id,))
                    for name, data in blobs.items():
                        db.execute("INSERT INTO physical_blobs VALUES(?,?,?,?)",
                                   (physical_id, name, sqlite3.Binary(data), hashlib.sha256(data).hexdigest()))
                counters["physical_seen"] += 1
    for old in db.execute("SELECT physical_record_id,content_hash,status,row_json,value_json,version_from FROM physical_records WHERE source_db_id=? AND last_seen_generation<>?", (sid, generation)).fetchall():
        if old[2] != "MISSING":
            db.execute("INSERT INTO physical_record_history(physical_record_id,content_hash,status,row_json,value_json,active_from,active_to) VALUES(?,?,?,?,?,?,?)",
                       (old[0], old[1], old[2], old[3], old[4], old[5], now))
            db.execute("UPDATE physical_records SET status='MISSING',version_from=?,last_seen_at=? WHERE physical_record_id=?", (now, now, old[0]))
            counters["physical_missing"] += 1
    db.execute("UPDATE source_databases SET max_source_timestamp=? WHERE source_db_id=?", (max_ts, sid))


def _rebuild_canonical(db: sqlite3.Connection, generation: str, now: str,
                       run_id: str, counters: Counter, selection_policy: str,
                       initial_build: bool = False) -> None:
    policy_version = f"{CONFLICT_POLICY_VERSION}:{selection_policy}"
    db.execute("CREATE TEMP TABLE old_choice AS SELECT * FROM canonical_selection")
    db.execute("CREATE INDEX old_choice_id_idx ON old_choice(logical_record_id)")
    db.execute("CREATE TEMP TABLE old_import AS SELECT record_id,content_hash,source_db_id,first_imported_at,imported_at FROM raw_records")
    db.execute("CREATE INDEX old_import_id_idx ON old_import(record_id)")
    db.execute("DELETE FROM canonical_selection")
    db.execute("DELETE FROM normalized_provenance")
    db.execute("DELETE FROM source_conflicts")
    db.execute("DELETE FROM raw_records")  # cascades normalized FK tables
    db.execute("DELETE FROM daily_summary") # daily aggregates have no raw FK
    db.execute("DELETE FROM quality_warnings")

    # Group the physical layer by logical vendor PK. Both regional physical
    # rows remain present even when one is selected for the canonical mirror.
    cursor = db.execute("""SELECT p.physical_record_id,p.logical_record_id,p.source_db_id,
      p.source_table,p.source_pk_json,p.source_timestamp,p.local_date,p.content_hash,
      p.status,i.source_key,p.value_json FROM physical_records p JOIN source_database_identities i
      ON i.source_db_id=p.source_db_id ORDER BY p.logical_record_id,p.physical_record_id""")
    group: list[sqlite3.Row] = []

    def finish(rows: list[sqlite3.Row]) -> None:
        if not rows:
            return
        logical_id = rows[0][1]
        active = [r for r in rows if r[8] == "ACTIVE"]
        # Region priority is only a compatibility tie-break, not a claim that
        # RU is physiologically more accurate. Differing payload stays UNRESOLVED.
        preferred = ":region:ru" if selection_policy == "ru_compat" else ":region:cn"
        if selection_policy == "unresolved_exclude":
            preferred = ":region:ru"
        secondary = ":region:cn" if preferred == ":region:ru" else ":region:ru"
        priority = lambda r: (0 if r[9].endswith(preferred) else 1 if r[9].endswith(secondary) else 2,
                              r[9], r[0])
        candidate = min(active, key=priority) if active else None
        hashes = {r[7].hex() for r in active}
        physical_conflict = len(hashes) > 1
        semantic_conflict = len({(r[10], r[5], r[6]) for r in active}) > 1
        chosen = None if semantic_conflict and selection_policy == "unresolved_exclude" else candidate
        state = ("UNRESOLVED_EXCLUDED" if semantic_conflict and chosen is None else
                 "UNRESOLVED_SELECTED_FOR_COMPATIBILITY" if semantic_conflict else
                 "EQUIVALENT_PHYSIOLOGY_METADATA_DIFF" if physical_conflict else
                 "DUPLICATE_EQUAL" if len(active) > 1 else "NONE")
        if physical_conflict:
            db.execute("""INSERT INTO source_conflicts
              (conflict_id,logical_record_id,table_name,physical_ids_json,payload_hashes_json,
               selected_physical_id,selection_reason,status,detected_at,conflict_policy_version)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (logical_id, logical_id, rows[0][3], json_dumps([r[0] for r in active]),
                        json_dumps([r[7].hex() for r in active]), chosen[0] if chosen else "",
                        "UNRESOLVED_NO_ROW_VERSION_EXCLUDED" if chosen is None else
                        f"EQUIVALENT_VALUE_{selection_policy.upper()}_REPRESENTATIVE" if not semantic_conflict else
                        "RU_PRIORITY_FOR_COMPATIBILITY_UNVERIFIED" if selection_policy == "ru_compat" else
                        "CN_PRIORITY_FOR_REVIEW_UNVERIFIED",
                        state, now, policy_version))
            counters["conflicts_unresolved" if semantic_conflict else "metadata_conflicts"] += 1
        elif len(active) > 1:
            counters["duplicates_equal"] += 1
        for r in rows:
            role = ("PRIMARY" if chosen and r[0] == chosen[0] else
                    "CONFLICT_ALTERNATIVE" if r[8] == "ACTIVE" and semantic_conflict else
                    ("DUPLICATE_EQUIVALENT" if physical_conflict else "DUPLICATE_EQUAL") if r[8] == "ACTIVE" else
                    "TOMBSTONE_SOURCE" if r[8] == "TOMBSTONE" else "SOURCE_MISSING")
            db.execute("""INSERT INTO normalized_provenance
              (logical_record_id,physical_record_id,source_db_id,source_table,source_pk_json,
               role,generation_id,conflict_policy_version) VALUES(?,?,?,?,?,?,?,?)""",
                       (logical_id, r[0], r[2], r[3], r[4], role, generation, policy_version))
        previous = db.execute("SELECT physical_record_id,content_hash,source_table,source_timestamp,local_date,conflict_status FROM old_choice WHERE logical_record_id=?", (logical_id,)).fetchone()
        if chosen:
            db.execute("""INSERT INTO canonical_selection
              (logical_record_id,physical_record_id,content_hash,source_db_id,source_table,
               source_timestamp,local_date,conflict_status,conflict_policy_version)
              VALUES(?,?,?,?,?,?,?,?,?)""",
                       (logical_id, chosen[0], chosen[7], chosen[2], chosen[3], chosen[5], chosen[6], state, policy_version))
        change = None
        if previous is None and chosen:
            change = "INSERT"
        elif previous and chosen is None:
            change = "DELETE"
        elif previous and chosen and (previous[0] != chosen[0] or previous[1] != chosen[7]):
            change = "UPDATE"
        elif previous and previous[5] != state:
            change = "CONFLICT_CHANGE"
        if change:
            # A fresh rebuild is a complete baseline, not 760k individual
            # mutations to an existing analytics state. Its generation row
            # records the full scan; later changes still get per-row logs.
            if not (initial_build and change == "INSERT"):
                db.execute("""INSERT INTO normalized_change_log
                  (generation_id,source_table,logical_record_id,old_hash,new_hash,change_type,
                   affected_timestamp,affected_local_date,old_timestamp,old_local_date,
                   new_timestamp,new_local_date,detected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (generation, chosen[3] if chosen else previous[2], logical_id,
                   previous[1].hex() if previous else None, chosen[7].hex() if chosen else None,
                   change, chosen[5] if chosen else previous[3], chosen[6] if chosen else previous[4],
                   previous[3] if previous else None, previous[4] if previous else None,
                   chosen[5] if chosen else None, chosen[6] if chosen else None, now))
            counters["canonical_" + change.lower()] += 1

    for row in cursor:
        if group and row[1] != group[0][1]:
            finish(group)
            group = []
        group.append(row)
    finish(group)
    db.execute("DROP TABLE old_choice")

    # The existing tables are a deterministic canonical mirror. Alternatives
    # remain losslessly available in physical_records/physical_blobs/history.
    selected = db.execute("""SELECT c.logical_record_id,p.physical_record_id,p.source_db_id,
      p.source_table,p.source_pk_json,p.source_timestamp,p.local_date,p.row_json,p.value_json,p.content_hash
      FROM canonical_selection c JOIN physical_records p
      ON c.physical_record_id=p.physical_record_id
      ORDER BY p.source_table,p.source_timestamp,c.logical_record_id""")
    for r in selected:
        row = json.loads(r[7])
        for key, value in list(row.items()):
            if isinstance(value, dict) and value.get("__physical_blob__") == key:
                blob = db.execute("SELECT data FROM physical_blobs WHERE physical_record_id=? AND column_name=?", (r[1], key)).fetchone()
                row[key] = blob[0] if blob else None
        canonical, blobs, value_json = canonicalize_record(row)
        timestamp = as_int(row.get("time")) or r[5]
        offset = as_int(row.get("zone_offset"))
        local_epoch = as_int(row.get("time_zero"))
        if local_epoch is None and timestamp is not None:
            local_epoch = timestamp + (offset or 0)
        old_import = db.execute("SELECT content_hash,source_db_id,first_imported_at,imported_at FROM old_import WHERE record_id=?", (r[0],)).fetchone()
        imported_at = old_import[3] if old_import and old_import[0] == r[9] and old_import[1] == r[2] else now
        first_imported_at = old_import[2] if old_import else now
        db.execute("INSERT INTO raw_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (r[0], r[2], r[3], r[4], str(row.get("sid")) if row.get("sid") is not None else None,
                    str(row.get("key")) if row.get("key") is not None else None,
                    timestamp, local_epoch, offset, r[6], 0, value_json,
                    json_dumps(canonical), r[9], first_imported_at, imported_at))
        for name, data in blobs.items():
            db.execute("INSERT INTO raw_blobs VALUES(?,?,?,?)",
                       (r[0], name, sqlite3.Binary(data), hashlib.sha256(data).hexdigest()))
        # Legacy table is now populated as an additional simple provenance view.
        for item in db.execute("SELECT source_db_id FROM normalized_provenance WHERE logical_record_id=?", (r[0],)).fetchall():
            db.execute("INSERT OR IGNORE INTO record_provenance VALUES(?,?,?)", (r[0], item[0], now))
        payload = parse_json(value_json) if value_json is not None else None
        normalize_record(db, r[3], row, r[0], payload, imported_at)
        counters["canonical_rows"] += 1
    db.execute("DROP TABLE old_import")
    counters["warnings"] = run_sanity_checks(db, run_id, now)


def reconcile(source_root: Path, output_dir: Path, *, rebuild: bool = False,
              full: bool = False, deep_hours: int = DEEP_INTERVAL_HOURS,
              selection_policy: str = "ru_compat",
              target_name: str = TARGET_NAME) -> dict:
    start = time.monotonic()
    source_root = source_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source_root.is_dir():
        return {"status": "SKIPPED", "reason": "SOURCE_UNAVAILABLE"}
    if selection_policy not in {"ru_compat", "cn_review", "unresolved_exclude"}:
        raise ValueError("unsupported selection policy")
    if Path(target_name).name != target_name or not target_name.endswith(".sqlite"):
        raise ValueError("target name must be a SQLite basename")
    # This candidate intentionally cannot be pointed at the installed runtime.
    production = Path("/Users/rus/Library/Application Support/MiFitnessETL").resolve()
    if output_dir == production or production in output_dir.parents:
        raise ValueError("production output is forbidden for reconciliation candidate")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / target_name
    candidates = _authoritative_databases(source_root)
    keys = [_source_key(source_root, p) for p in candidates]
    if len(keys) != len(set(keys)):
        raise RuntimeError("ambiguous duplicate source database identity")
    quick = {key: database_fingerprint(path)[0] for key, path in zip(keys, candidates)}
    quick_digest = hashlib.sha256(json_dumps(quick).encode()).hexdigest()
    if not rebuild and not full and target.exists():
        probe = sqlite3.connect("file:" + str(target) + "?mode=ro", uri=True)
        try:
            if probe.execute("SELECT value FROM schema_info WHERE key='schema_version'").fetchone()[0] != "2":
                raise RuntimeError("target is not schema v2; use --rebuild-from-source")
            previous = _read_state(probe, "quick_fingerprint")
            last = _read_state(probe, "last_deep_at")
            old_policy = _read_state(probe, "selection_policy")
            old_policy_version = _read_state(probe, "conflict_policy_version")
        finally:
            probe.close()
        due = last is None or dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last) >= dt.timedelta(hours=deep_hours)
        if (previous == quick_digest and old_policy == selection_policy and
                old_policy_version == f"{CONFLICT_POLICY_VERSION}:{selection_policy}" and not due):
            return {"status": "NO NEW SOURCE DATA", "duration_seconds": round(time.monotonic()-start, 3)}

    fd, temporary_name = tempfile.mkstemp(prefix=".health-rebuild-next-", suffix=".sqlite", dir=output_dir)
    os.close(fd)
    working = Path(temporary_name)
    try:
        if not rebuild and target.exists():
            old = sqlite3.connect("file:" + str(target) + "?mode=ro", uri=True)
            new = sqlite3.connect(working)
            try:
                old.backup(new)
            finally:
                old.close(); new.close()
        db = sqlite3.connect(working)
        db.row_factory = sqlite3.Row
        try:
            _init_db(db)
            if _read_state(db, "schema") not in (None, "2"):
                raise RuntimeError("unsupported reconciliation state")
            generation = str(uuid.uuid4())
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            counters: Counter = Counter()
            # The current analytics adapter fingerprints the latest ETL run_id.
            # Carry the policy version in that ID so a policy change is an
            # explicit analytics source-generation change without modifying
            # production analytics code or its formulas.
            run_id = f"{CONFLICT_POLICY_VERSION}:{selection_policy}:{uuid.uuid4()}"
            manifest: dict[str, dict[str, str]] = {}
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO etl_runs(run_id,started_at,status,source_root,overlap_hours) VALUES(?,?,?,?,?)",
                       (run_id, now, "RUNNING", str(source_root), 48.0))
            with tempfile.TemporaryDirectory(prefix=".mi-fitness-stage-", dir=output_dir) as stage:
                for index, (source_path, key) in enumerate(zip(candidates, keys)):
                    before = _group_full_manifest(source_path)
                    staged = stable_stage_database(source_path, Path(stage) / str(index))
                    after = _group_full_manifest(source_path)
                    if before != after:
                        raise SourceSnapshotBusyError("source changed during authoritative staging")
                    snapshot_sha = _sha256_file(staged)
                    manifest[key] = {"snapshot_sha256": snapshot_sha, "group": before}
                    source = sqlite3.connect("file:" + str(staged) + "?mode=ro", uri=True)
                    source.row_factory = sqlite3.Row
                    try:
                        _scan_database(db, source, key, source_path.relative_to(source_root).as_posix(),
                                       generation, now, snapshot_sha, counters)
                    finally:
                        source.close()
            # A source DB scanned early can change while later DBs are being
            # processed. The complete generation is authoritative only if all
            # source groups still match their pre-staging manifests.
            for source_path, key in zip(candidates, keys):
                if _group_full_manifest(source_path) != manifest[key]["group"]:
                    raise SourceSnapshotBusyError("source changed during authoritative scan")
            prior_sources = {r[0] for r in db.execute("SELECT source_db_id FROM source_database_identities")}
            current_sources = {_source_id(k) for k in keys}
            if prior_sources - current_sources:
                # A temporarily incomplete SynoSync tree must never erase a
                # whole DB's history. Require an explicit, separate policy.
                raise SourceSnapshotBusyError("previous source database absent; refusing mass deletion")
            _rebuild_canonical(db, generation, now, run_id, counters, selection_policy,
                               initial_build=rebuild or not target.exists())
            manifest_digest = hashlib.sha256(json_dumps(manifest).encode()).hexdigest()
            db.execute("""INSERT INTO source_generations
              (generation_id,scanned_at,authoritative_manifest_sha256,source_database_count,
               physical_row_count,conflict_policy_version) VALUES(?,?,?,?,?,?)""",
                       (generation, now, manifest_digest, len(candidates), counters["physical_seen"],
                        f"{CONFLICT_POLICY_VERSION}:{selection_policy}"))
            _set_state(db, "schema", "2")
            _set_state(db, "quick_fingerprint", quick_digest)
            _set_state(db, "selection_policy", selection_policy)
            _set_state(db, "conflict_policy_version", f"{CONFLICT_POLICY_VERSION}:{selection_policy}")
            _set_state(db, "last_deep_at", now)
            _set_state(db, "authoritative_manifest_sha256", manifest_digest)
            db.execute("""UPDATE etl_runs SET finished_at=?,status='SUCCESS',rows_new=?,rows_updated=?,
              warnings=?,duration_seconds=? WHERE run_id=?""",
              (dt.datetime.now(dt.timezone.utc).isoformat(), counters["canonical_insert"],
               counters["canonical_update"], counters["warnings"], time.monotonic()-start, run_id))
            db.commit()
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError("rebuild integrity_check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise sqlite3.DatabaseError("rebuild foreign_key_check failed")
        finally:
            db.close()
        os.replace(working, target)
        return {"status": "SUCCESS", "generation": generation,
                "duration_seconds": round(time.monotonic()-start, 3),
                "target": str(target), "counts": dict(counters)}
    finally:
        if working.exists():
            working.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disposable Mi Fitness authoritative reconciliation candidate")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="disposable working directory")
    parser.add_argument("--target-name", default=TARGET_NAME)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--rebuild-from-source", action="store_true")
    modes.add_argument("--full-reconcile", action="store_true")
    parser.add_argument("--deep-interval-hours", type=int, default=DEEP_INTERVAL_HOURS)
    parser.add_argument("--selection-policy", choices=("ru_compat", "cn_review", "unresolved_exclude"), default="ru_compat")
    args = parser.parse_args(argv)
    if args.deep_interval_hours < 0:
        parser.error("--deep-interval-hours must be nonnegative")
    try:
        result = reconcile(args.source, args.output, rebuild=args.rebuild_from_source,
                           full=args.full_reconcile, deep_hours=args.deep_interval_hours,
                           selection_policy=args.selection_policy,
                           target_name=args.target_name)
        print(json.dumps(result, sort_keys=True))
        return 0
    except SourceSnapshotBusyError as exc:
        print(json.dumps({"status": "SKIPPED", "reason": type(exc).__name__}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
