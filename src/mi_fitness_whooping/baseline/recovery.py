"""Vitals v3 Recovery on device-independent nightly measurements."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from mi_fitness_whooping.baseline.foundations import FeatureRecord, MetricDraft
from mi_fitness_whooping.baseline.profile import effective_values


RECOVERY_ALGORITHM_VERSION = "vitals-anchored-v3-local-gates-2"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
WEIGHTS = {"hrv": .55, "rhr": .25, "sleep": .20}


@dataclass(frozen=True)
class Baseline:
    mean: float
    sd: float | None
    count: int
    recent_30d_count: int
    last_date: date


@dataclass(frozen=True)
class RecoveryInput:
    day: date
    hrv_rmssd_ms: float | None
    rhr_bpm: float | None
    asleep_min: float | None
    sleep_target_min: float | None
    hrv_baseline: Baseline | None
    rhr_baseline: Baseline | None


@dataclass(frozen=True)
class RecoveryOutput:
    score: int | None
    components: dict[str, float]
    normalized_weights: dict[str, float]
    weighted_z: float | None


def _valid(value, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) and lo <= v <= hi else None


def vitals_v3(inp: RecoveryInput) -> RecoveryOutput:
    """Exact active Vitals v3 present-component weighted z/logistic branch.

    The DTO is source-independent. Eligibility of baselines/current Xiaomi is
    separately applied by the runner assembly below.
    """
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
        return RecoveryOutput(None, components, {}, None)
    total = sum(WEIGHTS[k] for k in components)
    normalized = {k: WEIGHTS[k] / total for k in components}
    weighted_z = sum(components[k] * normalized[k] for k in components)
    score = round(100 / (1 + math.exp(-(1.06 + .85 * weighted_z))))
    return RecoveryOutput(score, components, normalized, weighted_z)


def _baseline(day: date, nights: dict[date, FeatureRecord], field: str,
              lo: float, hi: float) -> tuple[Baseline | None, tuple[FeatureRecord, ...]]:
    # Project Step-3/4 gate: strictly prior 90 calendar days, latest 30 readings.
    # Vitals upstream includes D; the local no-self-baseline rule is deliberate.
    readings = [(d, n, _valid(n.values.get(field), lo, hi)) for d, n in nights.items()
                if day - timedelta(days=90) <= d < day]
    readings = sorted(((d, n, v) for d, n, v in readings if v is not None), key=lambda x: x[0])[-30:]
    if not readings:
        return None, ()
    values = [v for _, _, v in readings]
    baseline = Baseline(statistics.mean(values), statistics.pstdev(values) if len(values) >= 2 else None,
                        len(values), sum(d >= day - timedelta(days=30) for d, _, _ in readings), readings[-1][0])
    return baseline, tuple(n for _, n, _ in readings)


def _ready(base: Baseline | None, day: date) -> bool:
    return bool(base and base.count >= 5 and base.recent_30d_count >= 5 and
                (day - base.last_date).days <= 14)


def calculate_recovery_day(day: date, nights: dict[date, FeatureRecord], profile: dict) -> list[MetricDraft]:
    night = nights.get(day)
    if night is None:
        return []
    v = night.values
    hrv = _valid(v.get("hrv_rmssd_ms"), .001, 10000)
    rhr = _valid(v.get("rhr_bpm"), 25, 240)  # date-joined vendor daily RHR, not nocturnal trough
    asleep = (_valid(v.get("tst_min"), .001, 1440)
              if v.get("stage_coverage") == "COMPLETE" else None)
    raw_target = effective_values(profile, day).get("sleep_target_min")
    temporary_target = raw_target is None
    target = _valid(raw_target if raw_target is not None else 480, 300, 720)
    if target is None:
        raise ValueError("sleep_target_min must be within 300..720")
    hrv_baseline, hrv_features = _baseline(day, nights, "hrv_rmssd_ms", .001, 10000)
    rhr_baseline, rhr_features = _baseline(day, nights, "rhr_bpm", 25, 240)
    # Explicit project quality gate: no current or stale baseline contribution.
    gated_hrv = hrv if _ready(hrv_baseline, day) else None
    gated_rhr = rhr if _ready(rhr_baseline, day) else None
    inp = RecoveryInput(day, gated_hrv, gated_rhr, asleep, target,
                        hrv_baseline if gated_hrv is not None else None,
                        rhr_baseline if gated_rhr is not None else None)
    out = vitals_v3(inp)
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
    unique_inputs = {f.fingerprint: f for f in (night, *rhr_features, *hrv_features)}
    inputs = tuple(unique_inputs.values())
    metadata = {"mode": mode, "active_components": sorted(out.components) if ready_score else [],
                "missing_components": sorted(set(WEIGHTS) - set(out.components)),
                "z_scores": out.components if ready_score else {},
                "normalized_weights": out.normalized_weights if ready_score else {},
                "weighted_z": out.weighted_z if ready_score else None,
                "logistic_input": 1.06 + .85 * out.weighted_z if ready_score else None,
                "temporary_sleep_target": temporary_target,
                "sleep_target_min": target,
                "rhr_baseline": vars(rhr_baseline) | {"last_date": rhr_baseline.last_date.isoformat()} if rhr_baseline else None,
                "hrv_baseline": vars(hrv_baseline) | {"last_date": hrv_baseline.last_date.isoformat()} if hrv_baseline else None,
                "history_count": rhr_baseline.count if rhr_baseline else 0,
                "required_history_count": 5,
                "baseline_window_calendar_days": 90,
                "baseline_take_readings": 30,
                "baseline_excludes_current": True,
                "local_xiaomi_requires_sleep_and_rhr": gated_hrv is None}
    return [MetricDraft("recovery.score", day, score, "score_0_100", status,
                        "recovery.vitals_anchored_v3", RECOVERY_ALGORITHM_VERSION,
                        "OUR_DERIVED", "Vitals", VITALS_COMMIT, inputs, metadata, "MEDIUM")]
