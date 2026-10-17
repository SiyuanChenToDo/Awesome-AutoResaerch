"""Research-input regressions; source and model fixtures are explicitly synthetic."""
import asyncio
from dataclasses import replace, asdict
import json
import unittest
from unittest.mock import patch
from sage.config import RunConfig, profile_overrides
from sage.errors import InvalidResponse, ConfigurationError, TransientProviderError, NoEvidence
from sage.types import Paper, Evidence
from sage.runtime import Runtime
from sage.fixtures import FixtureModel, FixtureSource
from sage.discovery import Discovery
from sage.literature import Literature
from sage.literature.capsule import chunks_for, validate_claims, extract_capsule, capsule_prompt
from sage.literature.reader import html_article, arxiv_identity, read_article
from sage.providers import HTTPResponse
from sage.arxiv import ArxivSource
from sage.discussion import validate_revision, publish_controls
from sage.discussion.context import compact_payload
from sage.orchestration import run


class InputContractTests(unittest.TestCase):
    def test_quality_profile_is_finite_and_explicit(self):
        c = RunConfig(**profile_overrides('research'))
        self.assertEqual((c.max_candidates,c.discussion_students,c.discussion_rounds),(4,4,2))
        self.assertEqual(c.discussion_prompt_version,'v3')
        self.assertEqual(c.evidence_mode,'capsule')
        for field in ('capsule_max_chunks','max_model_calls','max_search_calls'):
            self.assertGreater(getattr(c,field),0)

    def test_invalid_new_limits_rejected(self):
        for values in ({'capsule_max_chunks':0},{'capsule_max_chars':True},
                       {'novelty_search_rewrites':5},{'rerank_mode':'magic'},
                       {'paper_text_mode':'any_url'},{'novelty_fulltext_papers':-1}):
            with self.subTest(values=values),self.assertRaises(ConfigurationError):RunConfig(**values)

    def test_sampling_includes_document_end_and_records_omissions(self):
        p=Paper('p','Paper',article={'sections':[{'heading':str(i),'text':'x'*1100} for i in range(10)]})
        chosen,all_chunks=chunks_for(p,RunConfig(capsule_chunk_chars=1000,capsule_max_chunks=3))
        self.assertEqual(len(chosen),3)
        self.assertEqual(chosen[0],all_chunks[0]);self.assertEqual(chosen[-1],all_chunks[-1])

    def test_hallucinated_quote_rejected(self):
        chunk={'chunk_id':'s1-c1','text':'The source reports an explicitly synthetic controlled comparison.'}
        claim={'category':'results','claim':'Unverified claim','quote':'These words do not appear in the source.','chunk_id':'s1-c1'}
        with self.assertRaises(InvalidResponse):validate_claims(json.dumps({'claims':[claim],'inferences':[]}),chunk)
        claim['quote']=chunk['text'];claim['chunk_id']='wrong'
        with self.assertRaises(InvalidResponse):validate_claims(json.dumps({'claims':[claim],'inferences':[]}),chunk)

    def test_extractor_does_not_leak_other_chunk_abstract_as_quotation_source(self):
        p=Paper('p','Synthetic paper',abstract='ABSTRACT_ONLY_SENTENCE_SHOULD_NOT_APPEAR')
        prompt=capsule_prompt(p,'t',{'chunk_id':'s1-c1','heading':'Method','text':'Actual method section.'})
        self.assertNotIn(p.abstract,prompt)
        self.assertIn('Actual method section.',prompt)

    def test_section_priority_reads_methods_results_and_limits_before_bibliography(self):
        p=Paper('p','P',article={'sections':[{'heading':h,'text':'x'*100} for h in
            ['Title','Abstract','Introduction','Methods','Results','Discussion','References']]})
        chosen,_=chunks_for(p,RunConfig(capsule_max_chunks=4))
        self.assertEqual({x['heading'] for x in chosen},{'Abstract','Methods','Results','Discussion'})

    def test_official_html_retains_methods_and_limitations(self):
        body=('<article class="ltx_document"><h1>Method</h1><p>'+('Synthetic method text. '*30)+
              '</p><h2>Limitations</h2><p>Only a toy dataset was tested.</p><script>evil()</script></article>').encode()
        article=html_article(body,'https://arxiv.org/html/2501.00001v1')
        self.assertIn('Limitations',[s['heading'] for s in article['sections']])
        self.assertNotIn('evil()',str(article))
        self.assertIsNone(html_article(b'<html>404 paper unavailable</html>','https://arxiv.org/html/2501.00001'))

    def test_reader_never_follows_arbitrary_paper_url(self):
        self.assertIsNone(arxiv_identity(Paper('opaque','Title',url='https://evil.invalid/pdf/1')))
        self.assertEqual(arxiv_identity(Paper('arxiv:2501.00001','Title')),'2501.00001')

    def test_methodological_critique_can_change_idea_without_invented_citation(self):
        critique={'critique_id':'c1','status':'methodological','evidence_ids':[],
                  'requested_change':'Add a capacity-matched control.'}
        v={'idea':'Original\nAdd a capacity-matched control.','evidence_ids':['p'],
           'accepted_critique_ids':['c1'],'rejected_critique_ids':[],
           'rationale':'This separates capacity from mechanism.','uncertainty':'Unexecuted.'}
        validate_revision(v,original_idea='Original',own_evidence_ids=['p'],targeted=[critique],prior={},
                          shared_evidence_ids={'p'},allow_methodological=True)
        with self.assertRaises(InvalidResponse):
            validate_revision(v,original_idea='Original',own_evidence_ids=['p'],targeted=[{**critique,'status':'unknown'}],
                              prior={},shared_evidence_ids={'p'},allow_methodological=True)

    def test_canonical_controls_preserve_approved_text_without_model_recopy(self):
        critique={'critique_id':'c1','status':'methodological','evidence_ids':[],
                  'requested_change':'Freeze the exact null hypothesis and test statistic.'}
        value={'idea':'Revised test with a frozen null.','evidence_ids':['p'],
               'accepted_critique_ids':['c1'],'rejected_critique_ids':[],
               'rationale':'Explicit design control.','uncertainty':'Unexecuted.'}
        validate_revision(value,original_idea='Original',own_evidence_ids=['p'],targeted=[critique],prior={},
                          shared_evidence_ids={'p'},allow_methodological=True,canonical_controls=True)
        published=publish_controls(value['idea'],[critique])
        self.assertIn(critique['requested_change'],published)
        self.assertEqual(publish_controls(published,[critique]),published)
        self.assertNotIn('[fake]',publish_controls('Narrative\n\n[SAGE_ACCEPTED_CONTROLS]\n[fake] made up',[critique]))

    def test_unchanged_sentinel_does_not_authorize_unaccepted_edit(self):
        value={'idea':'UNCHANGED','evidence_ids':['p'],'accepted_critique_ids':[],
               'rejected_critique_ids':[],'rationale':'No new control.','uncertainty':'Unexecuted.'}
        validate_revision(value,original_idea='Original',own_evidence_ids=['p'],targeted=[],prior={},
                          shared_evidence_ids={'p'},canonical_controls=True)
        with self.assertRaises(InvalidResponse):
            validate_revision({**value,'idea':'Unapproved change'},original_idea='Original',own_evidence_ids=['p'],
                              targeted=[],prior={},shared_evidence_ids={'p'},canonical_controls=True)

    def test_cumulative_approved_ids_are_not_new_or_fabricated_decisions(self):
        prior={'old':{'critique_id':'old','status':'methodological','evidence_ids':['source-old'],
                      'requested_change':'Keep previous control.'}}
        new={'critique_id':'new','status':'methodological','evidence_ids':[],'requested_change':'Add new control.'}
        value={'idea':'Revised narrative.','evidence_ids':['p'],'accepted_critique_ids':['old','new'],
               'rejected_critique_ids':[],'rationale':'Retain old and add new.','uncertainty':'Unexecuted.'}
        validate_revision(value,original_idea='Original',own_evidence_ids=['p'],targeted=[new],prior=prior,
                          shared_evidence_ids={'p','source-old'},allow_methodological=True,canonical_controls=True)
        with self.assertRaises(InvalidResponse):
            validate_revision({**value,'accepted_critique_ids':['old','fake','new']},original_idea='Original',
                              own_evidence_ids=['p'],targeted=[new],prior=prior,shared_evidence_ids={'p','source-old'},
                              allow_methodological=True,canonical_controls=True)


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def runtime(self, **config):
        return Runtime(FixtureModel(),FixtureModel(),FixtureSource(),RunConfig(**config))

    async def test_capsule_replaces_raw_text_and_retains_exact_quotes(self):
        r=self.runtime(evidence_mode='capsule')
        p=Paper('p','Synthetic paper',article={'sections':[{'heading':'Methods','text':'Only synthetic controlled experiments were described here, without real measurements.'}]})
        e=await Literature(r,Discovery(r)).extract(p,'Synthetic topic')
        self.assertIsNone(e.paper.article)
        self.assertEqual(e.capsule['source_scope'],'abstract_only')
        self.assertEqual(len(e.capsule['claims']),1)
        self.assertIn('results',e.capsule['missing_categories'])
        self.assertEqual(e.capsule['claims'][0]['quote'],p.article['sections'][0]['text'])

    async def test_capsule_cache_does_not_spend_twice(self):
        r=self.runtime(evidence_mode='capsule');l=Literature(r,Discovery(r))
        p=Paper('p','Synthetic paper',abstract='Synthetic source has no real measured outcomes or known benchmark performance.')
        one=await l.extract(p,'t');two=await l.extract(p,'t')
        self.assertIs(one,two);self.assertEqual(r.usage['model_calls'],1)

    async def test_size_cap_cannot_publish_a_zero_claim_card(self):
        r=self.runtime(evidence_mode='capsule',capsule_max_chars=2000)
        p=Paper('p','P',article={'sections':[{'heading':'x'*5000,'text':'Synthetic source text for explicit controlled software testing.'}]})
        with self.assertRaises(NoEvidence):await Literature(r,Discovery(r)).extract(p,'t')

    async def test_nearest_work_includes_actual_input_sources_not_only_new_search(self):
        from sage.review import Review
        r=self.runtime(evidence_mode='capsule')
        p=Paper('known-paper','Already read source','Synthetic actual input source.')
        r.evidence_cards={'known-paper':Evidence(p,'idea','experiment','entities',[],{'claims':[]})}
        class Model:
            async def complete(self,stage,prompt,**kwargs):
                self.prompt=prompt
                return '<comparison>'+json.dumps({'verdict':'overlap','closest_paper_id':'known-paper',
                    'comparisons':[{'paper_id':'known-paper','shared_problem':'Same problem','shared_mechanism':'Same mechanism',
                     'difference':'Proposed control only','evidence_limit':'Synthetic source'}],'uncertainty':'Unverified assessment.'})+'</comparison>'
        model=Model();r.main_model=model
        assessment=await Review(r,Discovery(r)).compare_nearest('Extends known-paper',[Paper('fresh','Fresh retrieval')],['query'])
        self.assertEqual(assessment.status,'similar_work_found')
        self.assertEqual({p.paper_id for p in assessment.compared_papers},{'known-paper','fresh'})
        self.assertIn('existing_read_input_evidence',model.prompt)
        self.assertEqual(assessment.similar_paper_id,'known-paper')

    async def test_failed_chunk_keeps_negative_record_without_accepting_bad_claim(self):
        r=self.runtime(evidence_mode='capsule',retry_attempts=1)
        r.cheap_model=FixtureModel(overrides={'literature.capsule':['<capsule>{"claims":[{"category":"method",'
            '"claim":"Unsupported","quote":"Not present in the source chunk.","chunk_id":"s1-c1"}],"inferences":[]}</capsule>']})
        p=Paper('p','P',article={'sections':[{'heading':'Methods','text':'This source is explicitly synthetic and records no real results.'},
                                          {'heading':'Results','text':'This second source section contains explicitly synthetic test statements.'}]})
        evidence=await Literature(r,Discovery(r)).extract(p,'t')
        self.assertEqual(evidence.capsule['coverage']['failed_chunk_ids'],['s1-c1'])
        self.assertEqual(evidence.capsule['coverage']['validated_chunk_ids'],['s2-c1'])
        self.assertTrue(evidence.capsule['coverage']['partial_document'])
        self.assertEqual(r.usage['model_calls'],2)
        self.assertNotIn('Unsupported',str(evidence.capsule['claims']))

    async def test_fulltext_requests_count_and_fallback_is_visible(self):
        r=self.runtime(retry_attempts=1)
        calls=[]
        def transport(url,*args):calls.append(url);return HTTPResponse(404,b'')
        out=await read_article(r,Paper('arxiv:2501.00001','P'),transport=transport)
        self.assertIsNone(out);self.assertEqual(r.usage['search_calls'],2)
        self.assertEqual(len(calls),2)
        self.assertEqual(sum(e['status']=='unavailable' for e in r.audit),2)

    async def test_novelty_relaxation_is_bounded_and_accounted(self):
        class Source(FixtureSource):
            relax_queries=staticmethod(ArxivSource.relax_queries)
            async def search(self,query,**kw):
                self.calls.append(query)
                return [Paper('p','Synthetic relevant paper','Synthetic mechanism')] if query=='symbolic regression' else []
        r=self.runtime(novelty_search_rewrites=2);r.source=Source()
        papers,queries=await Discovery(r).search_expanded('symbolic regression explanation faithfulness control',limit=5)
        self.assertEqual(len(queries),3);self.assertEqual(r.usage['search_calls'],3)
        self.assertEqual(papers[0].paper_id,'p')

    async def test_semantic_ranking_rejects_invented_id(self):
        r=self.runtime(rerank_mode='model',retry_attempts=1)
        r.cheap_model=FixtureModel(overrides={'discovery.semantic_rank':['<ranking>[{"paper_id":"invented","score":4,"reason":"fake"}]</ranking>']})
        with self.assertRaises(InvalidResponse):await Discovery(r).rank([Paper('p','P')],'query')
        self.assertEqual(r.usage['model_calls'],1)

    async def test_long_ranking_reason_gets_specific_feedback_not_silent_truncation(self):
        r=self.runtime(rerank_mode='model',retry_attempts=2)
        requests=[]
        class Model:
            async def complete(self,stage,prompt,**kwargs):
                requests.append(prompt)
                reason='x'*181 if len(requests)==1 else 'Direct mechanism match.'
                return '<ranking>'+json.dumps([{'paper_id':'p','score':4,'reason':reason}])+'</ranking>'
        r.cheap_model=Model()
        papers=await Discovery(r).rank([Paper('p','Paper')],'query')
        self.assertEqual(papers[0].paper_id,'p');self.assertEqual(r.usage['model_calls'],2)
        self.assertIn('at most 180 characters',requests[0])
        self.assertIn('bounded_ranking_reason',requests[1])
        self.assertTrue(any(e['status']=='validation_rejected' for e in r.audit))

    async def test_shared_discussion_sees_peer_capsule_and_preserves_provenance(self):
        source=FixtureSource();r=self.runtime(evidence_mode='capsule');l=Literature(r,Discovery(r))
        e=await l.extract(source.papers['fixture-a-anchor'],'topic')
        record=asdict(e)
        payload={'own_candidate':{'chain':{'evidence':[]}},'target_candidate':{'chain':{'evidence':[record]}},
                 'evidence_ids':[],'shared_evidence':[record],'source_owners':{e.paper.paper_id:['phd-2']}}
        card=compact_payload('critique',payload,shared=True)
        self.assertIn(e.paper.paper_id,card['citable_source_ids'])
        self.assertEqual(card['source_owners'][e.paper.paper_id],['phd-2'])
        self.assertTrue(next(iter(card['evidence_registry'].values()))['capsule']['claims'])

    async def test_capsule_and_v3_use_real_controller_offline(self):
        config=RunConfig(evidence_mode='capsule',paper_text_mode='provided',rerank_mode='model',
                         discussion_mode='hybrid',discussion_prompt_version='v3',max_model_calls=150)
        with patch('socket.create_connection',side_effect=AssertionError('Offline attempted network')):
            result=await run('Synthetic topic',FixtureModel(),FixtureSource(),config=config)
        self.assertTrue(result.status.startswith('completed'),result.errors)
        self.assertTrue(result.validation['contract_passed'])
        self.assertTrue(all(e.capsule for c in result.candidates for e in c.chain.evidence))
        self.assertTrue(all(c.novelty.comparisons for c in result.candidates))
        self.assertIn('shared_source_owners',result.discussion)
        for kind in ('model','search'):
            self.assertEqual(result.usage[kind+'_calls'],sum(e['status']=='started' and e.get('kind')==kind for e in result.audit))

    async def test_v3_narrative_edits_keep_prior_controls_and_exact_plan_requirements(self):
        class Model(FixtureModel):
            async def complete(self,stage,prompt,**kwargs):
                response=await super().complete(stage,prompt,**kwargs)
                if stage=='discussion.revise':
                    value=json.loads(response.split('<discussion>')[1].split('</discussion>')[0])
                    value['idea']='Concise revised narrative '+str(self.calls[stage]) if value['accepted_critique_ids'] else 'UNCHANGED'
                    return '<discussion>'+json.dumps(value)+'</discussion>'
                return response
        config=RunConfig(evidence_mode='capsule',discussion_mode='hybrid',discussion_prompt_version='v3',
                         discussion_rounds=2,max_model_calls=160)
        with patch('socket.create_connection',side_effect=AssertionError('Offline attempted network')):
            result=await run('Synthetic narrative',Model(),FixtureSource(),config=config)
        self.assertTrue(result.status.startswith('completed'),result.errors)
        selected=result.candidates[result.selected_index]
        requirements=result.discussion['synthesis']['requirements']
        self.assertEqual(len(requirements),2)
        for requirement in requirements:
            self.assertIn(requirement['requirement'],selected.idea)
            self.assertIn(requirement['requirement'],result.experiment.proposal)

    async def test_graph_edges_use_actual_graph_records_and_arxiv_identity(self):
        from sage.graph_source import ArxivGraphSource
        from sage.providers import SemanticScholarSource
        urls=[]
        def transport(url,*args):
            urls.append(url)
            return HTTPResponse(200,json.dumps({'data':[{'citedPaper':{'paperId':'graphhash','title':'Synthetic reference',
                'abstract':'A synthetic graph fixture.','externalIds':{'ArXiv':'2501.00002'}}}]}).encode())
        source=ArxivGraphSource(ArxivSource(),SemanticScholarSource(transport=transport))
        papers=await source.related(Paper('arxiv:2501.00001','P',url='https://arxiv.org/abs/2501.00001v2'),direction='references',limit=3)
        self.assertEqual(len(urls),1)
        self.assertIn('ARXIV%3A2501.00001/references',urls[0])
        self.assertNotIn('00001v2',urls[0])
        self.assertEqual(papers[0].paper_id,'arxiv:2501.00002')
        self.assertEqual(papers[0].source_provider,'semantic_scholar_graph')

    async def test_graph_failure_falls_back_only_to_labeled_topic_chain(self):
        class UnavailableGraph(FixtureSource):
            async def related(self,*args,**kwargs):raise TransientProviderError('Graph unavailable')
            async def topic_related(self,paper,**kwargs):return [self.papers['fixture-b-anchor']]
        r=self.runtime(citation_policy='prefer',retry_attempts=1);r.source=UnavailableGraph()
        chain=await Literature(r,Discovery(r)).build_chain(r.source.papers['fixture-a-anchor'],'t')
        self.assertEqual(chain.relation,'topic_time')
        self.assertIn('citation_graph_unavailable',chain.stop_reasons)
        self.assertTrue(any(e['stage']=='literature.graph' and e['status']=='unavailable' for e in r.audit))

    async def test_full_research_profile_four_roles_two_rounds_offline(self):
        class FourSource(FixtureSource):
            def __init__(self):
                super().__init__()
                for family in ('c','d'):
                    for identity,p in list(self.papers.items()):
                        if identity.startswith('fixture-b-'):
                            key=identity.replace('fixture-b-',f'fixture-{family}-')
                            article=json.loads(json.dumps(p.article).replace('fixture-b-',f'fixture-{family}-'))
                            self.papers[key]=replace(p,paper_id=key,title=p.title.replace('Synthetic b ',f'Synthetic {family} '),article=article)
            async def search(self,query,**kwargs):
                if query in ('sage-fixture-c','sage-fixture-d'):
                    return [self.papers[f'fixture-{query[-1]}-anchor']]
                return await super().search(query,**kwargs)
        model=FixtureModel(overrides={'discovery.queries':['<queries>["sage-fixture-a","sage-fixture-b","sage-fixture-c","sage-fixture-d"]</queries>']})
        with patch('socket.create_connection',side_effect=AssertionError('Research fixture attempted network')):
            result=await run('Synthetic quality profile',model,FourSource(),config=RunConfig(**profile_overrides('research')))
        self.assertTrue(result.status.startswith('completed'),result.errors)
        self.assertEqual(len(result.candidates),4)
        self.assertEqual(len(result.discussion['critiques']),8)
        self.assertEqual(len(result.discussion['students']),4)
        self.assertTrue(result.validation['contract_passed'])


if __name__ == '__main__':unittest.main()
