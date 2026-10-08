"""Map selected features and profile v1 to Recovery/vitals inputs.

Feature selection and persistence stay with the caller; this module performs
no database access.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from mi_fitness_whooping.analytics.recovery_vitals.core import calculate_recovery
from mi_fitness_whooping.domain.metrics import MetricResult
from mi_fitness_whooping.domain.recovery_vitals.contracts import (
    RecoveryTarget, VitalsBand, VitalsDaily, VitalsNight,
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


MONITORED_SIGNALS = ("rhr", "spo2", "respiratory")


def monitoring_bands(results: Iterable[object]) -> dict[str, VitalsBand | None]:
    """Map each signal's series `baseline.<signal>.band_mean` result to a typed band.

    The mean is used only when the band is VALID/REDUCED; a signal without a
    band result (no current series value) maps to None.
    """
    by_name = {result.name: result for result in results if isinstance(result, MetricResult)}
    bands: dict[str, VitalsBand | None] = {}
    for signal in MONITORED_SIGNALS:
        result = by_name.get(f"baseline.{signal}.band_mean")
        if result is None:
            bands[signal] = None
            continue
        m = result.metadata
        bands[signal] = VitalsBand(
            result.value if result.status in {"VALID", "REDUCED"} else None,
            m.get("sd"), m.get("lower"), m.get("upper"), m.get("history_count", 0),
            date.fromisoformat(m["last_prior_date"]) if m.get("last_prior_date") else None,
            result.lineage)
    return bands
