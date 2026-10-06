from __future__ import annotations

import fcntl
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from analytics import IMPLEMENTATION_VERSION, NORMALIZATION_VERSION
from analytics.adapters.xiaomi import XiaomiAdapter
from analytics.algorithms.foundations import FOUNDATION_ALGORITHM_VERSION, calculate_day
from analytics.algorithms.sleep import SLEEP_ALGORITHM_VERSION, calculate_sleep_day
from analytics.algorithms.recovery import RECOVERY_ALGORITHM_VERSION, calculate_recovery_day
from analytics.algorithms.monitoring import (MONITORING_ALGORITHM_VERSION,
                                             calculate_cusum_series, calculate_monitoring_day)
from analytics.features.foundations import build_daily, build_nightly
from analytics.normalization.core import canonical_hash, sleep_date, utc_from_epoch
from analytics.profile.config import load_profile
from analytics.storage.db import (active_feature_records, connect, delete_active_feature,
                                  get_state, migrate, put_feature, put_result, set_state)


SOURCE_POLICY_VERSION = "primary-v1"


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("ANALYTICS_ALREADY_RUNNING") from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _source_file_digest(source: XiaomiAdapter) -> str:
    return canonical_hash(source.file_fingerprint())


def _all_dates(source: XiaomiAdapter) -> set[date]:
    db = source._db()
    dates = {date.fromisoformat(r[0]) for r in db.execute("SELECT local_date FROM daily_summary")}
    for r in db.execute("SELECT sleep_end_utc,utc_offset_seconds FROM sleep_sessions"):
        dates.add(sleep_date(utc_from_epoch(r[0]), offset_seconds=r[1]))
    return dates


def _changed_dates(source: XiaomiAdapter, imported_after: str | None, last_max_ts: int | None) -> set[date]:
    if imported_after is None:
        return _all_dates(source)
    db = source._db()
    result: set[date] = set()
    for table in ("heart_rate", "spo2", "stress"):
        sql = f"SELECT DISTINCT local_date FROM {table} WHERE imported_at>? AND local_date IS NOT NULL"
        result.update(date.fromisoformat(r[0]) for r in db.execute(sql, (imported_after,)))
    result.update(date.fromisoformat(r[0]) for r in db.execute(
        "SELECT local_date FROM daily_summary WHERE updated_at>?", (imported_after,)))
    for r in db.execute("SELECT sleep_end_utc,utc_offset_seconds FROM sleep_sessions WHERE imported_at>?", (imported_after,)):
        result.add(sleep_date(utc_from_epoch(r[0]), offset_seconds=r[1]))
    if last_max_ts is not None:
        # 48h overlap by source measurement timestamp, not wall-clock now.
        lo = last_max_ts - 48 * 3600
        for table in ("heart_rate", "spo2", "stress"):
            sql = f"SELECT DISTINCT local_date FROM {table} WHERE timestamp_utc>=? AND local_date IS NOT NULL"
            result.update(date.fromisoformat(r[0]) for r in db.execute(sql, (lo,)))
        for r in db.execute("SELECT sleep_end_utc,utc_offset_seconds FROM sleep_sessions WHERE sleep_end_utc>=?", (lo,)):
            result.add(sleep_date(utc_from_epoch(r[0]), offset_seconds=r[1]))
    # Sleep end/date changes may alter neighboring date assignments. Include
    # adjacent date so a now-absent old main session is removed.
    return {d + timedelta(days=offset) for d in result for offset in (-1, 0, 1)}


def _source_checkpoint(source: XiaomiAdapter) -> tuple[str | None, int | None]:
    db = source._db()
    values = []
    for table, field in (("heart_rate", "imported_at"), ("spo2", "imported_at"),
                         ("stress", "imported_at"), ("sleep_sessions", "imported_at"),
                         ("daily_summary", "updated_at")):
        values.append(db.execute(f"SELECT MAX({field}) FROM {table}").fetchone()[0])
    last_import = max((v for v in values if v is not None), default=None)
    max_ts = db.execute("SELECT MAX(max_source_timestamp) FROM source_databases").fetchone()[0]
    return last_import, max_ts


def _run_record(db: sqlite3.Connection, run_id: str, status: str, source_fp: str,
                generation: str, profile_revision: str, started: str, *,
                features: int = 0, skipped: int = 0, errors: list[str] | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute("""INSERT INTO analytics_runs
      (run_id,started_at,finished_at,status,source_fingerprint,source_generation,
       normalization_version,implementation_version,profile_revision,rows_normalized,
       features_calculated,features_skipped,metrics_calculated,metrics_skipped,errors)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
       (run_id, started, now if status != "RUNNING" else None, status, source_fp, generation,
        NORMALIZATION_VERSION, IMPLEMENTATION_VERSION, profile_revision, 0,
        features, skipped, 0, 0, json.dumps(errors or [])))


def run(source_path: str | Path, analytics_path: str | Path, profile_path: str | Path | None = None) -> dict:
    source_path, analytics_path = Path(source_path), Path(analytics_path)
    if not source_path.is_file():
        return {"status": "SKIPPED", "reason": "SOURCE_UNAVAILABLE", "features_calculated": 0}
    profile, profile_revision = load_profile(profile_path)
    with exclusive_lock(Path(str(analytics_path) + ".lock")):
        with XiaomiAdapter(source_path) as source:
            generation = source.generation()
            file_fp = _source_file_digest(source)
            db = connect(analytics_path)
            try:
                migrate(db)
                old_fp = get_state(db, "source_file_fingerprint")
                old_generation = get_state(db, "source_generation")
                old_profile = get_state(db, "profile_revision")
                old_norm = get_state(db, "normalization_version")
                old_impl = get_state(db, "implementation_version")
                old_foundation = get_state(db, "foundation_algorithm_version")
                old_sleep = get_state(db, "sleep_algorithm_version")
                old_recovery = get_state(db, "recovery_algorithm_version")
                old_monitoring = get_state(db, "monitoring_algorithm_version")
                force_full = old_profile != profile_revision or old_norm != NORMALIZATION_VERSION or old_impl != IMPLEMENTATION_VERSION
                source_changed = old_fp != file_fp or old_generation != generation
                metric_force_full = (old_foundation != FOUNDATION_ALGORITHM_VERSION or
                                     old_sleep != SLEEP_ALGORITHM_VERSION or
                                     old_recovery != RECOVERY_ALGORITHM_VERSION or
                                     old_monitoring != MONITORING_ALGORITHM_VERSION or force_full)
                if not force_full and not source_changed and not metric_force_full:
                    source.assert_unchanged()
                    return {"status": "NO NEW ANALYTICS INPUT", "features_calculated": 0, "metrics_calculated": 0}

                run_id = str(uuid.uuid4())
                started = datetime.now(timezone.utc).isoformat()
                with db:
                    _run_record(db, run_id, "RUNNING", file_fp, generation, profile_revision, started)
                old_import = None if force_full else get_state(db, "source_import_checkpoint")
                old_max_raw = None if force_full else get_state(db, "source_max_timestamp")
                dirty = (_all_dates(source) if force_full else
                         (_changed_dates(source, old_import, int(old_max_raw) if old_max_raw else None)
                          if source_changed else set()))
                calculated = 0
                skipped = 0
                rows_normalized = 0
                changed_feature_dates: set[date] = set()
                try:
                    db.execute("BEGIN IMMEDIATE")
                    for day in sorted(dirty):
                        night = build_nightly(source, day, normalization_version=NORMALIZATION_VERSION,
                                              profile_revision=profile_revision, source_policy_version=SOURCE_POLICY_VERSION)
                        daily = build_daily(source, day, normalization_version=NORMALIZATION_VERSION,
                                            profile_revision=profile_revision, source_policy_version=SOURCE_POLICY_VERSION)
                        for kind, feature in (("nightly", night), ("daily", daily)):
                            if feature is None:
                                if delete_active_feature(db, kind, day.isoformat()):
                                    calculated += 1
                                    changed_feature_dates.add(day)
                            elif put_feature(db, feature, profile_revision=profile_revision,
                                             source_policy_version=SOURCE_POLICY_VERSION):
                                calculated += 1
                                rows_normalized += len(feature.source_ids)
                                changed_feature_dates.add(day)
                            else:
                                skipped += 1
                    source.assert_unchanged()
                    nights, dailies = active_feature_records(db)
                    cusum_by_day = calculate_cusum_series(nights)
                    available_dates = set(nights) | set(dailies)
                    if metric_force_full:
                        metric_dates = available_dates
                    else:
                        metric_dates = {d for d in available_dates | changed_feature_dates
                                        if any(changed <= d <= changed + timedelta(days=90)
                                               for changed in changed_feature_dates)}
                        if changed_feature_dates and cusum_by_day:
                            # CUSUM may retain state beyond a 90-day baseline window.
                            # Continue only until its deterministic state rejoins the
                            # previously active trajectory after the changed window.
                            boundary = max(changed_feature_dates) + timedelta(days=90)
                            old_tokens = {date.fromisoformat(r[0]): json.loads(r[1]).get("state_token")
                                          for r in db.execute("""SELECT r.metric_date,r.metadata_json
                                              FROM active_metric_selection a JOIN derived_metric_results r
                                              ON r.result_id=a.result_id WHERE r.metric_name='anomaly.rhr_cusum'""")}
                            for future in sorted(d for d in cusum_by_day if d > boundary):
                                new_token = cusum_by_day[future].metadata["state_token"]
                                if old_tokens.get(future) == new_token:
                                    break
                                metric_dates.add(future)
                    metrics_calculated = 0
                    metrics_skipped = 0
                    today = datetime.now().astimezone().date()
                    for day in sorted(metric_dates):
                        foundation_drafts = calculate_day(day, nights, dailies)
                        drafts = (foundation_drafts + calculate_sleep_day(day, nights, profile) +
                                  calculate_recovery_day(day, nights, profile) +
                                  calculate_monitoring_day(day, nights, foundation_drafts))
                        if day in cusum_by_day:
                            drafts.append(cusum_by_day[day])
                        produced_names = {draft.name for draft in drafts}
                        for draft in drafts:
                            fresh = "HISTORICAL" if day < today else ("FRESH" if day == today else "STALE")
                            if put_result(db, draft, run_id=run_id, profile_revision=profile_revision,
                                          freshness_status=fresh, source_policy_version=SOURCE_POLICY_VERSION):
                                metrics_calculated += 1
                            else:
                                metrics_skipped += 1
                        if not metric_force_full:
                            old_names = {r[0] for r in db.execute(
                                "SELECT metric_name FROM active_metric_selection WHERE metric_date=? AND release_channel='production'",
                                (day.isoformat(),))}
                            for obsolete in old_names - produced_names:
                                db.execute("DELETE FROM active_metric_selection WHERE metric_date=? AND metric_name=? AND release_channel='production'",
                                           (day.isoformat(), obsolete))
                    latest_import, max_ts = _source_checkpoint(source)
                    set_state(db, "source_file_fingerprint", file_fp)
                    set_state(db, "source_generation", generation)
                    set_state(db, "profile_revision", profile_revision)
                    set_state(db, "normalization_version", NORMALIZATION_VERSION)
                    set_state(db, "implementation_version", IMPLEMENTATION_VERSION)
                    set_state(db, "foundation_algorithm_version", FOUNDATION_ALGORITHM_VERSION)
                    set_state(db, "sleep_algorithm_version", SLEEP_ALGORITHM_VERSION)
                    set_state(db, "recovery_algorithm_version", RECOVERY_ALGORITHM_VERSION)
                    set_state(db, "monitoring_algorithm_version", MONITORING_ALGORITHM_VERSION)
                    if latest_import is not None:
                        set_state(db, "source_import_checkpoint", latest_import)
                    if max_ts is not None:
                        set_state(db, "source_max_timestamp", str(max_ts))
                    db.execute("INSERT OR IGNORE INTO profile_revisions VALUES (?,?,?,?)",
                               (profile_revision, profile["schema_version"], profile_revision,
                                datetime.now(timezone.utc).isoformat()))
                    db.execute("INSERT OR IGNORE INTO source_generations VALUES (?,?,?,?)",
                               (generation, file_fp, datetime.now(timezone.utc).isoformat(), None))
                    db.execute("""UPDATE analytics_runs SET status='SUCCESS',finished_at=?,rows_normalized=?,
                                features_calculated=?,features_skipped=?,metrics_calculated=?,metrics_skipped=?
                                WHERE run_id=?""",
                               (datetime.now(timezone.utc).isoformat(), rows_normalized, calculated, skipped,
                                metrics_calculated, metrics_skipped, run_id))
                    db.commit()
                    return {"status": "SUCCESS", "features_calculated": calculated,
                            "features_unchanged": skipped, "metrics_calculated": metrics_calculated,
                            "metrics_unchanged": metrics_skipped, "dirty_dates": len(dirty),
                            "metric_dates": len(metric_dates), "source_generation": generation}
                except Exception as exc:
                    db.rollback()
                    with db:
                        db.execute("UPDATE analytics_runs SET status='FAILED',finished_at=?,errors=? WHERE run_id=?",
                                   (datetime.now(timezone.utc).isoformat(), json.dumps([type(exc).__name__]), run_id))
                    raise
            finally:
                db.close()
