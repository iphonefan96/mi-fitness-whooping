from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics.normalization.core import canonical_hash


ALLOWED_FIELDS = {"timezone", "date_of_birth", "sex", "height_cm", "weight_kg",
                  "sleep_target_min", "max_hr_bpm", "rhr_override_bpm", "waist_cm"}


def load_profile(path: str | Path | None) -> tuple[dict, str]:
    if path is None or not Path(path).exists():
        data = {"schema_version": 1, "values": []}
        return data, canonical_hash(data)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("values"), list):
        raise ValueError("unsupported profile schema")
    intervals: dict[str, list[tuple[date, date | None]]] = {}
    for entry in data["values"]:
        field = entry.get("field")
        if field not in ALLOWED_FIELDS or "effective_from" not in entry or "value" not in entry:
            raise ValueError("invalid profile entry")
        begin = date.fromisoformat(entry["effective_from"])
        end = date.fromisoformat(entry["effective_to"]) if entry.get("effective_to") else None
        if end is not None and end < begin:
            raise ValueError("inverted profile interval")
        if field == "timezone":
            ZoneInfo(entry["value"])
        if field in {"height_cm", "weight_kg", "sleep_target_min", "max_hr_bpm", "rhr_override_bpm", "waist_cm"}:
            if not isinstance(entry["value"], (float, int)) or entry["value"] <= 0:
                raise ValueError(f"invalid {field}")
        if field == "date_of_birth":
            date.fromisoformat(entry["value"])
        intervals.setdefault(field, []).append((begin, end))
    for field, spans in intervals.items():
        spans.sort()
        for (_, old_end), (new_begin, _) in zip(spans, spans[1:]):
            if old_end is None or old_end >= new_begin:
                raise ValueError(f"overlapping profile intervals for {field}")
    return data, canonical_hash(data)


def effective_values(data: dict, day: date) -> dict:
    return {entry["field"]: entry["value"] for entry in data["values"]
            if date.fromisoformat(entry["effective_from"]) <= day and
            (not entry.get("effective_to") or day <= date.fromisoformat(entry["effective_to"]))}

