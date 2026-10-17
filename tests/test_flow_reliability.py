"""Observed flow failures: irrelevant anchors, late preflight and lost lab progress."""
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sage.config import RunConfig
from sage.discovery import Discovery
from sage.fixtures import FixtureModel, FixtureSource
from sage.orchestration import run
from sage.runtime import Runtime
from sage.types import Paper

ROOT = Path(__file__).resolve().parents[1]


class AnchorQuality(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_code_repair_receives_original_command_and_format(self):
        from sage.execution import ExperimentRunner
        from sage.execution.fixtures import fixture_contract, IMPROVED_CODE
        from sage.types import ExperimentPlan
        malformed = 'REPLACE\n```python\nprint("recover this program")\n```'

        class Model:
            def __init__(self):
                self.requests = []

            async def complete(self, stage, prompt, **kwargs):
                self.requests.append((stage, prompt))
                return ('<command>' + malformed + '</command>' if len(self.requests) == 1 else
                        '<command>```REPLACE\n' + IMPROVED_CODE + '\n```</command>')
        model = Model()
        runtime = Runtime(model, model, FixtureSource(), RunConfig())
        result = await ExperimentRunner(runtime, fixture_contract()).run(ExperimentPlan('proposal'))
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(result['attempts'][0]['status'], 'failed')
        self.assertIn('```REPLACE', result['attempts'][0]['diagnostic'])
        repair = model.requests[1][1]
        self.assertIn(malformed, repair)
        self.assertIn('fixture-protocol-v1', repair)
        self.assertIn('<command>```REPLACE\n', repair)

    async def test_report_requests_do_not_accumulate_previous_section_prose(self):
        from sage.writing.prompts import section_prompt, MAX_COMMENTARY_CHARS
        from sage.writing.report import parse_section
        from sage.errors import ValidationError
        previous = [{'section_id': 'introduction', 'status': 'drafted', 'citation_ids': [],
                     'commentary': 'PAST_PROSE_DO_NOT_DUPLICATE ' * 5000}]
        request = section_prompt('methods', {'proposal': 'Exact current plan'}, previous)
        self.assertNotIn('PAST_PROSE_DO_NOT_DUPLICATE', request)
        self.assertIn('Exact current plan', request)
        self.assertIn('introduction', request)
        self.assertLess(len(request), 5000)
        oversized = {'commentary': 'x' * (MAX_COMMENTARY_CHARS + 1), 'citation_ids': []}
        with self.assertRaises(ValidationError) as error:
            parse_section(oversized, set())
        self.assertEqual(error.exception.field, 'commentary')
        self.assertEqual(oversized['commentary'], 'x' * (MAX_COMMENTARY_CHARS + 1))

    async def test_discussion_schema_expresses_array_and_requirement_item_types(self):
        from sage.discussion.prompts import output_schema
        schema = output_schema({'selected_index': 'index', 'accepted_critique_ids': 'ids',
                                'requirements': 'requirements', 'rationale': 'text'})
        self.assertEqual(schema['properties']['selected_index']['type'], 'integer')
        ids = schema['properties']['accepted_critique_ids']
        self.assertEqual(ids['type'], 'array')
        self.assertEqual(ids['items']['type'], 'string')
        self.assertTrue(ids['uniqueItems'])
        requirements = schema['properties']['requirements']
        self.assertEqual(requirements['type'], 'array')
        self.assertEqual(requirements['items']['type'], 'object')
        self.assertEqual(requirements['items']['required'], ['critique_id', 'requirement'])
        self.assertFalse(schema['additionalProperties'])

    async def test_discussion_task_views_preserve_primary_text_and_ownership(self):
        from copy import deepcopy
        from sage.discussion.context import compact_payload
        from sage.discussion.prompts import prompt

        def candidate(owner):
            evidence = [{'paper': {'paper_id': f'{owner}-{i}', 'title': 'Source',
                'abstract': 'Exact primary abstract. ' * 60, 'evidence_scope': 'abstract_only'},
                'idea': 'Derived idea. ' * 100, 'experiment': ('EXPERIMENT-' + owner) * 250,
                'entities': 'Derived entities. ' * 50, 'references': []} for i in range(3)]
            return {'idea': 'Current proposal. ' * 150,
                'chain': {'evidence': evidence, 'trend': 'Generated trend. ' * 100, 'entities': 'x'},
                'future': 'Earlier brainstorming. ' * 100, 'human_considerations': 'unknown',
                'novelty': {'status': 'not_established', 'compared_papers': [evidence[0]['paper']] * 12},
                'rejected_attempts': []}
        own, peer = candidate('own'), candidate('peer')
        payload = {'own_candidate': own, 'target_candidate': peer,
                   'evidence_ids': [e['paper']['paper_id'] for e in own['chain']['evidence']]}
        before = deepcopy(payload)
        text, _ = prompt('critique', payload, {'status': 'text'}, 'v2')
        self.assertGreater(len(json.dumps(payload)), 60000)
        self.assertLess(len(text), 60000)
        compact = compact_payload('critique', payload)
        self.assertEqual(payload, before)
        self.assertEqual(compact['citable_source_ids'], payload['evidence_ids'])
        self.assertNotIn('EXPERIMENT-peer', text)
        for original in own['chain']['evidence']:
            records = list(compact['evidence_registry'].values())
            self.assertIn(original, records)
        view = compact_payload('report', {'candidate': own, 'evidence_ids': payload['evidence_ids']})
        for record in view['evidence_registry'].values():
            original = next(e for e in own['chain']['evidence'] if e['paper']['paper_id'] == record['paper']['paper_id'])
            self.assertEqual(record['paper'], original['paper'])
            self.assertNotIn('experiment', record)
            self.assertIn('view_scope', record)

    async def test_report_context_excludes_replayed_audit_and_preserves_evidence(self):
        from copy import deepcopy
        from sage.writing.report import proposal_context, supplied_references
        model = FixtureModel()
        result = await run('topic', model, FixtureSource())
        first = result.to_dict()
        replayed = deepcopy(first)
        replayed['audit'] = [{'replayed': 'large operational history' * 10000}]
        replayed['usage'] = {'elapsed_seconds': 999, 'actual_total_tokens': 12345}
        self.assertEqual(proposal_context(first), proposal_context(replayed))
        context = proposal_context(first)
        self.assertEqual(set(context['citable_source_ids']), {p['paper_id'] for p in supplied_references(first)})
        self.assertTrue(context['evidence_registry'])
        self.assertEqual(context['experiment']['proposal'], first['experiment']['proposal'])

    async def test_rejects_top_lexical_match_and_uses_relevant_backup(self):
        class Source(FixtureSource):
            async def search(self, query, **kwargs):
                return [Paper('unrelated', 'Other task'), self.papers['fixture-a-anchor']]
        model = FixtureModel(overrides={
            'discovery.queries': ['<queries>["topic"]</queries>'],
            'discovery.anchor_relevance': ['<relevant>0</relevant>', '<relevant>1</relevant>']})
        runtime = Runtime(model, model, Source(), RunConfig())
        anchors = await Discovery(runtime).anchors('topic', limit=1)
        self.assertEqual([p.paper_id for p in anchors], ['fixture-a-anchor'])
        self.assertTrue(any(e['status'] == 'rejected_irrelevant' for e in runtime.audit))
        self.assertEqual(runtime.usage['search_calls'], 1)

    async def test_missing_student_anchors_stops_before_expensive_chain_and_ideas(self):
        model = FixtureModel()
        result = await run('topic', model, FixtureSource(),
            config=RunConfig(discussion_mode='hybrid', discussion_students=3, max_candidates=3))
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'no_evidence')
        self.assertNotIn('literature.extract', model.calls)
        self.assertNotIn('ideation.generate', model.calls)
        self.assertEqual(result.candidates, [])

    async def test_short_first_chain_does_not_hide_available_reserve_anchors(self):
        class Source(FixtureSource):
            async def search(self, query, **kwargs):
                if query == 'reserve':
                    return [Paper('fixture-c-anchor', 'Synthetic c anchor', 'Insufficient evidence', 2022),
                            self.papers['fixture-a-anchor'], self.papers['fixture-b-anchor']]
                return await super().search(query, **kwargs)

            async def related(self, paper, **kwargs):
                if paper.paper_id.startswith('fixture-c-'):
                    return []
                return await super().related(paper, **kwargs)
        model = FixtureModel(overrides={'discovery.queries': ['<queries>["reserve"]</queries>']})
        result = await run('topic', model, Source(), config=RunConfig(discussion_mode='hybrid'))
        self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertEqual(len(result.candidates), 2)
        self.assertEqual(len(result.discussion['students']), 2)
        self.assertTrue(any(e['status'] == 'skipped_insufficient_evidence' for e in result.audit))
        self.assertTrue(result.validation['contract_passed'])


class DurableLaboratory(unittest.TestCase):
    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-m', 'sage', *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, timeout=60)

    def test_interrupted_writing_keeps_execution_and_resumes_without_regeneration(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'resumed'
            args = ['laboratory', '--mode', 'offline', '--backend', 'fixture', '--allow-execution',
                    '--discussion-mode', 'hybrid', '--output', str(first)]
            script = '''
import os
from sage.runtime import Runtime
original = Runtime.event
def stop(self, stage, status, **fields):
    original(self, stage, status, **fields)
    if stage == 'writing.section' and status == 'drafted':
        os._exit(77)
Runtime.event = stop
from sage.cli import main
main(ARGUMENTS)
'''.replace('ARGUMENTS', repr(args))
            process = subprocess.run([sys.executable, '-c', script], cwd=ROOT, timeout=60)
            self.assertEqual(process.returncode, 77)
            self.assertTrue((first / 'checkpoint.json').exists())
            partial = json.loads((first / 'result.partial.json').read_text())
            self.assertEqual(partial['execution']['status'], 'completed_fixture')
            self.assertEqual(partial['status'], 'writing_running')
            self.assertTrue(partial['report']['sections'][0]['commentary'])
            audit = [json.loads(line) for line in (first / 'audit.jsonl').read_text().splitlines()]
            self.assertEqual(audit[-1]['status'], 'drafted')
            resumed = self.cli(*args[:-1], second, '--resume', first / 'checkpoint.json')
            self.assertEqual(resumed.returncode, 0, resumed.stderr + '\n' + resumed.stdout)
            result = json.loads((second / 'result.json').read_text())
            self.assertEqual(result['status'], 'completed_fixture')
            new_events = result['audit'][len(audit):]
            self.assertFalse(any(e['status'] == 'started' and e.get('stage') in
                ('execution.generate', 'execution.reflect', 'discovery.queries') for e in new_events))
            self.assertTrue(any(e['status'] == 'cache_hit' for e in new_events))
            started = Counter(e.get('kind') for e in result['audit'] if e['status'] == 'started' and e.get('kind'))
            self.assertEqual(result['usage']['model_calls'], started['model'])
            self.assertEqual(result['usage']['search_calls'], started['search'])
            self.assertTrue((second / 'draft.md').exists())

    def test_failure_reports_nested_proposal_cause_in_cli_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'failed'
            process = self.cli('laboratory', '--max-model-calls', '1', '--output', output)
            self.assertEqual(process.returncode, 1)
            summary = json.loads(process.stdout)
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual(summary['errors'][0]['stage'], 'proposal')
            self.assertEqual(summary['errors'][0]['code'], 'budget_exceeded')
            self.assertEqual(result['errors'], summary['errors'])
            self.assertEqual(summary['proposal_status'], 'stopped')

    def test_checkpoint_is_bound_to_contract_and_execution_backend(self):
        from dataclasses import asdict
        from sage.execution.fixtures import fixture_contract
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first', Path(directory) / 'other'
            process = self.cli('laboratory', '--output', first)
            self.assertEqual(process.returncode, 0, process.stderr)
            changed = asdict(fixture_contract())
            changed['max_attempts'] += 1
            contract = Path(directory) / 'changed.json'
            contract.write_text(json.dumps(changed))
            process = self.cli('laboratory', '--output', second, '--contract', contract,
                               '--resume', first / 'checkpoint.json')
            self.assertEqual(process.returncode, 2)
            self.assertIn('Checkpoint is invalid', process.stderr)
            self.assertFalse((second / 'audit.jsonl').exists())

    def test_docker_resume_is_refused_before_any_execution_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'run'
            process = self.cli('laboratory', '--backend', 'docker', '--resume', 'unused.json', '--output', output)
            self.assertEqual(process.returncode, 2)
            self.assertIn('Docker execution cannot be resumed', process.stderr)
            self.assertFalse(output.exists())
