"""Small local path from target baseline analytics to dated answers.

The target runner owns calculation and persistence. This module reads its
selected schema-v3 outputs; presentation does not calculate metrics.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path


def _open_results(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise ValueError("analytics schema v3 is required")
        db.execute("BEGIN")  # One stable read snapshot for the whole response.
    except BaseException:
        db.close()
        raise
    return db


def _metric_group(name: str) -> str:
    if name.startswith("sleep."):
        return "sleep"
    if name.startswith("recovery."):
        return "recovery"
    if name.startswith(("rhr.", "spo2.", "respiratory.")):
        return "vitals"
    return "other_metrics"


def _selected_daily(db: sqlite3.Connection, day: date) -> dict | None:
    row = db.execute("""SELECT a.kind AS selected_kind, a.metric_date AS selected_date,
        f.kind, f.metric_date, f.values_json, f.input_fingerprint, f.source_count,
        f.source_ids_hash, f.quality_status, f.quality_flags_json, f.freshness_status
        FROM active_features a JOIN features f ON f.feature_id=a.feature_id
        WHERE a.kind='daily' AND a.metric_date=?""", (day.isoformat(),)).fetchone()
    if row is None:
        return None
    if row["kind"] != row["selected_kind"] or row["metric_date"] != row["selected_date"]:
        raise ValueError("active daily selection does not match its feature row")
    values = json.loads(row["values_json"])
    return {
        "activity": {key: values.get(key) for key in (
            "steps", "step_energy_kcal", "total_energy_kcal", "activity_duration_min",
            "standing_count", "distance_m")},
        "stress": {key: values.get(key) for key in (
            "vendor_stress_median", "vendor_stress_p10", "vendor_stress_p90",
            "vendor_stress_n")},
        "provenance": {
            "kind": "selected_daily_feature", "input_fingerprint": row["input_fingerprint"],
            "source_count": row["source_count"], "source_ids_hash": row["source_ids_hash"],
            "quality_status": row["quality_status"],
            "quality_flags": json.loads(row["quality_flags_json"]),
            "stored_freshness": row["freshness_status"],
        },
    }


def _day_report(db: sqlite3.Connection, day: date) -> dict:
    groups: dict[str, dict] = {name: {} for name in
                               ("sleep", "recovery", "vitals", "other_metrics")}
    rows = db.execute("""SELECT a.metric_name AS selected_name,
        a.metric_date AS selected_date, r.*
        FROM active_metric_selection a
        JOIN derived_metric_results r ON r.result_id=a.result_id
        WHERE a.metric_date=? AND a.source_scope='primary'
          AND a.release_channel='production'
        ORDER BY a.metric_name""", (day.isoformat(),))
    for row in rows:
        name = row["selected_name"]
        if row["metric_name"] != name or row["metric_date"] != row["selected_date"]:
            raise ValueError("active metric selection does not match its result row")
        groups[_metric_group(name)][name] = {
            "value": row["value"], "unit": row["unit"], "status": row["status"],
            "stored_freshness": row["freshness_status"], "source_type": row["source_type"],
            "confidence": row["confidence"], "algorithm_id": row["algorithm_id"],
            "algorithm_version": row["algorithm_version"],
            "upstream_project": row["upstream_project"],
            "upstream_commit": row["upstream_commit"],
            "profile_revision": row["profile_revision"],
            "source_policy_version": row["source_policy_version"],
            "input_fingerprint": row["input_fingerprint"],
            "quality_flags": json.loads(row["quality_flags_json"]),
            "measurement_start": row["measurement_start"],
            "measurement_end": row["measurement_end"],
            "source_signals": json.loads(row["source_signals_json"]),
            "input_coverage": json.loads(row["input_coverage_json"]),
            "metadata": json.loads(row["metadata_json"]),
        }
    daily = _selected_daily(db, day)
    return {
        "date": day.isoformat(),
        "status": "READY" if daily is not None or any(groups.values()) else "MISSING",
        **groups,
        "activity": ({"values": daily["activity"], "provenance": daily["provenance"]}
                     if daily is not None else None),
        "stress": ({"values": daily["stress"], "provenance": daily["provenance"]}
                   if daily is not None else None),
    }


def day_report(analytics_path: str | Path, day: date) -> dict:
    """Read one selected date without creating or migrating an analytics DB."""
    with closing(_open_results(analytics_path)) as db:
        return _day_report(db, day)


def history_report(analytics_path: str | Path, start: date, end: date) -> dict:
    """Return every calendar date in an inclusive range, including gaps."""
    if start > end:
        raise ValueError("start date must be on or before end date")
    with closing(_open_results(analytics_path)) as db:
        days = []
        day = start
        while True:
            days.append(_day_report(db, day))
            if day == end:
                break
            day += timedelta(days=1)
    return {"from": start.isoformat(), "to": end.isoformat(), "days": days}


def run_and_read(source_path: str | Path, analytics_path: str | Path,
                 day: date | None = None, profile_path: str | Path | None = None) -> dict:
    """Run target baseline analytics, then read its selected result."""
    source, destination = Path(source_path), Path(analytics_path)
    if source.resolve() == destination.resolve() or (
        source.is_file() and destination.is_file() and source.samefile(destination)
    ):
        raise ValueError("source and analytics database must be separate files")
    from mi_fitness_whooping.baseline.runner import run

    outcome = run(source, destination, profile_path)
    if outcome["status"] not in {"SUCCESS", "NO NEW ANALYTICS INPUT"}:
        return {"run": outcome, "day": None}
    with closing(_open_results(analytics_path)) as db:
        if day is None:
            # A newer activity-only date must not hide the last selected sleep night.
            row = db.execute("""SELECT MAX(metric_date) FROM active_features
                WHERE kind='nightly'""").fetchone()
            if row[0] is None:
                row = db.execute("""SELECT MAX(metric_date) FROM (
                    SELECT metric_date FROM active_metric_selection
                    WHERE source_scope='primary' AND release_channel='production'
                    UNION ALL SELECT metric_date FROM active_features)""").fetchone()
            day = date.fromisoformat(row[0]) if row[0] is not None else None
        return {"run": outcome, "day": _day_report(db, day) if day is not None else None}
