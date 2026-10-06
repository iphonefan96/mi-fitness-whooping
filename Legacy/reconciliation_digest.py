#!/usr/bin/env python3
"""Read-only, timestamp-independent digest of a reconciliation candidate.

This intentionally omits run/import times, SQLite page layout, and row order.
It includes selected logical content, physical content/status, conflicts,
provenance roles, and the normalized tables consumed by analytics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


QUERIES = {
    "physical": """SELECT physical_record_id,logical_record_id,source_db_id,
      source_table,source_pk_json,source_timestamp,local_date,hex(content_hash),
      source_deleted,status FROM physical_records ORDER BY physical_record_id""",
    "canonical": """SELECT logical_record_id,physical_record_id,hex(content_hash),
      source_db_id,source_table,source_timestamp,local_date,conflict_status,
      conflict_policy_version FROM canonical_selection ORDER BY logical_record_id""",
    "provenance": """SELECT logical_record_id,physical_record_id,source_db_id,source_table,
      source_pk_json,role,conflict_policy_version FROM normalized_provenance
      ORDER BY logical_record_id,physical_record_id""",
    "conflicts": """SELECT conflict_id,logical_record_id,table_name,physical_ids_json,
      payload_hashes_json,selected_physical_id,selection_reason,status,
      conflict_policy_version FROM source_conflicts ORDER BY conflict_id""",
    "raw_selected": """SELECT record_id,source_table,source_timestamp,local_date,
      source_deleted,hex(content_hash) FROM raw_records ORDER BY record_id""",
    "heart_rate": """SELECT source_record_id,timestamp_utc,local_date,bpm,kind
      FROM heart_rate ORDER BY source_record_id""",
    "heart_rate_events": """SELECT * FROM heart_rate_events ORDER BY source_record_id""",
    "heart_rate_event_samples": """SELECT * FROM heart_rate_event_samples
      ORDER BY source_record_id,sample_index""",
    "spo2": """SELECT source_record_id,timestamp_utc,local_date,value,kind
      FROM spo2 ORDER BY source_record_id""",
    "stress": """SELECT source_record_id,timestamp_utc,local_date,value,kind
      FROM stress ORDER BY source_record_id""",
    "activity_samples": """SELECT * FROM activity_samples ORDER BY source_record_id""",
    "calorie_samples": """SELECT * FROM calorie_samples ORDER BY source_record_id""",
    "intensity_samples": """SELECT * FROM intensity_samples ORDER BY source_record_id""",
    "standing_intervals": """SELECT * FROM standing_intervals ORDER BY source_record_id""",
    "sleep_sessions": """SELECT * FROM sleep_sessions ORDER BY source_record_id""",
    "sleep_stages": """SELECT * FROM sleep_stages ORDER BY source_record_id,stage_index""",
    "daily_summary": """SELECT * FROM daily_summary ORDER BY local_date""",
    "workouts": """SELECT * FROM workouts ORDER BY source_record_id""",
    "derived_metrics": """SELECT * FROM derived_metrics ORDER BY source_record_id,field_path""",
}


def digest(path: Path) -> dict:
    connection = sqlite3.connect(path.resolve().as_uri() + "?immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    result: dict[str, dict[str, int | str]] = {}
    try:
        for name, query in QUERIES.items():
            h = hashlib.sha256()
            count = 0
            for row in connection.execute(query):
                values = dict(row)
                values.pop("imported_at", None)
                values.pop("updated_at", None)
                encoded = json.dumps(values, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()
                h.update(len(encoded).to_bytes(4, "big"))
                h.update(encoded)
                count += 1
            result[name] = {"rows": count, "sha256": h.hexdigest()}
        combined = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return {"combined_sha256": combined, "tables": result}
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(digest(args.database), sort_keys=True))
