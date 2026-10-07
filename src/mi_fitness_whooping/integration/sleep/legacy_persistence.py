"""TEMPORARY MIGRATION DEBT: publish Sleep results through Legacy storage.

This bridge owns only the synthetic Sleep transaction and obsolete selection
cleanup. The future target storage boundary must replace it before Legacy
removal. The target orchestrator never imports SQLite or Legacy types.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Mapping, cast

from analytics.algorithms.foundations import FeatureRecord
from analytics.storage.db import put_result
from mi_fitness_whooping.domain.sleep.contracts import SleepMetric, SleepMetricResult
from mi_fitness_whooping.integration.sleep.input_adapter import NightlyFeature
from mi_fitness_whooping.integration.sleep.output_adapter import adapt_sleep_result
from mi_fitness_whooping.integration.sleep.run_context import SleepRunContext


class LegacySleepStore:
    """Compatibility-only storage transaction for a single synthetic date."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def publish(
        self,
        results: tuple[SleepMetricResult, ...],
        nights: Mapping[date, NightlyFeature],
        context: SleepRunContext,
    ) -> None:
        if self.db.in_transaction:
            raise RuntimeError("LegacySleepStore requires an idle connection")
        originals = cast(Mapping[date, FeatureRecord], nights)
        drafts = tuple(adapt_sleep_result(result, originals) for result in results)
        produced = {draft.name for draft in drafts}
        with self.db:
            for draft in drafts:
                put_result(
                    self.db, draft, run_id=context.run_id,
                    profile_revision=context.profile_revision,
                    freshness_status=context.stored_freshness,
                    source_policy_version=context.source_policy_version,
                )
            if context.cleanup_obsolete:
                for metric in SleepMetric:
                    if metric.value not in produced:
                        # Legacy's incremental cleanup removes the active
                        # production selection but keeps revision history.
                        self.db.execute(
                            "DELETE FROM active_metric_selection WHERE metric_date=? "
                            "AND metric_name=? AND release_channel='production'",
                            (context.day.isoformat(), metric.value),
                        )
