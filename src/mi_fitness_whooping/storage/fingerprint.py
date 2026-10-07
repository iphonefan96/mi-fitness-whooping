"""Legacy-compatible result fingerprinting owned by target storage.

This is the existing foundation-output-1 canonicalization, reproduced without
runtime Legacy imports. Any future change needs an explicit version decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Mapping

from mi_fitness_whooping.storage.contracts import PersistableMetricResult, ResultWriteContext


def canonical_hash(value: object) -> str:
    def normalize(obj: object) -> object:
        if is_dataclass(obj):
            return normalize(asdict(obj))
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Mapping):
            return {str(key): normalize(item) for key, item in
                    sorted(obj.items(), key=lambda pair: str(pair[0]))}
        if isinstance(obj, (tuple, list)):
            return [normalize(item) for item in obj]
        if isinstance(obj, (set, frozenset)):
            return sorted(normalize(item) for item in obj)
        if isinstance(obj, float):
            if not (-float("inf") < obj < float("inf")):
                raise ValueError("non-finite fingerprint input")
            return format(obj, ".17g")
        return obj

    encoded = json.dumps(normalize(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def result_fingerprint(result: PersistableMetricResult, context: ResultWriteContext) -> str:
    """Current digest; source policy is a row-key field, not a digest field."""
    return canonical_hash({
        "normalized_inputs": {
            "metric_name": result.metric_name,
            "date": result.day.isoformat(),
            "feature_fingerprints": [feature.fingerprint for feature in result.inputs],
            "metadata": result.metadata,
            "status": result.status,
            "value": result.value,
        },
        "profile_revision": context.profile_revision,
        "normalization_version": context.normalization_version,
        "algorithm_id": result.algorithm_id,
        "algorithm_version": result.algorithm_version,
        "input_contract_version": context.input_contract_version,
        "implementation_version": context.implementation_version,
    })
