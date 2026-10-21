"""Offline tests of exchange integrity, not evaluations of research quality."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from sage.autonomous.team import ROLES, TeamBoard
from sage.autonomous.protocol import protocol_descriptor


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def proposal(slot, count=2):
    return {'candidates': [{'id': f'C{i}', 'title': f'Synthetic slot {slot} candidate {i}',
                            'hypothesis': f'Synthetic testable statement {i}',
                            'source_ids': ['fixture-1', 'fixture-2']}
                           for i in range(count)], 'selected_ids': ['C0']}


class TeamBoardTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.board = TeamBoard(self.root / 'private')
        self.documents = {slot: proposal(slot) for slot in range(4)}
        for slot in range(4):
            self.board.register(slot, f'agent-{slot}', self.root / f'worktree-{slot}', f'session-{slot}')

    def tearDown(self):
        self.folder.cleanup()

    def propose_all(self):
        for slot, document in self.documents.items():
            self.board.propose(slot, document, sha(document))

    def issues(self, slot, number=1, kind='methodological'):
        return [{'id': f'R{number}-slot{slot}', 'candidate_id': 'C0', 'kind': kind,
                 'problem': 'The synthetic control is underspecified',
                 'repair': 'Specify a matched synthetic control',
                 'target_fields': ['hypothesis'],
                 'source_ids': ['fixture-1'] if kind == 'factual' else []}]

    def review_all(self, number=1, empty=False):
        for slot in range(4):
            status = self.board.status(slot)
            self.board.review(slot, status['review_target'], status['target_primary_sha256'],
                              [] if empty else self.issues(slot, number), expected_round=number)

    def revise_all(self, number=1, decision='rejected', empty=False):
        for slot in range(4):
            document = self.documents[slot]
            decisions = []
            if not empty:
                for issue in self.board.snapshot(slot)['incoming_issues']:
                    decisions.append({'issue_id': issue['id'], 'decision': decision,
                                      'reason': 'Synthetic decision justification', 'source_ids': [],
                                      'change': 'Added an explicit control' if decision == 'accepted' else ''})
                if decision == 'accepted':
                    document = copy.deepcopy(document)
                    document['candidates'][0]['hypothesis'] += f'; control round {number}'
                    self.documents[slot] = document
            self.board.revise(slot, document, sha(document), decisions, expected_round=number)

    def finish_rounds(self, empty=False):
        self.propose_all()
        for number in (1, 2):
            self.review_all(number, empty=empty)
            self.revise_all(number, empty=empty)

    def synthesis(self):
        result = {'candidates': [], 'selected_ids': ['S0-C0']}
        for key, record in self.board.snapshot(0)['frozen_proposals'].items():
            for candidate in record['document']['candidates']:
                item = copy.deepcopy(candidate)
                item['id'] = f'S{key}-{candidate["id"]}'
                item['origin'] = {'slot': int(key), 'candidate_id': candidate['id'],
                                  'proposal_sha256': record['primary_sha256']}
                result['candidates'].append(item)
        return result

    def test_native_identities_must_be_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            board = TeamBoard(folder)
            first = board.register(0, 'native-a', self.root / 'a', 'session-a')
            self.assertEqual(board.register(0, 'native-a', self.root / 'a', 'session-a'), first)
            for values in [('native-a', self.root / 'b', 'session-b'),
                           ('native-b', self.root / 'a', 'session-b'),
                           ('native-b', self.root / 'b', 'session-a')]:
                with self.assertRaises(ValueError):
                    board.register(1, *values)
            with self.assertRaises(ValueError):
                board.register(0, 'native-other', self.root / 'other', 'session-other')

    def test_peer_proof_issue_requires_actual_proof_repair(self):
        self.documents[1]['candidates'][0]['proof'] = 'Fixture invalid proof'
        self.propose_all()
        for slot in range(4):
            status = self.board.status(slot)
            issue = self.issues(slot) if slot == 0 else []
            if issue:
                issue[0]['target_fields'] = ['proof']
            self.board.review(slot, status['review_target'], status['target_primary_sha256'], issue, expected_round=1)
        document = copy.deepcopy(self.documents[1])
        decision = [{'issue_id': 'R1-slot0', 'decision': 'accepted', 'reason': 'Fixture proof repair',
                     'source_ids': [], 'change': 'Replaced the invalid step'}]
        document['candidates'][0]['risks'] = ['An unrelated risk does not repair the proof']
        with self.assertRaises(ValueError):
            self.board.revise(1, document, sha(document), decision, expected_round=1)
        document['candidates'][0]['proof'] = 'Fixture proof with the missing condition'
        receipt = self.board.revise(1, document, sha(document), decision, expected_round=1)
        self.assertEqual(receipt['operation'], 'revise')

    def test_unregistered_and_invalid_slots_are_rejected(self):
        board = TeamBoard(self.root / 'unregistered')
        for slot in (0, -1, 4, True, '1'):
            with self.assertRaises(ValueError):
                board.status(slot)
        with self.assertRaises(ValueError):
            board.propose(0, proposal(0), sha(proposal(0)))

    def test_proposal_barrier_hides_other_researchers_until_all_submit(self):
        document = self.documents[0]
        self.board.propose(0, document, sha(document))
        snapshot = self.board.snapshot(1)
        self.assertEqual(snapshot['phase'], 'proposing')
        self.assertEqual(snapshot['frozen_proposals'], {})
        self.assertEqual(snapshot['review_history'], [])
        with self.assertRaises(ValueError):
            self.board.review(0, 1, sha(self.documents[1]), [], expected_round=1)
        for slot in (1, 2, 3):
            self.board.propose(slot, self.documents[slot], sha(self.documents[slot]))
        self.assertEqual(len(self.board.snapshot(1)['frozen_proposals']), 4)
        self.assertEqual(self.board.status(0)['review_target'], 1)

    def test_proposals_are_immutable_and_idempotent(self):
        document = self.documents[0]
        first = self.board.propose(0, document, sha(document))
        self.assertEqual(self.board.propose(0, document, sha(document)), first)
        changed = copy.deepcopy(document)
        changed['candidates'][0]['title'] += ' changed'
        with self.assertRaises(ValueError):
            self.board.propose(0, changed, sha(changed))
        document['candidates'][0]['title'] = 'external mutation'
        self.assertNotEqual(self.board.snapshot(0)['own_proposal']['document'], document)

    def test_reviews_require_assigned_peer_and_exact_frozen_hash(self):
        self.propose_all()
        with self.assertRaises(ValueError):
            self.board.review(0, 2, sha(self.documents[2]), self.issues(0), expected_round=1)
        with self.assertRaises(ValueError):
            self.board.review(0, 1, '0' * 64, self.issues(0), expected_round=1)
        with self.assertRaises(ValueError):
            self.board.review(0, 1, sha(self.documents[1]), self.issues(0), expected_round=2)

    def test_factual_issues_need_sources_but_methodological_issues_do_not(self):
        self.propose_all()
        issues = self.issues(0, kind='factual')
        issues[0]['source_ids'] = []
        with self.assertRaisesRegex(ValueError, 'Factual'):
            self.board.review(0, 1, sha(self.documents[1]), issues, expected_round=1)
        receipt = self.board.review(0, 1, sha(self.documents[1]), self.issues(0), expected_round=1)
        self.assertEqual(receipt['operation'], 'review')

    def test_issues_must_target_real_candidates_and_have_valid_contract(self):
        self.propose_all()
        for key, value in [('candidate_id', 'invented'), ('kind', 'opinion'),
                           ('problem', ''), ('repair', ''), ('source_ids', None)]:
            issues = self.issues(0)
            issues[0][key] = value
            with self.assertRaises(ValueError):
                self.board.review(0, 1, sha(self.documents[1]), issues, expected_round=1)
        with self.assertRaises(ValueError):
            self.board.review(0, 1, sha(self.documents[1]), self.issues(0) * 2, expected_round=1)

    def test_partial_reviews_are_hidden_and_cannot_trigger_revision(self):
        self.propose_all()
        self.board.review(0, 1, sha(self.documents[1]), self.issues(0), expected_round=1)
        self.assertEqual(self.board.snapshot(1)['review_history'], [])
        self.assertEqual(self.board.snapshot(1)['incoming_issues'], [])
        with self.assertRaises(ValueError):
            self.board.revise(1, self.documents[1], sha(self.documents[1]), [], expected_round=1)

    def test_each_issue_requires_one_decision_without_forcing_acceptance(self):
        self.propose_all(); self.review_all()
        document = self.documents[0]
        incoming = self.board.snapshot(0)['incoming_issues']
        self.assertEqual(len(incoming), 1)
        with self.assertRaisesRegex(ValueError, 'Every incoming'):
            self.board.revise(0, document, sha(document), [], expected_round=1)
        decision = {'issue_id': incoming[0]['id'], 'decision': 'rejected',
                    'reason': 'The synthetic fixture deliberately retains the original control',
                    'source_ids': [], 'change': ''}
        with self.assertRaises(ValueError):
            self.board.revise(0, document, sha(document), [decision, decision], expected_round=1)
        receipt = self.board.revise(0, document, sha(document), [decision], expected_round=1)
        record = self.board.state['rounds']['1']['revisions']['0']
        self.assertEqual(record['decisions'][0]['decision'], 'rejected')
        self.assertEqual(receipt, self.board.revise(0, document, sha(document), [decision], expected_round=1))

    def test_accepted_issue_requires_change_to_corresponding_candidate(self):
        self.propose_all(); self.review_all()
        document = copy.deepcopy(self.documents[0])
        issue_id = self.board.snapshot(0)['incoming_issues'][0]['id']
        decision = {'issue_id': issue_id, 'decision': 'accepted', 'reason': 'Control correction',
                    'source_ids': [], 'change': 'Added a control'}
        with self.assertRaisesRegex(ValueError, 'actual change'):
            self.board.revise(0, document, sha(document), [decision], expected_round=1)
        document['candidates'][1]['hypothesis'] += ' unrelated change'
        with self.assertRaisesRegex(ValueError, 'actual change'):
            self.board.revise(0, document, sha(document), [decision], expected_round=1)
        document['candidates'][0]['origin'] = {'not': 'scientific content'}
        with self.assertRaisesRegex(ValueError, 'actual change'):
            self.board.revise(0, document, sha(document), [decision], expected_round=1)
        document['candidates'][0]['hypothesis'] += ' with matched control'
        self.board.revise(0, document, sha(document), [decision], expected_round=1)

    def test_uncertainty_is_retained_without_auto_acceptance(self):
        self.propose_all(); self.review_all(); self.revise_all(decision='uncertain')
        record = self.board.state['rounds']['1']['revisions']['0']
        self.assertEqual(record['decisions'][0]['decision'], 'uncertain')
        self.assertEqual(record['document'], self.documents[0])

    def accepted_decision(self):
        issue = self.board.snapshot(0)['incoming_issues'][0]
        return [{'issue_id': issue['id'], 'decision': 'accepted', 'reason': 'Synthetic repair',
                 'source_ids': [], 'change': 'Synthetic candidate response'}]

    def review_targets(self, targets, *, canonical=True):
        if canonical:
            self.documents[0]['candidates'][0]['protocol'] = protocol_descriptor()['template']
        self.propose_all()
        receipts = []
        for slot in range(4):
            status = self.board.status(slot)
            issues = self.issues(slot) if slot == 3 else []
            if issues:
                issues[0]['target_fields'] = targets
            receipts.append(self.board.review(slot, status['review_target'], status['target_primary_sha256'],
                                              issues, expected_round=1))
        return receipts[-1]

    def test_sample_size_alias_binds_canonical_leaf_and_records_repair(self):
        review = self.review_targets(['sample_size'])
        self.assertEqual(review['resolved_target_paths']['R1-slot3'],
                         {'sample_size': ['protocol.analysis.sample_size']})
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['protocol']['analysis']['sample_size'] = 200
        receipt = self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        change = receipt['issue_changes']['R1-slot3']
        self.assertEqual(change['changed_canonical_paths'], ['protocol.analysis.sample_size'])
        self.assertEqual(change['resolved_target_paths'], review['resolved_target_paths']['R1-slot3'])
        self.assertEqual(change['scientific_resolution'], 'not_verified')

    def test_sample_size_cannot_be_repaired_by_budget_risk_or_alias(self):
        self.review_targets(['sample_size'])
        for addition in ('new_alias', 'budget', 'risk', 'method'):
            with self.subTest(addition=addition):
                document = copy.deepcopy(self.documents[0]); candidate = document['candidates'][0]
                if addition == 'new_alias':
                    candidate['sample_size'] = 200
                elif addition == 'budget':
                    candidate['protocol']['resources']['compute_budget'] = '200 GPU hours'
                elif addition == 'risk':
                    candidate['risks'] = ['Acknowledge imprecision']
                else:
                    candidate['protocol']['analysis']['method'] = 'Paired analysis'
                with self.assertRaisesRegex(ValueError, 'targeted fields'):
                    self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_preexisting_mirror_does_not_override_canonical_target(self):
        self.documents[0]['candidates'][0]['sample_size'] = 100
        self.review_targets(['sample_size'])
        document = copy.deepcopy(self.documents[0]); document['candidates'][0]['sample_size'] = 200
        with self.assertRaisesRegex(ValueError, 'targeted fields'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_legacy_top_level_sample_size_and_missing_field_still_supported(self):
        self.documents[0]['candidates'][0]['sample_size'] = 100
        review = self.review_targets(['sample_size', 'power_analysis'], canonical=False)
        self.assertEqual(review['resolved_target_paths']['R1-slot3'],
                         {'sample_size': ['sample_size'], 'power_analysis': ['power_analysis']})
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0].update(sample_size=200, power_analysis='Pilot required')
        receipt = self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        self.assertEqual(receipt['issue_changes']['R1-slot3']['changed_canonical_paths'],
                         ['power_analysis', 'sample_size'])

    def test_explicit_protocol_method_path_ignores_other_analysis_fields(self):
        self.review_targets(['protocol.analysis.method'])
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['protocol']['analysis']['sample_size'] = 100
        with self.assertRaisesRegex(ValueError, 'targeted fields'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        document['candidates'][0]['protocol']['analysis']['method'] = 'Paired bootstrap'
        receipt = self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        self.assertEqual(receipt['issue_changes']['R1-slot3']['changed_canonical_paths'],
                         ['protocol.analysis.method'])

    def test_unknown_protocol_path_is_rejected_when_review_is_frozen(self):
        self.propose_all(); status = self.board.status(0)
        for path in ('protocol.quality_score', 'protocol.analysis.sample_size.typo', 'title', 'protocol.schema_version'):
            issue = self.issues(0); issue[0]['target_fields'] = [path]
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'scientific fields'):
                self.board.review(0, status['review_target'], status['target_primary_sha256'], issue, expected_round=1)

    def test_legacy_review_receipt_resolves_against_frozen_proposal(self):
        self.review_targets(['power_analysis'])
        self.board.state['rounds']['1']['reviews']['3']['receipt'].pop('resolved_target_paths')
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['protocol']['analysis']['power']['assumptions'] = 'Pilot covariance required'
        receipt = self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        self.assertEqual(receipt['issue_changes']['R1-slot3']['changed_canonical_paths'],
                         ['protocol.analysis.power'])

    def test_frozen_path_binding_cannot_be_reinterpreted_at_revision(self):
        self.review_targets(['sample_size'])
        self.board.state['rounds']['1']['reviews']['3']['receipt']['resolved_target_paths']['R1-slot3'] = {
            'sample_size': ['protocol.resources.compute_budget']}
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['protocol']['analysis']['sample_size'] = 200
        with self.assertRaisesRegex(ValueError, 'Frozen review target paths'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_metric_leaf_projection_ignores_order_role_and_endpoint_definition(self):
        protocol = protocol_descriptor()['template']
        second = copy.deepcopy(protocol['endpoints'][0]); second['id'] = 'E2'
        # review_targets supplies the same template; add the second endpoint
        # before freezing explicitly to exercise stable endpoint identities.
        self.documents[0]['candidates'][0]['protocol'] = protocol
        protocol['endpoints'].append(second)
        self.review_targets(['metrics'], canonical=False)
        document = copy.deepcopy(self.documents[0])
        endpoints = document['candidates'][0]['protocol']['endpoints']
        endpoints.reverse(); endpoints[0].update(role='secondary', definition='Unrelated prose')
        with self.assertRaisesRegex(ValueError, 'targeted fields'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        endpoints[0]['metric'] = 'Paired difference'
        receipt = self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        self.assertEqual(receipt['issue_changes']['R1-slot3']['changed_canonical_paths'],
                         ['protocol.endpoints[*].metric'])

    def test_compute_budget_alias_ignores_resource_status_and_stopping_rule(self):
        self.review_targets(['compute_budget'])
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['protocol']['resources'].update(status='estimated', stopping_rule='Stop at 100 items')
        with self.assertRaisesRegex(ValueError, 'targeted fields'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_removing_protocol_cannot_switch_to_top_level_alias(self):
        self.review_targets(['sample_size'])
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0].pop('protocol'); document['candidates'][0]['sample_size'] = 200
        with self.assertRaisesRegex(ValueError, 'preserve the canonical protocol'):
            self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_accepted_metadata_or_title_only_change_is_rejected(self):
        self.propose_all(); self.review_all()
        for key, value in [('acknowledged', True), ('title', 'Cosmetically renamed hypothesis'),
                           ('origin', {'slot': 0}), ('notes', 'We fixed it')]:
            document = copy.deepcopy(self.documents[0])
            document['candidates'][0][key] = value
            with self.assertRaisesRegex(ValueError, 'actual change'):
                self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_accepted_source_order_or_duplicate_only_change_is_rejected(self):
        self.propose_all(); self.review_all()
        for sources in (['fixture-2', 'fixture-1'], ['fixture-1', 'fixture-2', 'fixture-1']):
            document = copy.deepcopy(self.documents[0])
            document['candidates'][0]['source_ids'] = sources
            with self.assertRaisesRegex(ValueError, 'actual change'):
                self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_accepted_new_source_can_count_as_content_change(self):
        self.propose_all()
        for slot in range(4):
            status = self.board.status(slot)
            issues = self.issues(slot)
            issues[0]['target_fields'] = ['source_ids']
            self.board.review(slot, status['review_target'], status['target_primary_sha256'],
                              issues, expected_round=1)
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['source_ids'].append('fixture-new-source')
        # The ResearchService, rather than this isolated state board, must
        # authenticate that the new source was actually retrieved.
        self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_unrelated_risk_or_source_change_cannot_discharge_hypothesis_issue(self):
        self.propose_all(); self.review_all()
        for field, value in [('risks',['We acknowledge the problem']),
                              ('source_ids',['fixture-1','fixture-2','fixture-new'])]:
            document=copy.deepcopy(self.documents[0])
            document['candidates'][0][field]=value
            with self.assertRaisesRegex(ValueError,'targeted fields'):
                self.board.revise(0,document,sha(document),self.accepted_decision(),expected_round=1)

    def test_one_hypothesis_edit_does_not_discharge_a_separate_control_issue(self):
        self.propose_all()
        for slot in range(4):
            status=self.board.status(slot)
            issues=self.issues(slot)
            extra=copy.deepcopy(issues[0]); extra['id']+='-control'
            extra['target_fields']=['falsification']
            self.board.review(slot,status['review_target'],status['target_primary_sha256'],
                              issues+[extra],expected_round=1)
        document=copy.deepcopy(self.documents[0])
        document['candidates'][0]['hypothesis']+=' corrected'
        decisions=[{'issue_id':issue['id'],'decision':'accepted','reason':'Fixture repair',
                    'source_ids':[],'change':'Updated candidate'}
                   for issue in self.board.snapshot(0)['incoming_issues']]
        with self.assertRaisesRegex(ValueError,'targeted fields'):
            self.board.revise(0,document,sha(document),decisions,expected_round=1)

    def test_already_rejected_candidate_is_not_a_new_rejection_for_every_issue(self):
        for document in self.documents.values():
            document['candidates'][0].update(disposition='rejected',rejection_reason='Already rejected')
            document['selected_ids']=['C1']
        self.propose_all(); self.review_all()
        document=copy.deepcopy(self.documents[0])
        document['candidates'][0]['rejection_reason']+='; reiterated'
        with self.assertRaisesRegex(ValueError,'targeted fields'):
            self.board.revise(0,document,sha(document),self.accepted_decision(),expected_round=1)

    def test_real_repair_receipt_does_not_claim_scientific_resolution(self):
        self.propose_all(); self.review_all()
        document=copy.deepcopy(self.documents[0])
        document['candidates'][0]['hypothesis']+=' with the specified control'
        receipt=self.board.revise(0,document,sha(document),self.accepted_decision(),expected_round=1)
        self.assertEqual(receipt['scientific_resolution'],'not_verified')
        change=next(iter(receipt['issue_changes'].values()))
        self.assertEqual(change['changed_target_fields'],['hypothesis'])
        self.assertEqual(change['scientific_resolution'],'not_verified')

    def test_accepting_factual_criticism_can_inherit_the_issue_source(self):
        self.propose_all()
        for slot in range(4):
            status = self.board.status(slot)
            self.board.review(slot, status['review_target'], status['target_primary_sha256'],
                              self.issues(slot, kind='factual'), expected_round=1)
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['hypothesis'] += ' corrected against the incoming cited source'
        decisions = self.accepted_decision()
        self.assertEqual(decisions[0]['source_ids'], [])
        self.board.revise(0, document, sha(document), decisions, expected_round=1)
        self.assertEqual(self.board.state['rounds']['1']['reviews']['3']['issues'][0]['source_ids'], ['fixture-1'])

    def test_accepting_issue_can_reject_candidate_with_explicit_reason(self):
        self.propose_all(); self.review_all()
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['disposition'] = 'rejected'
        for reason in (None, '', '   '):
            document['candidates'][0]['rejection_reason'] = reason
            with self.assertRaisesRegex(ValueError, 'actual change'):
                self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)
        document['candidates'][0]['rejection_reason'] = 'The matched control eliminates the synthetic proposed mechanism'
        self.board.revise(0, document, sha(document), self.accepted_decision(), expected_round=1)

    def test_revision_barrier_freezes_same_round_and_hides_partial_changes(self):
        self.propose_all(); self.review_all()
        document = copy.deepcopy(self.documents[0])
        document['candidates'][0]['hypothesis'] += ' corrected'
        issue_id = self.board.snapshot(0)['incoming_issues'][0]['id']
        decisions = [{'issue_id': issue_id, 'decision': 'accepted', 'reason': 'Correction',
                      'source_ids': [], 'change': 'Changed hypothesis'}]
        self.board.revise(0, document, sha(document), decisions, expected_round=1)
        snapshot = self.board.snapshot(1)
        self.assertEqual(snapshot['revision_history'], [])
        self.assertEqual(snapshot['frozen_proposals']['0']['document'], self.documents[0])
        with self.assertRaises(ValueError):
            self.board.review(0, 2, sha(self.documents[2]), self.issues(0, 2), expected_round=2)

    def test_candidate_deletion_is_not_silently_allowed(self):
        self.propose_all(); self.review_all()
        document = copy.deepcopy(self.documents[0])
        document['candidates'].pop()
        with self.assertRaisesRegex(ValueError, 'Preserve each candidate'):
            self.board.revise(0, document, sha(document), [], expected_round=1)

    def test_round_two_targets_a_different_peer_and_uses_revised_documents(self):
        self.propose_all(); self.review_all(); self.revise_all(decision='accepted')
        status = self.board.status(0)
        self.assertEqual(status['review_target'], 2)
        self.assertEqual(status['target_primary_sha256'], sha(self.documents[2]))
        self.assertIn('control round 1', self.board.snapshot(0)['frozen_proposals']['2']['document']['candidates'][0]['hypothesis'])

    def test_identical_no_issue_rounds_do_not_get_stuck_as_historical_retries(self):
        self.finish_rounds(empty=True)
        self.assertEqual(self.board.summary()['review_count'], 8)
        self.assertEqual(self.board.summary()['revision_count'], 8)
        self.assertEqual(self.board.summary()['phase'], 'synthesizing')
        before = self.board.summary()['event_count']
        self.board.review(0, 1, sha(self.documents[1]), [], expected_round=1)
        self.board.revise(0, self.documents[0], sha(self.documents[0]), [], expected_round=1)
        self.assertEqual(self.board.summary()['event_count'], before)

    def test_stale_round_cannot_overwrite_a_submission(self):
        self.propose_all(); self.review_all(); self.revise_all()
        with self.assertRaises(ValueError):
            self.board.review(0, 1, sha(self.documents[1]), [], expected_round=1)
        changed = copy.deepcopy(self.documents[0]); changed['extra'] = 'new'
        with self.assertRaises(ValueError):
            self.board.revise(0, changed, sha(changed), [], expected_round=1)

    def test_only_coordinator_after_all_rounds_can_synthesize(self):
        with self.assertRaises(ValueError):
            self.board.synthesize(0, proposal(0, count=8), sha('early'))
        self.finish_rounds()
        document = self.synthesis()
        with self.assertRaises(ValueError):
            self.board.synthesize(1, document, sha(document))
        self.board.synthesize(0, document, sha(document))
        with self.assertRaises(ValueError):
            self.board.synthesize(1, document, sha(document))

    def test_synthesis_requires_all_final_origins_including_rejected_candidates(self):
        self.finish_rounds()
        document = self.synthesis()
        self.assertEqual(len(document['candidates']), 8)
        document['candidates'][-1]['disposition'] = 'rejected'
        for operation in ('missing', 'wrong_hash', 'duplicate_origin'):
            changed = copy.deepcopy(document)
            if operation == 'missing':
                changed['candidates'].pop()
            elif operation == 'wrong_hash':
                changed['candidates'][0]['origin']['proposal_sha256'] = '0' * 64
            else:
                changed['candidates'][-1]['origin'] = copy.deepcopy(changed['candidates'][0]['origin'])
            with self.assertRaises(ValueError):
                self.board.synthesize(0, changed, sha(changed))
        self.board.synthesize(0, document, sha(document))
        self.assertEqual(self.board.summary()['synthesis_count'], 1)

    def test_synthesis_snapshots_use_final_round_not_previous_round(self):
        self.propose_all()
        for number in (1, 2):
            self.review_all(number); self.revise_all(number, decision='accepted')
        document = self.synthesis()
        for item in document['candidates']:
            slot = item['origin']['slot']
            self.assertEqual(item['origin']['proposal_sha256'], sha(self.documents[slot]))
        self.board.synthesize(0, document, sha(document))

    def test_grade_requires_exact_recorded_synthesis_and_preserves_best_history(self):
        self.finish_rounds()
        document = self.synthesis()
        self.assertTrue(self.board.grade_errors(document, sha(document)))
        receipt = self.board.synthesize(0, document, sha(document))
        self.assertEqual(self.board.synthesize(0, document, sha(document)), receipt)
        self.assertEqual(self.board.grade_errors(document, sha(document)), [])
        changed = copy.deepcopy(document); changed['selection_rationale'] = 'Second exploratory revision'
        self.assertTrue(self.board.grade_errors(changed, sha(document)))
        self.board.synthesize(0, changed, sha(changed))
        self.assertEqual(self.board.grade_errors(document, sha(document)), [])
        self.assertEqual(self.board.summary()['synthesis_count'], 2)
        self.assertTrue(self.board.grade_errors(document, sha(changed)))

    def test_reload_preserves_all_receipts_and_final_state(self):
        self.finish_rounds(); document = self.synthesis()
        self.board.synthesize(0, document, sha(document))
        loaded = TeamBoard(self.root / 'private')
        self.assertEqual(loaded.snapshot(0), self.board.snapshot(0))
        self.assertEqual(loaded.grade_errors(document, sha(document)), [])
        self.assertEqual(loaded.summary()['registered_agents'], 4)
        self.assertEqual(loaded.summary()['proposal_count'], 4)
        self.assertEqual(loaded.summary()['review_count'], 8)
        self.assertEqual(loaded.summary()['revision_count'], 8)
        self.assertTrue(loaded.summary()['complete'])
        self.assertFalse(loaded.summary()['independent_acceptance'])
        self.assertEqual(loaded.summary()['scientific_validation'], 'not_performed')

    def test_configuration_mismatch_and_nonfinite_document_are_rejected(self):
        for slots, rounds in ((1, 2), (5, 2), (True, 2), (4, 0), (4, 9)):
            with self.assertRaises(ValueError):
                TeamBoard(self.root / 'invalid', slots=slots, rounds=rounds)
        with self.assertRaises(ValueError):
            TeamBoard(self.root / 'private', slots=2)
        document = self.documents[0]; document['nonfinite'] = float('nan')
        with self.assertRaises(ValueError):
            self.board.propose(0, document, sha('finite hash'))

    def test_two_researchers_can_review_each_other_for_multiple_rounds(self):
        board = TeamBoard(self.root / 'two', slots=2, rounds=3)
        for slot in (0, 1):
            document = proposal(slot, 4)
            board.register(slot, f'two-agent-{slot}', self.root / f'two-{slot}', f'two-session-{slot}')
            board.propose(slot, document, sha(document))
        for number in (1, 2, 3):
            for slot in (0, 1):
                state = board.status(slot)
                self.assertEqual(state['review_target'], 1 - slot)
                board.review(slot, 1 - slot, sha(proposal(1 - slot, 4)), [], expected_round=number)
            for slot in (0, 1):
                board.revise(slot, proposal(slot, 4), sha(proposal(slot, 4)), [], expected_round=number)
        self.assertEqual(board.summary()['review_count'], 6)
        self.assertEqual(board.summary()['phase'], 'synthesizing')

    @unittest.skipUnless(os.name == 'posix', 'Unix ownership/mode semantics')
    def test_private_persistence_modes(self):
        self.assertEqual(stat.S_IMODE((self.root / 'private').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.board.path.stat().st_mode), 0o600)
        self.assertFalse(self.board.path.with_name('team-state.json.pending').exists())


if __name__ == '__main__':
    unittest.main()
