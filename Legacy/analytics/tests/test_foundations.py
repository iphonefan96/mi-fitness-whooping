from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from analytics.adapters.xiaomi import XiaomiAdapter
from analytics.features.foundations import build_nightly
from analytics.models import (BeatInterval, CapabilitySupport, DailyActivity, DeviceCapability, HRVMeasurement,
                              HeartRateSample, Provenance, QualityFlag, RestingHeartRate,
                              RespiratoryRateMeasurement, SleepSession, SleepStageInterval, SourceType, SpO2Measurement)
from analytics.normalization.core import (canonical_hash, freshness, input_fingerprint,
                                          local_date_for, sleep_date, utc_from_epoch)
from analytics.profile.config import load_profile
from analytics.runners.runner import run
from analytics.storage import db as storage_db


def _epoch(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def synthetic_source(path: Path) -> None:
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE etl_runs(run_id TEXT, finished_at TEXT, status TEXT);
    CREATE TABLE source_databases(source_db_id INTEGER, last_fingerprint TEXT,max_source_timestamp INTEGER);
    CREATE TABLE daily_summary(local_date TEXT PRIMARY KEY,steps INTEGER,step_calories REAL,total_calories REAL,
      activity_duration_minutes REAL,standing_count INTEGER,resting_hr REAL,updated_at TEXT);
    CREATE TABLE sleep_sessions(source_record_id TEXT PRIMARY KEY,sleep_start_utc INTEGER,sleep_end_utc INTEGER,
      local_date TEXT,utc_offset_seconds INTEGER,duration_minutes REAL,sleep_score REAL,has_stages INTEGER,
      is_nap_inferred INTEGER,avg_respiratory_rate REAL,imported_at TEXT);
    CREATE TABLE sleep_stages(source_record_id TEXT,stage_index INTEGER,raw_state INTEGER,
      start_timestamp_utc INTEGER,end_timestamp_utc INTEGER,duration_minutes REAL);
    CREATE TABLE heart_rate(source_record_id TEXT PRIMARY KEY,timestamp_utc INTEGER,local_date TEXT,utc_offset_seconds INTEGER,bpm REAL,
      kind TEXT,imported_at TEXT);
    CREATE TABLE spo2(source_record_id TEXT PRIMARY KEY,timestamp_utc INTEGER,local_date TEXT,utc_offset_seconds INTEGER,value REAL,imported_at TEXT);
    CREATE TABLE stress(source_record_id TEXT PRIMARY KEY,timestamp_utc INTEGER,local_date TEXT,utc_offset_seconds INTEGER,value REAL,imported_at TEXT);
    """)
    stamp = "2026-09-25T01:00:00Z"
    db.execute("INSERT INTO etl_runs VALUES (?,?,?)", ("run1", stamp, "SUCCESS"))
    db.execute("INSERT INTO source_databases VALUES (?,?,?)", (1, "abc", _epoch("2026-09-25T01:00:00")))
    add_night(db, "2026-09-25", "s1", stamp)
    db.commit()
    db.close()


def add_night(db: sqlite3.Connection, day: str, session_id: str, stamp: str) -> None:
    wake = datetime.fromisoformat(day).replace(tzinfo=timezone.utc).replace(hour=4)
    start = wake - timedelta(hours=8)
    db.execute("INSERT INTO daily_summary VALUES (?,?,?,?,?,?,?,?)",
               (day, 0, 0, 100, 20, 3, 55, stamp))
    db.execute("INSERT INTO sleep_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
               (session_id, int(start.timestamp()), int(wake.timestamp()), day, 0, 450, None, 1, 0, 16, stamp))
    # 7h30 asleep, 30 min awake inside the 8h interval.
    stages = [(2, 180), (3, 150), (5, 30), (4, 120)]
    cursor = start
    for index, (raw_state, minutes) in enumerate(stages):
        finish = cursor + timedelta(minutes=minutes)
        db.execute("INSERT INTO sleep_stages VALUES (?,?,?,?,?,?)",
                   (session_id, index, raw_state, int(cursor.timestamp()), int(finish.timestamp()), minutes))
        cursor = finish
    for index in range(0, 480, 10):
        ts = int((start + timedelta(minutes=index)).timestamp())
        db.execute("INSERT INTO heart_rate VALUES (?,?,?,?,?,?,?)", (f"{session_id}-hr-{index}", ts, datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), 0, 60, "auto", stamp))
        db.execute("INSERT INTO spo2 VALUES (?,?,?,?,?,?)", (f"{session_id}-ox-{index}", ts, datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), 0, 97, stamp))
    db.execute("INSERT INTO stress VALUES (?,?,?,?,?,?)", (f"{session_id}-stress", int(wake.timestamp()), day, 0, 12, stamp))


class FakeFitbitAdapter:
    """No Fitbit API: synthetic normalized signals with the same feature interface."""

    def __init__(self):
        self.wake = datetime(2026, 9, 25, 7, tzinfo=timezone.utc)
        self.start = self.wake - timedelta(hours=8)
        self.prov = lambda metric, rid, typ=SourceType.VENDOR_DERIVED: Provenance(
            source_provider="fitbit_fixture", source_device="fake_1", source_metric=metric,
            source_record_id=rid, source_type=typ)

    def capabilities(self):
        return (DeviceCapability(signal_kind="HRV", support=CapabilitySupport.SUPPORTED,
                                 origin=SourceType.VENDOR_DERIVED),)

    def sleep_sessions(self, start, end):
        if start <= self.wake < end:
            yield SleepSession(provenance=self.prov("sleep", "s1"), measurement_start=self.start,
                               measurement_end=self.wake, local_date=date(2026, 9, 25),
                               utc_offset_seconds=0, session_kind="main", has_stages=True)

    def sleep_stages(self, session):
        yield SleepStageInterval(provenance=self.prov("stage", "s1:0"), measurement_start=self.start,
                                 measurement_end=self.wake, local_date=date(2026, 9, 25),
                                 utc_offset_seconds=0, session_id="s1", stage_index=0,
                                 stage="light", raw_state=None, duration_min=480)

    def heart_rate(self, start, end):
        for i in range(480):
            ts = self.start + timedelta(minutes=i)
            if start <= ts < end:
                yield HeartRateSample(provenance=self.prov("hr", f"h{i}", SourceType.RAW_MEASUREMENT),
                                      measurement_start=ts, measurement_end=ts,
                                      local_date=date(2026, 9, 25), utc_offset_seconds=0, bpm=58)

    def spo2(self, start, end):
        for i in range(0, 480, 10):
            ts = self.start + timedelta(minutes=i)
            if start <= ts < end:
                yield SpO2Measurement(provenance=self.prov("spo2", f"o{i}", SourceType.RAW_MEASUREMENT),
                                      measurement_start=ts, measurement_end=ts,
                                      local_date=date(2026, 9, 25), utc_offset_seconds=0, percent=98)

    def resting_hr(self, start, end):
        if start <= date(2026, 9, 25) < end:
            yield RestingHeartRate(provenance=self.prov("rhr", "r1"), measurement_start=None,
                                   measurement_end=None, local_date=date(2026, 9, 25),
                                   utc_offset_seconds=0, bpm=54, method="vendor_daily")

    def respiratory(self, session):
        return RespiratoryRateMeasurement(provenance=self.prov("respiratory_rate", "br1"),
                                          measurement_start=self.start, measurement_end=self.wake,
                                          local_date=date(2026, 9, 25), utc_offset_seconds=0,
                                          breaths_per_min=15, aggregation="night_mean")

    def nightly_hrv(self, session=None):
        return HRVMeasurement(provenance=self.prov("rmssd", "v1"), measurement_start=self.start,
                              measurement_end=self.wake, local_date=date(2026, 9, 25),
                              utc_offset_seconds=0, metric="RMSSD", value=42, unit="ms",
                              evidence="DEVICE_REPORTED_HRV")


class FoundationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "health.sqlite"
        self.target = self.root / "analytics.sqlite"
        synthetic_source(self.source)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_only_and_mapping(self):
        before = self.source.read_bytes()
        with XiaomiAdapter(self.source) as adapter:
            night = list(adapter.sleep_sessions(utc_from_epoch(_epoch("2026-09-24T00:00:00")),
                                                utc_from_epoch(_epoch("2026-09-26T00:00:00"))))[0]
            self.assertEqual(night.local_date, date(2026, 9, 25))
            self.assertEqual(night.provenance.source_type, SourceType.VENDOR_DERIVED)
            self.assertEqual([s.stage for s in adapter.sleep_stages(night)], ["deep", "light", "awake", "rem"])
            activity = next(adapter.daily_activity(date(2026, 9, 25), date(2026, 9, 26)))
            self.assertEqual(activity.steps, 0)  # observed zero, not missing
            self.assertIsNone(activity.distance_m)  # source unit unknown
            self.assertFalse(any(c.signal_kind == "HRV" and c.support == CapabilitySupport.SUPPORTED
                                 for c in adapter.capabilities()))
            with self.assertRaises(sqlite3.OperationalError):
                adapter._db().execute("UPDATE daily_summary SET steps=1")
            adapter.assert_unchanged()
        self.assertEqual(before, self.source.read_bytes())

    def test_time_freshness_and_no_fake_hrv(self):
        self.assertEqual(sleep_date(datetime(2026, 9, 26, 7, tzinfo=timezone.utc), offset_seconds=0), date(2026, 9, 26))
        self.assertEqual(sleep_date(datetime(2026, 9, 26, 0, tzinfo=timezone.utc), offset_seconds=0), date(2026, 9, 25))
        self.assertEqual(local_date_for(datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc), zone="America/New_York"), date(2026, 11, 1))
        self.assertEqual(local_date_for(datetime(2025, 11, 23, 22, tzinfo=timezone.utc), offset_seconds=4*3600), date(2025, 11, 24))
        with self.assertRaises(ValueError):
            local_date_for(datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(freshness(date(2026, 6, 26), date(2026, 9, 25),
                                   as_of=datetime(2026, 9, 25, tzinfo=timezone.utc),
                                   last_end=datetime(2026, 6, 26, tzinfo=timezone.utc)).value, "STALE")
        fixture = FakeFitbitAdapter()
        self.assertEqual(fixture.nightly_hrv().evidence, "DEVICE_REPORTED_HRV")
        with self.assertRaises(ValueError):
            HRVMeasurement(provenance=fixture.prov("bad", "b"), measurement_start=fixture.start,
                           measurement_end=fixture.wake, local_date=date(2026, 9, 25),
                           utc_offset_seconds=0, metric="RMSSD", value=1000, unit="ms",
                           evidence="BPM_DERIVED")
        with self.assertRaises(ValueError):
            BeatInterval(provenance=fixture.prov("hr_bpm", "b", SourceType.RAW_MEASUREMENT),
                         measurement_start=fixture.start, measurement_end=fixture.start,
                         local_date=date(2026, 9, 25), utc_offset_seconds=0,
                         rr_ms=1000, evidence="BPM_DERIVED")

    def test_features_and_fitbit_contract(self):
        with XiaomiAdapter(self.source) as adapter:
            f = build_nightly(adapter, date(2026, 9, 25), normalization_version="v1", profile_revision="p1")
            self.assertEqual(f.values["tst_min"], 450)
            self.assertEqual(f.values["time_in_bed_min"], 480)
            self.assertEqual(f.values["spo2_mean_pct"], 97)
            self.assertIsNone(f.values["hrv_rmssd_ms"])
        other = build_nightly(FakeFitbitAdapter(), date(2026, 9, 25), normalization_version="v1", profile_revision="p1")
        self.assertEqual(other.values["tst_min"], 480)
        self.assertEqual(set(other.values), set(f.values))
        self.assertEqual(other.values["spo2_mean_pct"], 98)
        self.assertEqual(other.values["respiratory_rate_bpm"], 15)
        self.assertEqual(other.values["hrv_rmssd_ms"], 42)

    def test_idempotent_incremental_and_failure(self):
        first = run(self.source, self.target)
        self.assertEqual(first["status"], "SUCCESS")
        self.assertGreater(first["features_calculated"], 0)
        db = sqlite3.connect(self.target)
        n1 = db.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        metrics1 = db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0]
        self.assertGreater(metrics1, 0)
        sleep_names = {r[0] for r in db.execute("SELECT metric_name FROM active_metric_selection WHERE metric_name IN ('sleep.score','sleep.need_min','sleep.debt_min')")}
        self.assertEqual(sleep_names, {"sleep.score", "sleep.need_min", "sleep.debt_min"})
        self.assertEqual(db.execute("SELECT status FROM derived_metric_results WHERE metric_name='sleep.need_min' ORDER BY result_id DESC LIMIT 1").fetchone()[0], "REDUCED")
        self.assertLess(db.execute("SELECT MAX(length(source_signals_json)) FROM derived_metric_results").fetchone()[0], 500)
        db.close()

        second = run(self.source, self.target)
        self.assertEqual(second["status"], "NO NEW ANALYTICS INPUT")
        db = sqlite3.connect(self.target)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0], n1)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM derived_metric_results").fetchone()[0], metrics1)
        db.close()
        db = sqlite3.connect(self.source)
        add_night(db, "2026-09-26", "s2", "2026-09-26T06:00:00Z")
        db.execute("UPDATE source_databases SET last_fingerprint='def',max_source_timestamp=?", (_epoch("2026-09-26T06:00:00"),))
        db.execute("INSERT INTO etl_runs VALUES (?,?,?)", ("run2", "2026-09-26T06:00:00Z", "SUCCESS"))
        db.commit(); db.close()
        third = run(self.source, self.target)
        self.assertEqual(third["status"], "SUCCESS")
        self.assertLess(third["dirty_dates"], 10)
        db = sqlite3.connect(self.target)
        n2 = db.execute("SELECT COUNT(*) FROM features").fetchone()[0]
        self.assertGreater(n2, n1)
        old_state = db.execute("SELECT value FROM analytics_state WHERE key='source_file_fingerprint'").fetchone()[0]
        db.close()
        db = sqlite3.connect(self.source)
        db.execute("UPDATE sleep_stages SET raw_state=3 WHERE source_record_id='s2' AND stage_index=3")
        db.execute("UPDATE sleep_sessions SET imported_at='2026-09-26T07:00:00Z' WHERE source_record_id='s2'")
        db.commit(); db.close()
        with patch("analytics.runners.runner.build_nightly", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                run(self.source, self.target)
        db = sqlite3.connect(self.target)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM features").fetchone()[0], n2)
        self.assertEqual(db.execute("SELECT value FROM analytics_state WHERE key='source_file_fingerprint'").fetchone()[0], old_state)
        db.close()
        fourth = run(self.source, self.target)
        self.assertEqual(fourth["status"], "SUCCESS")
        db = sqlite3.connect(self.target)
        self.assertGreater(db.execute("SELECT COUNT(*) FROM features").fetchone()[0], n2)
        db.close()

    def test_sleep_algorithm_version_creates_provenance_revision(self):
        run(self.source, self.target)
        db = sqlite3.connect(self.target)
        prior = db.execute("SELECT result_id FROM active_metric_selection WHERE metric_name='sleep.need_min'").fetchone()[0]
        db.close()
        with patch("analytics.runners.runner.SLEEP_ALGORITHM_VERSION", "sleep-test-next"), \
             patch("analytics.algorithms.sleep.SLEEP_ALGORITHM_VERSION", "sleep-test-next"):
            changed = run(self.source, self.target)
        self.assertEqual(changed["status"], "SUCCESS")
        db = sqlite3.connect(self.target)
        current = db.execute("SELECT result_id FROM active_metric_selection WHERE metric_name='sleep.need_min'").fetchone()[0]
        self.assertNotEqual(prior, current)
        versions = {r[0] for r in db.execute("SELECT algorithm_version FROM derived_metric_results WHERE metric_name='sleep.need_min'")}
        self.assertEqual(versions, {"sleep-1", "sleep-test-next"})
        db.close()

    def test_recovery_algorithm_version_creates_provenance_revision(self):
        run(self.source, self.target)
        db = sqlite3.connect(self.target)
        prior = db.execute("SELECT result_id FROM active_metric_selection WHERE metric_name='recovery.score'").fetchone()[0]
        db.close()
        with patch("analytics.runners.runner.RECOVERY_ALGORITHM_VERSION", "recovery-test-next"), \
             patch("analytics.algorithms.recovery.RECOVERY_ALGORITHM_VERSION", "recovery-test-next"):
            changed = run(self.source, self.target)
        self.assertEqual(changed["status"], "SUCCESS")
        db = sqlite3.connect(self.target)
        current = db.execute("SELECT result_id FROM active_metric_selection WHERE metric_name='recovery.score'").fetchone()[0]
        self.assertNotEqual(prior, current)
        self.assertEqual({r[0] for r in db.execute("SELECT algorithm_version FROM derived_metric_results WHERE metric_name='recovery.score'")},
                         {"vitals-anchored-v3-local-gates-2", "recovery-test-next"})
        db.close()

    def test_profile_and_fingerprint(self):
        self.assertEqual(canonical_hash({"a": 1, "b": 2}), canonical_hash({"b": 2, "a": 1}))
        params = {"normalized_inputs": {"hr_bpm": 60}, "profile_revision": "p1",
                  "normalization_version": "n1", "algorithm_id": "feature.test",
                  "algorithm_version": "1", "input_contract_version": "c1",
                  "implementation_version": "i1"}
        self.assertEqual(input_fingerprint(**params), input_fingerprint(**params))
        self.assertNotEqual(input_fingerprint(**params), input_fingerprint(**(params | {"input_contract_version": "c2"})))
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"schema_version": 1, "values": []}))
        _, revision1 = load_profile(profile)
        run(self.source, self.target, profile)
        profile.write_text(json.dumps({"schema_version": 1, "values": [
            {"field": "weight_kg", "value": 70, "effective_from": "2026-09-01"}]}))
        _, revision2 = load_profile(profile)
        self.assertNotEqual(revision1, revision2)
        result = run(self.source, self.target, profile)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertGreater(result["features_calculated"], 0)
        self.assertEqual(run(self.root / "absent.sqlite", self.target)["reason"], "SOURCE_UNAVAILABLE")

    def test_version_bump_promotes_all_features(self):
        first = run(self.source, self.target)
        self.assertEqual(first["features_calculated"], 2)
        with patch("analytics.runners.runner.IMPLEMENTATION_VERSION", "test-next"), \
             patch.object(storage_db, "IMPLEMENTATION_VERSION", "test-next"), \
             patch("analytics.features.foundations.IMPLEMENTATION_VERSION", "test-next"):
            changed = run(self.source, self.target)
            self.assertEqual(changed["features_calculated"], 2)
            db = sqlite3.connect(self.target)
            versions = db.execute("SELECT DISTINCT f.implementation_version FROM active_features a JOIN features f ON f.feature_id=a.feature_id").fetchall()
            self.assertEqual(versions, [("test-next",)])
            db.close()

    def test_historical_correction_recomputes_future_baseline(self):
        db = sqlite3.connect(self.source)
        for day_number in range(26, 31):
            add_night(db, f"2026-09-{day_number}", f"s{day_number}", "2026-10-01T01:00:00Z")
        for day_number in range(1, 5):
            add_night(db, f"2026-10-{day_number:02d}", f"so{day_number}", "2026-10-05T01:00:00Z")
        db.execute("UPDATE source_databases SET max_source_timestamp=?", (_epoch("2026-10-05T01:00:00"),))
        db.commit(); db.close()
        first = run(self.source, self.target)
        self.assertGreater(first["metrics_calculated"], 0)
        db = sqlite3.connect(self.target)
        old = db.execute("""SELECT r.input_fingerprint,r.value FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE a.metric_date='2026-10-04' AND a.metric_name='baseline.rhr.band_mean'""").fetchone()
        total_dates = db.execute("SELECT COUNT(DISTINCT metric_date) FROM active_features").fetchone()[0]
        db.close()
        self.assertIsNotNone(old[1])
        db = sqlite3.connect(self.source)
        db.execute("UPDATE daily_summary SET resting_hr=65,updated_at='2026-10-06T01:00:00Z' WHERE local_date='2026-09-28'")
        db.commit(); db.close()
        changed = run(self.source, self.target)
        self.assertEqual(changed["status"], "SUCCESS")
        self.assertLess(changed["dirty_dates"], total_dates)
        self.assertGreater(changed["metrics_calculated"], 0)
        db = sqlite3.connect(self.target)
        new = db.execute("""SELECT r.input_fingerprint,r.value FROM active_metric_selection a
            JOIN derived_metric_results r ON r.result_id=a.result_id
            WHERE a.metric_date='2026-10-04' AND a.metric_name='baseline.rhr.band_mean'""").fetchone()
        db.close()
        self.assertNotEqual(old[0], new[0])
        self.assertGreater(new[1], old[1])


if __name__ == "__main__":
    unittest.main()
