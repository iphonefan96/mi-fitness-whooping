"""Map selected feature records to canonical lineage and project results to storage.

No database access; the caller owns selection and persistence.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Protocol

from mi_fitness_whooping.domain.metrics import FeatureLineage, MetricResult
from mi_fitness_whooping.storage.contracts import PersistableMetricResult, StoredFeatureRef


class SelectedFeature(Protocol):
    kind: str
    day: date
    values: Mapping[str, Any]
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None
    measurement_end: str | None
    quality_flags: tuple[str, ...]


def lineage(feature: SelectedFeature) -> FeatureLineage:
    return FeatureLineage(feature.kind, feature.day, feature.fingerprint, feature.source_count,
                          feature.source_ids_hash, feature.measurement_start,
                          feature.measurement_end, tuple(feature.quality_flags))


def to_persistable(result: MetricResult) -> PersistableMetricResult:
    return PersistableMetricResult(
        metric_name=result.name, day=result.day, value=result.value, unit=result.unit,
        status=result.status, algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version, metadata=result.metadata,
        inputs=tuple(StoredFeatureRef(
            kind=ref.kind, day=ref.day, fingerprint=ref.fingerprint,
            source_count=ref.source_count, source_ids_hash=ref.source_ids_hash,
            measurement_start=ref.measurement_start, measurement_end=ref.measurement_end,
            quality_flags=ref.quality_flags,
        ) for ref in result.lineage),
        source_type=result.source_type, upstream_project=result.upstream_project,
        upstream_commit=result.upstream_commit, confidence=result.confidence,
    )
