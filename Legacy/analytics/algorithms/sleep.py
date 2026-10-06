"""Step-7 sleep metrics on device-independent, dated feature contracts."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from analytics.algorithms.foundations import FeatureRecord, MetricDraft
from analytics.profile.config import effective_values


SLEEP_ALGORITHM_VERSION = "sleep-1"
OPEN_WEARABLES_COMMIT = "fd78bdd3b8ed162e6716ba9c5fa2613dac005a40"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"


@dataclass(frozen=True)
class SleepScoreInput:
    day: date
    tst_min: float | None
    deep_min: float | None
    rem_min: float | None
    bedtime_local_min: float | None
    prior_bedtimes_local_min: tuple[float, ...]
    waso_min: float | None
    awakening_durations_min: tuple[float, ...] | None
    stage_coverage: str


@dataclass(frozen=True)
class SleepNeedInput:
    day: date
    target_min: float
    default_target: bool


@dataclass(frozen=True)
class SleepDebtInput:
    day: date
    dated_tst_target: tuple[tuple[date, float | None, float], ...]
    default_target: bool


def _valid(value, lo=0, hi=1440) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and lo <= value <= hi else None


def _sigmoid(x: float, k: float, midpoint: float, anchor: float) -> float:
    return 100 * (1 + math.exp(min(709, k * (anchor - midpoint)))) / (1 + math.exp(min(709, k * (x - midpoint))))


def _clock_past_noon(minutes: float) -> float:
    hours = minutes / 60
    return hours + 12 if hours < 12 else hours - 12


def score_components(inp: SleepScoreInput) -> dict[str, int] | None:
    """Port Open Wearables' four components; local missing/history gates precede it."""
    tst, deep, rem = (_valid(inp.tst_min), _valid(inp.deep_min), _valid(inp.rem_min))
    waso = _valid(inp.waso_min)
    bedtime = _valid(inp.bedtime_local_min, 0, 1439.999999)
    awakenings = inp.awakening_durations_min
    if (inp.stage_coverage != "COMPLETE" or tst is None or tst <= 0 or deep is None or rem is None
            or waso is None or bedtime is None or awakenings is None
            or any(_valid(d) is None for d in awakenings) or deep + rem > tst + 1
            or len(inp.prior_bedtimes_local_min) < 5):
        return None
    hours = tst / 60
    if 7 <= hours <= 9:
        duration = 100
    elif hours < 7:
        duration = max(0, min(100, int(_sigmoid(hours, -1.5, 5, 7))))
    else:
        duration = max(50, min(100, int(_sigmoid(hours, .8, 11, 9))))
    stages = int((min(100, int(deep / 90 * 100)) + min(100, int(rem / 90 * 100))) * .5)
    prior = [_clock_past_noon(v) for v in inp.prior_bedtimes_local_min]
    diff = (_clock_past_noon(bedtime) - statistics.median(prior)) * 60
    if diff > 15:
        penalty = (diff - 15) / 105 * 100
    elif diff < -15:
        penalty = min(20, (abs(diff) - 15) / 105 * 100)
    else:
        penalty = 0
    consistency = max(0, int(100 - penalty))
    duration_points = 80 if waso <= 20 else max(0, 80 - (waso - 20) / 70 * 80)
    count = sum(d > 5 for d in awakenings)
    freq_points = 20 * (1, 1, .75, .5, 0)[min(count, 4)]
    interruptions = max(0, min(100, int(duration_points + freq_points)))
    return {"duration": duration, "stages": stages, "consistency": consistency,
            "interruptions": interruptions}


def _draft(name: str, day: date, value: float | None, status: str, algorithm_id: str,
           inputs: tuple[FeatureRecord, ...], metadata: dict, *, unit: str,
           upstream_project: str | None = None, upstream_commit: str | None = None) -> MetricDraft:
    return MetricDraft(name, day, value, unit, status, algorithm_id, SLEEP_ALGORITHM_VERSION,
                       "OUR_DERIVED", upstream_project, upstream_commit, inputs, metadata)


def _target(profile: dict, day: date) -> tuple[float, bool]:
    raw = effective_values(profile, day).get("sleep_target_min")
    if raw is None:
        return 480.0, True
    target = _valid(raw, 300, 720)
    if target is None:
        raise ValueError("sleep_target_min must be within 300..720")
    return target, False


def calculate_sleep_day(day: date, nights: dict[date, FeatureRecord], profile: dict) -> list[MetricDraft]:
    night = nights.get(day)
    if night is None:
        return []
    v = night.values
    target, default = _target(profile, day)
    prior = tuple(nights[d] for d in (day - timedelta(days=i) for i in range(14, 0, -1))
                  if d in nights and _valid(nights[d].values.get("bedtime_local_min"), 0, 1439.999999) is not None)
    score_input = SleepScoreInput(day, v.get("tst_min"), v.get("deep_min"), v.get("rem_min"),
                                  v.get("bedtime_local_min"),
                                  tuple(n.values["bedtime_local_min"] for n in prior),
                                  v.get("waso_min"),
                                  tuple(v["awakening_durations_min"]) if v.get("awakening_durations_min") is not None else None,
                                  v.get("stage_coverage", "UNKNOWN"))
    components = score_components(score_input)
    if components is not None:
        score = int(.4 * components["duration"] + .2 * components["stages"] +
                    .2 * components["consistency"] + .2 * components["interruptions"])
        score_status = "VALID"
    else:
        score = None
        missing = (v.get("stage_coverage") != "COMPLETE" or any(v.get(k) is None for k in
                   ("tst_min", "deep_min", "rem_min", "waso_min", "awakening_durations_min")))
        score_status = "INSUFFICIENT_DATA" if missing else "CALIBRATING" if len(prior) < 5 else "INVALID"
    score_draft = _draft("sleep.score", day, score, score_status, "sleep.open_wearables_four_pillar_v1",
                         (night, *prior), {"mode": "FULL" if score is not None else None,
                                           "components": components, "history_count": len(prior),
                                           "required_history_count": 5, "history_window_calendar_nights": 14},
                         unit="score", upstream_project="Open Wearables", upstream_commit=OPEN_WEARABLES_COMMIT)
    need_input = SleepNeedInput(day, target, default)
    need_draft = _draft("sleep.need_min", day, need_input.target_min,
                        "REDUCED" if default else "VALID", "sleep.fixed_target_v1", (night,),
                        {"mode": "PROVISIONAL_DEFAULT" if default else "USER_TARGET",
                         "default_target": default, "physiological_estimate": False}, unit="min",
                        upstream_project="Vitals", upstream_commit=VITALS_COMMIT)
    ledger: list[tuple[date, float | None, float]] = []
    input_features: list[FeatureRecord] = []
    for offset in range(13, -1, -1):
        d = day - timedelta(days=offset)
        row = nights.get(d)
        t, is_default = _target(profile, d)
        default |= is_default
        tst = _valid(row.values.get("tst_min")) if row and row.values.get("stage_coverage") == "COMPLETE" else None
        if tst is not None and tst > 0 and row is not None:
            input_features.append(row)
        else:
            tst = None
        ledger.append((d, tst, t))
    debt_input = SleepDebtInput(day, tuple(ledger), default)
    valid = [(d, tst, t) for d, tst, t in debt_input.dated_tst_target if tst is not None]
    longest_gap = max((len(part) for part in "".join("1" if tst is None else "0" for _, tst, _ in ledger).split("0")), default=0)
    ready = len(valid) >= 10 and longest_gap <= 2
    balance = sum(tst - t for _, tst, t in valid) if ready else None
    debt = max(0, -balance) if balance is not None else None
    debt_draft = _draft("sleep.debt_min", day, debt, "REDUCED" if ready and default else
                        "VALID" if ready else "CALIBRATING", "sleep.signed_14_calendar_night_ledger_v1",
                        tuple(input_features), {"mode": "PROVISIONAL_DEFAULT" if default else "USER_TARGET",
                                                "default_target": default, "signed_balance_min": balance,
                                                "history_count": len(valid), "required_history_count": 10,
                                                "longest_missing_gap": longest_gap,
                                                "window_calendar_nights": 14}, unit="min")
    return [score_draft, need_draft, debt_draft]
