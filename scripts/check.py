#!/usr/bin/env python3
"""Run all SAGE offline checks, including the real controller with fake providers."""
from pathlib import Path
import subprocess
import sys
import tempfile

from catalog import ROOT, build_records, check_links, read_json, render_views, validate_catalog, repository_files
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
            # Generated text views may be checked out with CRLF on Windows.
            # Source archives retain their separate byte-exact hash checks.
            if not target.exists() or path.read_text(encoding='utf-8') != target.read_text(encoding='utf-8'):
                errors.append(f"Stale generated view: catalog/{path.name}; run catalog.py build")
    for project in sorted((ROOT / "examples").glob("*/project.json")):
        errors.extend(f"{project.parent.name}: {error}" for error in check_project(project.parent))
    for path in repository_files(ROOT, '*.json'):
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
    print("All SAGE offline checks passed. Synthetic pipelines, mock provider/Docker adapters and explicitly allowlisted reviewed-script subprocess tests were exercised; no live API calls, real Docker validation or scientific experiments were performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
