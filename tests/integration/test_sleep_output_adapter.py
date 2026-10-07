"""Phase 4B draft, fingerprint and persistence compatibility with Legacy."""

from __future__ import annotations

import ast
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

from analytics.algorithms.foundations import FeatureRecord, MetricDraft  # noqa: E402
from analytics.algorithms.sleep import calculate_sleep_day  # noqa: E402
from analytics.storage.db import connect, migrate, put_result  # noqa: E402
from mi_fitness_whooping.integration.sleep.input_adapter import adapt_sleep_input  # noqa: E402
from reference_legacy_output import adapt_sleep_result  # noqa: E402
from mi_fitness_whooping.analytics.sleep.core import calculate_sleep_core  # noqa: E402


DAY = date(2026, 1, 20)
PROFILE_REVISION = "synthetic-profile-v1"
DEFAULT_PROFILE = {"schema_version": 1, "values": []}
STORED_FRESHNESS = "HISTORICAL"


def night(day: date, **changes: object) -> FeatureRecord:
    values = {"tst_min": 480, "deep_min": 90, "rem_min": 90, "waso_min": 0,
              "awakening_durations_min": [], "bedtime_local_min": 1380,
              "stage_coverage": "COMPLETE"}
    values.update(changes)
    return FeatureRecord(
        "nightly", day, values, f"feature:{day.isoformat()}", 5,
        f"source-hash:{day.isoformat()}",
        f"{day.isoformat()}T22:00:00+00:00",
        f"{day.isoformat()}T23:00:00+00:00", ("SYNTHETIC",),
    )


def history() -> dict[date, FeatureRecord]:
    return {DAY - timedelta(days=i): night(DAY - timedelta(days=i))
            for i in range(14, -1, -1)}


def profile_target(value: int, start: date) -> dict:
    return {"schema_version": 1, "values": [{"field": "sleep_target_min",
            "value": value, "effective_from": start.isoformat()}]}


def paired_drafts(nights: dict[date, FeatureRecord], profile: dict = DEFAULT_PROFILE):
    legacy = calculate_sleep_day(DAY, nights, profile)
    canonical_input = adapt_sleep_input(DAY, nights, profile, PROFILE_REVISION)
    results = calculate_sleep_core(canonical_input)
    adapted = [adapt_sleep_result(result, nights) for result in results]
    return legacy, adapted


def persisted_rows(db):
    return {row["metric_name"]: dict(row) for row in db.execute(
        "SELECT * FROM derived_metric_results ORDER BY metric_name, result_id")}


def active_rows(db):
    return [tuple(row) for row in db.execute(
        "SELECT metric_name,metric_date,source_scope,release_channel,result_id "
        "FROM active_metric_selection ORDER BY metric_name")]


class OutputAdapterUnitTests(unittest.TestCase):
    def test_exact_draft_fields_metadata_and_original_lineage(self):
        cases = [
            ("valid_default", history(), DEFAULT_PROFILE),
            ("calibrating", {DAY: night(DAY)}, DEFAULT_PROFILE),
            ("insufficient", history() | {DAY: night(DAY, rem_min=None)}, DEFAULT_PROFILE),
            ("configured", history(), profile_target(450, DAY - timedelta(days=13))),
            ("partial_targets", history(), profile_target(450, DAY - timedelta(days=6))),
            ("debt_gap", {d: row for d, row in history().items()
                          if d not in {DAY - timedelta(days=i) for i in (3, 4, 5)}}, DEFAULT_PROFILE),
        ]
        for label, nights, profile in cases:
            with self.subTest(label=label):
                old, new = paired_drafts(nights, profile)
                self.assertEqual(new, old)
                self.assertEqual([type(draft) for draft in new], [MetricDraft] * 3)
                for original, adapted in zip(old, new):
                    self.assertEqual(len(original.inputs), len(adapted.inputs))
                    for prior, current in zip(original.inputs, adapted.inputs):
                        self.assertIs(current, prior)
                        self.assertIs(current, nights[current.day])

    def test_metadata_keeps_none_nested_components_and_numeric_types(self):
        old, new = paired_drafts(history())
        self.assertEqual(new[0].metadata, old[0].metadata)
        self.assertEqual(set(new[0].metadata["components"]),
                         {"duration", "stages", "consistency", "interruptions"})
        self.assertIs(type(new[0].metadata["components"]["duration"]), int)
        self.assertIs(type(new[1].value), float)
        self.assertIs(type(new[2].metadata["signed_balance_min"]), float)
        _, calibrating = paired_drafts({DAY: night(DAY)})
        self.assertIn("components", calibrating[0].metadata)
        self.assertIsNone(calibrating[0].metadata["components"])
        self.assertIn("signed_balance_min", calibrating[2].metadata)
        self.assertIsNone(calibrating[2].metadata["signed_balance_min"])

    def test_mismatched_or_missing_original_lineage_fails_closed(self):
        nights = history()
        result = calculate_sleep_core(adapt_sleep_input(DAY, nights, DEFAULT_PROFILE, PROFILE_REVISION))[0]
        with self.assertRaisesRegex(ValueError, "lineage"):
            adapt_sleep_result(result, {d: row for d, row in nights.items() if d != DAY})
        replaced = replace(nights[DAY], fingerprint="different")
        with self.assertRaisesRegex(ValueError, "lineage"):
            adapt_sleep_result(result, nights | {DAY: replaced})
        different_source = replace(nights[DAY], source_ids_hash="different")
        with self.assertRaisesRegex(ValueError, "lineage"):
            adapt_sleep_result(result, nights | {DAY: different_source})
        wrong_kind = replace(nights[DAY], kind="daily")
        with self.assertRaisesRegex(ValueError, "lineage"):
            adapt_sleep_result(result, nights | {DAY: wrong_kind})

    def test_output_adapter_has_only_compatibility_imports_and_no_clock(self):
        path = ROOT / "tests" / "integration" / "reference_legacy_output.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported.update(node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module)
        self.assertLessEqual(imported, {"__future__", "dataclasses", "datetime", "typing",
                                        "analytics.algorithms.foundations",
                                        "mi_fitness_whooping.domain.sleep.contracts"})
        self.assertNotIn(".now(", source)
        self.assertNotIn(".utcnow(", source)


class FingerprintCompatibilityTests(unittest.TestCase):
    def test_real_storage_fingerprints_match_for_all_three_metrics_and_statuses(self):
        cases = [
            ("valid_default", history(), DEFAULT_PROFILE),
            ("configured", history(), profile_target(450, DAY - timedelta(days=13))),
            ("partial_targets", history(), profile_target(450, DAY - timedelta(days=6))),
            ("calibrating", {DAY: night(DAY)}, DEFAULT_PROFILE),
            ("insufficient", history() | {DAY: night(DAY, rem_min=None)}, DEFAULT_PROFILE),
            ("invalid", history() | {DAY: night(DAY, tst_min=0)}, DEFAULT_PROFILE),
            ("debt_gap", {d: row for d, row in history().items()
                          if d not in {DAY - timedelta(days=i) for i in (3, 4, 5)}}, DEFAULT_PROFILE),
        ]
        for label, nights, profile in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                old, new = paired_drafts(nights, profile)
                databases = []
                for name, drafts in (("legacy", old), ("adapted", new)):
                    db = connect(Path(directory) / f"{name}.sqlite")
                    migrate(db)
                    for draft in drafts:
                        self.assertTrue(put_result(db, draft, run_id="run-a",
                                                   profile_revision=PROFILE_REVISION,
                                                   freshness_status=STORED_FRESHNESS))
                    databases.append(db)
                try:
                    legacy_rows, adapted_rows = map(persisted_rows, databases)
                    self.assertEqual(set(legacy_rows),
                                     {"sleep.score", "sleep.need_min", "sleep.debt_min"})
                    for metric in legacy_rows:
                        self.assertEqual(adapted_rows[metric]["input_fingerprint"],
                                         legacy_rows[metric]["input_fingerprint"])
                        for field in ("value", "unit", "status", "algorithm_id",
                                      "algorithm_version", "source_type", "upstream_project",
                                      "upstream_commit", "metadata_json", "source_signals_json",
                                      "input_coverage_json", "quality_flags_json",
                                      "measurement_start", "measurement_end"):
                            self.assertEqual(adapted_rows[metric][field], legacy_rows[metric][field],
                                             f"{label}/{metric}/{field}")
                finally:
                    for db in databases:
                        db.close()


class PersistenceCompatibilityTests(unittest.TestCase):
    def test_insert_unchanged_rerun_revision_and_active_selection(self):
        original = history()
        correction_day = DAY - timedelta(days=3)
        corrected = original | {correction_day: replace(
            night(correction_day, tst_min=300), fingerprint="corrected-feature")}
        with tempfile.TemporaryDirectory() as directory:
            databases = []
            snapshots = []
            for name, choose in (("legacy", lambda old, new: old),
                                 ("adapted", lambda old, new: new)):
                db = connect(Path(directory) / f"{name}.sqlite")
                migrate(db)
                before = choose(*paired_drafts(original))
                after = choose(*paired_drafts(corrected))
                self.assertEqual([put_result(db, draft, run_id="run-1",
                                             profile_revision=PROFILE_REVISION,
                                             freshness_status=STORED_FRESHNESS)
                                  for draft in before], [True] * 3)
                first_selection = active_rows(db)
                self.assertEqual([put_result(db, draft, run_id="run-2",
                                             profile_revision=PROFILE_REVISION,
                                             freshness_status=STORED_FRESHNESS)
                                  for draft in before], [False] * 3)
                self.assertEqual(active_rows(db), first_selection)
                changes = [put_result(db, draft, run_id="run-3",
                                      profile_revision=PROFILE_REVISION,
                                      freshness_status=STORED_FRESHNESS)
                           for draft in after]
                self.assertEqual(changes, [True, False, True])
                snapshots.append((first_selection, active_rows(db), [dict(r) for r in db.execute(
                    "SELECT metric_name,input_fingerprint,supersedes_result_id,run_id "
                    "FROM derived_metric_results ORDER BY result_id")]))
                databases.append(db)
            try:
                self.assertEqual(snapshots[0], snapshots[1])
                self.assertEqual(len(snapshots[0][2]), 5)
            finally:
                for db in databases:
                    db.close()

    def test_stored_freshness_is_supplied_externally_and_reselection_is_unchanged(self):
        old, new = paired_drafts(history())
        with tempfile.TemporaryDirectory() as directory:
            results = []
            for name, draft in (("legacy", old[1]), ("adapted", new[1])):
                db = connect(Path(directory) / f"{name}.sqlite")
                try:
                    migrate(db)
                    self.assertTrue(put_result(db, draft, run_id="run-1",
                                               profile_revision=PROFILE_REVISION,
                                               freshness_status="FRESH"))
                    first = db.execute("SELECT result_id,input_fingerprint,freshness_status "
                                       "FROM derived_metric_results").fetchone()
                    self.assertTrue(put_result(db, draft, run_id="run-2",
                                               profile_revision=PROFILE_REVISION,
                                               freshness_status="STALE"))
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0], 1)
                    current = db.execute("SELECT result_id,input_fingerprint,freshness_status "
                                         "FROM derived_metric_results").fetchone()
                    self.assertEqual(tuple(current), tuple(first))
                    results.append(tuple(current))
                finally:
                    db.close()
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
