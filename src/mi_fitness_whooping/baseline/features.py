from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta, timezone

from mi_fitness_whooping.baseline import IMPLEMENTATION_VERSION
from mi_fitness_whooping.baseline.models import Feature, Freshness, QualityFlag, QualityStatus
from mi_fitness_whooping.baseline.normalization import input_fingerprint


FEATURE_CONTRACT_VERSION = "foundations-2"


def _wide_utc_bounds(day: date) -> tuple[datetime, datetime]:
    # Includes any civil date in the UTC-12..UTC+14 offset range.
    begin = datetime.combine(day - timedelta(days=2), time.min, timezone.utc)
    end = datetime.combine(day + timedelta(days=2), time.min, timezone.utc)
    return begin, end


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    i = (len(ordered) - 1) * fraction
    lo = int(i)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] * (hi - i) + ordered[hi] * (i - lo)


def _night_rhr(heart_rates) -> tuple[float | None, int]:
    minute_values: dict[int, list[float]] = {}
    for hr in heart_rates:
        if hr.quality_status != QualityStatus.OK:
            continue
        minute = int(hr.measurement_start.timestamp()) // 60
        minute_values.setdefault(minute, []).append(hr.bpm)
    if not minute_values:
        return None, 0
    observed = {minute: statistics.mean(values) for minute, values in minute_values.items()}
    candidates: list[float] = []
    for start in observed:
        window = [observed[m] for m in range(start, start + 30) if m in observed]
        if len(window) >= 27:
            candidates.append(statistics.mean(window))
    return (min(candidates) if candidates else None), len(observed)


def build_nightly(source, day: date, *, normalization_version: str, profile_revision: str,
                  source_policy_version: str = "primary-v1") -> Feature | None:
    wide_start, wide_end = _wide_utc_bounds(day)
    sessions = [s for s in source.sleep_sessions(wide_start, wide_end) if s.local_date == day and s.session_kind == "main"]
    if not sessions:
        return None
    # Stable main selection; never add overlapping sessions together.
    sessions.sort(key=lambda s: (s.has_stages, s.vendor_duration_min or 0, s.measurement_end,
                                 s.provenance.source_record_id), reverse=True)
    session = sessions[0]
    stages = list(source.sleep_stages(session))
    flags = set(session.quality_flags)
    valid_stages = bool(stages) and session.has_stages and all(
        s.stage in {"deep", "light", "rem", "awake"} and
        s.measurement_start >= session.measurement_start and s.measurement_end <= session.measurement_end
        for s in stages)
    ordered = sorted(stages, key=lambda s: s.measurement_start)
    if any(a.measurement_end > b.measurement_start for a, b in zip(ordered, ordered[1:])):
        valid_stages = False
    if ordered and (abs((ordered[0].measurement_start - session.measurement_start).total_seconds()) > 60 or
                    abs((session.measurement_end - ordered[-1].measurement_end).total_seconds()) > 60 or
                    any((b.measurement_start - a.measurement_end).total_seconds() > 60
                        for a, b in zip(ordered, ordered[1:]))):
        valid_stages = False
    if not valid_stages:
        flags.add(QualityFlag.STAGE_INCOMPLETE)
    durations = {kind: 0.0 for kind in ("deep", "light", "rem", "awake")}
    if valid_stages:
        for stage in stages:
            durations[stage.stage] += (stage.measurement_end - stage.measurement_start).total_seconds() / 60
    tst = sum(durations[k] for k in ("deep", "light", "rem")) if valid_stages else None
    tib = (session.measurement_end - session.measurement_start).total_seconds() / 60
    if tst is not None and abs(tib - sum(durations.values())) > 1:
        flags.add(QualityFlag.SENSOR_GAP)
        valid_stages = False
        tst = None
        durations = {kind: 0.0 for kind in ("deep", "light", "rem", "awake")}
    asleep = [s for s in ordered if s.stage in ("deep", "light", "rem")]
    waso = None
    awakening_durations = None
    if valid_stages and asleep:
        first, last = asleep[0].measurement_start, asleep[-1].measurement_end
        awakening_durations = [(s.measurement_end - s.measurement_start).total_seconds() / 60
                               for s in ordered if s.stage == "awake" and
                               s.measurement_start >= first and s.measurement_end <= last]
        waso = sum(awakening_durations)

    hrs = list(source.heart_rate(session.measurement_start, session.measurement_end))
    night_rhr, hr_minutes = _night_rhr(hrs)
    vendor_rhr = next((r.bpm for r in source.resting_hr(day, day + timedelta(days=1))), None)
    spo2_points = [p for p in source.spo2(session.measurement_start, session.measurement_end)
                   if p.quality_status == QualityStatus.OK]
    spo2_values = [p.percent for p in spo2_points]
    spo2_span = ((spo2_points[-1].measurement_start - spo2_points[0].measurement_start).total_seconds() / 60
                 if len(spo2_points) > 1 else 0)
    spo2_mean = statistics.mean(spo2_values) if len(spo2_values) >= 6 and spo2_span >= 240 else None
    spo2_min = min(spo2_values) if len(spo2_values) >= 12 and spo2_span >= 240 else None
    spo2_p10 = _percentile(spo2_values, .1) if spo2_min is not None else None
    if spo2_mean is None:
        flags.add(QualityFlag.LOW_COVERAGE)
    respiration = source.respiratory(session)
    hrv = source.nightly_hrv(session)
    if hrv is not None and (hrv.metric != "RMSSD" or hrv.unit != "ms" or hrv.value <= 0):
        raise ValueError("nightly HRV must be genuine positive RMSSD in ms")
    ids = tuple(s.provenance.source_record_id for s in [session, *stages, *hrs, *spo2_points])
    values = {
        "main_session_id": session.provenance.source_record_id,
        "sleep_start_utc": session.measurement_start.isoformat(),
        "sleep_end_utc": session.measurement_end.isoformat(),
        "utc_offset_seconds": session.utc_offset_seconds,
        "time_in_bed_min": tib,
        "tst_min": tst,
        "awake_min": durations["awake"] if valid_stages else None,
        "light_min": durations["light"] if valid_stages else None,
        "deep_min": durations["deep"] if valid_stages else None,
        "rem_min": durations["rem"] if valid_stages else None,
        "waso_min": waso,
        "awakening_durations_min": awakening_durations,
        "sleep_efficiency_pct": (100 * tst / tib) if tst is not None and tib > 0 and tst <= tib + 1 else None,
        "stage_coverage": "COMPLETE" if valid_stages else "UNKNOWN",
        "bedtime_local_min": ((session.measurement_start.timestamp() + (session.utc_offset_seconds or 0)) // 60) % 1440,
        "wake_local_min": ((session.measurement_end.timestamp() + (session.utc_offset_seconds or 0)) // 60) % 1440,
        "night_rhr_bpm": night_rhr,
        "night_hr_measured_minutes": hr_minutes,
        "rhr_bpm": vendor_rhr,
        "rhr_method": "xiaomi_vendor_daily" if vendor_rhr is not None else None,
        "respiratory_rate_bpm": respiration.breaths_per_min if respiration else None,
        "respiratory_provenance": respiration.provenance.source_metric if respiration else None,
        "spo2_mean_pct": spo2_mean,
        "spo2_min_pct": spo2_min,
        "spo2_p10_pct": spo2_p10,
        "spo2_samples": len(spo2_points),
        "spo2_span_min": spo2_span,
        "hrv_rmssd_ms": hrv.value if hrv else None,
        "hrv_lnrmssd": math.log(hrv.value) if hrv else None,
        "skin_temp_deviation_c": None,
    }
    digest = input_fingerprint(normalized_inputs={"policy": source_policy_version, "session": session,
                                                  "stages": stages, "hr": hrs, "spo2": spo2_points,
                                                  "respiration": respiration, "vendor_rhr": vendor_rhr,
                                                  "hrv": hrv, "values": values},
                               profile_revision=profile_revision, normalization_version=normalization_version,
                               algorithm_id="feature.nightly", algorithm_version="1",
                               input_contract_version=FEATURE_CONTRACT_VERSION,
                               implementation_version=IMPLEMENTATION_VERSION)
    return Feature(kind="nightly", metric_date=day, measurement_start=session.measurement_start,
                   measurement_end=session.measurement_end, values=values, source_ids=ids,
                   quality_status=QualityStatus.PARTIAL if flags else QualityStatus.OK,
                   quality_flags=frozenset(flags), input_fingerprint=digest,
                   freshness_status=Freshness.HISTORICAL)


def build_daily(source, day: date, *, normalization_version: str, profile_revision: str,
                source_policy_version: str = "primary-v1") -> Feature | None:
    activity = next(source.daily_activity(day, day + timedelta(days=1)), None)
    if activity is None:
        return None
    wide_start, wide_end = _wide_utc_bounds(day)
    hrs = [h for h in source.heart_rate(wide_start, wide_end) if h.local_date == day]
    spo2 = [p for p in source.spo2(wide_start, wide_end) if p.local_date == day and p.quality_status == QualityStatus.OK]
    stress = [s for s in source.stress(wide_start, wide_end) if s.local_date == day]
    rhr = next((r.bpm for r in source.resting_hr(day, day + timedelta(days=1))), None)
    hr_minutes = sorted({int(h.measurement_start.timestamp()) // 60 for h in hrs if h.quality_status == QualityStatus.OK})
    max_gap = max(((b - a) for a, b in zip(hr_minutes, hr_minutes[1:])), default=None)
    stress_values = [s.numeric_value for s in stress if s.numeric_value is not None]
    flags = set(activity.quality_flags)
    values = {
        "steps": activity.steps,
        "step_energy_kcal": activity.step_energy_kcal,
        "total_energy_kcal": activity.total_energy_kcal,
        "activity_duration_min": activity.active_minutes,
        "standing_count": activity.standing_count,
        "distance_m": None,  # Xiaomi source unit is not verified.
        "daily_rhr_bpm": rhr,
        "daily_hr_measured_minutes": len(hr_minutes),
        "daily_hr_max_gap_min": max_gap,
        "spo2_samples": len(spo2),
        "spo2_measured_minutes": len({int(p.measurement_start.timestamp()) // 60 for p in spo2}),
        "respiratory_nights": None,  # Joined by sleep_date from nightly_features, not guessed from daily_summary.
        "vendor_stress_median": statistics.median(stress_values) if stress_values else None,
        "vendor_stress_p10": _percentile(stress_values, .1) if stress_values else None,
        "vendor_stress_p90": _percentile(stress_values, .9) if stress_values else None,
        "vendor_stress_n": len(stress_values),
        "training_load_trimp": None,
    }
    ids = tuple(s.provenance.source_record_id for s in [activity, *hrs, *spo2, *stress])
    digest = input_fingerprint(normalized_inputs={"policy": source_policy_version, "activity": activity,
                                                  "hr": hrs, "spo2": spo2, "stress": stress,
                                                  "rhr": rhr, "values": values},
                               profile_revision=profile_revision, normalization_version=normalization_version,
                               algorithm_id="feature.daily", algorithm_version="1",
                               input_contract_version=FEATURE_CONTRACT_VERSION,
                               implementation_version=IMPLEMENTATION_VERSION)
    return Feature(kind="daily", metric_date=day, measurement_start=None, measurement_end=None,
                   values=values, source_ids=ids, quality_status=QualityStatus.PARTIAL if flags else QualityStatus.OK,
                   quality_flags=frozenset(flags), input_fingerprint=digest,
                   freshness_status=Freshness.HISTORICAL)
