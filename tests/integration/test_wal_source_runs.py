"""End-to-end runs on WAL-mode source copies, as `cp`/`.backup` of the ETL output produce.

Legacy runs on a DELETE-journal copy of the same data, which is the only form
it accepts; tables and run summaries must match.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from analytics.runners.runner import run as legacy_run
from mi_fitness_whooping.baseline import runner as target_runner
from mi_fitness_whooping.baseline.runner import run as target_run
from test_basic_daily_path import source_with_gap
from test_target_baseline_run import TABLES, snapshot


CORRECTION = ("UPDATE daily_summary SET resting_hr=80, updated_at='2026-09-28T08:00:00Z' "
              "WHERE local_date='2026-09-24'", "UPDATE source_databases SET last_fingerprint='rhr'")
REMOVAL = ("DELETE FROM sleep_sessions WHERE source_record_id='s26'",
           "UPDATE daily_summary SET updated_at='2026-09-29T08:00:00Z' WHERE local_date='2026-09-25'",
           "UPDATE source_databases SET last_fingerprint='removed'")


def wal_source(path: Path) -> None:
    source_with_gap(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    # Last connection closed: the file stays in WAL mode, sidecars are removed.


def apply(path: Path, statements: tuple[str, ...]) -> None:
    with closing(sqlite3.connect(path)) as db, db:
        for statement in statements:
            db.execute(statement)


class WalSourceRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.wal = root / "wal" / "health.sqlite"
        self.delete = root / "delete" / "health.sqlite"
        self.target = root / "target.sqlite"
        self.legacy = root / "legacy.sqlite"
        for path in (self.wal, self.delete):
            path.parent.mkdir()
        wal_source(self.wal)
        source_with_gap(self.delete)

    def assert_matches_legacy(self, target_source: Path, legacy_source: Path) -> dict:
        new = target_run(target_source, self.target)
        old = legacy_run(legacy_source, self.legacy)
        self.assertEqual(new, old)
        for table in TABLES:
            with self.subTest(table=table):
                self.assertEqual(snapshot(self.target, table), snapshot(self.legacy, table))
        return new

    def test_wal_source_runs_repeats_and_follows_corrections(self):
        # Before the fix the target adapter, like Legacy, rejected its own sidecars.
        with self.assertRaisesRegex(RuntimeError, "SOURCE_CHANGED_DURING_ANALYTICS_RUN"):
            legacy_run(self.wal, Path(self.temp.name) / "legacy-on-wal.sqlite")
        for suffix in ("", "-wal", "-shm"):                  # fresh copy after Legacy's attempt
            Path(str(self.wal) + suffix).unlink(missing_ok=True)
        wal_source(self.wal)
        self.assertEqual(self.assert_matches_legacy(self.wal, self.delete)["status"], "SUCCESS")
        self.assertTrue(Path(str(self.wal) + "-shm").exists())    # created by the read-only reader
        self.assertEqual(target_run(self.wal, self.target)["status"], "NO NEW ANALYTICS INPUT")

        for label, statements in (("late RHR correction", CORRECTION), ("removed night", REMOVAL)):
            with self.subTest(label):
                apply(self.wal, statements)
                apply(self.delete, statements)
                self.assertEqual(self.assert_matches_legacy(self.wal, self.delete)["status"], "SUCCESS")
                self.assertEqual(target_run(self.wal, self.target)["status"], "NO NEW ANALYTICS INPUT")

    def test_copy_with_uncheckpointed_wal_frames_reads_them(self):
        # Like `cp health.sqlite*` while the ETL connection still holds WAL frames.
        writer = sqlite3.connect(self.wal)
        try:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            with writer:
                for statement in CORRECTION:
                    writer.execute(statement)
            copy = Path(self.temp.name) / "copy" / "health.sqlite"
            copy.parent.mkdir()
            for suffix in ("", "-wal", "-shm"):
                shutil.copy(str(self.wal) + suffix, str(copy) + suffix)
        finally:
            writer.close()
        self.assertGreater(Path(str(copy) + "-wal").stat().st_size, 0)
        apply(self.delete, CORRECTION)
        self.assertEqual(self.assert_matches_legacy(copy, self.delete)["status"], "SUCCESS")
        self.assertEqual(target_run(copy, self.target)["status"], "NO NEW ANALYTICS INPUT")

    def test_data_written_during_a_run_is_still_rejected(self):
        self.assertEqual(target_run(self.wal, self.target)["status"], "SUCCESS")
        before = {table: snapshot(self.target, table) for table in TABLES}
        apply(self.wal, ("UPDATE source_databases SET last_fingerprint='next'",))
        original = target_runner.build_daily
        writers: list[sqlite3.Connection] = []

        def build_daily_with_concurrent_write(*args, **kwargs):
            if not writers:                     # an ETL commit lands mid-run
                writer = sqlite3.connect(self.wal)
                writer.execute("PRAGMA wal_autocheckpoint=0")
                with writer:
                    writer.execute("UPDATE daily_summary SET steps=steps+1")
                writers.append(writer)
            return original(*args, **kwargs)

        try:
            with patch.object(target_runner, "build_daily", build_daily_with_concurrent_write):
                with self.assertRaisesRegex(RuntimeError, "SOURCE_CHANGED_DURING_ANALYTICS_RUN"):
                    target_run(self.wal, self.target)
        finally:
            for writer in writers:
                writer.close()
        for table in TABLES:
            self.assertEqual(snapshot(self.target, table), before[table])
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual(db.execute("SELECT status FROM analytics_runs ORDER BY rowid DESC LIMIT 1")
                             .fetchone()[0], "FAILED")


if __name__ == "__main__":
    unittest.main()
