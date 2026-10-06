"""Map canonical Sleep Core results to the current persistence-facing draft.

Importing Legacy's MetricDraft is an intentional, isolated compatibility
dependency. This module does not calculate, fingerprint, persist or select.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Mapping

from analytics.algorithms.foundations import FeatureRecord, MetricDraft
from domain.sleep.contracts import NightReference, SleepMetricResult


def _original_feature(
    reference: NightReference,
    nights: Mapping[date, FeatureRecord],
) -> FeatureRecord:
    original = nights.get(reference.day)
    if original is None or (
        original.kind != "nightly"
        or original.day != reference.day
        or original.fingerprint != reference.fingerprint
        or original.source_count != reference.source_count
        or original.source_ids_hash != reference.source_ids_hash
        or original.measurement_start != reference.measurement_start
        or original.measurement_end != reference.measurement_end
        or original.quality_flags != reference.quality_flags
    ):
        raise ValueError("Sleep Core lineage does not match an original active night")
    return original


def adapt_sleep_result(
    result: SleepMetricResult,
    nights: Mapping[date, FeatureRecord],
) -> MetricDraft:
    """Preserve original feature objects and Legacy's exact draft field shape."""
    inputs = tuple(_original_feature(ref, nights) for ref in result.lineage)
    return MetricDraft(
        name=result.metric.value,
        day=result.day,
        value=result.value,
        unit=result.unit,
        status=result.status.value,
        algorithm_id=result.algorithm_id,
        algorithm_version=result.algorithm_version,
        source_type=result.source_type,
        upstream_project=result.upstream_project,
        upstream_commit=result.upstream_commit,
        inputs=inputs,
        metadata=asdict(result.metadata),
        confidence=result.confidence,
    )
