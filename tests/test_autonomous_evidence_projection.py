"""Compact evidence projection regressions for both advisory review stages.

Stage one carries bounded summaries; stage two additionally supplies exact
originals in a reference catalog. Host-side validation binds every reference
to its paper. All content is synthetic fixture data, never scientific evidence.
"""
import json
import unittest

from sage.autonomous.novelty import (FEEDBACK_VERSION, advice_targets, feedback_prompt,
                                     validate_feedback)
from sage.autonomous.review import (AXES, RUBRIC_VERSION, canonical_json, evidence_view,
                                    review_prompt, source_scope, validate_review)

# Distinctive originals for checking each stage's evidence boundary.
SPAN_ORIGINAL = 'IMMUTABLE_SPAN_ORIGINAL_SENTENCE_QUOTED_FOR_PROJECTION_TEST.'
P1_SPAN_ORIGINAL = 'P1_ONLY_ORIGINAL_SENTENCE_NEVER_TRANSMITTED_TO_STAGE_TWO.'
P2_SPAN_ORIGINAL = 'P2_CLOSEST_ORIGINAL_SENTENCE_ALLOWED_IN_STAGE_TWO.'
P3_SPAN_ORIGINAL = 'P3_ONLY_ORIGINAL_SENTENCE_FOR_NULL_PRIOR_ART_CANDIDATE.'


def bulky_evidence(paper_count=6, spans_per_paper=40):
    """A deterministic evidence store whose raw JSON far exceeds the view bound."""
    evidence = {'papers': {}, 'cards': {}, 'targeted_original_passages': {}, 'searches': []}
    categories = ('problem', 'motivation', 'method', 'assumptions', 'metrics', 'results')
    for index in range(paper_count):
        pid = 'p' + str(index + 1)
        evidence['papers'][pid] = {'paper_id': pid, 'title': 'Fixture paper ' + pid,
                                   'abstract': 'Fixture abstract sentence. ' * 400,
                                   'evidence_scope': 'supplied_fixture_text'}
        spans, claims = {}, []
        for number in range(spans_per_paper):
            key = 's1-c1:P' + str(number + 1)
            spans[key] = {'span_id': 'P' + str(number + 1), 'chunk_id': 's1-c1',
                          'start': 0, 'end': len(SPAN_ORIGINAL),
                          'text': SPAN_ORIGINAL * 40 + key}
            claims.append({'category': categories[number % len(categories)],
                           'claim': 'Fixture claim ' + pid + ' number ' + str(number) + '.',
                           'source_span_ids': [key],
                           'support_check': 'original_span_lookup_not_entailment'})
        evidence['cards'][pid] = {'schema_version': 'sage.evidence_capsule.v2', 'paper_id': pid,
            'source_scope': 'supplied_fixture_text', 'claims': claims, 'source_spans': spans,
            'coverage': {'available_chunks': 1, 'read_chunks': 1, 'partial_document': False},
            'inferences_unverified': ['Fixture explicitly uncertain interpretation.']}
        evidence['targeted_original_passages'][pid] = [{'chunk_id': 's1-c1', 'heading': 'Fixture',
                                                        'text': SPAN_ORIGINAL * 60}]
    for number in range(8):
        evidence['searches'].append({'query': 'fixture prior-art query ' + str(number),
                                     'purpose': 'fixture novelty sweep', 'engine': 'fixture',
                                     'result_ids': ['p1', 'p2'],
                                     'results': [{'paper_id': 'p1'}, {'paper_id': 'p2'}]})
    return evidence


def review_document(source_ids):
    return {'selected_ids': ['C1'], 'candidates': [
        {'id': 'C1', 'title': 'Fixture candidate', 'hypothesis': 'Fixture hypothesis',
         'source_ids': source_ids, 'closest_prior_art': []}]}


def fixture_review(document):
    return {'rubric_version': RUBRIC_VERSION, 'calibration': 'none',
            'calibration_gap': 'Fixture: no human-curated anchors available',
            'candidate_reviews': [{'candidate_id': ident, 'dimensions': {
                axis: {'rating': 8, 'rationale': 'Fixture evidence-based rationale',
                       'source_ids': [], 'weakness': 'Fixture weakness',
                       'concrete_fix': 'Fixture concrete method fix', 'priority': 'IMPORTANT'}
                for axis in AXES}, 'simplification_opportunities': [],
                'modernization_opportunities': [], 'drift_warning': 'NONE', 'verdict': 'REVISE'}
                for ident in document['selected_ids']],
            'issues': [], 'surviving_ids': list(document['selected_ids']),
            'summary': 'Fixture unvalidated proposal review'}


class StageOneEvidenceProjectionTests(unittest.TestCase):
    def test_metadata_scope_does_not_hide_card_source_or_partial_reading(self):
        evidence = bulky_evidence(paper_count=1, spans_per_paper=1)
        evidence['papers']['p1']['evidence_scope'] = 'abstract_only'
        evidence['cards']['p1']['source_scope'] = 'arxiv_html'
        coverage = {'available_chunks': 12, 'read_chunks': 3, 'partial_document': True}
        evidence['cards']['p1']['coverage'] = coverage
        paper = evidence_view(evidence)['papers']['p1']
        self.assertEqual(paper['metadata_evidence_scope'], 'abstract_only')
        self.assertEqual(paper['source_scope'], 'arxiv_html')
        self.assertEqual(paper['reading_scope'], coverage)
        self.assertNotIn('evidence_scope', paper)
        document = review_document(['p1'])
        stage_one = review_prompt(document, evidence)
        stage_two = feedback_prompt(document, evidence, fixture_review(document))
        for prompt in (stage_one, stage_two):
            self.assertIn('"source_scope":"arxiv_html"', prompt)
            self.assertIn('"metadata_evidence_scope":"abstract_only"', prompt)
            self.assertNotIn('never transmitted', prompt)
        self.assertNotIn(SPAN_ORIGINAL, stage_one)
        self.assertIn(SPAN_ORIGINAL, stage_two)

    def test_evidence_section_is_compact_never_serializes_source_originals(self):
        evidence = bulky_evidence()
        prompt = review_prompt(review_document(sorted(evidence['papers'])), evidence)
        section = prompt.split('\nRETRIEVED EVIDENCE', 1)[1]
        view_bytes = len(section.encode('utf-8'))
        full_bytes = len(canonical_json(evidence).encode('utf-8'))
        self.assertGreater(full_bytes, 400 * 1024)
        self.assertLessEqual(view_bytes, 400 * 1024)
        self.assertLess(view_bytes * 4, full_bytes)
        self.assertNotIn(SPAN_ORIGINAL, prompt)
        self.assertIn('Fixture claim p1 number 0', prompt)
        self.assertIn('source_span_ids', prompt)
        self.assertIn('fixture prior-art query 3', prompt)
        self.assertIn('"results":2', prompt)
        self.assertNotIn('"result_ids"', section)
        self.assertIn('…[truncated]', section)  # 800-character abstract bound is enforced
        self.assertIn('reading_scope', section)
        self.assertIn('targeted_passage_chunk_ids', section)

    def test_claim_groups_are_bounded_per_category(self):
        evidence = bulky_evidence(paper_count=1)
        groups = evidence_view(evidence)['papers']['p1']['claims']
        for entries in groups.values():
            self.assertLessEqual(len(entries), 6)
            self.assertTrue(all(len(entry['claim']) <= 300 + len(' …[truncated]')
                                for entry in entries))
        # 40 claims over 6 categories: the 7th claim of a category is dropped.
        self.assertNotIn('Fixture claim p1 number 39', canonical_json(evidence_view(evidence)))
        self.assertIn('Fixture claim p1 number 33', canonical_json(evidence_view(evidence)))

    def test_full_store_survives_projection_for_host_validation(self):
        evidence = bulky_evidence(paper_count=2)
        before = json.loads(canonical_json(evidence))
        review_prompt(review_document(sorted(evidence['papers'])), evidence)
        self.assertEqual(evidence, before)  # projection is read-only

    def test_review_validation_still_accepts_legal_payload_over_compact_view(self):
        document = review_document(['p1'])
        projected = evidence_view(bulky_evidence(paper_count=1))
        scopes = source_scope(document, {'p1': {}})
        result = validate_review(fixture_review(document), document, scopes)
        self.assertEqual(result['score'], 0.8)
        self.assertIn('claims', projected['papers']['p1'])


def stage_two_fixture():
    def card(pid, original):
        return {'source_scope': 'supplied_fixture_text', 'source_sha256': 'a' * 64,
                'claims': [{'category': 'method', 'claim': 'Fixture ' + pid + ' method claim.',
                            'source_span_ids': ['s1-c1:P1'],
                            'support_check': 'original_span_lookup_not_entailment'}],
                'source_spans': {'s1-c1:P1': {'text': original, 'chunk_id': 's1-c1',
                                              'start': 0, 'end': len(original)}}}
    evidence = {'papers': {'p1': {'title': 'Fixture prior one'},
                           'p2': {'title': 'Fixture prior two'},
                           'p3': {'title': 'Fixture prior three'}},
                'cards': {'p1': card('p1', P1_SPAN_ORIGINAL),
                          'p2': card('p2', P2_SPAN_ORIGINAL),
                          'p3': card('p3', P3_SPAN_ORIGINAL)},
                'targeted_original_passages': {}}
    # C1 names p2 as closest prior art; C2 names none, so p3 stays summarized.
    document = {'selected_ids': ['C1', 'C2'], 'candidates': [
        {'id': 'C1', 'hypothesis': 'Fixture mechanism', 'source_ids': ['p1', 'p2'],
         'closest_prior_art': [{'paper_id': 'p2', 'overlap': 'Fixture', 'difference': 'Fixture'}]},
        {'id': 'C2', 'hypothesis': 'Fixture finding', 'source_ids': ['p3'],
         'closest_prior_art': []}]}
    return document, evidence


class StageTwoCatalogProjectionTests(unittest.TestCase):
    def test_every_selectable_reference_carries_exact_text_once(self):
        document, evidence = stage_two_fixture()
        prompt = feedback_prompt(document, evidence, {'candidate_reviews': [], 'issues': []})
        self.assertIn(P2_SPAN_ORIGINAL, prompt)      # closest source: full text kept
        self.assertEqual(prompt.count(P1_SPAN_ORIGINAL), 1)   # scoped but not closest: summarized
        self.assertEqual(prompt.count(P3_SPAN_ORIGINAL), 1)   # null closest_prior_art: all summarized
        self.assertIn('Fixture p1 method claim.', prompt)   # summary still names the claim
        self.assertIn('Fixture p3 method claim.', prompt)
        self.assertIn('card:s1-c1:P1', prompt)       # reference IDs remain listed
        self.assertIn('ALLOWED REFERENCE IDS BY CANDIDATE', prompt)
        catalog = json.loads(prompt.split('candidate source scope still applies):\n', 1)[1]
                         .split('\nALLOWED REFERENCE IDS BY CANDIDATE')[0])
        from sage.autonomous.novelty import reference_handle
        self.assertEqual(catalog['p2'][reference_handle('p2', 'card:s1-c1:P1')]['text'], P2_SPAN_ORIGINAL)
        self.assertEqual(catalog['p1'][reference_handle('p1', 'card:s1-c1:P1')]['text'], P1_SPAN_ORIGINAL)
        self.assertNotEqual(next(iter(catalog['p1'])), next(iter(catalog['p2'])))

    def test_host_gate_resolves_legacy_references_to_visible_text(self):
        document, evidence = stage_two_fixture()
        scopes = source_scope(document, evidence['papers'])
        value = {'feedback_version': FEEDBACK_VERSION, 'candidate_assessments': [
            {'candidate_id': 'C1', 'claims': [{'claim_id': 'claim-1',
                'statement': 'Fixture proposed mechanism', 'kind': 'mechanism',
                'novelty_status': 'covered', 'closest_source_id': 'p2',
                'source_refs': [{'source_id': 'p2', 'reference_id': 'card:s1-c1:P1'},
                                {'source_id': 'p1', 'reference_id': 'card:s1-c1:P1'}],
                'overlap': 'Fixture overlap', 'scientific_delta': 'Fixture delta',
                'evidence_limit': 'Fixture scope is partial'}],
             'novelty_moves': []},
            {'candidate_id': 'C2', 'claims': [{'claim_id': 'claim-1',
                'statement': 'Fixture proposed finding', 'kind': 'finding',
                'novelty_status': 'unknown', 'closest_source_id': None, 'source_refs': [],
                'overlap': 'Not established', 'scientific_delta': 'Unverified',
                'evidence_limit': 'Fixture has no comparison text'}], 'novelty_moves': []}],
            'advice_audits': [{'advice_id': target['advice_id'],
                'candidate_id': target['candidate_id'], 'problem_verdict': 'unknown',
                'problem_reason': 'Fixture needs further reasoning', 'repair_verdict': 'unknown',
                'repair_reason': 'Fixture repair is not verified', 'source_ids': []}
                for target in advice_targets(fixture_review(document))],
            'summary': 'Fixture projection-independent validation'}
        review = fixture_review(document)
        prompt = feedback_prompt(document, evidence, review)
        self.assertEqual(prompt.count(P1_SPAN_ORIGINAL), 1)
        result = validate_feedback(value, document, scopes, evidence, review)
        quotations = result['candidate_assessments'][0]['claims'][0]['source_quotations']
        by_source = {item['source_id']: item['quotation'] for item in quotations}
        self.assertEqual(by_source['p1'], P1_SPAN_ORIGINAL)
        self.assertEqual(by_source['p2'], P2_SPAN_ORIGINAL)
        self.assertTrue(all(item['integrity_check'] == 'manager_source_lookup_not_entailment'
                            for item in quotations))


if __name__ == '__main__':
    unittest.main()
