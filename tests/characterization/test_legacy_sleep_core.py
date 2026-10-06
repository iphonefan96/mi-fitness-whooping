"""Synthetic, observable contracts for the immutable Legacy sleep core.

Run with: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/characterization
The import path points at Legacy as an oracle; this file is not a target implementation.
"""

from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


LEGACY = Path(__file__).resolve().parents[2] / "Legacy"
sys.path.insert(0, str(LEGACY))

from analytics.__main__ import sleep_headline  # noqa: E402
from analytics.algorithms.foundations import FeatureRecord  # noqa: E402
from analytics.algorithms.sleep import (  # noqa: E402
    SleepScoreInput,
    calculate_sleep_day,
    score_components,
)
from analytics.models import Freshness  # noqa: E402
from analytics.normalization.core import freshness  # noqa: E402
from analytics.profile.config import load_profile  # noqa: E402
from analytics.runners.runner import run  # noqa: E402
from analytics.storage.db import connect, migrate, put_result  # noqa: E402
from analytics.tests.test_foundations import synthetic_source  # noqa: E402


START = date(2026, 1, 1)
PROFILE = {"schema_version": 1, "values": []}


def night(day: date, **changes: object) -> FeatureRecord:
    values = {
        "tst_min": 480,
        "deep_min": 90,
        "rem_min": 90,
        "waso_min": 0,
        "awakening_durations_min": (),
        "stage_coverage": "COMPLETE",
        "bedtime_local_min": 1380,
    }
    values.update(changes)
    return FeatureRecord("nightly", day, values, f"night:{day.isoformat()}", 1,
                         "synthetic-source", None, None)


def nights(count: int = 14, **changes: object) -> dict[date, FeatureRecord]:
    return {START + timedelta(days=i): night(START + timedelta(days=i), **changes)
            for i in range(count)}


def result(rows, name: str):
    return next(row for row in rows if row.name == name)


def target_profile(value: int, begin: date = START, end: date | None = None) -> dict:
    entry = {"field": "sleep_target_min", "value": value,
             "effective_from": begin.isoformat()}
    if end is not None:
        entry["effective_to"] = end.isoformat()
    return {"schema_version": 1, "values": [entry]}


class SleepScoreContracts(unittest.TestCase):
    def test_no_main_night_produces_no_sleep_core_metrics(self):
        self.assertEqual(calculate_sleep_day(START, {}, PROFILE), [])

    def test_complete_night_pins_result_shape_components_and_lineage(self):
        history = nights()
        day = START + timedelta(days=13)
        rows = calculate_sleep_day(day, history, PROFILE)
        self.assertEqual([row.name for row in rows],
                         ["sleep.score", "sleep.need_min", "sleep.debt_min"])
        score = result(rows, "sleep.score")
        self.assertEqual((score.value, score.unit, score.status), (100, "score", "VALID"))
        self.assertEqual((score.algorithm_id, score.algorithm_version, score.source_type),
                         ("sleep.open_wearables_four_pillar_v1", "sleep-1", "OUR_DERIVED"))
        self.assertEqual((score.upstream_project, score.upstream_commit, score.confidence),
                         ("Open Wearables", "fd78bdd3b8ed162e6716ba9c5fa2613dac005a40", "MEDIUM"))
        self.assertEqual(score.metadata, {
            "mode": "FULL",
            "components": {"duration": 100, "stages": 100,
                           "consistency": 100, "interruptions": 100},
            "history_count": 13,
            "required_history_count": 5,
            "history_window_calendar_nights": 14,
        })
        self.assertEqual([record.day for record in score.inputs],
                         [day, *(START + timedelta(days=i) for i in range(13))])
        self.assertEqual(calculate_sleep_day(day, history, PROFILE), rows)

    def test_history_window_and_calibration_boundary(self):
        day = START + timedelta(days=20)
        history = {day: night(day)}
        for offset in (15, 4, 3, 2, 1):
            previous = day - timedelta(days=offset)
            history[previous] = night(previous)
        score = result(calculate_sleep_day(day, history, PROFILE), "sleep.score")
        self.assertEqual((score.value, score.status, score.metadata["history_count"]),
                         (None, "CALIBRATING", 4))
        self.assertEqual(score.metadata["components"], None)
        self.assertEqual(score.metadata["mode"], None)
        fifth = day - timedelta(days=14)
        history[fifth] = night(fifth)
        score = result(calculate_sleep_day(day, history, PROFILE), "sleep.score")
        self.assertEqual((score.value, score.status, score.metadata["history_count"]),
                         (100, "VALID", 5))

    def test_incomplete_stage_missing_zero_and_invalid_have_distinct_statuses(self):
        history = nights()
        day = START + timedelta(days=13)
        cases = [
            ({"stage_coverage": "UNKNOWN"}, None, "INSUFFICIENT_DATA"),
            ({"rem_min": None}, None, "INSUFFICIENT_DATA"),
            ({"rem_min": 0}, 90, "VALID"),
            ({"tst_min": 0}, None, "INVALID"),
            ({"bedtime_local_min": None}, None, "INVALID"),
            ({"awakening_durations_min": (None,)}, None, "INVALID"),
        ]
        for changes, expected_value, expected_status in cases:
            with self.subTest(changes=changes):
                history[day] = night(day, **changes)
                score = result(calculate_sleep_day(day, history, PROFILE), "sleep.score")
                self.assertEqual((score.value, score.status),
                                 (expected_value, expected_status))

    def test_component_and_weighting_boundaries_are_observable(self):
        base = dict(day=START, tst_min=480, deep_min=90, rem_min=90,
                    bedtime_local_min=1380, prior_bedtimes_local_min=(1380,) * 5,
                    waso_min=0, awakening_durations_min=(), stage_coverage="COMPLETE")
        cases = [
            ({"tst_min": 420}, {"duration": 100, "stages": 100,
                                "consistency": 100, "interruptions": 100}),
            ({"tst_min": 540}, {"duration": 100, "stages": 100,
                                "consistency": 100, "interruptions": 100}),
            ({"tst_min": 720}, {"duration": 50, "stages": 100,
                                "consistency": 100, "interruptions": 100}),
            ({"deep_min": 0}, {"duration": 100, "stages": 50,
                               "consistency": 100, "interruptions": 100}),
            ({"bedtime_local_min": 60}, {"duration": 100, "stages": 100,
                                          "consistency": 0, "interruptions": 100}),
            ({"waso_min": 80, "awakening_durations_min": (10, 10, 10, 10)},
             {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 11}),
            ({"awakening_durations_min": (5, 5)},
             {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 100}),
            ({"bedtime_local_min": 1395},
             {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 100}),
            ({"bedtime_local_min": 1396},
             {"duration": 100, "stages": 100, "consistency": 99, "interruptions": 100}),
            ({"waso_min": 20},
             {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 100}),
            ({"waso_min": 20.01},
             {"duration": 100, "stages": 100, "consistency": 100, "interruptions": 99}),
        ]
        for change, expected in cases:
            with self.subTest(change=change):
                self.assertEqual(score_components(SleepScoreInput(**(base | change))), expected)
        self.assertIsNone(score_components(SleepScoreInput(**(base | {"deep_min": 400}))))
        self.assertIsNone(score_components(SleepScoreInput(**(base | {"prior_bedtimes_local_min": (1380,) * 4}))))
        history = nights()
        day = START + timedelta(days=13)
        history[day] = night(day, tst_min=720)
        # The dated calculation applies the integer weighted score to the components.
        self.assertEqual(result(calculate_sleep_day(day, history, PROFILE), "sleep.score").value, 80)


class SleepNeedContracts(unittest.TestCase):
    def test_default_need_is_fixed_target_with_pinned_status_metadata_and_provenance(self):
        day = START
        need = result(calculate_sleep_day(day, {day: night(day)}, PROFILE), "sleep.need_min")
        self.assertEqual((need.value, need.unit, need.status), (480.0, "min", "REDUCED"))
        self.assertEqual((need.algorithm_id, need.algorithm_version, need.source_type),
                         ("sleep.fixed_target_v1", "sleep-1", "OUR_DERIVED"))
        self.assertEqual((need.upstream_project, need.upstream_commit),
                         ("Vitals", "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"))
        self.assertEqual(need.metadata, {"mode": "PROVISIONAL_DEFAULT",
                                         "default_target": True,
                                         "physiological_estimate": False})
        self.assertEqual(need.inputs, (night(day),))

    def test_effective_dates_and_configured_target_bounds(self):
        day = START + timedelta(days=2)
        history = nights(3)
        profile = {"schema_version": 1, "values": [
            {"field": "sleep_target_min", "value": 300,
             "effective_from": START.isoformat(), "effective_to": START.isoformat()},
            {"field": "sleep_target_min", "value": 720,
             "effective_from": day.isoformat()},
        ]}
        first = result(calculate_sleep_day(START, history, profile), "sleep.need_min")
        middle = result(calculate_sleep_day(START + timedelta(days=1), history, profile), "sleep.need_min")
        last = result(calculate_sleep_day(day, history, profile), "sleep.need_min")
        self.assertEqual((first.value, first.status), (300.0, "VALID"))
        self.assertEqual((middle.value, middle.status), (480.0, "REDUCED"))
        self.assertEqual((last.value, last.status), (720.0, "VALID"))
        self.assertEqual(last.metadata, {"mode": "USER_TARGET", "default_target": False,
                                         "physiological_estimate": False})

    def test_missing_profile_file_and_invalid_profile_state(self):
        with tempfile.TemporaryDirectory() as directory:
            profile, revision = load_profile(Path(directory) / "absent.json")
            self.assertEqual(profile, PROFILE)
            self.assertEqual(len(revision), 64)
            invalid_path = Path(directory) / "invalid.json"
            invalid_path.write_text('{"schema_version":2,"values":[]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported profile schema"):
                load_profile(invalid_path)
        day = START
        for invalid in (299, 721, 0):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "300..720"):
                calculate_sleep_day(day, {day: night(day)}, target_profile(invalid))


class SleepDebtContracts(unittest.TestCase):
    def test_fourteen_calendar_nights_signed_balance_and_nonnegative_output(self):
        history = nights(tst_min=420)
        day = START + timedelta(days=13)
        debt = result(calculate_sleep_day(day, history, PROFILE), "sleep.debt_min")
        self.assertEqual((debt.value, debt.unit, debt.status), (840.0, "min", "REDUCED"))
        self.assertEqual((debt.algorithm_id, debt.algorithm_version, debt.source_type),
                         ("sleep.signed_14_calendar_night_ledger_v1", "sleep-1", "OUR_DERIVED"))
        self.assertEqual((debt.upstream_project, debt.upstream_commit), (None, None))
        self.assertEqual(debt.metadata, {
            "mode": "PROVISIONAL_DEFAULT", "default_target": True,
            "signed_balance_min": -840.0, "history_count": 14,
            "required_history_count": 10, "longest_missing_gap": 0,
            "window_calendar_nights": 14,
        })
        self.assertEqual([record.day for record in debt.inputs],
                         [START + timedelta(days=i) for i in range(14)])
        history[day] = night(day, tst_min=600)
        self.assertEqual(result(calculate_sleep_day(day, history, PROFILE),
                                "sleep.debt_min").value, 660.0)
        surplus = nights(tst_min=600)
        debt = result(calculate_sleep_day(day, surplus, PROFILE), "sleep.debt_min")
        self.assertEqual((debt.value, debt.metadata["signed_balance_min"]), (0, 1680.0))

    def test_ten_valid_nights_and_two_gap_pass_but_nine_or_three_gap_calibrate(self):
        day = START + timedelta(days=13)
        for missing, expected_count, expected_gap, expected_status in (
            ({0, 3, 6, 9}, 10, 1, "REDUCED"),
            ({0, 2, 4, 6, 8}, 9, 1, "CALIBRATING"),
            ({3, 4}, 12, 2, "REDUCED"),
            ({3, 4, 5}, 11, 3, "CALIBRATING"),
        ):
            with self.subTest(missing=missing):
                history = nights()
                for i in missing:
                    del history[START + timedelta(days=i)]
                debt = result(calculate_sleep_day(day, history, PROFILE), "sleep.debt_min")
                self.assertEqual(debt.status, expected_status)
                self.assertEqual(debt.metadata["history_count"], expected_count)
                self.assertEqual(debt.metadata["longest_missing_gap"], expected_gap)
                self.assertEqual(debt.value, 0 if expected_status == "REDUCED" else None)

    def test_zero_or_incomplete_tst_is_missing_not_zero_contribution(self):
        day = START + timedelta(days=13)
        for change in ({"tst_min": 0}, {"tst_min": None}, {"stage_coverage": "UNKNOWN"}):
            with self.subTest(change=change):
                history = nights()
                history[day] = night(day, **change)
                debt = result(calculate_sleep_day(day, history, PROFILE), "sleep.debt_min")
                self.assertEqual((debt.value, debt.metadata["history_count"],
                                  debt.metadata["longest_missing_gap"]), (0, 13, 1))
                self.assertNotIn(day, [record.day for record in debt.inputs])

    def test_effective_targets_and_default_anywhere_in_ledger(self):
        day = START + timedelta(days=13)
        history = nights()
        full = target_profile(450)
        debt = result(calculate_sleep_day(day, history, full), "sleep.debt_min")
        self.assertEqual((debt.status, debt.value, debt.metadata["signed_balance_min"]),
                         ("VALID", 0, 420.0))
        partial = target_profile(450, begin=START + timedelta(days=7))
        debt = result(calculate_sleep_day(day, history, partial), "sleep.debt_min")
        need = result(calculate_sleep_day(day, history, partial), "sleep.need_min")
        self.assertEqual((need.value, need.status), (450.0, "VALID"))
        self.assertEqual((debt.value, debt.status, debt.metadata["signed_balance_min"]),
                         (0, "REDUCED", 210.0))
        self.assertTrue(debt.metadata["default_target"])

    def test_window_excludes_older_and_future_nights_but_historical_correction_changes_balance(self):
        day = START + timedelta(days=20)
        history = {day - timedelta(days=i): night(day - timedelta(days=i)) for i in range(14)}
        history[day - timedelta(days=14)] = night(day - timedelta(days=14), tst_min=1)
        history[day + timedelta(days=1)] = night(day + timedelta(days=1), tst_min=1)
        before = result(calculate_sleep_day(day, history, PROFILE), "sleep.debt_min")
        self.assertEqual((before.value, before.metadata["signed_balance_min"]), (0, 0.0))
        changed = day - timedelta(days=3)
        history[changed] = night(changed, tst_min=300)
        after = result(calculate_sleep_day(day, history, PROFILE), "sleep.debt_min")
        self.assertEqual((after.value, after.metadata["signed_balance_min"]), (180.0, -180.0))


class PersistenceAndFreshnessContracts(unittest.TestCase):
    def test_runner_freshness_is_written_at_run_time_but_headline_is_query_time(self):
        first_clock = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        later_clock = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)

        def fixed_datetime(instant):
            class FixedDateTime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return instant.astimezone(tz) if tz is not None else instant

            return FixedDateTime

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "health.sqlite"
            target = Path(directory) / "analytics.sqlite"
            synthetic_source(source)
            with patch("analytics.runners.runner.datetime", fixed_datetime(first_clock)):
                self.assertEqual(run(source, target)["status"], "SUCCESS")
            with sqlite3.connect(target) as db:
                stored = db.execute("""SELECT r.freshness_status,r.status FROM active_metric_selection a
                    JOIN derived_metric_results r ON r.result_id=a.result_id
                    WHERE r.metric_name='sleep.need_min'""").fetchone()
                self.assertEqual(stored, ("FRESH", "REDUCED"))
            with patch("analytics.runners.runner.datetime", fixed_datetime(later_clock)):
                self.assertEqual(run(source, target)["status"], "NO NEW ANALYTICS INPUT")
            with sqlite3.connect(target) as db:
                self.assertEqual(db.execute("""SELECT r.freshness_status FROM active_metric_selection a
                    JOIN derived_metric_results r ON r.result_id=a.result_id
                    WHERE r.metric_name='sleep.need_min'""").fetchone()[0], "FRESH")
            query_status = freshness(date(2026, 9, 25), later_clock.date(),
                                     as_of=later_clock,
                                     last_end=datetime(2026, 9, 25, 4, tzinfo=timezone.utc))
            self.assertEqual(query_status, Freshness.STALE)
            self.assertIsNone(sleep_headline("2026-09-25", query_status.value,
                                               {"sleep.need_min": {"value": 480, "status": "REDUCED"}})["need_min"])

    def test_active_selection_rerun_revision_and_version_identity(self):
        day = START + timedelta(days=13)
        draft = result(calculate_sleep_day(day, nights(), PROFILE), "sleep.need_min")
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                self.assertTrue(put_result(db, draft, run_id="run-1", profile_revision="profile-v1",
                                           freshness_status="HISTORICAL"))
                first = db.execute("SELECT result_id,input_fingerprint,algorithm_version FROM derived_metric_results").fetchone()
                self.assertEqual(first["algorithm_version"], "sleep-1")
                self.assertFalse(put_result(db, draft, run_id="run-2", profile_revision="profile-v1",
                                            freshness_status="HISTORICAL"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT result_id FROM active_metric_selection").fetchone()[0], first["result_id"])
                changed = replace(draft, value=450.0)
                self.assertTrue(put_result(db, changed, run_id="run-3", profile_revision="profile-v1",
                                           freshness_status="HISTORICAL"))
                second = db.execute("SELECT result_id,input_fingerprint,supersedes_result_id FROM derived_metric_results ORDER BY result_id DESC LIMIT 1").fetchone()
                self.assertNotEqual(second["input_fingerprint"], first["input_fingerprint"])
                self.assertEqual(second["supersedes_result_id"], first["result_id"])
                self.assertEqual(db.execute("SELECT result_id FROM active_metric_selection").fetchone()[0], second["result_id"])
                self.assertTrue(put_result(db, changed, run_id="run-4", profile_revision="profile-v2",
                                           freshness_status="HISTORICAL"))
                self.assertTrue(put_result(db, replace(changed, algorithm_version="sleep-2"),
                                           run_id="run-5", profile_revision="profile-v2",
                                           freshness_status="HISTORICAL"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0], 4)
            finally:
                db.close()

    def test_explicit_freshness_transition_does_not_create_a_new_result_identity(self):
        day = START + timedelta(days=13)
        draft = result(calculate_sleep_day(day, nights(), PROFILE), "sleep.need_min")
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "analytics.sqlite")
            try:
                migrate(db)
                self.assertTrue(put_result(db, draft, run_id="run-1", profile_revision="profile-v1",
                                           freshness_status="FRESH"))
                first = db.execute("SELECT result_id FROM active_metric_selection").fetchone()[0]
                # Observed Legacy behavior: the call reports a change, but the
                # unique fingerprint reselects the existing row and leaves its
                # stored freshness as FRESH. This is a migration risk, not a
                # proposed policy for a future presentation layer.
                self.assertTrue(put_result(db, draft, run_id="run-2", profile_revision="profile-v1",
                                           freshness_status="HISTORICAL"))
                self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT result_id FROM active_metric_selection").fetchone()[0], first)
                self.assertEqual(db.execute("SELECT freshness_status FROM derived_metric_results").fetchone()[0], "FRESH")
            finally:
                db.close()

    def test_fixed_clock_freshness_and_headline_transitions(self):
        day = date(2026, 1, 14)
        end = datetime(2026, 1, 14, 8, tzinfo=timezone.utc)
        at_limit = end + timedelta(hours=36)
        self.assertEqual(freshness(day, day, as_of=at_limit, last_end=end), Freshness.FRESH)
        self.assertEqual(freshness(day, day, as_of=at_limit + timedelta(microseconds=1),
                                   last_end=end), Freshness.STALE)
        self.assertEqual(freshness(day, day + timedelta(days=1), as_of=end,
                                   last_end=end), Freshness.STALE)
        self.assertEqual(freshness(day, day, as_of=end - timedelta(seconds=1),
                                   last_end=end), Freshness.STALE)
        self.assertEqual(freshness(day, day, as_of=at_limit, last_end=end,
                                   current_query=False), Freshness.HISTORICAL)
        self.assertEqual(freshness(None, day, as_of=at_limit, last_end=end), Freshness.MISSING)
        self.assertEqual(freshness(day, day, as_of=at_limit, last_end=None), Freshness.MISSING)
        values = {
            "sleep.score": {"value": 88, "status": "VALID"},
            "sleep.need_min": {"value": 480, "status": "REDUCED"},
            "sleep.debt_min": {"value": 120, "status": "VALID"},
        }
        fresh = sleep_headline(day.isoformat(), "FRESH", values)
        self.assertEqual((fresh["score"], fresh["need_min"], fresh["debt_min"]), (88, 480, 120))
        for state in ("STALE", "HISTORICAL", "MISSING"):
            with self.subTest(state=state):
                hidden = sleep_headline(day.isoformat(), state, values)
                self.assertEqual((hidden["score"], hidden["need_min"], hidden["debt_min"]),
                                 (None, None, None))
                self.assertEqual(hidden["last_historical_statuses"],
                                 {"sleep.score": "VALID", "sleep.need_min": "REDUCED",
                                  "sleep.debt_min": "VALID"})


if __name__ == "__main__":
    unittest.main()
