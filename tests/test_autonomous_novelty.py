"""Synthetic adversarial checks for the second, score-blind advisory pass."""
import copy
import json
import unittest

from sage.autonomous.novelty import (FEEDBACK_VERSION, advice_targets,
                                     feedback_prompt, validate_feedback)


def novelty_fixture():
    # Invented software fixtures below are not scientific evidence.
    document = {'selected_ids': ['C1', 'C2'], 'candidates': [
        {'id': 'C1', 'hypothesis': 'Fixture mechanism', 'source_ids': ['p1'],
         'closest_prior_art': [{'paper_id': 'p1', 'overlap': 'Fixture', 'difference': 'Fixture'}]},
        {'id': 'C2', 'hypothesis': 'Fixture finding', 'source_ids': ['p2'],
         'closest_prior_art': [{'paper_id': 'p2', 'overlap': 'Fixture', 'difference': 'Fixture'}]}]}
    evidence = {'papers': {'p1': {'title': 'Fixture prior one'},
                           'p2': {'title': 'Fixture prior two'}},
                'cards': {'p1': {'source_scope': 'supplied_fixture_text',
                    'source_sha256': 'a' * 64,
                    'source_spans': {'section:P1': {'text': 'Exact fixture source passage.',
                        'chunk_id': 'section', 'start': 0, 'end': 29}}}},
                'targeted_original_passages': {'p2': [{'chunk_id': 'methods',
                    'heading': 'Fixture methods', 'text': 'Exact fixture targeted text.'}]}}
    scopes = {'C1': {'p1'}, 'C2': {'p2'}}
    review = {'score': 0.987654321, 'verdict': 'HIDDEN_OLD_VERDICT', 'surviving_ids': ['C1'],
              'issues': [{'candidate_id': 'C1', 'problem': 'Fixture proposed contradiction',
                          'repair': 'Fixture proposed remedy', 'source_ids': []}],
              'candidate_reviews': [{
                  'candidate_id': ident, 'dimensions': {'feasibility': {
                      'rating': 6, 'rationale': 'Fixture feasibility reasoning',
                      'weakness': 'Fixture resource concern', 'concrete_fix': 'Fixture minimal repair',
                      'source_ids': []}}, 'simplification_opportunities': [],
                  'modernization_opportunities': [], 'verdict': 'HIDDEN_OLD_VERDICT'}
                  for ident in ('C1', 'C2')]}
    value = {'feedback_version': FEEDBACK_VERSION, 'candidate_assessments': [{
        'candidate_id': ident, 'claims': [{'claim_id': 'claim-1',
            'statement': 'Fixture central proposed claim', 'kind': 'mechanism',
            'novelty_status': 'unknown', 'closest_source_id': None, 'source_refs': [],
            'overlap': 'No established duplication', 'scientific_delta': 'Fixture proposed distinction',
            'evidence_limit': 'Fixture corpus is partial, no search executed'}],
        'novelty_moves': []} for ident in ('C1', 'C2')],
        'advice_audits': [{'advice_id': target['advice_id'],
            'candidate_id': target['candidate_id'], 'problem_verdict': 'unknown',
            'problem_reason': 'Fixture logic requires checking', 'repair_verdict': 'unknown',
            'repair_reason': 'Fixture remedy requires checking', 'source_ids': []}
            for target in advice_targets(review)],
        'summary': 'Fixture only: scientific correctness not established'}
    return document, evidence, scopes, review, value


class NoveltyFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.document, self.evidence, self.scopes, self.review, self.value = novelty_fixture()

    def validate(self, value=None):
        return validate_feedback(self.value if value is None else value, self.document,
                                 self.scopes, self.evidence, self.review)

    def test_unknown_is_explicit_and_no_automatic_scientific_acceptance(self):
        result = self.validate()
        self.assertFalse(result['independent_acceptance'])
        self.assertFalse(result['automatic_application'])
        self.assertFalse(result['requires_adjudication'])
        self.assertEqual(result['candidate_status'], {'C1': 'EVIDENCE_NEEDED', 'C2': 'EVIDENCE_NEEDED'})
        self.assertEqual(result['proposed_search_status'], 'not_executed')
        self.assertEqual(result['validation_scope'], 'contract_and_source_integrity_not_scientific_correctness')
        self.assertNotIn('requires_adjudication', self.value)

    def test_advice_targets_include_issues_and_all_explicit_dimension_fixes(self):
        targets = advice_targets(self.review)
        self.assertEqual([t['advice_id'] for t in targets], [
            'issue:0', 'dimension:C1:feasibility', 'dimension:C2:feasibility'])
        # A concrete fix remains advice even if its original rating is high.
        self.review['candidate_reviews'][0]['dimensions']['feasibility']['rating'] = 9
        self.assertEqual(advice_targets(self.review), targets)
        self.assertNotIn('rating', json.dumps(targets))

    def test_second_prompt_does_not_receive_numeric_first_review_or_verdict(self):
        before = copy.deepcopy(self.review)
        prompt = feedback_prompt(self.document, self.evidence, self.review)
        self.assertNotIn('0.987654321', prompt)
        self.assertNotIn('HIDDEN_OLD_VERDICT', prompt)
        self.assertNotIn('"rating"', prompt)
        self.assertNotIn('"surviving_ids"', prompt)
        self.assertIn('Fixture proposed remedy', prompt)
        self.assertIn('Fixture minimal repair', prompt)
        self.assertIn('card:section:P1', prompt)
        self.assertIn('passage:methods', prompt)
        self.assertEqual(prompt.count('Exact fixture source passage.'), 1)
        self.assertEqual(prompt.count('Exact fixture targeted text.'), 1)
        self.assertEqual(self.review, before)

    def test_candidate_coverage_is_exact_and_selected_only(self):
        for mutate in (lambda v: v['candidate_assessments'].pop(),
                       lambda v: v['candidate_assessments'].append(copy.deepcopy(v['candidate_assessments'][0])),
                       lambda v: v['candidate_assessments'][0].update(candidate_id='HELD')):
            value = copy.deepcopy(self.value); mutate(value)
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_atomic_claims_are_required_unique_and_typed(self):
        for mutate in (lambda c: c.update(claims=[]),
                       lambda c: c['claims'].append(copy.deepcopy(c['claims'][0])),
                       lambda c: c['claims'][0].update(kind='marketing'),
                       lambda c: c['claims'][0].update(statement=' ')):
            value = copy.deepcopy(self.value); mutate(value['candidate_assessments'][0])
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_determinate_judgments_need_named_prior_work_and_original_text(self):
        for status in ('covered', 'distinct_within_evidence'):
            for mutate in (lambda c: c.update(novelty_status=status),
                           lambda c: c.update(novelty_status=status, closest_source_id='p1')):
                value = copy.deepcopy(self.value); mutate(value['candidate_assessments'][0]['claims'][0])
                with self.assertRaises(ValueError):
                    self.validate(value)

    def test_manager_copies_exact_span_instead_of_model_quote(self):
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim.update(novelty_status='distinct_within_evidence', closest_source_id='p1',
                     source_refs=[{'source_id': 'p1', 'reference_id': 'card:section:P1'}])
        result = self.validate()
        quotation = result['candidate_assessments'][0]['claims'][0]['source_quotations'][0]
        self.assertEqual(quotation['quotation'], 'Exact fixture source passage.')
        self.assertEqual(quotation['source_sha256'], 'a' * 64)
        self.assertEqual(quotation['integrity_check'], 'manager_source_lookup_not_entailment')
        self.assertNotIn('source_quotations', claim)

    def test_original_targeted_passage_can_support_comparison(self):
        claim = self.value['candidate_assessments'][1]['claims'][0]
        claim.update(novelty_status='covered', closest_source_id='p2',
                     source_refs=[{'source_id': 'p2', 'reference_id': 'passage:methods'}])
        result = self.validate()
        quotation = result['candidate_assessments'][1]['claims'][0]['source_quotations'][0]
        self.assertEqual(quotation['quotation'], 'Exact fixture targeted text.')
        self.assertEqual(len(quotation['source_metadata']['text_sha256']), 64)
        self.assertEqual(result['candidate_status']['C2'], 'EVIDENCE_NEEDED')

    def test_supported_prior_art_cannot_hide_unresolved_advice_in_summary_status(self):
        claim = self.value['candidate_assessments'][1]['claims'][0]
        claim.update(novelty_status='distinct_within_evidence', closest_source_id='p2',
                     source_refs=[{'source_id': 'p2', 'reference_id': 'passage:methods'}])
        audit = next(item for item in self.value['advice_audits'] if item['candidate_id'] == 'C2')
        audit.update(problem_verdict='supported', repair_verdict='helpful')
        self.assertEqual(self.validate()['candidate_status']['C2'], 'PROVISIONAL')
        for field in ('problem_verdict', 'repair_verdict'):
            value = copy.deepcopy(self.value)
            next(item for item in value['advice_audits'] if item['candidate_id'] == 'C2')[field] = 'unknown'
            self.assertEqual(self.validate(value)['candidate_status']['C2'], 'EVIDENCE_NEEDED')
        audit.update(problem_verdict='disputed', repair_verdict='unknown')
        self.assertEqual(self.validate()['candidate_status']['C2'], 'ADJUDICATE')

    def test_title_metadata_alone_cannot_substitute_for_comparison_text(self):
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim.update(novelty_status='covered', closest_source_id='p1',
                     source_refs=[{'source_id': 'p1', 'reference_id': 'card:section:P1'}])
        self.evidence['cards']['p1']['source_spans'] = {}
        with self.assertRaises(ValueError):
            self.validate()

    def test_closest_source_must_be_named_not_just_an_opaque_id(self):
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim.update(novelty_status='covered', closest_source_id='p1',
                     source_refs=[{'source_id': 'p1', 'reference_id': 'card:section:P1'}])
        self.evidence['papers']['p1'].pop('title')
        with self.assertRaises(ValueError):
            self.validate()

    def test_forged_out_of_scope_or_mismatched_source_refs_fail(self):
        for ref in ({'source_id': 'FAKE', 'reference_id': 'card:section:P1'},
                    {'source_id': 'p1', 'reference_id': 'card:FAKE'},
                    {'source_id': 'p2', 'reference_id': 'passage:methods'},
                    {'source_id': 'p1', 'reference_id': 'passage:methods'},
                    {'source_id': 'p1', 'reference_id': 'card:section:P1', 'quotation': 'Forged model quote'}):
            value = copy.deepcopy(self.value)
            value['candidate_assessments'][0]['claims'][0]['source_refs'] = [ref]
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.validate(value)

    def test_reference_violations_collect_id_level_detail_without_source_text(self):
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim['source_refs'] = [
            {'source_id': 'p2', 'reference_id': 'passage:methods'},
            {'source_id': 'p1', 'reference_id': 'card:FAKE'},
            {'source_id': 'FAKE', 'reference_id': 'card:section:P1'}]
        with self.assertRaises(ValueError) as caught:
            self.validate()
        exc = caught.exception
        self.assertEqual(str(exc), 'Reference must identify manager-supplied in-scope original text')
        detail = exc.detail
        self.assertEqual(detail['reason'], 'out_of_scope_source_id')
        self.assertEqual(detail['candidate_id'], 'C1')
        self.assertEqual(detail['offending'], [
            {'source_id': 'p2', 'reference_id': 'passage:methods', 'reason': 'out_of_scope_source_id'},
            {'source_id': 'p1', 'reference_id': 'card:FAKE', 'reason': 'unknown_reference_id'},
            {'source_id': 'FAKE', 'reference_id': 'card:section:P1', 'reason': 'out_of_scope_source_id'}])
        # The allowed sub-table covers only this candidate's scope sources.
        self.assertEqual(detail['allowed'], {'p1': ['card:section:P1']})
        self.assertNotIn('Exact fixture source passage.', json.dumps(detail, ensure_ascii=False))
        self.assertNotIn('Exact fixture targeted text.', json.dumps(detail, ensure_ascii=False))

    def test_duplicate_reference_carries_detail_and_unchanged_message(self):
        ref = {'source_id': 'p1', 'reference_id': 'card:section:P1'}
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim['source_refs'] = [dict(ref), dict(ref)]
        with self.assertRaises(ValueError) as caught:
            self.validate()
        self.assertEqual(str(caught.exception), 'Duplicate source reference')
        detail = caught.exception.detail
        self.assertEqual(detail['reason'], 'duplicate_reference')
        self.assertEqual(detail['candidate_id'], 'C1')
        self.assertEqual(detail['offending'],
                         [{'source_id': 'p1', 'reference_id': 'card:section:P1',
                           'reason': 'duplicate_reference'}])

    def test_valid_references_still_validate_without_detail(self):
        claim = self.value['candidate_assessments'][0]['claims'][0]
        claim.update(novelty_status='distinct_within_evidence', closest_source_id='p1',
                     source_refs=[{'source_id': 'p1', 'reference_id': 'card:section:P1'}])
        self.validate()

    def test_author_supplied_quote_is_not_a_manager_reference(self):
        self.document['candidates'][0]['source_spans'] = {'forged': {'text': 'Fabricated author passage'}}
        self.value['candidate_assessments'][0]['claims'][0]['source_refs'] = [
            {'source_id': 'p1', 'reference_id': 'card:forged'}]
        with self.assertRaises(ValueError):
            self.validate()

    def test_determinate_comparator_must_have_its_own_reference(self):
        self.scopes['C1'].add('p2')
        self.value['candidate_assessments'][0]['claims'][0].update(
            novelty_status='covered', closest_source_id='p1',
            source_refs=[{'source_id': 'p2', 'reference_id': 'passage:methods'}])
        with self.assertRaises(ValueError):
            self.validate()

    def test_duplicate_refs_and_missing_evidence_limits_fail(self):
        value = copy.deepcopy(self.value)
        ref = {'source_id': 'p1', 'reference_id': 'card:section:P1'}
        value['candidate_assessments'][0]['claims'][0]['source_refs'] = [ref, ref]
        with self.assertRaises(ValueError):
            self.validate(value)
        self.value['candidate_assessments'][0]['claims'][0]['evidence_limit'] = ''
        with self.assertRaises(ValueError):
            self.validate()

    def test_issue_and_dimension_advice_coverage_cannot_be_omitted_or_invented(self):
        for mutate in (lambda v: v['advice_audits'].pop(),
                       lambda v: v['advice_audits'].append(copy.deepcopy(v['advice_audits'][0])),
                       lambda v: v['advice_audits'][0].update(advice_id='issue:999'),
                       lambda v: v['advice_audits'][0].update(candidate_id='C2')):
            value = copy.deepcopy(self.value); mutate(value)
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_real_problem_and_harmful_remedy_are_separate_and_require_adjudication(self):
        self.value['advice_audits'][0].update(problem_verdict='supported', repair_verdict='harmful')
        result = self.validate()
        self.assertTrue(result['requires_adjudication'])
        self.assertEqual(result['candidate_status'], {'C1': 'ADJUDICATE', 'C2': 'EVIDENCE_NEEDED'})
        self.assertFalse(result['automatic_application'])
        self.assertEqual(result['advice_audits'][0]['problem_verdict'], 'supported')
        self.value['advice_audits'][0].update(problem_verdict='disputed', repair_verdict='unknown')
        self.assertTrue(self.validate()['requires_adjudication'])

    def test_advice_verdicts_need_reasoning_and_in_scope_evidence(self):
        for mutate in (lambda a: a.update(problem_verdict='accepted'),
                       lambda a: a.update(repair_verdict='guaranteed'),
                       lambda a: a.update(problem_reason=''),
                       lambda a: a.update(repair_reason=''),
                       lambda a: a.update(source_ids=['p2'])):
            value = copy.deepcopy(self.value); mutate(value['advice_audits'][0])
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_novelty_moves_are_optional_and_never_auto_accepted(self):
        move = {'move_id': 'move-1', 'target_claim_id': 'claim-1',
                'mechanism_change': 'Fixture assumption change',
                'predicted_scientific_delta': 'Fixture boundary result',
                'discriminating_test': 'Fixture minimal contrast', 'falsifier': 'Fixture refutation',
                'cost_and_risks': 'Fixture resource and confounding risks',
                'search_queries': ['fixture mechanism boundary'], 'status': 'proposed_unverified'}
        self.value['candidate_assessments'][0]['novelty_moves'] = [move]
        self.assertEqual(self.validate()['candidate_assessments'][0]['novelty_moves'][0]['status'], 'proposed_unverified')
        for mutate in (lambda m: m.update(status='verified'),
                       lambda m: m.update(target_claim_id='FAKE'),
                       lambda m: m.update(falsifier=''),
                       lambda m: m.update(search_queries=[]),
                       lambda m: m.update(search_queries=['Same query', ' same query '])):
            value = copy.deepcopy(self.value); mutate(value['candidate_assessments'][0]['novelty_moves'][0])
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_no_extra_numeric_confidence_or_acceptance_fields(self):
        for key in ('score', 'confidence', 'accepted'):
            value = copy.deepcopy(self.value); value[key] = 0.99
            with self.assertRaises(ValueError):
                self.validate(value)


if __name__ == '__main__':
    unittest.main()
