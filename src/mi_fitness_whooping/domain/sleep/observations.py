"""Selected-night observations for the existing sleep stage metrics and regularity.

Separate from the locked Sleep Core V1 contracts. Values are retained
unvalidated so the calculation reproduces the existing gates; None means
missing, not measured zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mi_fitness_whooping.domain.metrics import FeatureLineage


@dataclass(frozen=True, slots=True)
class SleepStagesNight:
    lineage: FeatureLineage
    time_in_bed_min: object = None
    tst_min: object = None
    awake_min: object = None
    light_min: object = None
    deep_min: object = None
    rem_min: object = None
    stage_coverage: object = None
    bedtime_local_min: object = None
    wake_local_min: object = None

    def __post_init__(self) -> None:
        if self.lineage.kind != "nightly":
            raise ValueError("sleep stages require nightly lineage")

    @property
    def day(self) -> date:
        return self.lineage.day
