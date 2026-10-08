"""Immutable Recovery/vitals boundary types.

Observations are retained unvalidated so the calculation can reproduce the
existing range gates. These types do not read storage, parse profiles or
evaluate time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from mi_fitness_whooping.domain.metrics import FeatureLineage


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
class VitalsBand:
    """Personal reference band for one vital signal on one date.

    `mean` is None unless the band is ready. Lineage is the band's own inputs,
    carried into monitoring results.
    """

    mean: float | None
    sd: float | None
    lower: float | None
    upper: float | None
    history_count: int
    last_prior_date: date | None
    lineage: tuple[FeatureLineage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, tuple):
            raise TypeError("band lineage must be an immutable tuple")
