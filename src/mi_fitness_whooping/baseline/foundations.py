"""Transparent foundation metrics on typed feature records, never SQL rows."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from mi_fitness_whooping.analytics.recovery_vitals import core as vitals
from mi_fitness_whooping.domain.metrics import MetricResult
from mi_fitness_whooping.integration.recovery_vitals.adapter import vitals_daily, vitals_night


VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
PULSE_COMMIT = "1f8975cfc8298b67482a7e37dba576b9ea8b62db"
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


def _vitals_draft(result: MetricResult, records: dict[tuple[str, str], FeatureRecord]) -> MetricDraft:
    return MetricDraft(result.name, result.day, result.value, result.unit, result.status,
                       result.algorithm_id, result.algorithm_version, result.source_type,
                       result.upstream_project, result.upstream_commit,
                       tuple(records[ref.kind, ref.fingerprint] for ref in result.lineage),
                       result.metadata, result.confidence)


def direct_metrics(day: date, night: FeatureRecord | None, daily: FeatureRecord | None) -> list[MetricDraft]:
    # Vitals are calculated by the Recovery/vitals component; this keeps the
    # existing persistence order around the sleep duration metrics.
    records = {(f.kind, f.fingerprint): f for f in (night, daily) if f is not None}
    vitals_n = vitals_night(night) if night else None
    vitals_d = vitals_daily(daily) if daily else None
    results: list[MetricDraft] = []
    if night:
        v = night.values
        inp = (night,)
        results.append(_vitals_draft(vitals.night_heart_rate(day, vitals_n), records))
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

        results.extend(_vitals_draft(r, records) for r in vitals.night_spo2(day, vitals_n))
        results.append(_vitals_draft(vitals.night_respiratory(day, vitals_n), records))

    vendor = vitals.vendor_daily_rhr(day, vitals_n, vitals_d)
    if vendor is not None:
        results.append(_vitals_draft(vendor, records))
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


SERIES = {
    "rhr": ("daily", "daily_rhr_bpm", "bpm"),
    "sleep_tst": ("nightly", "tst_min", "min"),
    "spo2": ("nightly", "spo2_mean_pct", "%"),
    "respiratory": ("nightly", "respiratory_rate_bpm", "breaths/min"),
    "steps": ("daily", "steps", "steps"),
    "stress_vendor": ("daily", "vendor_stress_median", "vendor_scale"),
}


def _series_at(day: date, key: str, nights: dict[date, FeatureRecord],
               dailies: dict[date, FeatureRecord]) -> tuple[float | None, FeatureRecord | None]:
    kind, field, _ = SERIES[key]
    feature = (nights if kind == "nightly" else dailies).get(day)
    if feature is None:
        return None, None
    value = _valid_number(feature.values.get(field))
    if key == "spo2" and value is not None and not 0 < value <= 100:
        value = None
    if key == "respiratory" and value is not None and not 4 <= value <= 60:
        value = None
    if key == "rhr" and value is not None and not 25 <= value <= 240:
        value = None
    if key in {"sleep_tst", "steps"} and value is not None and value < 0:
        value = None
    return value, feature


def _prior_series(day: date, key: str, nights: dict[date, FeatureRecord],
                  dailies: dict[date, FeatureRecord], days: int = 30) -> list[tuple[date, float, FeatureRecord]]:
    output = []
    for offset in range(days, 0, -1):
        past = day - timedelta(days=offset)
        value, feature = _series_at(past, key, nights, dailies)
        if value is not None and feature is not None:
            output.append((past, value, feature))
    return output


def baselines(day: date, nights: dict[date, FeatureRecord],
              dailies: dict[date, FeatureRecord]) -> list[MetricDraft]:
    results = []
    for key in ("rhr", "sleep_tst", "spo2", "respiratory"):
        current, current_feature = _series_at(day, key, nights, dailies)
        if current is None or current_feature is None:
            continue
        history = _prior_series(day, key, nights, dailies)
        recent = bool(history and (day - history[-1][0]).days <= 14)
        ready = len(history) >= 5 and recent
        unit = SERIES[key][2]
        metadata = {"window_calendar_days": 30, "history_count": len(history),
                    "required_history_count": 5, "last_prior_date": history[-1][0].isoformat() if history else None,
                    "max_last_observation_age_days": 14, "excludes_current_date": True}
        inputs = (current_feature, *(f for _, _, f in history))
        values = [v for _, v, _ in history]
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
                                   f"baseline.pulse_{key}_band_v1",
                                   inputs=inputs, upstream_project="Pulse", upstream_commit=PULSE_COMMIT,
                                   metadata=extra, confidence="MEDIUM" if ready else "LOW"))
            delta = current - mean if mean is not None else None
            results.append(_metric(f"{key}.deviation", day, delta, unit,
                                   "VALID" if delta is not None and key != "respiratory" else
                                   ("REDUCED" if delta is not None else "CALIBRATING"),
                                   f"deviation.{key}_delta_v1", inputs=inputs,
                                   metadata={"reference_metric": f"baseline.{key}.band_mean", **metadata}))
        # Standard EWMA level, distinct from the Pulse monitoring band.
        ewma = None
        if ready:
            alpha = 2 / 31
            ewma = values[0]
            for value in values[1:]:
                ewma = alpha * value + (1 - alpha) * ewma
        results.append(_metric(f"baseline.{key}.ewma", day, ewma, unit,
                               ("REDUCED" if key == "respiratory" else "VALID") if ewma is not None else "CALIBRATING",
                               f"baseline.ewma30_{key}_v1", inputs=inputs,
                               metadata={**metadata, "alpha": 2 / 31, "seed": "oldest_observation",
                                         "method": "EWMA_prior_30_calendar_days"}))
    return results


def _theil_sen(dated_values: list[tuple[date, float, FeatureRecord]]) -> float:
    slopes = []
    for i in range(len(dated_values) - 1):
        for j in range(i + 1, len(dated_values)):
            x = (dated_values[j][0] - dated_values[i][0]).days
            if x > 0:
                slopes.append((dated_values[j][1] - dated_values[i][1]) / x)
    return statistics.median(slopes) * 7


def trends(day: date, nights: dict[date, FeatureRecord],
           dailies: dict[date, FeatureRecord]) -> list[MetricDraft]:
    results = []
    for key, (_, _, unit) in SERIES.items():
        current, _ = _series_at(day, key, nights, dailies)
        if current is None:
            continue
        for window, min_n in ((14, 7), (30, 14), (90, 30)):
            dated = []
            for offset in range(window - 1, -1, -1):
                candidate_day = day - timedelta(days=offset)
                value, feature = _series_at(candidate_day, key, nights, dailies)
                if value is not None and feature is not None:
                    dated.append((candidate_day, value, feature))
            enough = len(dated) >= min_n and len(dated) / window >= .6
            # Do not describe a long unmeasured gap as continuous trend.
            max_gap = max(((b[0] - a[0]).days for a, b in zip(dated, dated[1:])), default=0)
            enough = enough and max_gap <= 7
            slope = _theil_sen(dated) if enough else None
            results.append(_metric(f"trend.{key}.{window}d.theilsen", day, slope, f"{unit}/week",
                                   ("REDUCED" if key in {"respiratory", "stress_vendor"} else "VALID")
                                   if slope is not None else "CALIBRATING",
                                   "trend.vitals_theilsen_calendar_v1", inputs=tuple(f for _, _, f in dated),
                                   upstream_project="Vitals", upstream_commit=VITALS_COMMIT,
                                   metadata={"window_calendar_days": window, "history_count": len(dated),
                                             "required_history_count": min_n, "required_coverage": .6,
                                             "max_gap_days": max_gap, "includes_current_date": True,
                                             "x_axis": "actual_calendar_days"},
                                   confidence="MEDIUM" if slope is not None else "LOW"))
    return results


def calculate_day(day: date, nights: dict[date, FeatureRecord],
                  dailies: dict[date, FeatureRecord]) -> list[MetricDraft]:
    result = direct_metrics(day, nights.get(day), dailies.get(day))
    reg = regularity(day, nights)
    if reg is not None:
        result.append(reg)
    result.extend(baselines(day, nights, dailies))
    result.extend(trends(day, nights, dailies))
    return result
