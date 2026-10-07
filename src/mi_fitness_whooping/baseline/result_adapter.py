"""Map existing baseline calculations to the schema-v3 target writer."""

from __future__ import annotations

from mi_fitness_whooping.baseline.foundations import MetricDraft
from mi_fitness_whooping.storage.contracts import PersistableMetricResult, StoredFeatureRef


def persistable(draft: MetricDraft) -> PersistableMetricResult:
    return PersistableMetricResult(
        metric_name=draft.name, day=draft.day, value=draft.value, unit=draft.unit,
        status=draft.status, algorithm_id=draft.algorithm_id,
        algorithm_version=draft.algorithm_version, metadata=draft.metadata,
        inputs=tuple(StoredFeatureRef(
            kind=feature.kind, day=feature.day, fingerprint=feature.fingerprint,
            source_count=feature.source_count, source_ids_hash=feature.source_ids_hash,
            measurement_start=feature.measurement_start,
            measurement_end=feature.measurement_end, quality_flags=feature.quality_flags,
        ) for feature in draft.inputs), source_type=draft.source_type,
        upstream_project=draft.upstream_project,
        upstream_commit=draft.upstream_commit, confidence=draft.confidence,
    )
