"""Per-date assembly of the existing foundation metric family.

Calculations live in their components (`analytics.recovery_vitals`,
`analytics.sleep.stages`, `analytics.series`). This module maps selected
feature records to component inputs once per run and keeps the existing
per-date persistence order, which is part of the stored-row compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from mi_fitness_whooping.analytics.recovery_vitals import core as vitals
from mi_fitness_whooping.analytics.series import core as series_core
from mi_fitness_whooping.analytics.sleep import stages
from mi_fitness_whooping.domain.metrics import MetricResult
from mi_fitness_whooping.domain.recovery_vitals.contracts import VitalsDaily, VitalsNight
from mi_fitness_whooping.domain.series.contracts import SeriesHistory
from mi_fitness_whooping.domain.sleep.observations import SleepStagesNight
from mi_fitness_whooping.integration.recovery_vitals.adapter import vitals_daily, vitals_night
from mi_fitness_whooping.integration.series.adapter import series_history
from mi_fitness_whooping.integration.sleep.stages_adapter import stages_night


FOUNDATION_ALGORITHM_VERSION = "foundation-2"


@dataclass(frozen=True)
class FeatureRecord:
    """One selected stored feature row (schema v3 `features`)."""

    kind: str
    day: date
    values: dict[str, Any]
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None
    measurement_end: str | None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FoundationInputs:
    vitals_nights: Mapping[date, VitalsNight]
    vitals_dailies: Mapping[date, VitalsDaily]
    stages_nights: Mapping[date, SleepStagesNight]
    series: SeriesHistory


def foundation_inputs(nights: Mapping[date, FeatureRecord],
                      dailies: Mapping[date, FeatureRecord]) -> FoundationInputs:
    """Map the selected features to every component input once per run."""
    return FoundationInputs({d: vitals_night(f) for d, f in nights.items()},
                            {d: vitals_daily(f) for d, f in dailies.items()},
                            {d: stages_night(f) for d, f in nights.items()},
                            series_history(nights, dailies))


def calculate_day(day: date, inputs: FoundationInputs) -> list[MetricResult]:
    """Foundation metrics for one date in the existing persistence order."""
    night = inputs.vitals_nights.get(day)
    results: list[MetricResult] = []
    if night is not None:
        results.append(vitals.night_heart_rate(day, night))
        results.extend(stages.stage_metrics(day, inputs.stages_nights[day]))
        results.extend(vitals.night_spo2(day, night))
        results.append(vitals.night_respiratory(day, night))
    vendor = vitals.vendor_daily_rhr(day, night, inputs.vitals_dailies.get(day))
    if vendor is not None:
        results.append(vendor)
    regularity = stages.regularity(day, inputs.stages_nights)
    if regularity is not None:
        results.append(regularity)
    results.extend(series_core.baselines(day, inputs.series))
    results.extend(series_core.trends(day, inputs.series))
    return results
