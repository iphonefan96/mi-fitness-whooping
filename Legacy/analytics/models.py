"""Typed canonical signals. No source-table names appear in feature algorithms."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import StrEnum
from typing import Any


class SourceType(StrEnum):
    RAW_MEASUREMENT = "RAW_MEASUREMENT"
    VENDOR_DERIVED = "VENDOR_DERIVED"
    OUR_DERIVED = "OUR_DERIVED"
    USER_CONFIG = "USER_CONFIG"


class QualityStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class QualityFlag(StrEnum):
    LOW_COVERAGE = "LOW_COVERAGE"
    STALE = "STALE"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    UNKNOWN_SEMANTICS = "UNKNOWN_SEMANTICS"
    SENSOR_GAP = "SENSOR_GAP"
    INVALID = "INVALID"
    VENDOR_DERIVED = "VENDOR_DERIVED"
    TIMEZONE_UNCERTAIN = "TIMEZONE_UNCERTAIN"
    SOURCE_UPDATE_UNKNOWN = "SOURCE_UPDATE_UNKNOWN"
    SENTINEL = "SENTINEL"
    STAGE_INCOMPLETE = "STAGE_INCOMPLETE"


class Freshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    HISTORICAL = "HISTORICAL"
    MISSING = "MISSING"


class CapabilitySupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class Provenance:
    source_provider: str
    source_device: str
    source_metric: str
    source_record_id: str
    source_type: SourceType


@dataclass(frozen=True, kw_only=True)
class Signal:
    provenance: Provenance
    measurement_start: datetime | None
    measurement_end: datetime | None
    local_date: date
    utc_offset_seconds: int | None
    source_updated_at: datetime | None = None
    quality_status: QualityStatus = QualityStatus.OK
    quality_flags: frozenset[QualityFlag] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if (self.measurement_start is None) != (self.measurement_end is None):
            raise ValueError("both interval endpoints must be present or absent")
        if self.measurement_start is None:
            return  # Date-only vendor aggregate.
        if self.measurement_start.tzinfo is None or self.measurement_end.tzinfo is None:
            raise ValueError("measurement timestamps require timezone")
        if self.measurement_end < self.measurement_start:
            raise ValueError("negative measurement interval")


@dataclass(frozen=True, kw_only=True)
class HeartRateSample(Signal):
    bpm: float
    context: str = "auto"


@dataclass(frozen=True, kw_only=True)
class RestingHeartRate(Signal):
    bpm: float
    method: str


@dataclass(frozen=True, kw_only=True)
class BeatInterval(Signal):
    rr_ms: float
    evidence: str  # TRUE_RR or VALIDATED_WAVEFORM, never periodic BPM.

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.evidence not in {"TRUE_RR", "VALIDATED_WAVEFORM"}:
            raise ValueError("beat intervals need actual beat-level evidence")
        if not 250 <= self.rr_ms <= 2500:
            raise ValueError("RR interval outside plausible raw range")


@dataclass(frozen=True, kw_only=True)
class HRVMeasurement(Signal):
    metric: str
    value: float
    unit: str
    evidence: str  # TRUE_RR, VALIDATED_WAVEFORM, or DEVICE_REPORTED_HRV
    nn_count: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.evidence not in {"TRUE_RR", "VALIDATED_WAVEFORM", "DEVICE_REPORTED_HRV"}:
            raise ValueError("HRV needs genuine beat-level or device-reported evidence")
        if self.metric not in {"RMSSD", "SDNN", "PNN50", "LNRMSSD"}:
            raise ValueError("unsupported HRV metric")
        expected = "%" if self.metric == "PNN50" else ("1" if self.metric == "LNRMSSD" else "ms")
        if self.unit != expected:
            raise ValueError("wrong HRV unit")


@dataclass(frozen=True, kw_only=True)
class SpO2Measurement(Signal):
    percent: float


@dataclass(frozen=True, kw_only=True)
class RespiratoryRateMeasurement(Signal):
    breaths_per_min: float
    aggregation: str


@dataclass(frozen=True, kw_only=True)
class SkinTemperature(Signal):
    celsius: float | None = None
    deviation_celsius: float | None = None
    reference_kind: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.celsius is None and self.deviation_celsius is None:
            raise ValueError("temperature requires absolute value or deviation")
        if self.deviation_celsius is not None and not self.reference_kind:
            raise ValueError("temperature deviation requires reference kind")


@dataclass(frozen=True, kw_only=True)
class SleepSession(Signal):
    session_kind: str
    has_stages: bool
    vendor_duration_min: float | None = None
    vendor_sleep_score: float | None = None


@dataclass(frozen=True, kw_only=True)
class SleepStageInterval(Signal):
    session_id: str
    stage_index: int
    stage: str
    raw_state: int | None
    duration_min: float


@dataclass(frozen=True, kw_only=True)
class DailyActivity(Signal):
    steps: int | None
    step_energy_kcal: float | None
    total_energy_kcal: float | None
    active_minutes: float | None
    standing_count: int | None
    distance_m: float | None = None


@dataclass(frozen=True, kw_only=True)
class Workout(Signal):
    workout_type: str | None
    duration_s: float | None
    avg_hr_bpm: float | None
    vendor_training_load: float | None


@dataclass(frozen=True, kw_only=True)
class VendorMetric(Signal):
    name: str
    numeric_value: float | None = None
    text_value: str | None = None
    unit: str | None = None


@dataclass(frozen=True, kw_only=True)
class UserProfile:
    revision: str
    timezone: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    sleep_target_min: int | None = None
    max_hr_bpm: int | None = None
    effective_from: date | None = None


@dataclass(frozen=True, kw_only=True)
class DeviceCapability:
    signal_kind: str
    support: CapabilitySupport
    origin: SourceType | None
    resolution_seconds: int | None = None
    notes: str = ""


@dataclass(frozen=True, kw_only=True)
class Feature:
    kind: str
    metric_date: date
    measurement_start: datetime | None
    measurement_end: datetime | None
    values: dict[str, Any]
    source_ids: tuple[str, ...]
    quality_status: QualityStatus
    quality_flags: frozenset[QualityFlag]
    input_fingerprint: str
    freshness_status: Freshness
