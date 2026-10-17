#!/usr/bin/env python3
"""Inspect or prepare CoI-Agent source locally; no live workflow execution."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.orchestration.coi_agent import prepare_runtime, verify_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="Verify the pinned source hashes and report status")
    prepare = sub.add_parser("prepare", help="Apply reviewed patches to a new ignored private copy")
    prepare.add_argument("--destination", type=Path, default=Path("projects/coi-agent-runtime"))
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            print(json.dumps(verify_snapshot(), indent=2))
        else:
            destination = prepare_runtime(args.destination)
            print(f"Prepared source only: {destination}")
            print("No dependencies installed, no model/API calls, no experiments executed.")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
