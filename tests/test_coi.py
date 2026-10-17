"""Offline source/patch tests. Never import upstream packages or call providers."""
import ast
import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.orchestration import coi_agent


def isolated_method(sources, filename, class_name, method_name, namespace):
    """Compile only the named method, replacing its dependencies with local fakes."""
    tree = ast.parse(sources[filename])
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(module, f"<isolated {filename}:{method_name}>", "exec"), namespace)
    return namespace[method_name]


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "third_party", self.root / "third_party")
        (self.root / "modules/orchestration").mkdir(parents=True)
        shutil.copyfile(ROOT / "modules/orchestration/coi_patches.json", self.root / "modules/orchestration/coi_patches.json")

    def test_pristine_snapshot_and_license(self):
        summary = coi_agent.verify_snapshot(self.root)
        self.assertEqual(summary["source_files"], 15)
        self.assertEqual(summary["license"], "Apache-2.0")
        self.assertEqual(summary["runtime_verification_status"], "not_run")
        self.assertFalse(summary["experiments_executed"])
        manifest = json.loads((self.root / "third_party/coi_agent/manifest.json").read_text())
        self.assertTrue(all(not any(part in {"dataset", "assets", "__pycache__"} for part in Path(f["path"]).parts) for f in manifest["files"]))

    def test_modified_source_rejected(self):
        (self.root / "third_party/coi_agent/upstream/agents.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            coi_agent.patched_sources(self.root)

    def test_extra_source_rejected(self):
        (self.root / "third_party/coi_agent/upstream/secret.txt").write_text("not a real secret")
        with self.assertRaisesRegex(ValueError, "file set changed"):
            coi_agent.verify_snapshot(self.root)

    def test_missing_source_rejected(self):
        (self.root / "third_party/coi_agent/upstream/main.py").unlink()
        with self.assertRaisesRegex(ValueError, "file set changed"):
            coi_agent.verify_snapshot(self.root)

    def test_pin_drift_rejected(self):
        path = self.root / "modules/orchestration/coi_patches.json"
        value = json.loads(path.read_text()); value["upstream_commit"] = "wrong"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "pin mismatch"):
            coi_agent.patched_sources(self.root)

    def test_patch_drift_rejected(self):
        path = self.root / "modules/orchestration/coi_patches.json"
        value = json.loads(path.read_text()); value["patches"][0]["old"] = "not present"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "exactly once"):
            coi_agent.patched_sources(self.root)

    def test_prepare_preserves_original_and_attribution(self):
        before = coi_agent.verify_snapshot(self.root)
        target = coi_agent.prepare_runtime(Path("projects/coi"), self.root)
        self.assertEqual(before, coi_agent.verify_snapshot(self.root))
        self.assertEqual((target / "LICENSE").read_bytes(), (self.root / "third_party/coi_agent/upstream/LICENSE").read_bytes())
        for filename in ("agents.py", "main.py", "LLM.py"):
            self.assertTrue((target / filename).read_text().startswith("# MODIFIED"))
        self.assertEqual(json.loads((target / "PROVENANCE.json").read_text())["commit"], coi_agent.PIN)
        self.assertEqual(len(json.loads((target / "LOCAL_CHANGES.json").read_text())["patches"]), 5)

    def test_prepare_refuses_existing_destination(self):
        target = self.root / "projects/coi"; target.mkdir(parents=True)
        (target / "keep.txt").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "already exists"):
            coi_agent.prepare_runtime(target, self.root)
        self.assertEqual((target / "keep.txt").read_text(), "preserve")

    def test_prepare_refuses_outside_private_area(self):
        for destination in (Path("public"), Path("projects"), Path("projects/../../escape")):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, "private subdirectory"):
                coi_agent.prepare_runtime(destination, self.root)

    def test_prepare_refuses_symlink_escape(self):
        (self.root / "projects").mkdir()
        (self.root / "outside").mkdir()
        (self.root / "projects/link").symlink_to(self.root / "outside", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "private subdirectory"):
            coi_agent.prepare_runtime(Path("projects/link/coi"), self.root)

    def test_all_python_sources_compile_without_import(self):
        for path, source in coi_agent.patched_sources(self.root).items():
            if path.endswith(".py"):
                with self.subTest(path=path):
                    compile(source, path, "exec")

    def test_snapshot_does_not_contain_credentials(self):
        config = (self.root / "third_party/coi_agent/upstream/config.yaml").read_text()
        for line in config.splitlines():
            if line and not line.lstrip().startswith("#"):
                key, value = line.split(":", 1)
                if key.strip() != "is_azure":
                    self.assertEqual(value.split("#", 1)[0].strip(), '\"\"')


class PatchBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = coi_agent.patched_sources()

    def test_chain_aggregation_preserves_field_meaning(self):
        namespace = {"asyncio": asyncio, "os": os, "json": json}
        method = isolated_method(self.sources, "agents.py", "DeepResearchAgent", "generate_idea_with_chain", namespace)
        async def queries(**kwargs): return ["query"]
        async def search(*args, **kwargs): return [types.SimpleNamespace(title="paper")]
        async def chain(paper): return ("idea", "chain", "trend", ["experiment"], ["entity"], "future", "human", [2024])
        with tempfile.TemporaryDirectory() as directory:
            agent = types.SimpleNamespace(get_search_query=queries, reader=types.SimpleNamespace(search_async=search),
                read_papers=set(), llm=None, publicationData=None, max_chain_numbers=1,
                deep_research_paper_with_chain=chain, log_save_file=directory)
            with redirect_stdout(io.StringIO()):
                result = asyncio.run(method(agent, "topic"))
        self.assertEqual(result, ("idea", ["experiment"], ["entity"], "chain", ["idea"], "trend", "future", "human", [2024]))

    def test_no_seed_papers_returns_no_idea(self):
        method = isolated_method(self.sources, "agents.py", "DeepResearchAgent", "generate_idea_with_chain", {})
        async def queries(**kwargs): return []
        agent = types.SimpleNamespace(get_search_query=queries)
        with redirect_stdout(io.StringIO()):
            result = asyncio.run(method(agent, "topic"))
        self.assertEqual(result, (None,) * 9)

    def azure_class(self):
        tree = ast.parse(self.sources["LLM.py"])
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "openai_llm")
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"]
        namespace = {"os": os, "base_llm": object, "OpenAI": lambda **kw: "openai", "AsyncOpenAI": lambda **kw: "openai-async",
                     "AzureOpenAI": lambda **kw: "azure", "AsyncAzureOpenAI": lambda **kw: "azure-async"}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "<isolated LLM.__init__>", "exec"), namespace)
        return namespace["openai_llm"]

    def test_azure_boolean_parses_both_providers(self):
        cls = self.azure_class()
        for value, provider in (("False", "openai"), ("0", "openai"), (" true ", "azure"), ("1", "azure")):
            with self.subTest(value=value), patch.dict(os.environ, {"is_azure": value, "OPENAI_API_KEY": "test-only", "AZURE_OPENAI_ENDPOINT": "test-only", "AZURE_OPENAI_KEY": "test-only"}, clear=True):
                self.assertEqual(cls().client, provider)

    def test_azure_unknown_boolean_rejected(self):
        with patch.dict(os.environ, {"is_azure": "maybe"}, clear=True), self.assertRaises(ValueError):
            self.azure_class()()

    def test_cli_chain_length_destination(self):
        import argparse
        tree = ast.parse(self.sources["main.py"])
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "add_argument" and node.args and isinstance(node.args[0], ast.Constant)
                 and node.args[0].value == "--max_chain_length"]
        self.assertEqual(len(calls), 1)
        parser = argparse.ArgumentParser()
        exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(calls[0])], type_ignores=[])), "<isolated CLI>", "exec"), {"argparser": parser})
        self.assertEqual(parser.parse_args(["--max_chain_length", "7"]).max_chain_length, 7)

    def novelty(self, papers, verdict="0", paper_id="0"):
        async def queries(idea): return ["query"]
        async def search(*args, **kwargs): return papers
        async def response(messages): return "fake-response"
        values = {"similar": verdict, "summary": "test summary", "similar_paper_id": paper_id}
        namespace = {"get_deep_check_idea_novel_prompt": lambda *args: "fake-prompt", "extract": lambda text, key: values[key]}
        method = isolated_method(self.sources, "agents.py", "DeepResearchAgent", "check_novel", namespace)
        agent = types.SimpleNamespace(get_check_novel_search_query=queries, reader=types.SimpleNamespace(search_async=search),
            llm=None, publicationData=None, wrap_messages=lambda text: [], get_cheap_openai_response_async=response)
        return asyncio.run(method(agent, "idea"))

    def test_empty_novelty_evidence_is_inconclusive(self):
        with self.assertRaisesRegex(RuntimeError, "inconclusive: no search evidence"):
            self.novelty([])

    def test_malformed_novelty_verdict_is_inconclusive(self):
        for verdict in ("", "maybe", "<similar>0"):
            with self.subTest(verdict=verdict), self.assertRaisesRegex(RuntimeError, "invalid similarity verdict"):
                self.novelty([types.SimpleNamespace(title="paper")], verdict)

    def test_novelty_verdict_and_optional_paper(self):
        paper = types.SimpleNamespace(title="paper")
        self.assertEqual(self.novelty([paper], "1"), (False, paper, "test summary"))
        self.assertEqual(self.novelty([paper], "0", "bad-index"), (True, None, "test summary"))

    def test_inspect_cli_offline(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/coi.py"), "inspect"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["commit"], coi_agent.PIN)


if __name__ == "__main__":
    unittest.main()
