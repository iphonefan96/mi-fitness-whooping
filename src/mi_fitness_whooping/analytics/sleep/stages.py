"""Existing sleep stage durations, shares, efficiency and regularity.

The formulas, gates, statuses and metadata are the existing foundation
behavior (Legacy `foundations.direct_metrics` sleep branch and `regularity`),
moved here unchanged. Independent of the locked Sleep Core V1 calculator; no
SQLite, CLI, clock, profile or Legacy dependency.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Mapping

from mi_fitness_whooping.domain.metrics import FeatureLineage, MetricResult
from mi_fitness_whooping.domain.sleep.observations import SleepStagesNight


# Part of the existing foundation metric family; the runner tracks this
# version as `foundation_algorithm_version`.
STAGES_ALGORITHM_VERSION = "foundation-2"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"


def _metric(name: str, day: date, value: float | None, unit: str, status: str,
            algorithm_id: str, lineage: tuple[FeatureLineage, ...], metadata: dict, *,
            upstream_project: str | None = None, upstream_commit: str | None = None,
            confidence: str = "MEDIUM") -> MetricResult:
    return MetricResult(name, day, value, unit, status, algorithm_id, STAGES_ALGORITHM_VERSION,
                        lineage, metadata, "OUR_DERIVED", upstream_project, upstream_commit,
                        confidence)


def _valid_number(value: object, lo: float | None = None, hi: float | None = None) -> float | None:
    # Existing foundation gate: bool is accepted as a number here.
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    num = float(value)
    if (lo is not None and num < lo) or (hi is not None and num > hi):
        return None
    return num


def stage_metrics(day: date, night: SleepStagesNight) -> list[MetricResult]:
    """Time in bed, TST, stage minutes, efficiency and stage shares for one night."""
    results: list[MetricResult] = []
    inp = (night.lineage,)
    tib = _valid_number(night.time_in_bed_min, 0, 1440)
    complete = night.stage_coverage == "COMPLETE" and "SENSOR_GAP" not in night.lineage.quality_flags
    tst = _valid_number(night.tst_min, 0, 1440) if complete else None
    stage_values = {key: _valid_number(getattr(night, key), 0, 1440) if complete else None
                    for key in ("awake_min", "light_min", "deep_min", "rem_min")}
    if complete and any(value is None for value in stage_values.values()):
        complete = False
        tst = None
        stage_values = {key: None for key in stage_values}
    if tst is not None and tib is not None and (tst > tib + 1 or
        abs(tst + (stage_values["awake_min"] or 0) - tib) > 1):
        tst = None
        stage_values = {key: None for key in stage_values}
        complete = False
    for name, value in (("sleep.time_in_bed_min", tib), ("sleep.total_sleep_time_min", tst),
                        *[("sleep." + key, value) for key, value in stage_values.items()]):
        results.append(_metric(name, day, value, "min", "VALID" if value is not None else "INSUFFICIENT_DATA",
                               "sleep.stage_duration_v1" if name != "sleep.time_in_bed_min" else "sleep.session_span_v1",
                               inp, {"stage_coverage": night.stage_coverage}))
    efficiency = 100 * tst / tib if tst is not None and tib and tib > 0 else None
    if efficiency is not None and not 0 <= efficiency <= 100.1:
        efficiency = None
    results.append(_metric("sleep.efficiency_pct", day, efficiency, "%",
                           "VALID" if efficiency is not None else "INSUFFICIENT_DATA",
                           "sleep.tst_over_tib_v1", inp,
                           {"numerator": "total_sleep_time_min", "denominator": "time_in_bed_min"}))
    for stage, denom, denom_name in (("deep", tst, "TST"), ("rem", tst, "TST"),
                                    ("light", tst, "TST"), ("awake", tib, "TIME_IN_BED")):
        stage_min = stage_values[stage + "_min"]
        pct = 100 * stage_min / denom if stage_min is not None and denom and denom > 0 else None
        if pct is not None and not 0 <= pct <= 100:
            pct = None
        results.append(_metric(f"sleep.{stage}_pct", day, pct, "%",
                               "VALID" if pct is not None else "INSUFFICIENT_DATA",
                               "sleep.stage_share_v1", inp,
                               {"denominator": denom_name, "numerator": f"{stage}_min"}))
    return results


def _circular_sd_minutes(values: list[float]) -> float:
    angles = [2 * math.pi * v / 1440 for v in values]
    center = math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))
    center_min = (center * 1440 / (2 * math.pi)) % 1440
    residuals = [((v - center_min + 720) % 1440) - 720 for v in values]
    return statistics.pstdev(residuals)


def regularity(day: date, nights: Mapping[date, SleepStagesNight]) -> MetricResult | None:
    """Vitals circular bed/wake consistency over 14 calendar nights including today."""
    current = nights.get(day)
    if current is None or current.stage_coverage != "COMPLETE":
        return None
    window = [nights[d] for offset in range(13, -1, -1)
              if (d := day - timedelta(days=offset)) in nights and
              nights[d].stage_coverage == "COMPLETE" and
              nights[d].bedtime_local_min is not None and
              nights[d].wake_local_min is not None]
    n = len(window)
    lineage = tuple(night.lineage for night in window)
    metadata = {"window_calendar_days": 14, "history_count": n,
                "required_history_count": 5, "includes_current_night": True,
                "clock_method": "circular_unwrap_then_population_sd"}
    if n < 5:
        return _metric("sleep.regularity", day, None, "score_0_100", "CALIBRATING",
                       "sleep.vitals_consistency_circular_v1", lineage, metadata,
                       upstream_project="Vitals", upstream_commit=VITALS_COMMIT, confidence="LOW")
    bed_sd = _circular_sd_minutes([float(f.bedtime_local_min) for f in window])
    wake_sd = _circular_sd_minutes([float(f.wake_local_min) for f in window])
    sigma = (bed_sd + wake_sd) / 2
    score = float(round(100 * (1 - max(0, min(100, sigma - 20)) / 100)))
    metadata.update({"bedtime_sd_min": bed_sd, "wake_sd_min": wake_sd, "combined_sd_min": sigma})
    return _metric("sleep.regularity", day, score, "score_0_100", "VALID",
                   "sleep.vitals_consistency_circular_v1", lineage, metadata,
                   upstream_project="Vitals", upstream_commit=VITALS_COMMIT)
