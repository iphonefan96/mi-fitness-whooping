"""Mi Fitness normalized SQLite adapter. This module never writes to source."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from mi_fitness_whooping.baseline.source_base import SourceAdapter
from mi_fitness_whooping.baseline.models import (CapabilitySupport, DailyActivity, DeviceCapability, HeartRateSample,
                              Provenance, QualityFlag, QualityStatus, RespiratoryRateMeasurement,
                              RestingHeartRate, SleepSession, SleepStageInterval, SourceType,
                              SpO2Measurement, VendorMetric, Workout)
from mi_fitness_whooping.baseline.normalization import canonical_hash, local_date_for, sleep_date, utc_from_epoch


PROVIDER = "xiaomi_mi_fitness"
UNKNOWN_DEVICE = "unknown_device"


def _prov(metric: str, record_id: str, source_type: SourceType) -> Provenance:
    return Provenance(source_provider=PROVIDER, source_device=UNKNOWN_DEVICE,
                      source_metric=metric, source_record_id=str(record_id), source_type=source_type)


class XiaomiAdapter(SourceAdapter):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None
        self.immutable_fallback = False
        self._file_before: tuple | None = None

    def file_fingerprint(self) -> tuple:
        def part(p: Path) -> tuple | None:
            if not p.exists():
                return None
            s = p.stat()
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        return tuple(part(Path(str(self.path) + suffix)) for suffix in ("", "-wal", "-shm"))

    def __enter__(self) -> "XiaomiAdapter":
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self._file_before = self.file_fingerprint()
        uri = self.path.resolve().as_uri()
        try:
            conn = sqlite3.connect(uri + "?mode=ro", uri=True)
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            if self._file_before[1] is not None or self._file_before[2] is not None:
                raise RuntimeError("read-only source WAL cannot be opened safely")
            # immutable avoids creating -shm in a protected source directory;
            # pre/post file fingerprints are mandatory for this fallback.
            conn = sqlite3.connect(uri + "?mode=ro&immutable=1", uri=True)
            self.immutable_fallback = True
        self.connection = conn
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("BEGIN")
        return self

    def __exit__(self, *_: object) -> None:
        if self.connection is not None:
            self.connection.rollback()
            self.connection.close()
            self.connection = None

    def assert_unchanged(self) -> None:
        if self._file_before != self.file_fingerprint():
            raise RuntimeError("SOURCE_CHANGED_DURING_ANALYTICS_RUN")

    def _db(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("use XiaomiAdapter as a context manager")
        return self.connection

    def generation(self) -> str:
        # A read-transaction sees one consistent ETL generation. Metadata check is cheap.
        row = self._db().execute("SELECT run_id, finished_at, status FROM etl_runs WHERE status='SUCCESS' ORDER BY finished_at DESC LIMIT 1").fetchone()
        sources = self._db().execute("SELECT source_db_id,last_fingerprint,max_source_timestamp FROM source_databases ORDER BY source_db_id").fetchall()
        return canonical_hash({"run": tuple(row) if row else None,
                               "sources": [tuple(r) for r in sources]})

    def capabilities(self) -> tuple[DeviceCapability, ...]:
        entries = [
            ("HR", True, SourceType.RAW_MEASUREMENT, 60),
            ("RHR", True, SourceType.VENDOR_DERIVED, None),
            ("SPO2", True, SourceType.RAW_MEASUREMENT, 600),
            ("SLEEP", True, SourceType.VENDOR_DERIVED, None),
            ("SLEEP_STAGES", True, SourceType.VENDOR_DERIVED, None),
            ("RESPIRATORY_RATE", True, SourceType.VENDOR_DERIVED, None),
            ("STRESS_VENDOR", True, SourceType.VENDOR_DERIVED, 300),
            ("STEPS", True, SourceType.VENDOR_DERIVED, None),
            ("WORKOUT", True, SourceType.VENDOR_DERIVED, None),
            ("HRV", False, None, None), ("RR", False, None, None),
            ("SKIN_TEMP", False, None, None), ("RAW_ACCEL", False, None, None),
            ("WORKOUT_HR_DENSE", False, None, None),
        ]
        return tuple(DeviceCapability(signal_kind=k, support=CapabilitySupport.SUPPORTED if yes else CapabilitySupport.UNSUPPORTED,
                                      origin=origin, resolution_seconds=resolution) for k, yes, origin, resolution in entries)

    def read(self, signal_kind: str, start: datetime | date, end: datetime | date) -> Iterator:
        routes = {
            "HEART_RATE_SAMPLE": self.heart_rate,
            "SPO2_SAMPLE": self.spo2,
            "SLEEP_SESSION": self.sleep_sessions,
            "DAILY_ACTIVITY": self.daily_activity,
            "RESTING_HR": self.resting_hr,
            "VENDOR_STRESS": self.stress,
            "WORKOUT": self.workouts,
        }
        if signal_kind not in routes:
            raise NotImplementedError(signal_kind)
        yield from routes[signal_kind](start, end)

    @staticmethod
    def _epoch_bounds(start: datetime | date, end: datetime | date) -> tuple[int, int]:
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise TypeError("timestamped reader requires aware datetimes")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("naive time bounds")
        return int(start.timestamp()), int(end.timestamp())

    def heart_rate(self, start: datetime, end: datetime) -> Iterator[HeartRateSample]:
        lo, hi = self._epoch_bounds(start, end)
        sql = "SELECT source_record_id,timestamp_utc,utc_offset_seconds,bpm,kind FROM heart_rate WHERE timestamp_utc>=? AND timestamp_utc<? ORDER BY timestamp_utc,source_record_id"
        for r in self._db().execute(sql, (lo, hi)):
            ts = utc_from_epoch(r["timestamp_utc"])
            bpm = float(r["bpm"])
            flags = frozenset({QualityFlag.INVALID}) if not 25 <= bpm <= 240 else frozenset()
            yield HeartRateSample(provenance=_prov("heart_rate.bpm", r["source_record_id"], SourceType.RAW_MEASUREMENT),
                                  measurement_start=ts, measurement_end=ts,
                                  local_date=local_date_for(ts, offset_seconds=r["utc_offset_seconds"]),
                                  utc_offset_seconds=r["utc_offset_seconds"], bpm=bpm,
                                  context=r["kind"] or "auto", quality_flags=flags,
                                  quality_status=QualityStatus.INVALID if flags else QualityStatus.OK)

    def spo2(self, start: datetime, end: datetime) -> Iterator[SpO2Measurement]:
        lo, hi = self._epoch_bounds(start, end)
        sql = "SELECT source_record_id,timestamp_utc,utc_offset_seconds,value FROM spo2 WHERE timestamp_utc>=? AND timestamp_utc<? ORDER BY timestamp_utc,source_record_id"
        for r in self._db().execute(sql, (lo, hi)):
            ts = utc_from_epoch(r["timestamp_utc"])
            value = float(r["value"])
            flags = frozenset({QualityFlag.SENTINEL, QualityFlag.INVALID}) if value <= 0 else (frozenset({QualityFlag.INVALID}) if value > 100 else frozenset())
            yield SpO2Measurement(provenance=_prov("spo2.value", r["source_record_id"], SourceType.RAW_MEASUREMENT),
                                  measurement_start=ts, measurement_end=ts,
                                  local_date=local_date_for(ts, offset_seconds=r["utc_offset_seconds"]),
                                  utc_offset_seconds=r["utc_offset_seconds"], percent=value,
                                  quality_flags=flags, quality_status=QualityStatus.INVALID if flags else QualityStatus.OK)

    def sleep_sessions(self, start: datetime, end: datetime) -> Iterator[SleepSession]:
        lo, hi = self._epoch_bounds(start, end)
        sql = "SELECT * FROM sleep_sessions WHERE sleep_end_utc>=? AND sleep_end_utc<? ORDER BY sleep_end_utc,source_record_id"
        for r in self._db().execute(sql, (lo, hi)):
            begin, finish = utc_from_epoch(r["sleep_start_utc"]), utc_from_epoch(r["sleep_end_utc"])
            offset = r["utc_offset_seconds"]
            flags = {QualityFlag.VENDOR_DERIVED}
            if not r["has_stages"]:
                flags.add(QualityFlag.STAGE_INCOMPLETE)
            yield SleepSession(provenance=_prov("sleep_sessions", r["source_record_id"], SourceType.VENDOR_DERIVED),
                               measurement_start=begin, measurement_end=finish,
                               local_date=sleep_date(finish, offset_seconds=offset), utc_offset_seconds=offset,
                               session_kind="nap" if r["is_nap_inferred"] else "main", has_stages=bool(r["has_stages"]),
                               vendor_duration_min=r["duration_minutes"], vendor_sleep_score=r["sleep_score"],
                               quality_flags=frozenset(flags))

    def sleep_stages(self, session: SleepSession) -> Iterator[SleepStageInterval]:
        mapping = {2: "deep", 3: "light", 4: "rem", 5: "awake"}
        sql = "SELECT * FROM sleep_stages WHERE source_record_id=? ORDER BY stage_index"
        for r in self._db().execute(sql, (session.provenance.source_record_id,)):
            begin, finish = utc_from_epoch(r["start_timestamp_utc"]), utc_from_epoch(r["end_timestamp_utc"])
            stage = mapping.get(r["raw_state"], "unknown")
            flags = {QualityFlag.VENDOR_DERIVED}
            if stage == "unknown":
                flags.add(QualityFlag.UNKNOWN_SEMANTICS)
            yield SleepStageInterval(provenance=_prov("sleep_stages", f"{r['source_record_id']}:{r['stage_index']}", SourceType.VENDOR_DERIVED),
                                     measurement_start=begin, measurement_end=finish, local_date=session.local_date,
                                     utc_offset_seconds=session.utc_offset_seconds, session_id=session.provenance.source_record_id,
                                     stage_index=r["stage_index"], stage=stage, raw_state=r["raw_state"],
                                     duration_min=float(r["duration_minutes"]), quality_flags=frozenset(flags),
                                     quality_status=QualityStatus.UNKNOWN if stage == "unknown" else QualityStatus.OK)

    def daily_activity(self, start: date, end: date) -> Iterator[DailyActivity]:
        if isinstance(start, datetime) or isinstance(end, datetime):
            raise TypeError("daily reader requires local dates")
        sql = "SELECT * FROM daily_summary WHERE local_date>=? AND local_date<? ORDER BY local_date"
        for r in self._db().execute(sql, (start.isoformat(), end.isoformat())):
            day = date.fromisoformat(r["local_date"])
            yield DailyActivity(provenance=_prov("daily_summary.activity", r["local_date"], SourceType.VENDOR_DERIVED),
                                measurement_start=None, measurement_end=None, local_date=day, utc_offset_seconds=None,
                                steps=r["steps"], step_energy_kcal=r["step_calories"],
                                total_energy_kcal=r["total_calories"], active_minutes=r["activity_duration_minutes"],
                                standing_count=r["standing_count"], distance_m=None,
                                quality_flags=frozenset({QualityFlag.VENDOR_DERIVED, QualityFlag.TIMEZONE_UNCERTAIN}))

    def resting_hr(self, start: date, end: date) -> Iterator[RestingHeartRate]:
        sql = "SELECT local_date,resting_hr FROM daily_summary WHERE local_date>=? AND local_date<? AND resting_hr IS NOT NULL ORDER BY local_date"
        for r in self._db().execute(sql, (start.isoformat(), end.isoformat())):
            value = float(r["resting_hr"])
            if value <= 0:
                continue  # Xiaomi sentinel, not resting HR zero.
            yield RestingHeartRate(provenance=_prov("daily_summary.resting_hr", r["local_date"], SourceType.VENDOR_DERIVED),
                                  measurement_start=None, measurement_end=None, local_date=date.fromisoformat(r["local_date"]),
                                  utc_offset_seconds=None, bpm=value, method="vendor_daily",
                                  quality_flags=frozenset({QualityFlag.VENDOR_DERIVED, QualityFlag.TIMEZONE_UNCERTAIN}))

    def respiratory(self, session: SleepSession) -> RespiratoryRateMeasurement | None:
        row = self._db().execute("SELECT avg_respiratory_rate FROM sleep_sessions WHERE source_record_id=?", (session.provenance.source_record_id,)).fetchone()
        if row is None or row["avg_respiratory_rate"] is None or row["avg_respiratory_rate"] <= 0:
            return None
        return RespiratoryRateMeasurement(provenance=_prov("sleep_sessions.avg_respiratory_rate", session.provenance.source_record_id, SourceType.VENDOR_DERIVED),
                                          measurement_start=session.measurement_start, measurement_end=session.measurement_end,
                                          local_date=session.local_date, utc_offset_seconds=session.utc_offset_seconds,
                                          breaths_per_min=float(row["avg_respiratory_rate"]), aggregation="night_mean",
                                          quality_status=QualityStatus.PARTIAL,
                                          quality_flags=frozenset({QualityFlag.VENDOR_DERIVED, QualityFlag.UNKNOWN_SEMANTICS}))

    def nightly_hrv(self, session: SleepSession):
        # Current Xiaomi export has no confirmed RR/IBI or true HRV signal.
        return None

    def stress(self, start: datetime, end: datetime) -> Iterator[VendorMetric]:
        lo, hi = self._epoch_bounds(start, end)
        sql = "SELECT source_record_id,timestamp_utc,utc_offset_seconds,value FROM stress WHERE timestamp_utc>=? AND timestamp_utc<? ORDER BY timestamp_utc,source_record_id"
        for r in self._db().execute(sql, (lo, hi)):
            ts = utc_from_epoch(r["timestamp_utc"])
            yield VendorMetric(provenance=_prov("stress.value", r["source_record_id"], SourceType.VENDOR_DERIVED),
                               measurement_start=ts, measurement_end=ts,
                               local_date=local_date_for(ts, offset_seconds=r["utc_offset_seconds"]),
                               utc_offset_seconds=r["utc_offset_seconds"], name="xiaomi_stress",
                               numeric_value=float(r["value"]), unit="vendor_scale",
                               quality_flags=frozenset({QualityFlag.VENDOR_DERIVED, QualityFlag.UNKNOWN_SEMANTICS}))

    def workouts(self, start: datetime, end: datetime) -> Iterator[Workout]:
        lo, hi = self._epoch_bounds(start, end)
        sql = "SELECT * FROM workouts WHERE start_timestamp_utc>=? AND start_timestamp_utc<? ORDER BY start_timestamp_utc"
        for r in self._db().execute(sql, (lo, hi)):
            begin, finish = utc_from_epoch(r["start_timestamp_utc"]), utc_from_epoch(r["end_timestamp_utc"])
            yield Workout(provenance=_prov("workouts", r["source_record_id"], SourceType.VENDOR_DERIVED),
                          measurement_start=begin, measurement_end=finish, local_date=date.fromisoformat(r["local_date"]),
                          utc_offset_seconds=None, workout_type=r["workout_type"], duration_s=r["duration_seconds"],
                          avg_hr_bpm=r["avg_hr"], vendor_training_load=r["training_load"],
                          quality_flags=frozenset({QualityFlag.VENDOR_DERIVED, QualityFlag.TIMEZONE_UNCERTAIN}))
