"""Map a selected nightly feature to sleep stage-metric observations."""

from __future__ import annotations

from mi_fitness_whooping.domain.sleep.observations import SleepStagesNight
from mi_fitness_whooping.integration.metric_results import SelectedFeature, lineage


_FIELDS = tuple(name for name in SleepStagesNight.__dataclass_fields__ if name != "lineage")


def stages_night(feature: SelectedFeature) -> SleepStagesNight:
    return SleepStagesNight(lineage(feature), **{name: feature.values.get(name) for name in _FIELDS})
