"""Storage Phase B: full-row synthetic differential tests against Legacy v3."""

from __future__ import annotations

import ast
import inspect
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from analytics.algorithms.foundations import FeatureRecord
from analytics.algorithms.sleep import calculate_sleep_day
from analytics.profile.config import load_profile
from analytics.storage.db import connect, migrate, put_result
from mi_fitness_whooping.analytics.sleep.core import calculate_sleep_core
from mi_fitness_whooping.integration.sleep.input_adapter import adapt_sleep_input
from mi_fitness_whooping.integration.sleep.storage_contract_adapter import to_persistable_sleep_result
from mi_fitness_whooping.storage.contracts import MetricResultRepository, ResultWriteContext
from mi_fitness_whooping.storage.fingerprint import result_fingerprint
from mi_fitness_whooping.storage.sqlite import (
    SqliteAnalyticsSessionFactory, SqliteMetricResultRepository,
)


ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 1, 20)
STAMP = datetime(2026, 1, 21, 0, 0, tzinfo=timezone.utc).isoformat()
SLEEP_NAMES = ("sleep.score", "sleep.need_min", "sleep.debt_min")


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 1, 21, 0, 0, tzinfo=timezone.utc)
        return instant if tz is None else instant.astimezone(tz)


def nights() -> dict[date, FeatureRecord]:
    result = {}
    for offset in range(14, -1, -1):
        day = DAY - timedelta(days=offset)
        result[day] = FeatureRecord(
            kind="nightly", day=day,
            values={"tst_min": 480.0, "deep_min": 90, "rem_min": 90,
                    "waso_min": 0, "awakening_durations_min": [],
                    "bedtime_local_min": 1380, "stage_coverage": "COMPLETE"},
            fingerprint=f"feature:{day.isoformat()}", source_count=offset + 1,
            source_ids_hash=f"sources:{day.isoformat()}",
            measurement_start=f"{day.isoformat()}T20:00:00+00:00",
            measurement_end=f"{day.isoformat()}T23:00:00+00:00",
            quality_flags=("VENDOR_DERIVED",),
        )
    return result


def write_context(revision: str, run_id: str, *, freshness: str = "HISTORICAL",
                  policy: str = "primary-v1") -> ResultWriteContext:
    return ResultWriteContext(
        run_id=run_id, profile_revision=revision, source_policy_version=policy,
        stored_freshness=freshness, normalization_version="xiaomi-normalization-1",
        implementation_version="0.5.0", input_contract_version="foundation-output-1",
        quality_gate_version="foundation-gates-1",
    )


@contextmanager
def paired_databases():
    with tempfile.TemporaryDirectory() as directory:
        legacy = connect(Path(directory) / "legacy.sqlite")
        target = connect(Path(directory) / "target.sqlite")
        try:
            migrate(legacy)
            migrate(target)  # Fixture only: target implementation never imports migrate().
            yield legacy, target, Path(directory)
        finally:
            legacy.close()
            target.close()


def snapshot(db: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    results = [dict(row) for row in db.execute(
        "SELECT * FROM derived_metric_results ORDER BY result_id")]
    selections = [dict(row) for row in db.execute(
        "SELECT * FROM active_metric_selection ORDER BY metric_name,metric_date,source_scope,release_channel")]
    return results, selections


def write_both(legacy, target, active_nights, profile, context):
    drafts = calculate_sleep_day(DAY, active_nights, profile)
    calculated = calculate_sleep_core(adapt_sleep_input(
        DAY, active_nights, profile, context.profile_revision))
    assert len(drafts) == len(calculated) == 3
    with patch("analytics.storage.db.datetime", FixedDateTime):
        with legacy:
            legacy_outcomes = [put_result(
                legacy, draft, run_id=context.run_id,
                profile_revision=context.profile_revision,
                freshness_status=context.stored_freshness,
                source_policy_version=context.source_policy_version,
            ) for draft in drafts]
    session = SqliteAnalyticsSessionFactory(target).begin()
    repository = SqliteMetricResultRepository(lambda: STAMP)
    try:
        outcomes = [repository.persist(session, to_persistable_sleep_result(result), context)
                    for result in calculated]
        session.commit()
    except BaseException:
        session.rollback()
        raise
    return drafts, calculated, legacy_outcomes, outcomes


class TargetStorageWriterTests(unittest.TestCase):
    def test_first_rerun_correction_profile_and_old_row_reselection_match_every_column(self):
        original = nights()
        correction_day = DAY - timedelta(days=3)
        corrected = original | {correction_day: replace(
            original[correction_day], fingerprint="corrected-feature",
            values=original[correction_day].values | {"tst_min": 300.0})}
        default, default_revision = load_profile(None)
        with paired_databases() as (legacy, target, directory):
            profile_path = directory / "profile.json"
            profile_path.write_text(json.dumps({"schema_version": 1, "values": [{
                "field": "sleep_target_min", "value": 450,
                "effective_from": (DAY - timedelta(days=13)).isoformat(),
            }]}), encoding="utf-8")
            configured, configured_revision = load_profile(profile_path)
            stages = (
                ("first", original, default, default_revision, 3),
                ("same", original, default, default_revision, 3),
                ("corrected", corrected, default, default_revision, 5),
                ("profile", corrected, configured, configured_revision, 8),
                ("reselect", original, default, default_revision, 8),
            )
            for label, active, profile, revision, expected_rows in stages:
                with self.subTest(stage=label):
                    context = write_context(revision, label)
                    drafts, calculated, old_outcomes, outcomes = write_both(
                        legacy, target, active, profile, context)
                    old_rows, old_selected = snapshot(legacy)
                    new_rows, new_selected = snapshot(target)
                    self.assertEqual(new_rows, old_rows)  # Every schema-v3 column, including timestamp.
                    self.assertEqual(new_selected, old_selected)
                    self.assertEqual(len(new_rows), expected_rows)
                    self.assertEqual([outcome.changed for outcome in outcomes], old_outcomes)
                    self.assertEqual({row["metric_name"] for row in new_selected}, set(SLEEP_NAMES))
                    if label == "first":
                        self.assertTrue(all(outcome.inserted and outcome.selection_changed
                                            for outcome in outcomes))
                    if label == "corrected":
                        self.assertEqual(sum(outcome.inserted for outcome in outcomes), 2)
                    if label == "profile":
                        self.assertTrue(all(outcome.inserted for outcome in outcomes))
                    for draft, result in zip(drafts, calculated, strict=True):
                        self.assertEqual(result_fingerprint(
                            to_persistable_sleep_result(result), context),
                            next(row["input_fingerprint"] for row in new_rows
                                 if row["result_id"] == next(
                                     selected["result_id"] for selected in new_selected
                                     if selected["metric_name"] == draft.name)))
                    if label == "same":
                        self.assertFalse(any(outcome.changed for outcome in outcomes))
                    if label == "reselect":
                        self.assertTrue(any(outcome.changed and not outcome.inserted
                                            for outcome in outcomes))

    def test_source_policy_and_freshness_nuances_match_legacy_rows(self):
        profile, revision = load_profile(None)
        with paired_databases() as (legacy, target, _):
            original = nights()
            write_both(legacy, target, original, profile,
                       write_context(revision, "first", freshness="FRESH"))
            first = snapshot(target)
            _, _, old, new = write_both(
                legacy, target, original, profile,
                write_context(revision, "policy-only", freshness="FRESH", policy="primary-v2"))
            self.assertEqual(old, [False] * 3)
            self.assertFalse(any(outcome.changed for outcome in new))
            self.assertEqual(snapshot(target), first)
            _, _, old, new = write_both(
                legacy, target, original, profile,
                write_context(revision, "freshness-only", freshness="STALE"))
            self.assertEqual(old, [True] * 3)
            self.assertTrue(all(outcome.changed and not outcome.inserted and
                                not outcome.selection_changed for outcome in new))
            self.assertEqual(snapshot(target), snapshot(legacy))
            self.assertEqual(snapshot(target), first)
            self.assertEqual({row["freshness_status"] for row in snapshot(target)[0]}, {"FRESH"})
            self.assertEqual({row["run_id"] for row in snapshot(target)[0]}, {"first"})

    def test_clear_is_explicit_cross_scope_and_history_is_preserved(self):
        profile, revision = load_profile(None)
        with paired_databases() as (legacy, target, _):
            write_both(legacy, target, nights(), profile, write_context(revision, "first"))
            for db in (legacy, target):
                selected_id = db.execute("""SELECT result_id FROM active_metric_selection
                    WHERE metric_name='sleep.score' AND source_scope='primary'""").fetchone()[0]
                with db:
                    db.execute("""INSERT INTO active_metric_selection
                        (metric_name,metric_date,source_scope,release_channel,result_id)
                        VALUES (?,?,?,'production',?)""",
                        ("sleep.score", DAY.isoformat(), "secondary", selected_id))
            before = snapshot(target)
            self.assertEqual(before, snapshot(legacy))
            # Full replay asks for no clear operation, preserving all selections.
            self.assertEqual(snapshot(target), before)
            with legacy:
                legacy.execute("""DELETE FROM active_metric_selection
                    WHERE metric_date=? AND metric_name IN (?,?,?)
                    AND release_channel='production'""", (DAY.isoformat(), *SLEEP_NAMES))
            session = SqliteAnalyticsSessionFactory(target).begin()
            repo = SqliteMetricResultRepository(lambda: STAMP)
            self.assertEqual(repo.clear_active(session, DAY, SLEEP_NAMES), 4)
            self.assertIsNone(repo.get_active(session, "sleep.score", DAY))
            session.commit()
            self.assertEqual(snapshot(target), snapshot(legacy))
            self.assertEqual(len(snapshot(target)[0]), 3)  # Revision history retained.
            self.assertEqual(snapshot(target)[1], [])

    def test_outer_transaction_rolls_back_partial_writes_and_rejects_nesting(self):
        profile, revision = load_profile(None)
        with paired_databases() as (legacy, target, _):
            write_both(legacy, target, nights(), profile, write_context(revision, "first"))
            baseline = snapshot(target)
            corrected = nights()
            corrected[DAY] = replace(corrected[DAY], fingerprint="new-today")
            drafts = calculate_sleep_day(DAY, corrected, profile)
            calculated = calculate_sleep_core(adapt_sleep_input(DAY, corrected, profile, revision))
            context = write_context(revision, "failed")
            with patch("analytics.storage.db.datetime", FixedDateTime):
                legacy.execute("BEGIN IMMEDIATE")
                try:
                    for draft in drafts[:2]:
                        put_result(legacy, draft, run_id="failed", profile_revision=revision,
                                   freshness_status="HISTORICAL")
                    raise RuntimeError("synthetic failure")
                except RuntimeError:
                    legacy.rollback()
            factory = SqliteAnalyticsSessionFactory(target)
            session = factory.begin()
            with self.assertRaisesRegex(RuntimeError, "nested"):
                factory.begin()
            repository = SqliteMetricResultRepository(lambda: STAMP)
            for result in calculated[:2]:
                repository.persist(session, to_persistable_sleep_result(result), context)
            self.assertTrue(target.in_transaction)
            self.assertNotEqual(snapshot(target), baseline)
            session.rollback()
            self.assertEqual(snapshot(target), snapshot(legacy))
            self.assertEqual(snapshot(target), baseline)
            with self.assertRaisesRegex(RuntimeError, "not active"):
                repository.get_active(session, "sleep.score", DAY)

    def test_schema_guard_and_architecture_import_direction(self):
        with sqlite3.connect(":memory:") as db:
            with self.assertRaisesRegex(RuntimeError, "schema v3"):
                SqliteAnalyticsSessionFactory(db)
        for operation in ("persist", "get_active", "clear_active"):
            self.assertEqual(
                inspect.signature(getattr(SqliteMetricResultRepository, operation))
                .parameters["session"].annotation,
                inspect.signature(getattr(MetricResultRepository, operation))
                .parameters["session"].annotation,
            )
        storage = ROOT / "src/mi_fitness_whooping/storage"
        for path in storage.glob("*.py"):
            with self.subTest(module=path.name):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = {alias.name for node in ast.walk(tree)
                            if isinstance(node, ast.Import) for alias in node.names}
                imported.update(node.module for node in ast.walk(tree)
                                if isinstance(node, ast.ImportFrom) and node.module)
                self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                                     or name.startswith("mi_fitness_whooping.analytics")
                                     or name.startswith("mi_fitness_whooping.orchestration")
                                     or name.startswith("mi_fitness_whooping.integration")
                                     for name in imported))
                self.assertNotIn("time", imported)
                self.assertNotIn("argparse", imported)
                self.assertNotIn(".time()", source)
                self.assertNotIn("calculate_sleep_core", source)


if __name__ == "__main__":
    unittest.main()
