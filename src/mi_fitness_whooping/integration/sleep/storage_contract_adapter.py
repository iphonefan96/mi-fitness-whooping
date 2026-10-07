"""Project canonical Sleep results into future target storage inputs.

This has no database writes and does not replace LegacySleepStore. The current
Legacy draft represents the same fields through original FeatureRecord inputs.
"""

from __future__ import annotations

from dataclasses import asdict

from mi_fitness_whooping.domain.sleep.contracts import SleepMetricResult
from mi_fitness_whooping.storage.contracts import PersistableMetricResult, StoredFeatureRef


def to_persistable_sleep_result(result: SleepMetricResult) -> PersistableMetricResult:
    """Retain all result and ordered lineage fields used by Legacy persistence."""
    return PersistableMetricResult(
        metric_name=result.metric.value,
        day=result.day,
        value=result.value,
        unit=result.unit,
        status=result.status.value,
        algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version,
        metadata=asdict(result.metadata),
        inputs=tuple(StoredFeatureRef(
            kind="nightly", day=ref.day, fingerprint=ref.fingerprint,
            source_count=ref.source_count, source_ids_hash=ref.source_ids_hash,
            measurement_start=ref.measurement_start,
            measurement_end=ref.measurement_end, quality_flags=ref.quality_flags,
        ) for ref in result.lineage),
        source_type=result.source_type,
        upstream_project=result.upstream_project,
        upstream_commit=result.upstream_commit,
        confidence=result.confidence,
    )
