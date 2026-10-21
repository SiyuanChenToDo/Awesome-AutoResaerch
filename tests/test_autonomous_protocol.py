"""Actual endpoint drift and invalid inference regressions, without API calls."""
import copy
import unittest

from sage.autonomous.protocol import (VERSION, interval_decision, protocol_descriptor,
                                      protocol_errors)


def fixture_protocol():
    value = copy.deepcopy(protocol_descriptor()['template'])
    value['hypothesis']['expected_direction'] = 'increase'
    value['endpoints'][0].update(role='primary', direction='higher')
    value['decision_rule'].update(type='superiority', combination='all',
                                 multiplicity='none', low_power_action='inconclusive')
    value['analysis']['power']['status'] = 'not_established'
    value['resources']['status'] = 'unresolved'
    return value


class ProtocolTests(unittest.TestCase):
    def test_unresolved_power_and_budget_are_explicit_not_fabricated(self):
        protocol = fixture_protocol()
        self.assertEqual(protocol_errors({'protocol': protocol}), [])
        self.assertIsNone(protocol['analysis']['sample_size'])
        self.assertEqual(protocol['analysis']['power']['status'], 'not_established')

    def test_coprimary_vs_single_primary_disagreement_is_blocked(self):
        protocol = fixture_protocol()
        other = copy.deepcopy(protocol['endpoints'][0])
        other.update(id='E2', metric='gradient necessity')
        protocol['endpoints'].append(other)
        self.assertIn('Primary endpoint IDs disagree with endpoint roles', protocol_errors({'protocol': protocol}))
        protocol['primary_endpoint_ids'].append('E2')
        protocol['decision_rule']['endpoint_ids'].append('E2')
        self.assertTrue(any('multiplicity' in x for x in protocol_errors({'protocol': protocol})))
        protocol['decision_rule']['multiplicity'] = 'Holm familywise alpha=0.05'
        self.assertEqual(protocol_errors({'protocol': protocol}), [])

    def test_encoding_and_analysis_unit_cannot_be_omitted(self):
        protocol = fixture_protocol()
        del protocol['variables'][0]['encoding']
        del protocol['analysis']['unit_of_analysis']
        errors = protocol_errors({'protocol': protocol})
        self.assertTrue(any('encoding' in x for x in errors))
        self.assertTrue(any('unit_of_analysis' in x for x in errors))

    def test_same_dataset_split_is_not_a_power_certificate(self):
        protocol = fixture_protocol()
        protocol['analysis']['power']['status'] = 'validated'
        self.assertTrue(any('independent_replicates' in x for x in protocol_errors({'protocol': protocol})))

    def test_equivalence_and_noninferiority_need_an_explicit_margin(self):
        for kind in ('equivalence', 'noninferiority'):
            protocol = fixture_protocol()
            protocol['decision_rule']['type'] = kind
            self.assertTrue(any('positive numeric margin' in x for x in protocol_errors({'protocol': protocol})))
            protocol['decision_rule']['margin'] = 0.02
            self.assertEqual(protocol_errors({'protocol': protocol}), [])

    def test_ci_crossing_zero_is_inconclusive_even_under_low_power(self):
        self.assertEqual(interval_decision(-0.1, 0.2), 'inconclusive')
        self.assertEqual(interval_decision(0.1, 0.2, power_sufficient=False), 'inconclusive')
        self.assertEqual(interval_decision(-0.2, -0.1), 'refuted')
        self.assertEqual(interval_decision(0.1, 0.2), 'supported')

    def test_equivalence_is_a_margin_test_not_failure_to_reject_zero(self):
        self.assertEqual(interval_decision(-0.2, 0.2, kind='equivalence', margin=0.02), 'inconclusive')
        self.assertEqual(interval_decision(-0.01, 0.01, kind='equivalence', margin=0.02), 'supported')
        self.assertEqual(interval_decision(-0.01, 0.01, kind='noninferiority', margin=0.02), 'supported')
        with self.assertRaises(ValueError):
            interval_decision(float('nan'), 0.1)

    def test_wrong_types_and_empty_endpoints_fail_with_actionable_errors(self):
        for value in ({}, {'protocol': []}, {'protocol': {'schema_version': VERSION}},
                      {'protocol': {'variables': [None], 'endpoints': [None]}}):
            self.assertTrue(protocol_errors(value))


if __name__ == '__main__':
    unittest.main()
