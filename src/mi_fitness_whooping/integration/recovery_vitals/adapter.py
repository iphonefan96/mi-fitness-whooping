"""Map selected features and profile v1 to Recovery/vitals inputs.

Feature selection and persistence stay with the caller; this module performs
no database access.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from mi_fitness_whooping.analytics.recovery_vitals.core import calculate_recovery
from mi_fitness_whooping.domain.metrics import MetricResult
from mi_fitness_whooping.domain.recovery_vitals.contracts import (
    RecoveryTarget, VitalsDaily, VitalsNight,
)
from mi_fitness_whooping.integration.metric_results import SelectedFeature, lineage


_NIGHT_FIELDS = tuple(name for name in VitalsNight.__dataclass_fields__ if name != "lineage")


def vitals_night(feature: SelectedFeature) -> VitalsNight:
    return VitalsNight(lineage(feature), **{name: feature.values.get(name) for name in _NIGHT_FIELDS})


def vitals_daily(feature: SelectedFeature) -> VitalsDaily:
    return VitalsDaily(lineage(feature), feature.values.get("daily_rhr_bpm"))


def recovery_target(profile: Mapping[str, Any], day: date) -> RecoveryTarget:
    """Resolve profile v1 `sleep_target_min` for a date (last matching entry wins)."""
    effective = {
        entry["field"]: entry["value"]
        for entry in profile["values"]
        if date.fromisoformat(entry["effective_from"]) <= day
        and (not entry.get("effective_to") or day <= date.fromisoformat(entry["effective_to"]))
    }
    raw = effective.get("sleep_target_min")
    return RecoveryTarget(480.0, True) if raw is None else RecoveryTarget(raw, False)


def recovery_for_day(day: date, nights: Mapping[date, VitalsNight],
                     profile: Mapping[str, Any]) -> MetricResult | None:
    """Calculate Recovery from mapped nights; the target is resolved only for a night."""
    if day not in nights:
        return None
    return calculate_recovery(day, nights, recovery_target(profile, day))
