"""Shared canonical lineage and calculated-result types for target analytics.

These types carry no storage identity, revision or freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class FeatureLineage:
    """Opaque selected-feature identity carried through to result storage."""

    kind: str
    day: date
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None = None
    measurement_end: str | None = None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"nightly", "daily"}:
            raise ValueError("feature lineage kind must be nightly or daily")
        if not self.fingerprint or not self.source_ids_hash:
            raise ValueError("feature lineage identity is required")
        if self.source_count < 0:
            raise ValueError("source_count cannot be negative")
        if not isinstance(self.quality_flags, tuple):
            raise TypeError("quality_flags must be an immutable tuple")


@dataclass(frozen=True, slots=True)
class MetricResult:
    """Pure calculation result; storage identity, revision and freshness are external.

    Metadata is JSON-shaped and part of the stored result identity.
    """

    name: str
    day: date
    value: float | None
    unit: str | None
    status: str
    algorithm_id: str
    algorithm_version: str
    lineage: tuple[FeatureLineage, ...]
    metadata: dict[str, Any]
    source_type: str = "OUR_DERIVED"
    upstream_project: str | None = None
    upstream_commit: str | None = None
    confidence: str = "MEDIUM"

    def __post_init__(self) -> None:
        if self.status not in {"VALID", "REDUCED", "CALIBRATING", "INSUFFICIENT_DATA"}:
            raise ValueError("unsupported calculation status")
        if (self.value is not None) != (self.status in {"VALID", "REDUCED"}):
            raise ValueError("metric value and calculation status disagree")
        if not self.algorithm_id or not self.algorithm_version:
            raise ValueError("algorithm identity is required")
        if not isinstance(self.lineage, tuple):
            raise TypeError("lineage must be an immutable ordered tuple")
