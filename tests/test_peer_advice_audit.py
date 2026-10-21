import asyncio
import copy
import json
from types import SimpleNamespace
import unittest

from sage.autonomous.peer_audit import (PEER_AUDIT_VERSION, audit_peer_advice,
                                        peer_advice_prompt, validate_peer_advice)


def fixture():
    document = {'final_export': {'score': 'HISTORICAL_SCORE_SECRET'},
        'accepted': 'ACCEPTED_LABEL_SECRET', 'selected_ids': ['C1'],
        'candidates': [{'id': 'C1', 'title': 'Frozen claim', 'problem': 'Problem',
            'hypothesis': 'Conditional prediction', 'mechanism': 'Mechanism',
            'assumptions': 'Assumptions', 'source_ids': ['p1'],
            'closest_prior_art': [], 'score': 'AUTHOR_SCORE_SECRET',
            'accepted': 'CANDIDATE_ACCEPTED_SECRET'},
            {'id': 'C2', 'title': 'Rejected claim', 'problem': 'Other problem',
             'hypothesis': 'Other claim', 'source_ids': ['p2'],
             'disposition': 'rejected', 'closest_prior_art': []}]}
    evidence = {'papers': {'p1': {'title': 'Source one'}, 'p2': {'title': 'Source two'},
                           'p3': {'title': 'New counterevidence'}},
        'cards': {pid: {'source_spans': {'method': {'text': f'{pid} actual original text',
              'chunk_id': 'chunk1', 'chunk_sha256': 'a' * 64}},
              'source_scope': 'fulltext_partial', 'source_sha256': 'b' * 64}
                  for pid in ['p1', 'p2', 'p3']},
        'reviews': [{'score': 'EVIDENCE_SCORE_SECRET'}],
        'accepted': 'EVIDENCE_ACCEPTED_SECRET'}
    issues = [{'id': 'I1', 'candidate_id': 'C1', 'kind': 'factual',
               'problem': 'The claim overstates evidence', 'repair': 'Remove the unsupported claim',
               'source_ids': ['p3'], 'target_fields': ['hypothesis'],
               'accepted': 'PEER_ACCEPTED_SECRET'},
              {'id': 'I2', 'candidate_id': 'C2', 'kind': 'methodological',
               'problem': 'The estimand is not identified', 'repair': 'Drop a necessary control',
               'source_ids': [], 'target_fields': ['falsification']}]
    value = {'audit_version': PEER_AUDIT_VERSION, 'advice_audits': [
        {'issue_id': 'I1', 'candidate_id': 'C1', 'problem_verdict': 'supported',
         'problem_reason': 'The source states a narrower conditional result.',
         'repair_verdict': 'helpful', 'repair_reason': 'The repair matches the stated scope.',
         'source_ids': ['p3'], 'source_refs': [{'source_id': 'p3', 'reference_id': 'card:method'}],
         'evidence_limit': 'Only the supplied method passage has been inspected.'},
        {'issue_id': 'I2', 'candidate_id': 'C2', 'problem_verdict': 'supported',
         'problem_reason': 'The comparison fails to identify the stated effect.',
         'repair_verdict': 'harmful', 'repair_reason': 'Removing this control adds confounding.',
         'source_ids': [], 'source_refs': [], 'evidence_limit': 'Logical judgment, not experimental validation.'}],
        'summary': 'Adjudicate the harmful remedy independently from the valid problem.'}
    return document, evidence, issues, value


class FakeModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []
        self.last_response_model = 'offline-fixture'
        self.last_usage = {'input_tokens': 1, 'output_tokens': 1}
        self.last_response_id = 'fixture-response'
        self.config = SimpleNamespace(model='offline-fixture')

    async def complete(self, stage, prompt, **kwargs):
        self.calls.append((stage, prompt))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class PeerAdviceTests(unittest.TestCase):
    def test_score_blind_projection_preserves_all_issue_targets_including_rejected(self):
        doc, evidence, issues, _ = fixture()
        before = copy.deepcopy((doc, evidence, issues))
        prompt = peer_advice_prompt(doc, evidence, issues)
        for secret in ('HISTORICAL_SCORE_SECRET', 'ACCEPTED_LABEL_SECRET', 'AUTHOR_SCORE_SECRET',
                       'CANDIDATE_ACCEPTED_SECRET', 'EVIDENCE_SCORE_SECRET',
                       'EVIDENCE_ACCEPTED_SECRET', 'PEER_ACCEPTED_SECRET'):
            self.assertNotIn(secret, prompt)
        self.assertIn('Other claim', prompt)
        self.assertIn('New counterevidence', prompt)
        self.assertEqual(before, (doc, evidence, issues))

    def test_every_issue_gets_independent_problem_and_remedy_judgments(self):
        doc, evidence, issues, value = fixture()
        result = validate_peer_advice(value, doc, evidence, issues)
        self.assertEqual(result['adjudication_required_issue_ids'], ['I2'])
        self.assertFalse(result['automatic_application'])
        self.assertFalse(result['independent_acceptance'])
        first = result['advice_audits'][0]
        self.assertEqual(first['source_quotations'][0]['quotation'], 'p3 actual original text')
        self.assertEqual(result['source_scope_extensions_by_issue']['I1'], ['p3'])

    def test_missing_duplicate_and_wrong_candidate_coverage_are_rejected(self):
        for kind in ('missing', 'duplicate', 'wrong_candidate'):
            with self.subTest(kind=kind):
                doc, evidence, issues, value = fixture()
                if kind == 'missing':
                    value['advice_audits'].pop()
                elif kind == 'duplicate':
                    value['advice_audits'][1] = copy.deepcopy(value['advice_audits'][0])
                else:
                    value['advice_audits'][0]['candidate_id'] = 'C2'
                with self.assertRaises(ValueError):
                    validate_peer_advice(value, doc, evidence, issues)

    def test_new_counterevidence_does_not_grant_other_issues_its_scope(self):
        doc, evidence, issues, value = fixture()
        value['advice_audits'][1]['source_ids'] = ['p3']
        with self.assertRaises(ValueError):
            validate_peer_advice(value, doc, evidence, issues)

    def test_fake_reference_or_paper_id_in_place_of_reference_is_rejected(self):
        for reference in ('p3', 'card:unread', 'passage:invented'):
            doc, evidence, issues, value = fixture()
            value['advice_audits'][0]['source_refs'][0]['reference_id'] = reference
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                validate_peer_advice(value, doc, evidence, issues)

    def test_factual_determinate_needs_original_text_unknown_keeps_gap(self):
        doc, evidence, issues, value = fixture()
        value['advice_audits'][0]['source_refs'] = []
        with self.assertRaises(ValueError):
            validate_peer_advice(value, doc, evidence, issues)
        value['advice_audits'][0]['problem_verdict'] = 'unknown'
        value['advice_audits'][0]['repair_verdict'] = 'unknown'
        result = validate_peer_advice(value, doc, evidence, issues)
        self.assertEqual(result['adjudication_required_issue_ids'], ['I1', 'I2'])

    def test_finite_format_repair_produces_complete_receipt_and_raw_call_history(self):
        doc, evidence, issues, value = fixture()
        bad = copy.deepcopy(value)
        bad['advice_audits'].pop()
        model = FakeModel(json.dumps(bad), json.dumps(value))
        receipt = asyncio.run(audit_peer_advice(model, doc, evidence, issues))
        self.assertEqual(receipt['status'], 'completed')
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(receipt['model_calls']), 2)
        self.assertEqual(model.calls[0][0], 'autonomous.peer_advice_audit')
        self.assertTrue(receipt['original_peer_review_preserved'])

    def test_exhausted_audit_is_unavailable_without_changing_peer_review(self):
        doc, evidence, issues, _ = fixture()
        before = copy.deepcopy(issues)
        model = FakeModel('{}', '{}')
        receipt = asyncio.run(audit_peer_advice(model, doc, evidence, issues))
        self.assertEqual(receipt['status'], 'unavailable')
        self.assertFalse(receipt['complete_audit'])
        self.assertEqual(len(receipt['model_calls']), 2)
        self.assertEqual(before, issues)

    def test_transport_failure_is_unavailable_and_does_not_spend_retry(self):
        doc, evidence, issues, _ = fixture()
        model = FakeModel(OSError('private token-bearing upstream error'))
        receipt = asyncio.run(audit_peer_advice(model, doc, evidence, issues))
        self.assertEqual(receipt['status'], 'unavailable')
        self.assertEqual(len(model.calls), 1)
        self.assertNotIn('private token-bearing', json.dumps(receipt))

    def test_no_peer_issues_needs_no_model_audit(self):
        doc, evidence, _, _ = fixture()
        model = FakeModel()
        receipt = asyncio.run(audit_peer_advice(model, doc, evidence, []))
        self.assertEqual(receipt['status'], 'not_needed')
        self.assertEqual(model.calls, [])


if __name__ == '__main__':
    unittest.main()
