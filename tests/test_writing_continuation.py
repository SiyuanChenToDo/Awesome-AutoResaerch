"""Tamper rejection and read-only lineage; no model, training or network."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sage.checkpoints import digest
from sage.errors import ConfigurationError
from sage.writing.continuation import prepare_report_inputs


class WritingContinuationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.root=Path(self.directory.name)/'run';self.root.mkdir()
        self.addCleanup(self.directory.cleanup)
        program=Path(__file__).parents[1]/'sage/execution/sr_benchmark.py'
        contract={'schema_version':'sage.sr_protocol.v1','program_sha256':hashlib.sha256(program.read_bytes()).hexdigest(),
                  'sage_code_sha256':'a'*64,'bootstrap_repeats':2000}
        proposal={'schema_version':'sage.run.v1','mode':'offline','topic':'Synthetic writing fixture'}
        self.analysis={'schema_version':'sage.sr_analysis.v1','summaries':{'probe_verified':{'test_r2':.5}}}
        measurements={'phase':'confirmation','policy':{'hash_bits':64,'probe_count':32,'epsilon':0},'records':[]}
        selection={'selected_attempt_id':'policy-1','proposal_digest':digest(proposal),'protocol_digest':digest(contract),
                   'policy_digest':digest(measurements['policy']),'policy':measurements['policy']}
        parent={'schema_version':'sage.closed_loop.v1','status':'completed_closed_loop','closure_checks':{'fixture':True},
                'proposal':proposal,'analysis':self.analysis,'selection':selection,
                'development_attempts':[{'attempt_id':'policy-1','status':'measured','selection_score':.4}]}
        values={'result.json':parent,'proposal.json':proposal,'protocol.json':contract,
                'selection.json':selection,'analysis.json':self.analysis,
                'confirmation/measurements.json':measurements,
                'confirmation/receipt.json':{'measurements_digest':digest(measurements),
                    'policy_digest':digest(measurements['policy']),'protocol_digest':digest(contract)}}
        for name,value in values.items():self.write(name,value)
        self.freeze()

    def write(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value),encoding='utf-8')

    def freeze(self):
        self.write('manifest.json',{str(p.relative_to(self.root)).replace('\\','/'):{'bytes':p.stat().st_size,
            'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in self.root.rglob('*') if p.is_file() and p.name!='manifest.json'})

    def prepare(self,analysis=None):
        with patch('sage.execution.sr_benchmark.analyze',return_value=analysis or self.analysis):
            return prepare_report_inputs(self.root)

    def test_validated_lineage_is_read_only_and_preserves_old_source_identity(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        proposal,execution,lineage=self.prepare()
        self.assertEqual(lineage['experiment_sage_code_sha256'],'a'*64)
        self.assertEqual(lineage['new_training_runs'],0)
        self.assertEqual(lineage['new_final_test_accesses'],0)
        self.assertEqual(execution['research_details']['selected_policy']['epsilon'],0)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_modified_measurements_rejected_before_analysis(self):
        self.write('confirmation/measurements.json',{'forged':True})
        with self.assertRaises(ConfigurationError),patch('sage.execution.sr_benchmark.analyze',side_effect=AssertionError):
            prepare_report_inputs(self.root)

    def test_escape_paths_in_manifest_are_rejected(self):
        manifest=json.loads((self.root/'manifest.json').read_text());manifest['../outside']={'bytes':0,'sha256':'0'*64}
        self.write('manifest.json',manifest)
        with self.assertRaises(ConfigurationError):self.prepare()

    def test_missing_required_binding_rejected(self):
        manifest=json.loads((self.root/'manifest.json').read_text());del manifest['selection.json']
        self.write('manifest.json',manifest)
        with self.assertRaises(ConfigurationError):self.prepare()

    def test_rehashed_but_inconsistent_statistics_rejected(self):
        wrong=copy.deepcopy(self.analysis);wrong['summaries']['probe_verified']['test_r2']=.99
        self.write('analysis.json',wrong)
        parent=json.loads((self.root/'result.json').read_text());parent['analysis']=wrong
        self.write('result.json',parent);self.freeze()
        with self.assertRaises(ConfigurationError):self.prepare()

    def test_policy_value_cannot_disagree_with_its_frozen_digest(self):
        selection=json.loads((self.root/'selection.json').read_text());selection['policy']['epsilon']=.0001
        self.write('selection.json',selection)
        parent=json.loads((self.root/'result.json').read_text());parent['selection']=selection
        self.write('result.json',parent);self.freeze()
        with self.assertRaises(ConfigurationError):self.prepare()

    def test_changed_evaluator_cannot_be_used_to_reinterpret_parent_data(self):
        value=json.loads((self.root/'protocol.json').read_text());value['program_sha256']='0'*64
        self.write('protocol.json',value)
        selection=json.loads((self.root/'selection.json').read_text());selection['protocol_digest']=digest(value)
        self.write('selection.json',selection)
        parent=json.loads((self.root/'result.json').read_text());parent['selection']=selection
        self.write('result.json',parent);self.freeze()
        with self.assertRaises(ConfigurationError):self.prepare()


if __name__=='__main__':unittest.main()
