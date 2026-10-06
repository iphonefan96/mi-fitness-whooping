from __future__ import annotations

import unittest
from datetime import date, timedelta

from analytics.algorithms.foundations import (FeatureRecord, baselines, calculate_day,
                                              direct_metrics, regularity, trends)


def night(day: date, *, tst=450, tib=480, awake=30, deep=120, light=210, rem=120,
          bedtime=23 * 60 + 50, wake=7 * 60 + 50, rhr=60, spo2=97, resp=16,
          stage_coverage="COMPLETE", fingerprint="x") -> FeatureRecord:
    return FeatureRecord("nightly", day, {
        "night_rhr_bpm": 55, "night_hr_measured_minutes": 400, "rhr_bpm": rhr,
        "rhr_method": "xiaomi_vendor_daily", "time_in_bed_min": tib, "tst_min": tst,
        "awake_min": awake, "deep_min": deep, "light_min": light, "rem_min": rem,
        "stage_coverage": stage_coverage, "bedtime_local_min": bedtime,
        "wake_local_min": wake, "spo2_samples": 48 if spo2 is not None else 0,
        "spo2_span_min": 470 if spo2 is not None else 0,
        "spo2_mean_pct": spo2, "spo2_min_pct": spo2 - 2 if spo2 is not None else None,
        "spo2_p10_pct": spo2 - 1 if spo2 is not None else None,
        "respiratory_rate_bpm": resp, "respiratory_provenance": "sleep_sessions.avg_respiratory_rate",
    }, fingerprint, 100, "hash", None, None)


def daily(day: date, *, rhr=60, steps=8000) -> FeatureRecord:
    return FeatureRecord("daily", day, {"daily_rhr_bpm": rhr, "steps": steps,
                                         "vendor_stress_median": 20}, f"d-{day}-{rhr}", 20, "hash", None, None)


def by_name(metrics):
    return {m.name: m for m in metrics}


class Step6MetricTests(unittest.TestCase):
    def test_sleep_arithmetic_and_stage_denominators(self):
        d = date(2026, 1, 10)
        m = by_name(direct_metrics(d, night(d), None))
        self.assertEqual(m["sleep.total_sleep_time_min"].value, 450)
        self.assertEqual(m["sleep.time_in_bed_min"].value, 480)
        self.assertAlmostEqual(m["sleep.efficiency_pct"].value, 93.75)
        self.assertAlmostEqual(m["sleep.deep_pct"].value, 120 / 450 * 100)
        self.assertEqual(m["sleep.deep_pct"].metadata["denominator"], "TST")
        self.assertAlmostEqual(m["sleep.awake_pct"].value, 30 / 480 * 100)
        self.assertEqual(m["sleep.awake_pct"].metadata["denominator"], "TIME_IN_BED")
        self.assertNotIn("sleep.sri", m)
        self.assertNotIn("sleep.score", m)
        self.assertNotIn("recovery", m)

    def test_zero_awake_vs_missing_stage(self):
        d = date(2026, 1, 10)
        measured_zero = by_name(direct_metrics(d, night(d, tib=450, awake=0), None))
        self.assertEqual(measured_zero["sleep.awake_min"].value, 0)
        self.assertEqual(measured_zero["sleep.awake_min"].status, "VALID")
        self.assertEqual(measured_zero["sleep.awake_pct"].value, 0)
        missing = by_name(direct_metrics(d, night(d, awake=None), None))
        self.assertIsNone(missing["sleep.awake_min"].value)
        self.assertIsNone(missing["sleep.total_sleep_time_min"].value)
        self.assertEqual(missing["sleep.efficiency_pct"].status, "INSUFFICIENT_DATA")
        incomplete = by_name(direct_metrics(d, night(d, stage_coverage="UNKNOWN"), None))
        self.assertIsNone(incomplete["sleep.rem_pct"].value)

    def test_invalid_efficiency_and_sensor_bounds(self):
        d = date(2026, 1, 10)
        m = by_name(direct_metrics(d, night(d, tib=0, spo2=101, resp=100), None))
        self.assertIsNone(m["sleep.efficiency_pct"].value)
        self.assertIsNone(m["spo2.nightly_mean"].value)
        self.assertIsNone(m["respiratory.nightly_mean"].value)

    def test_rhr_and_vendor_provenance(self):
        d = date(2026, 1, 10)
        m = by_name(direct_metrics(d, night(d), daily(d)))
        self.assertEqual(m["rhr.nightly"].value, 55)
        self.assertEqual(m["rhr.vendor_daily"].value, 60)
        self.assertEqual(m["rhr.vendor_daily"].source_type, "VENDOR_DERIVED")
        self.assertEqual(m["rhr.nightly"].source_type, "OUR_DERIVED")

    def test_spo2_and_resp_are_not_diagnostic(self):
        d = date(2026, 1, 10)
        m = by_name(direct_metrics(d, night(d), None))
        self.assertEqual(m["spo2.nightly_count"].value, 48)
        self.assertEqual(m["spo2.nightly_mean"].value, 97)
        self.assertEqual(m["spo2.nightly_p10"].value, 96)
        self.assertEqual(m["respiratory.nightly_mean"].value, 16)
        self.assertEqual(m["respiratory.nightly_mean"].status, "REDUCED")
        self.assertEqual(m["respiratory.nightly_mean"].metadata["raw_breath_count"], None)
        self.assertFalse(any("apnea" in name or "illness" in name for name in m))

    def test_circular_regularity_and_cold_start(self):
        d = date(2026, 1, 10)
        nights = {d - timedelta(days=i): night(d - timedelta(days=i),
                  bedtime=(10 if i % 2 else 1430), wake=470 if i % 2 else 490)
                  for i in range(5)}
        reg = regularity(d, nights)
        self.assertEqual(reg.status, "VALID")
        self.assertEqual(reg.value, 100)
        self.assertLess(reg.metadata["combined_sd_min"], 20)
        cold = regularity(d, {d: night(d)})
        self.assertEqual(cold.status, "CALIBRATING")
        self.assertIsNone(cold.value)
        self.assertEqual(cold.metadata["required_history_count"], 5)

    def test_baseline_no_lookahead_and_cold_start(self):
        d = date(2026, 1, 10)
        dailies = {d - timedelta(days=i): daily(d - timedelta(days=i), rhr=60)
                   for i in range(1, 6)}
        dailies[d] = daily(d, rhr=70)
        dailies[d + timedelta(days=1)] = daily(d + timedelta(days=1), rhr=200)
        base = by_name(baselines(d, {}, dailies))
        self.assertEqual(base["baseline.rhr.band_mean"].value, 60)
        self.assertEqual(base["rhr.deviation"].value, 10)
        self.assertEqual(base["baseline.rhr.band_mean"].metadata["history_count"], 5)
        self.assertTrue(base["baseline.rhr.band_mean"].metadata["excludes_current_date"])
        cold = by_name(baselines(d, {}, {d: daily(d)}))
        self.assertEqual(cold["baseline.rhr.band_mean"].status, "CALIBRATING")
        self.assertIsNone(cold["baseline.rhr.band_mean"].value)
        nights = {d - timedelta(days=i): night(d - timedelta(days=i), resp=16)
                  for i in range(6)}
        respiratory = by_name(baselines(d, nights, dailies))
        self.assertEqual(respiratory["baseline.respiratory.band_mean"].status, "REDUCED")

    def test_theilsen_calendar_slope_and_gap(self):
        d = date(2026, 1, 14)
        dailies = {d - timedelta(days=i): daily(d - timedelta(days=i), rhr=70 - i)
                   for i in range(14)}
        dailies[d - timedelta(days=7)] = daily(d - timedelta(days=7), rhr=200)
        m = by_name(trends(d, {}, dailies))
        self.assertAlmostEqual(m["trend.rhr.14d.theilsen"].value, 7)
        sparse = {d: daily(d), d - timedelta(days=10): daily(d - timedelta(days=10))}
        cold = by_name(trends(d, {}, sparse))
        self.assertEqual(cold["trend.rhr.14d.theilsen"].status, "CALIBRATING")
        self.assertIsNone(cold["trend.rhr.14d.theilsen"].value)

    def test_all_outputs_are_foundations(self):
        d = date(2026, 1, 10)
        metrics = calculate_day(d, {d: night(d)}, {d: daily(d)})
        forbidden = ("recovery", "readiness", "strain", "sleep.score", "sleep.debt", "sleep.need",
                     "illness", "resilience", "body_age", "training_load", "sleep.sri")
        self.assertFalse(any(m.name.startswith(forbidden) for m in metrics))


if __name__ == "__main__":
    unittest.main()
