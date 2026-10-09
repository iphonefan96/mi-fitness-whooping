"""Recovery and direct nightly/daily vitals over canonical inputs.

The formulas, gates, statuses and metadata are the existing baseline behavior
(Legacy `foundations.direct_metrics` vitals branch and `recovery`), moved here
unchanged. This module has no SQLite, CLI, clock, profile or Legacy dependency.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

from mi_fitness_whooping.domain.metrics import FeatureLineage, MetricResult
from mi_fitness_whooping.domain.recovery_vitals.contracts import (
    RecoveryTarget, VitalsDaily, VitalsNight,
)


# Direct vitals are part of the existing foundation metric family; the runner
# tracks this version as `foundation_algorithm_version`.
DIRECT_VITALS_ALGORITHM_VERSION = "foundation-2"
RECOVERY_ALGORITHM_VERSION = "vitals-anchored-v3-local-gates-2"
OPENSTRAP_COMMIT = "0441ef9e6fc6d5681c309ce6341911285e829f20"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
WEIGHTS = {"hrv": .55, "rhr": .25, "sleep": .20}


def _direct(name: str, day: date, value: float | None, unit: str, status: str,
            algorithm_id: str, lineage: tuple[FeatureLineage, ...], metadata: dict, *,
            source_type: str = "OUR_DERIVED", upstream_project: str | None = None,
            upstream_commit: str | None = None, confidence: str = "MEDIUM") -> MetricResult:
    return MetricResult(name, day, value, unit, status, algorithm_id,
                        DIRECT_VITALS_ALGORITHM_VERSION, lineage, metadata, source_type,
                        upstream_project, upstream_commit, confidence)


def _valid_number(value: object, lo: float | None = None, hi: float | None = None) -> float | None:
    # Existing foundation gate: bool is accepted as a number here.
    if not isinstance(value, (float, int)) or not math.isfinite(value):
        return None
    num = float(value)
    if (lo is not None and num < lo) or (hi is not None and num > hi):
        return None
    return num


def night_heart_rate(day: date, night: VitalsNight) -> MetricResult:
    rhr = _valid_number(night.night_rhr_bpm, 25, 240)
    return _direct("rhr.nightly", day, rhr, "bpm", "VALID" if rhr is not None else "INSUFFICIENT_DATA",
                   "rhr.openstrap_nocturnal_v1", (night.lineage,),
                   {"method": "minimum_30min_mean", "required_minutes_per_window": 27,
                    "measured_minutes": night.night_hr_measured_minutes},
                   upstream_project="OpenStrap", upstream_commit=OPENSTRAP_COMMIT)


def night_spo2(day: date, night: VitalsNight) -> tuple[MetricResult, ...]:
    lineage = (night.lineage,)
    spo2_count = int(night.spo2_samples or 0)
    results = [_direct("spo2.nightly_count", day, float(spo2_count), "samples", "VALID",
                       "spo2.observed_count_v1", lineage, {"observed": True}, confidence="HIGH")]
    span = _valid_number(night.spo2_span_min, 0)
    results.append(_direct("spo2.nightly_span_min", day, span, "min",
                           "VALID" if span is not None else "INSUFFICIENT_DATA",
                           "spo2.observed_span_v1", lineage, {"not_time_under_threshold": True}))
    for suffix, raw, minimum in (("mean", night.spo2_mean_pct, 6), ("min", night.spo2_min_pct, 12),
                                 ("p10", night.spo2_p10_pct, 12)):
        value = _valid_number(raw, 0, 100)
        results.append(_direct(f"spo2.nightly_{suffix}", day, value, "%",
                               "VALID" if value is not None else "INSUFFICIENT_DATA",
                               "spo2.night_distribution_v1", lineage,
                               {"sample_count": spo2_count, "required_samples": minimum,
                                "observed_span_min": span, "required_span_min": 240},
                               confidence="MEDIUM" if suffix == "mean" else "LOW"))
    return tuple(results)


def night_respiratory(day: date, night: VitalsNight) -> MetricResult:
    resp = _valid_number(night.respiratory_rate_bpm, 4, 60)
    return _direct("respiratory.nightly_mean", day, resp, "breaths/min",
                   "REDUCED" if resp is not None else "INSUFFICIENT_DATA",
                   "respiratory.xiaomi_night_mean_v1", (night.lineage,),
                   {"vendor_aggregate_count": 1 if resp is not None else 0,
                    "raw_breath_count": None, "coverage": "UNKNOWN",
                    "source_metric": night.respiratory_provenance},
                   source_type="VENDOR_DERIVED", confidence="LOW")


def vendor_daily_rhr(day: date, night: VitalsNight | None,
                     daily: VitalsDaily | None) -> MetricResult | None:
    """Vendor daily RHR, falling back to the date-joined value on the night."""
    rhr = _valid_number(daily.daily_rhr_bpm, 25, 240) if daily else None
    lineage = (daily.lineage,) if daily and rhr is not None else ()
    if rhr is None and night:
        rhr = _valid_number(night.rhr_bpm, 25, 240)
        lineage = (night.lineage,) if rhr is not None else ()
    if rhr is None:
        return None
    return _direct("rhr.vendor_daily", day, rhr, "bpm", "VALID", "xiaomi.vendor_rhr_v1", lineage,
                   {"source_metric": "daily_summary.resting_hr", "method": "vendor_daily"},
                   source_type="VENDOR_DERIVED")


@dataclass(frozen=True)
class Baseline:
    mean: float
    sd: float | None
    count: int
    recent_30d_count: int
    last_date: date


@dataclass(frozen=True)
class _VitalsV3Input:
    hrv_rmssd_ms: float | None
    rhr_bpm: float | None
    asleep_min: float | None
    sleep_target_min: float | None
    hrv_baseline: Baseline | None
    rhr_baseline: Baseline | None


@dataclass(frozen=True)
class _VitalsV3Output:
    score: int | None
    components: dict[str, float]
    normalized_weights: dict[str, float]
    weighted_z: float | None


def _valid(value: object, lo: float, hi: float) -> float | None:
    # Existing Recovery gate: bool is rejected.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) and lo <= v <= hi else None


def _vitals_v3(inp: _VitalsV3Input) -> _VitalsV3Output:
    """Vitals v3 present-component weighted z/logistic branch."""
    components: dict[str, float] = {}
    hrv = _valid(inp.hrv_rmssd_ms, 0.001, 10000)
    rhr = _valid(inp.rhr_bpm, 25, 240)
    asleep = _valid(inp.asleep_min, 0.001, 1440)
    target = _valid(inp.sleep_target_min, 300, 720)
    if hrv is not None and inp.hrv_baseline is not None:
        components["hrv"] = (hrv - inp.hrv_baseline.mean) / max(inp.hrv_baseline.sd or 0, 3.0)
    if rhr is not None and inp.rhr_baseline is not None:
        components["rhr"] = (inp.rhr_baseline.mean - rhr) / max(inp.rhr_baseline.sd or 0, 1.5)
    if asleep is not None and target is not None:
        components["sleep"] = ((asleep / target) - 1) / .12
    # Upstream rejects RHR-only, but permits sleep-only and HRV-only.
    if not components or ("hrv" not in components and "sleep" not in components):
        return _VitalsV3Output(None, components, {}, None)
    total = sum(WEIGHTS[k] for k in components)
    normalized = {k: WEIGHTS[k] / total for k in components}
    weighted_z = sum(components[k] * normalized[k] for k in components)
    score = round(100 / (1 + math.exp(-(1.06 + .85 * weighted_z))))
    return _VitalsV3Output(score, components, normalized, weighted_z)


def _baseline(day: date, nights: Mapping[date, VitalsNight], field: str,
              lo: float, hi: float) -> tuple[Baseline | None, tuple[FeatureLineage, ...]]:
    # Strictly prior 90 calendar days, latest 30 readings; no self-baseline.
    readings = [(d, n, _valid(getattr(n, field), lo, hi)) for d, n in nights.items()
                if day - timedelta(days=90) <= d < day]
    readings = sorted(((d, n, v) for d, n, v in readings if v is not None), key=lambda x: x[0])[-30:]
    if not readings:
        return None, ()
    values = [v for _, _, v in readings]
    baseline = Baseline(statistics.mean(values), statistics.pstdev(values) if len(values) >= 2 else None,
                        len(values), sum(d >= day - timedelta(days=30) for d, _, _ in readings), readings[-1][0])
    return baseline, tuple(n.lineage for _, n, _ in readings)


def _ready(base: Baseline | None, day: date) -> bool:
    return bool(base and base.count >= 5 and base.recent_30d_count >= 5 and
                (day - base.last_date).days <= 14)


def calculate_recovery(day: date, nights: Mapping[date, VitalsNight],
                       target: RecoveryTarget) -> MetricResult | None:
    """Recovery for one date from selected nights; None when the date has no night."""
    night = nights.get(day)
    if night is None:
        return None
    hrv = _valid(night.hrv_rmssd_ms, .001, 10000)
    rhr = _valid(night.rhr_bpm, 25, 240)  # date-joined vendor daily RHR, not nocturnal trough
    asleep = _valid(night.tst_min, .001, 1440) if night.stage_coverage == "COMPLETE" else None
    target_min = float(target.minutes)
    hrv_baseline, hrv_lineage = _baseline(day, nights, "hrv_rmssd_ms", .001, 10000)
    rhr_baseline, rhr_lineage = _baseline(day, nights, "rhr_bpm", 25, 240)
    # Explicit project quality gate: no current or stale baseline contribution.
    gated_hrv = hrv if _ready(hrv_baseline, day) else None
    gated_rhr = rhr if _ready(rhr_baseline, day) else None
    out = _vitals_v3(_VitalsV3Input(gated_hrv, gated_rhr, asleep, target_min,
                                    hrv_baseline if gated_hrv is not None else None,
                                    rhr_baseline if gated_rhr is not None else None))
    # Current Xiaomi requires both completed sleep and warmed RHR. A future
    # genuine-HRV source may use other Vitals-supported partial combinations.
    xiaomi_gate = gated_hrv is None and (asleep is None or gated_rhr is None)
    ready_score = out.score is not None and not xiaomi_gate
    score = out.score if ready_score else None
    if ready_score:
        full = set(out.components) == {"hrv", "rhr", "sleep"}
        status, mode = ("VALID", "FULL") if full else ("REDUCED", "REDUCED")
    elif hrv is None and asleep is None:
        status, mode = "INSUFFICIENT_DATA", None
    elif (rhr is not None and not _ready(rhr_baseline, day)) or (hrv is not None and not _ready(hrv_baseline, day)):
        status, mode = "CALIBRATING", None
    else:
        status, mode = "INSUFFICIENT_DATA", None
    unique = {ref.fingerprint: ref for ref in (night.lineage, *rhr_lineage, *hrv_lineage)}
    metadata = {"mode": mode, "active_components": sorted(out.components) if ready_score else [],
                "missing_components": sorted(set(WEIGHTS) - set(out.components)),
                "z_scores": out.components if ready_score else {},
                "normalized_weights": out.normalized_weights if ready_score else {},
                "weighted_z": out.weighted_z if ready_score else None,
                "logistic_input": 1.06 + .85 * out.weighted_z if ready_score else None,
                "temporary_sleep_target": target.is_default,
                "sleep_target_min": target_min,
                "rhr_baseline": vars(rhr_baseline) | {"last_date": rhr_baseline.last_date.isoformat()} if rhr_baseline else None,
                "hrv_baseline": vars(hrv_baseline) | {"last_date": hrv_baseline.last_date.isoformat()} if hrv_baseline else None,
                "history_count": rhr_baseline.count if rhr_baseline else 0,
                "required_history_count": 5,
                "baseline_window_calendar_days": 90,
                "baseline_take_readings": 30,
                "baseline_excludes_current": True,
                "local_xiaomi_requires_sleep_and_rhr": gated_hrv is None}
    return MetricResult("recovery.score", day, score, "score_0_100", status,
                        "recovery.vitals_anchored_v3", RECOVERY_ALGORITHM_VERSION,
                        tuple(unique.values()), metadata, "OUR_DERIVED", "Vitals", VITALS_COMMIT,
                        "MEDIUM")
