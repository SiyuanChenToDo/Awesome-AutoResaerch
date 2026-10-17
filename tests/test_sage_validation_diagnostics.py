"""Observed missing-diagnostic shape plus controlled rule violations, not invented live replies."""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from sage.checkpoints import Checkpoint, identity
from sage.config import RunConfig
from sage.discussion import validate_revision, strict_object
from sage.discussion.context import compact_payload
from sage.errors import InvalidResponse, ValidationError
from sage.fixtures import FixtureModel, FixtureSource
from sage.runtime import Runtime

UNKNOWN = {'critique_id':'unknown-1','status':'unknown','evidence_ids':['peer'], 'requested_change':'new control'}
SUPPORTED = {'critique_id':'supported-1','status':'supported','evidence_ids':['peer'], 'requested_change':'EXACT CONTROL'}
def response():
    return {'idea':'original unchanged text','evidence_ids':['own'],'accepted_critique_ids':[],
            'rejected_critique_ids':['unknown-1'],'rationale':'unknown not accepted','uncertainty':'unverified'}
def check(v):
    validate_revision(v, original_idea='original unchanged text', own_evidence_ids=['own'], targeted=[UNKNOWN], prior={})

class RuleTests(unittest.TestCase):
    def test_observed_failed_checkpoint_does_not_contain_a_replayable_response(self):
        # This is the metadata shape observed in the real 8-call failure, NOT its missing reply.
        observed=json.loads((Path(__file__).parent/'fixtures/observed_phd2_revision_failure.json').read_text())
        entry=observed['failed_entry']
        self.assertFalse(observed['raw_response_present'])
        self.assertFalse(observed['diagnostic_present'])
        self.assertEqual([e['attempt'] for e in observed['attempts']],[1,2])
        self.assertEqual(observed['model_calls_at_failure'],8)
        self.assertNotIn('value',entry)
        self.assertNotIn('raw_response',entry)
        self.assertNotIn('validation',entry)
        # A generic historical error must not be relabeled as a specific root cause.
        self.assertEqual(ValidationError().diagnostic()['rule'],'unspecified')

    def test_no_acceptance_still_requires_exact_idea_and_does_not_mutate(self):
        good=response();check(good)
        bad=deepcopy(good);bad['idea']+=' paraphrase';snapshot=deepcopy(bad)
        with self.assertRaises(ValidationError) as error:check(bad)
        self.assertEqual(error.exception.diagnostic()['field'],'idea')
        self.assertEqual(error.exception.diagnostic()['rule'],'unchanged_idea')
        self.assertEqual(bad,snapshot)

    def test_ownership_and_unknown_acceptance_have_distinct_diagnostics(self):
        bad=response();bad['evidence_ids']=['peer']
        with self.assertRaises(ValidationError) as error:check(bad)
        self.assertEqual(error.exception.rule,'source_ownership')
        bad=response();bad['accepted_critique_ids']=['unknown-1'];bad['rejected_critique_ids']=[]
        with self.assertRaises(ValidationError) as error:check(bad)
        self.assertEqual(error.exception.rule,'revision_decisions')

    def test_revision_prompt_does_not_grant_unaccepted_peer_sources(self):
        payload={'candidate':{'idea':'x','chain':{'evidence':[{'paper':{'paper_id':'own'}}]}},
                 'evidence_ids':['own','peer'],'critiques':[SUPPORTED,UNKNOWN], 'prior_accepted_critiques':[]}
        compact=compact_payload('revise',payload)
        self.assertEqual(compact['citable_source_ids'],['own'])
        self.assertEqual(compact['source_ids_conditional_on_acceptance'],{'supported-1':['peer']})
        self.assertEqual(compact['evidence_ids'],['own'])

    def test_diagnostics_never_echo_untrusted_json_keys_or_values(self):
        marker='sensitive-output-marker'
        e=ValidationError(marker,marker)
        self.assertNotIn(marker,json.dumps(e.diagnostic()))
        from sage.discussion import fields
        with self.assertRaises(ValidationError) as caught:fields({marker:marker},{'idea':'text'})
        self.assertNotIn(marker,str(caught.exception))
        with self.assertRaises(ValidationError) as caught:strict_object('{"secret":"x","secret":"y"}')
        self.assertEqual(caught.exception.rule,'duplicate_key')

class RuntimeDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, folder, *, retain, always_bad=False):
        class Model:
            def __init__(self):self.requests=[]
            async def complete(self,stage,prompt,*,max_tokens):
                self.requests.append((prompt,max_tokens))
                value=response()
                if len(self.requests)==1 or always_bad:value['idea']='sensitive-output-marker'
                return '<discussion>'+json.dumps(value)+'</discussion>'
        model=Model();source=FixtureSource();cfg=RunConfig(max_tokens_per_call=3000,retry_attempts=2)
        cp=Checkpoint(Path(folder)/'checkpoint.json',identity('x','offline',cfg,None,model,model,source))
        rt=Runtime(model,model,source,cfg,checkpoint=cp,retain_rejected_responses=retain)
        def validator(v):check(strict_object(v['discussion']))
        return model,cp,rt,validator

    async def test_bounded_field_feedback_changes_prompt_and_preserves_evidence_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            model,cp,rt,validator=await self.exercise(folder,retain=False)
            v=await rt.ask('discussion.revise','Original instructions INPUT_JSON:\n{}',('discussion',),validate=validator)
            self.assertEqual(json.loads(v['discussion'])['idea'],'original unchanged text')
            self.assertEqual(rt.usage['model_calls'],2)
            self.assertEqual([x[1] for x in model.requests],[3000,3000])
            self.assertIn('unchanged_idea',model.requests[1][0])
            self.assertNotIn('sensitive-output-marker',model.requests[1][0])
            self.assertEqual(json.loads(model.requests[1][0].split('INPUT_JSON:\n')[1]),{})
            rejected=[e for e in rt.audit if e['status']=='validation_rejected']
            self.assertEqual(rejected[0]['attempt'],1)
            self.assertEqual(rejected[0]['stage'],'discussion.revise')
            self.assertEqual(rejected[0]['validation']['field'],'idea')
            self.assertNotIn('sensitive-output-marker',json.dumps(rt.audit))
            self.assertEqual(cp.rejections,[])

    async def test_repeated_violation_is_still_rejected_and_private_reply_replayable(self):
        with tempfile.TemporaryDirectory() as folder:
            model,cp,rt,validator=await self.exercise(folder,retain=True,always_bad=True)
            with self.assertRaises(ValidationError) as error:
                await rt.ask('discussion.revise','instructions',('discussion',),validate=validator)
            self.assertEqual(error.exception.rule,'unchanged_idea')
            self.assertEqual(len(model.requests),2)
            self.assertEqual(len(cp.rejections),2)
            self.assertEqual([e['attempt'] for e in cp.rejections],[1,2])
            from sage.checkpoints import digest
            for saved in cp.rejections:
                self.assertEqual(digest(saved['raw_request']), saved['request_sha256'])
                value=saved['raw_response'].removeprefix('<discussion>').removesuffix('</discussion>')
                with self.assertRaises(ValidationError) as replay:check(json.loads(value))
                self.assertEqual(replay.exception.diagnostic(),saved['validation'])
            self.assertNotIn('sensitive-output-marker',json.dumps(rt.audit))
            stored=json.loads(cp.path.read_text())['data']
            self.assertEqual(len(stored['rejections']),2)
            self.assertEqual(cp.path.stat().st_mode & 0o777,0o600)
            failed=next(e for e in cp.entries.values() if e['status']=='failed')
            self.assertEqual(failed['validation']['rule'],'unchanged_idea')
