import asyncio
import dataclasses
import unittest
from sage.config import RunConfig
from sage.runtime import Runtime
from sage.types import ExperimentPlan
from sage.execution import ExperimentRunner
from sage.execution.commands import apply_command
from sage.execution.contracts import EvaluationContract
from sage.execution.fixtures import fixture_contract, TrustedFixtureBackend, LaboratoryFixtureModel, BASELINE_CODE, IMPROVED_CODE
from sage.fixtures import FixtureSource
from sage.errors import ConfigurationError


class Model:
    def __init__(self, answers): self.answers = iter(answers)
    async def complete(self, stage, prompt, *, max_tokens): return next(self.answers)


def response(code): return f'<command>```REPLACE\n{code}\n```</command>'


def runner(model=None, contract=None, execute=False, backend=None):
    contract = contract or fixture_contract()
    runtime = Runtime(model or LaboratoryFixtureModel(), model or LaboratoryFixtureModel(), FixtureSource(), RunConfig())
    return ExperimentRunner(runtime, contract, backend=(backend or TrustedFixtureBackend()) if execute else None,
                            allow_execution=execute, approved_contract_digest=contract.sha256 if execute else None)


class Commands(unittest.TestCase):
    def test_replace(self): self.assertEqual(apply_command('```REPLACE\nx=1\n```'), 'x=1')
    def test_edit_inclusive(self): self.assertEqual(apply_command('```EDIT 1 2\nz\n```','a\nb\nc\nd'), 'a\nz\nd')
    def test_invalid(self):
        for cmd in ('```EDIT 1 9\nx\n```','```EDIT 2 1\nx\n```','```EDIT -1 0\nx\n```','```REPLACE\nx\n``` extra','```REPLACE\nx\n```\n```REPLACE\ny\n```'):
            with self.subTest(cmd=cmd), self.assertRaises(ValueError): apply_command(cmd, 'a\nb')


class Contracts(unittest.TestCase):
    def test_frozen(self):
        contract=fixture_contract()
        with self.assertRaises(dataclasses.FrozenInstanceError): contract.max_attempts=90
        with self.assertRaises(ConfigurationError): dataclasses.replace(contract, targets=[1,2,3])
        self.assertNotIn('targets',contract.public_record())
    def test_metric(self): self.assertEqual(fixture_contract().evaluate([0,2,4]), {'mse':0})
    def test_invalid_predictions(self):
        for x in ([0,2], [0,float('nan'),4], [0,True,4], {'mse':0}, [0,1e308,4]):
            with self.subTest(x=x), self.assertRaises((ValueError,OverflowError)): fixture_contract().evaluate(x)
    def test_digest_changes(self):
        c=fixture_contract(); self.assertNotEqual(c.sha256,dataclasses.replace(c,max_attempts=2).sha256)
    def test_approval(self):
        with self.assertRaises(ConfigurationError): ExperimentRunner(None,fixture_contract(),backend=TrustedFixtureBackend())
        with self.assertRaises(ConfigurationError): ExperimentRunner(None,fixture_contract(),backend=TrustedFixtureBackend(),allow_execution=True,approved_contract_digest='wrong')


class Execution(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run(self):
        result=await runner().run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'dry_run'); self.assertIsNone(result['selected_attempt_id'])
        self.assertEqual(result['attempts'][0]['metrics'],{})
    async def test_improvement(self):
        result=await runner(execute=True).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'completed_fixture'); self.assertEqual(len(result['attempts']),2)
        self.assertGreater(result['attempts'][0]['metrics']['mse'],0)
        self.assertEqual(result['selected_attempt_id'],'attempt-2')
    async def test_repair(self):
        model=Model([response('bad syntax !'),response(IMPROVED_CODE)])
        result=await runner(model,execute=True).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['attempts'][0]['status'],'failed')
        self.assertIn('line 1', result['attempts'][0]['diagnostic'])
        self.assertEqual(result['attempts'][1]['kind'],'repair')
        self.assertEqual(result['status'],'completed_fixture')
    async def test_invalid_command_counted(self):
        result=await runner(Model(['<command>bad</command>']*3),execute=True).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'repair_budget_exhausted'); self.assertEqual(len(result['attempts']),2)
    async def test_no_arbitrary_fixture_execution(self):
        result=await runner(Model([response('raise SystemExit("evil")')]*3),execute=True).run(ExperimentPlan('synthetic'))
        self.assertTrue(all(x['status']=='failed' for x in result['attempts']))
    async def test_backend_error_retained(self):
        class Backend:
            fixture=False
            async def predict(self,*a,**k): raise RuntimeError('secret path')
        result=await runner(Model([response(BASELINE_CODE)]*3),execute=True,backend=Backend()).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['attempts'][0]['error'],'backend_error'); self.assertNotIn('secret',str(result))
    async def test_candidate_diagnostic_reaches_repair(self):
        from sage.execution.contracts import BackendExecutionError
        class Backend:
            fixture=False
            calls=0
            async def predict(self,*a,**k):
                self.calls+=1
                if self.calls==1: raise BackendExecutionError('candidate failed',diagnostic='candidate.py line 2: missing variable')
                return [0,2,4]
        class CapturingModel(Model):
            prompts=[]
            async def complete(self,stage,prompt,**kwargs):
                self.prompts.append(prompt)
                return await super().complete(stage,prompt,**kwargs)
        model=CapturingModel([response(BASELINE_CODE),response(IMPROVED_CODE)])
        result=await runner(model,execute=True,backend=Backend()).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'completed_development')
        self.assertIn('candidate.py line 2',model.prompts[1])
        self.assertIn('missing variable',result['attempts'][0]['diagnostic'])

    async def test_all_failed_exhaustion_is_not_success(self):
        c=dataclasses.replace(fixture_contract(),max_attempts=1)
        result=await runner(Model([response('bad !')]),contract=c,execute=True).run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'no_valid_candidate')
        self.assertIsNone(result['selected_attempt_id'])

    async def test_budget(self):
        r=runner(execute=True);r.runtime.config=RunConfig(max_model_calls=1)
        result=await r.run(ExperimentPlan('synthetic'))
        self.assertEqual(result['status'],'stopped'); self.assertEqual(r.runtime.usage['model_calls'],1)

if __name__=='__main__': unittest.main()
