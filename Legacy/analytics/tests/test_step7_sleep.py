from __future__ import annotations

import unittest
from datetime import date, timedelta

from analytics.algorithms.foundations import FeatureRecord
from analytics.algorithms.sleep import SleepScoreInput, calculate_sleep_day, score_components
from analytics.__main__ import sleep_headline


START = date(2026, 1, 1)
EMPTY_PROFILE = {"schema_version": 1, "values": []}


def night(day, *, tst=480, deep=90, rem=90, waso=0, bedtime=1380,
          awakenings=(), coverage="COMPLETE"):
    values = {"tst_min": tst, "deep_min": deep, "rem_min": rem, "waso_min": waso,
              "bedtime_local_min": bedtime, "awakening_durations_min": awakenings,
              "stage_coverage": coverage}
    return FeatureRecord("nightly", day, values, f"fp-{day}-{values}", 1, "source", None, None)


def metric(rows, name):
    return next(m for m in rows if m.name == name)


class SleepStep7Tests(unittest.TestCase):
    def test_stale_current_hides_historical_numbers(self):
        values = {"sleep.score": {"value": 88, "status": "VALID"},
                  "sleep.need_min": {"value": 480, "status": "REDUCED"},
                  "sleep.debt_min": {"value": 120, "status": "REDUCED"}}
        stale = sleep_headline("2026-06-26", "STALE", values)
        self.assertIsNone(stale["score"])
        self.assertIsNone(stale["need_min"])
        self.assertIsNone(stale["debt_min"])
        self.assertEqual(stale["last_night"], "2026-06-26")
        self.assertEqual(sleep_headline("2026-09-25", "FRESH", values)["score"], 88)

    def test_upstream_four_pillars_golden_and_variants(self):
        base = dict(day=START, tst_min=450, deep_min=90, rem_min=90,
                    bedtime_local_min=1380, prior_bedtimes_local_min=(1380,) * 5,
                    waso_min=10, awakening_durations_min=(), stage_coverage="COMPLETE")
        ideal = score_components(SleepScoreInput(**base))
        self.assertEqual(ideal, {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 100})
        self.assertLess(score_components(SleepScoreInput(**{**base, "tst_min": 120, "deep_min": 0,
            "rem_min": 0}))["duration"], 50)
        self.assertEqual(score_components(SleepScoreInput(**{**base, "tst_min": 720}))["duration"], 50)
        self.assertEqual(score_components(SleepScoreInput(**{**base, "bedtime_local_min": 60}))["consistency"], 0)
        self.assertEqual(score_components(SleepScoreInput(**{**base, "waso_min": 80,
            "awakening_durations_min": (10, 10, 10, 10)}))["interruptions"], 11)
        self.assertEqual(score_components(SleepScoreInput(**{**base, "deep_min": 0}))["stages"], 50)
        self.assertIsNone(score_components(SleepScoreInput(**{**base, "rem_min": None})))
        self.assertIsNone(score_components(SleepScoreInput(**{**base, "prior_bedtimes_local_min": (1380,) * 4})))

    def test_history_need_and_debt_repayment(self):
        nights = {START + timedelta(days=i): night(START + timedelta(days=i), tst=420) for i in range(14)}
        d = START + timedelta(days=13)
        rows = calculate_sleep_day(d, nights, EMPTY_PROFILE)
        self.assertEqual(metric(rows, "sleep.score").value, 100)
        self.assertEqual(metric(rows, "sleep.need_min").value, 480)
        self.assertEqual(metric(rows, "sleep.need_min").status, "REDUCED")
        self.assertEqual(metric(rows, "sleep.debt_min").value, 840)
        self.assertEqual(metric(rows, "sleep.debt_min").metadata["signed_balance_min"], -840)
        nights[d] = night(d, tst=600)
        self.assertEqual(metric(calculate_sleep_day(d, nights, EMPTY_PROFILE), "sleep.debt_min").value, 660)
        nights[d + timedelta(days=1)] = night(d + timedelta(days=1), tst=720)
        self.assertEqual(metric(calculate_sleep_day(d + timedelta(days=1), nights, EMPTY_PROFILE), "sleep.debt_min").value, 360)

    def test_no_lookahead_gaps_naps_and_cold_start(self):
        nights = {START + timedelta(days=i): night(START + timedelta(days=i)) for i in range(14)}
        d = START + timedelta(days=13)
        prior = metric(calculate_sleep_day(d, nights, EMPTY_PROFILE), "sleep.debt_min").value
        nights[d + timedelta(days=1)] = night(d + timedelta(days=1), tst=60)
        self.assertEqual(metric(calculate_sleep_day(d, nights, EMPTY_PROFILE), "sleep.debt_min").value, prior)
        self.assertEqual(metric(calculate_sleep_day(START, nights, EMPTY_PROFILE), "sleep.score").status, "CALIBRATING")
        self.assertIsNone(metric(calculate_sleep_day(START, nights, EMPTY_PROFILE), "sleep.debt_min").value)
        del nights[START + timedelta(days=4)]
        del nights[START + timedelta(days=5)]
        del nights[START + timedelta(days=6)]
        self.assertIsNone(metric(calculate_sleep_day(d, nights, EMPTY_PROFILE), "sleep.debt_min").value)
        self.assertEqual(metric(calculate_sleep_day(d, nights, EMPTY_PROFILE), "sleep.debt_min").metadata["longest_missing_gap"], 3)
        # Naps have no nightly main feature and are therefore absent from all three inputs.
        self.assertEqual(calculate_sleep_day(d + timedelta(days=2), nights, EMPTY_PROFILE), [])

    def test_missing_measured_zero_profile_and_correction(self):
        nights = {START + timedelta(days=i): night(START + timedelta(days=i)) for i in range(14)}
        d = START + timedelta(days=13)
        profile = {"schema_version": 1, "values": [{"field": "sleep_target_min", "value": 450,
                    "effective_from": START.isoformat()}]}
        self.assertEqual(metric(calculate_sleep_day(d, nights, profile), "sleep.need_min").status, "VALID")
        nights[d] = night(d, rem=None)
        self.assertEqual(metric(calculate_sleep_day(d, nights, profile), "sleep.score").status, "INSUFFICIENT_DATA")
        nights[d] = night(d, rem=0)
        self.assertIsNotNone(metric(calculate_sleep_day(d, nights, profile), "sleep.score").value)
        later = d + timedelta(days=1)
        nights[later] = night(later)
        before = metric(calculate_sleep_day(later, nights, profile), "sleep.debt_min").metadata["signed_balance_min"]
        nights[d] = night(d, tst=300, rem=0)
        after = metric(calculate_sleep_day(later, nights, profile), "sleep.debt_min").metadata["signed_balance_min"]
        self.assertEqual(after, before - 180)


if __name__ == "__main__":
    unittest.main()
