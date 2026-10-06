"""Project active nightly features and loaded profile into Sleep Core input.

This is a compatibility boundary, not a source reader or sleep calculator.
It intentionally imports neither Legacy nor target analytics implementations.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Mapping, Protocol

from domain.sleep.contracts import (
    EffectiveSleepTarget,
    NightReference,
    SelectedNight,
    SleepCoreInput,
)


class NightlyFeature(Protocol):
    """Fields supplied by the existing active nightly feature map."""

    day: date
    values: Mapping[str, object]
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None
    measurement_end: str | None
    quality_flags: tuple[str, ...]


def _target(profile: Mapping[str, object], day: date) -> tuple[float, bool]:
    # Preserve effective_values()' interval evaluation and last-match behavior.
    effective = {
        entry["field"]: entry["value"]
        for entry in profile["values"]
        if date.fromisoformat(entry["effective_from"]) <= day
        and (not entry.get("effective_to") or day <= date.fromisoformat(entry["effective_to"]))
    }
    raw = effective.get("sleep_target_min")
    if raw is None:
        return 480.0, True
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("sleep_target_min must be within 300..720")
    target = float(raw)
    if not math.isfinite(target) or not 300 <= target <= 720:
        raise ValueError("sleep_target_min must be within 300..720")
    return target, False


def _selected(row: NightlyFeature) -> SelectedNight:
    values = row.values
    awakenings = values.get("awakening_durations_min")
    return SelectedNight(
        day=row.day,
        lineage=NightReference(
            day=row.day,
            fingerprint=row.fingerprint,
            source_count=row.source_count,
            source_ids_hash=row.source_ids_hash,
            measurement_start=row.measurement_start,
            measurement_end=row.measurement_end,
            quality_flags=row.quality_flags,
        ),
        tst_min=values.get("tst_min"),
        deep_min=values.get("deep_min"),
        rem_min=values.get("rem_min"),
        waso_min=values.get("waso_min"),
        awakening_durations_min=tuple(awakenings) if awakenings is not None else None,
        bedtime_local_min=values.get("bedtime_local_min"),
        stage_complete=values.get("stage_coverage") == "COMPLETE",
    )


def adapt_sleep_input(
    day: date,
    nights: Mapping[date, NightlyFeature],
    profile: Mapping[str, object],
    profile_revision: str,
) -> SleepCoreInput:
    """Convert already selected nightly features; never read source or storage.

    The no-current-night return precedes any profile or history inspection, as
    in the Legacy sleep calculation. The caller retains original feature
    objects for the separate Phase 4B output compatibility boundary.
    """
    if day not in nights:
        return SleepCoreInput(day, (), (), profile_revision)

    # Legacy rejects an invalid current target before reading sleep history.
    current_target = _target(profile, day)
    earliest = day - timedelta(days=14)
    selected = tuple(_selected(nights[d]) for d in sorted(nights)
                     if earliest <= d <= day)

    # Legacy walks the 14-date ledger after resolving today's target.
    targets = tuple(
        EffectiveSleepTarget(d, *(current_target if d == day else _target(profile, d)))
        for d in (day - timedelta(days=offset) for offset in range(13, -1, -1))
    )
    return SleepCoreInput(day, selected, targets, profile_revision)
