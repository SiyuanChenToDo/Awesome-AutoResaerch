"""End-to-end tests of owned SAGE code; every external capability is a fake."""
from __future__ import annotations
import asyncio
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sage.config import RunConfig
from sage.dates import publication_window, within_window
from sage.discovery import Discovery, cosine, unique
from sage.errors import BudgetExceeded, ConfigurationError, InvalidResponse, ProviderError, TransientProviderError
from sage.fixtures import FixtureModel, FixtureSource, fixture_papers
from sage.orchestration import run
from sage.review import Review
from sage.review.evaluator import audit_result
from sage.runtime import Runtime, tags, string_list
from sage.types import Paper
from sage.cli import load_articles

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, model=None, source=None, **kwargs):
        with patch('socket.create_connection', side_effect=AssertionError('Offline workflow attempted network')):
            return await run('Synthetic research topic', model or FixtureModel(), source or FixtureSource(), **kwargs)

    async def test_full_pipeline_uses_all_owned_stages_and_named_fields(self):
        result = await self.execute()
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.validation['contract_passed'], True)
        self.assertFalse(result.validation['scientific_quality_assessed'])
        self.assertEqual(result.scientific_validation, 'not_performed')
        self.assertEqual((len(result.candidates), result.selected_index), (2, 0))
        self.assertEqual([len(c.chain.evidence) for c in result.candidates], [4, 4])
        self.assertEqual([e.paper.year for e in result.candidates[0].chain.evidence], [2020, 2021, 2022, 2023])
        self.assertTrue(result.candidates[0].chain.trend.startswith('Synthetic chain'))
        self.assertTrue(all(e.experiment.startswith('Synthetic source plan') for e in result.candidates[0].chain.evidence))
        self.assertTrue(result.candidates[0].rejected_attempts[0]['compared_papers'][0]['url'])
        self.assertEqual(len(result.ranking['comparisons']), 2)
        self.assertEqual(len(result.ranking['dimensions']), 6)
        self.assertEqual(result.ranking['scores'], [6.0, 6.0])
        self.assertFalse(result.ranking['scientific_validation'])
        self.assertEqual(result.experiment.status, 'proposal_only')
        self.assertEqual(len(result.experiment.revisions), 1)
        self.assertEqual(len(result.experiment.revisions[0]['paper_infos']), 2)
        self.assertTrue(result.experiment.revisions[0]['paper_infos'][0]['url'])
        self.assertEqual(result.usage['model_calls'], 46)  # includes two anchor relevance checks
        self.assertEqual(result.usage['search_calls'], 15)
        stages = {e['stage'] for e in result.audit}
        self.assertTrue({'discovery.citations', 'discovery.references', 'ideation.regenerate',
                         'review.pairwise', 'experiment_design.refine', 'literature.extract'} <= stages)
        self.assertEqual(result.execution_status, 'not_implemented')
        self.assertEqual(result.writing_status, 'not_implemented')
        self.assertNotIn('third_party.coi_agent', ' '.join(sys.modules))
        json.dumps(result.to_dict(), allow_nan=False)

    async def test_no_search_evidence_stops_with_bounded_query_rewrites(self):
        result = await self.execute(source=FixtureSource(empty=True))
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'no_evidence')
        self.assertIsNone(result.experiment)
        self.assertEqual(result.usage['search_calls'], 6)
        self.assertEqual(result.usage['model_calls'], 5)

    async def test_empty_novelty_is_unknown_not_successful_novelty(self):
        result = await self.execute(source=FixtureSource(empty_novelty=True))
        self.assertEqual(result.status, 'completed_with_uncertainty')
        self.assertTrue(all(c.novelty.status == 'not_established' for c in result.candidates))
        self.assertTrue(all(not c.novelty.compared_papers for c in result.candidates))

    async def test_novelty_regeneration_has_hard_attempt_limit(self):
        reply = '<similar>1</similar><summary>Overlapping fixture.</summary><similar_paper_id>0</similar_paper_id>'
        result = await self.execute(model=FixtureModel(overrides={'review.novelty_compare': [reply] * 8}))
        self.assertEqual(result.status, 'completed_with_uncertainty')
        self.assertTrue(all(len(c.rejected_attempts) == 2 for c in result.candidates))
        self.assertTrue(all(c.novelty.status == 'similar_work_found' for c in result.candidates))

    async def test_invalid_novelty_cannot_become_novel(self):
        bad = '<similar>maybe</similar><summary>Unknown.</summary><similar_paper_id>100</similar_paper_id>'
        result = await self.execute(model=FixtureModel(overrides={'review.novelty_compare': [bad] * 4}))
        self.assertEqual(result.status, 'completed_with_uncertainty')
        self.assertTrue(all(c.novelty.status == 'not_established' for c in result.candidates))

    async def test_model_budget_counts_attempts_and_preserves_partial_evidence(self):
        result = await self.execute(config=RunConfig(max_model_calls=5))
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.usage['model_calls'], 5)
        self.assertEqual(result.errors[-1]['code'], 'budget_exceeded')
        self.assertTrue(any(e['stage'] == 'literature.evidence' for e in result.audit))
        self.assertTrue(result.validation['contract_passed'])

    async def test_search_budget_stops_before_overrun(self):
        result = await self.execute(config=RunConfig(max_search_calls=1))
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.usage['search_calls'], 1)

    async def test_reserved_token_budget_stops_before_call(self):
        result = await self.execute(config=RunConfig(max_reserved_output_tokens=1999))
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.usage['model_calls'], 0)
        self.assertEqual(result.usage['reserved_output_tokens'], 0)

    async def test_retry_is_charged_and_audited(self):
        model = FixtureModel(overrides={'discovery.queries': [TransientProviderError('sensitive provider body')]})
        result = await self.execute(model=model)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.usage['model_calls'], 47)
        self.assertEqual(model.calls['discovery.queries'], 2)
        self.assertNotIn('sensitive provider body', json.dumps(result.to_dict()))
        failed = [e for e in result.audit if e['stage'] == 'discovery.queries' and e['status'] == 'failed']
        self.assertEqual(failed[0]['error_code'], 'transient_provider_error')

    async def test_invalid_model_format_retries_then_fails(self):
        result = await self.execute(model=FixtureModel(overrides={'discovery.queries': ['untagged', '<queries>{}</queries>']}))
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.usage['model_calls'], 2)
        self.assertEqual(result.errors[-1]['code'], 'invalid_response')

    async def test_permanent_provider_error_is_not_retried_or_leaked(self):
        result = await self.execute(model=FixtureModel(overrides={'discovery.queries': [ProviderError('sk-private-token')]}))
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.usage['model_calls'], 1)
        self.assertNotIn('sk-private-token', json.dumps(result.to_dict()))

    async def test_unexpected_provider_error_is_sanitized(self):
        result = await self.execute(model=FixtureModel(overrides={'discovery.queries': [RuntimeError('secret')]}))
        self.assertEqual(result.status, 'failed')
        self.assertNotIn('secret', json.dumps(result.to_dict()))

    async def test_short_chain_records_anchor_and_partial_evidence(self):
        class NoEdges(FixtureSource):
            async def related(self, *args, **kwargs): return []
            async def search(self, query, **kwargs):
                if query.startswith('Synthetic'): return []
                return await super().search(query, **kwargs)
        result = await self.execute(source=NoEdges())
        self.assertEqual(result.status, 'stopped')
        self.assertTrue(any(e.get('anchor_id') == 'fixture-a-anchor' for e in result.audit))
        self.assertTrue(any(e['stage'] == 'literature.evidence' for e in result.audit))

    async def test_cycles_are_removed_from_chains(self):
        class CyclicSource(FixtureSource):
            async def related(self, paper, **kwargs):
                return [paper, paper, *await super().related(paper, **kwargs)]
        result = await self.execute(source=CyclicSource())
        self.assertEqual(result.status, 'completed')
        for candidate in result.candidates:
            self.assertEqual(len(candidate.chain.evidence), len({e.paper.paper_id for e in candidate.chain.evidence}))

    async def test_no_refinement_rounds_preserves_original_plan(self):
        result = await self.execute(config=RunConfig(refinement_rounds=0))
        self.assertEqual(result.experiment.revisions, [])
        self.assertNotIn('revised', result.experiment.proposal)

    async def test_failure_during_refinement_retains_initial_plan(self):
        model = FixtureModel(overrides={'experiment_design.refine': [ProviderError('x')]})
        result = await self.execute(model=model)
        self.assertEqual(result.status, 'failed')
        self.assertTrue(result.experiment.proposal)
        self.assertEqual(result.experiment.revisions, [])

    async def test_fixed_audit_rejects_fabricated_validation_or_missing_evidence(self):
        result = await self.execute()
        result.scientific_validation = 'proven'
        self.assertFalse(audit_result(result, RunConfig())['contract_passed'])
        result.scientific_validation = 'not_performed'
        result.candidates[0].novelty.compared_papers.clear()
        self.assertFalse(audit_result(result, RunConfig())['contract_passed'])


class RuntimeAndDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_record_utc_time_and_elapsed_monotonic_progress(self):
        from datetime import datetime, timezone
        ticks = iter((100.0, 101.0, 103.5))
        runtime = Runtime(FixtureModel(), FixtureModel(), FixtureSource(), RunConfig(), clock=lambda: next(ticks))
        before = datetime.now(timezone.utc)
        runtime.event('handoff', 'started')
        runtime.event('handoff', 'succeeded')
        after = datetime.now(timezone.utc)
        self.assertEqual([e['elapsed_seconds'] for e in runtime.audit], [1.0, 3.5])
        for event in runtime.audit:
            observed = datetime.fromisoformat(event['time'])
            self.assertIsNotNone(observed.utcoffset())
            self.assertLessEqual(before, observed)
            self.assertLessEqual(observed, after)

    async def test_call_timeout_bounded(self):
        config = RunConfig(request_timeout_seconds=0.005)
        runtime = Runtime(FixtureModel(), FixtureModel(), FixtureSource(), config)
        async def wait(): await asyncio.sleep(1)
        with self.assertRaises(ProviderError):
            await runtime.call('model', 'timeout-test', wait)
        self.assertEqual(runtime.usage['model_calls'], 2)

    async def test_wall_budget_checks_before_provider(self):
        ticks = iter([0.0, 1000.0])
        runtime = Runtime(FixtureModel(), FixtureModel(), FixtureSource(), RunConfig(), clock=lambda: next(ticks))
        with self.assertRaises(BudgetExceeded):
            await runtime.ask('discovery.queries', 'x', ('queries',))
        self.assertEqual(runtime.usage['model_calls'], 0)

    async def test_embedding_ranking_is_actual_cosine_and_budgeted(self):
        class Embeddings(FixtureModel):
            embedding_enabled = True
            async def embed(self, texts): return [[1, 0], [0, 1], [1, 0]]
        runtime = Runtime(Embeddings(), FixtureModel(), FixtureSource(), RunConfig())
        papers = fixture_papers()[:2]
        ranked = await Discovery(runtime).rank(papers, 'query')
        self.assertEqual(ranked[0], papers[1])
        self.assertEqual(runtime.usage['model_calls'], 1)
        self.assertEqual(runtime.usage['reserved_output_tokens'], 0)

    async def test_publication_window_applies_to_citation_edges(self):
        runtime = Runtime(FixtureModel(), FixtureModel(), FixtureSource(), RunConfig(publication_date=':2022'))
        anchor = runtime.source.papers['fixture-a-anchor']
        self.assertEqual(await Discovery(runtime).related(anchor, 'topic', 'citations'), [])
        prior = await Discovery(runtime).related(anchor, 'topic', 'references')
        self.assertEqual(prior[0].year, 2021)

    async def test_user_articles_attach_explicit_evidence_scope(self):
        runtime = Runtime(FixtureModel(), FixtureModel(), FixtureSource(), RunConfig())
        article = {'sections': [{'text': 'User-supplied text'}], 'references': []}
        papers = await Discovery(runtime, articles={'fixture-a-anchor': article}).search('sage-fixture-a', limit=1)
        self.assertEqual(papers[0].evidence_scope, 'user_supplied_full_text')
        self.assertEqual(papers[0].article, article)


class ValidationTests(unittest.TestCase):
    def test_configuration_rejects_bad_bounds_before_execution(self):
        for values in ({'max_model_calls': True}, {'max_chain_length': 0}, {'min_chain_length': 5},
                       {'max_related': 101}, {'retry_attempts': 6}, {'refinement_rounds': -1},
                       {'max_wall_seconds': float('nan')}, {'request_timeout_seconds': 301},
                       {'publication_date': '2025:2020'}, {'publication_date': '2024-02-31'}):
            with self.subTest(values=values), self.assertRaises(ConfigurationError): RunConfig(**values)

    def test_strict_parser_rejects_missing_duplicate_and_empty_tags(self):
        for response in ('free text', '<x></x>', '<x>a</x><x>b</x>'):
            with self.assertRaises(InvalidResponse): tags(response, ('x',))
        self.assertEqual(tags('<x></x>', ('x',), ('x',)), {'x': ''})
        self.assertEqual(string_list('["a", "a", "b"]', 2), ['a', 'b'])
        for value in ('{}', '[1]', '[""]'):
            with self.assertRaises(InvalidResponse): string_list(value, 2)

    def test_cosine_zero_and_invalid_vectors(self):
        self.assertEqual(cosine([0, 0], [1, 0]), 0)
        self.assertEqual(cosine([1, 0], [1, 0]), 1)
        self.assertAlmostEqual(cosine([1e308, 1e308], [1e308, 1e308]), 1)
        with self.assertRaises(InvalidResponse): cosine([1], [1, 2])
        with self.assertRaises(InvalidResponse): cosine([float('nan')], [1])

    def test_title_and_id_deduplication(self):
        paper = fixture_papers()[0]
        self.assertEqual(unique([paper, paper, replace(paper, paper_id='another')]), [paper])

    def test_date_precision_is_conservative(self):
        paper = Paper('p', 'Title', year=2024)
        self.assertFalse(within_window(paper, ':2024-06-01'))
        self.assertTrue(within_window(paper, ':2024'))
        self.assertTrue(within_window(replace(paper, publication_date='2024-05-01'), ':2024-06-01'))
        self.assertFalse(within_window(replace(paper, year=None), ':2024'))
        self.assertEqual(str(publication_window('2024-02')[1]), '2024-02-29')

    def test_article_input_shape_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'article.json'
            path.write_text('{"id":{"sections":["not an object"]}}')
            with self.assertRaises(ConfigurationError): load_articles(path)


class CliTests(unittest.TestCase):
    def cli(self, *args, cwd=ROOT):
        return subprocess.run([sys.executable, '-m', 'sage', *map(str, args)], cwd=cwd, text=True, capture_output=True, timeout=20)

    def test_cli_run_saves_complete_artifacts_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            first = self.cli('run', '--output', output)
            self.assertEqual(first.returncode, 0, first.stderr)
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual(result['schema_version'], 'sage.run.v1')
            self.assertEqual(set(x.name for x in output.iterdir()), {'result.json', 'config.json', 'audit.jsonl', 'checkpoint.json'})
            before = (output / 'result.json').read_bytes()
            second = self.cli('run', '--output', output)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(before, (output / 'result.json').read_bytes())

    def test_runtime_works_without_third_party_snapshot_or_legacy_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            shutil.copytree(ROOT / 'sage', Path(directory) / 'sage', ignore=shutil.ignore_patterns('__pycache__'))
            output = Path(directory) / 'output'
            result = self.cli('run', '--output', output, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((output / 'result.json').exists())

    def test_live_mode_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            result = self.cli('run', '--mode', 'live', '--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--allow-live', result.stderr)
            self.assertFalse(output.exists())

    def test_cli_budget_failure_is_saved_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            result = self.cli('run', '--max-model-calls', '1', '--output', output)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads((output / 'result.json').read_text())['status'], 'stopped')

    def test_cli_rejects_symlink_output_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'link'
            link.symlink_to(Path(directory), target_is_directory=True)
            result = self.cli('run', '--output', link / 'new')
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(directory) / 'new').exists())

    def test_legacy_catalog_and_project_commands_remain_available(self):
        self.assertEqual(self.cli('catalog', 'search', 'hypothesis').returncode, 0)
        self.assertEqual(self.cli('project', 'check-project', 'examples/toy-regularization').returncode, 0)
        self.assertEqual(self.cli('provenance', 'inspect').returncode, 0)

    def test_doctor_is_offline_and_hides_environment_values(self):
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertTrue(report['offline_ready'])
        self.assertFalse(report['live_network_tested'])


if __name__ == '__main__': unittest.main()
