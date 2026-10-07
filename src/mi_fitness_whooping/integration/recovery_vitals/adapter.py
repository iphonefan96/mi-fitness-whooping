"""Map selected features and profile v1 to Recovery/vitals inputs and storage values.

Feature selection and persistence stay with the caller; this module performs
no database access.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Protocol

from mi_fitness_whooping.analytics.recovery_vitals.core import calculate_recovery
from mi_fitness_whooping.domain.recovery_vitals.contracts import (
    FeatureLineage, RecoveryTarget, VitalsDaily, VitalsNight, VitalsResult,
)
from mi_fitness_whooping.storage.contracts import PersistableMetricResult, StoredFeatureRef


class SelectedFeature(Protocol):
    kind: str
    day: date
    values: Mapping[str, Any]
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None
    measurement_end: str | None
    quality_flags: tuple[str, ...]


_NIGHT_FIELDS = tuple(name for name in VitalsNight.__dataclass_fields__ if name != "lineage")


def lineage(feature: SelectedFeature) -> FeatureLineage:
    return FeatureLineage(feature.kind, feature.day, feature.fingerprint, feature.source_count,
                          feature.source_ids_hash, feature.measurement_start,
                          feature.measurement_end, tuple(feature.quality_flags))


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
                     profile: Mapping[str, Any]) -> VitalsResult | None:
    """Calculate Recovery from mapped nights; the target is resolved only for a night."""
    if day not in nights:
        return None
    return calculate_recovery(day, nights, recovery_target(profile, day))


def to_persistable(result: VitalsResult) -> PersistableMetricResult:
    return PersistableMetricResult(
        metric_name=result.name, day=result.day, value=result.value, unit=result.unit,
        status=result.status, algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version, metadata=result.metadata,
        inputs=tuple(StoredFeatureRef(
            kind=ref.kind, day=ref.day, fingerprint=ref.fingerprint,
            source_count=ref.source_count, source_ids_hash=ref.source_ids_hash,
            measurement_start=ref.measurement_start, measurement_end=ref.measurement_end,
            quality_flags=ref.quality_flags,
        ) for ref in result.lineage),
        source_type=result.source_type, upstream_project=result.upstream_project,
        upstream_commit=result.upstream_commit, confidence=result.confidence,
    )
