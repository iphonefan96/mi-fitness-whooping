"""Target-owned reconciliation: parity with the Legacy candidate and explicit contract."""

from __future__ import annotations

import functools
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

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
    """All 24 candidate regression tests, executed against the target port."""


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
    def test_policy_and_equivalence_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            sources = Sources(Path(temp))
            self.addCleanup(sources.close)
            out = Path(temp) / "out"
            for kwargs in ({}, {"selection_policy": "unresolved_exclude"},
                           {"equivalence": "strict-v1"}, {"selection_policy": "ru_compat ",
                                                          "equivalence": "strict-v1"}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaisesRegex(ValueError, "explicit"):
                        _original_reconcile(sources.root, out, rebuild=True, **kwargs)
            self.assertFalse(out.exists())
            cli = subprocess.run([str(ROOT / "mi-fitness-whooping"), "reconcile", "--source",
                                  str(sources.root), "--output", str(out), "--rebuild-from-source"],
                                 capture_output=True, text=True)
            self.assertEqual(cli.returncode, 2)
            self.assertIn("--selection-policy", cli.stderr)
            self.assertFalse(out.exists())


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
