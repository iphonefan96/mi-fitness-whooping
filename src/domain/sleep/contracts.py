"""Immutable Sleep Core V1 boundary types.

These types retain observed values for later Legacy-compatible quality gates.
They do not calculate metrics, resolve profiles, persist results or evaluate time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class SleepMetric(StrEnum):
    SCORE = "sleep.score"
    NEED_MIN = "sleep.need_min"
    DEBT_MIN = "sleep.debt_min"


class CalculationStatus(StrEnum):
    VALID = "VALID"
    REDUCED = "REDUCED"
    CALIBRATING = "CALIBRATING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class NightReference:
    """Opaque selected-night lineage carried through to a storage adapter."""

    day: date
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None = None
    measurement_end: str | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.fingerprint or not self.source_ids_hash:
            raise ValueError("night lineage identity is required")
        if self.source_count < 0:
            raise ValueError("source_count cannot be negative")
        if not isinstance(self.quality_flags, tuple):
            raise TypeError("quality_flags must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class SelectedNight:
    """One already-selected main night, including unvalidated observations.

    Values such as zero, negative duration or out-of-range bedtime are retained
    so Phase 3 can reproduce Legacy's INVALID/INSUFFICIENT_DATA decisions.
    None means missing rather than measured zero.
    """

    day: date
    lineage: NightReference
    tst_min: float | None
    deep_min: float | None
    rem_min: float | None
    waso_min: float | None
    awakening_durations_min: tuple[float | None, ...] | None
    bedtime_local_min: float | None
    stage_complete: bool

    def __post_init__(self) -> None:
        if self.lineage.day != self.day:
            raise ValueError("night and lineage dates differ")
        if self.awakening_durations_min is not None and not isinstance(
            self.awakening_durations_min, tuple
        ):
            raise TypeError("awakening durations must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class EffectiveSleepTarget:
    """Resolved target for one ledger date; profile parsing stays outside."""

    day: date
    minutes: float
    is_default: bool

    def __post_init__(self) -> None:
        if isinstance(self.minutes, bool) or not isinstance(self.minutes, (int, float)):
            raise ValueError("sleep target must be numeric")
        if not math.isfinite(self.minutes) or not 300 <= self.minutes <= 720:
            raise ValueError("sleep target must be within 300..720 minutes")
        if self.is_default and self.minutes != 480:
            raise ValueError("Legacy default sleep target is 480 minutes")


@dataclass(frozen=True, slots=True)
class SleepCoreInput:
    """At most 14 prior nights plus today, and a 14-date target ledger.

    Selected nights are sorted oldest to newest and may omit calendar dates.
    With a current night, targets cover today and the preceding 13 dates,
    including dates with no night. Without a current night, targets may be
    empty: Legacy returns no metrics before it inspects profile targets.
    """

    target_date: date
    selected_nights: tuple[SelectedNight, ...]
    targets: tuple[EffectiveSleepTarget, ...]
    profile_revision: str

    def __post_init__(self) -> None:
        if not self.profile_revision:
            raise ValueError("profile_revision is required for reproducible lineage")
        if not isinstance(self.selected_nights, tuple) or not isinstance(self.targets, tuple):
            raise TypeError("sleep history and targets must be immutable tuples")
        night_days = tuple(n.day for n in self.selected_nights)
        if night_days != tuple(sorted(set(night_days))):
            raise ValueError("selected nights must have unique ascending dates")
        earliest = self.target_date - timedelta(days=14)
        if any(not earliest <= d <= self.target_date for d in night_days):
            raise ValueError("selected night outside Sleep Core history window")
        if self.target_date not in night_days and not self.targets:
            return
        expected_target_days = tuple(
            self.target_date - timedelta(days=offset) for offset in range(13, -1, -1)
        )
        if tuple(t.day for t in self.targets) != expected_target_days:
            raise ValueError("targets must cover the ordered 14-night ledger")


@dataclass(frozen=True, slots=True)
class ScoreComponents:
    duration: int
    stages: int
    consistency: int
    interruptions: int


@dataclass(frozen=True, slots=True)
class ScoreMetadata:
    mode: str | None
    components: ScoreComponents | None
    history_count: int
    required_history_count: int
    history_window_calendar_nights: int


@dataclass(frozen=True, slots=True)
class NeedMetadata:
    mode: str
    default_target: bool
    physiological_estimate: bool


@dataclass(frozen=True, slots=True)
class DebtMetadata:
    mode: str
    default_target: bool
    signed_balance_min: float | None
    history_count: int
    required_history_count: int
    longest_missing_gap: int
    window_calendar_nights: int


SleepMetadata = ScoreMetadata | NeedMetadata | DebtMetadata


@dataclass(frozen=True, slots=True)
class SleepMetricResult:
    """Pure calculation result; storage revision and freshness are external."""

    metric: SleepMetric
    day: date
    value: float | None
    unit: str
    status: CalculationStatus
    algorithm_id: str
    algorithm_version: str
    metadata: SleepMetadata
    lineage: tuple[NightReference, ...]
    upstream_project: str | None = None
    upstream_commit: str | None = None
    source_type: str = "OUR_DERIVED"
    confidence: str = "MEDIUM"

    def __post_init__(self) -> None:
        if not isinstance(self.metric, SleepMetric):
            raise ValueError("unsupported Sleep Core metric")
        if not isinstance(self.status, CalculationStatus):
            raise ValueError("unsupported Sleep Core calculation status")
        metadata_types = {
            SleepMetric.SCORE: (ScoreMetadata, "score"),
            SleepMetric.NEED_MIN: (NeedMetadata, "min"),
            SleepMetric.DEBT_MIN: (DebtMetadata, "min"),
        }
        metadata_type, unit = metadata_types[self.metric]
        if not isinstance(self.metadata, metadata_type) or self.unit != unit:
            raise ValueError("metric metadata or unit does not match identity")
        allowed_statuses = {
            SleepMetric.SCORE: {CalculationStatus.VALID, CalculationStatus.CALIBRATING,
                                CalculationStatus.INSUFFICIENT_DATA, CalculationStatus.INVALID},
            SleepMetric.NEED_MIN: {CalculationStatus.VALID, CalculationStatus.REDUCED},
            SleepMetric.DEBT_MIN: {CalculationStatus.VALID, CalculationStatus.REDUCED,
                                   CalculationStatus.CALIBRATING},
        }
        if self.status not in allowed_statuses[self.metric]:
            raise ValueError("calculation status does not match metric")
        has_value = self.value is not None
        requires_value = self.status in {CalculationStatus.VALID, CalculationStatus.REDUCED}
        if has_value != requires_value:
            raise ValueError("metric value and calculation status disagree")
        if has_value:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value):
                raise ValueError("metric value must be finite and numeric")
            if (self.metric == SleepMetric.SCORE and not 0 <= self.value <= 100 or
                    self.metric == SleepMetric.NEED_MIN and not 300 <= self.value <= 720 or
                    self.metric == SleepMetric.DEBT_MIN and self.value < 0):
                raise ValueError("metric value outside Sleep Core range")
        if not self.algorithm_id or not self.algorithm_version:
            raise ValueError("algorithm identity is required")
        if not isinstance(self.lineage, tuple):
            raise TypeError("lineage must be an immutable ordered tuple")
        if self.source_type != "OUR_DERIVED":
            raise ValueError("Sleep Core V1 results are our derived metrics")
