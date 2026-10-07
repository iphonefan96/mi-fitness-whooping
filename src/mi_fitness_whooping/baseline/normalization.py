from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from mi_fitness_whooping.baseline.models import Freshness


def utc_from_epoch(seconds: int | float) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


def local_date_for(instant: datetime, *, offset_seconds: int | None = None, zone: str | None = None) -> date:
    if instant.tzinfo is None:
        raise ValueError("naive instant")
    if zone:
        return instant.astimezone(ZoneInfo(zone)).date()
    if offset_seconds is None:
        raise ValueError("timezone/offset missing")
    return (instant.astimezone(timezone.utc) + timedelta(seconds=offset_seconds)).date()


def sleep_date(end: datetime, *, offset_seconds: int | None = None, zone: str | None = None) -> date:
    if end.tzinfo is None:
        raise ValueError("naive sleep end")
    # Half-open interval: midnight end belongs to preceding sleep day.
    return local_date_for(end - timedelta(microseconds=1), offset_seconds=offset_seconds, zone=zone)


def freshness(measurement_date: date | None, requested_date: date, *, as_of: datetime,
              last_end: datetime | None, current_query: bool = True, max_age_hours: int = 36) -> Freshness:
    if measurement_date is None or last_end is None:
        return Freshness.MISSING
    if not current_query:
        return Freshness.HISTORICAL
    if measurement_date != requested_date or last_end > as_of or as_of - last_end > timedelta(hours=max_age_hours):
        return Freshness.STALE
    return Freshness.FRESH


def canonical_hash(value: object) -> str:
    def normalize(obj: object):
        if is_dataclass(obj):
            return normalize(asdict(obj))
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {str(k): normalize(v) for k, v in sorted(obj.items(), key=lambda p: str(p[0]))}
        if isinstance(obj, (tuple, list)):
            return [normalize(v) for v in obj]
        if isinstance(obj, (set, frozenset)):
            return sorted(normalize(v) for v in obj)
        if isinstance(obj, float):
            if not (-float("inf") < obj < float("inf")):
                raise ValueError("non-finite fingerprint input")
            return format(obj, ".17g")
        return obj
    encoded = json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def input_fingerprint(*, normalized_inputs: object, profile_revision: str,
                      normalization_version: str, algorithm_id: str,
                      algorithm_version: str, input_contract_version: str,
                      implementation_version: str) -> str:
    """Stable input identity; wall-clock/run IDs must never be included."""
    return canonical_hash({
        "normalized_inputs": normalized_inputs,
        "profile_revision": profile_revision,
        "normalization_version": normalization_version,
        "algorithm_id": algorithm_id,
        "algorithm_version": algorithm_version,
        "input_contract_version": input_contract_version,
        "implementation_version": implementation_version,
    })
