"""Series statistics and vitals monitoring: synthetic characterization against Legacy."""

from __future__ import annotations

import ast
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Legacy"))

from analytics.algorithms import foundations as legacy_foundations  # noqa: E402
from analytics.algorithms import monitoring as legacy_monitoring  # noqa: E402
from analytics.algorithms.foundations import FeatureRecord  # noqa: E402
from mi_fitness_whooping.analytics.recovery_vitals import monitoring  # noqa: E402
from mi_fitness_whooping.analytics.series import core as series_core  # noqa: E402
from mi_fitness_whooping.integration.recovery_vitals.adapter import (  # noqa: E402
    monitoring_bands, vitals_night,
)
from mi_fitness_whooping.integration.series.adapter import series_history  # noqa: E402


START = date(2026, 1, 1)
DAYS = 120


def _feature(kind: str, day: date, values: dict) -> FeatureRecord:
    return FeatureRecord(kind, day, values, f"{kind}-{day}", 2, f"ids-{kind}-{day}",
                         f"{day}T00:00:00+00:00", f"{day}T07:00:00+00:00",
                         ("SENSOR_GAP",) if day.day == 13 else ())


def _odd(rng: random.Random, value: object) -> object:
    roll = rng.random()
    if roll < .08:
        return None
    if roll < .1:
        return rng.choice([True, -3, 0, 300, "60", float("nan"), float("inf")])
    return value


def _history(seed: int) -> tuple[dict, dict]:
    rng = random.Random(seed)
    nights, dailies = {}, {}
    rhr, spo2, resp = 58.0, 96.0, 14.5
    skip_until = None
    for offset in range(DAYS):
        day = START + timedelta(days=offset)
        if skip_until is None and rng.random() < .03:
            skip_until = day + timedelta(days=rng.choice([3, 9, 16]))  # stale/contiguity gaps
        if skip_until is not None and day < skip_until:
            continue
        skip_until = None
        rhr += rng.uniform(-1.5, 1.5)
        spo2 = min(99.5, max(88.0, spo2 + rng.uniform(-.6, .6)))
        resp = min(20.0, max(10.0, resp + rng.uniform(-.4, .4)))
        spike = 12 if rng.random() < .07 else 0
        if rng.random() < .9:
            nights[day] = _feature("nightly", day, {
                "rhr_bpm": _odd(rng, round(rhr + spike)),
                "tst_min": _odd(rng, rng.uniform(300, 520)),
                "spo2_mean_pct": _odd(rng, spo2 - (5 if spike else 0)),
                "respiratory_rate_bpm": _odd(rng, resp + (3 if spike else 0)),
                "stage_coverage": "COMPLETE",
            })
        if rng.random() < .85:
            dailies[day] = _feature("daily", day, {
                "daily_rhr_bpm": _odd(rng, round(rhr + spike)),
                "steps": _odd(rng, rng.randint(0, 15000)),
                "vendor_stress_median": _odd(rng, rng.uniform(10, 60)),
            })
    return nights, dailies


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


SEEDS = range(10)


class SeriesCharacterizationTests(unittest.TestCase):
    def test_baselines_deviations_and_trends_match_legacy(self):
        statuses = set()
        for seed in SEEDS:
            nights, dailies = _history(seed)
            history = series_history(nights, dailies)
            for offset in range(DAYS):
                day = START + timedelta(days=offset)
                for name, legacy, target in (
                    ("baselines", legacy_foundations.baselines(day, nights, dailies),
                     series_core.baselines(day, history)),
                    ("trends", legacy_foundations.trends(day, nights, dailies),
                     series_core.trends(day, history)),
                ):
                    with self.subTest(seed=seed, day=day, family=name):
                        self.assertEqual([_comparable(r) for r in target],
                                         [_comparable(d) for d in legacy])
                    statuses.update((d.name.split(".")[0], d.status) for d in legacy)
        for family in ("baseline", "trend"):
            for status in ("VALID", "REDUCED", "CALIBRATING"):
                self.assertIn((family, status), statuses)


class MonitoringCharacterizationTests(unittest.TestCase):
    def test_band_anomalies_and_watch_match_legacy(self):
        states, watch = set(), set()
        for seed in SEEDS:
            nights, dailies = _history(seed)
            history = series_history(nights, dailies)
            mapped = {d: vitals_night(f) for d, f in nights.items()}
            for offset in range(DAYS):
                day = START + timedelta(days=offset)
                legacy = legacy_monitoring.calculate_monitoring_day(
                    day, nights, legacy_foundations.calculate_day(day, nights, dailies))
                target = monitoring.calculate_monitoring_day(
                    day, mapped, monitoring_bands(series_core.baselines(day, history)))
                with self.subTest(seed=seed, day=day):
                    self.assertEqual([_comparable(r) for r in target],
                                     [_comparable(d) for d in legacy])
                states.update(d.metadata["state"] for d in legacy if "state" in d.metadata)
                watch.update((d.status, d.value) for d in legacy
                             if d.name == "health_signal.physiological_watch")
        self.assertTrue({"NO_DATA", "STALE", "CALIBRATING", "IN_RANGE", "ABOVE", "BELOW"} <= states,
                        states)
        self.assertTrue({("REDUCED", 1.0), ("REDUCED", 0.0), ("CALIBRATING", None)} <= watch, watch)

    def test_rhr_cusum_series_matches_legacy(self):
        states = set()
        for seed in SEEDS:
            nights, _ = _history(seed)
            legacy = legacy_monitoring.calculate_cusum_series(nights)
            target = monitoring.calculate_cusum_series({d: vitals_night(f) for d, f in nights.items()})
            self.assertEqual(list(target), list(legacy))
            for day in legacy:
                with self.subTest(seed=seed, day=day):
                    self.assertEqual(_comparable(target[day]), _comparable(legacy[day]))
                states.add(legacy[day].metadata["state"])
        self.assertTrue({"UNEVALUATED", "GREEN", "YELLOW", "RED"} <= states, states)


class BoundaryCharacterizationTests(unittest.TestCase):
    def test_trend_gap_of_eight_days_is_not_a_trend(self):
        day = START + timedelta(days=29)
        dailies = {START + timedelta(days=o): _feature("daily", START + timedelta(days=o),
                                                       {"steps": 1000 + 10 * o})
                   for o in range(30) if not 10 <= o <= 16}  # 9 -> 17 is an 8-day gap
        legacy = legacy_foundations.trends(day, {}, dailies)
        target = series_core.trends(day, series_history({}, dailies))
        self.assertEqual([_comparable(r) for r in target], [_comparable(d) for d in legacy])
        month = next(d for d in legacy if d.name == "trend.steps.30d.theilsen")
        self.assertEqual((month.status, month.metadata["max_gap_days"]), ("CALIBRATING", 8))

    def test_cusum_crossing_just_above_threshold(self):
        nights = {START + timedelta(days=o): _feature("nightly", START + timedelta(days=o),
                                                      {"rhr_bpm": 60 if o % 2 == 0 else 58})
                  for o in range(40)}  # median 59, scaled MAD 1.4826; day 39 resets to zero
        last = START + timedelta(days=40)
        nights[last] = _feature("nightly", last, {"rhr_bpm": 59 + 4.55 * 1.4826})  # CUSUM 4.05
        legacy = legacy_monitoring.calculate_cusum_series(nights)
        target = monitoring.calculate_cusum_series({d: vitals_night(f) for d, f in nights.items()})
        for day in legacy:
            with self.subTest(day=day):
                self.assertEqual(_comparable(target[day]), _comparable(legacy[day]))
        self.assertEqual(legacy[last].metadata["state"], "YELLOW")
        self.assertAlmostEqual(legacy[last].metadata["cusum"], 4.05)


class IndependenceTests(unittest.TestCase):
    def test_pure_modules_have_no_storage_runner_or_legacy_dependency(self):
        package = ROOT / "src" / "mi_fitness_whooping"
        allowed = {
            "domain/series/contracts.py": ("mi_fitness_whooping.domain.metrics",),
            "analytics/series/core.py": ("mi_fitness_whooping.domain.metrics",
                                         "mi_fitness_whooping.domain.series"),
            "analytics/recovery_vitals/monitoring.py": ("mi_fitness_whooping.domain.metrics",
                                                       "mi_fitness_whooping.domain.recovery_vitals"),
        }
        for relative, prefixes in allowed.items():
            source = (package / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = {alias.name for node in ast.walk(tree)
                        if isinstance(node, ast.Import) for alias in node.names}
            imported.update(node.module for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom) and node.module)
            with self.subTest(module=relative):
                self.assertNotIn("sqlite3", imported)
                self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                                     for name in imported))
                project = {name for name in imported if name.startswith("mi_fitness_whooping")}
                self.assertTrue(all(name.startswith(prefixes) for name in project), project)
                self.assertNotIn(".now(", source)
                self.assertNotIn("today(", source)

    def test_versions_match_runner_state_contract(self):
        from mi_fitness_whooping.baseline.foundations import FOUNDATION_ALGORITHM_VERSION
        self.assertEqual(series_core.SERIES_ALGORITHM_VERSION, FOUNDATION_ALGORITHM_VERSION)
        self.assertEqual(monitoring.MONITORING_ALGORITHM_VERSION,
                         legacy_monitoring.MONITORING_ALGORITHM_VERSION)


if __name__ == "__main__":
    unittest.main()
