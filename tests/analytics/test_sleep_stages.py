"""Sleep stage metrics and regularity: synthetic characterization against Legacy."""

from __future__ import annotations

import ast
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Legacy"))

from analytics.algorithms import foundations as legacy  # noqa: E402
from analytics.algorithms.foundations import FeatureRecord  # noqa: E402
from mi_fitness_whooping.analytics.sleep import stages  # noqa: E402
from mi_fitness_whooping.integration.sleep.stages_adapter import stages_night  # noqa: E402


START = date(2026, 3, 1)
DAYS = 60
STAGE_NAMES = {"sleep.time_in_bed_min", "sleep.total_sleep_time_min", "sleep.awake_min",
               "sleep.light_min", "sleep.deep_min", "sleep.rem_min", "sleep.efficiency_pct",
               "sleep.deep_pct", "sleep.rem_pct", "sleep.light_pct", "sleep.awake_pct"}


def _odd(rng: random.Random, value: object) -> object:
    roll = rng.random()
    if roll < .06:
        return None
    if roll < .09:
        return rng.choice([True, -1, 2000, "30", float("nan")])
    return value


def _night(rng: random.Random, day: date) -> FeatureRecord:
    light, deep, rem = rng.uniform(150, 260), rng.uniform(40, 110), rng.uniform(50, 120)
    awake = rng.uniform(0, 60)
    tst = light + deep + rem
    tib = tst + awake
    if rng.random() < .1:
        tib += rng.choice([-30, 5, 40])  # inconsistent TST/TIB
    bedtime = (rng.choice([1320, 1380, 1430]) + rng.uniform(-60, 60)) % 1440  # wraps midnight
    values = {"time_in_bed_min": _odd(rng, tib), "tst_min": _odd(rng, tst),
              "awake_min": _odd(rng, awake), "light_min": _odd(rng, light),
              "deep_min": _odd(rng, deep), "rem_min": _odd(rng, rem),
              "stage_coverage": rng.choice(["COMPLETE"] * 5 + ["INCOMPLETE", None]),
              # Feature builder emits clock minutes or None; Legacy rejects other types.
              "bedtime_local_min": None if rng.random() < .06 else bedtime,
              "wake_local_min": None if rng.random() < .06 else (bedtime + tib) % 1440}
    flags = ("SENSOR_GAP",) if rng.random() < .08 else ()
    return FeatureRecord("nightly", day, values, f"n-{day}", 4, f"ids-{day}",
                         f"{day}T22:00:00+00:00", f"{day}T07:00:00+00:00", flags)


def _history(seed: int) -> dict:
    rng = random.Random(seed)
    return {START + timedelta(days=o): _night(rng, START + timedelta(days=o))
            for o in range(DAYS) if rng.random() < (.5 if seed % 4 == 0 else .9)}


def _comparable(item) -> dict:
    lineage = item.lineage if hasattr(item, "lineage") else item.inputs
    return {"name": item.name, "day": item.day, "value": item.value, "unit": item.unit,
            "status": item.status, "algorithm_id": item.algorithm_id,
            "algorithm_version": item.algorithm_version, "source_type": item.source_type,
            "upstream_project": item.upstream_project, "upstream_commit": item.upstream_commit,
            "metadata": item.metadata, "confidence": item.confidence,
            "lineage": [(f.kind, f.day, f.fingerprint, f.source_count, f.source_ids_hash,
                         f.measurement_start, f.measurement_end, tuple(f.quality_flags))
                        for f in lineage]}


class SleepStagesCharacterizationTests(unittest.TestCase):
    def test_stage_metrics_and_regularity_match_legacy(self):
        seen = set()
        for seed in range(12):
            nights = _history(seed)
            mapped = {d: stages_night(f) for d, f in nights.items()}
            for offset in range(DAYS):
                day = START + timedelta(days=offset)
                night = nights.get(day)
                expected = [d for d in legacy.direct_metrics(day, night, None) if d.name in STAGE_NAMES]
                actual = stages.stage_metrics(day, mapped[day]) if night else []
                legacy_reg = legacy.regularity(day, nights)
                target_reg = stages.regularity(day, mapped)
                with self.subTest(seed=seed, day=day):
                    self.assertEqual([_comparable(r) for r in actual], [_comparable(d) for d in expected])
                    self.assertEqual(_comparable(target_reg) if target_reg else None,
                                     _comparable(legacy_reg) if legacy_reg else None)
                seen.update((d.name, d.status) for d in expected)
                if legacy_reg:
                    seen.add(("sleep.regularity", legacy_reg.status))
        for name in ("sleep.total_sleep_time_min", "sleep.efficiency_pct", "sleep.awake_pct"):
            self.assertTrue({(name, "VALID"), (name, "INSUFFICIENT_DATA")} <= seen, name)
        self.assertTrue({("sleep.regularity", "VALID"), ("sleep.regularity", "CALIBRATING")} <= seen)

    def test_consistency_and_efficiency_boundaries_match_legacy(self):
        day = START
        cases = {
            # TST + awake misses TIB by 1.5 min: stages rejected.
            "inconsistent": ({"time_in_bed_min": 481.5, "tst_min": 450.0, "awake_min": 30.0},
                             "sleep.total_sleep_time_min", "INSUFFICIENT_DATA"),
            # TST exceeds TIB by 0.3 min: efficiency 100.06 % is still accepted.
            "efficiency_tolerance": ({"time_in_bed_min": 480.0, "tst_min": 480.3, "awake_min": 0.0},
                                     "sleep.efficiency_pct", "VALID"),
        }
        for label, (values, metric, status) in cases.items():
            light = values["tst_min"] - 160.0
            record = FeatureRecord("nightly", day, {**values, "light_min": light, "deep_min": 80.0,
                                                    "rem_min": 80.0, "stage_coverage": "COMPLETE"},
                                   f"n-{label}", 1, f"ids-{label}", None, None)
            expected = [d for d in legacy.direct_metrics(day, record, None) if d.name in STAGE_NAMES]
            actual = stages.stage_metrics(day, stages_night(record))
            with self.subTest(label):
                self.assertEqual([_comparable(r) for r in actual], [_comparable(d) for d in expected])
                self.assertEqual(next(d.status for d in expected if d.name == metric), status)

    def test_stage_modules_are_independent(self):
        package = ROOT / "src" / "mi_fitness_whooping"
        for relative in ("domain/sleep/observations.py", "analytics/sleep/stages.py"):
            source = (package / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = {alias.name for node in ast.walk(tree)
                        if isinstance(node, ast.Import) for alias in node.names}
            imported.update(node.module for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom) and node.module)
            project = {name for name in imported if name.startswith("mi_fitness_whooping")}
            with self.subTest(module=relative):
                self.assertNotIn("sqlite3", imported)
                self.assertFalse(any(name.startswith("analytics.") for name in imported))
                self.assertTrue(all(name.startswith(("mi_fitness_whooping.domain.metrics",
                                                     "mi_fitness_whooping.domain.sleep.observations"))
                                    for name in project), project)
                self.assertNotIn(".now(", source)


if __name__ == "__main__":
    unittest.main()
