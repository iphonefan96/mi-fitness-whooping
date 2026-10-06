from __future__ import annotations

import math
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from analytics.algorithms.foundations import calculate_day
from analytics.__main__ import monitoring_headline
from analytics.algorithms.monitoring import (HealthBandInput, _vitals_watch,
                                             calculate_cusum_series,
                                             calculate_monitoring_day, evaluate_band,
                                             IllnessWatchInput)
from analytics.tests.test_step6_metrics import daily, night
from analytics.runners.runner import run
from analytics.tests.test_foundations import synthetic_source, add_night, _epoch


START = date(2026, 1, 1)


def fixture(days=11):
    nights = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=60,
                                               spo2=97, resp=16,
                                               fingerprint=f"night-{i}")
              for i in range(days)}
    dailies = {d: daily(d, rhr=60) for d in nights}
    return nights, dailies


def results(d, nights, dailies):
    foundations = calculate_day(d, nights, dailies)
    return {m.name: m for m in calculate_monitoring_day(d, nights, foundations)}


class MonitoringTests(unittest.TestCase):
    def test_stale_current_hides_historical_events(self):
        headline = monitoring_headline("2026-06-26", "STALE", ["anomaly.rhr"],
                                       "2026-06-26", ["rhr", "spo2"])
        self.assertIsNone(headline["active_anomalies"])
        self.assertEqual(headline["latest_anomaly_date"], "2026-06-26")

    def test_normal_band_and_directional_outliers(self):
        nights, dailies = fixture()
        d = START + timedelta(days=10)
        normal = results(d, nights, dailies)
        for signal in ("rhr", "spo2", "respiratory"):
            self.assertEqual(normal[f"anomaly.{signal}"].value, 0)
        self.assertEqual(normal["health_signal.physiological_watch"].value, 0)
        self.assertEqual(normal["anomaly.rhr"].metadata["upper"], 63)
        self.assertEqual(normal["anomaly.spo2"].metadata["lower"], 95.5)
        self.assertEqual(normal["anomaly.respiratory"].metadata["upper"], 16.8)
        nights[d].values.update({"rhr_bpm": 66, "spo2_mean_pct": 91, "respiratory_rate_bpm": 18})
        dailies[d].values["daily_rhr_bpm"] = 66
        flagged = results(d, nights, dailies)
        for signal in ("rhr", "spo2", "respiratory"):
            self.assertEqual(flagged[f"anomaly.{signal}"].value, 1)
        self.assertEqual(flagged["health_signal.physiological_watch"].value, 1)
        self.assertEqual(set(flagged["health_signal.physiological_watch"].metadata["drivers"]),
                         {"rhr", "spo2", "respiratory"})
        self.assertFalse(flagged["health_signal.physiological_watch"].metadata["diagnosis"])

    def test_single_outlier_missing_and_cold_start(self):
        nights, dailies = fixture()
        d = START + timedelta(days=10)
        nights[d].values["rhr_bpm"] = 66
        dailies[d].values["daily_rhr_bpm"] = 66
        m = results(d, nights, dailies)
        self.assertEqual(m["anomaly.rhr"].value, 1)
        self.assertEqual(m["health_signal.physiological_watch"].value, 0)
        nights[d].values["spo2_mean_pct"] = None
        self.assertIsNone(results(d, nights, dailies)["anomaly.spo2"].value)
        self.assertIsNone(results(START, nights, dailies)["anomaly.rhr"].value)
        self.assertEqual(results(START, nights, dailies)["anomaly.rhr"].status, "CALIBRATING")

    def test_no_lookahead_and_long_gap(self):
        nights, dailies = fixture()
        d = START + timedelta(days=10)
        old = results(d, nights, dailies)["anomaly.rhr"].metadata["baseline_mean"]
        future = d + timedelta(days=1)
        nights[future] = night(future, rhr=100, fingerprint="future")
        dailies[future] = daily(future, rhr=100)
        self.assertEqual(results(d, nights, dailies)["anomaly.rhr"].metadata["baseline_mean"], old)
        resumed = START + timedelta(days=100)
        nights[resumed] = night(resumed, rhr=60, fingerprint="resumed")
        dailies[resumed] = daily(resumed, rhr=60)
        self.assertIsNone(results(resumed, nights, dailies)["anomaly.rhr"].value)
        for i in range(1, 6):
            x = resumed + timedelta(days=i)
            nights[x] = night(x, rhr=60, fingerprint=f"resume-{i}")
            dailies[x] = daily(x, rhr=60)
        self.assertEqual(results(resumed + timedelta(days=5), nights, dailies)["anomaly.rhr"].value, 0)

    def test_pulse_and_vitals_reference_cases(self):
        base = HealthBandInput("spo2", START, 93, 97, 0, 95.5, None, 10, START - timedelta(days=1))
        self.assertTrue(evaluate_band(base).concerning)
        self.assertEqual(evaluate_band(HealthBandInput("rhr", START, 63, 60, 0, 57, 63,
                                                      10, START - timedelta(days=1))).state, "IN_RANGE")
        drivers, _ = _vitals_watch(IllnessWatchInput(START,
            {"rhr": 66, "respiratory": 18, "spo2": 91},
            {"rhr": (60, 0), "respiratory": (16, 0), "spo2": (97, 0)}))
        self.assertEqual(drivers, ["rhr", "respiratory", "spo2"])
        drivers, _ = _vitals_watch(IllnessWatchInput(START,
            {"rhr": 65, "respiratory": None, "spo2": None},
            {"rhr": (60, 0), "respiratory": None, "spo2": None}))
        self.assertEqual(drivers, [])  # upstream fallback is strictly > base+5

    def test_cusum_golden_sequence_zero_variance_and_gap(self):
        values = [55 + 2 * math.sin(i) for i in range(30)] + [65] * 5 + [55] * 12
        nights = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=v,
                                                  fingerprint=f"c{i}")
                  for i, v in enumerate(values)}
        output = calculate_cusum_series(nights)
        self.assertTrue(any(output[START + timedelta(days=i)].metadata["state"] == "RED"
                            for i in range(30, 35)))
        self.assertEqual(output[START + timedelta(days=len(values)-1)].metadata["state"], "GREEN")
        downstream_before = output[START + timedelta(days=31)].metadata["state_token"]
        nights[START + timedelta(days=30)].values["rhr_bpm"] = 80
        downstream_after = calculate_cusum_series(nights)[START + timedelta(days=31)].metadata["state_token"]
        self.assertNotEqual(downstream_before, downstream_after)
        flat = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=55,
                                                fingerprint=f"f{i}") for i in range(9)}
        flat[START + timedelta(days=9)] = night(START + timedelta(days=9), rhr=60, fingerprint="bump")
        abstained = calculate_cusum_series(flat)[START + timedelta(days=9)]
        self.assertIsNone(abstained.value)
        self.assertEqual(abstained.metadata["reason"], "degenerate_baseline:scale=0")
        gapped = {START + timedelta(days=i): night(START + timedelta(days=i), rhr=55 + 2 * math.sin(i),
                                                   fingerprint=f"g{i}") for i in range(9) if i != 4}
        self.assertEqual(calculate_cusum_series(gapped)[START + timedelta(days=8)].metadata["reason"],
                         "need_contiguous_baseline")
        gap_day = START + timedelta(days=90)
        nights[gap_day] = night(gap_day, rhr=55, fingerprint="after-gap")
        self.assertIsNone(calculate_cusum_series(nights)[gap_day].value)

    def test_runner_correction_idempotency_and_version_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source.sqlite", Path(tmp) / "analytics.sqlite"
            synthetic_source(source)
            db = sqlite3.connect(source)
            for i in range(20, 25):
                add_night(db, f"2026-09-{i}", f"s{i}", "2026-09-25T02:00:00Z")
            db.execute("UPDATE source_databases SET last_fingerprint='monitor-test',max_source_timestamp=?",
                       (_epoch("2026-09-25T05:00:00"),))
            db.commit(); db.close()
            self.assertEqual(run(source, target)["status"], "SUCCESS")
            db = sqlite3.connect(target)
            before = db.execute("SELECT r.result_id FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id WHERE r.metric_name='anomaly.rhr' AND r.metric_date='2026-09-25'").fetchone()[0]
            count = db.execute("SELECT COUNT(*) FROM derived_metric_results WHERE metric_name='anomaly.rhr'").fetchone()[0]
            db.close()
            self.assertEqual(run(source, target)["status"], "NO NEW ANALYTICS INPUT")
            db = sqlite3.connect(target)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results WHERE metric_name='anomaly.rhr'").fetchone()[0], count)
            db.close()
            db = sqlite3.connect(source)
            db.execute("UPDATE daily_summary SET resting_hr=80,updated_at='2026-09-26T07:00:00Z' WHERE local_date='2026-09-24'")
            db.execute("UPDATE source_databases SET last_fingerprint='monitor-corrected'")
            db.commit(); db.close()
            changed = run(source, target)
            self.assertEqual(changed["status"], "SUCCESS")
            self.assertLess(changed["dirty_dates"], 10)
            db = sqlite3.connect(target)
            after = db.execute("SELECT r.result_id,r.supersedes_result_id FROM active_metric_selection a JOIN derived_metric_results r ON r.result_id=a.result_id WHERE r.metric_name='anomaly.rhr' AND r.metric_date='2026-09-25'").fetchone()
            self.assertNotEqual(before, after[0])
            self.assertEqual(after[1], before)
            db.close()
            with patch("analytics.runners.runner.MONITORING_ALGORITHM_VERSION", "monitor-test-next"), \
                 patch("analytics.algorithms.monitoring.MONITORING_ALGORITHM_VERSION", "monitor-test-next"):
                self.assertEqual(run(source, target)["status"], "SUCCESS")
            db = sqlite3.connect(target)
            self.assertEqual({r[0] for r in db.execute("SELECT algorithm_version FROM derived_metric_results WHERE metric_name='anomaly.rhr'")},
                             {"monitoring-2", "monitor-test-next"})
            db.close()


if __name__ == "__main__":
    unittest.main()
