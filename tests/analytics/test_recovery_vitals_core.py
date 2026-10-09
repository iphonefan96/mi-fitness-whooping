"""Recovery/vitals component: synthetic characterization against immutable Legacy."""

from __future__ import annotations

import ast
import random
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Legacy"))

from analytics.algorithms.foundations import FeatureRecord, direct_metrics  # noqa: E402
from analytics.algorithms.recovery import calculate_recovery_day  # noqa: E402
from mi_fitness_whooping.analytics.recovery_vitals import core  # noqa: E402
from mi_fitness_whooping.integration.recovery_vitals.adapter import (  # noqa: E402
    recovery_for_day, vitals_daily, vitals_night,
)


START = date(2026, 1, 1)
VITALS = {"rhr.nightly", "rhr.vendor_daily", "spo2.nightly_count", "spo2.nightly_span_min",
          "spo2.nightly_mean", "spo2.nightly_min", "spo2.nightly_p10",
          "respiratory.nightly_mean"}


def _maybe(rng: random.Random, value: object, missing: float = .15) -> object:
    roll = rng.random()
    if roll < missing:
        return None
    if roll < missing + .03:
        return rng.choice([True, -5, 0, 999.0, "72", float("nan")])  # gate edge cases
    return value


def _feature(kind: str, day: date, values: dict) -> FeatureRecord:
    return FeatureRecord(kind, day, values, f"{kind}-{day}", 3, f"ids-{kind}-{day}",
                         f"{day}T00:00:00+00:00", f"{day}T07:00:00+00:00",
                         ("SENSOR_GAP",) if day.day % 11 == 0 else ())


def _history(seed: int, days: int = 70) -> tuple[dict, dict]:
    rng = random.Random(seed)
    with_hrv = seed % 3 == 0  # Xiaomi has no HRV; the component still supports it.
    nights, dailies = {}, {}
    for offset in range(days):
        day = START + timedelta(days=offset)
        if rng.random() < .8:
            nights[day] = _feature("nightly", day, {
                "night_rhr_bpm": _maybe(rng, rng.uniform(45, 70)),
                "night_hr_measured_minutes": rng.randint(0, 400),
                "rhr_bpm": _maybe(rng, rng.randint(48, 75)),
                "hrv_rmssd_ms": _maybe(rng, rng.uniform(20, 90)) if with_hrv else None,
                "tst_min": _maybe(rng, rng.uniform(300, 540)),
                "stage_coverage": rng.choice(["COMPLETE", "COMPLETE", "COMPLETE", "INCOMPLETE"]),
                "spo2_samples": rng.choice([None, 0, 4, 20]),
                "spo2_span_min": _maybe(rng, rng.uniform(0, 420)),
                "spo2_mean_pct": _maybe(rng, rng.uniform(90, 99)),
                "spo2_min_pct": _maybe(rng, rng.uniform(84, 95)),
                "spo2_p10_pct": _maybe(rng, rng.uniform(88, 96)),
                "respiratory_rate_bpm": _maybe(rng, rng.uniform(12, 18)),
                "respiratory_provenance": rng.choice([None, "vendor_sleep_summary"]),
            })
        if rng.random() < .7:
            dailies[day] = _feature("daily", day, {"daily_rhr_bpm": _maybe(rng, rng.randint(48, 75))})
    return nights, dailies


def _comparable(draft) -> dict:
    return {"name": draft.name, "day": draft.day, "value": draft.value, "unit": draft.unit,
            "status": draft.status, "algorithm_id": draft.algorithm_id,
            "algorithm_version": draft.algorithm_version, "source_type": draft.source_type,
            "upstream_project": draft.upstream_project, "upstream_commit": draft.upstream_commit,
            "metadata": draft.metadata, "confidence": draft.confidence,
            "lineage": [(f.kind, f.day, f.fingerprint, f.source_count, f.source_ids_hash,
                         f.measurement_start, f.measurement_end, tuple(f.quality_flags))
                        for f in (draft.lineage if hasattr(draft, "lineage") else draft.inputs)]}


class RecoveryVitalsCharacterizationTests(unittest.TestCase):
    def test_direct_vitals_match_legacy(self):
        for seed in range(12):
            nights, dailies = _history(seed)
            for offset in range(70):
                day = START + timedelta(days=offset)
                night, daily = nights.get(day), dailies.get(day)
                legacy = [_comparable(d) for d in direct_metrics(day, night, daily)
                          if d.name in VITALS]
                vn = vitals_night(night) if night else None
                vd = vitals_daily(daily) if daily else None
                target = []
                if vn is not None:
                    target += [core.night_heart_rate(day, vn), *core.night_spo2(day, vn),
                               core.night_respiratory(day, vn)]
                vendor = core.vendor_daily_rhr(day, vn, vd)
                target += [vendor] if vendor is not None else []
                with self.subTest(seed=seed, day=day):
                    self.assertEqual([_comparable(r) for r in target], legacy)

    def test_recovery_matches_legacy_across_profiles_and_histories(self):
        profiles = (
            {"schema_version": 1, "values": []},
            {"schema_version": 1, "values": [
                {"field": "sleep_target_min", "value": 450, "effective_from": "2026-01-20"},
                {"field": "sleep_target_min", "value": 510.5, "effective_from": "2026-02-01",
                 "effective_to": "2026-02-10"}]},
        )
        statuses = set()
        for seed in range(12):
            nights, _ = _history(seed)
            mapped = {d: vitals_night(f) for d, f in nights.items()}
            for profile in profiles:
                for offset in range(70):
                    day = START + timedelta(days=offset)
                    legacy = calculate_recovery_day(day, nights, profile)
                    result = recovery_for_day(day, mapped, profile)
                    with self.subTest(seed=seed, day=day, profile=len(profile["values"])):
                        self.assertEqual([_comparable(r) for r in ([result] if result else [])],
                                         [_comparable(d) for d in legacy])
                    statuses.update(d.status for d in legacy)
        # The synthetic histories must reach every Recovery outcome.
        self.assertEqual(statuses, {"VALID", "REDUCED", "CALIBRATING", "INSUFFICIENT_DATA"})

    def test_invalid_profile_target_fails_like_legacy_only_for_a_night(self):
        nights, _ = _history(1)
        mapped = {d: vitals_night(f) for d, f in nights.items()}
        bad = {"schema_version": 1, "values": [
            {"field": "sleep_target_min", "value": 200, "effective_from": "2026-01-01"}]}
        night_day = next(iter(nights))
        gap = next(START + timedelta(days=o) for o in range(70)
                   if START + timedelta(days=o) not in nights)
        with self.assertRaisesRegex(ValueError, "300..720"):
            calculate_recovery_day(night_day, nights, bad)
        with self.assertRaisesRegex(ValueError, "300..720"):
            recovery_for_day(night_day, mapped, bad)
        self.assertEqual(calculate_recovery_day(gap, nights, bad), [])
        self.assertIsNone(recovery_for_day(gap, mapped, bad))

    def test_calculation_is_independent_of_storage_runner_and_legacy(self):
        package = ROOT / "src" / "mi_fitness_whooping"
        for path in (package / "domain" / "metrics.py",
                     package / "domain" / "recovery_vitals" / "contracts.py",
                     package / "analytics" / "recovery_vitals" / "core.py"):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = {alias.name for node in ast.walk(tree)
                            if isinstance(node, ast.Import) for alias in node.names}
                imported.update(node.module for node in ast.walk(tree)
                                if isinstance(node, ast.ImportFrom) and node.module)
                project = {name for name in imported if name.startswith("mi_fitness_whooping")}
                self.assertNotIn("sqlite3", imported)
                self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                                     for name in imported))
                self.assertTrue(all(name.startswith(("mi_fitness_whooping.domain.metrics",
                                                     "mi_fitness_whooping.domain.recovery_vitals",
                                                     "mi_fitness_whooping.analytics.recovery_vitals"))
                                    for name in project), project)
                self.assertNotIn(".now(", source)
                self.assertNotIn("today(", source)

    def test_versions_match_runner_state_contract(self):
        from mi_fitness_whooping.baseline.foundations import FOUNDATION_ALGORITHM_VERSION
        self.assertEqual(core.DIRECT_VITALS_ALGORITHM_VERSION, FOUNDATION_ALGORITHM_VERSION)


if __name__ == "__main__":
    unittest.main()
