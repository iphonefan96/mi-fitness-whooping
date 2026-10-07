"""Schema-v3 lifecycle and selected feature persistence for the baseline runner.

Preserves the existing feature identity and active selection contract. Result
rows are written by the target result repository instead.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mi_fitness_whooping.baseline import IMPLEMENTATION_VERSION, NORMALIZATION_VERSION
from mi_fitness_whooping.baseline.foundations import FeatureRecord
from mi_fitness_whooping.baseline.models import Feature
from mi_fitness_whooping.baseline.normalization import canonical_hash


SCHEMA_VERSION = 3


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    return db


def migrate(db: sqlite3.Connection) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError("analytics database is newer than this package")
    if version == SCHEMA_VERSION:
        return
    if version == 0:
        with db:
            db.executescript("""
        CREATE TABLE analytics_runs (
          run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, source_fingerprint TEXT, source_generation TEXT,
          normalization_version TEXT NOT NULL, implementation_version TEXT NOT NULL,
          profile_revision TEXT, rows_normalized INTEGER NOT NULL DEFAULT 0,
          features_calculated INTEGER NOT NULL DEFAULT 0,
          features_skipped INTEGER NOT NULL DEFAULT 0,
          metrics_calculated INTEGER NOT NULL DEFAULT 0,
          metrics_skipped INTEGER NOT NULL DEFAULT 0, errors TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE analytics_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE profile_revisions (
          revision_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
          profile_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE source_generations (
          generation TEXT PRIMARY KEY, source_fingerprint TEXT NOT NULL,
          first_seen_at TEXT NOT NULL, source_schema_version TEXT
        );
        CREATE TABLE features (
          feature_id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL CHECK(kind IN ('nightly','daily')),
          metric_date TEXT NOT NULL,
          measurement_start TEXT, measurement_end TEXT,
          values_json TEXT NOT NULL, source_count INTEGER NOT NULL,
          source_ids_hash TEXT NOT NULL,
          quality_status TEXT NOT NULL, quality_flags_json TEXT NOT NULL,
          freshness_status TEXT NOT NULL,
          normalization_version TEXT NOT NULL, implementation_version TEXT NOT NULL,
          profile_revision TEXT NOT NULL, source_policy_version TEXT NOT NULL,
          input_fingerprint TEXT NOT NULL, calculated_at TEXT NOT NULL,
          UNIQUE(kind,metric_date,normalization_version,implementation_version,
                 profile_revision,source_policy_version,input_fingerprint)
        );
        CREATE INDEX features_date_idx ON features(kind,metric_date);
        CREATE TABLE active_features (
          kind TEXT NOT NULL, metric_date TEXT NOT NULL, feature_id INTEGER NOT NULL,
          PRIMARY KEY(kind,metric_date), FOREIGN KEY(feature_id) REFERENCES features(feature_id)
        );
        CREATE TABLE derived_metric_results (
          result_id INTEGER PRIMARY KEY, metric_date TEXT NOT NULL, metric_name TEXT NOT NULL,
          value REAL, unit TEXT, status TEXT NOT NULL, freshness_status TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT 'OUR_DERIVED',
          algorithm_id TEXT NOT NULL, algorithm_version TEXT NOT NULL,
          implementation_version TEXT NOT NULL, normalization_version TEXT NOT NULL,
          upstream_project TEXT, upstream_commit TEXT, source_scope TEXT NOT NULL,
          profile_revision TEXT NOT NULL, source_policy_version TEXT NOT NULL,
          quality_gate_version TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
          source_signals_json TEXT NOT NULL, input_coverage_json TEXT NOT NULL,
          confidence TEXT NOT NULL, quality_flags_json TEXT NOT NULL,
          measurement_start TEXT, measurement_end TEXT, source_updated_at TEXT,
          calculated_at TEXT NOT NULL, metadata_json TEXT NOT NULL, run_id TEXT NOT NULL,
          supersedes_result_id INTEGER,
          UNIQUE(metric_date,metric_name,algorithm_id,algorithm_version,
                 implementation_version,normalization_version,source_scope,
                 profile_revision,source_policy_version,input_fingerprint)
        );
        CREATE TABLE active_metric_selection (
          metric_name TEXT NOT NULL, metric_date TEXT NOT NULL,
          source_scope TEXT NOT NULL, release_channel TEXT NOT NULL,
          result_id INTEGER NOT NULL,
          PRIMARY KEY(metric_name,metric_date,source_scope,release_channel),
          FOREIGN KEY(result_id) REFERENCES derived_metric_results(result_id)
        );
        PRAGMA user_version=3;
        """)
    elif version == 1:
        with db:
            db.execute("ALTER TABLE analytics_runs ADD COLUMN features_skipped INTEGER NOT NULL DEFAULT 0")
            db.execute("PRAGMA user_version=2")
        version = 2
    if version == 2:
        with db:
            db.execute("ALTER TABLE derived_metric_results ADD COLUMN source_type TEXT NOT NULL DEFAULT 'OUR_DERIVED'")
            db.execute("PRAGMA user_version=3")


def get_state(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM analytics_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_state(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO analytics_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def put_feature(db: sqlite3.Connection, feature: Feature, *, profile_revision: str,
                source_policy_version: str = "primary-v1") -> bool:
    old = db.execute("""SELECT f.input_fingerprint,f.normalization_version,f.implementation_version,
                            f.profile_revision,f.source_policy_version
                            FROM active_features a JOIN features f ON f.feature_id=a.feature_id
                            WHERE a.kind=? AND a.metric_date=?""",
                     (feature.kind, feature.metric_date.isoformat())).fetchone()
    if old and tuple(old) == (feature.input_fingerprint, NORMALIZATION_VERSION,
                              IMPLEMENTATION_VERSION, profile_revision, source_policy_version):
        return False
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""INSERT OR IGNORE INTO features
       (kind,metric_date,measurement_start,measurement_end,values_json,source_count,source_ids_hash,
        quality_status,quality_flags_json,freshness_status,normalization_version,implementation_version,
        profile_revision,source_policy_version,input_fingerprint,calculated_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (feature.kind, feature.metric_date.isoformat(),
        feature.measurement_start.isoformat() if feature.measurement_start else None,
        feature.measurement_end.isoformat() if feature.measurement_end else None,
        json.dumps(feature.values, sort_keys=True, separators=(",", ":")), len(feature.source_ids),
        canonical_hash(feature.source_ids), feature.quality_status.value,
        json.dumps(sorted(f.value for f in feature.quality_flags)), feature.freshness_status.value,
        NORMALIZATION_VERSION, IMPLEMENTATION_VERSION, profile_revision, source_policy_version,
        feature.input_fingerprint, now))
    row = db.execute("""SELECT feature_id FROM features WHERE kind=? AND metric_date=? AND
       normalization_version=? AND implementation_version=? AND profile_revision=? AND
       source_policy_version=? AND input_fingerprint=?""",
       (feature.kind, feature.metric_date.isoformat(), NORMALIZATION_VERSION,
        IMPLEMENTATION_VERSION, profile_revision, source_policy_version, feature.input_fingerprint)).fetchone()
    db.execute("""INSERT INTO active_features(kind,metric_date,feature_id) VALUES(?,?,?)
       ON CONFLICT(kind,metric_date) DO UPDATE SET feature_id=excluded.feature_id""",
       (feature.kind, feature.metric_date.isoformat(), row[0]))
    return True


def delete_active_feature(db: sqlite3.Connection, kind: str, day: str) -> bool:
    cursor = db.execute("DELETE FROM active_features WHERE kind=? AND metric_date=?", (kind, day))
    return cursor.rowcount > 0


def active_feature_records(db: sqlite3.Connection) -> tuple[dict, dict]:
    nights, dailies = {}, {}
    for row in db.execute("""SELECT f.* FROM active_features a JOIN features f ON a.feature_id=f.feature_id"""):
        record = FeatureRecord(kind=row["kind"], day=__import__("datetime").date.fromisoformat(row["metric_date"]),
                               values=json.loads(row["values_json"]), fingerprint=row["input_fingerprint"],
                               source_count=row["source_count"], source_ids_hash=row["source_ids_hash"],
                               measurement_start=row["measurement_start"], measurement_end=row["measurement_end"],
                               quality_flags=tuple(json.loads(row["quality_flags_json"])))
        (nights if record.kind == "nightly" else dailies)[record.day] = record
    return nights, dailies
