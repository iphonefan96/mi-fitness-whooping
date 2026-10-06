"""Synthetic differential tests against the immutable Legacy sleep calculation."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "Legacy"))

from analytics.algorithms.foundations import FeatureRecord  # noqa: E402
from analytics.algorithms.sleep import _target, calculate_sleep_day  # noqa: E402
from domain.sleep.contracts import (  # noqa: E402
    EffectiveSleepTarget, NightReference, SelectedNight, SleepCoreInput,
)
from src.analytics.sleep.core import calculate_sleep_core  # noqa: E402


DAY = date(2026, 1, 20)
DEFAULT_PROFILE = {"schema_version": 1, "values": []}


def night(day: date, **changes: object) -> FeatureRecord:
    values = {"tst_min": 480, "deep_min": 90, "rem_min": 90, "waso_min": 0,
              "awakening_durations_min": (), "bedtime_local_min": 1380,
              "stage_coverage": "COMPLETE"}
    values.update(changes)
    return FeatureRecord("nightly", day, values, f"night:{day.isoformat()}", 1,
                         "synthetic-source", None, None, ("SYNTHETIC",))


def history(day: date = DAY) -> dict[date, FeatureRecord]:
    return {day - timedelta(days=i): night(day - timedelta(days=i)) for i in range(14, -1, -1)}


def canonical(day: date, nights: dict[date, FeatureRecord], profile: dict = DEFAULT_PROFILE) -> SleepCoreInput:
    selected = []
    for night_day in sorted(nights):
        if not day - timedelta(days=14) <= night_day <= day:
            continue
        row = nights[night_day]
        value = row.values
        selected.append(SelectedNight(
            night_day,
            NightReference(row.day, row.fingerprint, row.source_count, row.source_ids_hash,
                           row.measurement_start, row.measurement_end, row.quality_flags),
            value.get("tst_min"), value.get("deep_min"), value.get("rem_min"),
            value.get("waso_min"),
            tuple(value["awakening_durations_min"]) if value.get("awakening_durations_min") is not None else None,
            value.get("bedtime_local_min"), value.get("stage_coverage") == "COMPLETE",
        ))
    # A missing current night returns before Legacy inspects profile targets.
    targets = () if day not in nights else tuple(
        EffectiveSleepTarget(d, *_target(profile, d))
        for d in (day - timedelta(days=i) for i in range(13, -1, -1))
    )
    return SleepCoreInput(day, tuple(selected), targets, "synthetic-profile-revision")


def observable_new(row) -> tuple:
    metadata = asdict(row.metadata)
    return (row.metric.value, row.day, row.value, row.unit, row.status.value,
            row.algorithm_id, row.algorithm_version, row.source_type,
            row.upstream_project, row.upstream_commit, row.confidence,
            metadata, tuple(asdict(ref) for ref in row.lineage))


def observable_legacy(row) -> tuple:
    return (row.name, row.day, row.value, row.unit, row.status, row.algorithm_id,
            row.algorithm_version, row.source_type, row.upstream_project,
            row.upstream_commit, row.confidence, row.metadata,
            tuple(asdict(ref) | {"day": ref.day, "fingerprint": ref.fingerprint}
                  for ref in row.inputs))


class SleepCoreDifferentialTests(unittest.TestCase):
    def assert_equivalent(self, day: date, nights: dict[date, FeatureRecord],
                          profile: dict = DEFAULT_PROFILE) -> tuple:
        old = calculate_sleep_day(day, nights, profile)
        new = calculate_sleep_core(canonical(day, nights, profile))
        self.assertEqual(len(new), len(old))
        for fresh, legacy in zip(new, old):
            # FeatureRecord has kind/values; NightReference intentionally omits them.
            old_observable = observable_legacy(legacy)
            new_observable = observable_new(fresh)
            self.assertEqual(new_observable[:-1], old_observable[:-1])
            self.assertEqual([r["fingerprint"] for r in new_observable[-1]],
                             [r["fingerprint"] for r in old_observable[-1]])
            self.assertEqual([r["day"] for r in new_observable[-1]],
                             [r["day"] for r in old_observable[-1]])
            for actual, expected in zip(new_observable[-1], old_observable[-1]):
                for field in ("source_count", "source_ids_hash", "measurement_start",
                              "measurement_end", "quality_flags"):
                    self.assertEqual(actual[field], expected[field])
        return new

    def test_happy_path_and_component_boundaries(self):
        base = history()
        self.assertEqual(self.assert_equivalent(DAY, base)[0].value, 100)
        for changes in ({"tst_min": 420}, {"tst_min": 540}, {"tst_min": 720},
                        {"deep_min": 0}, {"rem_min": 0}, {"bedtime_local_min": 60},
                        {"bedtime_local_min": 1395}, {"bedtime_local_min": 1396},
                        {"waso_min": 20}, {"waso_min": 20.01},
                        {"waso_min": 80, "awakening_durations_min": (10, 10, 10, 10)},
                        {"awakening_durations_min": (5, 5)}):
            with self.subTest(changes=changes):
                self.assert_equivalent(DAY, base | {DAY: night(DAY, **changes)})

    def test_score_calibration_missing_and_invalid_branch_order(self):
        base = history()
        for changes in ({"tst_min": 0}, {"tst_min": None}, {"deep_min": None},
                        {"rem_min": None}, {"waso_min": None},
                        {"bedtime_local_min": None}, {"bedtime_local_min": 1440},
                        {"awakening_durations_min": None},
                        {"awakening_durations_min": (None,)},
                        {"stage_coverage": "UNKNOWN"},
                        {"deep_min": 400}, {"tst_min": -1}):
            with self.subTest(changes=changes):
                self.assert_equivalent(DAY, base | {DAY: night(DAY, **changes)})
        short = {DAY: night(DAY)}
        for i in range(1, 5):
            short[DAY - timedelta(days=i)] = night(DAY - timedelta(days=i))
        self.assertEqual(self.assert_equivalent(DAY, short)[0].status.value, "CALIBRATING")
        short[DAY - timedelta(days=14)] = night(DAY - timedelta(days=14))
        self.assertEqual(self.assert_equivalent(DAY, short)[0].status.value, "VALID")

    def test_need_default_effective_dates_and_no_current_night(self):
        self.assertEqual(self.assert_equivalent(DAY, history())[1].value, 480.0)
        profile = {"schema_version": 1, "values": [
            {"field": "sleep_target_min", "value": 300,
             "effective_from": (DAY - timedelta(days=13)).isoformat(),
             "effective_to": (DAY - timedelta(days=13)).isoformat()},
            {"field": "sleep_target_min", "value": 720,
             "effective_from": DAY.isoformat()},
        ]}
        self.assertEqual(self.assert_equivalent(DAY, history(), profile)[1].value, 720.0)
        self.assertEqual(self.assert_equivalent(DAY - timedelta(days=13), history(), profile)[1].value, 300.0)
        self.assertEqual(self.assert_equivalent(DAY - timedelta(days=1), history(), profile)[1].value, 480.0)
        without_today = history()
        del without_today[DAY]
        self.assertEqual(self.assert_equivalent(DAY, without_today), ())
        # Invalid profile state is rejected by the resolver before pure calculation.
        invalid = {"schema_version": 1, "values": [{"field": "sleep_target_min",
                   "value": 299, "effective_from": DAY.isoformat()}]}
        self.assertEqual(self.assert_equivalent(DAY, without_today, invalid), ())
        with self.assertRaisesRegex(ValueError, "300..720"):
            calculate_sleep_day(DAY, history(), invalid)
        with self.assertRaisesRegex(ValueError, "300..720"):
            canonical(DAY, history(), invalid)

    def test_debt_history_gap_and_signed_balance(self):
        base = history()
        for missing in ({0, 3, 6, 9}, {0, 2, 4, 6, 8}, {3, 4}, {3, 4, 5}):
            with self.subTest(missing=missing):
                altered = {d: row for d, row in base.items()
                           if d not in {DAY - timedelta(days=13 - i) for i in missing}}
                self.assert_equivalent(DAY, altered)
        for tst in (0, None, 300, 420, 480, 600, -1):
            with self.subTest(tst=tst):
                self.assert_equivalent(DAY, base | {DAY: night(DAY, tst_min=tst)})
        self.assert_equivalent(DAY, base | {DAY: night(DAY, stage_coverage="UNKNOWN")})
        surplus = {d: night(d, tst_min=600) for d in base}
        self.assertEqual(self.assert_equivalent(DAY, surplus)[2].metadata.signed_balance_min, 1680.0)
        partial = {"schema_version": 1, "values": [{"field": "sleep_target_min", "value": 450,
                   "effective_from": (DAY - timedelta(days=6)).isoformat()}]}
        self.assert_equivalent(DAY, base, partial)
        changed = DAY - timedelta(days=3)
        before = self.assert_equivalent(DAY, base)[2]
        after = self.assert_equivalent(DAY, base | {changed: night(changed, tst_min=300)})[2]
        self.assertNotEqual(before.metadata.signed_balance_min, after.metadata.signed_balance_min)

    def test_determinism_ordered_lineage_and_history_window(self):
        base = history()
        base[DAY + timedelta(days=1)] = night(DAY + timedelta(days=1), tst_min=1)
        base[DAY - timedelta(days=15)] = night(DAY - timedelta(days=15), tst_min=1)
        first = self.assert_equivalent(DAY, base)
        self.assertEqual(first, calculate_sleep_core(canonical(DAY, base)))
        self.assertEqual(first[0].lineage[0].day, DAY)
        self.assertEqual(tuple(r.day for r in first[2].lineage),
                         tuple(DAY - timedelta(days=i) for i in range(13, -1, -1)))
        changed = replace(base[DAY - timedelta(days=2)], fingerprint="revised-night")
        revised = self.assert_equivalent(DAY, base | {changed.day: changed})
        self.assertNotEqual(first[2].lineage, revised[2].lineage)

    def test_pure_module_has_no_forbidden_dependencies_or_clock_reads(self):
        path = ROOT / "src" / "analytics" / "sleep" / "core.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported.update(node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module)
        forbidden = {"sqlite3", "Legacy", "storage", "presentation", "orchestration",
                     "argparse", "pathlib", "os", "time"}
        self.assertFalse({name.split(".")[0] for name in imported} & forbidden)
        self.assertLessEqual(imported,
                             {"__future__", "math", "statistics", "datetime", "domain.sleep.contracts"})
        self.assertFalse(any("Legacy" in name for name in imported))
        self.assertNotIn(".now(", source)
        self.assertNotIn(".utcnow(", source)


if __name__ == "__main__":
    unittest.main()
