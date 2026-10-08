"""Map selected nightly/daily features to dated series observations.

The feature-field mapping is the existing foundation SERIES contract.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from mi_fitness_whooping.domain.series.contracts import SeriesObservation
from mi_fitness_whooping.integration.metric_results import SelectedFeature, lineage


SERIES_FIELDS = {
    "rhr": ("daily", "daily_rhr_bpm"),
    "sleep_tst": ("nightly", "tst_min"),
    "spo2": ("nightly", "spo2_mean_pct"),
    "respiratory": ("nightly", "respiratory_rate_bpm"),
    "steps": ("daily", "steps"),
    "stress_vendor": ("daily", "vendor_stress_median"),
}


def series_history(nights: Mapping[date, SelectedFeature],
                   dailies: Mapping[date, SelectedFeature]
                   ) -> dict[str, dict[date, SeriesObservation]]:
    """Build every series once per run from the selected features."""
    history: dict[str, dict[date, SeriesObservation]] = {}
    for key, (kind, field) in SERIES_FIELDS.items():
        features = nights if kind == "nightly" else dailies
        history[key] = {day: SeriesObservation(lineage(feature), feature.values.get(field))
                        for day, feature in features.items()}
    return history
