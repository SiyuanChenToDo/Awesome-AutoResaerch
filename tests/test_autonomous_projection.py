"""Network-free regressions for document/candidate blind-review projection.

The final_export container shape and historical scalar values below reproduce
the field-boundary failure observed in the frozen 2026-10-18 validation. All
research text, IDs, source content and mathematical examples are synthetic;
no unpublished candidate, original response or run artifact is committed here.
"""
import copy
import json
import unittest

from sage.autonomous.novelty import feedback_prompt
from sage.autonomous.review import (PROJECTION_VERSION, input_digest, review_prompt,
                                    scientific_input)


def historical_shape_fixture():
    return {
        'candidates': [{
            'id': 'SYNTHETIC-1', 'title': 'Synthetic proposal',
            'problem': 'Synthetic calibration bottleneck',
            'hypothesis': 'Synthetic conditional prediction',
            'mechanism': 'Synthetic mechanism', 'assumptions': ['Synthetic assumption'],
            'source_ids': ['synthetic-source'], 'closest_prior_art': [],
            'novelty_queries': ['synthetic query'],
            'falsification': {'test': 'Synthetic test', 'controls': 'Synthetic control',
                              'metric': {'name': 'Brier score', 'score': 0.44},
                              'reject_if': 'Synthetic falsifier'},
            'feasibility': {'gpu_hours': 160, 'fixed_budget': True},
            'statistics': {'estimand': 'E[Y(1)-Y(0)]', 'alpha': 0.05,
                           'model': 'logit(p)=a+b*x', 'power': 0.8},
            'power_derivation': 'Synthetic cluster-based standard error',
            'evidence_gaps': ['Synthetic incomplete source'],
            'origin': {'slot': 0, 'proposal_sha256': 'a' * 64},
            'status': 'provisional', 'disposition': 'selected',
        }],
        'selected_ids': ['SYNTHETIC-1'],
        'selection_rationale': 'AUTHOR_SELECTION_LEAK',
        'team_metadata': {'scientific_validation': 'AUTHOR_VALIDATION_LEAK'},
        'scientific_validation': 'AUTHOR_VALIDATION_LEAK',
        'independent_acceptance': True,
        'acceptance_status': 'AUTHOR_ACCEPTANCE_LEAK',
        'final_export': {'label': 'AUTHOR_FINAL_EXPORT_LEAK',
                         'note': 'AUTHOR_ROLLBACK_LEAK 0.805 / 0.75 / 0.76'},
    }


class ScientificAllowlistTests(unittest.TestCase):
    def test_shared_definitions_and_calibration_survive_without_nested_assessment(self):
        primary = historical_shape_fixture()
        primary['shared_scientific_context'] = {
            'novelty_operationalization': {'threshold': 0.92, 'unit': 'cosine'},
            'computational_envelope': {'gpu_hours': 80},
            'evidence_policy': 'Only source-bound claims',
            'verification_boundary': 'No experiments yet',
            'author_score': 0.999999}
        primary['candidates'][0]['calibration_plan'] = {'pilot': 'Estimate measurement reliability'}
        document, ledger = scientific_input(primary, 'Synthetic original problem')
        shared = document['scientific_context']['shared_scientific_context']
        self.assertEqual(shared['novelty_operationalization']['threshold'], 0.92)
        self.assertEqual(document['candidates'][0]['calibration_plan'], primary['candidates'][0]['calibration_plan'])
        self.assertEqual(ledger['omitted_shared_context_fields'], ['author_score'])
        for prompt in self.prompts(document):
            self.assertNotIn('0.999999', prompt)
            self.assertIn('Estimate measurement reliability', prompt)

    def prompts(self, document):
        # Both stages receive exactly this common scientific projection.
        return (review_prompt(document, {}),
                feedback_prompt(document, {}, {'candidate_reviews': [], 'issues': []}))

    def test_archived_failure_shape_is_blind_in_both_stages(self):
        primary = historical_shape_fixture()
        before = copy.deepcopy(primary)
        document, ledger = scientific_input(primary, 'Synthetic original problem')
        for prompt in self.prompts(document):
            with self.subTest(stage=prompt.splitlines()[0]):
                for marker in ('AUTHOR_', '0.805', '0.75', '0.76',
                               'final_export', 'proposal_sha256'):
                    self.assertNotIn(marker, prompt)
        self.assertEqual(document['scientific_context'], {})
        self.assertEqual(ledger['projection_version'], PROJECTION_VERSION)
        self.assertIn('final_export', ledger['omitted_context_fields'])
        self.assertIn('origin', ledger['omitted_candidate_fields']['SYNTHETIC-1'])
        self.assertEqual(primary, before)

    def test_unknown_new_names_cannot_bypass_boundary_or_change_science_digest(self):
        primary = historical_shape_fixture()
        baseline, _ = scientific_input(primary, 'Synthetic original problem')
        # An allowlist, rather than another final_export blacklist entry, must
        # exclude previously unseen container names at both trust boundaries.
        for name in ('diagnostics_v987', 'release_notes', 'ready_for_venue',
                     'unfamiliar_scientific_extension'):
            with self.subTest(name=name):
                primary[name] = {'nested': ['UNSEEN_ASSESSMENT_LEAK', 0.987654321]}
                primary['candidates'][0][name] = {'score': 0.987654321}
                projected, _ = scientific_input(primary, 'Synthetic original problem')
                self.assertEqual(input_digest(projected), input_digest(baseline))
                for prompt in self.prompts(projected):
                    self.assertNotIn('UNSEEN_ASSESSMENT_LEAK', prompt)
                    self.assertNotIn('0.987654321', prompt)

    def test_metrics_statistics_estimands_and_budget_are_not_redacted(self):
        primary = historical_shape_fixture()
        candidate = primary['candidates'][0]
        candidate['metrics'] = {'score': {'observed': 0.805, 'unit': 'measurement'}}
        candidate['estimand'] = {'target': 'E[Y(1)-Y(0)]', 'population': 'Synthetic population'}
        candidate['budget'] = {'gpu_hours': 160, 'per_seed': {'tokens': 2000}}
        candidate['protocol_contract'] = {'primary_metric': 'score',
                                           'minimum_effect': 0.01, 'sign': 'positive'}
        primary['analysis_plan'] = {'multiple_testing': 'Holm', 'alpha': 0.05}
        primary['compute_budget'] = {'gpu_hours': 160, 'cost_model': 'Synthetic'}
        document, _ = scientific_input(primary, 'Synthetic original problem')
        chosen = document['candidates'][0]
        for name in ('falsification', 'feasibility', 'statistics', 'metrics', 'estimand',
                     'power_derivation', 'budget', 'protocol_contract', 'evidence_gaps'):
            with self.subTest(name=name):
                self.assertEqual(chosen[name], candidate[name])
        for name in ('analysis_plan', 'compute_budget'):
            self.assertEqual(document['scientific_context'][name], primary[name])
        self.assertIn('0.805', json.dumps(document))  # Legitimate measured score survives.

    def test_objections_are_selected_scientific_questions_not_author_decisions(self):
        primary = historical_shape_fixture()
        primary['open_objections'] = [
            {'candidate_id': 'SYNTHETIC-1', 'objection': 'Synthetic identification concern',
             'source_ids': ['synthetic-source'], 'diagnosis': 'OBJECTION_DIAGNOSTIC_LEAK',
             'accepted': True, 'score': 0.991},
            {'candidate_id': 'NONSELECTED', 'objection': 'UNSELECTED_OBJECTION_LEAK'}]
        document, _ = scientific_input(primary, 'Synthetic original problem')
        self.assertEqual(document['scientific_context']['open_objections'], [{
            'candidate_id': 'SYNTHETIC-1', 'objection': 'Synthetic identification concern',
            'source_ids': ['synthetic-source']}])
        for prompt in self.prompts(document):
            self.assertNotIn('DIAGNOSTIC_LEAK', prompt)
            self.assertNotIn('UNSELECTED_OBJECTION_LEAK', prompt)

    def test_numeric_prompt_states_actual_candidate_scopes_explicitly(self):
        primary = historical_shape_fixture()
        second = copy.deepcopy(primary['candidates'][0])
        second.update(id='SYNTHETIC-2', source_ids=['other-source'])
        primary['candidates'].append(second)
        primary['selected_ids'].append('SYNTHETIC-2')
        document, _ = scientific_input(primary, 'Synthetic original problem')
        prompt = review_prompt(document, {'papers': {'synthetic-source': {}, 'other-source': {}}})
        encoded = prompt.split('\nCANDIDATE SOURCE SCOPE (IDs may only be cited for these candidates):\n')[1]
        scopes = json.loads(encoded.split('\nRETRIEVED EVIDENCE')[0])
        self.assertEqual(scopes, {'SYNTHETIC-1': ['synthetic-source'],
                                  'SYNTHETIC-2': ['other-source']})


if __name__ == '__main__':
    unittest.main()
