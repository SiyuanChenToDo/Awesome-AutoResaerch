import importlib.util
import unittest


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional experiment runtime')
class SupplementaryControls(unittest.TestCase):
    def test_random_gate_never_accesses_probe_values(self):
        import numpy as np
        from sage.execution.sr_controls import ControlledSimplifier
        policy={'hash_bits':64,'probe_count':32,'epsilon':1e-8}
        x=np.array([[0.,0.],[1.,1.]])
        simp=ControlledSimplifier('random_rejection',policy,x,x,1,{'0:0:proposed':10,'0:0:rejected':10})
        # Make a known eligible identity collide, while making probe access fail.
        simp.key=lambda t:'bucket'
        simp.bank['bucket']='x'
        simp.vector=lambda *a,**k: (_ for _ in ()).throw(AssertionError('random gate read probes'))
        tree=('add','x',0.)
        self.assertEqual(simp.simplify(tree),tree)
        self.assertEqual(simp.counts['gate_rejections'],1)

    def test_all_arms_keep_equal_fitness_budgets_and_champion_metrics(self):
        from sage.execution.sr_controls import trial,PROTOCOL
        protocol={**PROTOCOL,'population':8,'generations':1}
        gate=trial('polynomial',9001,'probe_verified',protocol)
        control=trial('polynomial',9001,'random_rejection',protocol,gate['profile'])
        self.assertEqual(gate['fitness_evaluations'],16)
        self.assertEqual(control['fitness_evaluations'],16)
        self.assertIn('test_r2',control)
        self.assertEqual(control['probe_evaluations'],0)


if __name__=='__main__':unittest.main()
