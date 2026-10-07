"""Explicit outer-run inputs for one Sleep publication, independent of Legacy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SleepRunContext:
    day: date
    profile_revision: str
    run_id: str
    source_policy_version: str
    stored_freshness: str
    cleanup_obsolete: bool
