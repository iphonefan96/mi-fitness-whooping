"""Phase 4C1: ordinary co-imports and a synthetic, persisted sleep path."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from analytics.algorithms.sleep import calculate_sleep_day
from analytics.models import Feature, Freshness, QualityFlag, QualityStatus
from analytics.profile.config import load_profile
from analytics.storage.db import (
    active_feature_records, connect, migrate, put_feature, put_result,
)
from mi_fitness_whooping.analytics.sleep.core import calculate_sleep_core
from mi_fitness_whooping.integration.sleep.input_adapter import adapt_sleep_input
from mi_fitness_whooping.integration.sleep.output_adapter import adapt_sleep_result


ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 1, 20)
POLICY = "primary-v1"
FRESHNESS = "HISTORICAL"  # Fixed outer context; the calculation never reads a clock.
STORED_FIELDS = (
    "result_id", "metric_date", "metric_name", "value", "unit", "status",
    "freshness_status", "source_type", "algorithm_id", "algorithm_version",
    "implementation_version", "normalization_version", "upstream_project",
    "upstream_commit", "source_scope", "profile_revision", "source_policy_version",
    "quality_gate_version", "input_fingerprint", "source_signals_json",
    "input_coverage_json", "confidence", "quality_flags_json",
    "measurement_start", "measurement_end", "source_updated_at", "metadata_json",
    "run_id", "supersedes_result_id",
)


def feature(day: date, *, corrected: bool = False) -> Feature:
    fingerprint = f"synthetic:{day.isoformat()}:{'correction' if corrected else 'initial'}"
    return Feature(
        kind="nightly", metric_date=day,
        measurement_start=datetime(day.year, day.month, day.day, 20, tzinfo=timezone.utc),
        measurement_end=datetime(day.year, day.month, day.day, 23, tzinfo=timezone.utc),
        values={"tst_min": 300 if corrected else 480, "deep_min": 90, "rem_min": 90,
                "waso_min": 0, "awakening_durations_min": [],
                "bedtime_local_min": 1380, "stage_coverage": "COMPLETE"},
        source_ids=(f"synthetic-session:{day.isoformat()}",),
        quality_status=QualityStatus.OK,
        quality_flags=frozenset({QualityFlag.VENDOR_DERIVED}),
        input_fingerprint=fingerprint, freshness_status=Freshness.HISTORICAL,
    )


def current_snapshot(db) -> tuple[list[tuple], list[tuple]]:
    rows = [tuple(row[field] for field in STORED_FIELDS) for row in db.execute(
        "SELECT * FROM derived_metric_results ORDER BY result_id")]
    active = [tuple(row) for row in db.execute(
        "SELECT metric_name,metric_date,source_scope,release_channel,result_id "
        "FROM active_metric_selection ORDER BY metric_name")]
    return rows, active


class PackageCoexistenceTests(unittest.TestCase):
    def test_both_packages_resolve_normally_in_either_root_order(self):
        code = "\n".join((
            "from pathlib import Path",
            "import analytics",
            "import analytics.algorithms.foundations as old",
            "import mi_fitness_whooping as target",
            "import mi_fitness_whooping.analytics.sleep.core as new",
            "import mi_fitness_whooping.integration.sleep.output_adapter as adapter",
            "assert Path(analytics.__file__).resolve() == Path('Legacy/analytics/__init__.py').resolve()",
            "assert Path(old.__file__).resolve() == Path('Legacy/analytics/algorithms/foundations.py').resolve()",
            "assert Path(target.__file__).resolve() == Path('src/mi_fitness_whooping/__init__.py').resolve()",
            "assert Path(new.__file__).resolve() == Path('src/mi_fitness_whooping/analytics/sleep/core.py').resolve()",
            "assert Path(adapter.__file__).resolve() == Path('src/mi_fitness_whooping/integration/sleep/output_adapter.py').resolve()",
        ))
        for roots in (("Legacy", "src"), ("src", "Legacy")):
            with self.subTest(roots=roots):
                env = os.environ.copy()
                env["PYTHONPATH"] = os.pathsep.join(str(ROOT / part) for part in roots)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                completed = subprocess.run([sys.executable, "-B", "-c", code],
                                           cwd=ROOT, env=env, text=True,
                                           capture_output=True, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)


class PersistedSleepSeamTests(unittest.TestCase):
    def _run_case(self, profile_path: Path | None, expected_target: float) -> None:
        profile, revision = load_profile(profile_path)
        with tempfile.TemporaryDirectory() as directory:
            snapshots = {}
            for name in ("legacy", "target"):
                db_path = Path(directory) / f"{name}.sqlite"
                db = connect(db_path)
                try:
                    migrate(db)
                    with db:
                        for offset in range(14, -1, -1):
                            self.assertTrue(put_feature(db, feature(DAY - timedelta(days=offset)),
                                                        profile_revision=revision,
                                                        source_policy_version=POLICY))
                    nights, _ = active_feature_records(db)
                    self.assertEqual(len(nights), 15)
                    seen = []
                    for step, correction in (("first", False), ("unchanged", False),
                                             ("corrected", True)):
                        if correction:
                            with db:
                                self.assertTrue(put_feature(db, feature(DAY - timedelta(days=3),
                                                                         corrected=True),
                                                            profile_revision=revision,
                                                            source_policy_version=POLICY))
                            nights, _ = active_feature_records(db)
                        legacy = calculate_sleep_day(DAY, nights, profile)
                        canonical = adapt_sleep_input(DAY, nights, profile, revision)
                        self.assertIs(type(canonical.targets[-1].minutes), float)
                        self.assertEqual(canonical.targets[-1].minutes, expected_target)
                        target = [adapt_sleep_result(result, nights)
                                  for result in calculate_sleep_core(canonical)]
                        self.assertEqual(target, legacy)
                        self.assertEqual([draft.name for draft in target],
                                         ["sleep.score", "sleep.need_min", "sleep.debt_min"])
                        self.assertIs(type(target[1].value), float)
                        self.assertEqual(target[1].value, expected_target)
                        for prior, adapted in zip(legacy, target):
                            self.assertEqual([row.fingerprint for row in adapted.inputs],
                                             [row.fingerprint for row in prior.inputs])
                            for row in adapted.inputs:
                                self.assertIs(row, nights[row.day])
                        drafts = legacy if name == "legacy" else target
                        with db:
                            changed = [put_result(db, draft, run_id=f"synthetic-{step}",
                                                  profile_revision=revision,
                                                  freshness_status=FRESHNESS,
                                                  source_policy_version=POLICY)
                                       for draft in drafts]
                        self.assertEqual(changed, {"first": [True] * 3,
                                                   "unchanged": [False] * 3,
                                                   "corrected": [True, False, True]}[step])
                        seen.append((step, changed, current_snapshot(db)))
                        if step == "unchanged":
                            self.assertEqual(seen[-1][2], seen[0][2])
                    snapshots[name] = seen
                finally:
                    db.close()
                # Read back from a new connection: the comparison covers persisted selection.
                reopened = connect(db_path)
                try:
                    self.assertEqual(current_snapshot(reopened), seen[-1][2])
                finally:
                    reopened.close()
            self.assertEqual(snapshots["target"], snapshots["legacy"])
            first_rows, first_active = snapshots["target"][0][2]
            self.assertEqual(len(first_rows), 3)
            self.assertEqual(len(first_active), 3)
            final_rows, final_active = snapshots["target"][-1][2]
            self.assertEqual(len(final_rows), 5)
            self.assertNotEqual(first_active, final_active)
            fingerprint_index = STORED_FIELDS.index("input_fingerprint")
            self.assertEqual(final_rows[1][fingerprint_index],
                             first_rows[1][fingerprint_index])
            self.assertNotEqual(final_rows[3][fingerprint_index],
                                first_rows[0][fingerprint_index])
            self.assertNotEqual(final_rows[4][fingerprint_index],
                                first_rows[2][fingerprint_index])
            by_metric = {row[2]: row for row in final_rows[-2:]}
            self.assertEqual(set(by_metric), {"sleep.score", "sleep.debt_min"})
            supersedes_index = STORED_FIELDS.index("supersedes_result_id")
            self.assertEqual({row[supersedes_index] for row in final_rows[-2:]}, {1, 3})
            for row in final_rows:
                self.assertEqual(row[STORED_FIELDS.index("freshness_status")], FRESHNESS)
                self.assertTrue(row[STORED_FIELDS.index("input_fingerprint")])
                self.assertEqual(row[STORED_FIELDS.index("profile_revision")], revision)
                self.assertIsInstance(json.loads(row[STORED_FIELDS.index("metadata_json")]), dict)

    def test_default_target_full_persistence_path(self):
        self._run_case(None, 480.0)

    def test_effective_dated_target_full_persistence_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"schema_version": 1, "values": [
                {"field": "sleep_target_min", "value": 450,
                 "effective_from": (DAY - timedelta(days=13)).isoformat()}
            ]}), encoding="utf-8")
            self._run_case(path, 450.0)


class PackageArchitectureTests(unittest.TestCase):
    def test_pure_and_integration_dependencies_remain_separate(self):
        package = ROOT / "src" / "mi_fitness_whooping"
        pure = (package / "domain" / "sleep" / "contracts.py",
                package / "analytics" / "sleep" / "core.py")
        adapters = (package / "integration" / "sleep" / "input_adapter.py",
                    package / "integration" / "sleep" / "output_adapter.py")
        for path in (*pure, *adapters):
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
                imported = {alias.name for node in ast.walk(tree)
                            if isinstance(node, ast.Import) for alias in node.names}
                imported.update(node.module for node in ast.walk(tree)
                                if isinstance(node, ast.ImportFrom) and node.module)
                self.assertNotIn("sqlite3", imported)
                self.assertFalse(any(name.startswith("analytics.storage") for name in imported))
                self.assertNotIn(".now(", source)
                self.assertNotIn(".utcnow(", source)
                self.assertNotIn("calculate_sleep_day", source)
                self.assertFalse(any("__main__" in name for name in imported))
                if path in pure:
                    self.assertFalse(any(name == "analytics" or name.startswith("analytics.")
                                         for name in imported))
                    self.assertFalse(any("Legacy" in name for name in imported))
                else:
                    self.assertFalse(any(name.startswith("analytics.algorithms.sleep")
                                         for name in imported))
        self.assertFalse((ROOT / "src" / "analytics").exists())
        self.assertFalse((ROOT / "src" / "domain").exists())
        self.assertFalse((ROOT / "src" / "integration").exists())


if __name__ == "__main__":
    unittest.main()
