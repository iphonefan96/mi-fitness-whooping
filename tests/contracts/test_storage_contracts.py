"""Storage Phase A: target-owned shape and full Sleep persistence field coverage."""

from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError, fields
from datetime import date, timedelta
from pathlib import Path

from analytics.algorithms.foundations import FeatureRecord
from analytics.algorithms.sleep import calculate_sleep_day
from analytics.profile.config import load_profile
from mi_fitness_whooping.analytics.sleep.core import calculate_sleep_core
from mi_fitness_whooping.integration.sleep.input_adapter import adapt_sleep_input
from mi_fitness_whooping.integration.sleep.storage_contract_adapter import to_persistable_sleep_result
from mi_fitness_whooping.storage.contracts import (
    ActiveResult, AnalyticsSession, AnalyticsSessionFactory, MetricResultRepository,
    PersistableMetricResult, ResultIdentity, ResultWriteContext, StoredFeatureRef,
    WriteOutcome,
)


ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 1, 20)


def nights() -> dict[date, FeatureRecord]:
    return {
        day: FeatureRecord(
            kind="nightly", day=day,
            values={"tst_min": 480.0, "deep_min": 90, "rem_min": 90,
                    "waso_min": 0, "awakening_durations_min": [],
                    "bedtime_local_min": 1380, "stage_coverage": "COMPLETE"},
            fingerprint=f"feature-{day.isoformat()}", source_count=offset,
            source_ids_hash=f"ids-{day.isoformat()}",
            measurement_start=f"{day.isoformat()}T20:00:00+00:00",
            measurement_end=f"{day.isoformat()}T23:00:00+00:00",
            quality_flags=("VENDOR_DERIVED",),
        )
        for offset in range(15)
        for day in (DAY - timedelta(days=14 - offset),)
    }


class StorageContractTests(unittest.TestCase):
    def test_selected_feature_ref_keeps_identity_not_observation_dictionary(self):
        source = nights()[DAY]
        ref = StoredFeatureRef(source.kind, source.day, source.fingerprint,
                               source.source_count, source.source_ids_hash,
                               source.measurement_start, source.measurement_end,
                               source.quality_flags)
        self.assertEqual(ref.fingerprint, source.fingerprint)
        self.assertEqual(ref.source_count, source.source_count)
        self.assertFalse(hasattr(ref, "values"))
        with self.assertRaises(FrozenInstanceError):
            ref.fingerprint = "changed"
        with self.assertRaises(ValueError):
            StoredFeatureRef("nightly", DAY, "", 0, "hash", None, None)

    def test_sleep_projection_covers_every_legacy_draft_field_and_ordered_lineage(self):
        active = nights()
        profile, revision = load_profile(None)
        canonical = calculate_sleep_core(adapt_sleep_input(DAY, active, profile, revision))
        legacy = calculate_sleep_day(DAY, active, profile)
        self.assertEqual(len(canonical), len(legacy), 3)
        for result, draft in zip(canonical, legacy, strict=True):
            with self.subTest(metric=draft.name):
                stored = to_persistable_sleep_result(result)
                for target_name, legacy_name in (
                    ("metric_name", "name"), ("day", "day"), ("value", "value"),
                    ("unit", "unit"), ("status", "status"),
                    ("algorithm_id", "algorithm_id"),
                    ("algorithm_version", "algorithm_version"),
                    ("source_type", "source_type"),
                    ("upstream_project", "upstream_project"),
                    ("upstream_commit", "upstream_commit"),
                    ("confidence", "confidence"),
                ):
                    self.assertEqual(getattr(stored, target_name), getattr(draft, legacy_name))
                self.assertEqual(stored.metadata, draft.metadata)
                self.assertEqual(len(stored.inputs), len(draft.inputs))
                self.assertEqual(tuple(ref.fingerprint for ref in stored.inputs),
                                 tuple(feature.fingerprint for feature in draft.inputs))
                for ref, feature in zip(stored.inputs, draft.inputs, strict=True):
                    self.assertEqual((ref.kind, ref.day, ref.fingerprint, ref.source_count,
                                      ref.source_ids_hash, ref.measurement_start,
                                      ref.measurement_end, ref.quality_flags),
                                     (feature.kind, feature.day, feature.fingerprint,
                                      feature.source_count, feature.source_ids_hash,
                                      feature.measurement_start, feature.measurement_end,
                                      feature.quality_flags))
                self.assertFalse(any(hasattr(stored, name) for name in
                                     ("result_id", "supersedes_result_id", "freshness_status")))

    def test_metadata_is_defensively_frozen_and_missing_differs_from_zero(self):
        metadata = {"components": {"duration": 0}, "history_count": None}
        result = PersistableMetricResult("sleep.score", DAY, None, "score", "CALIBRATING",
                                         "sleep.score_v1", "sleep-1", metadata, ())
        metadata["components"]["duration"] = 5
        self.assertEqual(result.metadata["components"]["duration"], 0)
        with self.assertRaises(TypeError):
            result.metadata["components"]["duration"] = 2
        with self.assertRaises(TypeError):
            result.metadata["history_count"] = 1
        zero = PersistableMetricResult("sleep.score", DAY, 0, "score", "VALID",
                                       "sleep.score_v1", "sleep-1", {}, ())
        self.assertIsNone(result.value)
        self.assertEqual(zero.value, 0)
        with self.assertRaises(FrozenInstanceError):
            zero.value = 5
        with self.assertRaises(TypeError):
            PersistableMetricResult("sleep.score", DAY, 0, "score", "VALID",
                                    "sleep.score_v1", "sleep-1", [], ())

    def test_write_context_and_post_write_identity_are_separate(self):
        context = ResultWriteContext("run-1", "profile-v1", "primary-v1", "HISTORICAL",
                                     "xiaomi-normalization-1", "0.5.0",
                                     "foundation-output-1", "foundation-gates-1")
        self.assertEqual(context.stored_freshness, "HISTORICAL")
        self.assertEqual((context.source_scope, context.release_channel),
                         ("primary", "production"))
        self.assertFalse(hasattr(context, "cleanup_obsolete"))
        self.assertFalse(hasattr(context, "as_of"))
        identity = ResultIdentity("sleep.score", DAY, "sleep.score_v1", "sleep-1",
                                  context.implementation_version, context.normalization_version,
                                  context.source_scope, context.profile_revision,
                                  context.source_policy_version, "digest")
        active = ActiveResult(3, identity, "FRESH", 2)
        reselection = WriteOutcome(True, False, False, active)
        self.assertTrue(reselection.changed)
        self.assertFalse(reselection.inserted)
        self.assertEqual(reselection.active.supersedes_result_id, 2)
        self.assertNotIn("run_id", {f.name for f in fields(ResultIdentity)})
        self.assertNotIn("source_policy_version", {f.name for f in fields(PersistableMetricResult)})

    def test_repository_uses_caller_session_and_explicit_clear_operation(self):
        self.assertEqual(list(inspect.signature(MetricResultRepository.persist).parameters),
                         ["self", "session", "result", "context"])
        self.assertEqual(list(inspect.signature(MetricResultRepository.get_active).parameters)[:4],
                         ["self", "session", "metric_name", "day"])
        self.assertEqual(list(inspect.signature(MetricResultRepository.clear_active).parameters)[:4],
                         ["self", "session", "day", "metric_names"])
        self.assertFalse(hasattr(MetricResultRepository, "commit"))
        self.assertEqual(list(inspect.signature(AnalyticsSessionFactory.begin).parameters),
                         ["self"])
        self.assertTrue(hasattr(AnalyticsSession, "commit"))
        self.assertTrue(hasattr(AnalyticsSession, "rollback"))

    def test_new_storage_contracts_and_projection_have_no_legacy_sql_or_clock_imports(self):
        for path in (ROOT / "src/mi_fitness_whooping/storage/contracts.py",
                     ROOT / "src/mi_fitness_whooping/integration/sleep/storage_contract_adapter.py"):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = {alias.name for node in ast.walk(tree)
                            if isinstance(node, ast.Import) for alias in node.names}
                imported.update(node.module for node in ast.walk(tree)
                                if isinstance(node, ast.ImportFrom) and node.module)
                self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                                     for name in imported))
                self.assertNotIn("sqlite3", imported)
                self.assertNotIn("time", imported)
                self.assertNotIn(".now(", source)
                self.assertNotIn(".utcnow(", source)
                self.assertNotIn(".execute(", source)
                self.assertNotIn("hashlib", imported)


if __name__ == "__main__":
    unittest.main()
