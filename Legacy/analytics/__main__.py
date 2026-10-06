from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from analytics.adapters.xiaomi import XiaomiAdapter
from analytics.normalization.core import freshness, sleep_date
from analytics.runners.runner import run
from analytics.storage.db import connect, migrate


DEFAULT_SOURCE = Path("/Users/rus/Library/Application Support/MiFitnessETL/data/health.sqlite")
DEFAULT_DB = Path("/Users/rus/Documents/temp/mi_fitness_analytics/analytics.sqlite")


def sleep_headline(last_night: str | None, current_freshness: str, values: dict) -> dict:
    available = current_freshness == "FRESH"
    return {"last_night": last_night,
            "score": values.get("sleep.score", {}).get("value") if available else None,
            "need_min": values.get("sleep.need_min", {}).get("value") if available else None,
            "debt_min": values.get("sleep.debt_min", {}).get("value") if available else None,
            "freshness": current_freshness,
            "last_historical_statuses": {k: v["status"] for k, v in values.items()}}


def recovery_headline(last_date: str | None, current_freshness: str, value: float | None,
                      status: str | None, metadata: dict | None) -> dict:
    available = current_freshness == "FRESH" and value is not None
    return {"last_date": last_date, "score": value if available else None,
            "mode": metadata.get("mode") if available and metadata else None,
            "active_components": metadata.get("active_components") if available and metadata else [],
            "freshness": current_freshness,
            "last_historical_status": status}


def monitoring_headline(last_date: str | None, current_freshness: str,
                        flagged_today: list[str], latest_event_date: str | None,
                        available_signals: list[str]) -> dict:
    return {"last_physiological_date": last_date,
            "current_status": current_freshness,
            "active_anomalies": sorted(flagged_today) if current_freshness == "FRESH" else None,
            "latest_anomaly_date": latest_event_date,
            "signals_available": available_signals}


def main() -> int:
    parser = argparse.ArgumentParser(description="Local wearable analytics foundations, sleep, recovery and monitoring")
    parser.add_argument("command", choices=("init", "validate", "run", "status"))
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()
    if args.command == "init":
        db = connect(args.db)
        try:
            migrate(db)
        finally:
            db.close()
        print(json.dumps({"status": "INITIALIZED", "db": str(args.db)}))
        return 0
    if args.command == "run":
        try:
            result = run(args.source, args.db, args.profile)
        except Exception as exc:
            print(json.dumps({"status": "FAILED", "error": str(exc)}))
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "validate":
        if not args.source.is_file():
            print(json.dumps({"status": "SKIPPED", "reason": "SOURCE_UNAVAILABLE"}))
            return 0
        with XiaomiAdapter(args.source) as source:
            db = source._db()
            output = {"status": "READ_ONLY", "source_generation": source.generation(),
                      "sleep_sessions": db.execute("SELECT COUNT(*) FROM sleep_sessions").fetchone()[0],
                      "main_sleep_sessions": db.execute("SELECT COUNT(*) FROM sleep_sessions WHERE is_nap_inferred=0").fetchone()[0],
                      "sleep_min_end": db.execute("SELECT MIN(sleep_end_utc) FROM sleep_sessions").fetchone()[0],
                      "sleep_max_end": db.execute("SELECT MAX(sleep_end_utc) FROM sleep_sessions").fetchone()[0],
                      "hr_samples": db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0],
                      "spo2_samples": db.execute("SELECT COUNT(*) FROM spo2").fetchone()[0],
                      "hrv_capability": False, "rr_capability": False}
            last_sleep = db.execute("SELECT sleep_end_utc,utc_offset_seconds FROM sleep_sessions ORDER BY sleep_end_utc DESC LIMIT 1").fetchone()
            max_end = output["sleep_max_end"]
            output["last_night_freshness"] = freshness(
                sleep_date(datetime.fromtimestamp(last_sleep[0], timezone.utc), offset_seconds=last_sleep[1]) if last_sleep else None,
                datetime.now().astimezone().date(), as_of=datetime.now(timezone.utc),
                last_end=datetime.fromtimestamp(max_end, timezone.utc) if max_end else None).value
            source.assert_unchanged()
        print(json.dumps(output, sort_keys=True))
        return 0
    if not args.db.is_file():
        print(json.dumps({"status": "NOT_INITIALIZED"}))
        return 0
    db = connect(args.db)
    try:
        migrate(db)
        latest = db.execute("SELECT status,finished_at,features_calculated,metrics_calculated FROM analytics_runs ORDER BY started_at DESC LIMIT 1").fetchone()
        counts = {r[0]: r[1] for r in db.execute("SELECT kind,COUNT(*) FROM active_features GROUP BY kind")}
        metric_counts = {r[0]: r[1] for r in db.execute("""SELECT r.status,COUNT(*) FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id GROUP BY r.status""")}
        freshness_counts = {r[0]: r[1] for r in db.execute("""SELECT r.freshness_status,COUNT(*) FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id GROUP BY r.freshness_status""")}
        last_dates = {r[0]: r[1] for r in db.execute("SELECT kind,MAX(metric_date) FROM active_features GROUP BY kind")}
        latest_night = db.execute("""SELECT f.metric_date,f.measurement_end FROM active_features a
            JOIN features f ON f.feature_id=a.feature_id WHERE a.kind='nightly'
            ORDER BY f.metric_date DESC LIMIT 1""").fetchone()
        current_day = datetime.now().astimezone().date()
        current_sleep = freshness(
            __import__("datetime").date.fromisoformat(latest_night[0]) if latest_night else None,
            current_day, as_of=datetime.now(timezone.utc),
            last_end=datetime.fromisoformat(latest_night[1]) if latest_night else None).value
        last_sleep_values = {r[0]: {"value": r[1], "status": r[2]} for r in db.execute("""SELECT r.metric_name,r.value,r.status
            FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE a.metric_date=? AND r.metric_name IN ('sleep.score','sleep.need_min','sleep.debt_min')""",
            (latest_night[0] if latest_night else "",))}
        sleep_display = sleep_headline(latest_night[0] if latest_night else None,
                                       current_sleep, last_sleep_values)
        recovery_row = db.execute("""SELECT r.metric_date,r.value,r.status,r.metadata_json
            FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE r.metric_name='recovery.score' ORDER BY r.metric_date DESC LIMIT 1""").fetchone()
        recovery_display = recovery_headline(
            recovery_row[0] if recovery_row else None, current_sleep,
            recovery_row[1] if recovery_row else None,
            recovery_row[2] if recovery_row else None,
            json.loads(recovery_row[3]) if recovery_row else None)
        flagged_today = [r[0] for r in db.execute("""SELECT r.metric_name FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE r.metric_date=? AND r.value=1 AND
              (r.metric_name LIKE 'anomaly.%' OR r.metric_name='health_signal.physiological_watch')""",
            (latest_night[0] if latest_night else "",))]
        latest_event = db.execute("""SELECT MAX(r.metric_date) FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE r.value=1 AND
              (r.metric_name LIKE 'anomaly.%' OR r.metric_name='health_signal.physiological_watch')""").fetchone()[0]
        available = [signal for signal, field in (("rhr", "rhr_bpm"), ("spo2", "spo2_mean_pct"),
                                                    ("respiratory", "respiratory_rate_bpm"))
                     if db.execute("""SELECT 1 FROM active_features a JOIN features f ON f.feature_id=a.feature_id
                         WHERE a.kind='nightly' AND json_extract(f.values_json,?) IS NOT NULL LIMIT 1""",
                         ("$." + field,)).fetchone()]
        monitoring_display = monitoring_headline(latest_night[0] if latest_night else None,
                                                 current_sleep, flagged_today, latest_event, available)
        source_max = db.execute("SELECT value FROM analytics_state WHERE key='source_max_timestamp'").fetchone()
        invalid = db.execute("""SELECT COUNT(*) FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE r.value IS NOT NULL AND (
              (r.metric_name LIKE 'sleep.%_pct' AND (r.value<0 OR r.value>100.1)) OR
              (r.metric_name='rhr.nightly' AND (r.value<25 OR r.value>240)) OR
              (r.metric_name IN ('spo2.nightly_mean','spo2.nightly_min','spo2.nightly_p10')
                   AND (r.value<=0 OR r.value>100)) OR
              (r.metric_name='respiratory.nightly_mean' AND (r.value<4 OR r.value>60))
            )""").fetchone()[0]
        print(json.dumps({"status": "READY", "active_features": counts,
                          "last_source_date_utc": datetime.fromtimestamp(int(source_max[0]), timezone.utc).date().isoformat() if source_max else None,
                          "last_analytics_dates": last_dates,
                          "current_sleep_freshness": current_sleep,
                          "sleep": sleep_display,
                          "recovery": recovery_display,
                          "health_monitoring": monitoring_display,
                          "current_sleep_headline_available": current_sleep == "FRESH",
                          "active_metric_status_counts": metric_counts,
                          "active_metric_freshness_counts": freshness_counts,
                          "calibrating_metrics": metric_counts.get("CALIBRATING", 0),
                          "stale_current_sleep_metrics": (db.execute("""SELECT COUNT(*) FROM active_metric_selection
                              WHERE metric_date=? AND metric_name LIKE 'sleep.%'""",
                              (latest_night[0],)).fetchone()[0] if latest_night and current_sleep == "STALE" else 0),
                          "sanity_warnings": invalid,
                          "active_derived_metrics": db.execute("SELECT COUNT(*) FROM active_metric_selection").fetchone()[0],
                          "stored_metric_revisions": db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0],
                          "last_run": dict(latest) if latest else None}, sort_keys=True))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
