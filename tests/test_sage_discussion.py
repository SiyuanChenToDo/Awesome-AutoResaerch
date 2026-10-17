"""Hybrid discussion contract tests; providers are synthetic and never networked.

These exercise the owned controller and shared Runtime, not scientific quality.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sage.config import RunConfig
from sage.errors import ConfigurationError, ProviderError, TransientProviderError
from sage.execution.fixtures import LaboratoryFixtureModel, fixture_contract
from sage.fixtures import FixtureModel, FixtureSource
from sage.orchestration import run
from sage.orchestration.laboratory import run_laboratory
from sage.runtime import tags


class RecordingModel:
    """Record actual requests and optionally corrupt one kind of fixture reply."""

    embedding_enabled = False

    def __init__(self, model=None, transform=None):
        self.model = model or FixtureModel()
        self.transform = transform
        self.calls = Counter()
        self.requests = []

    async def complete(self, stage, prompt, *, max_tokens):
        self.calls[stage] += 1
        self.requests.append((stage, prompt))
        response = await self.model.complete(stage, prompt, max_tokens=max_tokens)
        if self.transform:
            response = self.transform(stage, response, self.calls[stage])
        return response


def transform_discussion(stage_to_change, change):
    def transform(stage, response, occurrence):
        if stage != stage_to_change:
            return response
        payload = json.loads(tags(response, ('discussion',))['discussion'])
        change(payload, occurrence)
        return '<discussion>' + json.dumps(payload) + '</discussion>'
    return transform


class DiscussionConfigurationTests(unittest.TestCase):
    def test_discussion_is_opt_in_with_finite_defaults(self):
        config = RunConfig()
        self.assertEqual(config.discussion_mode, 'none')
        self.assertEqual(config.discussion_students, 2)
        self.assertEqual(config.discussion_rounds, 1)
        self.assertEqual(config.to_dict()['discussion_mode'], 'none')

    def test_invalid_discussion_configuration_is_rejected(self):
        cases = (
            {'discussion_mode': 'unbounded'},
            {'discussion_mode': True},
            {'discussion_students': 0},
            {'discussion_students': -1},
            {'discussion_students': True},
            {'discussion_students': '2'},
            {'discussion_students': 1},
            {'discussion_students': 5},
            {'discussion_rounds': 0},
            {'discussion_rounds': -1},
            {'discussion_rounds': True},
            {'discussion_rounds': '1'},
            {'discussion_rounds': 4},
            {'discussion_prompt_version': 'self-editing'},
            {'discussion_mode': 'hybrid', 'max_candidates': 1},
            {'discussion_mode': 'hybrid', 'max_candidates': '2'},
            {'discussion_mode': 'hybrid', 'max_candidates': None},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ConfigurationError):
                RunConfig(**values)


class HybridDiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def execute(self, model=None, source=None, config=None):
        with patch('socket.create_connection', side_effect=AssertionError('Offline discussion attempted network')):
            return await run('Synthetic discussion topic', model or FixtureModel(),
                             source or FixtureSource(), config=config or RunConfig(discussion_mode='hybrid'))

    def assert_accounted(self, result, config):
        for kind in ('model', 'search'):
            count = sum(event['status'] == 'started' and event.get('kind') == kind
                        for event in result.audit)
            self.assertEqual(result.usage[kind + '_calls'], count)
            self.assertLessEqual(count, getattr(config, 'max_' + kind + '_calls'))
        self.assertLessEqual(result.usage['reserved_output_tokens'], config.max_reserved_output_tokens)
        self.assertTrue(result.validation['contract_passed'], result.validation['issues'])

    async def test_default_and_explicit_none_preserve_baseline(self):
        default_model, explicit_model = RecordingModel(), RecordingModel()
        default = await self.execute(model=default_model, config=RunConfig())
        explicit = await self.execute(model=explicit_model, config=RunConfig(discussion_mode='none'))
        self.assertEqual(default.status, 'completed')
        self.assertIsNone(default.discussion)
        self.assertIsNone(explicit.discussion)
        self.assertFalse(any(stage.startswith('discussion.') for stage, _ in default_model.requests))
        self.assertEqual(default.usage['model_calls'], 44)
        self.assertEqual(default.usage['search_calls'], 15)
        left, right = default.to_dict(), explicit.to_dict()
        left['usage'].pop('elapsed_seconds', None)
        right['usage'].pop('elapsed_seconds', None)
        self.assertEqual(left, right)
        self.assertEqual(default_model.requests, explicit_model.requests)

    async def test_hybrid_preserves_distinct_origins_and_grounded_handoff(self):
        model = RecordingModel()
        config = RunConfig(discussion_mode='hybrid')
        result = await self.execute(model=model, config=config)
        baseline = await self.execute(config=RunConfig())
        self.assertTrue(result.status.startswith('completed'), result.errors)
        ledger = result.discussion
        self.assertEqual(ledger['status'], 'completed_with_uncertainty')
        self.assertEqual(len(ledger['students']), 2)
        students = {student['student_id']: student for student in ledger['students']}
        self.assertEqual(len(students), 2)
        self.assertEqual(len({student['role'] for student in students.values()}), 2)
        self.assertEqual({student['candidate_index'] for student in students.values()}, {0, 1})
        origins = []
        for student in students.values():
            index = student['candidate_index']
            original = student['original_candidate']
            self.assertEqual(original, baseline.to_dict()['candidates'][index])
            origins.append({entry['paper']['paper_id'] for entry in original['chain']['evidence']})
            self.assertTrue(student['revisions'])
            self.assertEqual(result.candidates[index].idea, student['revisions'][-1]['idea'])
            self.assertNotEqual(result.candidates[index].idea, original['idea'])
        self.assertNotEqual(origins[0], origins[1])
        all_evidence_ids = set.union(*origins)
        critiques = {critique['critique_id']: critique for critique in ledger['critiques']}
        self.assertEqual(len(critiques), 2)
        for critique in critiques.values():
            self.assertIn(critique['author_id'], students)
            self.assertIn(critique['target_id'], students)
            self.assertNotEqual(critique['author_id'], critique['target_id'])
            self.assertIn(critique['status'], ('supported', 'unknown'))
            if critique['status'] == 'supported':
                self.assertTrue(critique['evidence_ids'])
            self.assertLessEqual(set(critique['evidence_ids']), all_evidence_ids)
            self.assertLessEqual(set(critique['evidence_ids']), set(students[critique['author_id']]['evidence_ids']))
            self.assertTrue(critique['issue'])
            self.assertTrue(critique['requested_change'])
        for student in students.values():
            for revision in student['revisions']:
                for critique_id in revision['accepted_critique_ids']:
                    self.assertEqual(critiques[critique_id]['target_id'], student['student_id'])
                    self.assertEqual(critiques[critique_id]['status'], 'supported')
        synthesis, handoff = ledger['synthesis'], ledger['plan_handoff']
        self.assertEqual(synthesis['selected_index'], result.selected_index)
        self.assertTrue(synthesis['rationale'])
        self.assertEqual(handoff['candidate_index'], result.selected_index)
        self.assertEqual(handoff['accepted_critique_ids'], synthesis['accepted_critique_ids'])
        self.assertTrue(handoff['accepted_critique_ids'])
        self.assertLessEqual(set(handoff['accepted_critique_ids']), set(critiques))
        self.assertTrue(handoff['requirements'])
        generation_prompt = next(prompt for stage, prompt in model.requests if stage == 'experiment_design.generate')
        for requirement in handoff['requirements']:
            self.assertIn(requirement['requirement'], generation_prompt)
            self.assertEqual(requirement['requirement'], critiques[requirement['critique_id']]['requested_change'])
            self.assertIn(requirement['requirement'], result.experiment.proposal)
        self.assertTrue(handoff['bound_to_plan'])
        self.assertNotEqual(result.selected_index, baseline.selected_index)
        self.assertEqual(result.usage['model_calls'], baseline.usage['model_calls'] + 11)
        self.assertEqual(result.usage['search_calls'], baseline.usage['search_calls'] + 2)
        for stage, count in (('discussion.develop', 2), ('discussion.critique', 2),
                             ('discussion.revise', 2), ('discussion.synthesize', 1)):
            self.assertEqual(model.calls[stage], count)
        self.assertEqual(result.experiment.status, 'proposal_only')
        self.assertEqual(result.scientific_validation, 'not_performed')
        self.assertFalse(result.validation['scientific_quality_assessed'])
        self.assert_accounted(result, config)
        json.dumps(result.to_dict(), allow_nan=False)

    async def test_multiple_rounds_remain_bounded_and_keep_history(self):
        model = RecordingModel()
        config = RunConfig(discussion_mode='hybrid', discussion_rounds=2)
        result = await self.execute(model=model, config=config)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertEqual(model.calls['discussion.develop'], 2)
        self.assertEqual(model.calls['discussion.critique'], 4)
        self.assertEqual(model.calls['discussion.revise'], 4)
        self.assertEqual(model.calls['discussion.synthesize'], 1)
        self.assertEqual(len(result.discussion['critiques']), 4)
        self.assertEqual(len({item['critique_id'] for item in result.discussion['critiques']}), 4)
        self.assertTrue(all(len(student['revisions']) >= 2 for student in result.discussion['students']))
        self.assert_accounted(result, config)

    async def test_planner_receives_exact_accepted_peer_evidence_cards(self):
        model = RecordingModel()
        result = await self.execute(model=model)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        handoff = result.discussion['plan_handoff']
        generation_prompt = next(prompt for stage, prompt in model.requests if stage == 'experiment_design.generate')
        serialized = generation_prompt.split('Discussion planning handoff: ', 1)[1]
        delivered, _ = json.JSONDecoder().raw_decode(serialized)
        self.assertEqual(delivered['source_map'], handoff['source_map'])
        self.assertEqual(set(delivered['source_map']), set(handoff['accepted_critique_ids']))
        students = {student['student_id']: student for student in result.discussion['students']}
        selected_ids = {entry.paper.paper_id for entry in result.candidates[result.selected_index].chain.evidence}
        peer_only_ids = set()
        for source in delivered['source_map'].values():
            author = students[source['author_id']]
            original = {entry['paper']['paper_id']: entry for entry in author['original_candidate']['chain']['evidence']}
            self.assertEqual([card['paper']['paper_id'] for card in source['evidence']], source['evidence_ids'])
            for card in source['evidence']:
                identity = card['paper']['paper_id']
                expected = original[identity]
                self.assertEqual(set(card), {'paper', 'idea', 'experiment', 'entities'})
                self.assertEqual(card['paper'], {key: expected['paper'][key] for key in
                    ('paper_id', 'title', 'abstract', 'year', 'url', 'evidence_scope', 'publication_date')})
                self.assertEqual(card['idea'], expected['idea'])
                self.assertEqual(card['experiment'], expected['experiment'])
                self.assertEqual(card['entities'], expected['entities'])
                self.assertNotIn('article', card['paper'])
                if identity not in selected_ids:
                    peer_only_ids.add(identity)
        self.assertTrue(peer_only_ids, 'Fixture must exercise peer evidence absent from the selected student chain')

    async def test_fixed_prompt_versions_are_audited_without_self_editing(self):
        versions = {}
        for version in ('v1', 'v2'):
            with self.subTest(version=version):
                result = await self.execute(config=RunConfig(discussion_mode='hybrid', discussion_prompt_version=version))
                self.assertTrue(result.status.startswith('completed'), result.errors)
                history = result.discussion['prompt_history']
                self.assertEqual(len(history), 7)
                self.assertEqual({entry['version'] for entry in history}, {version})
                for entry in history:
                    self.assertRegex(entry['template_sha256'], r'^[a-f0-9]{64}$')
                    self.assertIn('no self-editing', entry['revision_policy'])
                versions[version] = {entry['stage']: entry['template_sha256'] for entry in history}
        self.assertEqual(set(versions['v1']), {'develop', 'critique', 'revise', 'synthesize'})
        self.assertTrue(all(versions['v1'][stage] != versions['v2'][stage] for stage in versions['v1']))

    async def test_missing_second_chain_stops_instead_of_inventing_a_student(self):
        class OneAnchor(FixtureSource):
            async def search(self, query, **kwargs):
                if query == 'sage-fixture-b':
                    return [self.papers['fixture-a-anchor']]
                return await super().search(query, **kwargs)
        model = RecordingModel()
        config = RunConfig(discussion_mode='hybrid')
        result = await self.execute(model=model, source=OneAnchor(), config=config)
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'no_evidence')
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.discussion['students'], [])
        self.assertFalse(any(stage.startswith('discussion.') for stage in model.calls))
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)

    async def test_duplicate_source_portfolios_do_not_create_independent_students(self):
        class SharedPortfolio(FixtureSource):
            async def related(self, paper, *, direction, limit):
                if direction == 'citations' and paper.paper_id.endswith('-anchor'):
                    family = 'b' if paper.paper_id == 'fixture-a-anchor' else 'a'
                    return [self.papers[f'fixture-{family}-anchor']]
                return []
        model = RecordingModel()
        config = RunConfig(discussion_mode='hybrid', max_chain_length=2)
        result = await self.execute(model=model, source=SharedPortfolio(), config=config)
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'no_evidence')
        self.assertEqual(len(result.candidates), 2)
        portfolios = [{entry.paper.paper_id for entry in candidate.chain.evidence} for candidate in result.candidates]
        self.assertEqual(portfolios[0], portfolios[1])
        self.assertFalse(any(stage.startswith('discussion.') for stage in model.calls))
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)

    async def test_original_candidate_is_an_independent_snapshot(self):
        result = await self.execute()
        student = result.discussion['students'][0]
        original = deepcopy(student['original_candidate'])
        candidate = result.candidates[student['candidate_index']]
        candidate.idea = 'Modified after the run'
        candidate.chain.trend = 'Modified chain after the run'
        candidate.rejected_attempts.append({'idea': 'Modified rejection'})
        self.assertEqual(student['original_candidate'], original)

    async def test_unknown_critiques_cannot_become_accepted_requirements(self):
        def unknown(payload, occurrence):
            payload['status'] = 'unknown'
            payload['evidence_ids'] = []
        model = RecordingModel(transform=transform_discussion('discussion.critique', unknown))
        result = await self.execute(model=model)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        ledger = result.discussion
        self.assertTrue(all(critique['status'] == 'unknown' for critique in ledger['critiques']))
        for student in ledger['students']:
            self.assertTrue(all(not revision['accepted_critique_ids'] for revision in student['revisions']))
        self.assertEqual(ledger['synthesis']['accepted_critique_ids'], [])
        self.assertEqual(ledger['plan_handoff']['accepted_critique_ids'], [])
        self.assertEqual(ledger['plan_handoff']['requirements'], [])

    async def test_malformed_discussion_response_retries_and_preserves_origins(self):
        config = RunConfig(discussion_mode='hybrid')
        model = FixtureModel(overrides={'discussion.develop': ['untagged'] * config.retry_attempts})
        result = await self.execute(model=model, config=config)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.errors[-1]['code'], 'invalid_response')
        self.assertEqual(model.calls['discussion.develop'], config.retry_attempts)
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNone(result.experiment)
        self.assertIsNotNone(result.discussion)
        self.assertEqual(result.discussion['status'], 'failed')
        self.assert_accounted(result, config)

    async def test_discussion_json_rejects_duplicate_keys_extra_fields_and_nonobjects(self):
        valid = {'idea': 'Synthetic proposal', 'evidence_ids': ['fixture-a-root'],
                 'rationale': 'Synthetic control only.', 'uncertainty': 'Unverified.'}
        extra = {**valid, 'grant_execution_permission': True}
        duplicate = json.dumps(valid)[:-1] + ', "idea": "Duplicate replacement"}'
        for payload in ('[]', 'null', json.dumps(extra), duplicate):
            with self.subTest(payload=payload):
                config = RunConfig(discussion_mode='hybrid')
                response = '<discussion>' + payload + '</discussion>'
                model = FixtureModel(overrides={'discussion.develop': [response] * config.retry_attempts})
                result = await self.execute(model=model, config=config)
                self.assertEqual(result.status, 'failed')
                self.assertEqual(result.errors[-1]['code'], 'invalid_response')
                self.assertEqual(model.calls['discussion.develop'], config.retry_attempts)
                self.assertIsNone(result.experiment)
                self.assert_accounted(result, config)

    async def test_fabricated_critique_evidence_is_never_accepted(self):
        def fabricated(payload, occurrence):
            payload['evidence_ids'] = ['invented-paper-not-in-retrieval']
        config = RunConfig(discussion_mode='hybrid')
        model = RecordingModel(transform=transform_discussion('discussion.critique', fabricated))
        result = await self.execute(model=model, config=config)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertEqual(result.discussion['status'], 'completed_with_uncertainty')
        self.assertEqual(model.calls['discussion.critique'], 2 * config.retry_attempts)
        self.assertTrue(all(critique['status'] == 'failed' for critique in result.discussion['critiques']))
        self.assertTrue(all(critique['error_code'] == 'invalid_response' for critique in result.discussion['critiques']))
        self.assertTrue(all(not student['accepted_critique_ids'] for student in result.discussion['students']))
        self.assertEqual(result.discussion['plan_handoff']['requirements'], [])
        self.assert_accounted(result, config)

    async def test_revision_cannot_accept_a_nonexistent_critique(self):
        def fabricated(payload, occurrence):
            payload['accepted_critique_ids'] = ['invented-critique']
        config = RunConfig(discussion_mode='hybrid')
        model = RecordingModel(transform=transform_discussion('discussion.revise', fabricated))
        result = await self.execute(model=model, config=config)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.errors[-1]['code'], 'invalid_response')
        self.assertEqual(model.calls['discussion.revise'], config.retry_attempts)
        self.assertEqual(model.calls['discussion.synthesize'], 0)
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)

    async def test_synthesis_cannot_select_a_nonexistent_candidate(self):
        def fabricated(payload, occurrence):
            payload['selected_index'] = 999
        config = RunConfig(discussion_mode='hybrid')
        model = RecordingModel(transform=transform_discussion('discussion.synthesize', fabricated))
        result = await self.execute(model=model, config=config)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.errors[-1]['code'], 'invalid_response')
        self.assertEqual(model.calls['discussion.synthesize'], config.retry_attempts)
        self.assertEqual(model.calls['experiment_design.generate'], 0)
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)

    async def test_transient_discussion_failure_retries_with_shared_accounting(self):
        success = await self.execute()
        config = RunConfig(discussion_mode='hybrid')
        model = FixtureModel(overrides={'discussion.develop': [TransientProviderError('private-provider-token')]})
        result = await self.execute(model=model, config=config)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertEqual(result.usage['model_calls'], success.usage['model_calls'] + 1)
        self.assertNotIn('private-provider-token', json.dumps(result.to_dict()))
        failed = [event for event in result.audit
                  if event['stage'] == 'discussion.develop' and event['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['error_code'], 'transient_provider_error')
        self.assert_accounted(result, config)

    async def test_permanent_discussion_failure_is_sanitized_and_not_retried(self):
        config = RunConfig(discussion_mode='hybrid')
        model = FixtureModel(overrides={'discussion.critique': [ProviderError('private-provider-token')]})
        result = await self.execute(model=model, config=config)
        self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertEqual(model.calls['discussion.critique'], 2)
        self.assertNotIn('private-provider-token', json.dumps(result.to_dict()))
        failed = [critique for critique in result.discussion['critiques'] if critique['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['error_code'], 'provider_error')
        self.assertEqual(result.discussion['plan_handoff']['accepted_critique_ids'], [])
        self.assert_accounted(result, config)

    async def test_model_budget_exhaustion_inside_discussion_preserves_partial_ledger(self):
        reference_model = RecordingModel()
        await self.execute(model=reference_model)
        first = next(index for index, (stage, _) in enumerate(reference_model.requests)
                     if stage.startswith('discussion.'))
        limit = first + 1
        config = RunConfig(discussion_mode='hybrid', max_model_calls=limit)
        model = RecordingModel()
        result = await self.execute(model=model, config=config)
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'budget_exceeded')
        self.assertEqual(result.usage['model_calls'], limit)
        self.assertEqual(sum(count for stage, count in model.calls.items() if stage.startswith('discussion.')), 1)
        self.assertEqual(len(result.candidates), 2)
        self.assertIsNotNone(result.discussion)
        self.assertEqual(result.discussion['status'], 'stopped')
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)

    async def test_output_token_budget_is_shared_with_discussion(self):
        reference_model = RecordingModel()
        await self.execute(model=reference_model)
        first = next(index for index, (stage, _) in enumerate(reference_model.requests)
                     if stage.startswith('discussion.'))
        config = RunConfig(discussion_mode='hybrid', max_reserved_output_tokens=(first + 1) * 2000)
        result = await self.execute(config=config)
        self.assertEqual(result.status, 'stopped')
        self.assertEqual(result.errors[-1]['code'], 'budget_exceeded')
        self.assertEqual(result.usage['reserved_output_tokens'], config.max_reserved_output_tokens)
        self.assertEqual(result.usage['model_calls'], first + 1)
        self.assertIsNotNone(result.discussion)
        self.assertIsNone(result.experiment)
        self.assert_accounted(result, config)


class HybridLaboratoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_composes_with_unexecuted_laboratory_and_one_budget(self):
        model = RecordingModel(LaboratoryFixtureModel())
        config = RunConfig(discussion_mode='hybrid')
        with patch('socket.create_connection', side_effect=AssertionError('Offline laboratory attempted network')):
            result = await run_laboratory('Synthetic discussion topic', model, FixtureSource(),
                                          contract=fixture_contract(), config=config)
        self.assertEqual(result['status'], 'dry_run', result['errors'])
        self.assertEqual(result['proposal']['discussion']['status'], 'completed_with_uncertainty')
        self.assertEqual(result['execution']['attempts'][0]['status'], 'syntax_valid_unexecuted')
        self.assertEqual(result['execution']['attempts'][0]['metrics'], {})
        self.assertEqual(result['execution']['contract_digest'], fixture_contract().sha256)
        self.assertIn('DRY RUN', result['report']['markdown'])
        self.assertEqual(result['scientific_validation'], 'not_performed')
        self.assertGreater(result['usage']['model_calls'], result['proposal']['usage']['model_calls'])
        started = sum(event['status'] == 'started' and event.get('kind') == 'model' for event in result['audit'])
        self.assertEqual(result['usage']['model_calls'], started)
        self.assertEqual(result['usage']['model_calls'], sum(model.calls.values()))
        self.assertLessEqual(result['usage']['model_calls'], config.max_model_calls)
        stages = [stage for stage, _ in model.requests]
        self.assertLess(stages.index('discussion.synthesize'), stages.index('experiment_design.generate'))
        self.assertLess(stages.index('experiment_design.generate'), stages.index('execution.generate'))
        json.dumps(result, allow_nan=False)


class HybridCLITests(unittest.TestCase):
    def test_both_entrypoints_persist_explicit_discussion_configuration(self):
        for command in ('run', 'laboratory'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'hybrid'
                process = subprocess.run(
                    [sys.executable, '-m', 'sage', command, '--mode', 'offline',
                     '--discussion-mode', 'hybrid', '--discussion-students', '2',
                     '--discussion-rounds', '1', '--discussion-prompt-version', 'v1',
                     '--output', str(output)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                result = json.loads((output / 'result.json').read_text())
                config = json.loads((output / 'config.json').read_text())
                self.assertEqual(config['discussion_mode'], 'hybrid')
                self.assertEqual(config['discussion_students'], 2)
                self.assertEqual(config['discussion_rounds'], 1)
                self.assertEqual(config['discussion_prompt_version'], 'v1')
                proposal = result if command == 'run' else result['proposal']
                self.assertEqual(proposal['discussion']['status'], 'completed_with_uncertainty')
                self.assertEqual(proposal['scientific_validation'], 'not_performed')
                self.assertTrue((output / 'audit.jsonl').read_text())
                if command == 'laboratory':
                    self.assertEqual(result['status'], 'dry_run')
                    self.assertTrue((output / 'report.md').exists())

    def test_invalid_hybrid_bounds_are_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'invalid'
            process = subprocess.run(
                [sys.executable, '-m', 'sage', 'run', '--discussion-mode', 'hybrid',
                 '--discussion-students', '3', '--max-candidates', '2', '--output', str(output)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(process.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
