"""Personal baselines, deviations and Theil-Sen trends over dated series.

The formulas, gates, statuses and metadata are the existing foundation
behavior (Legacy `foundations.baselines` and `foundations.trends`), moved here
unchanged. This module has no SQLite, CLI, clock, profile or Legacy dependency.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

from mi_fitness_whooping.domain.metrics import FeatureLineage, MetricResult
from mi_fitness_whooping.domain.series.contracts import SeriesHistory


# Part of the existing foundation metric family; the runner tracks this
# version as `foundation_algorithm_version`.
SERIES_ALGORITHM_VERSION = "foundation-2"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
PULSE_COMMIT = "1f8975cfc8298b67482a7e37dba576b9ea8b62db"
# Ordered: trends are emitted in this series order.
SERIES_UNITS = {
    "rhr": "bpm",
    "sleep_tst": "min",
    "spo2": "%",
    "respiratory": "breaths/min",
    "steps": "steps",
    "stress_vendor": "vendor_scale",
}

_Point = tuple[date, float, FeatureLineage]


def _metric(name: str, day: date, value: float | None, unit: str, status: str,
            algorithm_id: str, lineage: tuple[FeatureLineage, ...], metadata: dict, *,
            upstream_project: str | None = None, upstream_commit: str | None = None,
            confidence: str = "MEDIUM") -> MetricResult:
    return MetricResult(name, day, value, unit, status, algorithm_id, SERIES_ALGORITHM_VERSION,
                        lineage, metadata, "OUR_DERIVED", upstream_project, upstream_commit,
                        confidence)


def _valid_number(value: object) -> float | None:
    # Existing foundation gate: bool is accepted as a number here.
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    return float(value)


def _series_at(day: date, key: str,
               history: SeriesHistory) -> tuple[float | None, FeatureLineage | None]:
    observation = history.get(key, {}).get(day)
    if observation is None:
        return None, None
    value = _valid_number(observation.value)
    if key == "spo2" and value is not None and not 0 < value <= 100:
        value = None
    if key == "respiratory" and value is not None and not 4 <= value <= 60:
        value = None
    if key == "rhr" and value is not None and not 25 <= value <= 240:
        value = None
    if key in {"sleep_tst", "steps"} and value is not None and value < 0:
        value = None
    return value, observation.lineage


def _prior_series(day: date, key: str, history: SeriesHistory, days: int = 30) -> list[_Point]:
    output = []
    for offset in range(days, 0, -1):
        past = day - timedelta(days=offset)
        value, lineage = _series_at(past, key, history)
        if value is not None and lineage is not None:
            output.append((past, value, lineage))
    return output


def baselines(day: date, history: SeriesHistory) -> list[MetricResult]:
    """Pulse band mean, deviation and EWMA level from the prior 30 calendar days."""
    results = []
    for key in ("rhr", "sleep_tst", "spo2", "respiratory"):
        current, current_lineage = _series_at(day, key, history)
        if current is None or current_lineage is None:
            continue
        prior = _prior_series(day, key, history)
        recent = bool(prior and (day - prior[-1][0]).days <= 14)
        ready = len(prior) >= 5 and recent
        unit = SERIES_UNITS[key]
        metadata = {"window_calendar_days": 30, "history_count": len(prior),
                    "required_history_count": 5, "last_prior_date": prior[-1][0].isoformat() if prior else None,
                    "max_last_observation_age_days": 14, "excludes_current_date": True}
        lineage = (current_lineage, *(ref for _, _, ref in prior))
        values = [v for _, v, _ in prior]
        if key != "sleep_tst":
            mean = statistics.mean(values) if ready else None
            sd = statistics.pstdev(values) if ready else None
            floor = {"rhr": 3.0, "spo2": 1.5, "respiratory": .8}[key]
            half_width = max(1.65 * sd, floor) if sd is not None else None
            extra = {**metadata, "sd": sd, "half_width": half_width,
                     "lower": max(90, mean - half_width) if key == "spo2" and mean is not None else
                              (mean - half_width if mean is not None else None),
                     "upper": None if key == "spo2" else (mean + half_width if mean is not None else None),
                     "method": "prior_30_calendar_day_population_mean_sd_pulse_band"}
            results.append(_metric(f"baseline.{key}.band_mean", day, mean, unit,
                                   ("REDUCED" if key == "respiratory" else "VALID") if ready else "CALIBRATING",
                                   f"baseline.pulse_{key}_band_v1", lineage, extra,
                                   upstream_project="Pulse", upstream_commit=PULSE_COMMIT,
                                   confidence="MEDIUM" if ready else "LOW"))
            delta = current - mean if mean is not None else None
            results.append(_metric(f"{key}.deviation", day, delta, unit,
                                   "VALID" if delta is not None and key != "respiratory" else
                                   ("REDUCED" if delta is not None else "CALIBRATING"),
                                   f"deviation.{key}_delta_v1", lineage,
                                   {"reference_metric": f"baseline.{key}.band_mean", **metadata}))
        # Standard EWMA level, distinct from the Pulse monitoring band.
        ewma = None
        if ready:
            alpha = 2 / 31
            ewma = values[0]
            for value in values[1:]:
                ewma = alpha * value + (1 - alpha) * ewma
        results.append(_metric(f"baseline.{key}.ewma", day, ewma, unit,
                               ("REDUCED" if key == "respiratory" else "VALID") if ewma is not None else "CALIBRATING",
                               f"baseline.ewma30_{key}_v1", lineage,
                               {**metadata, "alpha": 2 / 31, "seed": "oldest_observation",
                                "method": "EWMA_prior_30_calendar_days"}))
    return results


def _theil_sen(dated_values: list[_Point]) -> float:
    slopes = []
    for i in range(len(dated_values) - 1):
        for j in range(i + 1, len(dated_values)):
            x = (dated_values[j][0] - dated_values[i][0]).days
            if x > 0:
                slopes.append((dated_values[j][1] - dated_values[i][1]) / x)
    return statistics.median(slopes) * 7


def trends(day: date, history: SeriesHistory) -> list[MetricResult]:
    """Weekly Theil-Sen slope over 14/30/90 calendar days, ending on the current date."""
    results = []
    for key, unit in SERIES_UNITS.items():
        current, _ = _series_at(day, key, history)
        if current is None:
            continue
        for window, min_n in ((14, 7), (30, 14), (90, 30)):
            dated = []
            for offset in range(window - 1, -1, -1):
                candidate_day = day - timedelta(days=offset)
                value, lineage = _series_at(candidate_day, key, history)
                if value is not None and lineage is not None:
                    dated.append((candidate_day, value, lineage))
            enough = len(dated) >= min_n and len(dated) / window >= .6
            # Do not describe a long unmeasured gap as continuous trend.
            max_gap = max(((b[0] - a[0]).days for a, b in zip(dated, dated[1:])), default=0)
            enough = enough and max_gap <= 7
            slope = _theil_sen(dated) if enough else None
            results.append(_metric(f"trend.{key}.{window}d.theilsen", day, slope, f"{unit}/week",
                                   ("REDUCED" if key in {"respiratory", "stress_vendor"} else "VALID")
                                   if slope is not None else "CALIBRATING",
                                   "trend.vitals_theilsen_calendar_v1",
                                   tuple(ref for _, _, ref in dated),
                                   {"window_calendar_days": window, "history_count": len(dated),
                                    "required_history_count": min_n, "required_coverage": .6,
                                    "max_gap_days": max_gap, "includes_current_date": True,
                                    "x_axis": "actual_calendar_days"},
                                   upstream_project="Vitals", upstream_commit=VITALS_COMMIT,
                                   confidence="MEDIUM" if slope is not None else "LOW"))
    return results
