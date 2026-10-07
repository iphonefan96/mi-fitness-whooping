"""Immutable Recovery/vitals boundary types.

Observations are retained unvalidated so the calculation can reproduce the
existing range gates. These types do not read storage, parse profiles or
evaluate time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureLineage:
    """Opaque selected-feature identity carried through to result storage."""

    kind: str
    day: date
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None = None
    measurement_end: str | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"nightly", "daily"}:
            raise ValueError("feature lineage kind must be nightly or daily")
        if not self.fingerprint or not self.source_ids_hash:
            raise ValueError("feature lineage identity is required")
        if self.source_count < 0:
            raise ValueError("source_count cannot be negative")
        if not isinstance(self.quality_flags, tuple):
            raise TypeError("quality_flags must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class VitalsNight:
    """One selected main night; None means missing, not measured zero."""

    lineage: FeatureLineage
    night_rhr_bpm: object = None
    night_hr_measured_minutes: object = None
    rhr_bpm: object = None
    hrv_rmssd_ms: object = None
    tst_min: object = None
    stage_coverage: object = None
    spo2_samples: object = None
    spo2_span_min: object = None
    spo2_mean_pct: object = None
    spo2_min_pct: object = None
    spo2_p10_pct: object = None
    respiratory_rate_bpm: object = None
    respiratory_provenance: object = None

    def __post_init__(self) -> None:
        if self.lineage.kind != "nightly":
            raise ValueError("vitals night requires nightly lineage")

    @property
    def day(self) -> date:
        return self.lineage.day


@dataclass(frozen=True, slots=True)
class VitalsDaily:
    """One selected daily feature; only the vendor daily RHR is used here."""

    lineage: FeatureLineage
    daily_rhr_bpm: object = None

    def __post_init__(self) -> None:
        if self.lineage.kind != "daily":
            raise ValueError("vitals daily requires daily lineage")

    @property
    def day(self) -> date:
        return self.lineage.day


@dataclass(frozen=True, slots=True)
class RecoveryTarget:
    """Resolved sleep target for one date; profile parsing stays outside."""

    minutes: float
    is_default: bool

    def __post_init__(self) -> None:
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, (int, float)):
            raise ValueError("sleep_target_min must be within 300..720")
        if not math.isfinite(self.minutes) or not 300 <= self.minutes <= 720:
            raise ValueError("sleep_target_min must be within 300..720")
        if self.is_default and self.minutes != 480:
            raise ValueError("default sleep target is 480 minutes")


@dataclass(frozen=True, slots=True)
class VitalsResult:
    """Pure calculation result; storage identity, revision and freshness are external.

    Metadata is JSON-shaped and part of the stored result identity.
    """

    name: str
    day: date
    value: float | None
    unit: str | None
    status: str
    algorithm_id: str
    algorithm_version: str
    lineage: tuple[FeatureLineage, ...]
    metadata: dict[str, Any]
    source_type: str = "OUR_DERIVED"
    upstream_project: str | None = None
    upstream_commit: str | None = None
    confidence: str = "MEDIUM"

    def __post_init__(self) -> None:
        if self.status not in {"VALID", "REDUCED", "CALIBRATING", "INSUFFICIENT_DATA"}:
            raise ValueError("unsupported calculation status")
        if (self.value is not None) != (self.status in {"VALID", "REDUCED"}):
            raise ValueError("metric value and calculation status disagree")
        if not self.algorithm_id or not self.algorithm_version:
            raise ValueError("algorithm identity is required")
        if not isinstance(self.lineage, tuple):
            raise TypeError("lineage must be an immutable ordered tuple")
