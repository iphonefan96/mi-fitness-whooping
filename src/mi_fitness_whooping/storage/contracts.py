"""Storage boundary values and protocols, without fingerprint or database code.

The target writer owns result identity, revisions and active selection. The
selected-night read contract carries only Sleep-required observations. A future
outer runner owns shared session lifetime and replay/clear policy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Protocol


def _freeze_json(value: object) -> object:
    """Copy JSON-shaped metadata into immutable containers, retaining number types."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("metadata keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("metadata must contain finite JSON-compatible values")


@dataclass(frozen=True, slots=True)
class StoredFeatureRef:
    """Selected feature lineage needed by result identity and stored provenance."""

    kind: str
    day: date
    fingerprint: str
    source_count: int
    source_ids_hash: str
    measurement_start: str | None
    measurement_end: str | None
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.kind or not self.fingerprint or not self.source_ids_hash:
            raise ValueError("feature lineage identity is required")
        if self.source_count < 0:
            raise ValueError("source_count cannot be negative")
        if not isinstance(self.quality_flags, tuple):
            raise TypeError("quality_flags must be a tuple")


@dataclass(frozen=True, slots=True)
class SelectedSleepFeature:
    """Narrow active-night read value; raw observations retain calculation gates."""

    reference: StoredFeatureRef
    tst_min: object
    deep_min: object
    rem_min: object
    waso_min: object
    awakening_durations_min: object
    bedtime_local_min: object
    stage_coverage: object

    def __post_init__(self) -> None:
        if self.reference.kind != "nightly":
            raise ValueError("selected Sleep input must be nightly")

    @property
    def kind(self) -> str:
        return self.reference.kind

    @property
    def day(self) -> date:
        return self.reference.day

    @property
    def fingerprint(self) -> str:
        return self.reference.fingerprint

    @property
    def source_count(self) -> int:
        return self.reference.source_count

    @property
    def source_ids_hash(self) -> str:
        return self.reference.source_ids_hash

    @property
    def measurement_start(self) -> str | None:
        return self.reference.measurement_start

    @property
    def measurement_end(self) -> str | None:
        return self.reference.measurement_end

    @property
    def quality_flags(self) -> tuple[str, ...]:
        return self.reference.quality_flags

    @property
    def values(self) -> Mapping[str, object]:
        """Compatibility view for the existing input adapter; only Sleep keys exist."""
        return MappingProxyType({
            "tst_min": self.tst_min, "deep_min": self.deep_min,
            "rem_min": self.rem_min, "waso_min": self.waso_min,
            "awakening_durations_min": self.awakening_durations_min,
            "bedtime_local_min": self.bedtime_local_min,
            "stage_coverage": self.stage_coverage,
        })


@dataclass(frozen=True, slots=True)
class PersistableMetricResult:
    """Calculated output plus ordered lineage, before storage assigns identity."""

    metric_name: str
    day: date
    value: float | None
    unit: str | None
    status: str
    algorithm_id: str
    algorithm_version: str
    metadata: Mapping[str, object]
    inputs: tuple[StoredFeatureRef, ...]
    source_type: str = "OUR_DERIVED"
    upstream_project: str | None = None
    upstream_commit: str | None = None
    confidence: str = "MEDIUM"

    def __post_init__(self) -> None:
        if not all((self.metric_name, self.status, self.algorithm_id,
                    self.algorithm_version, self.source_type, self.confidence)):
            raise ValueError("metric and algorithm identity are required")
        if not isinstance(self.inputs, tuple):
            raise TypeError("inputs must preserve ordered tuple lineage")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("metadata must be a mapping")
        if self.value is not None and (isinstance(self.value, bool) or
                                       not isinstance(self.value, (int, float)) or
                                       not math.isfinite(self.value)):
            raise ValueError("metric value must be finite numeric or missing")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class ResultWriteContext:
    """Persistence inputs supplied by an outer run, separate from calculation."""

    run_id: str
    profile_revision: str
    source_policy_version: str
    stored_freshness: str
    normalization_version: str
    implementation_version: str
    input_contract_version: str
    quality_gate_version: str
    source_scope: str = "primary"
    release_channel: str = "production"

    def __post_init__(self) -> None:
        if not all((self.run_id, self.profile_revision, self.source_policy_version,
                    self.stored_freshness, self.normalization_version,
                    self.implementation_version, self.input_contract_version,
                    self.quality_gate_version, self.source_scope, self.release_channel)):
            raise ValueError("write context fields must be supplied")


@dataclass(frozen=True, slots=True)
class ResultIdentity:
    """Post-fingerprint row key; digest alone is not the complete row identity."""

    metric_name: str
    day: date
    algorithm_id: str
    algorithm_version: str
    implementation_version: str
    normalization_version: str
    source_scope: str
    profile_revision: str
    source_policy_version: str
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class ActiveResult:
    result_id: int
    identity: ResultIdentity
    stored_freshness: str
    supersedes_result_id: int | None


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    """A write/reselection may report changed without inserting a new row."""

    changed: bool
    inserted: bool
    selection_changed: bool
    active: ActiveResult


class AnalyticsSession(Protocol):
    """Outer runner decides when the shared transaction commits or rolls back."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class AnalyticsSessionFactory(Protocol):
    """Begin an explicit outer-owned transaction; never nest implicitly."""

    def begin(self) -> AnalyticsSession: ...


class ActiveNightReader(Protocol):
    """Read selected nightly features inside an existing analytics session."""

    def selected_nights(
        self, session: AnalyticsSession, day: date,
    ) -> Mapping[date, SelectedSleepFeature]: ...


class MetricResultRepository(Protocol):
    """Result operations inside a caller-owned session; no commit method."""

    def persist(
        self, session: AnalyticsSession, result: PersistableMetricResult,
        context: ResultWriteContext,
    ) -> WriteOutcome: ...

    def get_active(
        self, session: AnalyticsSession, metric_name: str, day: date,
        source_scope: str = "primary", release_channel: str = "production",
    ) -> ActiveResult | None: ...

    def clear_active(
        self, session: AnalyticsSession, day: date,
        metric_names: tuple[str, ...], release_channel: str = "production",
    ) -> int: ...
