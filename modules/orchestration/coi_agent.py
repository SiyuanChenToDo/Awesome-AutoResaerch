"""Verify and prepare the pinned CoI-Agent source without importing or running it.

This module is our maintained adapter. Upstream stays byte-for-byte unchanged.
Preparation applies reviewed local patches to an ignored private working copy.
It does not install dependencies, load credentials, contact a model, or run code.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "ac94317ff2d1997f362747edc2c9e5f0fdc9c450"


def _metadata(root: Path):
    base = root / "third_party/coi_agent"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    patches = json.loads((root / "modules/orchestration/coi_patches.json").read_text(encoding="utf-8"))
    if manifest["commit"] != PIN or patches["upstream_commit"] != PIN:
        raise ValueError("CoI-Agent pin mismatch; review source and patches together")
    return base, manifest, patches


def verify_snapshot(root: Path = ROOT) -> dict:
    """Check the complete included file set and both upstream and local hashes."""
    base, manifest, patches = _metadata(root)
    upstream = base / "upstream"
    expected = {entry["path"] for entry in manifest["files"]}
    actual = {str(path.relative_to(upstream)) for path in upstream.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError(f"CoI-Agent file set changed: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    for entry in manifest["files"]:
        path = upstream / entry["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(upstream.resolve()):
            raise ValueError(f"Invalid upstream source path: {entry['path']}")
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if (len(data) != entry["size_bytes"] or blob != entry["git_blob_sha"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"]):
            raise ValueError(f"CoI-Agent source changed: {entry['path']}")
    return {"project": manifest["project"], "commit": PIN, "license": manifest["license"],
            "source_files": len(expected), "local_patches": len(patches["patches"]),
            "runtime_verification_status": "not_run", "experiments_executed": False}


def patched_sources(root: Path = ROOT) -> dict[str, str]:
    """Return a patched text view, failing closed if any patch precondition drifts."""
    verify_snapshot(root)
    base, manifest, patch_set = _metadata(root)
    sources = {entry["path"]: (base / "upstream" / entry["path"]).read_text(encoding="utf-8")
               for entry in manifest["files"]}
    modified = set()
    for patch in patch_set["patches"]:
        text = sources[patch["path"]]
        if not patch["old"] or text.count(patch["old"]) != 1:
            raise ValueError(f"Patch does not apply exactly once: {patch['id']}")
        sources[patch["path"]] = text.replace(patch["old"], patch["new"], 1)
        modified.add(patch["path"])
    for path in modified:
        sources[path] = ("# MODIFIED by SAGE (2026-10-17).\n"
                         "# See LOCAL_CHANGES.json; upstream source remains Apache-2.0.\n" + sources[path])
    return sources


def prepare_runtime(destination: Path, root: Path = ROOT) -> Path:
    """Create a new private source tree. Refuse overwrites or paths outside projects/."""
    root = root.resolve()
    private_root = root / "projects"
    requested = destination if destination.is_absolute() else root / destination
    target = requested.resolve()
    if private_root.is_symlink() or target == private_root or not target.is_relative_to(private_root):
        raise ValueError("Destination must be a new private subdirectory of projects/")
    if target.exists() or requested.is_symlink():
        raise ValueError("Destination already exists; choose a new directory")
    sources = patched_sources(root)
    _, _, patches = _metadata(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".coi-prepare-", dir=target.parent))
    try:
        for name, text in sources.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        (staging / "LOCAL_CHANGES.json").write_text(json.dumps(patches, indent=2) + "\n", encoding="utf-8")
        (staging / "PROVENANCE.json").write_bytes((root / "third_party/coi_agent/manifest.json").read_bytes())
        # Claim the destination exclusively before moving files into it.
        target.mkdir()
        for path in staging.iterdir():
            shutil.move(str(path), str(target / path.name))
    finally:
        shutil.rmtree(staging)
    return target
