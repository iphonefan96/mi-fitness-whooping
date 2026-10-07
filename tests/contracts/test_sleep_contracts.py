"""Contract-only tests; no sleep formula or persistence implementation is imported."""

from __future__ import annotations

import ast
import json
import unittest
from dataclasses import asdict, fields
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from pathlib import Path


SRC = Path(__file__).resolve().parents[2] / "src"

from mi_fitness_whooping.domain.sleep.contracts import (  # noqa: E402
    CalculationStatus,
    DebtMetadata,
    EffectiveSleepTarget,
    NeedMetadata,
    NightReference,
    ScoreComponents,
    ScoreMetadata,
    SelectedNight,
    SleepCoreInput,
    SleepMetric,
    SleepMetricResult,
)


DAY = date(2026, 1, 14)


def reference(day: date, tag: str = "a") -> NightReference:
    return NightReference(day, f"feature:{day}:{tag}", 4, f"source-hash:{tag}",
                          "2026-01-13T22:00:00+00:00", "2026-01-14T06:00:00+00:00",
                          ("VENDOR_DERIVED",))


def selected(day: date, **changes: object) -> SelectedNight:
    values = dict(day=day, lineage=reference(day), tst_min=480, deep_min=90,
                  rem_min=90, waso_min=0, awakening_durations_min=(),
                  bedtime_local_min=1380, stage_complete=True)
    values.update(changes)
    return SelectedNight(**values)


def targets(day: date, *, default: bool = True) -> tuple[EffectiveSleepTarget, ...]:
    return tuple(EffectiveSleepTarget(day - timedelta(days=i), 480 if default else 450,
                                      default)
                 for i in range(13, -1, -1))


def core_input(day: date = DAY, selected_nights=()) -> SleepCoreInput:
    return SleepCoreInput(day, tuple(selected_nights), targets(day), "profile-revision-a")


class SleepInputContractTests(unittest.TestCase):
    def test_missing_zero_and_invalid_observations_remain_distinct(self):
        missing = selected(DAY, tst_min=None, rem_min=None, waso_min=None,
                           awakening_durations_min=None, bedtime_local_min=None)
        measured_zero = selected(DAY, tst_min=0, rem_min=0, waso_min=0,
                                 awakening_durations_min=(), bedtime_local_min=0)
        invalid = selected(DAY, tst_min=-1)
        self.assertIsNone(missing.tst_min)
        self.assertEqual(measured_zero.tst_min, 0)
        self.assertNotEqual(missing, measured_zero)
        self.assertEqual(invalid.tst_min, -1)  # Phase 3 must apply Legacy's INVALID gate.

    def test_incomplete_stage_and_default_targets_are_explicit(self):
        incomplete = selected(DAY, stage_complete=False)
        self.assertFalse(incomplete.stage_complete)
        inp = core_input(selected_nights=(incomplete,))
        self.assertEqual(len(inp.targets), 14)
        self.assertEqual(inp.targets[-1], EffectiveSleepTarget(DAY, 480, True))
        self.assertEqual(inp.selected_nights[0].lineage.quality_flags, ("VENDOR_DERIVED",))
        self.assertEqual(core_input().selected_nights, ())  # No current main night.
        self.assertEqual(SleepCoreInput(DAY, (), (), "profile-revision-a").targets, ())

    def test_night_history_bounds_order_and_unique_dates(self):
        old = selected(DAY - timedelta(days=14))  # Score's oldest prior bedtime.
        current = selected(DAY)
        inp = core_input(selected_nights=(old, current))
        self.assertEqual(tuple(n.day for n in inp.selected_nights),
                         (DAY - timedelta(days=14), DAY))
        with self.assertRaisesRegex(ValueError, "ascending"):
            core_input(selected_nights=(current, old))
        with self.assertRaisesRegex(ValueError, "unique"):
            core_input(selected_nights=(current, current))
        with self.assertRaisesRegex(ValueError, "outside"):
            core_input(selected_nights=(selected(DAY - timedelta(days=15)),))
        with self.assertRaisesRegex(ValueError, "ordered 14-night"):
            SleepCoreInput(DAY, (current,), targets(DAY)[:-1], "profile-revision-a")

    def test_target_and_reference_validation_preserve_reproducibility(self):
        for value in (299, 721, float("nan"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EffectiveSleepTarget(DAY, value, False)
        with self.assertRaisesRegex(ValueError, "480"):
            EffectiveSleepTarget(DAY, 450, True)
        with self.assertRaisesRegex(ValueError, "lineage"):
            selected(DAY, lineage=reference(DAY - timedelta(days=1)))
        with self.assertRaisesRegex(ValueError, "profile_revision"):
            SleepCoreInput(DAY, (), targets(DAY), "")
        with self.assertRaisesRegex(TypeError, "immutable"):
            selected(DAY, awakening_durations_min=[1, 2])

    def test_input_equality_and_primitive_representation_are_deterministic(self):
        one = core_input(selected_nights=(selected(DAY),))
        two = core_input(selected_nights=(selected(DAY),))
        self.assertEqual(one, two)
        self.assertEqual(json.dumps(asdict(one), sort_keys=True, default=str),
                         json.dumps(asdict(two), sort_keys=True, default=str))
        self.assertNotIn("as_of", asdict(one))
        with self.assertRaises(FrozenInstanceError):
            one.profile_revision = "changed"


class SleepOutputContractTests(unittest.TestCase):
    def test_all_metric_identities_and_calculation_statuses_are_supported(self):
        self.assertEqual({m.value for m in SleepMetric},
                         {"sleep.score", "sleep.need_min", "sleep.debt_min"})
        self.assertEqual({s.value for s in CalculationStatus},
                         {"VALID", "REDUCED", "CALIBRATING",
                          "INSUFFICIENT_DATA", "INVALID"})
        for status in (CalculationStatus.CALIBRATING,
                       CalculationStatus.INSUFFICIENT_DATA, CalculationStatus.INVALID):
            with self.subTest(status=status):
                result = SleepMetricResult(
                    SleepMetric.SCORE, DAY, None, "score", status,
                    "sleep.open_wearables_four_pillar_v1", "sleep-1",
                    ScoreMetadata(None, None, 4, 5, 14), (reference(DAY),),
                )
                self.assertEqual(result.status.value, status.value)

    def test_results_preserve_units_metadata_and_ordered_lineage(self):
        current = reference(DAY)
        prior = reference(DAY - timedelta(days=1))
        score = SleepMetricResult(
            SleepMetric.SCORE, DAY, 100, "score", CalculationStatus.VALID,
            "sleep.open_wearables_four_pillar_v1", "sleep-1",
            ScoreMetadata("FULL", ScoreComponents(100, 100, 100, 100), 5, 5, 14),
            (current, prior), "Open Wearables", "pinned-commit",
        )
        need = SleepMetricResult(
            SleepMetric.NEED_MIN, DAY, 480, "min", CalculationStatus.REDUCED,
            "sleep.fixed_target_v1", "sleep-1",
            NeedMetadata("PROVISIONAL_DEFAULT", True, False), (current,),
            "Vitals", "pinned-commit",
        )
        debt = SleepMetricResult(
            SleepMetric.DEBT_MIN, DAY, None, "min", CalculationStatus.CALIBRATING,
            "sleep.signed_14_calendar_night_ledger_v1", "sleep-1",
            DebtMetadata("PROVISIONAL_DEFAULT", True, None, 9, 10, 3, 14),
            (prior, current),
        )
        self.assertEqual(tuple(r.metric.value for r in (score, need, debt)),
                         ("sleep.score", "sleep.need_min", "sleep.debt_min"))
        self.assertEqual(score.lineage, (current, prior))
        self.assertEqual(debt.lineage, (prior, current))
        self.assertEqual(need.metadata.physiological_estimate, False)
        self.assertIsNone(debt.value)
        self.assertEqual(asdict(score)["metadata"]["components"]["duration"], 100)
        self.assertEqual(json.dumps(asdict(score), sort_keys=True, default=str),
                         json.dumps(asdict(score), sort_keys=True, default=str))

    def test_identity_cannot_be_arbitrary_or_mismatched(self):
        valid = dict(metric=SleepMetric.NEED_MIN, day=DAY, value=480, unit="min",
                     status=CalculationStatus.REDUCED, algorithm_id="sleep.fixed_target_v1",
                     algorithm_version="sleep-1",
                     metadata=NeedMetadata("PROVISIONAL_DEFAULT", True, False),
                     lineage=(reference(DAY),))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            SleepMetricResult(**(valid | {"metric": "sleep.other"}))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            SleepMetricResult(**(valid | {"status": "FRESH"}))
        with self.assertRaisesRegex(ValueError, "metadata or unit"):
            SleepMetricResult(**(valid | {"unit": "score"}))
        with self.assertRaisesRegex(ValueError, "metadata or unit"):
            SleepMetricResult(**(valid | {"metadata": ScoreMetadata(None, None, 0, 5, 14)}))
        with self.assertRaisesRegex(ValueError, "status does not match"):
            SleepMetricResult(**(valid | {"status": CalculationStatus.INVALID}))
        with self.assertRaisesRegex(ValueError, "value and calculation status"):
            SleepMetricResult(**(valid | {"value": None}))
        with self.assertRaisesRegex(ValueError, "outside Sleep Core range"):
            SleepMetricResult(**(valid | {"value": 721}))
        with self.assertRaisesRegex(ValueError, "value and calculation status"):
            SleepMetricResult(**(valid | {"metric": SleepMetric.DEBT_MIN,
                                        "metadata": DebtMetadata("PROVISIONAL_DEFAULT", True,
                                                                 None, 9, 10, 3, 14),
                                        "status": CalculationStatus.CALIBRATING}))

    def test_persistence_freshness_and_clock_fields_are_absent(self):
        names = {field.name for field in fields(SleepMetricResult)}
        self.assertFalse(names & {"result_id", "supersedes_result_id", "active_selection",
                                  "freshness_status", "as_of", "run_id", "db"})
        self.assertFalse({field.name for field in fields(SleepCoreInput)} &
                         {"as_of", "now", "freshness_status", "db_path"})

    def test_contract_module_has_no_forbidden_dependencies(self):
        path = SRC / "mi_fitness_whooping" / "domain" / "sleep" / "contracts.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported.update(node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module)
        forbidden = {"sqlite3", "Legacy", "analytics", "storage", "orchestration",
                     "presentation", "argparse"}
        self.assertFalse({name.split(".")[0] for name in imported} & forbidden)
        self.assertNotIn(".now(", path.read_text(encoding="utf-8"))
        self.assertNotIn(".utcnow(", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
