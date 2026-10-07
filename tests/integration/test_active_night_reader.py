"""Synthetic selected-night read contracts against schema v3 and Legacy."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from analytics.algorithms.sleep import calculate_sleep_day
from analytics.models import QualityFlag
from analytics.profile.config import load_profile
from analytics.storage.db import (
    active_feature_records, connect, delete_active_feature, migrate, put_feature,
    put_result,
)
from mi_fitness_whooping.integration.sleep.run_context import SleepRunContext
from mi_fitness_whooping.integration.sleep.input_adapter import adapt_sleep_input
from mi_fitness_whooping.integration.sleep.target_persistence import TargetSleepStore
from mi_fitness_whooping.orchestration.sleep import run_sleep_day
from mi_fitness_whooping.storage.sqlite import SqliteAnalyticsSessionFactory
from mi_fitness_whooping.storage.sqlite import (
    SqliteActiveNightReader, SqliteMetricResultRepository,
)
from test_sleep_orchestration import FixedDateTime, STAMP, full_snapshot
from test_sleep_package_and_seam import DAY, POLICY, feature, target_selected_nights


class SelectedNightReaderTests(unittest.TestCase):
    def test_active_revision_bounded_history_and_provenance(self):
        _, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                lower = DAY - timedelta(days=14)
                missing = DAY - timedelta(days=5)
                with db:
                    for offset in range(-1, 16):
                        day = DAY - timedelta(days=offset)
                        if day != missing:
                            put_feature(db, feature(day), profile_revision=revision,
                                        source_policy_version=POLICY)
                    corrected = replace(
                        feature(DAY), input_fingerprint="corrected-current",
                        values=feature(DAY).values | {
                            "tst_min": 301, "bedtime_local_min": 1430,
                            "extra_vital": 73,
                        },
                        quality_flags=frozenset({QualityFlag.STAGE_INCOMPLETE}),
                    )
                    put_feature(db, corrected, profile_revision=revision,
                                source_policy_version=POLICY)

                legacy, _ = active_feature_records(db)
                session = SqliteAnalyticsSessionFactory(db).begin()
                try:
                    selected = SqliteActiveNightReader().selected_nights(session, DAY)
                    expected_days = {day for day in legacy if lower <= day <= DAY}
                    self.assertEqual(set(selected), expected_days)
                    self.assertNotIn(missing, selected)
                    self.assertNotIn(DAY - timedelta(days=15), selected)
                    self.assertNotIn(DAY + timedelta(days=1), selected)
                    current = selected[DAY]
                    self.assertEqual(current.fingerprint, "corrected-current")
                    self.assertEqual(current.tst_min, 301)
                    self.assertEqual(current.bedtime_local_min, 1430)
                    self.assertEqual(current.quality_flags, ("STAGE_INCOMPLETE",))
                    self.assertNotIn("extra_vital", current.values)
                    self.assertFalse(hasattr(current, "feature_id"))
                    for day, target in selected.items():
                        reference = legacy[day]
                        self.assertEqual(target.kind, "nightly")
                        self.assertEqual(target.day, reference.day)
                        self.assertEqual(target.fingerprint, reference.fingerprint)
                        self.assertEqual(target.source_count, reference.source_count)
                        self.assertEqual(target.source_ids_hash, reference.source_ids_hash)
                        self.assertEqual(target.measurement_start, reference.measurement_start)
                        self.assertEqual(target.measurement_end, reference.measurement_end)
                        self.assertEqual(target.quality_flags, reference.quality_flags)
                        for field in ("tst_min", "deep_min", "rem_min", "waso_min",
                                      "bedtime_local_min", "stage_coverage"):
                            self.assertEqual(getattr(target, field), reference.values.get(field))
                        self.assertEqual(target.awakening_durations_min,
                                         reference.values.get("awakening_durations_min"))
                    self.assertTrue(db.in_transaction)  # Reader does not commit.
                finally:
                    session.commit()
            finally:
                db.close()

    def test_selected_nights_and_all_persisted_sleep_results_match_legacy(self):
        default, default_revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            configured_path = Path(directory) / "profile.json"
            configured_path.write_text(
                '{"schema_version":1,"values":[{"field":"sleep_target_min",'
                '"value":450,"effective_from":"2026-01-07"}]}', encoding="utf-8")
            configured, configured_revision = load_profile(configured_path)
            legacy = connect(Path(directory) / "legacy.sqlite")
            target = connect(Path(directory) / "target.sqlite")
            try:
                migrate(legacy)
                migrate(target)
                for db in (legacy, target):
                    with db:
                        for offset in range(14, -1, -1):
                            put_feature(db, feature(DAY - timedelta(days=offset)),
                                        profile_revision=default_revision,
                                        source_policy_version=POLICY)
                stages = (
                    ("first", None, default, default_revision),
                    ("unchanged", None, default, default_revision),
                    ("past-correction", DAY - timedelta(days=3), default, default_revision),
                    ("current-correction", DAY, default, default_revision),
                    ("profile", None, configured, configured_revision),
                    ("missing-current", "delete", configured, configured_revision),
                )
                for label, changed_day, profile, revision in stages:
                    with self.subTest(stage=label):
                        if isinstance(changed_day, date):
                            changed = feature(changed_day, corrected=True)
                            for db in (legacy, target):
                                with db:
                                    put_feature(db, changed, profile_revision=default_revision,
                                                source_policy_version=POLICY)
                        elif changed_day == "delete":
                            for db in (legacy, target):
                                with db:
                                    delete_active_feature(db, "nightly", DAY.isoformat())
                        old_nights, _ = active_feature_records(legacy)
                        new_nights = target_selected_nights(target)
                        self.assertEqual(
                            {day for day in old_nights if DAY - timedelta(days=14) <= day <= DAY},
                            set(new_nights))
                        for day, selected in new_nights.items():
                            self.assertEqual(selected.fingerprint, old_nights[day].fingerprint)
                            self.assertEqual(selected.source_ids_hash,
                                             old_nights[day].source_ids_hash)
                        run_context = SleepRunContext(
                            DAY, revision, label, POLICY, "HISTORICAL", True)
                        drafts = calculate_sleep_day(DAY, old_nights, profile)
                        with patch("analytics.storage.db.datetime", FixedDateTime):
                            with legacy:
                                for draft in drafts:
                                    put_result(legacy, draft, run_id=label,
                                               profile_revision=revision,
                                               freshness_status="HISTORICAL",
                                               source_policy_version=POLICY)
                                if not drafts:
                                    legacy.execute("""DELETE FROM active_metric_selection
                                        WHERE metric_date=? AND metric_name IN (?,?,?)
                                        AND release_channel='production'""",
                                        (DAY.isoformat(), "sleep.score", "sleep.need_min",
                                         "sleep.debt_min"))
                        results = run_sleep_day(
                            new_nights, profile, run_context,
                            TargetSleepStore(SqliteAnalyticsSessionFactory(target),
                                             SqliteMetricResultRepository(lambda: STAMP)))
                        self.assertEqual([result.metric.value for result in results],
                                         [draft.name for draft in drafts])
                        self.assertEqual(full_snapshot(target), full_snapshot(legacy))
                        if label == "past-correction":
                            self.assertNotEqual(results[2].value, 0)
                        if label == "current-correction":
                            self.assertNotEqual(results[0].value, 100)
                        if label == "profile":
                            self.assertEqual(results[1].value, 450.0)
                        if label == "missing-current":
                            self.assertEqual(results, ())
                            self.assertEqual(full_snapshot(target)[1], [])
            finally:
                legacy.close()
                target.close()

    def test_deleted_active_selection_does_not_fall_back_to_historical_row(self):
        _, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                with db:
                    put_feature(db, feature(DAY), profile_revision=revision,
                                source_policy_version=POLICY)
                    self.assertTrue(delete_active_feature(db, "nightly", DAY.isoformat()))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0], 1)
                session = SqliteAnalyticsSessionFactory(db).begin()
                try:
                    self.assertEqual(SqliteActiveNightReader().selected_nights(session, DAY), {})
                finally:
                    session.commit()
            finally:
                db.close()

    def test_older_reselected_row_wins_over_newer_historical_revision(self):
        _, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                original = feature(DAY)
                corrected = replace(original, input_fingerprint="newer-correction",
                                    values=original.values | {"tst_min": 300})
                with db:
                    put_feature(db, original, profile_revision=revision,
                                source_policy_version=POLICY)
                    put_feature(db, corrected, profile_revision=revision,
                                source_policy_version=POLICY)
                    put_feature(db, original, profile_revision=revision,
                                source_policy_version=POLICY)  # Reselect older row.
                self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0], 2)
                legacy, _ = active_feature_records(db)
                session = SqliteAnalyticsSessionFactory(db).begin()
                try:
                    selected = SqliteActiveNightReader().selected_nights(session, DAY)
                    self.assertEqual(selected[DAY].fingerprint, legacy[DAY].fingerprint)
                    self.assertEqual(selected[DAY].fingerprint, original.input_fingerprint)
                    self.assertEqual(selected[DAY].tst_min, original.values["tst_min"])
                finally:
                    session.commit()
            finally:
                db.close()

    def test_reads_uncommitted_active_selection_in_supplied_session(self):
        _, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                session = SqliteAnalyticsSessionFactory(db).begin()
                try:
                    put_feature(db, feature(DAY), profile_revision=revision,
                                source_policy_version=POLICY)
                    selected = SqliteActiveNightReader().selected_nights(session, DAY)
                    self.assertEqual(selected[DAY].fingerprint,
                                     feature(DAY).input_fingerprint)
                    self.assertTrue(db.in_transaction)
                finally:
                    session.rollback()
                self.assertEqual(db.execute("SELECT COUNT(*) FROM active_features").fetchone()[0], 0)
            finally:
                db.close()

    def test_raw_missing_zero_and_incomplete_stage_values_reach_sleep_adapter(self):
        profile, revision = load_profile(None)
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                original = feature(DAY)
                incomplete = replace(original, values=original.values | {
                    "tst_min": 0, "deep_min": None, "rem_min": -1,
                    "waso_min": 0, "awakening_durations_min": None,
                    "bedtime_local_min": None, "stage_coverage": "UNKNOWN",
                })
                with db:
                    put_feature(db, incomplete, profile_revision=revision,
                                source_policy_version=POLICY)
                nights = target_selected_nights(db)
                row = nights[DAY]
                self.assertEqual(row.tst_min, 0)
                self.assertIsNone(row.deep_min)
                self.assertEqual(row.rem_min, -1)
                self.assertEqual(row.waso_min, 0)
                self.assertIsNone(row.awakening_durations_min)
                self.assertIsNone(row.bedtime_local_min)
                self.assertEqual(row.stage_coverage, "UNKNOWN")
                canonical = adapt_sleep_input(DAY, nights, profile, revision)
                selected = canonical.selected_nights[0]
                self.assertEqual(selected.tst_min, 0)
                self.assertIsNone(selected.deep_min)
                self.assertFalse(selected.stage_complete)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
