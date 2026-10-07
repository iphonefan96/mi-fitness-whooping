"""Synthetic end-to-end contract for the narrow usable daily path."""

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

from analytics.runners.runner import run as legacy_run
from analytics.tests.test_foundations import add_night, synthetic_source

from mi_fitness_whooping.basic import day_report, history_report, run_and_read


ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 9, 25)


def source_with_gap(path: Path) -> None:
    synthetic_source(path)
    with closing(sqlite3.connect(path)) as db:
        with db:
            for day in (19, 20, 21, 23, 24, 26):
                add_night(db, f"2026-09-{day}", f"s{day}", "2026-09-26T06:00:00Z")
            # Day 26 has a session but incomplete stage coverage.
            db.execute("DELETE FROM sleep_stages WHERE source_record_id='s26'")
            # A more recent activity-only day tests default night selection.
            db.execute("INSERT INTO daily_summary VALUES (?,?,?,?,?,?,?,?)",
                       ("2026-09-27", 17, 2, 80, 15, 1, 55,
                        "2026-09-27T06:00:00Z"))
            db.execute("UPDATE source_databases SET last_fingerprint='seven-nights'")


def selected_legacy(db_path: Path, day: date) -> dict[str, dict]:
    """Independent reference query against unchanged Legacy-produced rows."""
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return {row["metric_name"]: dict(row) for row in db.execute("""
            SELECT r.* FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE a.metric_date=? AND a.source_scope='primary'
              AND a.release_channel='production'
            """, (day.isoformat(),))}


class BasicDailyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "health.sqlite"
        self.target = root / "target.sqlite"
        self.reference = root / "legacy.sqlite"
        source_with_gap(self.source)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_source_to_dated_answer_matches_legacy_selected_metrics(self):
        before = self.source.read_bytes()
        answer = run_and_read(self.source, self.target, DAY)
        self.assertEqual(answer["run"]["status"], "SUCCESS")
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(legacy_run(self.source, self.reference)["status"], "SUCCESS")

        day = answer["day"]
        self.assertEqual(day["date"], DAY.isoformat())
        self.assertEqual(day["status"], "READY")
        for group, name in (("sleep", "sleep.score"),
                            ("sleep", "sleep.need_min"),
                            ("sleep", "sleep.debt_min"),
                            ("recovery", "recovery.score"),
                            ("vitals", "rhr.nightly"),
                            ("vitals", "spo2.nightly_mean"),
                            ("vitals", "respiratory.nightly_mean")):
            self.assertIn(name, day[group])
        self.assertEqual(day["recovery"]["recovery.score"]["status"], "REDUCED")
        self.assertEqual(day["recovery"]["recovery.score"]["metadata"]["active_components"],
                         ["rhr", "sleep"])
        self.assertEqual(day["activity"]["values"]["steps"], 0)
        self.assertIsNone(day["activity"]["values"]["distance_m"])
        self.assertEqual(day["stress"]["values"]["vendor_stress_median"], 12.0)

        selected = selected_legacy(self.reference, DAY)
        flattened = {name: metric for group in ("sleep", "recovery", "vitals", "other_metrics")
                     for name, metric in day[group].items()}
        self.assertEqual(set(flattened), set(selected))
        for name, expected in selected.items():
            with self.subTest(metric=name):
                actual = flattened[name]
                for key, column in (("value", "value"), ("unit", "unit"),
                                    ("status", "status"),
                                    ("stored_freshness", "freshness_status"),
                                    ("input_fingerprint", "input_fingerprint"),
                                    ("algorithm_id", "algorithm_id"),
                                    ("profile_revision", "profile_revision")):
                    self.assertEqual(actual[key], expected[column])
                self.assertEqual(actual["metadata"], json.loads(expected["metadata_json"]))

        second = run_and_read(self.source, self.target, DAY)
        self.assertEqual(second["run"]["status"], "NO NEW ANALYTICS INPUT")
        self.assertEqual(second["day"], day)

        # A newer activity-only date must not replace the latest sleep date.
        latest = run_and_read(self.source, self.target)
        self.assertEqual(latest["day"]["date"], "2026-09-26")

    def test_gap_incomplete_stages_and_inclusive_history(self):
        self.assertEqual(run_and_read(self.source, self.target, DAY)["run"]["status"], "SUCCESS")
        gap = day_report(self.target, date(2026, 9, 22))
        self.assertEqual(gap["status"], "MISSING")
        self.assertEqual(gap["sleep"], {})
        self.assertIsNone(gap["activity"])
        activity_only = day_report(self.target, date(2026, 9, 27))
        self.assertEqual(activity_only["status"], "READY")
        self.assertEqual(activity_only["sleep"], {})
        self.assertEqual(activity_only["activity"]["values"]["steps"], 17)
        incomplete = day_report(self.target, date(2026, 9, 26))
        self.assertEqual(incomplete["sleep"]["sleep.score"]["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(incomplete["sleep"]["sleep.score"]["value"])
        self.assertIsNone(incomplete["recovery"]["recovery.score"]["value"])
        days = history_report(self.target, date(2026, 9, 21), date(2026, 9, 23))["days"]
        self.assertEqual([d["date"] for d in days],
                         ["2026-09-21", "2026-09-22", "2026-09-23"])
        self.assertEqual([d["status"] for d in days], ["READY", "MISSING", "READY"])
        with self.assertRaisesRegex(ValueError, "start date"):
            history_report(self.target, date(2026, 9, 23), date(2026, 9, 21))

    def test_selected_result_row_wins_over_a_newer_revision(self):
        self.assertEqual(run_and_read(self.source, self.target, DAY)["run"]["status"], "SUCCESS")
        original = day_report(self.target, DAY)["recovery"]["recovery.score"]
        with closing(sqlite3.connect(self.target)) as db:
            old_id = db.execute("""SELECT result_id FROM active_metric_selection
                WHERE metric_date=? AND metric_name='recovery.score'
                AND source_scope='primary' AND release_channel='production'""",
                (DAY.isoformat(),)).fetchone()[0]
        with closing(sqlite3.connect(self.source)) as db:
            with db:
                db.execute("UPDATE daily_summary SET resting_hr=80,updated_at='2026-09-27T08:00:00Z' "
                           "WHERE local_date='2026-09-24'")
                db.execute("UPDATE source_databases SET last_fingerprint='corrected'")
        self.assertEqual(run_and_read(self.source, self.target, DAY)["run"]["status"], "SUCCESS")
        revised = day_report(self.target, DAY)["recovery"]["recovery.score"]
        self.assertNotEqual(revised["input_fingerprint"], original["input_fingerprint"])
        with closing(sqlite3.connect(self.target)) as db:
            with db:
                db.execute("""UPDATE active_metric_selection SET result_id=?
                    WHERE metric_date=? AND metric_name='recovery.score'
                    AND source_scope='primary' AND release_channel='production'""",
                    (old_id, DAY.isoformat()))
        self.assertEqual(day_report(self.target, DAY)["recovery"]["recovery.score"], original)

    def test_read_commands_are_read_only_and_cli_run_is_usable(self):
        source_before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "separate files"):
            run_and_read(self.source, self.source, DAY)
        self.assertEqual(self.source.read_bytes(), source_before)
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT / "Legacy")))
        command = [sys.executable, "-m", "mi_fitness_whooping", "run", "--source",
                   str(self.source), "--db", str(self.target), "--day", DAY.isoformat()]
        completed = subprocess.run(command, cwd=ROOT, env=env, check=True,
                                   capture_output=True, text=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["run"]["status"], "SUCCESS")
        self.assertEqual(result["day"]["recovery"]["recovery.score"]["status"], "REDUCED")
        before = self.target.read_bytes()
        read_env = env | {"PYTHONPATH": str(ROOT / "src")}
        for action in (("day", "--day", DAY.isoformat()),
                       ("history", "--from", "2026-09-21", "--to", "2026-09-23")):
            response = subprocess.run([sys.executable, "-m", "mi_fitness_whooping",
                                       action[0], "--db", str(self.target), *action[1:]],
                                      cwd=ROOT, env=read_env, check=True,
                                      capture_output=True, text=True)
            self.assertTrue(json.loads(response.stdout))
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), source_before)
        empty = Path(self.temp.name) / "empty.sqlite"
        with closing(sqlite3.connect(empty)):
            pass
        empty_before = empty.read_bytes()
        with self.assertRaisesRegex(ValueError, "schema v3"):
            day_report(empty, DAY)
        self.assertEqual(empty.read_bytes(), empty_before)


if __name__ == "__main__":
    unittest.main()
