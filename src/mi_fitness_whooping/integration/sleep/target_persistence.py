"""Publish one synthetic Sleep date through target-owned result storage.

The caller supplies already selected features, profile and replay policy.
This sink opens only a Sleep-date session; a future full runner must own the
larger transaction and lock before any production activation.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from mi_fitness_whooping.domain.sleep.contracts import SleepMetric, SleepMetricResult
from mi_fitness_whooping.integration.sleep.input_adapter import NightlyFeature
from mi_fitness_whooping.integration.sleep.run_context import SleepRunContext
from mi_fitness_whooping.integration.sleep.storage_contract_adapter import to_persistable_sleep_result
from mi_fitness_whooping.storage.contracts import (
    AnalyticsSessionFactory, MetricResultRepository, ResultWriteContext,
)


class TargetSleepStore:
    """SleepResultSink backed by target storage; no Legacy or SQL dependency."""

    def __init__(
        self, sessions: AnalyticsSessionFactory, repository: MetricResultRepository,
        *, normalization_version: str = "xiaomi-normalization-1",
        implementation_version: str = "0.5.0",
        input_contract_version: str = "foundation-output-1",
        quality_gate_version: str = "foundation-gates-1",
    ) -> None:
        self.sessions = sessions
        self.repository = repository
        self.normalization_version = normalization_version
        self.implementation_version = implementation_version
        self.input_contract_version = input_contract_version
        self.quality_gate_version = quality_gate_version

    def publish(
        self,
        results: tuple[SleepMetricResult, ...],
        nights: Mapping[date, NightlyFeature],
        context: SleepRunContext,
    ) -> None:
        # Verify lineage against the already selected active feature map.
        for result in results:
            for ref in result.lineage:
                original = nights.get(ref.day)
                if original is None or (
                    getattr(original, "kind", None) != "nightly"
                    or original.day != ref.day
                    or original.fingerprint != ref.fingerprint
                    or original.source_count != ref.source_count
                    or original.source_ids_hash != ref.source_ids_hash
                    or original.measurement_start != ref.measurement_start
                    or original.measurement_end != ref.measurement_end
                    or original.quality_flags != ref.quality_flags
                ):
                    raise ValueError("Sleep Core lineage does not match an original active night")
        projected = tuple(to_persistable_sleep_result(result) for result in results)
        write_context = ResultWriteContext(
            run_id=context.run_id,
            profile_revision=context.profile_revision,
            source_policy_version=context.source_policy_version,
            stored_freshness=context.stored_freshness,
            normalization_version=self.normalization_version,
            implementation_version=self.implementation_version,
            input_contract_version=self.input_contract_version,
            quality_gate_version=self.quality_gate_version,
        )
        produced = {result.metric_name for result in projected}
        session = self.sessions.begin()
        try:
            for result in projected:
                self.repository.persist(session, result, write_context)
            if context.cleanup_obsolete:
                obsolete = tuple(metric.value for metric in SleepMetric
                                 if metric.value not in produced)
                if obsolete:
                    self.repository.clear_active(session, context.day, obsolete)
            session.commit()
        except BaseException:
            session.rollback()
            raise
