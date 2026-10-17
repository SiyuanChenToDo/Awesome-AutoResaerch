#!/usr/bin/env python3
"""Create local draft research projects and check their artifacts. Never runs experiments."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

from catalog import ROOT, SLUG, read_json, safe_relative, write_json

PROJECT_FILES = ["brief.md", "literature.md", "hypotheses.md", "preregistration.json", "benchmark.md", "decisions.md", "claims.md", "runs.jsonl", "reflection.md", "memory.md", "reproducibility.md"]


def create_project(root: Path, slug: str, title: str):
    root = root.resolve()
    if not SLUG.fullmatch(slug):
        raise ValueError("Project id must be a lowercase hyphenated slug, with no paths")
    if not isinstance(title, str) or not title.strip() or "\x00" in title:
        raise ValueError("Project title must be nonempty text")
    destination = safe_relative(root, f"projects/{slug}")
    if destination.exists():
        raise ValueError("Project already exists; refusing to overwrite")
    source = root / "templates/project"
    if not all((source / path).is_file() for path in PROJECT_FILES):
        raise ValueError("Project templates are incomplete")
    # Never follow a symlink introduced into a template tree.
    if any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("Project template symlinks are not permitted")
    shutil.copytree(source, destination)
    for path in destination.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            # JSON fields are updated structurally below; avoid quote injection in titles.
            if path.suffix == ".json":
                value = json.loads(text)
                value["project_id"] = slug
                write_json(path, value)
            else:
                path.write_text(text.replace("{{PROJECT_ID}}", slug).replace("{{PROJECT_NAME}}", title.strip()), encoding="utf-8")
    write_json(destination / "project.json", {"schema_version": 1, "id": slug, "title": title.strip(), "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(), "protocol_file": "preregistration.json"})
    return destination


def has_value(value):
    if isinstance(value, str):
        value = value.strip()
        return bool(value) and "{{" not in value and value.lower() not in {"todo", "tbd", "unknown"}
    return value is not None and value != [] and value != {}


def numeric(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def protocol_checks(protocol: dict, ready: bool):
    errors = []
    if not isinstance(protocol, dict):
        return ["Protocol must be a JSON object"]
    if protocol.get("schema_version") != 1:
        errors.append("Protocol schema_version must be 1")
    if protocol.get("status") not in {"draft", "frozen", "superseded"}:
        errors.append("Protocol status must be draft, frozen or superseded")
    if not ready:
        return errors
    if protocol.get("status") != "frozen":
        errors.append("Protocol is not frozen")
    required = {
        "primary_metric": ["name", "direction", "unit", "minimum_effect", "aggregation"],
        "data": ["dataset_id", "version", "fingerprint", "split_policy", "train_manifest", "development_manifest", "final_test_manifest", "license_review", "contamination_check"],
        "candidate": ["description", "change_scope", "search_space", "selection_rule"],
        "analysis": ["independent_unit", "effect_estimator", "interval_method", "interval_level", "multiple_comparisons", "missing_and_failed_runs", "falsification_rule"],
        "budget": ["max_runs", "max_wall_time_hours", "max_accelerator_hours", "max_api_cost", "currency", "max_retries_per_run", "accounting_policy", "confirmation_reserve"],
        "evaluation": ["evaluator_version", "evaluator_path", "evaluator_sha256", "protected_paths", "editable_paths", "final_test_access_policy", "max_final_test_accesses", "holdout_custodian", "baseline_fairness_rule"],
        "environment": ["code_commit", "dependency_lock", "hardware", "model_or_api_version", "network_policy"],
        "approval": ["decision_id", "reviewer", "approved_at"],
    }
    for group, fields in required.items():
        value = protocol.get(group)
        if not isinstance(value, dict):
            errors.append(f"Missing protocol group: {group}")
            continue
        for field in fields:
            if not has_value(value.get(field)):
                errors.append(f"Unfilled protocol field: {group}.{field}")
    for field in ["project_id", "protocol_id", "hypothesis_ids", "baselines", "seeds", "ablations", "stopping_rules"]:
        if not has_value(protocol.get(field)):
            errors.append(f"Unfilled protocol field: {field}")
    if protocol.get("primary_metric", {}).get("direction") not in {"minimize", "maximize"}:
        errors.append("primary_metric.direction must be minimize or maximize")
    effect = protocol.get("primary_metric", {}).get("minimum_effect")
    if not numeric(effect) or effect < 0:
        errors.append("minimum_effect must be finite and nonnegative")
    level = protocol.get("analysis", {}).get("interval_level")
    if not numeric(level) or not 0 < level < 1:
        errors.append("analysis.interval_level must be between 0 and 1")
    seeds = protocol.get("seeds")
    if not isinstance(seeds, list) or not seeds or any(type(seed) is not int or seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
        errors.append("seeds must be nonempty, distinct nonnegative integers")
    budget = protocol.get("budget", {})
    for field in ["max_runs", "max_wall_time_hours", "max_accelerator_hours", "max_api_cost", "max_retries_per_run"]:
        value = budget.get(field)
        minimum = 0 if field in {"max_accelerator_hours", "max_api_cost", "max_retries_per_run"} else 1e-15
        if not numeric(value) or value < minimum:
            errors.append(f"Invalid nonnegative/positive budget: {field}")
    for field in ["max_runs", "max_retries_per_run"]:
        if type(budget.get(field)) is not int:
            errors.append(f"budget.{field} must be an integer")
    evaluation = protocol.get("evaluation", {})
    if type(evaluation.get("max_final_test_accesses")) is not int or evaluation["max_final_test_accesses"] < 1:
        errors.append("max_final_test_accesses must be a positive integer")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evaluation.get("evaluator_sha256", ""))):
        errors.append("evaluator_sha256 must be a SHA256 hex digest")
    for field in ["protected_paths", "editable_paths"]:
        if not isinstance(evaluation.get(field), list) or not evaluation[field] or any(not isinstance(p, str) or not p for p in evaluation[field]):
            errors.append(f"evaluation.{field} must be a nonempty string list")
    protected, editable = evaluation.get("protected_paths", []), evaluation.get("editable_paths", [])
    if isinstance(protected, list) and isinstance(editable, list):
        for protected_path in protected:
            for editable_path in editable:
                if isinstance(protected_path, str) and isinstance(editable_path, str):
                    a, b = Path(protected_path), Path(editable_path)
                    if a == b or a in b.parents or b in a.parents:
                        errors.append("Protected and editable paths overlap")
    try:
        stamp = datetime.fromisoformat(protocol.get("approval", {}).get("approved_at", ""))
        if stamp.tzinfo is None:
            errors.append("approval.approved_at requires a timezone")
    except (ValueError, TypeError):
        errors.append("approval.approved_at must be an ISO timestamp with timezone")
    return errors


def finite_tree(value):
    if isinstance(value, float): return math.isfinite(value)
    if isinstance(value, dict): return all(finite_tree(v) for v in value.values())
    if isinstance(value, list): return all(finite_tree(v) for v in value)
    return True


def check_project(project: Path, ready: bool = False):
    errors = []
    if not project.is_dir():
        return ["Project directory not found"]
    for name in PROJECT_FILES + ["project.json"]:
        if not (project / name).is_file():
            errors.append(f"Missing project artifact: {name}")
    if errors: return errors
    try:
        metadata = read_json(project / "project.json")
        if metadata.get("schema_version") != 1 or not SLUG.fullmatch(metadata.get("id", "")):
            errors.append("Invalid project metadata")
        protocol_path = safe_relative(project, metadata["protocol_file"])
        protocol = read_json(protocol_path)
        if protocol.get("project_id") != metadata.get("id"):
            errors.append("Protocol project_id does not match project.json")
        errors.extend(protocol_checks(protocol, ready))
        if ready:
            evaluation = protocol.get("evaluation", {})
            evaluator_name = evaluation.get("evaluator_path")
            if isinstance(evaluator_name, str) and evaluator_name:
                evaluator = safe_relative(project, evaluator_name)
                if not evaluator.is_file():
                    errors.append("Evaluator file does not exist")
                elif hashlib.sha256(evaluator.read_bytes()).hexdigest() != evaluation.get("evaluator_sha256"):
                    errors.append("Evaluator SHA256 mismatch")
                protected = [safe_relative(project, path) for path in evaluation.get("protected_paths", [])]
                if not any(evaluator == p or p in evaluator.parents for p in protected):
                    errors.append("Evaluator is not inside a protected path")
            protected_paths = [safe_relative(project, path) for path in evaluation.get("protected_paths", [])]
            editable_paths = [safe_relative(project, path) for path in evaluation.get("editable_paths", [])]
            for protected in protected_paths:
                for editable in editable_paths:
                    if protected == editable or protected in editable.parents or editable in protected.parents:
                        errors.append("Resolved protected and editable paths overlap")
        seen = set()
        for number, line in enumerate((project / "runs.jsonl").read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip(): continue
            record = json.loads(line)
            if not isinstance(record, dict) or not finite_tree(record):
                errors.append(f"Run line {number}: invalid record or NaN/Infinity")
                continue
            run_id = record.get("run_id")
            if not isinstance(run_id, str) or not run_id or run_id in seen:
                errors.append(f"Run line {number}: missing/duplicate run_id")
            seen.add(run_id)
            status = record.get("status")
            if status not in {"planned", "running", "completed", "failed", "timeout", "cancelled", "invalid"}:
                errors.append(f"Run line {number}: unknown status")
            if record.get("project_id") != metadata["id"]:
                errors.append(f"Run line {number}: mismatched project_id")
            if status in {"planned", "running"} and record.get("metrics") not in (None, {}):
                errors.append(f"Run line {number}: unfinished run cannot support result metrics")
            if status == "completed":
                if type(record.get("exit_code")) is not int or record.get("exit_code") != 0 or not isinstance(record.get("metrics"), dict) or not record["metrics"]:
                    errors.append(f"Run line {number}: completed run needs exit_code=0 and metrics")
                elif any(not isinstance(key, str) or not numeric(value) for key, value in record["metrics"].items()):
                    errors.append(f"Run line {number}: metrics must be finite numeric scalars, not bool/string")
                for field in ["protocol_sha256", "evaluator_sha256", "config_sha256"]:
                    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(field, ""))):
                        errors.append(f"Run line {number}: missing {field}")
                for field in ["code_commit", "data_fingerprint", "environment_manifest", "started_at", "ended_at", "artifacts"]:
                    if not has_value(record.get(field)):
                        errors.append(f"Run line {number}: missing {field}")
            if status in {"completed", "failed", "timeout", "cancelled", "invalid"}:
                try:
                    started = datetime.fromisoformat(record.get("started_at", ""))
                    ended = datetime.fromisoformat(record.get("ended_at", ""))
                    if started.tzinfo is None or ended.tzinfo is None or ended < started:
                        errors.append(f"Run line {number}: invalid timestamp timezone or order")
                except (ValueError, TypeError):
                    errors.append(f"Run line {number}: timestamps must be ISO dates with timezone")
                cost = record.get("cost")
                if not isinstance(cost, dict):
                    errors.append(f"Run line {number}: missing cost record")
                else:
                    for field in ["wall_time_seconds", "accelerator_seconds", "api_cost"]:
                        if not numeric(cost.get(field)) or cost[field] < 0:
                            errors.append(f"Run line {number}: {field} must be finite and nonnegative")
                    if not isinstance(cost.get("currency"), str) or not cost["currency"]:
                        errors.append(f"Run line {number}: cost currency is required")
            if status in {"failed", "timeout", "invalid"} and not has_value(record.get("failure_reason")):
                errors.append(f"Run line {number}: missing failure_reason")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        errors.append(f"Invalid project data: {error}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    initializer = sub.add_parser("init")
    initializer.add_argument("slug")
    initializer.add_argument("--title")
    checker = sub.add_parser("check-project")
    checker.add_argument("path", type=Path)
    checker.add_argument("--ready", action="store_true", help="Check frozen protocol fields and evaluator hash; does not grant execution approval")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "init":
            destination = create_project(root, args.slug, args.title or args.slug)
            print(f"Created draft project: {destination}\nNo models, APIs or experiments were run.")
        else:
            path = args.path if args.path.is_absolute() else root / args.path
            errors = check_project(path, args.ready)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print("Project structural checks passed. Scientific validity, actual approval and execution isolation are not verified.")
        return 0
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
