"""Target-owned reconciliation: parity with the Legacy candidate and explicit contract."""

from __future__ import annotations

import functools
import io
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Legacy"))

import mi_fitness_reconcile as candidate  # noqa: E402  (test-only oracle)
import reconciliation_digest  # noqa: E402
import test_reconciliation as candidate_tests  # noqa: E402
from mi_fitness_whooping.ingestion import reconcile as port  # noqa: E402

T0 = candidate_tests.T0
_original_reconcile = port.reconcile


def setUpModule() -> None:
    # The candidate's own suite, run against the port with the candidate's rule.
    port.reconcile = functools.partial(_original_reconcile, equivalence="candidate-v1")
    candidate_tests.rec = port


def tearDownModule() -> None:
    port.reconcile = _original_reconcile
    candidate_tests.rec = candidate


class CandidateSuiteOnPort(candidate_tests.ReconciliationTests):
    """The candidate regression tests, executed against the target port.

    One expectation differs by contract: an expected source database that is
    absent is SOURCE_INCOMPLETE, not a transient busy source.
    """

    def test_missing_whole_source_db_is_safe_skip(self):
        candidate_tests.hr(self.ru, T0, 60)
        self.run_reconcile(rebuild=True)
        before = candidate_tests.hash_file(self.output / port.TARGET_NAME)
        self.ru.close()
        self.ru_path.unlink()
        self.ru = sqlite3.connect(":memory:")
        with self.assertRaises(port.SourceIncompleteError) as raised:
            self.run_reconcile(full=True)
        self.assertNotIsInstance(raised.exception, port.SourceSnapshotBusyError)
        self.assertEqual(candidate_tests.hash_file(self.output / port.TARGET_NAME), before)


def table(db: sqlite3.Connection, name: str, *extra: str) -> None:
    columns = ", ".join(extra)
    db.execute(f"""CREATE TABLE IF NOT EXISTS {name}(
        sid TEXT NOT NULL,key TEXT NOT NULL,time INTEGER NOT NULL,value TEXT NOT NULL,
        zone_offset INTEGER NOT NULL,time_zero INTEGER NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0,isUploaded INTEGER NOT NULL DEFAULT 0
        {', ' + columns if columns else ''},PRIMARY KEY(sid,key,time))""")


class Sources:
    def __init__(self, root: Path) -> None:
        self.root = root / "source"
        self.db = {}
        for region in ("cn", "ru"):
            path = self.root / "DataBase" / "123" / region / "123.db"
            path.parent.mkdir(parents=True)
            db = sqlite3.connect(path)
            for name in ("heart_rate", "sleep", "steps"):
                table(db, name)
            table(db, "heart_rate_day", "valueList TEXT")
            table(db, "sleep_original_data", "rawData BLOB")
            db.commit()
            self.db[region] = db

    def put(self, region: str, name: str, when: int, value: dict, **columns) -> None:
        row = {"sid": "device", "key": name, "time": when, "value": json.dumps(value),
               "zone_offset": 0, "time_zero": when, "deleted": 0, "isUploaded": 0, **columns}
        db = self.db[region]
        db.execute(f"INSERT OR REPLACE INTO {name}({','.join(row)}) VALUES({','.join('?' * len(row))})",
                   tuple(row.values()))
        db.commit()

    def execute(self, region: str, sql: str, *params) -> None:
        self.db[region].execute(sql, params)
        self.db[region].commit()

    def close(self) -> None:
        for db in self.db.values():
            db.close()


def conflict_states(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as db:
        return {table: status for table, status in db.execute(
            "SELECT table_name, status FROM source_conflicts")}


def change_log(path: Path) -> list[tuple]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("""SELECT source_table,logical_record_id,old_hash,new_hash,change_type,
            affected_local_date,old_local_date,new_local_date FROM normalized_change_log
            ORDER BY source_table,logical_record_id,change_type""").fetchall()


class ExplicitContractTests(unittest.TestCase):
    def test_equivalence_is_required_and_policy_defaults_to_the_accepted_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = Sources(Path(temp))
            self.addCleanup(sources.close)
            sources.put("ru", "heart_rate", T0, {"bpm": 60})
            out = Path(temp) / "out"
            for kwargs in ({}, {"selection_policy": "unresolved_exclude"},
                           {"selection_policy": "ru_compat ", "equivalence": "strict-v2"}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaisesRegex(ValueError, "explicit"):
                        _original_reconcile(sources.root, out, rebuild=True, **kwargs)
            self.assertFalse(out.exists())
            cli = subprocess.run([str(ROOT / "mi-fitness-whooping"), "reconcile", "--source",
                                  str(sources.root), "--output", str(out), "--rebuild-from-source"],
                                 capture_output=True, text=True)
            self.assertEqual(cli.returncode, 2)
            self.assertIn("--equivalence", cli.stderr)
            self.assertFalse(out.exists())
            result = _original_reconcile(sources.root, out, rebuild=True, equivalence="strict-v2")
            self.assertEqual(result["conflict_policy_version"], "physiology-v1+strict-v2:unresolved_exclude")
            again = _original_reconcile(sources.root, out, equivalence="strict-v2")
            self.assertEqual((again["status"], again["conflict_policy_version"]),
                             ("NO NEW SOURCE DATA", "physiology-v1+strict-v2:unresolved_exclude"))


class NoLegacyRuntimeTests(unittest.TestCase):
    def test_reconcile_runs_with_only_src_on_the_path(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = Sources(Path(temp))
            self.addCleanup(sources.close)
            sources.put("ru", "heart_rate", T0, {"bpm": 60})
            code = ("import sys; from pathlib import Path; "
                    "from mi_fitness_whooping.ingestion.reconcile import reconcile; "
                    "r = reconcile(Path(sys.argv[1]), Path(sys.argv[2]), rebuild=True, "
                    "selection_policy='unresolved_exclude', equivalence='strict-v1'); "
                    "assert r['status'] == 'SUCCESS', r; "
                    "assert not {'mi_fitness_etl', 'mi_fitness_reconcile', 'analytics'} & set(sys.modules)")
            subprocess.run([sys.executable, "-B", "-c", code, str(sources.root), str(Path(temp) / "out")],
                           cwd=temp, env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
                           check=True, capture_output=True, text=True)


class EquivalenceInventoryTests(unittest.TestCase):
    """A CN/RU difference outside value/time/date is hidden by candidate-v1 only."""

    def test_meaningful_columns_are_conflicts_under_strict_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = Sources(root)
            self.addCleanup(sources.close)
            for region, upload, values, offset, raw in (("cn", 0, "[60,61]", 0, b"\x01\x02"),
                                                        ("ru", 1, "[60,99]", 3600, b"\x01\x03")):
                sources.put(region, "heart_rate_day", T0, {"avg_rhr": 60}, valueList=values)
                sources.put(region, "heart_rate", T0, {"bpm": 60}, zone_offset=offset)
                sources.put(region, "sleep_original_data", T0, {"v": 1}, rawData=raw)
                sources.put(region, "steps", T0, {"steps": 10}, isUploaded=upload)
            rules = {}
            for rule in ("candidate-v1", "strict-v1"):
                out = root / rule
                result = _original_reconcile(sources.root, out, rebuild=True,
                                             selection_policy="unresolved_exclude", equivalence=rule)
                self.assertEqual(result["status"], "SUCCESS")
                rules[rule] = conflict_states(out / port.TARGET_NAME)
                with closing(sqlite3.connect(out / port.TARGET_NAME)) as db:
                    # Every physical alternative is kept under both rules.
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records "
                                                "WHERE status='ACTIVE'").fetchone()[0], 8)
            hidden = "EQUIVALENT_PHYSIOLOGY_METADATA_DIFF"
            self.assertEqual(rules["candidate-v1"], {"heart_rate_day": hidden, "heart_rate": hidden,
                                                     "sleep_original_data": hidden, "steps": hidden})
            self.assertEqual(rules["strict-v1"], {"heart_rate_day": "UNRESOLVED_EXCLUDED",
                                                  "heart_rate": "UNRESOLVED_EXCLUDED",
                                                  "sleep_original_data": "UNRESOLVED_EXCLUDED",
                                                  "steps": hidden})


class CandidateParityScenarios(unittest.TestCase):
    """Same source history, same policy: port(candidate-v1) == Legacy candidate."""

    def run_both(self, sources: Sources, outputs: dict[str, Path], policy: str, **kwargs) -> dict:
        legacy = candidate.reconcile(sources.root, outputs["legacy"], selection_policy=policy, **kwargs)
        target = _original_reconcile(sources.root, outputs["target"], selection_policy=policy,
                                     equivalence="candidate-v1", **kwargs)
        self.assertEqual({k: v for k, v in target.items() if k in ("status", "counts")},
                         {k: v for k, v in legacy.items() if k in ("status", "counts")})
        paths = {name: out / port.TARGET_NAME for name, out in outputs.items()}
        if all(path.exists() for path in paths.values()):
            self.assertEqual(reconciliation_digest.digest(paths["target"]),
                             reconciliation_digest.digest(paths["legacy"]))
            self.assertEqual(change_log(paths["target"]), change_log(paths["legacy"]))
        return target

    def test_history_scenarios_match_candidate(self):
        for policy in ("unresolved_exclude", "ru_compat"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sources = Sources(root)
                self.addCleanup(sources.close)
                outputs = {"legacy": root / "legacy", "target": root / "target"}
                old = T0 - 30 * 86400
                for region in ("cn", "ru"):
                    sources.put(region, "heart_rate", old, {"bpm": 60})               # equal duplicate
                    sources.put(region, "steps", old, {"steps": 10}, isUploaded=int(region == "ru"))
                sources.put("cn", "heart_rate", T0, {"bpm": 61})                      # semantic conflict
                sources.put("ru", "heart_rate", T0, {"bpm": 75})
                for offset in range(4):
                    sources.put("ru", "sleep", old + offset * 86400, {"night": offset})
                self.assertEqual(self.run_both(sources, outputs, policy, rebuild=True)["status"], "SUCCESS")
                self.assertEqual(self.run_both(sources, outputs, policy)["status"], "NO NEW SOURCE DATA")
                for label, region, sql, params in (
                    ("late correction", "ru", "UPDATE steps SET value=? WHERE time=?",
                     (json.dumps({"steps": 99}), old)),
                    ("deletion", "ru", "DELETE FROM sleep WHERE time=?", (old + 86400,)),
                    ("tombstone", "ru", "UPDATE sleep SET deleted=1 WHERE time=?", (old + 2 * 86400,)),
                ):
                    with self.subTest(label):
                        sources.execute(region, sql, *params)
                        self.assertEqual(self.run_both(sources, outputs, policy, full=True)["status"],
                                         "SUCCESS")
                self.assertEqual(self.run_both(sources, outputs, policy, full=True)["counts"]
                                 .get("canonical_update", 0), 0)


if __name__ == "__main__":
    unittest.main()


class SchemaVersionSources:
    """CN/RU databases whose `red_dot_day` schemas differ like the NAS snapshot."""

    OLD = ("sid TEXT NOT NULL,key TEXT NOT NULL,tag TEXT NOT NULL,time INTEGER NOT NULL,"
           "zone_offset INTEGER NOT NULL,zone_name TEXT,valueList BLOB,value TEXT NOT NULL,"
           "time_zero INTEGER NOT NULL,deleted INTEGER DEFAULT 0,isUploaded INTEGER DEFAULT 0")
    NEW = OLD + ",category TEXT DEFAULT '',sportFitnesId INTEGER,extra TEXT,cheat_info TEXT"

    def __init__(self, root: Path, ru_extra: str = "") -> None:
        self.root = root / "source"
        self.db = {}
        for region, columns in (("cn", self.OLD), ("ru", self.NEW + ru_extra)):
            path = self.root / "DataBase" / "123" / region / "123.db"
            path.parent.mkdir(parents=True)
            db = sqlite3.connect(path)
            for name in ("heart_rate", "sleep", "steps"):
                table(db, name)
            db.execute(f"CREATE TABLE red_dot_day({columns},PRIMARY KEY(sid,key,time))")
            db.commit()
            self.db[region] = db

    def put(self, region: str, when: int, **columns) -> None:
        row = {"sid": "device", "key": "red_dot", "tag": "days", "time": when, "zone_offset": 0,
               "value": json.dumps({"dot": 1}), "time_zero": when, **columns}
        self.db[region].execute(f"INSERT INTO red_dot_day({','.join(row)}) VALUES({','.join('?' * len(row))})",
                                tuple(row.values()))
        self.db[region].commit()

    def close(self) -> None:
        for db in self.db.values():
            db.close()


class StrictV2Tests(unittest.TestCase):
    def build(self, sources, root: Path, rule: str) -> Path:
        out = root / rule
        result = _original_reconcile(sources.root, out, rebuild=True, equivalence=rule)
        self.assertEqual(result["status"], "SUCCESS")
        return out / port.TARGET_NAME

    def conflicts(self, path: Path) -> dict[int, tuple[str, str]]:
        with closing(sqlite3.connect(path)) as db:
            by_time = {}
            for status, reason, physical in db.execute(
                    "SELECT status, selection_reason, physical_ids_json FROM source_conflicts"):
                when = db.execute("SELECT source_timestamp FROM physical_records WHERE physical_record_id=?",
                                  (json.loads(physical)[0],)).fetchone()[0]
                by_time[when] = (status, reason)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM physical_records WHERE status='ACTIVE'")
                             .fetchone()[0], 2 * len(by_time))   # every alternative kept
            return by_time

    def test_added_columns_with_their_defaults_are_a_schema_difference_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = SchemaVersionSources(root)
            self.addCleanup(sources.close)
            cases = {
                T0: ({}, "EQUIVALENT_SCHEMA_DEFAULT_DIFF"),                       # NAS red_dot_day pattern
                T0 + 60: ({"category": "sport"}, "UNRESOLVED_EXCLUDED"),          # not the declared default
                T0 + 120: ({"category": None}, "UNRESOLVED_EXCLUDED"),            # NULL is not DEFAULT ''
                T0 + 180: ({"sportFitnesId": 7}, "UNRESOLVED_EXCLUDED"),          # nullable, no DEFAULT
                T0 + 240: ({"valueList": b"\x01"}, "UNRESOLVED_EXCLUDED"),        # shared data column
            }
            for when, (ru_columns, _) in cases.items():
                sources.put("cn", when, isUploaded=0)
                sources.put("ru", when, isUploaded=1, **{"category": "", **ru_columns})
            v2 = self.conflicts(self.build(sources, root, "strict-v2"))
            self.assertEqual({when: state for when, (state, _) in v2.items()},
                             {when: expected for when, (_, expected) in cases.items()})
            self.assertEqual(v2[T0][1], "EQUIVALENT_SCHEMA_DEFAULTS:category,cheat_info,extra,sportFitnesId")
            v1 = self.conflicts(self.build(sources, root, "strict-v1"))
            self.assertEqual(v1[T0][0], "UNRESOLVED_EXCLUDED")    # the former false conflict
            with closing(sqlite3.connect(root / "strict-v2" / port.TARGET_NAME)) as db:
                roles = sorted(r for (r,) in db.execute(
                    "SELECT role FROM normalized_provenance WHERE logical_record_id IN "
                    "(SELECT logical_record_id FROM source_conflicts WHERE status='EQUIVALENT_SCHEMA_DEFAULT_DIFF')"))
                self.assertEqual(roles, ["DUPLICATE_EQUIVALENT", "PRIMARY"])

    def test_undeclared_or_non_constant_defaults_stay_conflicts(self):
        for extra, value in ((",stamp TEXT DEFAULT CURRENT_TIMESTAMP", {"stamp": "2026-01-01 00:00:00"}),
                             (",level INTEGER NOT NULL DEFAULT (1+1)", {"level": 2}),
                             (",flag INTEGER NOT NULL", {"flag": 0})):
            with self.subTest(extra), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sources = SchemaVersionSources(root, ru_extra=extra)
                self.addCleanup(sources.close)
                sources.put("cn", T0)
                sources.put("ru", T0, category="", **value)
                self.assertEqual(self.conflicts(self.build(sources, root, "strict-v2"))[T0][0],
                                 "UNRESOLVED_EXCLUDED")

    def test_meaningful_shared_columns_and_upload_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = Sources(root)
            self.addCleanup(sources.close)
            for region, upload, values, offset, raw in (("cn", 0, "[60,61]", 0, b"\x01\x02"),
                                                        ("ru", 1, "[60,99]", 3600, b"\x01\x03")):
                sources.put(region, "heart_rate_day", T0, {"avg_rhr": 60}, valueList=values)
                sources.put(region, "heart_rate", T0, {"bpm": 60}, zone_offset=offset)
                sources.put(region, "sleep_original_data", T0, {"v": 1}, rawData=raw)
                sources.put(region, "steps", T0, {"steps": 10}, isUploaded=upload)
            out = root / "v2"
            _original_reconcile(sources.root, out, rebuild=True, equivalence="strict-v2")
            self.assertEqual(conflict_states(out / port.TARGET_NAME),
                             {"heart_rate_day": "UNRESOLVED_EXCLUDED", "heart_rate": "UNRESOLVED_EXCLUDED",
                              "sleep_original_data": "UNRESOLVED_EXCLUDED",
                              "steps": "EQUIVALENT_PHYSIOLOGY_METADATA_DIFF"})


class MissingSourceDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = Sources(self.root)
        self.sources.put("cn", "heart_rate", T0, {"bpm": 60})
        self.sources.put("ru", "heart_rate", T0 + 60, {"bpm": 62})
        self.out = self.root / "out"
        self.target = self.out / port.TARGET_NAME

    def cli(self, *extra: str) -> tuple[int, dict]:
        run = subprocess.run([str(ROOT / "mi-fitness-whooping"), "reconcile", "--source", str(self.sources.root),
                              "--output", str(self.out), "--equivalence", "strict-v2", *extra],
                             capture_output=True, text=True)
        return run.returncode, json.loads(run.stdout)

    def test_absent_expected_database_is_source_incomplete_and_publishes_nothing(self):
        self.assertEqual(self.cli("--rebuild-from-source")[0], 0)
        before = self.target.read_bytes()
        cn = self.sources.root / "DataBase" / "123" / "cn"
        self.sources.db["cn"].close()
        shutil.move(cn, self.root / "cn-away")
        for mode in ((), ("--full-reconcile",), ("--rebuild-from-source",)):
            with self.subTest(mode=mode):
                code, result = self.cli(*mode)
                self.assertEqual(code, 3)
                self.assertEqual(result["status"], "SOURCE_INCOMPLETE")
                self.assertEqual(result["missing_databases"],
                                 [{"relative_path": "DataBase/123/cn/123.db",
                                   "source_key": "xiaomi-account:123:region:cn"}])
                self.assertEqual(self.target.read_bytes(), before)
                self.assertEqual(sorted(p.name for p in self.out.iterdir()), [port.TARGET_NAME])
        shutil.move(self.root / "cn-away", cn)
        # Restored unchanged: the published generation is current again.
        self.assertEqual(self.cli(), (0, {**self.cli()[1], "status": "NO NEW SOURCE DATA"}))

    def test_busy_source_is_reported_separately(self):
        self.assertEqual(self.cli("--rebuild-from-source")[0], 0)
        out = io.StringIO()
        with patch.object(port, "stable_stage_database", side_effect=port.SourceSnapshotBusyError("busy")), \
                redirect_stdout(out):
            code = port.main(["--source", str(self.sources.root), "--output", str(self.out),
                              "--equivalence", "strict-v2", "--full-reconcile"])
        self.assertEqual((code, json.loads(out.getvalue())["status"], json.loads(out.getvalue())["reason"]),
                         (0, "SKIPPED", "SOURCE_BUSY"))

    def test_first_build_has_no_expected_list(self):
        self.sources.db["cn"].close()
        shutil.rmtree(self.sources.root / "DataBase" / "123" / "cn")
        code, result = self.cli("--rebuild-from-source")
        self.assertEqual((code, result["status"]), (0, "SUCCESS"))
        with closing(sqlite3.connect(self.target)) as db:
            self.assertEqual([k for (k,) in db.execute("SELECT source_key FROM source_database_identities")],
                             ["xiaomi-account:123:region:ru"])
