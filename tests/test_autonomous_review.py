"""Synthetic, network-free regressions for the scientific review instrument."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from sage.autonomous.review import (AXES, RUBRIC_VERSION, input_digest, review_prompt,
                                    rubric_descriptor, scientific_input, source_scope,
                                    validate_review)
from sage.autonomous.service import ResearchService
from sage.autonomous.novelty import FEEDBACK_VERSION, advice_targets


def primary_document():
    # All content here is a software fixture, not scientific evidence.
    return {'problem_anchor': 'Fixture bottleneck',
            'known_limitations': ['Fixture protocol is untested'],
            'candidates': [
                {'id': 'C1', 'title': 'Fixture one', 'problem': 'Fixture problem',
                 'hypothesis': 'Fixture prediction', 'source_ids': ['p1'],
                 'closest_prior_art': [{'paper_id': 'p2', 'overlap': 'Fixture', 'difference': 'Fixture'}],
                 'falsification': {'metric': {'score': 0.44, 'name': 'Fixture Brier score'}},
                 'statistics': {'power': 0.8, 'cost': 100},
                 'power_derivation': 'Fixture clustered power model',
                 'evidence_gaps': ['Fixture full text missing'],
                 'origin': {'proposal_sha256': 'a' * 64}},
                {'id': 'C2', 'title': 'Fixture two', 'source_ids': ['p3'], 'closest_prior_art': []},
                {'id': 'HELD', 'title': 'Ledger experiment with blocking flaw',
                 'hypothesis': 'LEDGER_ONLY_SCIENCE', 'disposition': 'held', 'source_ids': ['p4']},
            ], 'selected_ids': ['C1', 'C2']}


def fixture_review(document, rating=8):
    reviews = []
    for candidate in document['candidates']:
        reviews.append({'candidate_id': candidate['id'], 'dimensions': {
            axis: {'rating': rating, 'rationale': 'Fixture evidence-based rationale',
                   'source_ids': [], 'weakness': 'Fixture weakness',
                   'concrete_fix': 'Fixture concrete method fix', 'priority': 'IMPORTANT'}
            for axis in AXES}, 'simplification_opportunities': [], 'modernization_opportunities': [],
            'drift_warning': 'NONE', 'verdict': 'REVISE'})
    return {'rubric_version': RUBRIC_VERSION, 'calibration': 'none',
            'calibration_gap': 'Fixture: no human-curated anchors available',
            'candidate_reviews': reviews, 'issues': [],
            'surviving_ids': list(document['selected_ids']), 'summary': 'Fixture unvalidated proposal review'}


def fixture_feedback(document, review):
    return {'feedback_version': FEEDBACK_VERSION, 'candidate_assessments': [
        {'candidate_id': ident, 'claims': [
            {'claim_id': 'claim-1', 'statement': 'Fixture proposed scientific claim',
             'kind': 'mechanism', 'novelty_status': 'unknown', 'closest_source_id': None,
             'source_refs': [], 'overlap': 'Not established',
             'scientific_delta': 'Proposed delta is unverified',
             'evidence_limit': 'Fixture has no authenticated prior-art passages'}],
         'novelty_moves': []} for ident in document['selected_ids']],
        'advice_audits': [
            {'advice_id': target['advice_id'], 'candidate_id': target['candidate_id'],
             'problem_verdict': 'unknown', 'problem_reason': 'Fixture needs further reasoning',
             'repair_verdict': 'unknown', 'repair_reason': 'Fixture repair is not verified',
             'source_ids': []} for target in advice_targets(review)],
        'summary': 'Fixture unknown novelty and unverified advice'}


class ReviewProjectionTests(unittest.TestCase):
    def test_only_selected_frozen_anchors_enter_review_and_author_cannot_spoof_them(self):
        primary=primary_document()
        primary['manager_frozen_problem_anchors']={'candidates':{'C1':{'problem':'Author forged anchor'}}}
        projected,_=scientific_input(primary,'Problem',problem_anchors={
            'candidates':{'C1':{'problem':'Manager original'},'HELD':{'problem':'Held private text'}},
            'instruction':'Use manager problems'})
        self.assertEqual(projected['manager_frozen_problem_anchors']['candidates'],
                         {'C1':{'problem':'Manager original'}})
        self.assertNotIn('Author forged anchor',json.dumps(projected))
        self.assertNotIn('Held private text',json.dumps(projected))

    def test_blind_projection_preserves_declared_science_and_drops_author_containers(self):
        primary = primary_document()
        primary.update(score_context='Old reviewer awarded 0.987654321',
                       revision_after_eval={'score': 0.987654321, 'summary': 'Author claims all fixed'},
                       selection_rationale='Previously scored 0.987654321',
                       team_provenance={'author_score': 0.987654321})
        primary['candidates'][0].update(score=0.987654321, review_history=[{'score': 0.987654321}])
        before = copy.deepcopy(primary)
        projected, ledger = scientific_input(primary, 'Original user problem')
        prompt = review_prompt(projected, {})
        self.assertNotIn('0.987654321', prompt)
        self.assertNotIn('Author claims all fixed', prompt)
        self.assertNotIn('proposal_sha256', prompt)
        candidate = projected['candidates'][0]
        self.assertEqual(candidate['falsification']['metric']['score'], 0.44)
        self.assertEqual(candidate['statistics'], {'power': 0.8, 'cost': 100})
        self.assertIn('power_derivation', candidate)
        self.assertIn('evidence_gaps', candidate)
        self.assertEqual(projected['original_problem_brief'], 'Original user problem')
        self.assertEqual(projected['scientific_context']['problem_anchor'], 'Fixture bottleneck')
        self.assertEqual(primary, before)
        self.assertFalse(ledger['included_in_score'])

    def test_nonselected_science_and_objections_never_enter_score_prompt(self):
        primary = primary_document()
        primary['open_objections'] = [{'candidate_id': 'C1', 'objection': 'Relevant scientific flaw'},
                                      {'candidate_id': 'HELD', 'objection': 'LEDGER_ONLY_OBJECTION'}]
        projected, ledger = scientific_input(primary, 'Problem')
        prompt = review_prompt(projected, {})
        self.assertNotIn('LEDGER_ONLY_SCIENCE', prompt)
        self.assertNotIn('LEDGER_ONLY_OBJECTION', prompt)
        self.assertIn('Relevant scientific flaw', prompt)
        self.assertEqual(ledger['ids'], ['HELD'])
        self.assertEqual(ledger['scientific_review'], 'not_performed')

    def test_selected_scope_must_be_explicit_unique_and_known(self):
        for selected in (None, [], ['C1', 'C1'], ['MISSING'], ['C1', 1]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                primary = primary_document(); primary['selected_ids'] = selected
                scientific_input(primary, 'Problem')

    def test_candidate_ids_must_be_unique_and_rejected_not_selected(self):
        primary = primary_document(); primary['candidates'][1]['id'] = 'C1'
        with self.assertRaises(ValueError):
            scientific_input(primary, 'Problem')
        primary = primary_document(); primary['candidates'][0]['disposition'] = 'rejected'
        with self.assertRaises(ValueError):
            scientific_input(primary, 'Problem')

    def test_no_nonfinite_scientific_payload_is_transmitted(self):
        primary = primary_document(); primary['candidates'][0]['budget'] = float('nan')
        with self.assertRaises(ValueError):
            scientific_input(primary, 'Problem')


class RubricValidationTests(unittest.TestCase):
    def setUp(self):
        self.document, _ = scientific_input(primary_document(), 'Problem')
        self.scopes = source_scope(self.document, {'p1', 'p2', 'p3'})
        self.value = fixture_review(self.document)

    def test_original_aris_axes_and_weights_are_frozen(self):
        self.assertEqual({axis: entry[0] for axis, entry in AXES.items()}, {
            'problem_fidelity': 15, 'method_specificity': 25, 'contribution_quality': 25,
            'frontier_leverage': 15, 'feasibility': 10, 'validation_focus': 5, 'venue_readiness': 5})
        self.assertEqual(sum(entry[0] for entry in AXES.values()), 100)
        self.assertEqual(rubric_descriptor()['calibration'], 'none')
        self.assertIn('SAGE adaptation', rubric_descriptor()['adaptation'])

    def test_score_is_recomputable_selected_mean_and_ignores_model_scalar(self):
        # C1: .15*10+.25*8+.25*6+.15*4+.1*2+.05*1+.05*9 =6.3
        ratings = [10, 8, 6, 4, 2, 1, 9]
        for dimension, number in zip(self.value['candidate_reviews'][0]['dimensions'].values(), ratings):
            dimension['rating'] = number
        self.value['score'] = 0.99999
        self.value['candidate_scores'] = {'C1': 0.99999}
        result = validate_review(self.value, self.document, self.scopes)
        self.assertEqual(result['candidate_scores'], {'C1': 0.63, 'C2': 0.8})
        self.assertEqual(result['score'], 0.715)
        self.assertFalse(result['independent_acceptance'])
        self.assertEqual(result['score_scope'], ['C1', 'C2'])
        self.assertEqual(self.value['score'], 0.99999)

    def test_one_is_point_one_and_no_monotonic_improvement_rule(self):
        low = validate_review(fixture_review(self.document, 1), self.document, self.scopes)
        high = validate_review(fixture_review(self.document, 8), self.document, self.scopes)
        self.assertEqual(low['score'], 0.1)
        self.assertLess(low['score'], high['score'])

    def test_seven_ratings_required_for_each_selected_candidate(self):
        for mutate in (lambda v: v['candidate_reviews'].pop(),
                       lambda v: v['candidate_reviews'].append(copy.deepcopy(v['candidate_reviews'][0])),
                       lambda v: v['candidate_reviews'][0]['dimensions'].pop('feasibility'),
                       lambda v: v['candidate_reviews'][0].update(candidate_id='HELD')):
            value = copy.deepcopy(self.value); mutate(value)
            with self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_below_seven_requires_actionable_weakness_fix_and_priority(self):
        for key in ('weakness', 'concrete_fix', 'priority'):
            value = copy.deepcopy(self.value)
            dimension = value['candidate_reviews'][0]['dimensions']['feasibility']
            dimension['rating'] = 6; dimension.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_dimensions_need_rationale_and_explicit_source_ids(self):
        for key in ('rationale', 'source_ids'):
            value = copy.deepcopy(self.value)
            value['candidate_reviews'][0]['dimensions']['feasibility'].pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_invalid_numeric_types_and_ranges_fail(self):
        for number in (True, None, '8', float('nan'), float('inf'), 0, 11):
            value = copy.deepcopy(self.value)
            value['candidate_reviews'][0]['dimensions']['feasibility']['rating'] = number
            with self.subTest(number=number), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_issue_schema_prevents_historical_missing_repair_success(self):
        issue = {'candidate_id': 'C1', 'severity': 'high', 'problem': 'Fixture mathematical contradiction',
                 'repair': 'Fixture repair', 'source_ids': []}
        self.value['issues'] = [issue]
        validate_review(self.value, self.document, self.scopes)
        for key in issue:
            value = copy.deepcopy(self.value); value['issues'][0].pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_issue_scope_severity_and_sources_are_validated(self):
        issue = {'candidate_id': 'C1', 'severity': 'high', 'problem': 'Fixture problem',
                 'repair': 'Fixture repair', 'source_ids': ['p2']}
        self.value['issues'] = [issue]
        validate_review(self.value, self.document, self.scopes)
        for mutation in ({'candidate_id': 'HELD'}, {'severity': 'CRITICAL'}, {'problem': ''},
                         {'repair': None}, {'source_ids': ['p3']}, {'source_ids': ['invented']},
                         {'source_ids': ['p1', 'p1']}):
            value = copy.deepcopy(self.value); value['issues'][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_known_peer_source_is_not_a_source_for_this_candidate(self):
        self.value['candidate_reviews'][0]['dimensions']['feasibility']['source_ids'] = ['p3']
        with self.assertRaises(ValueError):
            validate_review(self.value, self.document, self.scopes)

    def test_out_of_scope_dimension_source_ids_carry_id_level_detail(self):
        dimension = self.value['candidate_reviews'][0]['dimensions']['feasibility']
        dimension['source_ids'] = ['p3', 'FAKE']
        with self.assertRaises(ValueError) as caught:
            validate_review(self.value, self.document, self.scopes)
        exc = caught.exception
        self.assertEqual(str(exc), 'feasibility source_ids contains an unknown or out-of-scope ID')
        detail = exc.detail
        self.assertEqual(detail['reason'], 'unknown_or_out_of_scope_id')
        self.assertEqual(detail['field'], 'feasibility source_ids')
        self.assertEqual(detail['offending'], ['FAKE', 'p3'])
        self.assertEqual(detail['candidate_id'], 'C1')
        self.assertEqual(detail['allowed'], ['p1', 'p2'])

    def test_issue_source_ids_detail_names_candidate_scope(self):
        self.value['issues'] = [{'candidate_id': 'C1', 'severity': 'low',
                                 'problem': 'Fixture problem', 'repair': 'Fixture repair',
                                 'source_ids': ['p3']}]
        with self.assertRaises(ValueError) as caught:
            validate_review(self.value, self.document, self.scopes)
        self.assertEqual(str(caught.exception),
                         'Issue source_ids contains an unknown or out-of-scope ID')
        detail = caught.exception.detail
        self.assertEqual(detail['candidate_id'], 'C1')
        self.assertEqual(detail['offending'], ['p3'])
        self.assertEqual(detail['allowed'], ['p1', 'p2'])

    def test_surviving_ids_detail_has_no_candidate_binding(self):
        self.value['surviving_ids'] = ['C1', 'GHOST']
        with self.assertRaises(ValueError) as caught:
            validate_review(self.value, self.document, self.scopes)
        detail = caught.exception.detail
        self.assertEqual(detail['offending'], ['GHOST'])
        self.assertEqual(detail['candidate_id'], None)
        self.assertEqual(detail['allowed'], ['C1', 'C2'])

    def test_survivors_and_no_fabricated_calibration_are_validated(self):
        for mutation in ({'surviving_ids': ['HELD']}, {'surviving_ids': ['C1', 'C1']},
                         {'calibration': 'anchored'}, {'calibration_gap': ''}, {'summary': ''},
                         {'rubric_version': 'old-holistic'}):
            value = copy.deepcopy(self.value); value.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_review(value, self.document, self.scopes)

    def test_ready_is_advisory_and_requires_original_score_and_drift_conditions(self):
        self.value['candidate_reviews'][0]['verdict'] = 'READY'
        with self.assertRaises(ValueError):
            validate_review(self.value, self.document, self.scopes)
        ready = fixture_review(self.document, 9)
        ready['candidate_reviews'][0]['verdict'] = 'READY'
        self.assertFalse(validate_review(ready, self.document, self.scopes)['independent_acceptance'])
        ready['candidate_reviews'][0]['drift_warning'] = 'Fixture method changes the original problem'
        with self.assertRaises(ValueError):
            validate_review(ready, self.document, self.scopes)

    def test_ready_cannot_coexist_with_own_blocking_issue_but_provisional_can_survive(self):
        value = fixture_review(self.document, 9)
        value['candidate_reviews'][0]['verdict'] = 'READY'
        issue = {'candidate_id': 'C2', 'severity': 'high',
                 'problem': 'Fixture core mathematical contradiction',
                 'repair': 'Fixture correct the hypothesis and rejection rule', 'source_ids': []}
        value['issues'] = [issue]
        # Another candidate's unresolved problem does not invalidate C1's verdict.
        validate_review(value, self.document, self.scopes)
        issue['candidate_id'] = 'C1'
        with self.assertRaisesRegex(ValueError, 'READY.*blocking high'):
            validate_review(value, self.document, self.scopes)
        value['candidate_reviews'][0]['verdict'] = 'REVISE'
        result = validate_review(value, self.document, self.scopes)
        self.assertIn('C1', result['surviving_ids'])
        self.assertFalse(result['independent_acceptance'])


class ServiceReviewTests(unittest.TestCase):
    def service_and_model(self, root, response=None):
        service = ResearchService(root / 'private', root, 'Original fixture problem',
                                  review_repair_attempts=0)
        service.papers = {pid: {'paper_id': pid, 'title': 'Fixture source', 'evidence_scope': 'metadata_only'}
                          for pid in ('p1', 'p2', 'p3', 'p4')}
        projected, _ = scientific_input(primary_document(), service.topic)
        review = response if response is not None else fixture_review(projected)
        model = SimpleNamespace(config=SimpleNamespace(model='fixture-model'), last_usage={'output_tokens': 100},
                                last_response_model='fixture-model',
                                complete=mock.AsyncMock(side_effect=[json.dumps(review),
                                    json.dumps(fixture_feedback(projected, review))]),
                                aclose=mock.AsyncMock())
        return service, model

    def test_service_sends_blind_payload_but_binds_original_sha_and_frozen_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); service, model = self.service_and_model(root)
            primary = primary_document()
            primary['score_context'] = 'AUTHOR_PREVIOUS_SCORE_0.987654321'
            primary['final_export'] = {'label': 'FINAL_EXPORT_LEAK',
                                       'note': 'Past score 0.987654321 led to rollback'}
            primary['candidates'][0]['private_diagnostics_new_name'] = {
                'explanation': 'CANDIDATE_UNKNOWN_CONTAINER_LEAK'}
            raw = json.dumps(primary)
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                receipt = asyncio.run(service.judgment(raw, 'FOCUS_LEAK_0.123456789', grading=True))
            prompt = model.complete.call_args_list[0].args[1]
            self.assertNotIn('AUTHOR_PREVIOUS_SCORE', prompt)
            self.assertNotIn('FINAL_EXPORT_LEAK', prompt)
            self.assertNotIn('CANDIDATE_UNKNOWN_CONTAINER_LEAK', prompt)
            self.assertNotIn('FOCUS_LEAK', prompt)
            self.assertNotIn('LEDGER_ONLY_SCIENCE', prompt)
            self.assertNotIn('"p4":', prompt)
            self.assertIn('Original fixture problem', prompt)
            self.assertEqual(receipt['input_sha256'], hashlib.sha256(raw.encode()).hexdigest())
            request = json.loads((service.private / receipt['request_file']).read_text(encoding='utf-8'))
            self.assertEqual(request['primary_raw'], raw)
            self.assertEqual(request['focus'], 'FOCUS_LEAK_0.123456789')
            self.assertFalse(request['focus_transmitted'])
            self.assertEqual(receipt['scientific_input_sha256'], input_digest(request['scientific_input']))
            self.assertEqual(receipt['evidence_sha256'], input_digest(request['evidence']))
            self.assertEqual(receipt['review']['score'], 0.8)
            self.assertEqual(receipt['ledger_report']['ids'], ['HELD'])
            self.assertEqual([call.args[0] for call in model.complete.call_args_list],
                             ['autonomous.scientific_review', 'autonomous.novelty_feedback'])
            self.assertEqual(len(receipt['model_calls']), 2)
            self.assertEqual(receipt['feedback_version'], FEEDBACK_VERSION)
            novelty_request = json.loads((service.private / receipt['novelty_request_file']).read_text(encoding='utf-8'))
            self.assertEqual(novelty_request['evidence_sha256'], receipt['evidence_sha256'])
            self.assertEqual(novelty_request['scientific_input_sha256'], receipt['scientific_input_sha256'])
            self.assertEqual(novelty_request['prompt_sha256'], input_digest(novelty_request['prompt']))
            self.assertNotIn('AUTHOR_PREVIOUS_SCORE', novelty_request['prompt'])
            self.assertNotIn('FINAL_EXPORT_LEAK', novelty_request['prompt'])
            self.assertNotIn('CANDIDATE_UNKNOWN_CONTAINER_LEAK', novelty_request['prompt'])
            self.assertNotIn('FOCUS_LEAK', novelty_request['prompt'])
            model.aclose.assert_awaited_once()

    def test_novelty_audit_is_score_blind_and_does_not_silently_rescore_disagreement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document, _ = scientific_input(primary_document(), 'Original fixture problem')
            response = fixture_review(document)
            response['summary'] = 'SECRET_NUMERIC_ANCHOR_0.99112233'
            response['issues'] = [{'candidate_id': 'C1', 'severity': 'medium',
                'problem': 'Fixture alleged problem', 'repair': 'Fixture proposed repair', 'source_ids': []}]
            feedback = fixture_feedback(document, response)
            feedback['advice_audits'][0].update(problem_verdict='disputed', repair_verdict='harmful')
            service, model = self.service_and_model(root, response)
            model.complete.side_effect = [json.dumps(response), json.dumps(feedback)]
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                receipt = asyncio.run(service.judgment(json.dumps(primary_document()), 'Fixture'))
            self.assertNotIn('SECRET_NUMERIC_ANCHOR', model.complete.call_args_list[1].args[1])
            self.assertEqual(receipt['review']['score'], 0.8)
            self.assertTrue(receipt['novelty_feedback']['requires_adjudication'])
            self.assertFalse(receipt['independent_acceptance'])

    def test_incomplete_second_stage_cannot_leave_a_complete_review_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); service, model = self.service_and_model(root)
            document, _ = scientific_input(primary_document(), service.topic)
            model.complete.side_effect = [json.dumps(fixture_review(document)), '{}']
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                with self.assertRaises(ValueError):
                    asyncio.run(service.judgment(json.dumps(primary_document()), 'Fixture', grading=True))
            self.assertEqual(service.reviews, [])
            events = [json.loads(line) for line in (service.private / 'events.jsonl').read_text().splitlines()]
            self.assertEqual([event['stage'] for event in events
                              if event['kind'] == 'review_stage_response'],
                             ['scientific_review', 'novelty_feedback'])
            failure = next(event for event in events if event['kind'] == 'review_failed')
            self.assertEqual(failure['stage'], 'novelty_feedback')
            self.assertNotIn('review_completed', [event['kind'] for event in events])
            self.assertEqual(model.complete.await_count, 2)
            model.aclose.assert_awaited_once()

    def test_malformed_critic_never_creates_success_receipt_or_grade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); service, model = self.service_and_model(root, {'score': 0.99, 'issues': []})
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                with self.assertRaises(ValueError):
                    asyncio.run(service.judgment(json.dumps(primary_document()), 'Fixture focus', grading=True))
            self.assertEqual(service.reviews, [])
            self.assertEqual(service.grades, [])
            events = [json.loads(line) for line in (service.private / 'events.jsonl').read_text().splitlines()]
            self.assertIn('review_stage_response', [x['kind'] for x in events])
            self.assertIn('review_failed', [x['kind'] for x in events])
            self.assertNotIn('review_completed', [x['kind'] for x in events])
            model.aclose.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
