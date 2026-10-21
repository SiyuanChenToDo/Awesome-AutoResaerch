"""Contract, heldout leakage and scientific-analysis regression checks."""
import copy
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from sage.checkpoints import digest
from sage.errors import BudgetExceeded, ConfigurationError, InvalidResponse
from sage.execution.research import protocol, validate_protocol, native_evaluate, _communicate
from sage.execution.sr_benchmark import (ARMS, validate_policy, trial, dataset,
                                         Simplifier, analyze)
from sage.orchestration.closed_loop import policy_response, compact_measurements, run_closed_loop

HAS_NUMPY=importlib.util.find_spec('numpy') is not None


class ResearchContractTests(unittest.TestCase):
    def test_protocol_forbids_changing_holdout_evaluator_and_stopping(self):
        value=protocol();self.assertEqual(value,validate_protocol(value))
        for field,replacement in [('primary_metric','validation_r2'),('confirmation_accesses',2),
                                   ('suite_timeout_seconds',99999),('arms',['probe_verified']),
                                   ('minimum_effect',0),('program_sha256','0'*64)]:
            changed=copy.deepcopy(value);changed[field]=replacement
            with self.assertRaises(ConfigurationError):validate_protocol(changed)

    def test_overlap_and_duplicate_seeds_rejected(self):
        for dev,confirm in [([101,102],[102,103,104,105]),([101,101],[1001,1002,1003,1004])]:
            with self.assertRaises(ConfigurationError):validate_protocol(protocol(development_seeds=dev,confirmation_seeds=confirm))

    def test_model_cannot_submit_code_or_unauthorized_policy(self):
        for value in [{'code':'print(1)'},{'hash_bits':True,'probe_count':32,'epsilon':0},
                      {'hash_bits':64,'probe_count':32,'epsilon':float('nan')}]:
            with self.assertRaises(ValueError):validate_policy(value)
        policy={'hash_bits':64,'probe_count':32,'epsilon':0.0}
        import json
        with self.assertRaises(InvalidResponse):policy_response({'policy':json.dumps(policy)},policy)

    def test_execution_without_exact_authorization_stops_before_process(self):
        with self.assertRaises(ConfigurationError):native_evaluate(protocol(),{'hash_bits':64,'probe_count':32,'epsilon':0},
            'confirmation',destination='unused',coral_python='unused',candidate_python='unused')

    def test_expired_shared_deadline_stops_before_files_or_process(self):
        contract=protocol()
        with patch('sage.execution.research.subprocess.Popen') as launch:
            with self.assertRaises(BudgetExceeded):
                native_evaluate(contract,{'hash_bits':64,'probe_count':32,'epsilon':0},
                    'confirmation',destination='unused',coral_python='unused',candidate_python='unused',
                    allow_execution=True,approved_protocol_digest=digest(contract),deadline=time.monotonic()-1)
            launch.assert_not_called()

    def test_cancelled_native_request_does_not_start_a_process(self):
        contract=protocol();cancel=threading.Event();cancel.set()
        with patch('sage.execution.research.subprocess.Popen') as launch:
            with self.assertRaises(BudgetExceeded):
                native_evaluate(contract,{'hash_bits':64,'probe_count':32,'epsilon':0},
                    'development',destination='unused',coral_python='unused',candidate_python='unused',
                    allow_execution=True,approved_protocol_digest=digest(contract),cancel_event=cancel)
            launch.assert_not_called()


@unittest.skipUnless(HAS_NUMPY,'optional NumPy research runtime not installed')
class ResearchMeasurementTests(unittest.TestCase):
    policy={'hash_bits':64,'probe_count':16,'epsilon':0.0}

    def test_disjoint_inputs_and_development_never_emits_test_results(self):
        import numpy as np
        data=dataset('polynomial',101)
        self.assertFalse(np.array_equal(data['train'][0],data['validation'][0]))
        row=trial('polynomial',101,'probe_verified',self.policy,population=20,generations=5)
        self.assertEqual(row['fitness_evaluations'],120)
        self.assertNotIn('test_r2',row);self.assertNotIn('heldout_semantic_violations',row)
        other=trial('polynomial',101,'probe_verified',self.policy,population=20,generations=5)
        for key in ('champion','validation_r2','final_size','replacement_events'):
            self.assertEqual(row[key],other[key])

    def test_gate_rejects_hash_collision_without_assuming_equivalence(self):
        import numpy as np
        x=np.array([[-.7,.1],[.2,-.3],[.9,.8]])
        ungated=Simplifier('lsh_only',self.policy,x,x,1)
        gated=Simplifier('probe_verified',self.policy,x,x,1)
        # Deliberately force a collision to test the gate, not to score the method.
        for simplifier in (ungated,gated):
            simplifier.key=lambda t:('forced_collision',)
            simplifier.bank[('forced_collision',)]='x'
        tree=('add','x',1.0)
        self.assertEqual(ungated.simplify(tree),'x')
        self.assertEqual(gated.simplify(tree),tree)
        self.assertGreater(gated.counts['gate_rejections'],0)

    def test_analysis_null_negative_and_incomplete_grid(self):
        rows=[]
        for name in ('polynomial','interaction'):
            for seed in range(4):
                for arm in ARMS:
                    rows.append({'benchmark':name,'seed':seed,'arm':arm,'test_r2':.5,
                        'ood_r2':.1,'final_size':5,'wall_seconds':1,'fitness_evaluations':120,
                        'accepted':0,'heldout_semantic_violations':0})
        result={'phase':'confirmation','records':rows}
        analysis=analyze(result,bootstrap_repeats=200)
        self.assertEqual(analysis['primary_claim_status'],'not_supported')
        self.assertEqual(analysis['contrasts'][0]['ci95'],[0,0])
        self.assertEqual(analysis['contrasts'][0]['holm_p'],1)
        for row in rows:
            if row['arm']=='probe_verified':row['test_r2']=.25
        self.assertLess(analyze(result)['contrasts'][0]['mean_delta_test_r2'],0)
        with self.assertRaises(ValueError):analyze({'phase':'confirmation','records':rows[:-1]})
        with self.assertRaises(ValueError):analyze({'phase':'development','records':rows})

    def analysis_for_deltas(self,deltas):
        rows=[]
        for seed,delta in enumerate(deltas):
            for arm in ARMS:
                rows.append({'benchmark':'polynomial','seed':seed,'arm':arm,
                    'test_r2':.5+(delta if arm=='probe_verified' else 0),
                    'ood_r2':.1,'final_size':5,'wall_seconds':1,'fitness_evaluations':120,
                    'accepted':0,'heldout_semantic_violations':0})
        return analyze({'phase':'confirmation','records':rows})

    def test_significant_positive_effect_crossing_minimum_is_inconclusive(self):
        analysis=self.analysis_for_deltas([.001,.005,.009,.014,.025,.039,.055,.07])
        primary=analysis['contrasts'][0]
        self.assertGreater(primary['mean_delta_test_r2'],.02)
        self.assertGreater(primary['ci95'][0],0)
        self.assertLess(primary['ci95'][0],.02)
        self.assertLess(primary['holm_p'],.05)
        self.assertEqual(analysis['primary_claim_status'],'inconclusive')
        decision=analysis['primary_decision']
        self.assertEqual(decision['minimum_effect'],.02)
        self.assertIn('not_a_test_of_minimum_effect',decision['signflip_scope'])

    def test_primary_interval_entirely_below_or_above_minimum(self):
        small=self.analysis_for_deltas([.005,.006,.007,.008,.009,.010,.011,.012])
        self.assertLess(small['contrasts'][0]['holm_p'],.05)
        self.assertEqual(small['primary_claim_status'],'not_supported')
        strong=self.analysis_for_deltas([.03,.035,.04,.045,.05,.055,.06,.065])
        self.assertGreater(strong['contrasts'][0]['ci95'][0],.02)
        self.assertEqual(strong['primary_claim_status'],'supported_in_this_bounded_experiment')


class ClosedLoopDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.contract=protocol()
        class Runtime:
            main_model=cheap_model=source=None
            config=SimpleNamespace()
            left=10000
            def __init__(self):self.usage={};self.audit=[];self.policy_calls=0
            def remaining(self):return self.left
            def event(self,stage,status,**kw):self.audit.append({'stage':stage,'status':status,**kw})
            async def ask(self,stage,prompt,required,**kwargs):
                if stage=='closed_loop.design_review':
                    value={'review':json.dumps({'issues':[],'scope_summary':'Synthetic deadline test only'})}
                else:
                    self.policy_calls+=1
                    value={'policy':json.dumps({'hash_bits':64 if self.policy_calls==1 else 256,'probe_count':32,'epsilon':0})}
                kwargs['validate'](value)
                return value
        self.runtime=Runtime()
        self.proposal=SimpleNamespace(status='completed',experiment=SimpleNamespace(proposal='Synthetic plan'),
            candidates=[SimpleNamespace(idea='Synthetic idea')],selected_index=0,
            to_dict=lambda:{'status':'completed','candidates':[]})
        self.call_args=dict(contract=self.contract,destination=self.root,coral_python='unused',
            candidate_python='unused',allow_execution=True,approved_protocol_digest=digest(self.contract))

    def measurement(self,policy):
        return {'records':[{'arm':arm,'validation_r2':.5,'final_size':5,'accepted':0,'gate_rejections':0}
                           for arm in ARMS]}, {'policy_digest':digest(policy)}

    async def test_wall_expiry_after_development_never_starts_confirmation(self):
        calls=[]
        def evaluate(contract,policy,phase,**kw):
            calls.append((phase,kw['deadline']))
            if len(calls)==2:self.runtime.left=-1
            return self.measurement(policy)
        with patch('sage.orchestration.closed_loop.run',new=AsyncMock(return_value=self.proposal)), \
             patch('sage.orchestration.closed_loop.native_evaluate',side_effect=evaluate):
            result=await run_closed_loop('fixture',self.runtime,**self.call_args)
        self.assertEqual([p for p,_ in calls],['development','development'])
        self.assertEqual(calls[0][1],calls[1][1])
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['errors'][-1],{'stage':'confirmation','code':'budget_exceeded'})
        self.assertFalse((self.root/'confirmation').exists())

    async def test_frozen_execution_deadline_is_not_reset_between_phases(self):
        now=[100.0];calls=[]
        def evaluate(contract,policy,phase,**kw):
            calls.append(phase)
            if len(calls)==2:now[0]+=contract['max_total_execution_seconds']+1
            return self.measurement(policy)
        with patch('sage.orchestration.closed_loop.run',new=AsyncMock(return_value=self.proposal)), \
             patch('sage.orchestration.closed_loop.native_evaluate',side_effect=evaluate), \
             patch('sage.orchestration.closed_loop.time',SimpleNamespace(monotonic=lambda:now[0])):
            result=await run_closed_loop('fixture',self.runtime,**self.call_args)
        self.assertEqual(calls,['development','development'])
        self.assertEqual(result['status'],'stopped')
        self.assertEqual(result['errors'][-1]['code'],'budget_exceeded')

    async def test_cancellation_waits_for_native_cleanup_and_keeps_failure(self):
        entered=threading.Event();cleaned=threading.Event()
        def evaluate(contract,policy,phase,**kw):
            entered.set()
            if not kw['cancel_event'].wait(5):raise AssertionError('Cancellation did not reach native worker')
            cleaned.set()
            raise BudgetExceeded('Synthetic cancelled worker')
        with patch('sage.orchestration.closed_loop.run',new=AsyncMock(return_value=self.proposal)), \
             patch('sage.orchestration.closed_loop.native_evaluate',side_effect=evaluate):
            task=asyncio.create_task(run_closed_loop('fixture',self.runtime,**self.call_args))
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(.01)
            self.assertTrue(entered.is_set())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertTrue(cleaned.is_set())
        result=json.loads((self.root/'result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'cancelled')
        self.assertEqual(result['development_attempts'][0]['status'],'cancelled')


@unittest.skipUnless(sys.platform.startswith('linux'),'real process-group lifecycle requires Linux')
class ResearchProcessDeadlineTests(unittest.TestCase):
    def check_termination(self,cancel):
        # A trusted local Python fixture, not research or CORAL execution. Both
        # the child and grandchild inherit the new session's process group.
        script=('import subprocess,sys,time,json\n'
            'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
            'print(json.dumps({"child":child.pid}),flush=True)\n'
            'time.sleep(30)\n')
        process=subprocess.Popen([sys.executable,'-c',script],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
        event=threading.Event() if cancel else None
        timer=threading.Timer(.4,event.set) if cancel else None
        if timer:timer.start()
        started=time.monotonic()
        try:
            stdout,stderr,reason=_communicate(process,'{}',started+(5 if cancel else .4),event)
        finally:
            if timer:timer.cancel()
        self.assertEqual(reason,'cancelled' if cancel else 'deadline')
        self.assertLess(time.monotonic()-started,3)
        self.assertIsNotNone(process.poll())
        child=json.loads(stdout)['child']
        stat=Path('/proc')/str(child)/'stat'
        # An orphan may be a zombie until init reaps it; it cannot run work.
        for _ in range(100):
            try:state=stat.read_text().rsplit(')',1)[1].split()[0]
            except FileNotFoundError:break
            if state=='Z':break
            time.sleep(.01)
        else:self.fail('Evaluator descendant continued running after group termination')

    def test_deadline_terminates_parent_and_descendant(self):self.check_termination(False)
    def test_cancellation_terminates_parent_and_descendant(self):self.check_termination(True)


if __name__=='__main__':unittest.main()
