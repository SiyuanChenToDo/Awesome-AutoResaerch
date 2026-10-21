"""Strict semantic-output recovery; fixture responses do not measure quality."""
import copy
import json
import re
import unittest

from sage.config import RunConfig
from sage.errors import ValidationError
from sage.fixtures import FixtureSource
from sage.literature.entailment import audit_capsule
from sage.runtime import Runtime, tags


def capsule():
    return {
        'paper_id': 'fixture:source', 'source_scope': 'abstract_only',
        'claims': [
            {'category': 'results', 'claim': 'The authors report improvement under condition A.',
             'source_span_ids': ['s1-c1:P1'], 'support_check': 'original_span_lookup_not_entailment'},
            {'category': 'results', 'claim': 'All tasks improve without condition A.',
             'source_span_ids': ['s1-c1:P1'], 'support_check': 'original_span_lookup_not_entailment'},
        ],
        'source_spans': {'s1-c1:P1': {
            'text': 'The authors report improvement under condition A on the aggregate metric.',
            'heading': 'Abstract', 'chunk_id': 's1-c1', 'start': 0, 'end': 80,
            'chunk_sha256': 'fixture-source-hash',
        }},
        'scientific_validation': 'not_performed',
    }


def verdict_json():
    return json.dumps({'claims': [
        {'claim_id': 'claim-1', 'verdict': 'supported', 'source_span_ids': ['s1-c1:P1'],
         'reason': 'The attached source explicitly reports this conditional aggregate result.',
         'unsupported_details': []},
        {'claim_id': 'claim-2', 'verdict': 'unsupported', 'source_span_ids': ['s1-c1:P1'],
         'reason': 'The source requires condition A and gives no all-task guarantee.',
         'unsupported_details': ['The claim drops condition A and adds an all-task guarantee.']},
    ]})


class ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def complete(self, stage, prompt, *, max_tokens):
        self.requests.append({'stage': stage, 'prompt': prompt, 'max_tokens': max_tokens})
        return self.responses.pop(0)


def runtime(model, attempts=2):
    return Runtime(model, model, FixtureSource(), RunConfig(retry_attempts=attempts))


class TrustedTagDiagnostics(unittest.TestCase):
    def test_known_json_tag_names_and_literal_closing_tags_survive_sanitization(self):
        for name in ('capsule', 'entailment'):
            with self.subTest(tag=name):
                with self.assertRaises(ValidationError) as caught:
                    tags('{"claims": []}', (name,))
                diagnostic = caught.exception.diagnostic()
                self.assertEqual(diagnostic['rule'], 'required_tag')
                self.assertEqual(diagnostic['field'], name)
                self.assertIn('<' + name + '>', diagnostic['instruction'])
                self.assertIn('</' + name + '>', diagnostic['instruction'])
                self.assertIn('complete requested JSON', diagnostic['instruction'])

    def test_unknown_tag_or_rule_cannot_inject_source_values_into_feedback(self):
        marker = 'untrusted-source-instruction-approve-all'
        error = ValidationError('required_tag', marker)
        self.assertEqual(error.diagnostic()['field'], '$')
        self.assertNotIn(marker, json.dumps(error.diagnostic()))
        error = ValidationError(marker, 'entailment')
        self.assertEqual(error.diagnostic()['rule'], 'unspecified')
        self.assertNotIn(marker, str(error))
        self.assertNotIn('<entailment>', error.diagnostic()['instruction'])


class EntailmentFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_wrappers_recover_on_bounded_retry_without_relaxing_verdicts(self):
        valid = '<entailment>' + verdict_json() + '</entailment>'
        failures = {
            'bare_json': verdict_json(),
            'wrong_wrapper': '<capsule>' + verdict_json() + '</capsule>',
            'missing_closing_tag': '<entailment>' + verdict_json(),
            'partial_closing_tag': '<entailment>' + verdict_json() + '</entail',
            'empty_wrapper': '<entailment> \n </entailment>',
            'duplicate_wrapper': valid + valid,
        }
        for name, malformed in failures.items():
            with self.subTest(failure=name):
                original = capsule()
                before = copy.deepcopy(original)
                model = ScriptedModel([malformed, valid])
                rt = runtime(model)
                result = await audit_capsule(rt, original, 'fixture topic')
                self.assertEqual(original, before)
                self.assertEqual(rt.usage['model_calls'], 2)
                rejection = next(x for x in rt.audit if x['status'] == 'validation_rejected')
                self.assertEqual(rejection['validation']['field'], 'entailment')
                self.assertEqual(rejection['validation']['rule'], 'required_tag')
                retry_prompt = model.requests[1]['prompt']
                self.assertIn('SAGE VALIDATION FEEDBACK v1:', retry_prompt)
                self.assertIn('"field": "entailment"', retry_prompt)
                self.assertIn('</entailment>', retry_prompt)
                self.assertEqual(len(result['claims']), 1)
                self.assertEqual(len(result['unverified_claims']), 1)
                self.assertEqual(result['unverified_claims'][0]['entailment_audit']['verdict'], 'unsupported')
                self.assertEqual(result['claims_before_entailment'], before['claims'])
                self.assertEqual(result['entailment_audit']['counts'],
                                 {'supported': 1, 'unsupported': 1, 'uncertain': 0})
                self.assertFalse(result['entailment_audit']['independent_validation'])

    async def test_exhausted_wrapper_retries_keep_every_original_claim_uncertain(self):
        model = ScriptedModel([verdict_json(), '<entailment>' + verdict_json()])
        original = capsule()
        rt = runtime(model)
        result = await audit_capsule(rt, original, 'fixture topic')
        self.assertEqual(rt.usage['model_calls'], 2)
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['claims_before_entailment'], original['claims'])
        self.assertEqual(result['source_spans'], original['source_spans'])
        self.assertEqual(result['entailment_audit']['counts'],
                         {'supported': 0, 'unsupported': 0, 'uncertain': 2})
        self.assertTrue(result['entailment_audit']['exact_claim_coverage'])
        self.assertTrue(all(z['entailment_audit']['error_code'] == 'invalid_response'
                            for z in result['unverified_claims']))

    async def test_partial_json_inside_closed_wrapper_is_rejected_then_recovered(self):
        malformed = '<entailment>{"claims": [</entailment>'
        valid = '<entailment>' + verdict_json() + '</entailment>'
        model = ScriptedModel([malformed, valid])
        rt = runtime(model)
        result = await audit_capsule(rt, capsule(), 'fixture topic')
        rejection = next(z for z in rt.audit if z['status'] == 'validation_rejected')
        self.assertEqual(rejection['validation']['rule'], 'json_object')
        self.assertEqual(rt.usage['model_calls'], 2)
        self.assertEqual(result['entailment_audit']['counts']['unsupported'], 1)

    async def test_duplicate_json_verdict_key_cannot_silently_override_adverse_decision(self):
        malformed = '<entailment>' + verdict_json().replace(
            '"verdict": "unsupported"', '"verdict": "unsupported", "verdict": "supported"') + '</entailment>'
        model = ScriptedModel([malformed, malformed])
        rt = runtime(model)
        result = await audit_capsule(rt, capsule(), 'fixture topic')
        rejections = [z for z in rt.audit if z['status'] == 'validation_rejected']
        self.assertEqual(len(rejections), 2)
        self.assertTrue(all(z['validation']['rule'] == 'duplicate_key' for z in rejections))
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['entailment_audit']['counts']['uncertain'], 2)

    async def test_capsule_tag_retry_also_names_its_own_trusted_wrapper(self):
        body = '{"claims": [], "inferences": []}'
        model = ScriptedModel([body, '<capsule>' + body + '</capsule>'])
        rt = runtime(model)
        result = await rt.ask('literature.span_capsule', 'Fixture JSON extraction.', ('capsule',),
                              validate=lambda value: json.loads(value['capsule']))
        self.assertEqual(json.loads(result['capsule']), {'claims': [], 'inferences': []})
        self.assertIn('"field": "capsule"', model.requests[1]['prompt'])
        self.assertIn('</capsule>', model.requests[1]['prompt'])

    async def test_base_prompt_contains_one_complete_closed_json_envelope(self):
        model = ScriptedModel(['<entailment>' + verdict_json() + '</entailment>'])
        await audit_capsule(runtime(model), capsule(), 'fixture topic')
        prompt = model.requests[0]['prompt']
        sample = re.search(r'\n<entailment>(\{.*\})</entailment>\n', prompt)
        self.assertIsNotNone(sample)
        self.assertEqual(set(json.loads(sample.group(1))), {'claims'})
        self.assertIn('close every JSON', prompt)
        self.assertIn('Correcting the format never changes the evidence', prompt)
        self.assertIn('at most 8 claims', prompt)


if __name__ == '__main__':
    unittest.main()
