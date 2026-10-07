"""Coordinate one already-loaded Sleep Core date without source or clock access."""

from __future__ import annotations

from datetime import date
from typing import Mapping, Protocol

from mi_fitness_whooping.analytics.sleep.core import calculate_sleep_core
from mi_fitness_whooping.domain.sleep.contracts import SleepMetricResult
from mi_fitness_whooping.integration.sleep.input_adapter import NightlyFeature, adapt_sleep_input
from mi_fitness_whooping.integration.sleep.run_context import SleepRunContext


class SleepResultSink(Protocol):
    """Publish canonical results atomically; storage implementation is external."""

    def publish(
        self,
        results: tuple[SleepMetricResult, ...],
        nights: Mapping[date, NightlyFeature],
        context: SleepRunContext,
    ) -> None: ...


def run_sleep_day(
    nights: Mapping[date, NightlyFeature],
    profile: Mapping[str, object],
    context: SleepRunContext,
    sink: SleepResultSink,
) -> tuple[SleepMetricResult, ...]:
    """Compute and publish one date; caller supplies active features and run policy."""
    inp = adapt_sleep_input(context.day, nights, profile, context.profile_revision)
    results = calculate_sleep_core(inp)
    sink.publish(results, nights, context)
    return results
