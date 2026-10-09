"""Incremental runs over a reconciled source (candidate `normalized_change_log`).

The reconciliation candidate re-normalizes every row and keeps unchanged rows'
import times: a corrected daily aggregate does not advance
`daily_summary.updated_at`, and a deleted record leaves no row. Only its change
log names the affected dates. An incremental run must then equal a fresh run.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from analytics.runners.runner import run as legacy_run
from mi_fitness_whooping.baseline.runner import run as target_run
from test_basic_daily_path import source_with_gap
from test_target_baseline_run import TABLES, snapshot


CHANGE_LOG = """CREATE TABLE normalized_change_log (
  change_id INTEGER PRIMARY KEY, generation_id TEXT NOT NULL, source_table TEXT NOT NULL,
  logical_record_id TEXT NOT NULL, old_hash TEXT, new_hash TEXT, change_type TEXT NOT NULL,
  affected_timestamp INTEGER, affected_local_date TEXT, old_timestamp INTEGER,
  old_local_date TEXT, new_timestamp INTEGER, new_local_date TEXT, detected_at TEXT NOT NULL)"""
# Later than every import/update time in the fixture (<= 2026-09-27T06:00:00Z).
DETECTED = "2026-10-01T00:00:00+00:00"


def log_change(db: sqlite3.Connection, kind: str, table: str, old: str | None, new: str | None) -> None:
    db.execute("""INSERT INTO normalized_change_log
        (generation_id,source_table,logical_record_id,change_type,affected_local_date,
         old_local_date,new_local_date,detected_at) VALUES ('g2',?,?,?,?,?,?,?)""",
               (table, f"{table}:{old or new}", kind, new or old, old, new, DETECTED))


def active(path: Path) -> tuple[dict, dict]:
    with closing(sqlite3.connect(path)) as db:
        results = {(n, d): (v, s, f) for n, d, v, s, f in db.execute(
            """SELECT r.metric_name,r.metric_date,r.value,r.status,r.input_fingerprint
               FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id""")}
        features = {(k, d): f for k, d, f in db.execute(
            """SELECT a.kind,a.metric_date,f.input_fingerprint
               FROM active_features a JOIN features f USING(feature_id)""")}
    return results, features


class ReconciledSourceChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "health.sqlite"
        source_with_gap(self.source)
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute(CHANGE_LOG)
        self.target = self.root / "target.sqlite"
        self.legacy = self.root / "legacy.sqlite"
        self.assertEqual(target_run(self.source, self.target)["status"], "SUCCESS")
        self.assertEqual(legacy_run(self.source, self.legacy)["status"], "SUCCESS")

    def fresh(self) -> tuple[dict, dict]:
        copy = self.root / f"fresh-{len(list(self.root.glob('fresh-*')))}"
        copy.mkdir()
        shutil.copy(self.source, copy / "health.sqlite")
        target_run(copy / "health.sqlite", copy / "analytics.sqlite")
        return active(copy / "analytics.sqlite")

    def assert_incremental_equals_fresh(self) -> dict:
        outcome = target_run(self.source, self.target)
        self.assertEqual(outcome["status"], "SUCCESS")
        self.assertEqual(active(self.target), self.fresh())
        self.assertEqual(target_run(self.source, self.target)["status"], "NO NEW ANALYTICS INPUT")
        return outcome

    def test_old_daily_correction_without_updated_at_is_recalculated(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("UPDATE daily_summary SET resting_hr=80 WHERE local_date='2026-09-21'")
            log_change(db, "UPDATE", "heart_rate_day", "2026-09-21", "2026-09-21")
        self.assertGreater(self.assert_incremental_equals_fresh()["metrics_calculated"], 0)
        results, _ = active(self.target)
        self.assertEqual(results[("rhr.vendor_daily", "2026-09-21")][0], 80.0)
        # Legacy's discovery has no change-log input and keeps the old value.
        legacy_run(self.source, self.legacy)
        self.assertEqual(active(self.legacy)[0][("rhr.vendor_daily", "2026-09-21")][0], 55.0)

    def test_deleted_old_night_is_removed(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("DELETE FROM sleep_stages WHERE source_record_id='s21'")
            db.execute("DELETE FROM sleep_sessions WHERE source_record_id='s21'")
            log_change(db, "DELETE", "sleep", "2026-09-21", None)
        self.assert_incremental_equals_fresh()
        results, features = active(self.target)
        self.assertNotIn(("nightly", "2026-09-21"), features)
        self.assertNotIn(("sleep.total_sleep_time_min", "2026-09-21"), results)
        legacy_run(self.source, self.legacy)
        self.assertIn(("nightly", "2026-09-21"), active(self.legacy)[1])

    def test_unrelated_old_log_entries_do_not_force_work(self):
        with closing(sqlite3.connect(self.source)) as db, db:
            db.execute("""INSERT INTO normalized_change_log
                (generation_id,source_table,logical_record_id,change_type,affected_local_date,
                 old_local_date,new_local_date,detected_at)
                VALUES ('g0','steps','x','UPDATE','2026-09-21','2026-09-21','2026-09-21',
                        '2026-09-01T00:00:00+00:00')""")
            db.execute("UPDATE source_databases SET last_fingerprint='touched'")
        outcome = target_run(self.source, self.target)
        self.assertEqual((outcome["status"], outcome["features_calculated"]), ("SUCCESS", 0))
        self.assertEqual(active(self.target)[1], active(self.legacy)[1])


class SourceWithoutChangeLogTests(unittest.TestCase):
    def test_tables_and_summaries_still_equal_legacy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_with_gap(root / "health.sqlite")
            for statements in ((), ("UPDATE daily_summary SET resting_hr=80,"
                                    "updated_at='2026-09-28T08:00:00Z' WHERE local_date='2026-09-24'",
                                    "UPDATE source_databases SET last_fingerprint='c'")):
                with closing(sqlite3.connect(root / "health.sqlite")) as db, db:
                    for statement in statements:
                        db.execute(statement)
                self.assertEqual(target_run(root / "health.sqlite", root / "t.sqlite"),
                                 legacy_run(root / "health.sqlite", root / "l.sqlite"))
                for table in TABLES:
                    self.assertEqual(snapshot(root / "t.sqlite", table), snapshot(root / "l.sqlite", table))


if __name__ == "__main__":
    unittest.main()
