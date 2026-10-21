"""Offline accountability checks for actual synthesis regressions and withdrawals."""
import copy
import unittest

from sage.autonomous.revision_contract import (VERSION, revision_descriptor,
                                               revision_errors)
from sage.autonomous.review import (CANDIDATE_SCIENTIFIC_FIELDS, CONTEXT_SCIENTIFIC_FIELDS,
                                    scientific_input)


PARENT = 'a' * 64
SOURCES = {'p1', 'p2'}


def primary():
    return {'candidates': [
        {'id': 'C1', 'title': 'Synthetic one', 'problem': 'Synthetic problem',
         'hypothesis': 'Synthetic prediction', 'mechanism': 'Synthetic mechanism',
         'source_ids': ['p1', 'p2'],
         'protocol': {'primary_metric': 'score', 'estimand': 'Synthetic signed effect'}},
        {'id': 'C2', 'title': 'Synthetic two', 'problem': 'Synthetic other problem',
         'hypothesis': 'Synthetic other prediction', 'source_ids': ['p2']}],
        'selected_ids': ['C1', 'C2']}


def record(changes=None, withdrawals=None):
    return {'schema_version': VERSION, 'parent_sha256': PARENT,
            'change_type': 'scientific_revision' if changes else 'no_scientific_change',
            'basis': ['protocol_correction'] if changes else [],
            'problem_assessment': 'Synthetic issue; not applicable for metadata-only changes',
            'remedy_assessment': 'Synthetic remedy with unverified scientific validity',
            'reason': 'Synthetic identification grounds rather than a model grade',
            'remaining_uncertainty': 'Synthetic proposal has not been experimentally tested',
            'candidate_changes': changes or [], 'withdrawn_selected': withdrawals or []}


def change(ident, fields):
    return {'candidate_id': ident, 'changed_fields': fields,
            'scientific_reason': 'Synthetic estimand/control correction', 'source_ids': []}


class RevisionContractTests(unittest.TestCase):
    def check(self, before, after):
        return revision_errors(before, PARENT, after, known_sources=SOURCES)

    def test_every_reviewed_scientific_candidate_field_requires_change_accounting(self):
        # Regression: proof/derivation/metrics entered numeric review but the
        # shorter team field list classified their edits as metadata only.
        for field in CANDIDATE_SCIENTIFIC_FIELDS:
            with self.subTest(field=field):
                before = primary()
                before['candidates'][0][field] = ['p1'] if field == 'source_ids' else 'Fixture old science'
                after = copy.deepcopy(before)
                after['candidates'][0][field] = ['p2'] if field == 'source_ids' else 'Fixture changed science'
                after['revision_record'] = record()
                projected, _ = scientific_input(after, 'Fixture topic')
                self.assertIn(field, projected['candidates'][0])
                self.assertTrue(any('scientific_revision' in error for error in self.check(before, after)))
                after['revision_record'] = record([change('C1', [field])])
                self.assertEqual(self.check(before, after), [])

    def test_every_projected_context_field_requires_explicit_reason(self):
        for field in CONTEXT_SCIENTIFIC_FIELDS:
            with self.subTest(field=field):
                before = primary()
                before[field] = ([{'candidate_id': 'C1', 'objection': 'Fixture original objection'}]
                                 if field == 'open_objections' else 'Fixture original context')
                after = copy.deepcopy(before)
                after[field] = ([{'candidate_id': 'C1', 'objection': 'Fixture opposite objection'}]
                                if field == 'open_objections' else 'Fixture opposite context')
                after['revision_record'] = record()
                projected, _ = scientific_input(after, 'Fixture topic')
                self.assertIn(field, projected['scientific_context'])
                errors = self.check(before, after)
                self.assertTrue(any('context_changes must exactly' in error for error in errors))
                self.assertTrue(any('scientific_revision' in error for error in errors))
                after['revision_record'].update(change_type='scientific_revision', basis=['protocol_correction'],
                    context_changes=[{'field': field, 'scientific_reason': 'Fixture protocol correction', 'source_ids': []}])
                self.assertEqual(self.check(before, after), [])

    def test_context_addition_deletion_and_dormant_candidate_objection_are_accounted(self):
        before = primary()
        before['selected_ids'] = ['C1']
        for field, value in (('shared_protocol', {'metric': 'Fixture shared metric'}),
                             ('open_objections', [{'candidate_id': 'C2', 'objection': 'Fixture dormant issue'}])):
            with self.subTest(field=field):
                after = copy.deepcopy(before)
                after[field] = value
                after['revision_record'] = record()
                self.assertTrue(any('context_changes' in error for error in self.check(before, after)))
                after['revision_record'].update(change_type='scientific_revision', basis=['supported_issue'],
                    context_changes=[{'field': field, 'scientific_reason': 'Fixture scientific addition', 'source_ids': ['p1']}])
                self.assertEqual(self.check(before, after), [])
                removed = copy.deepcopy(after)
                del removed[field]
                self.assertEqual(self.check(after, removed), [])
                removed['revision_record']['context_changes'] = []
                self.assertTrue(any('context_changes' in error for error in self.check(after, removed)))

    def test_context_records_reject_wrong_coverage_duplicates_and_invented_sources(self):
        before = primary(); after = copy.deepcopy(before)
        after['shared_protocol'] = {'metric': 'Fixture new metric'}
        after['revision_record'] = record()
        after['revision_record'].update(change_type='scientific_revision', basis=['protocol_correction'])
        valid = {'field': 'shared_protocol', 'scientific_reason': 'Fixture correction', 'source_ids': []}
        for rows in (None, [], [valid, valid], [dict(valid, source_ids=['invented'])],
                     [dict(valid, scientific_reason='')], [dict(valid, field='final_export')]):
            with self.subTest(rows=rows):
                after['revision_record']['context_changes'] = rows
                self.assertTrue(self.check(before, after))

    def test_context_projection_does_not_reintroduce_author_evaluation(self):
        before = primary()
        before['open_objections'] = [{'candidate_id': 'C1', 'objection': 'Fixture issue', 'rating': 2}]
        after = copy.deepcopy(before)
        after['open_objections'][0]['rating'] = 10
        after['final_export'] = {'score': 1.0, 'review': 'AUTHOR_GRADE_LEAK'}
        after['candidates'][0]['author_evaluation'] = 'AUTHOR_GRADE_LEAK'
        after['revision_record'] = record()
        self.assertEqual(self.check(before, after), [])
        projected, _ = scientific_input(after, 'Fixture topic')
        self.assertNotIn('rating', projected['scientific_context']['open_objections'][0])
        self.assertNotIn('final_export', projected['scientific_context'])
        self.assertNotIn('author_evaluation', projected['candidates'][0])

    def test_protocol_change_is_exactly_recorded_and_never_mutates_documents(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['protocol']['estimand'] = 'Synthetic corrected signed effect'
        after['revision_record'] = record([change('C1', ['protocol'])])
        saved = copy.deepcopy((before, after))
        self.assertEqual(self.check(before, after), [])
        self.assertEqual((before, after), saved)

    def test_real_single_grade_rollback_cannot_be_its_only_basis(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['hypothesis'] = 'Synthetic earlier hypothesis restored'
        after['revision_record'] = record([change('C1', ['hypothesis'])])
        for basis in ('higher_score', 'lower_score', 'rank', 'schema_convenience', 'acceptance'):
            after['revision_record']['basis'] = [basis]
            self.assertTrue(any('scientific grounds' in x for x in self.check(before, after)))
        after['revision_record']['basis'] = []
        self.assertTrue(any('at least one' in x for x in self.check(before, after)))

    def test_revision_needs_the_exact_immediate_parent(self):
        before = primary(); after = copy.deepcopy(before)
        after['revision_record'] = record()
        after['revision_record']['parent_sha256'] = 'b' * 64
        self.assertTrue(any('immediate' in x for x in self.check(before, after)))
        self.assertTrue(any('manager-frozen previous' in x for x in
                            revision_errors(before, 'not-a-hash', after, known_sources=SOURCES)))

    def test_all_assessments_and_remaining_uncertainty_are_explicit(self):
        for key in ('problem_assessment', 'remedy_assessment', 'reason', 'remaining_uncertainty'):
            before = primary(); after = copy.deepcopy(before)
            after['revision_record'] = record()
            after['revision_record'][key] = ''
            self.assertTrue(any(key in x for x in self.check(before, after)))

    def test_metadata_change_uses_no_change_without_manufacturing_scientific_issue(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0].update(title='Synthetic corrected title', origin={'slot': 0})
        after['selection_rationale'] = 'Synthetic editorial clarification'
        after['revision_record'] = record()
        self.assertEqual(self.check(before, after), [])
        after['revision_record']['basis'] = ['supported_issue']
        self.assertTrue(any('metadata-only' in x for x in self.check(before, after)))

    def test_scientific_change_cannot_hide_as_metadata_or_empty_record(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['mechanism'] = 'Synthetic revised mechanism'
        self.assertTrue(any('requires revision_record' in x for x in self.check(before, after)))
        after['revision_record'] = record()
        errors = self.check(before, after)
        self.assertTrue(any('scientific_revision' in x for x in errors))
        self.assertTrue(any('exactly cover' in x for x in errors))

    def test_exact_field_coverage_disallows_missing_extra_and_duplicate_fields(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0].update(hypothesis='Synthetic new prediction', mechanism='Synthetic new mechanism')
        after['revision_record'] = record([change('C1', ['hypothesis', 'mechanism'])])
        self.assertEqual(self.check(before, after), [])
        for fields in (['hypothesis'], ['hypothesis', 'mechanism', 'protocol'],
                       ['hypothesis', 'mechanism', 'mechanism'], ['hypothesis', 1]):
            after['revision_record']['candidate_changes'][0]['changed_fields'] = fields
            self.assertTrue(any('changed_fields' in x for x in self.check(before, after)))

    def test_exact_candidate_coverage_disallows_extra_or_duplicate_changes(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['mechanism'] = 'Synthetic new mechanism'
        after['revision_record'] = record([change('C1', ['mechanism'])])
        after['revision_record']['candidate_changes'].append(change('C2', []))
        self.assertTrue(any('exactly cover' in x for x in self.check(before, after)))
        after['revision_record']['candidate_changes'][-1] = change('C1', ['mechanism'])
        self.assertTrue(any('repeat' in x for x in self.check(before, after)))

    def withdrawn(self):
        before = primary(); after = copy.deepcopy(before)
        after['selected_ids'] = ['C2']
        after['candidates'][0].update(disposition='rejected', rejection_reason='Synthetic scientific limitation')
        withdrawal = {'candidate_id': 'C1', 'scientific_reason': 'Synthetic contradicted mechanism',
                      'source_ids': ['p2']}
        after['revision_record'] = record([change('C1', ['selected'])], [withdrawal])
        return before, after

    def test_withdrawal_preserves_ledger_and_is_source_bound(self):
        before, after = self.withdrawn()
        self.assertEqual(self.check(before, after), [])
        after['revision_record']['withdrawn_selected'][0]['source_ids'] = ['invented']
        self.assertTrue(any('actually retrieved' in x for x in self.check(before, after)))

    def test_withdrawal_without_source_needs_concrete_protocol_or_resource_constraint(self):
        before, after = self.withdrawn()
        entry = after['revision_record']['withdrawn_selected'][0]
        entry['source_ids'] = []
        self.assertTrue(any('requires actual sources' in x for x in self.check(before, after)))
        for kind in ('protocol', 'feasibility'):
            entry['constraint'] = {'kind': kind, 'description': 'Synthetic explicit identification or resource limitation'}
            self.assertEqual(self.check(before, after), [])
        for constraint in ({'kind': 'score', 'description': 'Score decreased'},
                           {'kind': 'schema', 'description': 'Too few fields'},
                           {'kind': 'protocol', 'description': ''}):
            entry['constraint'] = constraint
            self.assertTrue(any('constraint' in x or 'limitation' in x for x in self.check(before, after)))

    def test_each_withdrawal_requires_specific_reason_and_exact_coverage(self):
        before, after = self.withdrawn()
        after['revision_record']['withdrawn_selected'][0]['scientific_reason'] = ''
        self.assertTrue(any('scientific_reason' in x for x in self.check(before, after)))
        after['revision_record']['withdrawn_selected'] = []
        self.assertTrue(any('every previously selected' in x for x in self.check(before, after)))

    def test_deleting_candidate_cannot_be_fixed_by_declaring_its_removal(self):
        before, after = self.withdrawn()
        del after['candidates'][0]
        after['revision_record']['candidate_changes'][0]['changed_fields'] = [
            'problem', 'hypothesis', 'mechanism', 'source_ids', 'protocol', 'selected']
        self.assertTrue(any('Preserve every old candidate' in x for x in self.check(before, after)))

    def test_added_selected_candidate_lists_every_introduced_scientific_field(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'].append({'id': 'C3', 'title': 'Synthetic new candidate',
                                    'problem': 'Synthetic new problem', 'source_ids': ['p1']})
        after['selected_ids'].append('C3')
        after['revision_record'] = record([change('C3', ['problem', 'source_ids', 'selected'])])
        self.assertEqual(self.check(before, after), [])

    def test_source_order_is_not_scientific_change_but_new_evidence_is(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['source_ids'].reverse()
        after['revision_record'] = record()
        self.assertEqual(self.check(before, after), [])
        after['candidates'][0]['source_ids'] = ['p1']
        self.assertTrue(any('scientific_revision' in x for x in self.check(before, after)))

    def test_nonfinite_changes_wrong_shapes_and_duplicate_ids_fail_safely(self):
        before = primary()
        for after in (None, [], {'candidates': [None]}, {'candidates': [{'id': 'C1'}, {'id': 'C1'}]}):
            self.assertTrue(self.check(before, after))
        after = copy.deepcopy(before)
        after['candidates'][0]['protocol']['threshold'] = float('nan')
        after['revision_record'] = record()
        self.assertTrue(any('finite JSON' in x for x in self.check(before, after)))

    def test_measurement_named_score_is_allowed_and_record_does_not_certify_improvement(self):
        before = primary(); after = copy.deepcopy(before)
        after['candidates'][0]['protocol']['score'] = {'measurement_unit': 'Synthetic Brier loss'}
        after['revision_record'] = record([change('C1', ['protocol'])])
        self.assertEqual(self.check(before, after), [])
        self.assertIn('semantic support remain unverified', revision_descriptor()['validation_scope'])
        self.assertIn('protocol', revision_descriptor()['candidate_scientific_fields'])


if __name__ == '__main__':
    unittest.main()
