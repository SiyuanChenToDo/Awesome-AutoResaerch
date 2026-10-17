#!/usr/bin/env python3
"""Offline, standard-library catalog import, search, render and integrity checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
STAGES = {"discovery", "experiment_design", "orchestration", "execution", "scope", "literature", "ideation", "implementation", "experimentation", "evaluation", "writing", "review", "memory"}
CATEGORIES = {"foundation", "experiment-loop", "end-to-end", "domain-science", "literature", "infrastructure", "skills-writing", "hypothesis", "benchmark", "survey", "risk-governance", "curated-list", "paper-system", "industry", "community", "other"}
SECTION_CATEGORY = {"2.1": "foundation", "2.2": "experiment-loop", "2.3": "end-to-end", "2.4": "domain-science", "2.5": "literature", "2.6": "curated-list", "2.7": "infrastructure", "2.8": "skills-writing", "2.9": "end-to-end", "2.10": "hypothesis", "2.11": "domain-science", "2.12": "curated-list", "3.1": "foundation", "3.2": "paper-system", "3.3": "benchmark", "3.4": "hypothesis", "3.5": "paper-system", "3.6": "survey", "3.7": "risk-governance", "5": "industry", "6": "community"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Path must be a nonempty relative path")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes workspace: {relative}")
    return resolved


def canonicalize(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"Not a public HTTP(S) URL: {url}")
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if host == "github.com":
        pieces = path.strip("/").split("/")
        # A repository, branch, file or subdirectory all identify the same tool.
        if len(pieces) >= 2 and pieces[0].lower() not in {"search", "topics", "settings", "features", "orgs"}:
            owner, name = pieces[:2]
            name = name.removesuffix(".git")
            canonical = f"https://github.com/{owner.lower()}/{name.lower()}"
            return canonical, "tool", "github-" + owner.lower() + "-" + name.lower().replace("_", "-") + "-" + hashlib.sha256(canonical.encode()).hexdigest()[:12]
    if host in {"arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?", path)
        if match:
            identifier = match.group(1)
            return f"https://arxiv.org/abs/{identifier}", "paper", "arxiv-" + identifier.replace(".", "-")
    canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))
    kind = "paper" if host in {"doi.org", "www.nature.com", "nature.com", "ieeexplore.ieee.org"} else "resource"
    return canonical, kind, kind + "-" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def extract_records(text: str, source: dict):
    records = {}
    section = "preamble"
    for number, line in enumerate(text.splitlines(), 1):
        if re.match(r"^#{1,6} ", line):
            section = re.sub(r"^#+\s+", "", line)
        section_number = re.match(r"(\d+(?:\.\d+)?)", section)
        category = SECTION_CATEGORY.get(section_number.group(1), "other") if section_number else "other"
        for label, url in LINK.findall(line):
            if not url.startswith(("http://", "https://")):
                continue
            canonical, kind, identifier = canonicalize(url)
            display_title = label
            if line.startswith("|") and category in {"benchmark", "industry", "community"}:
                first_cell = line.split("|")[1].strip()
                if first_cell and "[" not in first_cell and label.startswith(("arXiv", "http", "ICLR", "Nature", "链接")):
                    display_title = first_cell
            record = records.setdefault(canonical, {"id": identifier, "kind": kind, "title": display_title, "url": canonical, "categories": [], "source_mentions": [], "verification_status": "source_imported", "integration_status": "not_integrated"})
            # Prefer a title to generic arXiv/URL labels, without inventing metadata.
            if (record["title"].startswith(("arXiv", "http", "链接")) and not display_title.startswith(("arXiv", "http", "链接"))):
                record["title"] = display_title
            if category not in record["categories"]:
                record["categories"].append(category)
            record["source_mentions"].append({"source_id": source["id"], "path": source["path"], "line": number, "section": section, "label": label, "original_url": url, "source_excerpt": line})
    return list(records.values())


def build_records(root: Path):
    manifest = read_json(root / "sources/manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("sources"), list) or not manifest["sources"]:
        raise ValueError("Manifest requires schema_version=1 and a nonempty sources list")
    merged = {}
    source_ids = set()
    for source in manifest["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not SLUG.fullmatch(source["id"]):
            raise ValueError("Invalid source id")
        if source["id"] in source_ids:
            raise ValueError("Duplicate source id")
        source_ids.add(source["id"])
        date.fromisoformat(source["snapshot_date"])
        if not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("Invalid source digest")
        source_path = safe_relative(root, source["path"])
        if digest(source_path) != source["sha256"]:
            raise ValueError(f"Source digest mismatch: {source['path']}")
        for record in extract_records(source_path.read_text(encoding="utf-8"), source):
            if record["url"] not in merged:
                merged[record["url"]] = record
            else:
                old = merged[record["url"]]
                old["categories"] = sorted(set(old["categories"] + record["categories"]))
                old["source_mentions"].extend(record["source_mentions"])
    for record in merged.values():
        record["categories"].sort()
    return {"schema_version": 1, "records": sorted(merged.values(), key=lambda r: (r["kind"], r["id"]))}


def import_snapshot(root: Path, source_path: Path, source_id: str, snapshot_date: str):
    if not SLUG.fullmatch(source_id):
        raise ValueError("Source id must be a lowercase hyphenated slug")
    date.fromisoformat(snapshot_date)
    content = source_path.read_bytes()
    content.decode("utf-8")
    manifest_path = root / "sources/manifest.json"
    if manifest_path.exists():
        try:
            build_records(root)  # Validate existing metadata and archives before any writes.
        except OSError as error:
            raise ValueError(f"Existing source archive is unavailable: {error}") from error
    manifest = read_json(manifest_path) if manifest_path.exists() else {"schema_version": 1, "sources": []}
    target = safe_relative(root, f"sources/snapshots/{source_id}.md")
    sha = hashlib.sha256(content).hexdigest()
    existing = next((s for s in manifest["sources"] if s["id"] == source_id), None)
    if existing:
        if existing["sha256"] != sha or existing["snapshot_date"] != snapshot_date:
            raise ValueError("Source id already exists with different bytes/date; use a new snapshot id")
        if not target.exists() or digest(target) != sha:
            raise ValueError("Archived source was modified or is missing")
        return False
    if target.exists() and digest(target) != sha:
        raise ValueError("Refusing to overwrite an existing source archive")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    manifest["sources"].append({"id": source_id, "snapshot_date": snapshot_date, "path": target.relative_to(root.resolve()).as_posix(), "sha256": sha, "original_filename": source_path.name, "verification_scope": "Imported bytes only; source claims are not independently verified"})
    write_json(manifest_path, manifest)
    return True


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")


def render_views(root: Path, data: dict):
    records = data["records"]
    groups = {"tools": [r for r in records if r["kind"] == "tool"], "papers": [r for r in records if r["kind"] == "paper"], "benchmarks": [r for r in records if "benchmark" in r["categories"]], "resources": [r for r in records if r["kind"] == "resource"]}
    for name, selected in groups.items():
        lines = [f"# {name} · 来源索引", "", "<!-- Generated by scripts/catalog.py build; do not edit. -->", "", f"共 {len(selected)} 条。仅表示来源清单出现过；分类来自原文分节，不代表独立核验、安装或实测。", "", "当前抽查与纠错见 [verification.json](verification.json)，工作流选型见 [reading-path](../docs/reading-path.md)。", "", "| 条目 | 分类 | 来源定位 |", "|---|---|---|"]
        for record in selected:
            mention = record["source_mentions"][0]
            lines.append(f"| [{escape_cell(record['title'])}]({record['url']}) | {', '.join(record['categories'])} | [{mention['source_id']}:L{mention['line']}](../{mention['path']}#L{mention['line']}) |")
        (root / "catalog" / (name + ".md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = {name: len(values) for name, values in groups.items()}
    counts["total_unique_urls"] = len(records)
    counts["arxiv_ids"] = sum(r["id"].startswith("arxiv-") for r in records)
    write_json(root / "catalog/stats.json", counts)


def validate_catalog(root: Path):
    errors = []
    try:
        data = read_json(root / "catalog/records.json")
        expected = build_records(root)
        if data != expected:
            errors.append("Catalog differs from source extraction; run catalog.py build, do not edit generated records")
        records = data["records"]
        if data["schema_version"] != 1 or not isinstance(records, list):
            raise ValueError("Unsupported catalog schema")
        ids, urls = set(), set()
        for record in records:
            identifier = record["id"]
            if identifier in ids or record["url"] in urls:
                errors.append(f"Duplicate id/url: {identifier}")
            ids.add(identifier); urls.add(record["url"])
            url, kind, correct_id = canonicalize(record["url"])
            if url != record["url"] or kind != record["kind"] or correct_id != identifier:
                errors.append(f"Noncanonical metadata: {identifier}")
            if not record["title"] or not record["source_mentions"]:
                errors.append(f"Missing title or provenance: {identifier}")
            if not set(record["categories"]) <= CATEGORIES:
                errors.append(f"Unknown category: {identifier}")
            if record["verification_status"] != "source_imported" or record["integration_status"] != "not_integrated":
                errors.append(f"Generated source record must not claim verification/integration: {identifier}")
            for mention in record["source_mentions"]:
                lines = safe_relative(root, mention["path"]).read_text(encoding="utf-8").splitlines()
                line = mention["line"]
                if not isinstance(line, int) or line < 1 or line > len(lines) or mention["original_url"] not in lines[line - 1]:
                    errors.append(f"Invalid source location: {identifier}")
        verification_path = root / "catalog/verification.json"
        if verification_path.exists():
            verification = read_json(verification_path)
            for check in verification["checks"]:
                canonicalize(check["url"])
                date.fromisoformat(check["checked_at"])
                if check["runtime_tested"] is not False:
                    errors.append("Initial scaffold may not claim runtime verification")
                if not check.get("evidence_urls") or not check.get("limitations"):
                    errors.append(f"Verification lacks evidence or limitations: {check['url']}")
        curation_path = root / "catalog/curation.json"
        if curation_path.exists():
            for entry in read_json(curation_path)["entries"]:
                if entry["id"] not in ids:
                    errors.append(f"Unknown curated id: {entry['id']}")
                if not set(entry["stages"]) <= STAGES:
                    errors.append(f"Unknown workflow stage: {entry['id']}")
                if any(related not in ids for related in entry.get("related_ids", [])):
                    errors.append(f"Unknown related id: {entry['id']}")
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        errors.append(f"Invalid catalog: {error}")
    return errors


def repository_files(root: Path, pattern: str):
    """Walk owned files without descending into local environments or run data."""
    excluded = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', 'node_modules', 'projects', 'outputs'}
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names if name not in excluded)
        for name in sorted(files):
            path = Path(directory) / name
            if path.match(pattern):
                yield path


def check_links(root: Path):
    errors = []
    for path in repository_files(root, '*.md'):
        relative = path.relative_to(root)
        if relative.parts[0] in {"sources", "projects", ".git"}:
            continue  # Immutable source missing attachments are reported separately.
        for _, target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")) or "{{" in target:
                continue
            destination = unquote(target.split("#", 1)[0])
            if not destination:
                continue
            resolved = (path.parent / destination).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                errors.append(f"Broken local link: {relative} -> {target}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    sub.add_parser("validate")
    search = sub.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--kind", choices=["tool", "paper", "resource"])
    search.add_argument("--category", choices=sorted(CATEGORIES))
    importer = sub.add_parser("import-snapshot")
    importer.add_argument("source", type=Path)
    importer.add_argument("--id", required=True)
    importer.add_argument("--date", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "import-snapshot":
            added = import_snapshot(root, args.source, args.id, args.date)
            print("Snapshot imported" if added else "Snapshot already present; unchanged")
        if args.command in {"build", "import-snapshot"}:
            data = build_records(root)
            write_json(root / "catalog/records.json", data)
            render_views(root, data)
            print(f"Built {len(data['records'])} canonical URL records")
        elif args.command == "validate":
            errors = validate_catalog(root) + check_links(root)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            print("Catalog, source SHA256, provenance, curation and local document paths passed (external links not checked)")
        elif args.command == "search":
            for record in read_json(root / "catalog/records.json")["records"]:
                if args.kind and record["kind"] != args.kind: continue
                if args.category and args.category not in record["categories"]: continue
                if args.query.casefold() not in json.dumps(record, ensure_ascii=False).casefold(): continue
                print(f"{record['id']}\t{record['title']}\t{record['url']}")
        return 0
    except (ValueError, KeyError, OSError, TypeError, AttributeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
