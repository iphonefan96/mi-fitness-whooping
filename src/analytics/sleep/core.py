"""Behavior-preserving Sleep Core V1 calculations over resolved dated inputs.

The immutable Legacy sleep algorithm is the behavioral reference. Profile
resolution, storage identity, freshness and presentation remain outside here.
"""

from __future__ import annotations

import math
import statistics
from datetime import timedelta

from domain.sleep.contracts import (
    CalculationStatus,
    DebtMetadata,
    NeedMetadata,
    ScoreComponents,
    ScoreMetadata,
    SelectedNight,
    SleepCoreInput,
    SleepMetric,
    SleepMetricResult,
)


ALGORITHM_VERSION = "sleep-1"
OPEN_WEARABLES_COMMIT = "fd78bdd3b8ed162e6716ba9c5fa2613dac005a40"
VITALS_COMMIT = "fb3a837a017567b0fbc3c0c2b5666f8db4acad21"


def _valid(value: object, lo: float = 0, hi: float = 1440) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and lo <= number <= hi else None


def _sigmoid(x: float, k: float, midpoint: float, anchor: float) -> float:
    return 100 * (1 + math.exp(min(709, k * (anchor - midpoint)))) / (1 + math.exp(min(709, k * (x - midpoint))))


def _clock_past_noon(minutes: float) -> float:
    hours = minutes / 60
    return hours + 12 if hours < 12 else hours - 12


def _score_components(current: SelectedNight, prior_bedtimes: tuple[float, ...]) -> ScoreComponents | None:
    tst, deep, rem = (_valid(current.tst_min), _valid(current.deep_min), _valid(current.rem_min))
    waso = _valid(current.waso_min)
    bedtime = _valid(current.bedtime_local_min, 0, 1439.999999)
    awakenings = current.awakening_durations_min
    if (not current.stage_complete or tst is None or tst <= 0 or deep is None or rem is None
            or waso is None or bedtime is None or awakenings is None
            or any(_valid(d) is None for d in awakenings) or deep + rem > tst + 1
            or len(prior_bedtimes) < 5):
        return None
    hours = tst / 60
    if 7 <= hours <= 9:
        duration = 100
    elif hours < 7:
        duration = max(0, min(100, int(_sigmoid(hours, -1.5, 5, 7))))
    else:
        duration = max(50, min(100, int(_sigmoid(hours, .8, 11, 9))))
    stages = int((min(100, int(deep / 90 * 100)) + min(100, int(rem / 90 * 100))) * .5)
    prior = [_clock_past_noon(v) for v in prior_bedtimes]
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
    return ScoreComponents(duration, stages, consistency, interruptions)


def calculate_sleep_core(inp: SleepCoreInput) -> tuple[SleepMetricResult, ...]:
    """Calculate the three Legacy-compatible metrics, or none without a current night."""
    nights = {night.day: night for night in inp.selected_nights}
    current = nights.get(inp.target_date)
    if current is None:
        return ()
    targets = {target.day: target for target in inp.targets}
    target = targets[inp.target_date]

    prior = tuple(nights[d] for d in (inp.target_date - timedelta(days=i) for i in range(14, 0, -1))
                  if d in nights and _valid(nights[d].bedtime_local_min, 0, 1439.999999) is not None)
    components = _score_components(current, tuple(n.bedtime_local_min for n in prior))
    if components is not None:
        score = int(.4 * components.duration + .2 * components.stages +
                    .2 * components.consistency + .2 * components.interruptions)
        score_status = CalculationStatus.VALID
    else:
        score = None
        missing = (not current.stage_complete or any(value is None for value in
                   (current.tst_min, current.deep_min, current.rem_min, current.waso_min,
                    current.awakening_durations_min)))
        score_status = (CalculationStatus.INSUFFICIENT_DATA if missing else
                        CalculationStatus.CALIBRATING if len(prior) < 5 else
                        CalculationStatus.INVALID)
    score_result = SleepMetricResult(
        SleepMetric.SCORE, inp.target_date, score, "score", score_status,
        "sleep.open_wearables_four_pillar_v1", ALGORITHM_VERSION,
        ScoreMetadata("FULL" if score is not None else None, components, len(prior), 5, 14),
        (current.lineage, *(n.lineage for n in prior)), "Open Wearables", OPEN_WEARABLES_COMMIT,
    )

    need_result = SleepMetricResult(
        SleepMetric.NEED_MIN, inp.target_date, target.minutes, "min",
        CalculationStatus.REDUCED if target.is_default else CalculationStatus.VALID,
        "sleep.fixed_target_v1", ALGORITHM_VERSION,
        NeedMetadata("PROVISIONAL_DEFAULT" if target.is_default else "USER_TARGET",
                     target.is_default, False),
        (current.lineage,), "Vitals", VITALS_COMMIT,
    )

    ledger = []
    debt_lineage = []
    default = target.is_default
    for offset in range(13, -1, -1):
        day = inp.target_date - timedelta(days=offset)
        row = nights.get(day)
        effective = targets[day]
        default |= effective.is_default
        tst = _valid(row.tst_min) if row and row.stage_complete else None
        if tst is not None and tst > 0 and row is not None:
            debt_lineage.append(row.lineage)
        else:
            tst = None
        ledger.append((day, tst, effective.minutes))
    valid = [(day, tst, t) for day, tst, t in ledger if tst is not None]
    longest_gap = max((len(part) for part in "".join("1" if tst is None else "0" for _, tst, _ in ledger).split("0")), default=0)
    ready = len(valid) >= 10 and longest_gap <= 2
    balance = sum(tst - t for _, tst, t in valid) if ready else None
    debt = max(0, -balance) if balance is not None else None
    debt_result = SleepMetricResult(
        SleepMetric.DEBT_MIN, inp.target_date, debt, "min",
        CalculationStatus.REDUCED if ready and default else
        CalculationStatus.VALID if ready else CalculationStatus.CALIBRATING,
        "sleep.signed_14_calendar_night_ledger_v1", ALGORITHM_VERSION,
        DebtMetadata("PROVISIONAL_DEFAULT" if default else "USER_TARGET", default,
                     balance, len(valid), 10, longest_gap, 14), tuple(debt_lineage),
    )
    return score_result, need_result, debt_result
