import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from sage.config import RunConfig
from sage.errors import ConfigurationError, InvalidResponse
from sage.fixtures import FixtureModel, FixtureSource
from sage.runtime import Runtime
from sage.review.claims import checked_claims, checked_assessment
from sage.integrations.aris import ArisGate, family, reviewer_from_env
from sage.integrations.coral import validate_contract, run_coral_task, file_digest, parse_candidate_script
from sage.integrations.simplifier_task import dataset
from sage.checkpoints import digest


class ClaimContracts(unittest.TestCase):
    def claim(self):
        return {'statement':'A proposed mechanism','kind':'method','source_ids':['p1'],
                'queries':['tree hashing'],'falsifier':'A matched control shows the same behavior.'}

    def assessment(self):
        return {'overall_verdict':'insufficient_evidence','combination_prior_id':None,'score':5,
                'verdict':'not ready','uncertainty':'Only selected text was read.',
                'assessments':[{'claim_id':'c1','status':'insufficient_evidence','closest_paper_id':'p1',
                    'overlap':'Same problem','delta':'Proposed intervention','evidence_limit':'No full paper comparison',
                    'decisive_test':'Compare against a matched baseline'}]}

    def test_claim_source_and_query_bounds(self):
        row=self.claim()
        self.assertEqual(checked_claims(json.dumps([row]),{'p1'},RunConfig())[0]['claim_id'],'c1')
        row['source_ids']=['invented']
        with self.assertRaises(InvalidResponse):checked_claims(json.dumps([row]),{'p1'},RunConfig())
        row=self.claim();row['queries']=['x']*4
        with self.assertRaises(InvalidResponse):checked_claims(json.dumps([row]),{'p1'},RunConfig())

    def test_duplicate_claims_rejected(self):
        with self.assertRaises(InvalidResponse):checked_claims(json.dumps([self.claim(),self.claim()]),{'p1'},RunConfig())

    def test_comparator_ids_are_claim_scoped(self):
        value=self.assessment();value['assessments'][0]['closest_paper_id']='p2'
        with self.assertRaises(InvalidResponse):checked_assessment(json.dumps(value),{'c1':{'p1'}})

    def test_whole_idea_overlap_needs_named_work(self):
        value=self.assessment();value['overall_verdict']='overlap'
        with self.assertRaises(InvalidResponse):checked_assessment(json.dumps(value),{'c1':{'p1'}})

    def test_every_claim_requires_assessment(self):
        with self.assertRaises(InvalidResponse):checked_assessment(json.dumps(self.assessment()),{'c1':{'p1'},'c2':{'p2'}})

    def test_invalid_score_is_not_acceptance(self):
        value=self.assessment();value['score']=True
        with self.assertRaises(InvalidResponse):checked_assessment(json.dumps(value),{'c1':{'p1'}})

    def test_optional_reviewer_configuration_does_not_change_main(self):
        env={'SAGE_MODEL_PROVIDER':'deepseek','SAGE_MAIN_MODEL':'deepseek-flash',
             'SAGE_OPENAI_BASE_URL':'https://api.deepseek.com','SAGE_OPENAI_API_KEY':'not-a-real-key',
             'SAGE_REVIEWER_MODEL':'gpt-test','SAGE_REVIEWER_MODEL_PROVIDER':'openai',
             'SAGE_REVIEWER_OPENAI_BASE_URL':'https://api.openai.com/v1','SAGE_REVIEWER_OPENAI_API_KEY':'review-test'}
        reviewer=reviewer_from_env(timeout=10,env=env)
        self.assertEqual(reviewer.config.provider,'openai')
        self.assertEqual(reviewer.config.model,'gpt-test')
        self.assertEqual(env['SAGE_MAIN_MODEL'],'deepseek-flash')
        self.assertIsNone(reviewer_from_env(timeout=10,env={}))

    def test_aris_pin_refuses_unknown_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'tools';p.mkdir();(p/'review_gate.py').write_text('print("fake")')
            with self.assertRaises(ConfigurationError):ArisGate(directory)


class IntegratedClaims(unittest.IsolatedAsyncioTestCase):
    async def test_reason_preview_preserves_full_text_and_scores_without_rebuying(self):
        from sage.discovery import Discovery
        from sage.types import Paper
        reason='Mechanism explanation. '*12
        model=FixtureModel(overrides={'discovery.semantic_rank':['<ranking>'+json.dumps([
            {'paper_id':'p','score':4,'reason':reason}])+'</ranking>']})
        runtime=Runtime(model,model,FixtureSource(),RunConfig(rerank_mode='semantic'))
        papers=await Discovery(runtime).rank([Paper('p','Paper')],'mechanism')
        self.assertEqual(papers[0].paper_id,'p')
        self.assertEqual(runtime.usage['model_calls'],1)
        row=next(e for e in runtime.audit if e['status']=='semantic_model')['ranking'][0]
        self.assertEqual(row['score'],4)
        self.assertTrue(row['reason_truncated'])
        self.assertEqual(len(row['reason']),180)
        self.assertEqual(row['full_reason'],reason)
        self.assertEqual(row['full_reason_sha256'],digest(reason))

    async def test_prior_art_retrieval_does_not_require_generator_ranking(self):
        from sage.discovery import Discovery
        model=FixtureModel(overrides={'discovery.semantic_rank':[InvalidResponse('broken ranking')]})
        runtime=Runtime(model,model,FixtureSource(),RunConfig(rerank_mode='semantic'))
        papers=await Discovery(runtime).search('sage-fixture-novelty',limit=6,rerank=False)
        self.assertEqual(papers[0].paper_id,'fixture-comparison')
        self.assertEqual(runtime.usage['model_calls'],0)
        self.assertTrue(any(e['status']=='skipped_for_comparison_recall' for e in runtime.audit))

    async def test_query_overflow_retry_receives_exact_limit_feedback(self):
        base={'statement':'Proposed mechanism','kind':'method','source_ids':['p1'],
              'queries':['query one','query two','query three'],'falsifier':'A matched control refutes it.'}
        good={**base,'queries':['query one','query two']}
        class Replies(FixtureModel):
            def __init__(self):
                super().__init__(overrides={'claims':['<claims>'+json.dumps([base])+'</claims>',
                                                         '<claims>'+json.dumps([good])+'</claims>']});self.prompts=[]
            async def complete(self,stage,prompt,*,max_tokens):
                self.prompts.append(prompt)
                return await super().complete(stage,prompt,max_tokens=max_tokens)
        model=Replies();runtime=Runtime(model,model,FixtureSource(),RunConfig())
        await runtime.ask('claims','Extract claims with at most two queries.',('claims',),
            validate=lambda r:checked_claims(r['claims'],{'p1'},runtime.config))
        self.assertEqual(runtime.usage['model_calls'],2)
        self.assertIn('at most TWO',model.prompts[1])
        self.assertTrue(any(e['status']=='validation_rejected' for e in runtime.audit))

    async def test_claim_review_rechecks_discussion_revisions(self):
        from sage.orchestration import run
        model=FixtureModel()
        config=RunConfig(evidence_mode='capsule',claim_review=True,max_candidates=2,
            max_chain_length=2,min_chain_length=2,refinement_rounds=0,max_model_calls=180,
            max_reserved_output_tokens=360000,discussion_mode='hybrid',discussion_prompt_version='v3')
        result=await run('Controlled research',model,FixtureSource(),config=config)
        self.assertTrue(result.status.startswith('completed'),result.errors)
        self.assertGreaterEqual(model.calls['review.claims.assess'],4)
        self.assertTrue(all(c.novelty.research_claims for c in result.candidates))

    async def test_reviewer_uses_shared_budget_and_receipt(self):
        main=FixtureModel();reviewer=FixtureModel(overrides={'review.test':['<answer>ok</answer>']})
        reviewer.config=SimpleNamespace(model='deepseek-review',provider='deepseek')
        reviewer.last_response_model='deepseek-review';reviewer.last_response_id='receipt-test'
        runtime=Runtime(main,main,FixtureSource(),RunConfig(),reviewer_model=reviewer)
        await runtime.ask('review.test','bounded evidence',('answer',),reviewer=True)
        self.assertEqual(runtime.usage['model_calls'],1)
        self.assertEqual(main.calls['review.test'],0)
        event=next(e for e in runtime.audit if e['status']=='response_receipt')
        self.assertEqual(event['returned_model'],'deepseek-review')
        self.assertEqual(event['response_id'],'receipt-test')

    async def test_research_claims_run_in_real_controller(self):
        from sage.orchestration import run
        model=FixtureModel();model.config=SimpleNamespace(model='deepseek-fixture',provider='deepseek')
        config=RunConfig(evidence_mode='capsule',claim_review=True,max_candidates=2,
            max_chain_length=2,min_chain_length=2,refinement_rounds=0,max_model_calls=160,
            max_reserved_output_tokens=320000)
        result=await run('Controlled research',model,FixtureSource(),config=config)
        self.assertTrue(result.status.startswith('completed'),result.errors)
        self.assertTrue(result.validation['contract_passed'])
        self.assertEqual(len(result.candidates),2)
        for c in result.candidates:
            self.assertEqual(len(c.novelty.research_claims),1)
            self.assertEqual(c.novelty.review_receipt['independence'],'same_family')
            self.assertEqual(c.novelty.review_receipt['acceptance_status'],'provisional')
        self.assertTrue(any(e['stage']=='ideation.lens' for e in result.audit))

    async def test_original_gate_is_invoked_with_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Path(directory)/'tools';tools.mkdir();script=tools/'review_gate.py';script.write_text('trusted mock')
            pin=hashlib.sha256(script.read_bytes()).hexdigest()
            with patch('sage.integrations.aris.GATE_SHA256',pin):gate=ArisGate(directory)
            value={'decision':'review_unavailable','next_backend':None,'requires_external_acquittal':False,
                   'identity_assurance':'failed','reason':'Same family'}
            with patch('sage.integrations.aris.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(value))) as mocked:
                actual=await gate.evaluate(score=7,verdict='ready',executor_model='deepseek-flash',reviewer_model='deepseek-flash')
            self.assertTrue(actual['executed'])
            args,kw=mocked.call_args
            self.assertIn(str(script),args[0])
            self.assertNotIn('SAGE_OPENAI_API_KEY',kw['env'])
            self.assertEqual(actual['decision'],'review_unavailable')


class CoralContracts(unittest.TestCase):
    def test_changed_candidate_interpreter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory)
            Path(contract['candidate_python']).write_text('changed')
            with self.assertRaises(ConfigurationError):validate_contract(contract)

    def test_code_format_recovery_is_explicit_and_hashed(self):
        raw='```python\nprint(1)\n```'
        parsed=parse_candidate_script(raw)
        self.assertEqual(parsed['input_format'],'python_fence')
        self.assertEqual(parsed['code'],'print(1)\n')
        self.assertEqual(parsed['raw_response_sha256'],hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(parse_candidate_script('<code>print(1)</code>')['input_format'],'code_tag')

    def test_multiple_code_blocks_and_prose_are_rejected(self):
        for raw in ('```python\nprint(1)\n```\n```python\nprint(2)\n```','Here is the script:\nprint(1)','<code>incomplete'):
            with self.assertRaises(ConfigurationError):parse_candidate_script(raw)

    def make_contract(self, directory):
        root=Path(directory);data=root/'data.json';script=root/'solution.py'
        data.write_text(json.dumps(dataset(count=2)));script.write_text('import json,sys\njson.dump(json.load(sys.stdin)["expressions"],sys.stdout)\n')
        interpreter=root/'python';interpreter.write_text('Reviewed interpreter stand-in; never executed by these unit tests.')
        grader=Path(__file__).resolve().parents[1]/'sage/integrations/coral_simplifier_grader.py'
        return {'schema_version':'sage.coral_task.v1','purpose':'reviewed_integration_smoke','task_id':'test',
            'proposal_sha256':'a'*64,'dataset_path':str(data),'dataset_sha256':file_digest(data),
            'grader_sha256':file_digest(grader),'candidates':[{'attempt_id':'baseline','parent_attempt_id':None,
                'script_path':str(script),'script_sha256':file_digest(script)}],
            'max_attempts':1,'attempt_timeout_seconds':12,'max_wall_seconds':30,
            'candidate_python':str(interpreter),'candidate_python_sha256':file_digest(interpreter)}

    def test_changed_dataset_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory)
            Path(contract['dataset_path']).write_text('{}')
            with self.assertRaises(ConfigurationError):validate_contract(contract)

    def test_changed_candidate_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory)
            Path(contract['candidates'][0]['script_path']).write_text('changed')
            with self.assertRaises(ConfigurationError):validate_contract(contract)

    def test_duplicate_attempt_and_budget_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory);contract['candidates']*=2;contract['max_attempts']=2
            with self.assertRaises(ConfigurationError):validate_contract(contract)
            contract=self.make_contract(directory);contract['max_attempts']=0
            with self.assertRaises(ConfigurationError):validate_contract(contract)

    def test_execution_requires_exact_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory)
            with self.assertRaises(ConfigurationError):run_coral_task(contract,python='python',destination=directory)
            with self.assertRaises(ConfigurationError):run_coral_task(contract,python='python',destination=directory,allow_execution=True,approved_digest='wrong')

    def test_scope_is_not_arbitrary_host_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            contract=self.make_contract(directory);contract['purpose']='arbitrary_autonomous_research'
            with self.assertRaises(ConfigurationError):validate_contract(contract)

    def test_synthetic_task_is_reproducible(self):
        self.assertEqual(dataset(),dataset())
        self.assertNotEqual(dataset(seed=1),dataset(seed=2))
        self.assertEqual(len(dataset()['probes']),16)


class RecordedCorpus(unittest.IsolatedAsyncioTestCase):
    async def test_local_lookup_never_claims_fresh_search(self):
        from sage.recorded import RecordedPaperSource
        from sage.checkpoints import provider_identity
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'corpus.json'
            value={'schema_version':'sage.paper_corpus.v1','provenance':{'scope':'recorded real paper'},
                'papers':[{'paper_id':'arxiv:1234.12345','title':'Symbolic regression hashing',
                           'abstract':'Expression simplification','evidence_scope':'arxiv_html'}]}
            path.write_text(json.dumps(value))
            source=RecordedPaperSource(path)
            self.assertFalse(source.fresh_search)
            rows=await source.search('symbolic regression',limit=2)
            self.assertEqual(rows[0].evidence_scope,'recorded_arxiv_html')
            self.assertEqual(await source.search('unmatchedword',limit=2),[])
            self.assertEqual(provider_identity(source)['corpus_sha256'],file_digest(path))
            previous=source.corpus_sha256;value['papers'][0]['title']='Changed'
            path.write_text(json.dumps(value))
            self.assertNotEqual(previous,RecordedPaperSource(path).corpus_sha256)


if __name__=='__main__':unittest.main()
