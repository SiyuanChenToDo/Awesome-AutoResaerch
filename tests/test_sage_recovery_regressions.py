"""Sanitized structural reproductions of the observed live failures; no network."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from sage.checkpoints import Checkpoint, identity, digest
from sage.config import RunConfig
from sage.discovery import Discovery
from sage.discussion import evidence_ids
from sage.discussion.context import compact_payload
from sage.discussion.prompts import prompt
from sage.errors import (InvalidResponse, TruncatedResponse, ConfigurationError,
                         ProviderError, TransientProviderError, RetrievalUnavailable)
from sage.experiment_design.contract import parse_contract, fixture_contract
from sage.fixtures import FixtureModel, FixtureSource
from sage.orchestration import run
from sage.review import Review
from sage.runtime import Runtime


class ContextRegressions(unittest.TestCase):
    def evidence(self, key):
        return {'paper': {'paper_id': key, 'title': 'Sanitized paper ' + key,
                         'abstract': 'abstract body ' * 100, 'evidence_scope': 'abstract_only',
                         'url': 'https://arxiv.org/abs/0000.00000'},
                'idea': 'source interpretation', 'experiment': 'not performed',
                'entities': 'entities', 'references': []}

    def candidate(self, key):
        return {'idea': 'Current proposal with critical control ' + key,
                'chain': {'evidence': [self.evidence(key)], 'trend': 'unknown', 'entities': 'x'},
                'novelty': {'status': 'not_established', 'compared_papers': []}, 'rejected_attempts': []}

    def test_foreign_source_visible_is_not_permission_to_cite(self):
        p = {'student_id': 'phd-1', 'evidence_ids': ['own'],
             'own_candidate': self.candidate('own'), 'target_candidate': self.candidate('peer')}
        text, _ = prompt('critique', p, {'status': 'text'}, 'v2')
        data = json.loads(text.split('INPUT_JSON:\n')[1])
        self.assertEqual(data['citable_source_ids'], ['own'])
        self.assertEqual(data['target_source_ids_not_citable'], ['peer'])
        self.assertIn('ONLY from citable_source_ids', text)
        with self.assertRaises(InvalidResponse):
            evidence_ids(['peer'], ['own'])
        evidence_ids(['own'], ['own'])

    def test_synthesis_deduplicates_history_without_losing_evidence_or_acceptance(self):
        candidates = [self.candidate('own'), self.candidate('peer')]
        students = []
        for i, candidate in enumerate(candidates):
            students.append({'student_id': 'phd-' + str(i+1), 'role': 'role', 'candidate_index': i,
                'evidence_ids': [candidate['chain']['evidence'][0]['paper']['paper_id']],
                'accepted_critique_ids': ['accepted-' + str(i)],
                'original_candidate': {**candidate, 'idea': 'discardable prior copy ' * 6000},
                'development': {'idea': 'prior development ' * 4000, 'uncertainty': 'unknown'},
                'revisions': [{'previous_idea': 'old copy ' * 6000, 'idea': candidate['idea'],
                    'accepted_critique_ids': ['accepted-' + str(i)], 'evidence_ids': ['own'],
                    'rationale': 'keep exact required control', 'round': 1}]})
        payload = {'students': students, 'candidates': candidates,
                   'critiques': [{'critique_id': 'accepted-0', 'requested_change': 'EXACT REQUIRED CONTROL',
                                 'evidence_ids': ['own'], 'status': 'supported'}]}
        before = deepcopy(payload)
        self.assertGreater(len(json.dumps(payload)), 100000)
        compact = compact_payload('synthesize', payload)
        self.assertLess(len(json.dumps(compact)), 100000)
        self.assertEqual(payload, before)
        self.assertEqual(compact['critiques'], payload['critiques'])
        self.assertEqual(compact['candidates'][0]['idea'], candidates[0]['idea'])
        ref = compact['candidates'][0]['chain']['evidence'][0]['evidence_ref']
        card = compact['evidence_registry'][ref]
        original_card = candidates[0]['chain']['evidence'][0]
        self.assertEqual(card['paper'], original_card['paper'])
        self.assertEqual(card['full_evidence_sha256'], digest(original_card))
        self.assertNotIn('experiment', card)
        self.assertNotIn('idea', card)
        self.assertEqual(compact['students'][0]['accepted_critique_ids'], ['accepted-0'])
        self.assertEqual(compact['students'][0]['history_sha256'], digest(students[0]))

    def test_different_extractions_are_not_silently_overwritten(self):
        a = self.candidate('same'); b = deepcopy(a)
        b['chain']['evidence'][0]['idea'] = 'conflicting interpretation'
        result = compact_payload('develop', {'candidate': a, 'peer': b, 'evidence_ids': ['same']})
        self.assertEqual(len(result['evidence_registry']), 2)

    def test_plan_requires_explicit_unresolved_decisions_and_never_execution_approval(self):
        value = fixture_contract()
        self.assertEqual(parse_contract(json.dumps(value)), value)
        for mutate in (lambda v: v.update(execution_ready=True),
                       lambda v: v.pop('metrics'),
                       lambda v: v['sample_size'].update(status='proposed'),
                       lambda v: v['metrics'][0].update(denominator='')):
            bad = deepcopy(value); mutate(bad)
            with self.assertRaises(InvalidResponse): parse_contract(json.dumps(bad))


class RuntimeRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_plan_recovery_changes_request_not_cap_or_validation(self):
        class Model:
            def __init__(self): self.requests = []
            async def complete(self, stage, prompt, *, max_tokens):
                self.requests.append((prompt, max_tokens))
                if len(self.requests) == 1: raise TruncatedResponse('bounded fake length finish')
                return '<experiment>complete concise plan</experiment>'
        model = Model(); rt = Runtime(model, model, FixtureSource(), RunConfig(max_tokens_per_call=3000))
        result = await rt.ask('experiment_design.refine', 'plan inputs', ('experiment',))
        self.assertEqual(result['experiment'], 'complete concise plan')
        self.assertNotIn('RECOVERY AFTER TRUNCATION', model.requests[0][0])
        self.assertIn('RECOVERY AFTER TRUNCATION', model.requests[1][0])
        self.assertEqual([x[1] for x in model.requests], [3000, 3000])
        self.assertEqual(rt.usage['model_calls'], 2)
        self.assertEqual(rt.usage['reserved_output_tokens'], 6000)
        sent = [e for e in rt.audit if e['status'] == 'request_metadata']
        self.assertEqual([e['policy'] for e in sent], ['base', 'concise_complete_v1'])
        self.assertNotEqual(sent[0]['input_sha256'], sent[1]['input_sha256'])

    async def test_repeated_truncation_exhausts_budget_never_returns_partial(self):
        class Model:
            async def complete(self, *a, **kw): raise TruncatedResponse('partial')
        model = Model(); rt = Runtime(model, model, FixtureSource(), RunConfig(retry_attempts=2))
        with self.assertRaises(TruncatedResponse):
            await rt.ask('experiment_design.generate', 'inputs', ('experiment',))
        self.assertEqual(rt.usage['model_calls'], 2)

    async def test_oversized_core_evidence_is_not_silently_truncated(self):
        model = FixtureModel(); rt = Runtime(model, model, FixtureSource(), RunConfig(max_prompt_chars=500))
        from sage.errors import BudgetExceeded
        with self.assertRaises(BudgetExceeded):
            await rt.ask('discussion.critique', 'critical evidence ' * 100, ('discussion',))
        self.assertEqual(rt.usage['model_calls'], 0)

    async def test_incomplete_novelty_explicit_only_and_never_auth_bypass(self):
        class DiscoveryFailure:
            async def search(self, *a, **kw): raise TransientProviderError('rate limited')
        for enabled in (False, True):
            model = FixtureModel(); rt = Runtime(model, model, FixtureSource(), RunConfig(), allow_incomplete_novelty=enabled)
            review = Review(rt, DiscoveryFailure())
            if enabled:
                result = await review.novelty('idea', 'topic')
                self.assertEqual(result.status, 'not_established')
                self.assertEqual(result.compared_papers, [])
            else:
                with self.assertRaises(TransientProviderError): await review.novelty('idea', 'topic')
        class Denied:
            async def search(self, *a, **kw): raise ProviderError('denied')
        with self.assertRaises(ProviderError): await Review(rt, Denied()).novelty('idea', 'topic')

    async def test_missing_chain_evidence_still_stops(self):
        class EmptySource(FixtureSource):
            async def search(self, *a, **kw): return []
        model=FixtureModel();source=EmptySource();cfg=RunConfig()
        rt=Runtime(model,model,source,cfg,allow_incomplete_novelty=True)
        result=await run('topic',model,source,config=cfg,runtime=rt)
        self.assertEqual(result.status,'stopped')
        self.assertEqual(result.candidates,[])

    async def test_checkpoint_resume_replays_complete_run_without_paid_regeneration(self):
        cfg = RunConfig(discussion_mode='hybrid')
        with tempfile.TemporaryDirectory() as folder:
            model, source = FixtureModel(), FixtureSource()
            ident = identity('topic', 'offline', cfg, None, model, model, source)
            cp = Checkpoint(Path(folder)/'one.json', ident)
            rt = Runtime(model, model, source, cfg, checkpoint=cp)
            first = await run('topic', model, source, config=cfg, runtime=rt)
            self.assertTrue(first.status.startswith('completed'), first.errors)
            model2, source2 = FixtureModel(), FixtureSource()
            cp2 = Checkpoint(Path(folder)/'two.json', ident, resume=Path(folder)/'one.json')
            rt2 = Runtime(model2, model2, source2, cfg, checkpoint=cp2, cache_only_retrieval=True)
            second = await run('topic', model2, source2, config=cfg, runtime=rt2)
            self.assertTrue(second.status.startswith('completed'), second.errors)
            self.assertEqual(second.candidates, first.candidates)
            self.assertEqual(second.experiment, first.experiment)
            self.assertEqual(rt2.usage['model_calls'], rt.usage['model_calls'])
            self.assertEqual(rt2.usage['search_calls'], rt.usage['search_calls'])
            self.assertEqual(sum(model2.calls.values()), 0)
            self.assertTrue(second.validation['contract_passed'])
            self.assertTrue(any(e['status']=='cache_hit' for e in rt2.audit))

    async def test_resume_keeps_failed_attempts_and_stops_ambiguous_calls(self):
        cfg=RunConfig();model=FixtureModel();source=FixtureSource()
        with tempfile.TemporaryDirectory() as folder:
            ident=identity('topic','offline',cfg,None,model,model,source)
            cp=Checkpoint(Path(folder)/'one.json',ident);rt=Runtime(model,model,source,cfg,checkpoint=cp)
            async def fail(): raise TransientProviderError('temporary')
            with self.assertRaises(TransientProviderError):
                await rt.call('search','lookup',fail,cache_input={'query':'same'})
            cp2=Checkpoint(Path(folder)/'two.json',ident,resume=Path(folder)/'one.json')
            rt2=Runtime(model,model,source,cfg,checkpoint=cp2)
            with self.assertRaises(TransientProviderError):
                await rt2.call('search','lookup',fail,cache_input={'query':'same'})
            self.assertEqual(rt2.usage['search_calls'],2)
            key=digest({'kind':'model','stage':'pending','input':{'prompt':'x'}})
            cp2.entries[key]={'status':'pending','provenance':{}};rt2.persist()
            with self.assertRaises(ConfigurationError):
                await rt2.call('model','pending',fail,cache_input={'prompt':'x'})
            with self.assertRaises(ConfigurationError):
                Checkpoint(Path(folder)/'bad.json',{**ident,'input_sha256':'different'},resume=Path(folder)/'one.json')

    async def test_cache_only_miss_never_calls_source(self):
        model=FixtureModel();rt=Runtime(model,model,FixtureSource(),RunConfig(),cache_only_retrieval=True)
        async def forbidden(): raise AssertionError('network attempted')
        with self.assertRaises(RetrievalUnavailable):
            await rt.call('search','lookup',forbidden,cache_input={'query':'new'})
        self.assertEqual(rt.usage['search_calls'],0)

    async def test_late_novelty_failure_keeps_paid_final_idea_for_resumption(self):
        class LimitedSource(FixtureSource):
            async def search(self, query, **kwargs):
                if query == 'sage-fixture-novelty':
                    raise TransientProviderError('sanitized observed 429')
                return await super().search(query, **kwargs)
        cfg=RunConfig(discussion_mode='hybrid')
        with tempfile.TemporaryDirectory() as folder:
            model=FixtureModel();source=LimitedSource()
            ident=identity('topic','offline',cfg,None,model,model,source)
            cp=Checkpoint(Path(folder)/'first.json',ident)
            rt=Runtime(model,model,source,cfg,checkpoint=cp)
            failed=await run('topic',model,source,config=cfg,runtime=rt)
            self.assertEqual(failed.status,'failed')
            self.assertEqual(model.calls['ideation.finalize'],1)
            model2=FixtureModel();source2=LimitedSource()
            cp2=Checkpoint(Path(folder)/'second.json',ident,resume=Path(folder)/'first.json')
            rt2=Runtime(model2,model2,source2,cfg,checkpoint=cp2,allow_incomplete_novelty=True)
            result=await run('topic',model2,source2,config=cfg,runtime=rt2)
            self.assertEqual(result.status,'completed_with_uncertainty',result.errors)
            # Only the not-yet-generated second candidate requires new ideation.
            self.assertEqual(model2.calls['ideation.finalize'],1)
            self.assertEqual(model2.calls['discovery.queries'],0)
            self.assertTrue(all(c.novelty.status=='not_established' for c in result.candidates))
            self.assertTrue(result.validation['contract_passed'])
            self.assertTrue(any(e['status']=='cached_failure' for e in result.audit))

    async def test_recorded_sdk_usage_includes_truncation_and_is_not_reservation(self):
        class Model:
            def __init__(self):self.n=0
            async def complete(self,*args,**kwargs):
                self.n+=1;self.last_usage={'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}
                if self.n==1:raise TruncatedResponse('length')
                return '<experiment>plan</experiment>'
        model=Model();rt=Runtime(model,model,FixtureSource(),RunConfig())
        await rt.ask('experiment_design.refine','x',('experiment',))
        self.assertEqual(rt.usage['actual_total_tokens'],20)
        self.assertEqual(rt.usage['reserved_output_tokens'],4000)
        self.assertEqual(rt.usage['sdk_reported_responses'],2)

    async def test_429_retains_retry_after_and_does_not_retry_or_start_other_search(self):
        from sage.errors import RateLimited
        from sage.providers import _retry_after
        self.assertEqual(_retry_after('120'),120)
        self.assertIsNone(_retry_after('not a retry date'))
        model=FixtureModel();rt=Runtime(model,model,FixtureSource(),RunConfig())
        calls=[]
        async def limited():
            calls.append(1);raise RateLimited('observed 429',120)
        with self.assertRaises(RateLimited):await rt.call('search','lookup',limited,cache_input='one')
        with self.assertRaises(RetrievalUnavailable):await rt.call('search','lookup',limited,cache_input='two')
        self.assertEqual(len(calls),1)
        self.assertEqual(rt.audit[-2]['retry_after_seconds'],120)

    async def test_checkpoint_tampering_and_elapsed_budget_do_not_reset(self):
        model=FixtureModel();source=FixtureSource();cfg=RunConfig(max_wall_seconds=10)
        with tempfile.TemporaryDirectory() as folder:
            ident=identity('topic','offline',cfg,None,model,model,source)
            cp=Checkpoint(Path(folder)/'first.json',ident)
            now=[0.0];rt=Runtime(model,model,source,cfg,checkpoint=cp,clock=lambda:now[0])
            now[0]=8.0;rt.persist()
            cp2=Checkpoint(Path(folder)/'next.json',ident,resume=Path(folder)/'first.json')
            rt2=Runtime(model,model,source,cfg,checkpoint=cp2,clock=lambda:20.0)
            self.assertEqual(rt2.remaining(),2.0)
            data=json.loads((Path(folder)/'first.json').read_text());data['data']['elapsed_seconds']=0
            (Path(folder)/'tampered.json').write_text(json.dumps(data))
            with self.assertRaises(ConfigurationError):
                Checkpoint(Path(folder)/'refused.json',ident,resume=Path(folder)/'tampered.json')

    async def test_cache_hits_revalidate_ownership(self):
        model=FixtureModel();source=FixtureSource();cfg=RunConfig()
        with tempfile.TemporaryDirectory() as folder:
            cp=Checkpoint(Path(folder)/'cache.json',identity('t','offline',cfg,None,model,model,source))
            rt=Runtime(model,model,source,cfg,checkpoint=cp)
            await rt.ask('discovery.queries','same',('queries',))
            used=rt.usage['model_calls']
            def reject(_):raise InvalidResponse('foreign ownership')
            with self.assertRaises(InvalidResponse):await rt.ask('discovery.queries','same',('queries',),validate=reject)
            self.assertEqual(rt.usage['model_calls'],used)
