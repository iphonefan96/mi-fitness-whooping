"""Phase 4C2 synthetic Sleep orchestration and Legacy compatibility."""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from analytics.algorithms.foundations import FeatureRecord
from analytics.algorithms.sleep import calculate_sleep_day
from analytics.profile.config import load_profile
from analytics.storage.db import connect, migrate, put_result
from mi_fitness_whooping.integration.sleep.legacy_persistence import LegacySleepStore
from mi_fitness_whooping.orchestration.sleep import SleepRunContext, run_sleep_day


ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 1, 20)
SLEEP_NAMES = {"sleep.score", "sleep.need_min", "sleep.debt_min"}


def nights() -> dict[date, FeatureRecord]:
    result = {}
    for offset in range(14, -1, -1):
        day = DAY - timedelta(days=offset)
        result[day] = FeatureRecord(
            kind="nightly", day=day,
            values={"tst_min": 480, "deep_min": 90, "rem_min": 90,
                    "waso_min": 0, "awakening_durations_min": [],
                    "bedtime_local_min": 1380, "stage_coverage": "COMPLETE"},
            fingerprint=f"synthetic:{day.isoformat()}", source_count=1,
            source_ids_hash=f"source:{day.isoformat()}",
            measurement_start=f"{day.isoformat()}T20:00:00+00:00",
            measurement_end=f"{day.isoformat()}T23:00:00+00:00",
            quality_flags=("VENDOR_DERIVED",),
        )
    return result


def context(revision: str, run_id: str, *, cleanup: bool = True,
            freshness: str = "HISTORICAL") -> SleepRunContext:
    return SleepRunContext(DAY, revision, run_id, "primary-v1", freshness, cleanup)


def snapshot(db) -> tuple[list[tuple], list[tuple]]:
    rows = [tuple(row) for row in db.execute("""SELECT result_id,metric_date,metric_name,value,
        unit,status,freshness_status,algorithm_id,algorithm_version,upstream_project,
        upstream_commit,metadata_json,source_signals_json,input_fingerprint,
        profile_revision,source_policy_version,supersedes_result_id
        FROM derived_metric_results ORDER BY result_id""")]
    selected = [tuple(row) for row in db.execute("""SELECT metric_name,metric_date,
        source_scope,release_channel,result_id FROM active_metric_selection
        WHERE metric_name IN ('sleep.score','sleep.need_min','sleep.debt_min')
        ORDER BY metric_name""")]
    return rows, selected


class SleepOrchestrationTests(unittest.TestCase):
    def test_first_rerun_correction_and_profile_revision_match_legacy(self):
        default, default_revision = load_profile(None)
        original = nights()
        correction_day = DAY - timedelta(days=3)
        corrected = original | {correction_day: replace(
            original[correction_day], fingerprint="corrected-night",
            values=original[correction_day].values | {"tst_min": 300})}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"schema_version": 1, "values": [{
                "field": "sleep_target_min", "value": 450,
                "effective_from": (DAY - timedelta(days=13)).isoformat()}]}), encoding="utf-8")
            configured, configured_revision = load_profile(path)
            self.assertNotEqual(configured_revision, default_revision)
            steps = (
                ("first", original, default, default_revision),
                ("same", original, default, default_revision),
                ("corrected", corrected, default, default_revision),
                ("profile", corrected, configured, configured_revision),
            )
            snapshots = {}
            for name in ("legacy", "target"):
                db = connect(Path(directory) / f"{name}.sqlite")
                try:
                    migrate(db)
                    states = []
                    for label, active_nights, profile, revision in steps:
                        run_context = context(revision, f"synthetic-{label}")
                        if name == "legacy":
                            drafts = calculate_sleep_day(DAY, active_nights, profile)
                            with db:
                                for draft in drafts:
                                    put_result(db, draft, run_id=run_context.run_id,
                                               profile_revision=revision,
                                               freshness_status=run_context.stored_freshness,
                                               source_policy_version=run_context.source_policy_version)
                        else:
                            results = run_sleep_day(active_nights, profile, run_context,
                                                    LegacySleepStore(db))
                            self.assertEqual([result.metric.value for result in results],
                                             ["sleep.score", "sleep.need_min", "sleep.debt_min"])
                            self.assertEqual(results[1].value,
                                             450.0 if label == "profile" else 480.0)
                            self.assertIs(type(results[1].value), float)
                        states.append(snapshot(db))
                    snapshots[name] = states
                finally:
                    db.close()
            self.assertEqual(snapshots["target"], snapshots["legacy"])
            first, same, corrected_state, profile_state = snapshots["target"]
            self.assertEqual(first, same)
            self.assertEqual([len(state[0]) for state in snapshots["target"]],
                             [3, 3, 5, 8])
            self.assertEqual(len(profile_state[1]), 3)
            self.assertNotEqual(first[1], corrected_state[1])
            self.assertNotEqual(corrected_state[1], profile_state[1])
            # Score's value is unchanged, but profile revision participates in
            # storage identity, so all three metrics get a new revision.
            self.assertEqual({row[2] for row in profile_state[0][-3:]}, SLEEP_NAMES)
            self.assertEqual({row[-1] for row in profile_state[0][-3:]}, {2, 4, 5})

    def test_missing_current_night_cleanup_follows_runner_mode(self):
        profile, revision = load_profile(None)
        for cleanup in (True, False):
            with self.subTest(cleanup=cleanup), tempfile.TemporaryDirectory() as directory:
                db = connect(Path(directory) / "analytics.sqlite")
                try:
                    migrate(db)
                    original = nights()
                    run_sleep_day(original, profile, context(revision, "first"),
                                  LegacySleepStore(db))
                    previous = snapshot(db)
                    without_today = {day: row for day, row in original.items() if day != DAY}
                    self.assertEqual(run_sleep_day(without_today, profile,
                                                   context(revision, "missing", cleanup=cleanup),
                                                   LegacySleepStore(db)), ())
                    rows, active = snapshot(db)
                    self.assertEqual(rows, previous[0])  # History is never deleted.
                    self.assertEqual(len(active), 0 if cleanup else 3)
                finally:
                    db.close()

    def test_failed_second_sleep_write_rolls_back_entire_sleep_date(self):
        profile, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                original = nights()
                run_sleep_day(original, profile, context(revision, "first"),
                              LegacySleepStore(db))
                previous = snapshot(db)
                changed_day = DAY - timedelta(days=2)
                corrected = original | {changed_day: replace(
                    original[changed_day], fingerprint="changed-before-failure")}

                from mi_fitness_whooping.integration.sleep import legacy_persistence
                original_put_result = legacy_persistence.put_result

                def fail_on_need(*args, **kwargs):
                    if args[1].name == "sleep.need_min":
                        raise RuntimeError("synthetic write failure")
                    return original_put_result(*args, **kwargs)

                with patch.object(legacy_persistence, "put_result", side_effect=fail_on_need):
                    with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
                        run_sleep_day(corrected, profile, context(revision, "failed"),
                                      LegacySleepStore(db))
                self.assertEqual(snapshot(db), previous)
            finally:
                db.close()

    def test_sleep_store_does_not_commit_a_callers_transaction(self):
        profile, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                db.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(RuntimeError, "idle connection"):
                    run_sleep_day(nights(), profile, context(revision, "nested"),
                                  LegacySleepStore(db))
                self.assertTrue(db.in_transaction)
                self.assertEqual(snapshot(db), ([], []))
                db.rollback()
            finally:
                db.close()

    def test_orchestrator_has_no_legacy_sql_clock_or_formula_ownership(self):
        package = ROOT / "src" / "mi_fitness_whooping"
        path = package / "orchestration" / "sleep.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported.update(node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module)
        self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                             for name in imported))
        self.assertNotIn("sqlite3", imported)
        self.assertNotIn("fcntl", imported)
        self.assertNotIn("argparse", imported)
        self.assertNotIn(".execute(", source)
        self.assertNotIn(".now(", source)
        self.assertNotIn(".utcnow(", source)
        self.assertNotIn("calculate_sleep_day", source)
        self.assertNotIn("score_components", source)
        bridge = (package / "integration" / "sleep" /
                  "legacy_persistence.py").read_text(encoding="utf-8")
        self.assertIn("TEMPORARY MIGRATION DEBT", bridge)
        self.assertNotIn("calculate_sleep_day", bridge)
        self.assertNotIn("mi_fitness_whooping.orchestration", bridge)
        run_context = (package / "integration" / "sleep" /
                       "run_context.py").read_text(encoding="utf-8")
        self.assertNotIn("from analytics", run_context)
        self.assertNotIn(".now(", run_context)


if __name__ == "__main__":
    unittest.main()
