"""Non-diagnostic personal health bands, RHR CUSUM and corroborated watch."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from analytics.algorithms.foundations import FeatureRecord, MetricDraft


MONITORING_ALGORITHM_VERSION = "monitoring-2"
PULSE_COMMIT = "1f8975cfc8298b67482a7e37dba576b9ea8b62db"
OPENSTRAP_COMMIT = "0441ef9e6fc6d5681c309ce6341911285e829f20"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"
SIGNALS = ("rhr", "spo2", "respiratory")


@dataclass(frozen=True)
class HealthBandInput:
    signal: str
    day: date
    value: float | None
    baseline_mean: float | None
    baseline_sd: float | None
    lower: float | None
    upper: float | None
    history_count: int
    last_prior_date: date | None


@dataclass(frozen=True)
class HealthBandResult:
    state: str
    concerning: bool | None
    direction: str | None
    reason: str


@dataclass(frozen=True)
class CusumInput:
    day: date
    value: float | None
    prior_28d: tuple[tuple[date, float], ...]


@dataclass(frozen=True)
class IllnessWatchInput:
    day: date
    current: dict[str, float | None]
    baselines: dict[str, tuple[float, float] | None]


def _valid(value, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and lo <= value <= hi else None


def evaluate_band(inp: HealthBandInput) -> HealthBandResult:
    if inp.value is None:
        return HealthBandResult("NO_DATA", None, None, "missing_current_measurement")
    if inp.last_prior_date is not None and (inp.day - inp.last_prior_date).days > 14:
        return HealthBandResult("STALE", None, None, "baseline_last_observation_too_old")
    if inp.baseline_mean is None or inp.history_count < 5 or inp.last_prior_date is None:
        return HealthBandResult("CALIBRATING", None, None, "insufficient_prior_baseline")
    if inp.lower is None and inp.upper is None:
        return HealthBandResult("CALIBRATING", None, None, "missing_baseline_bounds")
    if inp.lower is not None and inp.value < inp.lower:
        return HealthBandResult("BELOW", inp.signal == "spo2", "LOW", "below_personal_band")
    if inp.upper is not None and inp.value > inp.upper:
        return HealthBandResult("ABOVE", inp.signal in {"rhr", "respiratory"}, "HIGH", "above_personal_band")
    return HealthBandResult("IN_RANGE", False, None, "within_personal_band")


def _draft(name: str, day: date, value: float | None, status: str, algorithm_id: str,
           inputs: tuple[FeatureRecord, ...], metadata: dict, *, upstream: str,
           commit: str, confidence: str = "MEDIUM") -> MetricDraft:
    return MetricDraft(name, day, value, "event_flag", status, algorithm_id,
                       MONITORING_ALGORITHM_VERSION, "OUR_DERIVED", upstream,
                       commit, inputs, metadata, confidence)


def _current(night: FeatureRecord, signal: str) -> float | None:
    fields = {"rhr": ("rhr_bpm", 25, 240),
              "spo2": ("spo2_mean_pct", .001, 100),
              "respiratory": ("respiratory_rate_bpm", 4, 60)}
    field, lo, hi = fields[signal]
    return _valid(night.values.get(field), lo, hi)


def _band_input(day: date, night: FeatureRecord, signal: str,
                baseline: MetricDraft | None) -> HealthBandInput:
    m = baseline.metadata if baseline else {}
    return HealthBandInput(signal, day, _current(night, signal),
                           baseline.value if baseline and baseline.status in {"VALID", "REDUCED"} else None,
                           m.get("sd"), m.get("lower"), m.get("upper"),
                           m.get("history_count", 0),
                           date.fromisoformat(m["last_prior_date"]) if m.get("last_prior_date") else None)


def _vitals_watch(inp: IllnessWatchInput) -> tuple[list[str], dict]:
    """Vitals' RHR/resp z-or-absolute and SpO2<92 branches, local 2-signal gate."""
    drivers: list[str] = []
    explanations: dict = {}
    for signal in ("rhr", "respiratory"):
        value, baseline = inp.current.get(signal), inp.baselines.get(signal)
        if value is None or baseline is None:
            continue
        mean, sd = baseline
        min_sd = .01 if signal == "rhr" else .1
        z = (value - mean) / sd if sd >= min_sd else None
        threshold = 1.5 if z is not None else (5 if signal == "rhr" else 1.5)
        fired = z > 1.5 if z is not None else value > mean + threshold
        explanations[signal] = {"value": value, "baseline": mean, "sd": sd,
                                "z": z, "threshold": threshold,
                                "method": "z" if z is not None else "absolute_delta",
                                "triggered": fired}
        if fired:
            drivers.append(signal)
    spo2, spo2_base = inp.current.get("spo2"), inp.baselines.get("spo2")
    if spo2 is not None and spo2_base is not None:
        fired = spo2 < 92
        explanations["spo2"] = {"value": spo2, "baseline": spo2_base[0],
                                "threshold": 92, "method": "qualified_night_mean",
                                "triggered": fired}
        if fired:
            drivers.append("spo2")
    return drivers, explanations


def calculate_monitoring_day(day: date, nights: dict[date, FeatureRecord],
                             foundation_drafts: list[MetricDraft]) -> list[MetricDraft]:
    night = nights.get(day)
    if night is None:
        return []
    by_name = {m.name: m for m in foundation_drafts}
    results: list[MetricDraft] = []
    band_inputs: dict[str, HealthBandInput] = {}
    watch_current: dict[str, float | None] = {}
    watch_baselines: dict[str, tuple[float, float] | None] = {}
    watch_inputs: list[FeatureRecord] = [night]
    for signal in SIGNALS:
        baseline = by_name.get(f"baseline.{signal}.band_mean")
        inp = _band_input(day, night, signal, baseline)
        band_inputs[signal] = inp
        outcome = evaluate_band(inp)
        if baseline:
            watch_inputs.extend(baseline.inputs)
        value = float(outcome.concerning) if outcome.concerning is not None else None
        status = ("REDUCED" if signal == "respiratory" else "VALID") if value is not None else (
            "INSUFFICIENT_DATA" if outcome.state == "NO_DATA" else "CALIBRATING")
        metadata = {"signal": signal, "current_value": inp.value,
                    "baseline_mean": inp.baseline_mean, "baseline_sd": inp.baseline_sd,
                    "lower": inp.lower, "upper": inp.upper,
                    "direction": outcome.direction, "state": outcome.state,
                    "reason": outcome.reason, "concerning": outcome.concerning,
                    "history_count": inp.history_count,
                    "required_history_count": 5,
                    "last_prior_date": inp.last_prior_date.isoformat() if inp.last_prior_date else None,
                    "reference_baseline": f"baseline.{signal}.band_mean",
                    "reference_deviation": f"{signal}.deviation",
                    "source_quality": "vendor_aggregate" if signal == "respiratory" else "measured_or_vendor_daily"}
        results.append(_draft(f"anomaly.{signal}", day, value, status,
                              f"anomaly.pulse_{signal}_band_v1",
                              tuple({f.fingerprint: f for f in (night, *(baseline.inputs if baseline else ()))}.values()),
                              metadata, upstream="Pulse", commit=PULSE_COMMIT,
                              confidence="LOW" if signal == "respiratory" else "MEDIUM"))
        ready = outcome.concerning is not None
        watch_current[signal] = inp.value if ready else None
        watch_baselines[signal] = (inp.baseline_mean, inp.baseline_sd) if ready and inp.baseline_mean is not None and inp.baseline_sd is not None else None
    ready_count = sum(v is not None for v in watch_baselines.values())
    drivers, evidence = _vitals_watch(IllnessWatchInput(day, watch_current, watch_baselines))
    watch_ready = ready_count >= 2
    watch_value = float(len(drivers) >= 2) if watch_ready else None
    measured_count = sum(_current(night, signal) is not None for signal in SIGNALS)
    watch_status = ("REDUCED" if watch_ready else
                    "INSUFFICIENT_DATA" if measured_count < 2 else "CALIBRATING")
    watch_metadata = {"category": "possible_physiological_deviation", "mode": "REDUCED" if watch_ready else None,
                      "drivers": drivers if watch_ready else [], "evidence": evidence,
                      "ready_signal_count": ready_count, "required_signal_count": 2,
                      "missing_components": [k for k in SIGNALS if watch_baselines[k] is None],
                      "unavailable_components": ["hrv", "skin_temperature"],
                      "threshold_policy": "Vitals_v3_signal_rules_plus_local_two_independent_signals",
                      "diagnosis": False}
    results.append(_draft("health_signal.physiological_watch", day, watch_value,
                          watch_status, "health_signal.vitals_two_signal_watch_v1",
                          tuple({f.fingerprint: f for f in watch_inputs}.values()), watch_metadata,
                          upstream="Vitals", commit=VITALS_COMMIT, confidence="LOW"))
    return results


def calculate_cusum_series(nights: dict[date, FeatureRecord]) -> dict[date, MetricDraft]:
    """OpenStrap one-sided RHR CUSUM, evaluated chronologically on main nights."""
    out: dict[date, MetricDraft] = {}
    accumulator = 0.0
    yellow_run = normal_run = 0
    last_scored: date | None = None
    for day in sorted(nights):
        night = nights[day]
        current = _current(night, "rhr")
        prior = [(d, nights[d], _current(nights[d], "rhr")) for d in sorted(nights)
                 if day - timedelta(days=28) <= d < day]
        prior = [(d, f, v) for d, f, v in prior if v is not None]
        inp = CusumInput(day, current, tuple((d, v) for d, _, v in prior))
        values = [v for _, v in inp.prior_28d]
        contiguous = 0
        for offset in range(1, 8):
            prior_night = nights.get(day - timedelta(days=offset))
            if prior_night is None or _current(prior_night, "rhr") is None:
                break
            contiguous += 1
        state, reason, z, evaluated = "GREEN", None, None, False
        median = mad = sample_sd = None
        if inp.value is None:
            reason = "missing_current_rhr"
        elif len(values) < 7:
            reason = "need_baseline"
        elif contiguous < 7:
            reason = "need_contiguous_baseline"
        elif (day - prior[-1][0]).days > 14:
            reason = "stale_baseline"
        else:
            median = statistics.median(values)
            mad = statistics.median(abs(v - median) for v in values) * 1.4826
            sample_sd = statistics.stdev(values)
            scale = mad if mad > 0 else sample_sd
            if scale <= 0:
                reason = "degenerate_baseline:scale=0"
            elif sample_sd < 1.0:
                reason = "baseline_dispersion_below_quantum"
            else:
                if last_scored is None or (day - last_scored).days > 1:
                    accumulator = 0.0
                    yellow_run = normal_run = 0
                last_scored = day
                z = (inp.value - median) / scale
                accumulator = max(0.0, accumulator + z - .5)
                if z < .5:
                    normal_run += 1
                    if normal_run >= 2:
                        accumulator = 0.0
                else:
                    normal_run = 0
                if accumulator > 4.0:
                    yellow_run += 1
                    state = "RED" if yellow_run >= 2 else "YELLOW"
                else:
                    yellow_run = 0
                evaluated = True
        value = float(state in {"YELLOW", "RED"}) if evaluated else None
        status = "VALID" if evaluated else ("INSUFFICIENT_DATA" if current is None else "CALIBRATING")
        token = {"accumulator": round(accumulator, 12), "yellow_run": yellow_run,
                 "normal_run": normal_run,
                 "last_scored_date": last_scored.isoformat() if last_scored else None}
        metadata = {"state": state if evaluated else "UNEVALUATED", "reason": reason,
                    "cusum": accumulator if evaluated else None, "z": z,
                    "k": .5, "h": 4.0, "return_z": .5,
                    "recover_days": 2, "persist_days": 2,
                    "baseline_window_calendar_days": 28,
                    "baseline_median": median if len(values) >= 7 else None,
                    "baseline_mad_scaled": mad if len(values) >= 7 else None,
                    "baseline_sample_sd": sample_sd if len(values) >= 7 else None,
                    "history_count": len(values), "required_history_count": 7,
                    "contiguous_prior_nights": contiguous,
                    "last_prior_date": prior[-1][0].isoformat() if prior else None,
                    "state_token": token,
                    "non_diagnostic": True}
        inputs = tuple({f.fingerprint: f for f in (night, *(f for _, f, _ in prior))}.values())
        out[day] = _draft("anomaly.rhr_cusum", day, value, status,
                          "anomaly.openstrap_rhr_cusum_v1", inputs, metadata,
                          upstream="OpenStrap", commit=OPENSTRAP_COMMIT,
                          confidence="LOW")
    return out
