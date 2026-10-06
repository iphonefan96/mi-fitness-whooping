from __future__ import annotations

import math
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from analytics.__main__ import recovery_headline
from analytics.algorithms.foundations import FeatureRecord
from analytics.algorithms.recovery import (Baseline, RecoveryInput, calculate_recovery_day,
                                           vitals_v3)
from analytics.features.foundations import build_nightly
from analytics.runners.runner import run
from analytics.tests.test_foundations import FakeFitbitAdapter, add_night, synthetic_source, _epoch


START = date(2026, 1, 1)
PROFILE = {"schema_version": 1, "values": []}


def night(day, *, rhr=60, tst=480, hrv=None):
    values = {"rhr_bpm": rhr, "tst_min": tst, "stage_coverage": "COMPLETE",
              "hrv_rmssd_ms": hrv}
    return FeatureRecord("nightly", day, values, f"fp-{day}-{values}", 1, "source", None, None)


class RecoveryTests(unittest.TestCase):
    def test_exact_v3_formula_and_weight_normalization(self):
        b = Baseline(60, 3, 10, 10, START)
        inp = RecoveryInput(START + timedelta(days=1), None, 57, 420, 480, None, b)
        got = vitals_v3(inp)
        z_rhr = 1.0
        z_sleep = ((420 / 480) - 1) / .12
        w = (.25 * z_rhr + .20 * z_sleep) / .45
        expected = round(100 / (1 + math.exp(-(1.06 + .85 * w))))
        self.assertEqual(got.score, expected)
        self.assertAlmostEqual(got.normalized_weights["rhr"], .25 / .45)
        self.assertAlmostEqual(got.normalized_weights["sleep"], .20 / .45)
        self.assertEqual(vitals_v3(RecoveryInput(START, 55, 60, 480, 480,
            Baseline(55, 0, 5, 5, START), Baseline(60, 0, 5, 5, START))).score, 74)

    def test_upstream_supported_missing_combinations(self):
        h = Baseline(50, 3, 10, 10, START)
        r = Baseline(60, 1.5, 10, 10, START)
        make = lambda hrv, rhr, sleep: RecoveryInput(START, hrv, rhr, sleep, 480, h, r)
        self.assertIsNotNone(vitals_v3(make(None, 60, 480)).score)
        self.assertIsNotNone(vitals_v3(make(50, None, 480)).score)
        self.assertIsNotNone(vitals_v3(make(50, 60, None)).score)
        self.assertIsNone(vitals_v3(make(None, 60, None)).score)
        self.assertIsNotNone(vitals_v3(make(None, None, 480)).score)  # upstream sleep-only
        self.assertIsNone(vitals_v3(make(None, None, None)).score)

    def test_sd_floor_zero_variance_and_outlier(self):
        base = Baseline(60, 0, 10, 10, START)
        got = vitals_v3(RecoveryInput(START, None, 57, 480, 480, None, base))
        self.assertEqual(got.components["rhr"], 2.0)  # floor 1.5 bpm
        broad = Baseline(50, 34, 10, 10, START)
        outlier = vitals_v3(RecoveryInput(START, 119, None, 480, 480, broad, None))
        self.assertAlmostEqual(outlier.components["hrv"], 69 / 34)
        self.assertLess(outlier.components["hrv"], 3)

    def test_local_cold_start_no_lookahead_gap_and_correction(self):
        nights = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=60)
                  for i in range(6)}
        d = START + timedelta(days=5)
        self.assertEqual(calculate_recovery_day(START, nights, PROFILE)[0].status, "CALIBRATING")
        current = calculate_recovery_day(d, nights, PROFILE)[0]
        self.assertEqual(current.status, "REDUCED")
        self.assertTrue(current.metadata["temporary_sleep_target"])
        self.assertEqual(current.metadata["active_components"], ["rhr", "sleep"])
        baseline_before = current.metadata["rhr_baseline"]["mean"]
        nights[d + timedelta(days=1)] = night(d + timedelta(days=1), rhr=100)
        self.assertEqual(calculate_recovery_day(d, nights, PROFILE)[0].metadata["rhr_baseline"]["mean"], baseline_before)
        nights[START] = night(START, rhr=80)
        corrected = calculate_recovery_day(d, nights, PROFILE)[0]
        self.assertNotEqual(corrected.value, current.value)
        late = START + timedelta(days=95)
        nights[late] = night(late, rhr=60)
        self.assertEqual(calculate_recovery_day(late, nights, PROFILE)[0].status, "CALIBRATING")
        for i in range(1, 6):
            nights[late + timedelta(days=i)] = night(late + timedelta(days=i), rhr=60)
        self.assertEqual(calculate_recovery_day(late + timedelta(days=5), nights, PROFILE)[0].status, "REDUCED")

    def test_full_synthetic_hrv_and_local_sleep_only_gate(self):
        nights = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=60, hrv=50)
                  for i in range(6)}
        d = START + timedelta(days=5)
        full = calculate_recovery_day(d, nights, PROFILE)[0]
        self.assertEqual(full.status, "VALID")
        self.assertEqual(full.metadata["mode"], "FULL")
        self.assertEqual(full.metadata["active_components"], ["hrv", "rhr", "sleep"])
        no_rhr = {k: night(k, rhr=None, hrv=50) for k in nights}
        self.assertEqual(calculate_recovery_day(d, no_rhr, PROFILE)[0].status, "REDUCED")
        no_sleep = {k: night(k, tst=None, hrv=50) for k in nights}
        self.assertEqual(calculate_recovery_day(d, no_sleep, PROFILE)[0].status, "REDUCED")
        sleep_only = {k: night(k, rhr=None) for k in nights}
        self.assertIsNone(calculate_recovery_day(d, sleep_only, PROFILE)[0].value)

    def test_fake_fitbit_feature_uses_same_recovery_contract(self):
        d = date(2026, 9, 25)
        feature = build_nightly(FakeFitbitAdapter(), d, normalization_version="test",
                                profile_revision="test")
        self.assertEqual(feature.values["hrv_rmssd_ms"], 42)
        nights = {d - timedelta(days=i): night(d - timedelta(days=i), rhr=54, hrv=42)
                  for i in range(1, 6)}
        nights[d] = FeatureRecord("nightly", d, feature.values, feature.input_fingerprint,
                                  len(feature.source_ids), "fitbit", None, None)
        result = calculate_recovery_day(d, nights, PROFILE)[0]
        self.assertEqual(result.metadata["mode"], "FULL")

    def test_stale_headline(self):
        stale = recovery_headline("2026-06-26", "STALE", 74, "REDUCED",
                                  {"mode": "REDUCED", "active_components": ["rhr", "sleep"]})
        self.assertIsNone(stale["score"])
        self.assertIsNone(stale["mode"])
        self.assertEqual(stale["freshness"], "STALE")

    def test_incremental_historical_correction_updates_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source.sqlite", Path(tmp) / "analytics.sqlite"
            synthetic_source(source)
            db = sqlite3.connect(source)
            for i in range(20, 25):
                add_night(db, f"2026-09-{i}", f"s{i}", "2026-09-25T02:00:00Z")
            add_night(db, "2026-09-26", "s26", "2026-09-26T05:00:00Z")
            db.execute("UPDATE source_databases SET last_fingerprint='six-nights',max_source_timestamp=?",
                       (_epoch("2026-09-26T05:00:00"),))
            db.commit(); db.close()
            self.assertEqual(run(source, target)["status"], "SUCCESS")
            db = sqlite3.connect(target)
            before = db.execute("SELECT r.result_id,r.value FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id WHERE r.metric_name='recovery.score' AND r.metric_date='2026-09-25'").fetchone()
            db.close()
            self.assertEqual(run(source, target)["status"], "NO NEW ANALYTICS INPUT")
            db = sqlite3.connect(source)
            db.execute("UPDATE daily_summary SET resting_hr=80,updated_at='2026-09-26T07:00:00Z' WHERE local_date='2026-09-24'")
            db.execute("UPDATE source_databases SET last_fingerprint='corrected'")
            db.commit(); db.close()
            changed = run(source, target)
            self.assertEqual(changed["status"], "SUCCESS")
            self.assertLess(changed["dirty_dates"], 10)
            db = sqlite3.connect(target)
            after = db.execute("SELECT r.result_id,r.value,r.supersedes_result_id FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id WHERE r.metric_name='recovery.score' AND r.metric_date='2026-09-25'").fetchone()
            db.close()
            self.assertNotEqual(before[0], after[0])
            self.assertNotEqual(before[1], after[1])
            self.assertEqual(after[2], before[0])


if __name__ == "__main__":
    unittest.main()
