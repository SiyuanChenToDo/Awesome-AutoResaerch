"""Contract, heldout leakage and scientific-analysis regression checks."""
import copy
import importlib.util
import unittest
from sage.errors import ConfigurationError, InvalidResponse
from sage.execution.research import protocol, validate_protocol, native_evaluate
from sage.execution.sr_benchmark import (ARMS, validate_policy, trial, dataset,
                                         Simplifier, analyze)
from sage.orchestration.closed_loop import policy_response, compact_measurements

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


if __name__=='__main__':unittest.main()
