"""Schema-v3-compatible result writer and selected-night reader.

The target package does not create/migrate a schema or read source data here.
`calculated_at` is an operational timestamp; freshness and identity are supplied
or calculated independently of this clock.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping

from mi_fitness_whooping.storage.contracts import (
    ActiveResult, AnalyticsSession, PersistableMetricResult, ResultIdentity, ResultWriteContext,
    SelectedSleepFeature, StoredFeatureRef, WriteOutcome,
)
from mi_fitness_whooping.storage.fingerprint import canonical_hash, result_fingerprint


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_ready(value: object) -> object:
    """Convert Phase-A immutable metadata back to Legacy's JSON-shaped values."""
    if isinstance(value, Mapping):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def _fetch_dict(cursor: sqlite3.Cursor) -> dict[str, object] | None:
    raw = cursor.fetchone()
    if raw is None:
        return None
    return dict(zip((column[0] for column in cursor.description), raw))


def _active_from_row(row: Mapping[str, object]) -> ActiveResult:
    identity = ResultIdentity(
        metric_name=row["metric_name"], day=date.fromisoformat(row["metric_date"]),
        algorithm_id=row["algorithm_id"], algorithm_version=row["algorithm_version"],
        implementation_version=row["implementation_version"],
        normalization_version=row["normalization_version"],
        source_scope=row["source_scope"], profile_revision=row["profile_revision"],
        source_policy_version=row["source_policy_version"],
        input_fingerprint=row["input_fingerprint"],
    )
    return ActiveResult(row["result_id"], identity, row["freshness_status"],
                        row["supersedes_result_id"])


class SqliteAnalyticsSession:
    """A single explicit transaction; the caller commits or rolls it back."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._active = True

    def require_active(self) -> sqlite3.Connection:
        if not self._active or not self.connection.in_transaction:
            raise RuntimeError("analytics session is not active")
        return self.connection

    def commit(self) -> None:
        self.require_active().commit()
        self._active = False

    def rollback(self) -> None:
        self.require_active().rollback()
        self._active = False


class SqliteAnalyticsSessionFactory:
    """Begin an outer-owned transaction on an existing schema-v3 connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != 3:
            raise RuntimeError("analytics schema v3 is required")

    def begin(self) -> SqliteAnalyticsSession:
        if self.connection.in_transaction:
            raise RuntimeError("nested analytics transaction is not supported")
        self.connection.execute("BEGIN IMMEDIATE")
        return SqliteAnalyticsSession(self.connection)


def _connection(session: AnalyticsSession) -> sqlite3.Connection:
    if not isinstance(session, SqliteAnalyticsSession):
        raise TypeError("SQLite repository requires a SQLite analytics session")
    return session.require_active()


class SqliteActiveNightReader:
    """Project active schema-v3 nightly rows without selecting feature revisions."""

    def selected_nights(
        self, session: AnalyticsSession, day: date,
    ) -> dict[date, SelectedSleepFeature]:
        db = _connection(session)
        lower = (day - timedelta(days=14)).isoformat()
        cursor = db.execute("""SELECT a.metric_date AS selected_date,
            f.kind, f.metric_date, f.values_json, f.input_fingerprint,
            f.source_count, f.source_ids_hash, f.measurement_start,
            f.measurement_end, f.quality_flags_json
            FROM active_features a JOIN features f ON f.feature_id=a.feature_id
            WHERE a.kind='nightly' AND a.metric_date BETWEEN ? AND ?
            ORDER BY a.metric_date""", (lower, day.isoformat()))
        columns = tuple(column[0] for column in cursor.description)
        selected = {}
        for raw in cursor:
            row = dict(zip(columns, raw, strict=True))
            if row["kind"] != "nightly" or row["metric_date"] != row["selected_date"]:
                raise ValueError("active nightly selection does not match its feature row")
            values = json.loads(row["values_json"])
            flags = tuple(json.loads(row["quality_flags_json"]))
            feature_day = date.fromisoformat(row["metric_date"])
            reference = StoredFeatureRef(
                kind="nightly", day=feature_day, fingerprint=row["input_fingerprint"],
                source_count=row["source_count"], source_ids_hash=row["source_ids_hash"],
                measurement_start=row["measurement_start"],
                measurement_end=row["measurement_end"], quality_flags=flags,
            )
            selected[feature_day] = SelectedSleepFeature(
                reference=reference, tst_min=values.get("tst_min"),
                deep_min=values.get("deep_min"), rem_min=values.get("rem_min"),
                waso_min=values.get("waso_min"),
                awakening_durations_min=values.get("awakening_durations_min"),
                bedtime_local_min=values.get("bedtime_local_min"),
                stage_coverage=values.get("stage_coverage"),
            )
        return selected


class SqliteMetricResultRepository:
    """Result rows and selection only; never commits a caller's session."""

    def __init__(self, calculated_at: Callable[[], str] = _utc_now) -> None:
        self.calculated_at = calculated_at

    def get_active(
        self, session: AnalyticsSession, metric_name: str, day: date,
        source_scope: str = "primary", release_channel: str = "production",
    ) -> ActiveResult | None:
        db = _connection(session)
        row = _fetch_dict(db.execute("""SELECT r.* FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE a.metric_name=? AND a.metric_date=? AND a.source_scope=?
              AND a.release_channel=?""",
            (metric_name, day.isoformat(), source_scope, release_channel)))
        return _active_from_row(row) if row is not None else None

    def persist(
        self, session: AnalyticsSession, result: PersistableMetricResult,
        context: ResultWriteContext,
    ) -> WriteOutcome:
        db = _connection(session)
        current = self.get_active(session, result.metric_name, result.day,
                                  context.source_scope, context.release_channel)
        digest = result_fingerprint(result, context)
        if current and current.identity.input_fingerprint == digest and \
                current.stored_freshness == context.stored_freshness:
            return WriteOutcome(False, False, False, current)

        metadata = _json_ready(result.metadata)
        signals = {
            "lineage_digest": canonical_hash([(feature.kind, feature.day.isoformat(),
                                               feature.source_ids_hash)
                                              for feature in result.inputs]),
            "feature_kinds": sorted({feature.kind for feature in result.inputs}),
            "date_start": min((feature.day.isoformat() for feature in result.inputs), default=None),
            "date_end": max((feature.day.isoformat() for feature in result.inputs), default=None),
            "feature_count": len(result.inputs),
        }
        coverage = {
            "feature_count": len(result.inputs),
            "source_signal_reads": sum(feature.source_count for feature in result.inputs),
            "history_count": metadata.get("history_count"),
            "required_history_count": metadata.get("required_history_count"),
        }
        flags = sorted({flag for feature in result.inputs for flag in feature.quality_flags})
        first_start = min((feature.measurement_start for feature in result.inputs
                           if feature.measurement_start), default=None)
        last_end = max((feature.measurement_end for feature in result.inputs
                        if feature.measurement_end), default=None)
        cursor = db.execute("""INSERT OR IGNORE INTO derived_metric_results
            (metric_date,metric_name,value,unit,status,freshness_status,source_type,
             algorithm_id,algorithm_version,implementation_version,normalization_version,
             upstream_project,upstream_commit,source_scope,profile_revision,source_policy_version,
             quality_gate_version,input_fingerprint,source_signals_json,input_coverage_json,
             confidence,quality_flags_json,measurement_start,measurement_end,source_updated_at,
             calculated_at,metadata_json,run_id,supersedes_result_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (result.day.isoformat(), result.metric_name, result.value, result.unit, result.status,
             context.stored_freshness, result.source_type, result.algorithm_id,
             result.algorithm_version, context.implementation_version,
             context.normalization_version, result.upstream_project, result.upstream_commit,
             context.source_scope, context.profile_revision, context.source_policy_version,
             context.quality_gate_version, digest, json.dumps(signals, sort_keys=True),
             json.dumps(coverage, sort_keys=True), result.confidence, json.dumps(flags),
             first_start, last_end, None, self.calculated_at(),
             json.dumps(metadata, sort_keys=True), context.run_id,
             current.result_id if current else None))
        inserted = cursor.rowcount == 1
        row = _fetch_dict(db.execute("""SELECT result_id FROM derived_metric_results
            WHERE metric_date=? AND metric_name=? AND algorithm_id=? AND algorithm_version=?
              AND implementation_version=? AND normalization_version=? AND source_scope=?
              AND profile_revision=? AND source_policy_version=? AND input_fingerprint=?""",
            (result.day.isoformat(), result.metric_name, result.algorithm_id,
             result.algorithm_version, context.implementation_version,
             context.normalization_version, context.source_scope, context.profile_revision,
             context.source_policy_version, digest)))
        if row is None:
            raise RuntimeError("inserted metric result could not be selected")
        result_id = row["result_id"]
        db.execute("""INSERT INTO active_metric_selection
            (metric_name,metric_date,source_scope,release_channel,result_id)
            VALUES (?,?,?,?,?)
            ON CONFLICT(metric_name,metric_date,source_scope,release_channel)
            DO UPDATE SET result_id=excluded.result_id""",
            (result.metric_name, result.day.isoformat(), context.source_scope,
             context.release_channel, result_id))
        selected = self.get_active(session, result.metric_name, result.day,
                                   context.source_scope, context.release_channel)
        if selected is None:
            raise RuntimeError("active metric selection was not written")
        return WriteOutcome(True, inserted,
                            current is None or current.result_id != selected.result_id,
                            selected)

    def clear_active(
        self, session: AnalyticsSession, day: date,
        metric_names: tuple[str, ...], release_channel: str = "production",
    ) -> int:
        db = _connection(session)
        if not metric_names:
            return 0
        # Legacy incremental cleanup removes matching names across scopes.
        placeholders = ",".join("?" for _ in metric_names)
        cursor = db.execute(
            "DELETE FROM active_metric_selection WHERE metric_date=? "
            f"AND metric_name IN ({placeholders}) AND release_channel=?",
            (day.isoformat(), *metric_names, release_channel),
        )
        return cursor.rowcount
