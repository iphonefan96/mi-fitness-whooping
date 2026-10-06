"""Synthetic Phase 4A input adapter contracts against immutable Legacy records."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "Legacy"))

from analytics.algorithms.foundations import FeatureRecord  # noqa: E402
from analytics.algorithms.sleep import _target as legacy_target  # noqa: E402
from analytics.algorithms.sleep import calculate_sleep_day  # noqa: E402
from domain.sleep.contracts import SleepCoreInput  # noqa: E402
from integration.sleep.input_adapter import adapt_sleep_input  # noqa: E402


DAY = date(2026, 1, 20)
PROFILE = {"schema_version": 1, "values": []}


def night(day: date, **changes: object) -> FeatureRecord:
    values = {"tst_min": 480, "deep_min": 90, "rem_min": 90, "waso_min": 0,
              "awakening_durations_min": [3.0], "bedtime_local_min": 1380,
              "stage_coverage": "COMPLETE", "extra_vitals_field": 42}
    values.update(changes)
    return FeatureRecord("nightly", day, values, f"feature:{day.isoformat()}", 7,
                         f"source-hash:{day.isoformat()}",
                         f"{day.isoformat()}T22:00:00+00:00",
                         f"{day.isoformat()}T23:00:00+00:00", ("SYNTHETIC",))


def profile_target(value: object, begin: date, end: date | None = None) -> dict:
    entry = {"field": "sleep_target_min", "value": value,
             "effective_from": begin.isoformat()}
    if end is not None:
        entry["effective_to"] = end.isoformat()
    return {"schema_version": 1, "values": [entry]}


class SleepInputAdapterTests(unittest.TestCase):
    def test_current_night_bounded_history_and_ordered_references(self):
        rows = {DAY - timedelta(days=i): night(DAY - timedelta(days=i))
                for i in range(-1, 16)}  # Future and day-15 excluded.
        adapted = adapt_sleep_input(DAY, rows, PROFILE, "profile-revision-a")
        self.assertIsInstance(adapted, SleepCoreInput)
        expected_days = tuple(DAY - timedelta(days=i) for i in range(14, -1, -1))
        self.assertEqual(tuple(n.day for n in adapted.selected_nights), expected_days)
        self.assertEqual(tuple(n.lineage.fingerprint for n in adapted.selected_nights),
                         tuple(rows[d].fingerprint for d in expected_days))
        self.assertEqual(tuple(t.day for t in adapted.targets), expected_days[1:])
        self.assertEqual(adapted.profile_revision, "profile-revision-a")
        for selected in adapted.selected_nights:
            original = rows[selected.day]
            self.assertEqual(selected.lineage.source_count, original.source_count)
            self.assertEqual(selected.lineage.source_ids_hash, original.source_ids_hash)
            self.assertEqual(selected.lineage.measurement_start, original.measurement_start)
            self.assertEqual(selected.lineage.measurement_end, original.measurement_end)
            self.assertEqual(selected.lineage.quality_flags, original.quality_flags)

    def test_no_current_night_returns_before_profile_or_history_inspection(self):
        malformed_prior = object()
        rows = {DAY - timedelta(days=1): malformed_prior}
        adapted = adapt_sleep_input(DAY, rows, {}, "profile-revision-a")
        self.assertEqual(adapted, SleepCoreInput(DAY, (), (), "profile-revision-a"))
        self.assertEqual(calculate_sleep_day(DAY, rows, {}), [])

    def test_missing_zero_invalid_values_and_stage_coverage_are_preserved(self):
        current = night(DAY, tst_min=0, deep_min=None, rem_min=-1,
                        waso_min=0, awakening_durations_min=None,
                        bedtime_local_min=None, stage_coverage="UNKNOWN")
        adapted = adapt_sleep_input(DAY, {DAY: current}, PROFILE, "revision")
        selected = adapted.selected_nights[0]
        self.assertEqual(selected.tst_min, 0)
        self.assertIsNone(selected.deep_min)
        self.assertEqual(selected.rem_min, -1)
        self.assertEqual(selected.waso_min, 0)
        self.assertIsNone(selected.awakening_durations_min)
        self.assertIsNone(selected.bedtime_local_min)
        self.assertFalse(selected.stage_complete)
        complete = adapt_sleep_input(DAY, {DAY: night(DAY)}, PROFILE, "revision")
        self.assertEqual(complete.selected_nights[0].awakening_durations_min, (3.0,))
        self.assertTrue(complete.selected_nights[0].stage_complete)
        self.assertNotIn("extra_vitals_field", asdict(complete.selected_nights[0]))

    def test_bedtime_and_sleep_history_remain_distinct_for_calculation(self):
        rows = {DAY - timedelta(days=i): night(DAY - timedelta(days=i)) for i in range(15)}
        rows[DAY - timedelta(days=2)] = night(DAY - timedelta(days=2), bedtime_local_min=None)
        rows[DAY - timedelta(days=3)] = night(DAY - timedelta(days=3), tst_min=0)
        adapted = adapt_sleep_input(DAY, rows, PROFILE, "revision")
        by_day = {n.day: n for n in adapted.selected_nights}
        self.assertIsNone(by_day[DAY - timedelta(days=2)].bedtime_local_min)
        self.assertEqual(by_day[DAY - timedelta(days=3)].tst_min, 0)
        self.assertEqual(tuple(n.day for n in adapted.selected_nights),
                         tuple(DAY - timedelta(days=i) for i in range(14, -1, -1)))
        old = calculate_sleep_day(DAY, rows, PROFILE)
        score_inputs = next(r.inputs for r in old if r.name == "sleep.score")
        debt_inputs = next(r.inputs for r in old if r.name == "sleep.debt_min")
        self.assertNotIn(DAY - timedelta(days=2), [r.day for r in score_inputs])
        self.assertNotIn(DAY - timedelta(days=3), [r.day for r in debt_inputs])
        # Selection for the two metrics stays in pure Sleep Core, not this adapter.
        self.assertIn(DAY - timedelta(days=2), by_day)
        self.assertIn(DAY - timedelta(days=3), by_day)

    def test_effective_dated_targets_and_fallback_have_legacy_float_shape(self):
        start = DAY - timedelta(days=13)
        profile = {"schema_version": 1, "values": [
            {"field": "sleep_target_min", "value": 300,
             "effective_from": start.isoformat(), "effective_to": start.isoformat()},
            {"field": "sleep_target_min", "value": 720,
             "effective_from": DAY.isoformat()},
        ]}
        adapted = adapt_sleep_input(DAY, {DAY: night(DAY)}, profile, "rev-123")
        self.assertEqual(adapted.profile_revision, "rev-123")
        self.assertEqual((adapted.targets[0].minutes, adapted.targets[0].is_default), (300.0, False))
        self.assertEqual((adapted.targets[1].minutes, adapted.targets[1].is_default), (480.0, True))
        self.assertEqual((adapted.targets[-1].minutes, adapted.targets[-1].is_default), (720.0, False))
        for target in adapted.targets:
            self.assertIs(type(target.minutes), float)
            self.assertEqual((target.minutes, target.is_default), legacy_target(profile, target.day))
        old_need = next(r for r in calculate_sleep_day(DAY, {DAY: night(DAY)}, profile)
                        if r.name == "sleep.need_min")
        self.assertIs(type(old_need.value), float)
        self.assertIs(type(adapted.targets[-1].minutes), type(old_need.value))

    def test_invalid_target_rejection_matches_legacy(self):
        for invalid in (299, 721, True, float("nan"), "480"):
            with self.subTest(invalid=invalid):
                profile = profile_target(invalid, DAY)
                with self.assertRaisesRegex(ValueError, "300..720"):
                    adapt_sleep_input(DAY, {DAY: night(DAY)}, profile, "revision")
                with self.assertRaisesRegex(ValueError, "300..720"):
                    calculate_sleep_day(DAY, {DAY: night(DAY)}, profile)

    def test_current_target_is_checked_before_history(self):
        profile = profile_target(299, DAY)
        rows = {DAY: night(DAY), DAY - timedelta(days=1): object()}
        with self.assertRaisesRegex(ValueError, "300..720"):
            adapt_sleep_input(DAY, rows, profile, "revision")

    def test_deterministic_output_from_equivalent_inputs(self):
        row = night(DAY)
        one = adapt_sleep_input(DAY, {DAY: row}, PROFILE, "revision")
        two = adapt_sleep_input(DAY, {DAY: row}, PROFILE, "revision")
        self.assertEqual(one, two)
        self.assertEqual(asdict(one), asdict(two))

    def test_adapter_imports_only_domain_and_standard_library(self):
        source = (ROOT / "src" / "integration" / "sleep" / "input_adapter.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported.update(node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module)
        self.assertLessEqual(imported, {"__future__", "math", "datetime", "typing",
                                        "domain.sleep.contracts"})
        self.assertNotIn(".now(", source)
        self.assertNotIn(".utcnow(", source)


if __name__ == "__main__":
    unittest.main()
