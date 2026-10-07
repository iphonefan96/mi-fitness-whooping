"""Full baseline differential checks against the immutable Legacy runner."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from analytics.runners.runner import run as legacy_run
from mi_fitness_whooping.baseline.runner import exclusive_lock, run as target_run
from mi_fitness_whooping.basic import day_report, history_report
from mi_fitness_whooping.storage.sqlite import SqliteMetricResultRepository
from test_basic_daily_path import source_with_gap


ROOT = Path(__file__).resolve().parents[2]
TABLES = ("features", "active_features", "derived_metric_results",
          "active_metric_selection")


def snapshot(path: Path, table: str) -> list[dict]:
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
    operational = ({"calculated_at", "run_id"} if table == "derived_metric_results"
                   else {"calculated_at"} if table == "features" else set())
    return [{key: value for key, value in row.items() if key not in operational}
            for row in rows]


class TargetBaselineRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "health.sqlite"
        self.legacy = self.root / "legacy.sqlite"
        self.target = self.root / "target.sqlite"
        source_with_gap(self.source)

    def compare_published(self) -> None:
        for table in TABLES:
            with self.subTest(table=table):
                self.assertEqual(snapshot(self.target, table), snapshot(self.legacy, table))
        for day in (date(2026, 9, 22), date(2026, 9, 25), date(2026, 9, 26),
                    date(2026, 9, 27)):
            with self.subTest(day=day):
                self.assertEqual(day_report(self.target, day), day_report(self.legacy, day))
        self.assertEqual(history_report(self.target, date(2026, 9, 21), date(2026, 9, 27)),
                         history_report(self.legacy, date(2026, 9, 21), date(2026, 9, 27)))

    def run_pair(self, profile: Path | None = None) -> tuple[dict, dict]:
        old = legacy_run(self.source, self.legacy, profile)
        new = target_run(self.source, self.target, profile)
        self.assertEqual(new, old)
        self.compare_published()
        return old, new

    def test_first_run_repeat_correction_and_missing_current_night(self):
        source_before = self.source.read_bytes()
        self.assertEqual(self.run_pair()[1]["status"], "SUCCESS")
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(day_report(self.target, date(2026, 9, 22))["status"], "MISSING")
        self.assertEqual(day_report(self.target, date(2026, 9, 26))
                         ["sleep"]["sleep.score"]["status"], "INSUFFICIENT_DATA")
        self.assertEqual(self.run_pair()[1]["status"], "NO NEW ANALYTICS INPUT")

        with closing(sqlite3.connect(self.source)) as db:
            with db:
                db.execute("UPDATE daily_summary SET resting_hr=80,"
                           "updated_at='2026-09-28T08:00:00Z' WHERE local_date='2026-09-24'")
                db.execute("UPDATE source_databases SET last_fingerprint='corrected-night'")
        self.assertEqual(self.run_pair()[1]["status"], "SUCCESS")

        with closing(sqlite3.connect(self.source)) as db:
            with db:
                db.execute("DELETE FROM sleep_sessions WHERE source_record_id='s26'")
                db.execute("UPDATE daily_summary SET updated_at='2026-09-29T08:00:00Z' "
                           "WHERE local_date='2026-09-25'")
                db.execute("UPDATE source_databases SET last_fingerprint='missing-night'")
        self.assertEqual(self.run_pair()[1]["status"], "SUCCESS")
        self.assertEqual(day_report(self.target, date(2026, 9, 26))["sleep"], {})

    def test_effective_profile_and_shared_transaction_rollback(self):
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"schema_version": 1, "values": [
            {"field": "sleep_target_min", "value": 450,
             "effective_from": "2026-09-23"}]}), encoding="utf-8")
        self.assertEqual(self.run_pair(profile)[1]["status"], "SUCCESS")
        self.assertEqual(day_report(self.target, date(2026, 9, 25))
                         ["sleep"]["sleep.need_min"]["value"], 450.0)
        previous = {table: snapshot(self.target, table) for table in TABLES}
        with closing(sqlite3.connect(self.source)) as db:
            with db:
                db.execute("UPDATE daily_summary SET resting_hr=82,"
                           "updated_at='2026-09-30T08:00:00Z' WHERE local_date='2026-09-24'")
                db.execute("UPDATE source_databases SET last_fingerprint='rollback'")
        original = SqliteMetricResultRepository.persist
        calls = 0

        def fail_second(repository, session, result, context):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic write failure")
            return original(repository, session, result, context)

        with patch.object(SqliteMetricResultRepository, "persist", fail_second):
            with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
                target_run(self.source, self.target, profile)
        self.assertGreaterEqual(calls, 2)
        for table in TABLES:
            self.assertEqual(snapshot(self.target, table), previous[table])
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute("SELECT status FROM analytics_runs ORDER BY rowid DESC LIMIT 1")
                             .fetchone()[0], "FAILED")

    def test_target_runner_imports_without_legacy_on_python_path(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        code = ("from mi_fitness_whooping.baseline.runner import run; "
                "import sys; result=run(sys.argv[1],sys.argv[2]); "
                "assert result['status']=='SUCCESS'; "
                "assert 'analytics' not in sys.modules")
        subprocess.run([sys.executable, "-c", code, str(self.source), str(self.target)],
                       cwd=self.root, env=env, check=True, capture_output=True, text=True)

    def test_runner_respects_outer_lock_before_opening_analytics(self):
        with exclusive_lock(Path(str(self.target) + ".lock")):
            with self.assertRaisesRegex(RuntimeError, "ANALYTICS_ALREADY_RUNNING"):
                target_run(self.source, self.target)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
