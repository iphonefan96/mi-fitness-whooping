"""Transparent foundation metrics on typed feature records, never SQL rows."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mi_fitness_whooping.analytics.recovery_vitals import core as vitals
from mi_fitness_whooping.analytics.series import core as series_core
from mi_fitness_whooping.domain.metrics import MetricResult
from mi_fitness_whooping.domain.series.contracts import SeriesHistory
from mi_fitness_whooping.integration.recovery_vitals.adapter import vitals_daily, vitals_night


VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
FOUNDATION_ALGORITHM_VERSION = "foundation-2"


@dataclass(frozen=True)
class FeatureRecord:
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
class MetricDraft:
    name: str
    day: date
    value: float | None
    unit: str | None
    status: str
    algorithm_id: str
    algorithm_version: str
    source_type: str = "OUR_DERIVED"
    upstream_project: str | None = None
    upstream_commit: str | None = None
    inputs: tuple[FeatureRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: str = "MEDIUM"


def _metric(name: str, day: date, value: float | None, unit: str | None,
            status: str, algorithm_id: str, *, inputs: tuple[FeatureRecord, ...] = (),
            source_type: str = "OUR_DERIVED", upstream_project: str | None = None,
            upstream_commit: str | None = None, metadata: dict | None = None,
            confidence: str = "MEDIUM") -> MetricDraft:
    return MetricDraft(name, day, value, unit, status, algorithm_id, FOUNDATION_ALGORITHM_VERSION,
                       source_type, upstream_project, upstream_commit, inputs, metadata or {}, confidence)


def _valid_number(value: object, lo: float | None = None, hi: float | None = None) -> float | None:
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    num = float(value)
    if (lo is not None and num < lo) or (hi is not None and num > hi):
        return None
    return num


def direct_metrics(day: date, night: FeatureRecord | None,
                   daily: FeatureRecord | None) -> list[MetricDraft | MetricResult]:
    # Vitals are calculated by the Recovery/vitals component; this keeps the
    # existing persistence order around the sleep duration metrics.
    vitals_n = vitals_night(night) if night else None
    vitals_d = vitals_daily(daily) if daily else None
    results: list[MetricDraft | MetricResult] = []
    if night:
        v = night.values
        inp = (night,)
        results.append(vitals.night_heart_rate(day, vitals_n))
        tib = _valid_number(v.get("time_in_bed_min"), 0, 1440)
        complete = v.get("stage_coverage") == "COMPLETE" and "SENSOR_GAP" not in night.quality_flags
        tst = _valid_number(v.get("tst_min"), 0, 1440) if complete else None
        stage_values = {key: _valid_number(v.get(key), 0, 1440) if complete else None
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
                                   inputs=inp, metadata={"stage_coverage": v.get("stage_coverage")}, confidence="MEDIUM"))
        efficiency = 100 * tst / tib if tst is not None and tib and tib > 0 else None
        if efficiency is not None and not 0 <= efficiency <= 100.1:
            efficiency = None
        results.append(_metric("sleep.efficiency_pct", day, efficiency, "%",
                               "VALID" if efficiency is not None else "INSUFFICIENT_DATA",
                               "sleep.tst_over_tib_v1", inputs=inp,
                               metadata={"numerator": "total_sleep_time_min", "denominator": "time_in_bed_min"}))
        for stage, denom, denom_name in (("deep", tst, "TST"), ("rem", tst, "TST"),
                                        ("light", tst, "TST"), ("awake", tib, "TIME_IN_BED")):
            stage_min = stage_values[stage + "_min"]
            pct = 100 * stage_min / denom if stage_min is not None and denom and denom > 0 else None
            if pct is not None and not 0 <= pct <= 100:
                pct = None
            results.append(_metric(f"sleep.{stage}_pct", day, pct, "%",
                                   "VALID" if pct is not None else "INSUFFICIENT_DATA",
                                   "sleep.stage_share_v1", inputs=inp,
                                   metadata={"denominator": denom_name, "numerator": f"{stage}_min"}))

        results.extend(vitals.night_spo2(day, vitals_n))
        results.append(vitals.night_respiratory(day, vitals_n))

    vendor = vitals.vendor_daily_rhr(day, vitals_n, vitals_d)
    if vendor is not None:
        results.append(vendor)
    return results


def _circular_sd_minutes(values: list[float]) -> float:
    angles = [2 * math.pi * v / 1440 for v in values]
    center = math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))
    center_min = (center * 1440 / (2 * math.pi)) % 1440
    residuals = [((v - center_min + 720) % 1440) - 720 for v in values]
    return statistics.pstdev(residuals)


def regularity(day: date, nights: dict[date, FeatureRecord]) -> MetricDraft | None:
    current = nights.get(day)
    if current is None or current.values.get("stage_coverage") != "COMPLETE":
        return None
    window = [nights[d] for offset in range(13, -1, -1)
              if (d := day - timedelta(days=offset)) in nights and
              nights[d].values.get("stage_coverage") == "COMPLETE" and
              nights[d].values.get("bedtime_local_min") is not None and
              nights[d].values.get("wake_local_min") is not None]
    n = len(window)
    metadata = {"window_calendar_days": 14, "history_count": n,
                "required_history_count": 5, "includes_current_night": True,
                "clock_method": "circular_unwrap_then_population_sd"}
    if n < 5:
        return _metric("sleep.regularity", day, None, "score_0_100", "CALIBRATING",
                       "sleep.vitals_consistency_circular_v1", inputs=tuple(window),
                       upstream_project="Vitals", upstream_commit=VITALS_COMMIT,
                       metadata=metadata, confidence="LOW")
    bed_sd = _circular_sd_minutes([float(f.values["bedtime_local_min"]) for f in window])
    wake_sd = _circular_sd_minutes([float(f.values["wake_local_min"]) for f in window])
    sigma = (bed_sd + wake_sd) / 2
    score = float(round(100 * (1 - max(0, min(100, sigma - 20)) / 100)))
    metadata.update({"bedtime_sd_min": bed_sd, "wake_sd_min": wake_sd, "combined_sd_min": sigma})
    return _metric("sleep.regularity", day, score, "score_0_100", "VALID",
                   "sleep.vitals_consistency_circular_v1", inputs=tuple(window),
                   upstream_project="Vitals", upstream_commit=VITALS_COMMIT,
                   metadata=metadata)


def calculate_day(day: date, nights: dict[date, FeatureRecord],
                  dailies: dict[date, FeatureRecord],
                  series: SeriesHistory) -> list[MetricDraft | MetricResult]:
    """Foundation metrics for one date in the existing persistence order.

    Sleep duration metrics and regularity are drafts here; vitals, baselines,
    deviations and trends come from their components as `MetricResult`s.
    """
    result = direct_metrics(day, nights.get(day), dailies.get(day))
    reg = regularity(day, nights)
    if reg is not None:
        result.append(reg)
    result.extend(series_core.baselines(day, series))
    result.extend(series_core.trends(day, series))
    return result
