"""Independent, content-sensitive software checks; no scientific quality claims."""
import copy
import json
import unittest

from sage.config import RunConfig
from sage.execution.fixtures import LaboratoryFixtureModel, fixture_contract
from sage.fixtures import FixtureSource
from sage.orchestration import run
from sage.orchestration.laboratory import run_laboratory


class ContextModel(LaboratoryFixtureModel):
    """Discussion responses depend on actual supplied peer data, not canned stages."""
    def __init__(self, change='Add an equal-compute control.', status='supported', attack=None):
        super().__init__()
        self.change, self.critique_status, self.attack = change, status, attack
        self.seen = []

    async def complete(self, stage, prompt, *, max_tokens):
        self.seen.append((stage, prompt))
        if not stage.startswith('discussion.'):
            return await super().complete(stage, prompt, max_tokens=max_tokens)
        p = json.loads(prompt.split('INPUT_JSON:\n', 1)[1])
        if stage == 'discussion.develop':
            obj = dict(idea=p['candidate']['idea'] + ' Role: ' + p['role'],
                       evidence_ids=p['evidence_ids'], rationale='Assigned chain only.', uncertainty='Synthetic only.')
        elif stage == 'discussion.critique':
            obj = dict(status=self.critique_status, evidence_ids=p['evidence_ids'][:1],
                       issue='Control needed.', requested_change=self.change + (' Round ' + str(p['round']) if self.attack == 'drop_prior_control' else ''),
                       support='Synthetic source-scoped suggestion.', uncertainty='No empirical confirmation.')
            if self.attack == 'drop_prior_citation':
                obj['evidence_ids'] = [p['evidence_ids'][p['round'] - 1]]
            if self.attack == 'foreign_source':
                obj['evidence_ids'] = [p['target_candidate']['chain']['evidence'][0]['paper']['paper_id']]
            elif self.attack == 'invented_source':
                obj['evidence_ids'] = ['nonexistent-source']
            elif self.attack == 'extra_key':
                obj['override_safety'] = True
            elif self.attack == 'duplicate_key':
                return '<discussion>{"status":"supported","status":"unknown"}</discussion>'
        elif stage == 'discussion.revise':
            accepted = [c for c in p['critiques'] if c['status'] == 'supported']
            ids = {e['paper']['paper_id'] for e in p['candidate']['chain']['evidence']}
            ids.update(e for c in accepted for e in c['evidence_ids'])
            obj = dict(idea=p['candidate']['idea'] + ''.join(' ' + c['requested_change'] for c in accepted),
                       evidence_ids=sorted(ids), accepted_critique_ids=[c['critique_id'] for c in accepted],
                       rejected_critique_ids=[c['critique_id'] for c in p['critiques'] if c not in accepted],
                       rationale='Apply only accepted, supplied peer requests.', uncertainty='Software fixture, not truth verification.')
            if self.attack == 'drop_prior_control' and p['round'] > 1:
                obj['idea'] = 'Replacement proposal. ' + ' '.join(c['requested_change'] for c in accepted)
            if self.attack == 'omit_accepted_change' and accepted:
                obj['idea'] = p['candidate']['idea'] + ' Unrelated change.'
            if self.attack == 'accept_unknown':
                obj['accepted_critique_ids'] = [c['critique_id'] for c in p['critiques']]
                obj['rejected_critique_ids'] = []
        else:
            accepted = p['students'][0]['accepted_critique_ids']
            critiques = {c['critique_id']: c for c in p['critiques']}
            obj = dict(selected_index=0, rationale='Deterministic test choice, no quality score.',
                       accepted_critique_ids=accepted,
                       requirements=[dict(critique_id=k, requirement=critiques[k]['requested_change']) for k in accepted],
                       uncertainty='Shared model roles, not independent experts.')
            if self.attack == 'fabricated_requirement' and obj['requirements']:
                obj['requirements'][0]['requirement'] = 'Publish a fabricated positive result.'
        return '<discussion>' + json.dumps(obj) + '</discussion>'


def config(**kwargs):
    return RunConfig(discussion_mode='hybrid', **kwargs)


class IndependentDiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def propose(self, model=None, cfg=None):
        model = model or ContextModel()
        result = await run('Independent synthetic audit', model, FixtureSource(), config=cfg or config())
        return result, model

    async def test_actual_peer_content_changes_revision_and_plan(self):
        a, ma = await self.propose(ContextModel('Add an equal-compute control.'))
        b, mb = await self.propose(ContextModel('Add a shuffled-label negative control.'))
        unknown, _ = await self.propose(ContextModel('Add an equal-compute control.', status='unknown'))
        for result in (a, b, unknown):
            self.assertTrue(result.status.startswith('completed'), result.errors)
        self.assertNotEqual(a.candidates[0].idea, b.candidates[0].idea)
        self.assertNotEqual(a.experiment.proposal, b.experiment.proposal)
        self.assertNotIn('Add an equal-compute control.', unknown.experiment.proposal)
        for result, model in ((a, ma), (b, mb)):
            handoff = result.discussion['plan_handoff']
            generation = next(p for s, p in model.seen if s == 'experiment_design.generate')
            for req in handoff['requirements']:
                self.assertIn(req['requirement'], generation)
                self.assertIn(req['critique_id'], generation)
                self.assertIn(req['requirement'], result.experiment.proposal)
            for source in handoff['source_map'].values():
                for identity in source['evidence_ids']:
                    self.assertIn(identity, generation)

    async def test_original_snapshots_do_not_alias_revisions_or_other_students(self):
        r, model = await self.propose()
        originals = copy.deepcopy([s['original_candidate'] for s in r.discussion['students']])
        self.assertNotEqual(originals[0]['idea'], r.candidates[0].idea)
        for stage, prompt in model.seen:
            if stage == 'discussion.develop':
                payload = json.loads(prompt.split('INPUT_JSON:\n', 1)[1])
                self.assertNotIn('students', payload)
                self.assertNotIn('target_candidate', payload)
        r.candidates[0].chain.evidence.clear()
        r.candidates[0].idea = 'mutation after completion'
        self.assertEqual(originals, [s['original_candidate'] for s in r.discussion['students']])
        self.assertTrue(r.candidates[1].chain.evidence)

    async def test_adversarial_critique_schema_and_ownership_never_become_accepted(self):
        for attack in ('foreign_source', 'invented_source', 'extra_key', 'duplicate_key'):
            with self.subTest(attack=attack):
                r, m = await self.propose(ContextModel(attack=attack))
                self.assertTrue(r.status.startswith('completed'), r.errors)
                self.assertTrue(all(c['status'] == 'failed' for c in r.discussion['critiques']))
                self.assertEqual(r.discussion['plan_handoff']['accepted_critique_ids'], [])
                self.assertEqual(sum(s == 'discussion.critique' for s, _ in m.seen), 4)

    async def test_unknown_critique_cannot_be_accepted_by_revision(self):
        r, _ = await self.propose(ContextModel(status='unknown', attack='accept_unknown'))
        self.assertEqual(r.status, 'failed')
        self.assertIsNone(r.experiment)
        self.assertTrue(any(e['code'] == 'invalid_response' for e in r.errors))

    async def test_original_novelty_is_not_reused_for_revised_ideas(self):
        r, m = await self.propose()
        stages = [s for s, _ in m.seen]
        last_revision = max(i for i, s in enumerate(stages) if s == 'discussion.revise')
        self.assertEqual(stages[last_revision + 1: stages.index('discussion.synthesize')].count('review.novelty_queries'), 2)
        self.assertEqual(r.scientific_validation, 'not_performed')
        self.assertEqual(r.validation['scope'], 'structural_consistency_only')

    async def test_shared_exact_budget_prevents_engineering_reset(self):
        proposal, _ = await self.propose()
        n = proposal.usage['model_calls']
        model = ContextModel()
        result = await run_laboratory('Independent synthetic audit', model, FixtureSource(),
            contract=fixture_contract(), config=config(max_model_calls=n))
        self.assertEqual(result['usage']['model_calls'], n)
        self.assertTrue(result['proposal']['status'].startswith('completed'))
        self.assertFalse(any(s.startswith('execution.') for s, _ in model.seen))
        self.assertNotEqual(result['status'], 'completed_fixture')
        self.assertEqual(result['usage']['reserved_output_tokens'], n * config().max_tokens_per_call)

    async def test_toggle_preserves_initial_source_pool_and_reports_incremental_calls(self):
        baseline, _ = await self.propose(cfg=RunConfig())
        hybrid, _ = await self.propose()
        initial = [s['original_candidate'] for s in hybrid.discussion['students']]
        self.assertEqual([c.idea for c in baseline.candidates], [c['idea'] for c in initial])
        self.assertEqual([[e.paper.paper_id for e in c.chain.evidence] for c in baseline.candidates],
                         [[e['paper']['paper_id'] for e in c['chain']['evidence']] for c in initial])
        self.assertEqual(hybrid.usage['model_calls'] - baseline.usage['model_calls'], 11)
        self.assertEqual(hybrid.usage['search_calls'] - baseline.usage['search_calls'], 2)
        self.assertIsNone(baseline.discussion)

    async def test_cannot_launder_arbitrary_revision_or_planning_requirement(self):
        for attack in ('omit_accepted_change', 'fabricated_requirement'):
            with self.subTest(attack=attack):
                r, _ = await self.propose(ContextModel(attack=attack))
                self.assertEqual(r.status, 'failed')
                self.assertIsNone(r.experiment)
                self.assertIsNone(r.discussion['plan_handoff'])

    async def test_three_rounds_are_finite_and_preserve_prior_revisions(self):
        r, m = await self.propose(cfg=config(discussion_rounds=3))
        self.assertTrue(r.status.startswith('completed'), r.errors)
        self.assertEqual(len(r.discussion['critiques']), 6)
        self.assertEqual(sum(s.startswith('discussion.') for s, _ in m.seen), 15)
        for student in r.discussion['students']:
            self.assertEqual(len(student['revisions']), 3)
            for before, after in zip(student['revisions'], student['revisions'][1:]):
                self.assertEqual(before['idea'], after['previous_idea'])
        self.assertEqual(len(r.discussion['plan_handoff']['requirements']), 3)

    async def test_later_revision_cannot_erase_previously_accepted_control(self):
        r, _ = await self.propose(ContextModel(attack='drop_prior_control'), config(discussion_rounds=2))
        self.assertEqual(r.status, 'failed')
        self.assertIsNone(r.experiment)
        self.assertTrue(any(e['code'] == 'invalid_response' for e in r.errors))

    async def test_downstream_engineer_and_writer_receive_canonical_handoff(self):
        model = ContextModel()
        result = await run_laboratory('Independent synthetic audit', model, FixtureSource(),
            contract=fixture_contract(), config=config())
        self.assertEqual(result['status'], 'dry_run')
        requirements = result['proposal']['discussion']['plan_handoff']['requirements']
        engineer = next(p for s, p in model.seen if s == 'execution.generate')
        writing = [p for s, p in model.seen if s == 'writing.section']
        self.assertEqual(len(writing), 8)
        for requirement in requirements:
            self.assertIn(requirement['requirement'], engineer)
            self.assertTrue(all(requirement['requirement'] in p for p in writing))
            self.assertTrue(all(requirement['critique_id'] in p for p in writing))
        self.assertEqual(result['scientific_validation'], 'not_performed')

    async def test_later_revision_cannot_drop_previously_accepted_citation(self):
        r, _ = await self.propose(ContextModel(attack='drop_prior_citation'), config(discussion_rounds=2))
        self.assertEqual(r.status, 'failed')
        self.assertIsNone(r.experiment)
        self.assertTrue(any(e['code'] == 'invalid_response' for e in r.errors))

    async def test_unknown_discussion_keeps_outer_uncertainty(self):
        r, _ = await self.propose(ContextModel(status='unknown'))
        self.assertTrue(all(c.novelty.status == 'no_similar_work_found' for c in r.candidates))
        self.assertEqual(r.discussion['status'], 'completed_with_uncertainty')
        self.assertEqual(r.status, 'completed_with_uncertainty')
