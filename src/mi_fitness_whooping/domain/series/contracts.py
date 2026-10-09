"""Dated series observations for shared baseline, deviation and trend statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from mi_fitness_whooping.domain.metrics import FeatureLineage


@dataclass(frozen=True, slots=True)
class SeriesObservation:
    """One selected feature's raw, unvalidated value for one series."""

    lineage: FeatureLineage
    value: object

    @property
    def day(self) -> date:
        return self.lineage.day


# Series key -> date -> observation. Keys: rhr, sleep_tst, spo2, respiratory,
# steps, stress_vendor. A date without a selected feature is absent.
SeriesHistory = Mapping[str, Mapping[date, SeriesObservation]]
