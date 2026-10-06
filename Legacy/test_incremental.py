#!/usr/bin/env python3
"""Standard-library integration tests for incremental/idempotent behavior."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).with_name("mi_fitness_etl.py")
BASE_TIME = 1_750_000_000


COMMON_COLUMNS = """
sid TEXT NOT NULL,
key TEXT NOT NULL,
time INTEGER NOT NULL,
value TEXT NOT NULL,
zone_offset INTEGER NOT NULL,
time_zero INTEGER NOT NULL,
zone_name TEXT,
deleted INTEGER DEFAULT 0,
isUploaded INTEGER DEFAULT 0,
PRIMARY KEY(sid,key,time) ON CONFLICT REPLACE
"""


def run(source: Path, output: Path, *extra: str, expect: int = 0) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(source), "--output", str(output), "--overlap-hours", "48", *extra],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != expect:
        raise AssertionError(f"expected exit {expect}, got {result.returncode}:\n{result.stdout}")
    return result.stdout


def target_value(output: Path, timestamp: int) -> float:
    with sqlite3.connect(output / "health.sqlite") as connection:
        return float(connection.execute("SELECT bpm FROM heart_rate WHERE timestamp_utc=?", (timestamp,)).fetchone()[0])


def target_count(output: Path) -> int:
    with sqlite3.connect(output / "health.sqlite") as connection:
        return int(connection.execute("SELECT count(*) FROM heart_rate").fetchone()[0])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mi-fitness-etl-test-") as temporary:
        root = Path(temporary)
        source = root / "source"
        output = root / "output"
        db_dir = source / "DataBase" / "123" / "ru"
        db_dir.mkdir(parents=True)
        db_path = db_dir / "123.db"
        source_db = sqlite3.connect(db_path)
        source_db.execute("PRAGMA journal_mode=WAL")
        source_db.execute("PRAGMA wal_autocheckpoint=0")
        for table in ("heart_rate", "sleep", "steps"):
            source_db.execute(f"CREATE TABLE {table}({COMMON_COLUMNS})")
        source_db.execute(
            "INSERT INTO heart_rate VALUES(?,?,?,?,?,?,?,?,?)",
            ("device", "heart_rate", BASE_TIME, json.dumps({"time": BASE_TIME, "bpm": 60}), 14400, BASE_TIME + 14400, None, 0, 0),
        )
        source_db.commit()

        first = run(source, output)
        assert "Status: SUCCESS" in first
        assert target_count(output) == 1
        print("Test A (initial full load): PASS")

        second = run(source, output)
        assert "NO NEW SOURCE DATA" in second
        assert target_count(output) == 1
        print("Test B (unchanged/idempotent): PASS")

        new_time = BASE_TIME + 3600
        source_db.execute(
            "INSERT INTO heart_rate VALUES(?,?,?,?,?,?,?,?,?)",
            ("device", "heart_rate", new_time, json.dumps({"time": new_time, "bpm": 61}), 14400, new_time + 14400, None, 0, 0),
        )
        source_db.commit()
        third = run(source, output)
        assert "new: 1" in third
        assert target_count(output) == 2
        print("Test C (new source row): PASS")

        source_db.execute(
            "UPDATE heart_rate SET value=? WHERE sid='device' AND key='heart_rate' AND time=?",
            (json.dumps({"time": new_time, "bpm": 66}), new_time),
        )
        source_db.commit()
        fourth = run(source, output)
        assert "updated: 1" in fourth
        assert target_count(output) == 2
        assert target_value(output, new_time) == 66
        print("Test D (overlap update): PASS")

        state_before = (output / "state.json").read_bytes()
        count_before = target_count(output)
        failure_time = BASE_TIME + 7200
        source_db.execute(
            "INSERT INTO heart_rate VALUES(?,?,?,?,?,?,?,?,?)",
            ("device", "heart_rate", failure_time, json.dumps({"time": failure_time, "bpm": 67}), 14400, failure_time + 14400, None, 0, 0),
        )
        source_db.commit()
        failure = run(source, output, "--fail-after", "1", expect=1)
        assert "Status: FAILED" in failure
        assert (output / "state.json").read_bytes() == state_before
        assert target_count(output) == count_before
        print("Test E (rollback/state unchanged): PASS")
        source_db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
