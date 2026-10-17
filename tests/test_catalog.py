"""Offline regressions for deterministic import, honest provenance and validation."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("catalog", REPO / "scripts/catalog.py")
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)


class CatalogFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "sage"
        self.root.mkdir()
        self.source = self.base / "source.md"
        self.source.write_text(
            "# Research sources\n"
            "## 2.2 Experiment loops\n"
            "[Example](https://github.com/Example/Tool)\n"
            "[same repository](http://github.com/example/tool.git/tree/main?x=1#readme)\n"
            "## 3.3 Benchmarks\n"
            "[arXiv](https://arxiv.org/abs/2408.06292v1)\n"
            "[Paper title](https://export.arxiv.org/pdf/2408.06292v2.pdf)\n",
            encoding="utf-8",
        )
        catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-14")
        self.archive = self.root / "sources/snapshots/fixture-2026.md"
        self.manifest = self.root / "sources/manifest.json"

    def build(self):
        data = catalog.build_records(self.root)
        catalog.write_json(self.root / "catalog/records.json", data)
        return data

    def write_manifest(self, manifest):
        catalog.write_json(self.manifest, manifest)

    def test_import_preserves_exact_bytes_and_source_hash(self):
        self.assertEqual(self.archive.read_bytes(), self.source.read_bytes())
        manifest = catalog.read_json(self.manifest)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(len(manifest["sources"]), 1)
        record = manifest["sources"][0]
        self.assertEqual(record["sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(record["snapshot_date"], "2026-10-14")
        self.assertEqual(record["original_filename"], "source.md")

    def test_reimport_is_idempotent_and_does_not_rewrite_files(self):
        before = (self.manifest.read_bytes(), self.archive.read_bytes(), self.manifest.stat().st_mtime_ns)
        self.assertFalse(catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-14"))
        self.assertEqual(before, (self.manifest.read_bytes(), self.archive.read_bytes(), self.manifest.stat().st_mtime_ns))

    def test_reimport_refuses_changed_content_or_date(self):
        original_manifest = self.manifest.read_bytes()
        original_archive = self.archive.read_bytes()
        self.source.write_text("Changed content\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-14")
        self.source.write_bytes(original_archive)
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-15")
        self.assertEqual(self.manifest.read_bytes(), original_manifest)
        self.assertEqual(self.archive.read_bytes(), original_archive)

    def test_reimport_detects_archive_tampering_and_missing_archive(self):
        self.archive.write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-14")
        self.archive.unlink()
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "fixture-2026", "2026-10-14")

    def test_import_refuses_overwriting_unregistered_archive(self):
        target = self.root / "sources/snapshots/new-source.md"
        target.write_text("existing bytes", encoding="utf-8")
        before = self.manifest.read_bytes()
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "new-source", "2026-10-14")
        self.assertEqual(target.read_text(encoding="utf-8"), "existing bytes")
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_import_rejects_invalid_existing_manifest_before_writing(self):
        manifest = catalog.read_json(self.manifest)
        manifest["schema_version"] = 99
        self.write_manifest(manifest)
        before = self.manifest.read_bytes()
        with self.assertRaises(ValueError):
            catalog.import_snapshot(self.root, self.source, "new-source", "2026-10-15")
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertFalse((self.root / "sources/snapshots/new-source.md").exists())

    def test_import_rejects_unsafe_source_ids_without_mutation(self):
        before = self.manifest.read_bytes()
        for source_id in ("", "../escape", "/absolute", "with/slash", "with\\slash", "UPPER", "two words", "-edge", "edge-", "two--dashes"):
            with self.subTest(source_id=source_id), self.assertRaises(ValueError):
                catalog.import_snapshot(self.root, self.source, source_id, "2026-10-14")
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_import_rejects_invalid_dates_and_encoding_without_mutation(self):
        before = self.manifest.read_bytes()
        for value in ("", "not-a-date", "2026-02-30", "2026-13-01"):
            with self.subTest(date=value), self.assertRaises(ValueError):
                catalog.import_snapshot(self.root, self.source, "new-source", value)
        self.source.write_bytes(b"\xff\xfe")
        with self.assertRaises(UnicodeDecodeError):
            catalog.import_snapshot(self.root, self.source, "new-source", "2026-10-14")
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertFalse((self.root / "sources/snapshots/new-source.md").exists())

    def test_build_deduplicates_canonical_urls_preserving_every_mention(self):
        data = self.build()
        self.assertEqual(len(data["records"]), 2)
        tool = next(r for r in data["records"] if r["kind"] == "tool")
        paper = next(r for r in data["records"] if r["kind"] == "paper")
        self.assertEqual(tool["url"], "https://github.com/example/tool")
        self.assertEqual(paper["url"], "https://arxiv.org/abs/2408.06292")
        self.assertEqual(paper["title"], "Paper title")
        self.assertEqual([m["line"] for m in tool["source_mentions"]], [3, 4])
        self.assertEqual([m["line"] for m in paper["source_mentions"]], [6, 7])
        for record in data["records"]:
            self.assertEqual(record["verification_status"], "source_imported")
            self.assertEqual(record["integration_status"], "not_integrated")
            for mention in record["source_mentions"]:
                self.assertEqual(mention["source_id"], "fixture-2026")
                self.assertEqual(mention["path"], "sources/snapshots/fixture-2026.md")
                self.assertIn(mention["original_url"], self.archive.read_text(encoding="utf-8").splitlines()[mention["line"] - 1])
        self.assertEqual(catalog.validate_catalog(self.root), [])

    def test_build_merges_multiple_sources_without_losing_provenance(self):
        second = self.base / "second.md"
        second.write_text("## 2.1 Foundation\n[Tool again](https://github.com/example/tool#about)\n", encoding="utf-8")
        catalog.import_snapshot(self.root, second, "second-2026", "2026-10-15")
        data = self.build()
        self.assertEqual(len(data["records"]), 2)
        tool = next(r for r in data["records"] if r["kind"] == "tool")
        self.assertEqual(len(tool["source_mentions"]), 3)
        self.assertEqual(set(m["source_id"] for m in tool["source_mentions"]), {"fixture-2026", "second-2026"})
        self.assertEqual(tool["categories"], ["experiment-loop", "foundation"])

    def test_build_and_render_are_byte_reproducible(self):
        first = self.build()
        catalog.render_views(self.root, first)
        initial = {p.name: p.read_bytes() for p in (self.root / "catalog").iterdir()}
        second = self.build()
        catalog.render_views(self.root, second)
        rebuilt = {p.name: p.read_bytes() for p in (self.root / "catalog").iterdir()}
        self.assertEqual(first, second)
        self.assertEqual(initial, rebuilt)

    def test_build_detects_source_digest_mismatch(self):
        self.archive.write_text(self.archive.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "[Dd]igest"):
            catalog.build_records(self.root)

    def test_build_rejects_manifest_path_escape_and_symlink_escape(self):
        manifest = catalog.read_json(self.manifest)
        manifest["sources"][0]["path"] = "../source.md"
        self.write_manifest(manifest)
        with self.assertRaises(ValueError):
            catalog.build_records(self.root)
        link = self.root / "linked.md"
        link.symlink_to(self.source)
        manifest["sources"][0]["path"] = "linked.md"
        self.write_manifest(manifest)
        with self.assertRaises(ValueError):
            catalog.build_records(self.root)

    def test_build_rejects_invalid_manifest_metadata(self):
        original = catalog.read_json(self.manifest)
        cases = []
        wrong_schema = copy.deepcopy(original)
        wrong_schema["schema_version"] = 99
        cases.append(("schema_version", wrong_schema))
        for key, value in (("id", ""), ("id", "../escape"), ("snapshot_date", "2026-02-30"), ("snapshot_date", ""), ("sha256", ""), ("path", "")):
            invalid = copy.deepcopy(original)
            invalid["sources"][0][key] = value
            cases.append((f"{key}={value!r}", invalid))
        duplicate = copy.deepcopy(original)
        duplicate["sources"].append(copy.deepcopy(duplicate["sources"][0]))
        cases.append(("duplicate source id", duplicate))
        for label, invalid in cases:
            with self.subTest(case=label):
                self.write_manifest(invalid)
                with self.assertRaises((ValueError, TypeError, KeyError)):
                    catalog.build_records(self.root)

    def test_validate_reports_malformed_manifest_shapes_without_crashing(self):
        self.build()
        for value in (None, [], "wrong", 42, {}, {"schema_version": 1, "sources": []}, {"schema_version": 1, "sources": [None]}):
            with self.subTest(value=value):
                self.write_manifest(value)
                self.assertTrue(catalog.validate_catalog(self.root))

    def test_benchmark_table_keeps_name_and_original_excerpt(self):
        text = "## 3.3 Benchmarks\n| CORE-Bench | Description | [arXiv](https://arxiv.org/abs/2408.06292) |\n"
        source = {"id": "table-source", "path": "sources/snapshots/table-source.md"}
        records = catalog.extract_records(text, source)
        self.assertEqual(records[0]["title"], "CORE-Bench")
        self.assertEqual(records[0]["categories"], ["benchmark"])
        self.assertEqual(records[0]["source_mentions"][0]["source_excerpt"], text.splitlines()[1])
        self.assertEqual(records[0]["source_mentions"][0]["label"], "arXiv")

    def test_validate_rejects_tampered_metadata_and_fabricated_claims(self):
        original = self.build()
        changes = [
            ("title", ""), ("categories", ["invented"]), ("source_mentions", []),
            ("verification_status", "runtime_verified"), ("integration_status", "installed"),
            ("url", "https://example.org/changed"), ("id", "invented"),
        ]
        for field, value in changes:
            with self.subTest(field=field):
                data = copy.deepcopy(original)
                data["records"][0][field] = value
                catalog.write_json(self.root / "catalog/records.json", data)
                self.assertTrue(catalog.validate_catalog(self.root))

    def test_validate_rejects_false_or_out_of_range_source_locations(self):
        original = self.build()
        for line in (0, -1, 99999, "3", False):
            with self.subTest(line=line):
                data = copy.deepcopy(original)
                data["records"][0]["source_mentions"][0]["line"] = line
                catalog.write_json(self.root / "catalog/records.json", data)
                self.assertTrue(catalog.validate_catalog(self.root))

    def test_validate_reports_malformed_json_without_crashing(self):
        self.build()
        (self.root / "catalog/records.json").write_text("{invalid", encoding="utf-8")
        self.assertTrue(catalog.validate_catalog(self.root))

    def test_validate_rejects_unknown_curation_and_unsubstantiated_verification(self):
        data = self.build()
        catalog.write_json(self.root / "catalog/curation.json", {"entries": [{"id": "missing", "stages": ["invented"], "related_ids": ["absent"]}]})
        catalog.write_json(self.root / "catalog/verification.json", {"checks": [{"url": data["records"][0]["url"], "checked_at": "2026-10-17", "runtime_tested": True, "evidence_urls": [], "limitations": ""}]})
        errors = catalog.validate_catalog(self.root)
        self.assertTrue(any("Unknown curated id" in e for e in errors))
        self.assertTrue(any("Unknown workflow stage" in e for e in errors))
        self.assertTrue(any("runtime" in e for e in errors))
        self.assertTrue(any("evidence" in e for e in errors))

    def test_cli_build_search_and_invalid_import_are_offline(self):
        command = [sys.executable, str(REPO / "scripts/catalog.py"), "--root", str(self.root)]
        built = subprocess.run(command + ["build"], capture_output=True, text=True, timeout=10)
        self.assertEqual(built.returncode, 0, built.stderr)
        found = subprocess.run(command + ["search", "Example", "--kind", "tool"], capture_output=True, text=True, timeout=10)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn("https://github.com/example/tool", found.stdout)
        bad = subprocess.run(command + ["import-snapshot", str(self.source), "--id", "../escape", "--date", "2026-10-14"], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(bad.returncode, 0)
        self.assertNotIn("Traceback", bad.stderr)


class CanonicalUrlTests(unittest.TestCase):
    def test_github_repository_variants_share_one_identity(self):
        canonical = catalog.canonicalize("https://github.com/Example/Tool")
        for url in ("http://github.com/example/tool/", "https://github.com/EXAMPLE/TOOL.git", "https://github.com/example/tool/tree/main/subdir?tab=readme#title"):
            with self.subTest(url=url):
                self.assertEqual(catalog.canonicalize(url), canonical)

    def test_arxiv_versions_pdf_and_export_host_share_one_identity(self):
        expected = catalog.canonicalize("https://arxiv.org/abs/2408.06292")
        for url in ("http://arxiv.org/pdf/2408.06292v3.pdf", "https://export.arxiv.org/abs/2408.06292v1", "https://arxiv.org/pdf/2408.06292"):
            with self.subTest(url=url):
                self.assertEqual(catalog.canonicalize(url), expected)

    def test_distinct_repository_urls_never_collide_on_hyphens_or_underscores(self):
        urls = ["https://github.com/a-b/c", "https://github.com/a/b-c", "https://github.com/a/b_c"]
        identities = [catalog.canonicalize(url) for url in urls]
        self.assertEqual(len({item[0] for item in identities}), len(urls))
        self.assertEqual(len({item[2] for item in identities}), len(urls))

    def test_external_fragments_removed_but_semantic_query_preserved(self):
        self.assertEqual(catalog.canonicalize("https://EXAMPLE.ORG/article/?version=2#section")[0], "https://example.org/article?version=2")

    def test_rejects_non_http_urls_and_embedded_credentials(self):
        for url in ("", "relative/path", "javascript:alert(1)", "file:///etc/passwd", "https:///missing", "https://name:password@example.org/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                catalog.canonicalize(url)


class LocalLinkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()

    def test_valid_relative_encoded_and_fragment_links(self):
        (self.root / "docs").mkdir()
        (self.root / "docs/with space.md").write_text("# Target\n", encoding="utf-8")
        (self.root / "README.md").write_text("[target](docs/with%20space.md#target) [local](#anchor) [web](https://example.invalid/not-fetched) [mail](mailto:test@example.invalid)\n", encoding="utf-8")
        self.assertEqual(catalog.check_links(self.root), [])

    def test_missing_and_escaping_paths_are_reported(self):
        (self.base / "outside.md").write_text("outside", encoding="utf-8")
        (self.root / "README.md").write_text("[missing](absent.md) [escape](../outside.md) [encoded](%2e%2e/outside.md)\n", encoding="utf-8")
        errors = catalog.check_links(self.root)
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("README.md" in e for e in errors))

    def test_symlink_escape_is_reported(self):
        outside = self.base / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        (self.root / "linked.md").symlink_to(outside)
        (self.root / "README.md").write_text("[escape](linked.md)\n", encoding="utf-8")
        self.assertEqual(len(catalog.check_links(self.root)), 1)

    def test_source_snapshots_projects_and_template_placeholders_are_exempt(self):
        for directory in ("sources/snapshots", "projects/example", ".git"):
            path = self.root / directory
            path.mkdir(parents=True)
            (path / "content.md").write_text("[not bundled](missing.md)\n", encoding="utf-8")
        (self.root / "README.md").write_text("[future]({{PROJECT_ID}}/file.md)\n", encoding="utf-8")
        self.assertEqual(catalog.check_links(self.root), [])


if __name__ == "__main__":
    unittest.main()
