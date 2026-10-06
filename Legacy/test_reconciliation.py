"""Disposable source-reconciliation regression tests; no production paths."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import mi_fitness_reconcile as rec

T0 = 1_750_000_000
T1 = T0 + 10 * 86400


def source_db(path: Path, *, wal: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    if wal:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
    for table in ("heart_rate", "sleep", "steps"):
        db.execute(f"""CREATE TABLE {table}(
            sid TEXT NOT NULL,key TEXT NOT NULL,time INTEGER NOT NULL,value TEXT NOT NULL,
            zone_offset INTEGER NOT NULL,time_zero INTEGER NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(sid,key,time))""")
    db.commit()
    return db


def hr(db: sqlite3.Connection, when: int, bpm: int, *, deleted: int = 0) -> None:
    db.execute("INSERT INTO heart_rate VALUES(?,?,?,?,?,?,?)",
               ("device", "heart_rate", when, json.dumps({"time": when, "bpm": bpm}), 0, when, deleted))
    db.commit()


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="reconcile-test-")
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.output = self.root / "out"
        self.cn_path = self.source / "DataBase" / "123" / "cn" / "123.db"
        self.ru_path = self.source / "DataBase" / "123" / "ru" / "123.db"
        self.cn = source_db(self.cn_path)
        self.ru = source_db(self.ru_path)

    def tearDown(self) -> None:
        self.cn.close()
        self.ru.close()
        self.tmp.cleanup()

    def run_reconcile(self, *, rebuild=False, full=False, selection_policy="ru_compat") -> dict:
        return rec.reconcile(self.source, self.output, rebuild=rebuild, full=full,
                             selection_policy=selection_policy)

    def target(self):
        return closing(sqlite3.connect(self.output / rec.TARGET_NAME))

    def test_identical_regions_two_physical_one_logical_provenance(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 60)
        self.assertEqual(self.run_reconcile(rebuild=True)["status"], "SUCCESS")
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM normalized_provenance").fetchone()[0], 2)
            self.assertEqual({r[0] for r in db.execute("SELECT role FROM normalized_provenance")},
                             {"PRIMARY", "DUPLICATE_EQUAL"})
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0], 0)

    def test_differing_bpm_conflict_and_selection_replay(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 65)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 65)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_conflicts WHERE status LIKE 'UNRESOLVED%'").fetchone()[0], 1)
            self.assertEqual({r[0] for r in db.execute("SELECT role FROM normalized_provenance")},
                             {"PRIMARY", "CONFLICT_ALTERNATIVE"})
        changed = self.run_reconcile(selection_policy="cn_review")
        self.assertEqual(changed["status"], "SUCCESS")
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 60)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM normalized_change_log WHERE change_type='UPDATE'").fetchone()[0], 1)
            self.assertIn("CN_PRIORITY", db.execute("SELECT selection_reason FROM source_conflicts").fetchone()[0])

    def test_unresolved_bpm_is_excluded_with_both_sources_retained(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 65)
        self.run_reconcile(rebuild=True, selection_policy="unresolved_exclude")
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM source_conflicts").fetchone()[0], "UNRESOLVED_EXCLUDED")
            self.assertEqual(db.execute("SELECT selected_physical_id FROM source_conflicts").fetchone()[0], "")
            self.assertEqual({r[0] for r in db.execute("SELECT role FROM normalized_provenance")},
                             {"CONFLICT_ALTERNATIVE"})
            self.assertEqual(db.execute("SELECT value FROM reconcile_state WHERE key='conflict_policy_version'").fetchone()[0],
                             "physiology-v1:unresolved_exclude")

    def test_metadata_only_difference_is_equivalent_not_excluded(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 60)
        self.ru.execute("UPDATE heart_rate SET zone_offset=? WHERE time=?", (0, T0))
        self.ru.execute("ALTER TABLE heart_rate ADD COLUMN isUploaded INTEGER")
        self.ru.execute("UPDATE heart_rate SET isUploaded=1 WHERE time=?", (T0,))
        self.ru.commit()
        self.run_reconcile(rebuild=True, selection_policy="unresolved_exclude")
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM source_conflicts").fetchone()[0],
                             "EQUIVALENT_PHYSIOLOGY_METADATA_DIFF")

    def test_policy_version_and_selection_change_trigger_replay(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 65)
        self.run_reconcile(rebuild=True, selection_policy="ru_compat")
        with self.target() as db:
            before = db.execute("SELECT conflict_policy_version FROM source_generations").fetchone()[0]
            old_run_id = db.execute("SELECT run_id FROM etl_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
            self.assertTrue(old_run_id.startswith("physiology-v1:ru_compat:"))
        self.run_reconcile(selection_policy="unresolved_exclude")
        with self.target() as db:
            after = db.execute("SELECT conflict_policy_version FROM source_generations ORDER BY scanned_at DESC LIMIT 1").fetchone()[0]
            new_run_id = db.execute("SELECT run_id FROM etl_runs ORDER BY started_at DESC LIMIT 1").fetchone()[0]
            self.assertNotEqual(before, after)
            self.assertTrue(new_run_id.startswith("physiology-v1:unresolved_exclude:"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT change_type FROM normalized_change_log ORDER BY change_id DESC LIMIT 1").fetchone()[0], "DELETE")

    def test_old_correction_detected_by_deep_reconcile(self):
        hr(self.ru, T0, 60)
        hr(self.ru, T1, 70)
        self.run_reconcile(rebuild=True)
        self.ru.execute("UPDATE heart_rate SET value=? WHERE time=?",
                        (json.dumps({"time": T0, "bpm": 65}), T0))
        self.ru.commit()
        result = self.run_reconcile(full=True)
        self.assertEqual(result["counts"]["canonical_update"], 1)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate WHERE timestamp_utc=?", (T0,)).fetchone()[0], 65)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_record_history").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT affected_local_date FROM normalized_change_log WHERE change_type='UPDATE'").fetchone()[0],
                             "2025-06-15")

    def test_date_move_logs_both_dirty_dates(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        self.ru.execute("UPDATE heart_rate SET time_zero=? WHERE time=?", (T0 + 86400, T0))
        self.ru.commit()
        self.run_reconcile(full=True)
        with self.target() as db:
            old_date, new_date = db.execute("""SELECT old_local_date,new_local_date
              FROM normalized_change_log WHERE change_type='UPDATE'""").fetchone()
            self.assertEqual(old_date, "2025-06-15")
            self.assertEqual(new_date, "2025-06-16")

    def test_old_blob_version_is_archived(self):
        hr(self.ru, T0, 60)
        self.ru.execute("ALTER TABLE heart_rate ADD COLUMN sensor_blob BLOB")
        self.ru.execute("UPDATE heart_rate SET sensor_blob=? WHERE time=?", (b"old", T0))
        self.ru.commit()
        self.run_reconcile(rebuild=True)
        self.ru.execute("UPDATE heart_rate SET sensor_blob=? WHERE time=?", (b"new", T0))
        self.ru.commit()
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT data FROM physical_blob_archive").fetchone()[0], b"old")
            self.assertEqual(db.execute("SELECT data FROM physical_blobs").fetchone()[0], b"new")

    def test_physical_disappearance_deactivates_but_retains_history(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        self.ru.execute("DELETE FROM heart_rate WHERE time=?", (T0,))
        self.ru.commit()
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM physical_records").fetchone()[0], "MISSING")
            self.assertEqual(db.execute("SELECT role FROM normalized_provenance").fetchone()[0], "SOURCE_MISSING")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM normalized_change_log WHERE change_type='DELETE'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_record_history").fetchone()[0], 1)
        hr(self.ru, T0, 60)
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM physical_records").fetchone()[0], "ACTIVE")

    def test_tombstone_toggle_and_fallback_to_other_region(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 65)
        self.run_reconcile(rebuild=True)
        self.ru.execute("UPDATE heart_rate SET deleted=1 WHERE time=?", (T0,))
        self.ru.commit()
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 60)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records WHERE status='TOMBSTONE'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM normalized_provenance WHERE role='TOMBSTONE_SOURCE'").fetchone()[0], 1)
        self.ru.execute("UPDATE heart_rate SET deleted=0 WHERE time=?", (T0,))
        self.ru.commit()
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 65)

    def test_only_tombstone_has_no_normalized_value(self):
        hr(self.ru, T0, 60, deleted=1)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0], 1)

    def test_source_replaced_same_path_and_order_stable(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T1, 70)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            ids_before = {r[0]: r[1] for r in db.execute("SELECT source_key,source_db_id FROM source_database_identities")}
        self.cn.close()
        self.cn_path.unlink()
        self.cn = source_db(self.cn_path)
        hr(self.cn, T1, 61)
        self.run_reconcile(full=True)
        with self.target() as db:
            ids_after = {r[0]: r[1] for r in db.execute("SELECT source_key,source_db_id FROM source_database_identities")}
            self.assertEqual(ids_before, ids_after)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records WHERE status='MISSING'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 1)

    def test_same_content_moved_path_keeps_source_identity(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            source_id_before = db.execute("SELECT source_db_id FROM physical_records").fetchone()[0]
        self.ru.close()
        moved = self.source / "DataBase" / "relocated" / "ru" / "123.db"
        moved.parent.mkdir(parents=True)
        shutil.move(self.ru_path, moved)
        self.ru = sqlite3.connect(moved)
        self.run_reconcile(full=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT source_db_id FROM physical_records").fetchone()[0], source_id_before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 1)

    def test_database_discovery_order_does_not_change_identity(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T1, 70)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            before = db.execute("SELECT source_key,source_db_id FROM source_database_identities ORDER BY source_key").fetchall()
        normal_discovery = rec.discover_candidate_databases
        with patch.object(rec, "discover_candidate_databases",
                          side_effect=lambda root: list(reversed(normal_discovery(root)))):
            self.assertEqual(self.run_reconcile(full=True)["status"], "SUCCESS")
        with self.target() as db:
            after = db.execute("SELECT source_key,source_db_id FROM source_database_identities ORDER BY source_key").fetchall()
            self.assertEqual(before, after)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM heart_rate").fetchone()[0], 2)

    def test_synology_conflict_copy_is_not_authoritative(self):
        hr(self.ru, T0, 65)
        conflict_path = self.ru_path.with_name("123.conflict-20260925-002251.db")
        stale = source_db(conflict_path)
        try:
            hr(stale, T0, 60)
        finally:
            stale.close()
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_database_identities").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 65)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM source_conflicts").fetchone()[0], 0)

    def test_full_rebuild_logical_idempotency_and_fast_noop(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            before = db.execute("SELECT source_record_id,bpm FROM heart_rate").fetchall()
        self.assertEqual(self.run_reconcile()["status"], "NO NEW SOURCE DATA")
        self.run_reconcile(rebuild=True)
        with self.target() as db:
            self.assertEqual(db.execute("SELECT source_record_id,bpm FROM heart_rate").fetchall(), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_two_clean_rebuilds_have_identical_logical_and_provenance_digest(self):
        hr(self.cn, T0, 60)
        hr(self.ru, T0, 65)
        hr(self.ru, T1, 70)
        first = self.output / "a"
        second = self.output / "b"
        for output in (first, second):
            self.assertEqual(rec.reconcile(self.source, output, rebuild=True,
                                           selection_policy="unresolved_exclude")["status"], "SUCCESS")
        def digest(path):
            with closing(sqlite3.connect(path / rec.TARGET_NAME)) as db:
                data = {
                    "canonical": db.execute("SELECT logical_record_id,physical_record_id,conflict_status FROM canonical_selection ORDER BY logical_record_id").fetchall(),
                    "provenance": db.execute("SELECT logical_record_id,physical_record_id,role,conflict_policy_version FROM normalized_provenance ORDER BY logical_record_id,physical_record_id").fetchall(),
                    "heart_rate": db.execute("SELECT source_record_id,timestamp_utc,bpm FROM heart_rate ORDER BY source_record_id").fetchall(),
                }
                return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
        self.assertEqual(digest(first), digest(second))

    def test_incremental_after_rebuild_updates_old_row(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        self.ru.execute("UPDATE heart_rate SET value=? WHERE time=?",
                        (json.dumps({"time": T0, "bpm": 65}), T0))
        self.ru.commit()
        self.assertEqual(self.run_reconcile()["status"], "SUCCESS")
        with self.target() as db:
            self.assertEqual(db.execute("SELECT bpm FROM heart_rate").fetchone()[0], 65)

    def test_failure_does_not_replace_disposable_target(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        target = self.output / rec.TARGET_NAME
        before = hash_file(target)
        hr(self.ru, T1, 70)
        with patch.object(rec, "_rebuild_canonical", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                self.run_reconcile(full=True)
        self.assertEqual(hash_file(target), before)
        self.assertEqual(self.run_reconcile(full=True)["status"], "SUCCESS")

    def test_source_change_during_staging_refused(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        target = self.output / rec.TARGET_NAME
        before = hash_file(target)
        original = rec.stable_stage_database
        fired = False

        def mutate(path, stage):
            nonlocal fired
            result = original(path, stage)
            if path.resolve() == self.ru_path.resolve() and not fired:
                hr(self.ru, T1, 70)
                fired = True
            return result

        with patch.object(rec, "stable_stage_database", side_effect=mutate):
            with self.assertRaises(rec.SourceSnapshotBusyError):
                self.run_reconcile(full=True)
        self.assertEqual(hash_file(target), before)

    def test_source_change_after_staging_during_later_scan_refused(self):
        hr(self.cn, T0, 60)
        self.run_reconcile(rebuild=True)
        target = self.output / rec.TARGET_NAME
        before = hash_file(target)
        original = rec._scan_database
        fired = False

        def mutate(*args, **kwargs):
            nonlocal fired
            result = original(*args, **kwargs)
            if not fired and "/cn/" in args[3]:
                hr(self.cn, T1, 70)
                fired = True
            return result

        with patch.object(rec, "_scan_database", side_effect=mutate):
            with self.assertRaises(rec.SourceSnapshotBusyError):
                self.run_reconcile(full=True)
        self.assertEqual(hash_file(target), before)

    def test_wal_change_during_copy_refused(self):
        self.ru.close()
        self.ru_path.unlink()
        self.ru = source_db(self.ru_path, wal=True)
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        target = self.output / rec.TARGET_NAME
        before = hash_file(target)
        original = rec.stable_stage_database

        def mutate(path, stage):
            result = original(path, stage)
            if path.resolve() == self.ru_path.resolve():
                hr(self.ru, T1, 70)  # committed into WAL after copied snapshot
            return result

        with patch.object(rec, "stable_stage_database", side_effect=mutate):
            with self.assertRaises(rec.SourceSnapshotBusyError):
                self.run_reconcile(full=True)
        self.assertEqual(hash_file(target), before)

    def test_missing_whole_source_db_is_safe_skip(self):
        hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        before = hash_file(self.output / rec.TARGET_NAME)
        self.ru.close()
        self.ru_path.unlink()
        self.ru = sqlite3.connect(":memory:")
        with self.assertRaises(rec.SourceSnapshotBusyError):
            self.run_reconcile(full=True)
        self.assertEqual(hash_file(self.output / rec.TARGET_NAME), before)

    def test_production_output_guard(self):
        with self.assertRaises(ValueError):
            rec.reconcile(self.source, Path("/Users/rus/Library/Application Support/MiFitnessETL/data"), rebuild=True)


if __name__ == "__main__":
    unittest.main()
