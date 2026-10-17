#!/usr/bin/env python3
"""Run every offline scaffold check, without model APIs or full external workflow execution."""
from pathlib import Path
import subprocess
import sys
import tempfile

from catalog import ROOT, build_records, check_links, read_json, render_views, validate_catalog
from research import check_project, create_project


def main():
    errors = validate_catalog(ROOT) + check_links(ROOT)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    # Ensure checked-in views are deterministic; do not repair them during validation.
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        (temporary / "catalog").mkdir()
        render_views(temporary, build_records(ROOT))
        for path in (temporary / "catalog").iterdir():
            target = ROOT / "catalog" / path.name
            if not target.exists() or path.read_bytes() != target.read_bytes():
                errors.append(f"Stale generated view: catalog/{path.name}; run catalog.py build")
    for project in sorted((ROOT / "examples").glob("*/project.json")):
        errors.extend(f"{project.parent.name}: {error}" for error in check_project(project.parent))
    for path in ROOT.rglob("*.json"):
        if any(part in {"projects", ".git", "__pycache__"} for part in path.relative_to(ROOT).parts):
            continue
        try:
            read_json(path)
        except (OSError, ValueError) as error:
            errors.append(f"Invalid JSON {path.relative_to(ROOT)}: {error}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=False)
    if completed.returncode:
        return completed.returncode
    print("All offline scaffold checks passed. CoI source patches were unit-tested with local fakes; no complete upstream workflow, network verification, model API or experiments were run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
