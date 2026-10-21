import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from sage.config import RunConfig, profile_overrides
from sage.errors import ConfigurationError
from sage.fixtures import FixtureModel, FixtureSource
from sage.literature import Literature
from sage.literature.spans import extract_span_capsule
from sage.runtime import Runtime
from sage.types import Paper


class SemanticCapsulePipelineTests(unittest.IsolatedAsyncioTestCase):
    def screening_context(self, *, config=None):
        class Model(FixtureModel):
            def __init__(self):
                super().__init__()
                self.prompts = []

            async def complete(self, stage, prompt, *, max_tokens):
                self.prompts.append((stage, prompt))
                if stage == 'literature.span_capsule':
                    self.calls[stage] += 1
                    passages = json.loads(prompt.split('INPUT_PASSAGES: ', 1)[1])
                    return '<capsule>' + json.dumps({'claims': [
                        {'category': 'method', 'claim': 'SUPPORTED_METHOD', 'span_ids': [passages[0]['span_id']]},
                        {'category': 'results', 'claim': 'UNSUPPORTED_PER_TASK_COMPARISON', 'span_ids': [passages[0]['span_id']]},
                        {'category': 'data', 'claim': 'UNCERTAIN_SAMPLE_COUNT', 'span_ids': [passages[0]['span_id']]}],
                        'inferences': []}) + '</capsule>'
                if stage == 'literature.entailment':
                    self.calls[stage] += 1
                    batch = json.loads(prompt.split('INPUT_CLAIMS_AND_ORIGINAL_PASSAGES: ', 1)[1])
                    decisions = {'SUPPORTED_METHOD': 'supported',
                                 'UNSUPPORTED_PER_TASK_COMPARISON': 'unsupported',
                                 'UNCERTAIN_SAMPLE_COUNT': 'uncertain'}
                    return '<entailment>' + json.dumps({'claims': [{
                        'claim_id': item['claim_id'], 'verdict': decisions[item['claim']],
                        'source_span_ids': list(item['source_spans']),
                        'reason': 'Synthetic semantic decision; inspect the assigned verdict.',
                        'unsupported_details': [] if decisions[item['claim']] == 'supported'
                            else ['This assertion is not established by the supplied text.']}
                        for item in batch]}) + '</entailment>'
                return await super().complete(stage, prompt, max_tokens=max_tokens)
        model = Model()
        runtime = Runtime(model, model, FixtureSource(), config or RunConfig(
            evidence_mode='capsule', capsule_semantic_audit=True, capsule_max_chars=30000,
            refinement_rounds=0))
        paper = Paper('fixture-semantic', 'Synthetic semantic fixture', article={
            'sections': [{'heading': 'Method', 'text': 'The synthetic fixture defines a task and an observation.'}]},
            evidence_scope='synthetic_fixture')
        return model, runtime, Literature(runtime, None), paper

    async def test_rejected_semantic_claim_cannot_reenter_evidence_summary(self):
        class Model:
            async def complete(self, stage, prompt, *, max_tokens):
                if stage == 'literature.span_capsule':
                    return '<capsule>' + json.dumps({'claims': [
                        {'category': 'method', 'claim': 'SUPPORTED_CONDITION', 'span_ids': ['P1']},
                        {'category': 'results', 'claim': 'UNSUPPORTED_PER_TASK_COMPARISON', 'span_ids': ['P1']}],
                        'inferences': []}) + '</capsule>'
                batch = json.loads(prompt.split('INPUT_CLAIMS_AND_ORIGINAL_PASSAGES: ', 1)[1])
                return '<entailment>' + json.dumps({'claims': [{
                    'claim_id': item['claim_id'], 'verdict': 'supported' if index == 0 else 'unsupported',
                    'source_span_ids': list(item['source_spans']) if index == 0 else [],
                    'reason': 'Fixture: a located quote does not entail the extra per-task comparison.',
                    'unsupported_details': [] if index == 0 else ['The passage does not compare per-task metrics.']}
                    for index, item in enumerate(batch)]}) + '</entailment>'
        model = Model()
        runtime = Runtime(model, model, FixtureSource(), RunConfig(evidence_mode='capsule', capsule_max_chars=30000))
        result = await extract_span_capsule(runtime,
            Paper('fixture-paper', 'Fixture', abstract='The author defines records as tasks times generations.'),
            'Fixture', semantic_audit=True)
        self.assertIn('SUPPORTED_CONDITION', result.idea)
        self.assertNotIn('UNSUPPORTED_PER_TASK_COMPARISON', result.idea + result.experiment)
        self.assertEqual(result.capsule['unverified_claims'][0]['claim'], 'UNSUPPORTED_PER_TASK_COMPARISON')
        self.assertEqual(result.capsule['entailment_audit']['counts']['unsupported'], 1)
        self.assertIn('results', result.capsule['missing_categories'])

    async def test_literature_extract_routes_through_semantic_screen_and_caches_exact_input(self):
        model, runtime, literature, paper = self.screening_context()
        with patch('socket.create_connection', side_effect=AssertionError('Synthetic evidence attempted network')):
            result = await literature.extract(paper, 'Synthetic topic')
            calls, usage = dict(model.calls), dict(runtime.usage)
            repeated = await literature.extract(replace(paper), 'Synthetic topic')
        self.assertIs(repeated, result)
        self.assertEqual(dict(model.calls), calls)
        self.assertEqual(runtime.usage, usage)
        self.assertEqual(calls, {'literature.span_capsule': 1, 'literature.entailment': 1})
        self.assertIs(runtime.evidence_cards[paper.paper_id], result)
        self.assertIn('SUPPORTED_METHOD', result.idea)
        for rejected in ('UNSUPPORTED_PER_TASK_COMPARISON', 'UNCERTAIN_SAMPLE_COUNT'):
            self.assertNotIn(rejected, result.idea + result.experiment)
        self.assertEqual([c['claim'] for c in result.capsule['claims']], ['SUPPORTED_METHOD'])
        self.assertEqual({c['entailment_audit']['verdict'] for c in result.capsule['unverified_claims']},
                         {'unsupported', 'uncertain'})

    async def test_semantic_cache_distinguishes_changed_topic_and_source_text(self):
        model, _, literature, paper = self.screening_context()
        await literature.extract(paper, 'First topic')
        await literature.extract(paper, 'Different topic')
        changed = replace(paper, article={'sections': [{'heading': 'Method', 'text': 'Changed fixture source text.'}]})
        await literature.extract(changed, 'Different topic')
        self.assertEqual(model.calls['literature.span_capsule'], 3)
        self.assertEqual(model.calls['literature.entailment'], 3)

    async def test_real_ideation_and_plan_prompts_use_labelled_view_and_preserve_full_audit(self):
        from sage.ideation import Ideation
        from sage.experiment_design import ExperimentDesign
        from sage.types import Chain, NoveltyAssessment
        class Review:
            async def novelty(self, idea, topic):
                return NoveltyAssessment('not_established', [], [], 'Synthetic test, no novelty finding.')
            async def literature_suggestions(self, candidate, topic):
                return {'suggestions': 'Synthetic test only.'}
        model, runtime, literature, paper = self.screening_context()
        result = await literature.extract(paper, 'Synthetic topic')
        audit_card = next(e['capsule'] for e in runtime.audit
                          if e['stage'] == 'literature.evidence' and e['status'] == 'span_capsule_extracted')
        original_audit = json.dumps(audit_card, sort_keys=True)
        chain = Chain([result], '', '')
        candidate = await Ideation(runtime, Review()).generate(chain, 'Synthetic topic')
        await ExperimentDesign(runtime, None, Review()).generate(candidate, 'Synthetic topic')
        sent = {stage: prompt for stage, prompt in model.prompts
                if stage in ('ideation.generate', 'experiment_design.generate')}
        self.assertEqual(set(sent), {'ideation.generate', 'experiment_design.generate'})
        for prompt in sent.values():
            self.assertNotIn('claims_before_entailment', prompt)
            self.assertNotIn('"decisions":', prompt)
            for label in ('supported', 'unsupported', 'uncertain', 'unverified_claims', 'entailment_audit'):
                self.assertIn(label, prompt)
            self.assertIn('This assertion is not established by the supplied text.', prompt)
        self.assertEqual(json.dumps(audit_card, sort_keys=True), original_audit)
        self.assertEqual(len(audit_card['claims_before_entailment']), 3)
        self.assertEqual(len(audit_card['entailment_audit']['decisions']), 3)
        # The transport view is a deep copy, not a shared mutable audit object.
        result.capsule['unverified_claims'][0]['entailment_audit']['reason'] = 'Local test mutation'
        self.assertEqual(json.dumps(audit_card, sort_keys=True), original_audit)

    async def test_research_profile_enables_semantic_branch_with_valid_capacity(self):
        config = RunConfig(**profile_overrides('research'))
        self.assertTrue(config.capsule_semantic_audit)
        self.assertEqual(config.capsule_max_chars, 240000)
        model, _, literature, paper = self.screening_context(config=config)
        with patch('socket.create_connection', side_effect=AssertionError('Research fixture attempted network')):
            result = await literature.extract(paper, 'Synthetic profile input')
        self.assertEqual(result.capsule['schema_version'], 'sage.evidence_capsule.v2')
        self.assertEqual(model.calls['literature.entailment'], 1)

    async def test_explicit_legacy_capsule_mode_does_not_claim_semantic_audit(self):
        config = RunConfig(evidence_mode='capsule')
        self.assertFalse(config.capsule_semantic_audit)
        model, _, literature, paper = self.screening_context(config=config)
        result = await literature.extract(paper, 'Synthetic compatible input')
        self.assertEqual(model.calls['literature.capsule'], 1)
        self.assertEqual(model.calls['literature.entailment'], 0)
        self.assertEqual(result.capsule['schema_version'], 'sage.evidence_capsule.v1')
        self.assertNotIn('entailment_audit', result.capsule)

    async def test_semantic_switch_requires_boolean(self):
        for value in ('false', 0, 1, None):
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                RunConfig(capsule_semantic_audit=value)


if __name__ == '__main__':
    unittest.main()
