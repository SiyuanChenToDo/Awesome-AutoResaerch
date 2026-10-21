"""Regression tests for project scaffolding and local, non-executing readiness gates.

All protocol and run values below are isolated synthetic test fixtures, never
research observations. The evaluator fixture is hashed but never executed.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
SPEC = importlib.util.spec_from_file_location("research", REPO / "scripts/research.py")
research = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(research)


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "sage"
        self.root.mkdir()
        shutil.copytree(REPO / "templates", self.root / "templates")

    def create(self, slug="fixture-study", title="Synthetic fixture study"):
        return research.create_project(self.root, slug, title)

    def write_protocol(self, project, protocol):
        research.write_json(project / "preregistration.json", protocol)

    def ready_fixture(self):
        project = self.create()
        evaluator = project / "evaluation/score.py"
        evaluator.parent.mkdir()
        evaluator.write_text("# Synthetic test fixture. This file is never executed.\n", encoding="utf-8")
        (project / "src").mkdir()
        protocol = research.read_json(project / "preregistration.json")
        protocol.update({
            "status": "frozen",
            "baselines": [{"id": "baseline-fixture", "description": "Synthetic fixture", "config": "baseline.json"}],
            "seeds": [11, 22, 33],
            "ablations": [{"id": "ablation-fixture", "description": "Synthetic fixture", "config": "ablation.json"}],
            "stopping_rules": ["Stop at the synthetic test budget"],
        })
        protocol["primary_metric"] = {"name": "fixture_loss", "direction": "minimize", "unit": "absolute", "minimum_effect": 0.01, "aggregation": "paired mean"}
        protocol["data"] = {key: "synthetic fixture metadata" for key in protocol["data"]}
        protocol["candidate"] = {key: "synthetic fixture specification" for key in protocol["candidate"]}
        protocol["analysis"] = {key: "synthetic fixture analysis rule" for key in protocol["analysis"]}
        protocol["analysis"]["interval_level"] = 0.95
        protocol["budget"] = {"max_runs": 12, "max_wall_time_hours": 1, "max_accelerator_hours": 0, "max_api_cost": 0, "currency": "USD", "max_retries_per_run": 0, "accounting_policy": "All attempts count", "confirmation_reserve": "Three fixture attempts"}
        protocol["evaluation"] = {"evaluator_version": "fixture-v1", "evaluator_path": "evaluation/score.py", "evaluator_sha256": hashlib.sha256(evaluator.read_bytes()).hexdigest(), "protected_paths": ["evaluation"], "editable_paths": ["src"], "final_test_access_policy": "One synthetic fixture access", "max_final_test_accesses": 1, "holdout_custodian": "Synthetic reviewer", "baseline_fairness_rule": "Same synthetic fixture budget"}
        protocol["environment"] = {key: "synthetic fixture metadata" for key in protocol["environment"]}
        protocol["environment"]["network_policy"] = "deny_by_default"
        protocol["approval"] = {"decision_id": "TEST-ONLY", "reviewer": "Synthetic test fixture", "approved_at": "2026-10-17T00:00:00+00:00"}
        self.write_protocol(project, protocol)
        return project, protocol

    def test_init_creates_complete_draft_without_experiment_records(self):
        project = self.create()
        self.assertEqual(project, (self.root / "projects/fixture-study").resolve())
        for name in research.PROJECT_FILES + ["project.json"]:
            self.assertTrue((project / name).is_file(), name)
        metadata = research.read_json(project / "project.json")
        protocol = research.read_json(project / "preregistration.json")
        self.assertEqual(metadata["id"], "fixture-study")
        self.assertEqual(metadata["status"], "draft")
        self.assertEqual(protocol["project_id"], "fixture-study")
        self.assertEqual(protocol["status"], "draft")
        self.assertEqual((project / "runs.jsonl").read_bytes(), b"")
        self.assertEqual(research.check_project(project), [])
        for path in project.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("{{PROJECT_ID}}", text)
            self.assertNotIn("{{PROJECT_NAME}}", text)

    def test_init_does_not_modify_template_bytes(self):
        template = self.root / "templates/project"
        before = {p.relative_to(template): p.read_bytes() for p in template.rglob("*") if p.is_file()}
        self.create()
        after = {p.relative_to(template): p.read_bytes() for p in template.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_init_refuses_existing_project_without_overwrite(self):
        project = self.create()
        sentinel = project / "brief.md"
        sentinel.write_text("Existing researcher work must survive.\n", encoding="utf-8")
        before = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            self.create(title="Different title")
        after = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_init_handles_quote_and_unicode_title_without_json_injection(self):
        title = '研究 "title" with \\ paths'
        project = self.create(title=title)
        self.assertEqual(research.read_json(project / "project.json")["title"], title)
        self.assertEqual(research.check_project(project), [])

    def test_init_rejects_unsafe_slugs(self):
        for slug in ("", "../escape", "/absolute", "nested/study", "nested\\study", ".", "..", "UPPER", "with space", "-start", "end-", "two--dashes"):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                self.create(slug=slug)
        self.assertFalse((self.root / "projects").exists())

    def test_init_rejects_empty_or_invalid_titles_without_writes(self):
        for title in ("", "  \n ", "null\x00byte", None, 42):
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.create(title=title)
        self.assertFalse((self.root / "projects").exists())

    def test_init_rejects_project_directory_symlink_escape(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "projects").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.create()
        self.assertEqual(list(outside.iterdir()), [])

    def test_init_rejects_incomplete_templates_without_partial_project(self):
        (self.root / "templates/project/brief.md").unlink()
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse((self.root / "projects/fixture-study").exists())

    def test_init_rejects_symlink_in_templates(self):
        outside = self.base / "outside.txt"
        outside.write_text("Do not follow", encoding="utf-8")
        (self.root / "templates/project/untrusted.md").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.create()
        self.assertFalse((self.root / "projects/fixture-study").exists())

    def test_draft_structural_check_passes_but_ready_gate_fails(self):
        project = self.create()
        self.assertEqual(research.check_project(project), [])
        errors = research.check_project(project, ready=True)
        self.assertTrue(errors)
        self.assertTrue(any("not frozen" in e for e in errors))
        self.assertTrue(any("Unfilled protocol field" in e for e in errors))
        self.assertEqual((project / "runs.jsonl").read_bytes(), b"")

    def test_ready_gate_accepts_complete_fixture_without_running_evaluator(self):
        project, _ = self.ready_fixture()
        before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        self.assertEqual(research.check_project(project, ready=True), [])
        after = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((project / "runs.jsonl").read_bytes(), b"")

    def test_check_reports_missing_artifact_and_nonexistent_project(self):
        self.assertTrue(research.check_project(self.root / "not-created"))
        project = self.create()
        (project / "brief.md").unlink()
        self.assertTrue(any("brief.md" in e for e in research.check_project(project)))

    def test_check_rejects_malformed_metadata_without_crashing(self):
        project = self.create()
        for value in (None, [], "bad", {}, {"schema_version": 1, "id": None}, {"schema_version": 99, "id": "fixture-study"}):
            with self.subTest(value=value):
                research.write_json(project / "project.json", value)
                self.assertTrue(research.check_project(project))

    def test_check_rejects_malformed_protocol_without_crashing(self):
        project = self.create()
        for value in (None, [], "bad", {}, {"schema_version": 99}, {"schema_version": 1, "status": "invented"}):
            with self.subTest(value=value):
                self.write_protocol(project, value)
                self.assertTrue(research.check_project(project))

    def test_check_rejects_protocol_project_id_mismatch(self):
        project = self.create()
        protocol = research.read_json(project / "preregistration.json")
        protocol["project_id"] = "another-study"
        self.write_protocol(project, protocol)
        self.assertTrue(any("does not match" in e for e in research.check_project(project)))

    def test_check_rejects_protocol_path_escape(self):
        project = self.create()
        outside = self.base / "outside-protocol.json"
        shutil.copyfile(project / "preregistration.json", outside)
        metadata = research.read_json(project / "project.json")
        metadata["protocol_file"] = str(outside)
        research.write_json(project / "project.json", metadata)
        self.assertTrue(research.check_project(project))

    def test_ready_rejects_malformed_nested_protocol_groups(self):
        project, original = self.ready_fixture()
        for group in ("primary_metric", "analysis", "budget", "evaluation", "approval", "data", "candidate", "environment"):
            for value in (None, [], "invalid"):
                with self.subTest(group=group, value=value):
                    protocol = copy.deepcopy(original)
                    protocol[group] = value
                    self.write_protocol(project, protocol)
                    self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_invalid_or_nonfinite_numeric_fields(self):
        project, original = self.ready_fixture()
        fields = [("primary_metric", "minimum_effect"), ("analysis", "interval_level"), ("budget", "max_runs"), ("budget", "max_wall_time_hours"), ("budget", "max_api_cost")]
        for group, field in fields:
            for value in (float("nan"), float("inf"), -1, True, "10", None):
                with self.subTest(group=group, field=field, value=value):
                    protocol = copy.deepcopy(original)
                    protocol[group][field] = value
                    self.write_protocol(project, protocol)
                    self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_huge_integer_budget_without_crashing(self):
        project, protocol = self.ready_fixture()
        protocol["budget"]["max_runs"] = 10 ** 400
        self.write_protocol(project, protocol)
        self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_duplicate_invalid_seeds_and_fractional_run_budget(self):
        project, original = self.ready_fixture()
        for value in ([], [1, 1], [-1], [True], [1.5], "1", [[1]]):
            with self.subTest(seeds=value):
                protocol = copy.deepcopy(original)
                protocol["seeds"] = value
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))
        protocol = copy.deepcopy(original)
        protocol["budget"]["max_runs"] = 1.5
        self.write_protocol(project, protocol)
        self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_unapproved_or_unfrozen_protocol(self):
        project, original = self.ready_fixture()
        for status in ("draft", "superseded"):
            with self.subTest(status=status):
                protocol = copy.deepcopy(original)
                protocol["status"] = status
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))
        for value in (None, "TODO", "2026-10-17T00:00:00", "not-a-date"):
            with self.subTest(approved_at=value):
                protocol = copy.deepcopy(original)
                protocol["approval"]["approved_at"] = value
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_whitespace_and_padded_placeholders(self):
        project, original = self.ready_fixture()
        for value in ("   ", "\n\t", " TODO ", " tbd ", " UNKNOWN "):
            with self.subTest(value=value):
                protocol = copy.deepcopy(original)
                protocol["primary_metric"]["name"] = value
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_missing_or_modified_evaluator(self):
        project, _ = self.ready_fixture()
        evaluator = project / "evaluation/score.py"
        evaluator.write_text("# Modified fixture\n", encoding="utf-8")
        self.assertTrue(any("SHA256 mismatch" in e for e in research.check_project(project, ready=True)))
        evaluator.unlink()
        self.assertTrue(any("does not exist" in e for e in research.check_project(project, ready=True)))

    def test_ready_rejects_unprotected_evaluator_and_unsafe_paths(self):
        project, original = self.ready_fixture()
        for field, value in (("protected_paths", ["other"]), ("editable_paths", ["../outside"]), ("editable_paths", ["/"]), ("protected_paths", [])):
            with self.subTest(field=field, value=value):
                protocol = copy.deepcopy(original)
                protocol["evaluation"][field] = value
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_direct_and_normalized_editable_protected_overlap(self):
        project, original = self.ready_fixture()
        for path in ("evaluation", "evaluation/subdir", ".", "src/../evaluation"):
            with self.subTest(path=path):
                protocol = copy.deepcopy(original)
                protocol["evaluation"]["editable_paths"] = [path]
                self.write_protocol(project, protocol)
                self.assertTrue(research.check_project(project, ready=True))

    def test_ready_rejects_symlink_alias_of_protected_path(self):
        project, protocol = self.ready_fixture()
        (project / "editable-alias").symlink_to(project / "evaluation", target_is_directory=True)
        protocol["evaluation"]["editable_paths"] = ["editable-alias"]
        self.write_protocol(project, protocol)
        self.assertTrue(research.check_project(project, ready=True))

    def test_check_rejects_malformed_run_json_and_nonobject_lines(self):
        project = self.create()
        for text in ("{invalid\n", "[]\n", "null\n", '"wrong"\n'):
            with self.subTest(text=text):
                (project / "runs.jsonl").write_text(text, encoding="utf-8")
                self.assertTrue(research.check_project(project))

    def test_run_gate_rejects_duplicate_ids_project_mismatch_and_fake_planned_metrics(self):
        project = self.create()
        original = {"run_id": "synthetic-001", "project_id": "fixture-study", "status": "planned", "metrics": None}
        (project / "runs.jsonl").write_text(json.dumps(original) + "\n", encoding="utf-8")
        self.assertEqual(research.check_project(project), [])
        for changes in ({"run_id": None}, {"project_id": "wrong"}, {"status": "invented"}, {"metrics": {"fake": 0.9}}, {"metrics": {"fake": float("nan")}}):
            with self.subTest(changes=changes):
                record = dict(original, **changes)
                (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                self.assertTrue(research.check_project(project))
        (project / "runs.jsonl").write_text((json.dumps(original) + "\n") * 2, encoding="utf-8")
        self.assertTrue(any("duplicate" in e for e in research.check_project(project)))

    def test_run_gate_rejects_completed_without_evidence_and_failed_without_reason(self):
        project = self.create()
        for status in ("completed", "failed", "invalid"):
            with self.subTest(status=status):
                record = {"run_id": "synthetic-001", "project_id": "fixture-study", "status": status, "metrics": None}
                (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                self.assertTrue(research.check_project(project))

    def test_run_gate_accepts_documented_timeout_with_failure_reason(self):
        project = self.create()
        record = {"run_id": "synthetic-timeout", "project_id": "fixture-study", "status": "timeout", "metrics": None, "failure_reason": "Synthetic timeout fixture, not an actual experiment", "started_at": "2026-10-17T00:00:00+00:00", "ended_at": "2026-10-17T00:00:10+00:00", "cost": {"wall_time_seconds": 10, "accelerator_seconds": 0, "api_cost": 0, "currency": "USD"}}
        (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        self.assertEqual(research.check_project(project), [])

    def completed_fixture_record(self, project):
        """Build a schema fixture, not a claimed experimental observation."""
        artifact = project / "synthetic-result.json"
        artifact.write_text('{"fixture_only": true, "metric": 0.5}\n', encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return {
            "run_id": "synthetic-completed", "project_id": "fixture-study",
            "status": "completed", "exit_code": 0, "metrics": {"fixture_metric": 0.5},
            "protocol_sha256": hashlib.sha256((project / "preregistration.json").read_bytes()).hexdigest(),
            "evaluator_sha256": digest, "config_sha256": digest,
            "code_commit": "synthetic-fixture", "data_fingerprint": "synthetic-fixture",
            "environment_manifest": "synthetic-fixture", "artifacts": [{"path": artifact.name, "sha256": digest}],
            "started_at": "2026-10-17T00:00:00+00:00", "ended_at": "2026-10-17T00:00:10+00:00",
            "cost": {"wall_time_seconds": 10, "accelerator_seconds": 0, "api_cost": 0, "currency": "USD"},
            "notes": "Synthetic schema test fixture. No experiment occurred.",
        }

    def test_completed_run_accepts_well_formed_synthetic_schema_fixture(self):
        project = self.create()
        record = self.completed_fixture_record(project)
        (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        self.assertEqual(research.check_project(project), [])

    def test_completed_run_rejects_nonnumeric_metrics_and_boolean_exit_code(self):
        project = self.create()
        original = self.completed_fixture_record(project)
        for metric in (True, "0.5", None, [], {}, float("nan"), float("inf")):
            with self.subTest(metric=metric):
                record = copy.deepcopy(original)
                record["metrics"] = {"fixture_metric": metric}
                (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                self.assertTrue(research.check_project(project))
        record = copy.deepcopy(original)
        record["exit_code"] = False
        (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        self.assertTrue(research.check_project(project))

    def test_terminal_runs_require_aware_ordered_timestamps(self):
        project = self.create()
        original = self.completed_fixture_record(project)
        cases = [
            ("started_at", None), ("ended_at", None),
            ("started_at", "2026-10-17T00:00:00"),
            ("ended_at", "2026-10-17T00:00:10"),
            ("ended_at", "2026-10-16T00:00:00+00:00"),
            ("started_at", "not-a-timestamp"),
        ]
        for status in ("completed", "failed", "timeout", "cancelled", "invalid"):
            for field, value in cases:
                with self.subTest(status=status, field=field, value=value):
                    record = copy.deepcopy(original)
                    record.update({"status": status, "failure_reason": "Synthetic failure fixture", field: value})
                    (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                    self.assertTrue(research.check_project(project))

    def test_terminal_runs_require_finite_nonnegative_costs_and_currency(self):
        project = self.create()
        original = self.completed_fixture_record(project)
        for field in ("wall_time_seconds", "accelerator_seconds", "api_cost"):
            for value in (-1, None, True, "10", float("inf"), float("nan")):
                with self.subTest(field=field, value=value):
                    record = copy.deepcopy(original)
                    record["cost"][field] = value
                    (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                    self.assertTrue(research.check_project(project))
        for cost in (None, {}, {"wall_time_seconds": 0, "accelerator_seconds": 0, "api_cost": 0, "currency": ""}):
            with self.subTest(cost=cost):
                record = copy.deepcopy(original)
                record["cost"] = cost
                (project / "runs.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
                self.assertTrue(research.check_project(project))

    def test_cli_init_draft_check_and_ready_failure_are_honest(self):
        command = [sys.executable, str(REPO / "scripts/research.py"), "--root", str(self.root)]
        initialized = subprocess.run(command + ["init", "cli-fixture", "--title", "CLI fixture"], capture_output=True, text=True, timeout=10)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertIn("No models, APIs or experiments were run", initialized.stdout)
        checked = subprocess.run(command + ["check-project", "projects/cli-fixture"], capture_output=True, text=True, timeout=10)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        blocked = subprocess.run(command + ["check-project", "projects/cli-fixture", "--ready"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("not frozen", blocked.stderr)
        repeated = subprocess.run(command + ["init", "cli-fixture"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertNotIn("Traceback", repeated.stderr)
        self.assertEqual((self.root / "projects/cli-fixture/runs.jsonl").read_bytes(), b"")


class NumericHelperTests(unittest.TestCase):
    def test_numeric_rejects_bool_nan_and_infinity(self):
        for value in (True, False, float("nan"), float("inf"), float("-inf"), "1", None):
            with self.subTest(value=value):
                self.assertFalse(research.numeric(value))
        for value in (0, 1, -1, 1.5):
            with self.subTest(value=value):
                self.assertTrue(research.numeric(value))

    def test_finite_tree_finds_nested_nonfinite_values(self):
        self.assertTrue(research.finite_tree({"nested": [0, 1.5, None]}))
        self.assertFalse(research.finite_tree({"nested": [{"bad": float("nan")}]}))
        self.assertFalse(research.finite_tree([{"bad": float("inf")}]))


if __name__ == "__main__":
    unittest.main()
