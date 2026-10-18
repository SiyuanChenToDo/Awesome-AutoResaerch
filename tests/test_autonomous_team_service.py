"""Offline service contracts for authenticated native research teams.

The HTTP server is local; scholarly and model providers are blocked in every test.
Slow-call checks use events rather than paid requests or timing a provider.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sage.autonomous.dsh_runtime import team_token
from sage.autonomous.service import ResearchService, serve


SESSIONS = (
    'session-8bcf49e8-2861-43d3-98a5-e5334965a903',
    'session-a2eae48a-4917-4c46-b030-e274a16e68d9',
)


def candidate_document(count=8):
    """Synthetic schema fixtures, never presented as scientific findings."""
    return {
        'candidates': [{
            'id': 'C' + str(i), 'title': 'Fixture hypothesis ' + str(i),
            'problem': 'Fixture problem', 'hypothesis': 'Fixture conditional prediction',
            'mechanism': 'Fixture mechanism', 'assumptions': 'Fixture conditions',
            'source_ids': ['p0', 'p1'],
            'closest_prior_art': [{'paper_id': 'p0', 'overlap': 'Fixture overlap',
                                  'difference': 'Fixture difference'}],
            'falsification': {'test': 'Fixture test', 'controls': 'Fixture control',
                              'metric': 'Fixture error', 'reject_if': 'Fixture null effect'},
            'risks': ['Fixture limitation'], 'status': 'provisional',
        } for i in range(count)],
        'selected_ids': ['C0'], 'selection_rationale': 'Synthetic service contract fixture',
    }


class TeamServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'fixture topic',
                                       researchers=2, discussion_rounds=2)
        self.workspaces = []
        for slot in range(2):
            workspace = self.root / 'native-run' / 'agents' / ('researcher-' + str(slot))
            workspace.mkdir(parents=True)
            self.workspaces.append(workspace)
        self.master = 'fixture-manager-token-not-a-provider-key'
        self.model = mock.patch('sage.autonomous.service.OpenAIModel.from_env',
                                side_effect=AssertionError('No paid model calls in offline tests')).start()
        self.search = mock.patch('sage.autonomous.service.ArxivSource.search',
                                 side_effect=AssertionError('No scholarly network calls in offline tests')).start()
        self.addCleanup(mock.patch.stopall)
        self.server = serve(self.service, self.master)
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, token, tool, arguments=None):
        request = Request('http://127.0.0.1:' + str(self.server.server_port) + '/tool',
                          data=json.dumps({'tool': tool, 'arguments': arguments or {}}).encode(),
                          headers={'Content-Type': 'application/json',
                                   'Authorization': 'Bearer ' + token})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def identity(self, slot):
        return {'slot': slot, 'agent_id': 'researcher-' + str(slot),
                'cwd': str(self.workspaces[slot]), 'session_id': SESSIONS[slot]}

    def register(self, slot):
        result = self.post(self.master, 'runtime_register', self.identity(slot))
        self.assertNotIn('error', result)
        return result

    def seed_evidence(self):
        self.service.papers = {'p' + str(i): {'paper_id': 'p' + str(i)} for i in range(12)}
        self.service.cards = {'p' + str(i): {'claims': [{'claim': 'Synthetic claim'}]}
                              for i in range(6)}
        self.service.searches = [{'purpose': purpose, 'results': [{'paper_id': 'p0'}]}
                                for purpose in ('landscape', 'novelty', 'counterevidence')]
        self.service.reviews = [{'id': 'fixture-review', 'grading': False}]

    def write_artifact(self, slot, name='proposal.json', count=4):
        path = self.workspaces[slot] / name
        path.write_text(json.dumps(candidate_document(count)), encoding='utf-8')
        return path

    def test_slot_tokens_are_hmac_bound_distinct_and_not_master(self):
        expected = hmac.new(self.master.encode(), b'sage-research-slot:0',
                            hashlib.sha256).hexdigest()
        self.assertEqual(team_token(self.master, 0), expected)
        self.assertNotEqual(team_token(self.master, 0), team_token(self.master, 1))
        self.assertNotEqual(team_token(self.master, 0), self.master)
        self.assertNotEqual(team_token(self.master + '-other', 0), expected)

    def test_invalid_token_cannot_access_or_register(self):
        with self.assertRaises(HTTPError) as error:
            self.post('invalid-token', 'runtime_register', self.identity(0))
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(self.service.team.summary()['registered_agents'], 0)

    def test_master_registers_native_identity_but_cannot_issue_agent_calls(self):
        receipt = self.register(0)
        self.assertEqual(receipt['slot'], 0)
        for tool, args in (('team', {'action': 'status'}), ('evidence', {}),
                           ('search', {'query': 'fixture'})):
            with self.subTest(tool=tool):
                result = self.post(self.master, tool, args)
                self.assertEqual(result['error'], 'ValueError')
                self.assertIn('per-researcher', result['message'])
        self.search.assert_not_called()
        self.assertEqual(self.service.tool_calls, 0)

    def test_agent_token_cannot_register_itself_or_a_peer(self):
        for target in (0, 1):
            with self.subTest(target=target):
                result = self.post(team_token(self.master, 0), 'runtime_register', self.identity(target))
                self.assertEqual(result['error'], 'ValueError')
                self.assertIn('Only the manager', result['message'])
        self.assertEqual(self.service.team.summary()['registered_agents'], 0)

    def test_registration_rejects_foreign_worktree_and_invalid_native_session(self):
        for change in ({'cwd': str(self.root / 'outside-agents')},
                       {'session_id': 'invented-session'}):
            with self.subTest(change=change):
                identity = self.identity(0) | change
                result = self.post(self.master, 'runtime_register', identity)
                self.assertEqual(result['error'], 'ValueError')
        self.assertEqual(self.service.team.summary()['registered_agents'], 0)

    def test_same_native_session_cannot_register_two_researchers(self):
        self.register(0)
        identity = self.identity(1) | {'session_id': SESSIONS[0]}
        result = self.post(self.master, 'runtime_register', identity)
        self.assertEqual(result['error'], 'ValueError')
        self.assertEqual(self.service.team.summary()['registered_agents'], 1)

    def test_team_identity_comes_from_token_even_if_payload_claims_another_slot(self):
        self.register(0)
        self.register(1)
        for slot in (0, 1):
            result = self.post(team_token(self.master, slot), 'team',
                               {'action': 'status', 'slot': 1 - slot})
            self.assertEqual(result['slot'], slot)
            self.assertEqual(result['role'], self.service.team.state['roster'][str(slot)]['role'])

    def test_unregistered_slot_cannot_access_team_or_research_tools(self):
        for tool, args in (('team', {'action': 'status'}), ('evidence', {}),
                           ('search', {'query': 'fixture'})):
            with self.subTest(tool=tool):
                result = self.post(team_token(self.master, 0), tool, args)
                self.assertEqual(result['error'], 'ValueError')
                self.assertIn('register', result['message'])
        self.assertEqual(self.service.coordination_calls, 0)
        self.assertEqual(self.service.tool_calls, 0)
        self.search.assert_not_called()

    def test_http_cannot_invoke_formal_grade_even_with_manager_token(self):
        self.register(0)
        for token in (self.master, team_token(self.master, 0)):
            with self.subTest(token_is_master=token == self.master):
                result = self.post(token, 'grade', {'artifact_path': '/fixture/conjectures.json'})
                self.assertEqual(result['error'], 'ValueError')
                self.assertIn('manager-private', result['message'])
        self.assertEqual(self.service.grades, [])
        self.model.assert_not_called()

    def test_peer_primary_artifact_cannot_be_used_as_own_proposal(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        peer_file = self.write_artifact(1)
        result = self.post(team_token(self.master, 0), 'team',
                           {'action': 'propose', 'artifact_path': str(peer_file)})
        self.assertEqual(result['error'], 'ValueError')
        self.assertIn('inside this run', result['message'])
        self.assertEqual(self.service.team.summary()['proposal_count'], 0)
        own = self.write_artifact(0)
        result = self.post(team_token(self.master, 0), 'team',
                           {'action': 'propose', 'artifact_path': str(own)})
        self.assertNotIn('error', result)
        self.assertEqual(result['slot'], 0)
        self.assertEqual(self.service.team.summary()['proposal_count'], 1)

    def test_peer_file_cannot_be_reviewed_via_own_critique_transport(self):
        self.register(0)
        self.register(1)
        peer_file = self.write_artifact(1)
        result = self.post(team_token(self.master, 0), 'critique',
                           {'artifact_path': str(peer_file), 'focus': 'fixture'})
        self.assertEqual(result['error'], 'ValueError')
        self.model.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Native artifact-root symlink confinement is POSIX-specific')
    def test_registered_artifact_root_cannot_be_replaced_with_a_symlink(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        primary = self.write_artifact(0)
        workspace = self.workspaces[0]
        moved = workspace.with_name(workspace.name + '-moved')
        workspace.rename(moved)
        try:
            workspace.symlink_to(moved, target_is_directory=True)
        except OSError as error:
            self.skipTest('Directory symlinks unavailable: ' + type(error).__name__)
        result = self.post(team_token(self.master, 0), 'team',
                           {'action': 'propose', 'artifact_path': str(primary)})
        self.assertEqual(result['error'], 'ValueError')
        self.assertIn('Artifact root', result['message'])
        self.assertEqual(self.service.team.summary()['proposal_count'], 0)

    def test_missing_review_or_revision_round_has_an_actionable_error(self):
        self.register(0)
        for action in ('review', 'revise'):
            with self.subTest(action=action):
                result = self.post(team_token(self.master, 0), 'team', {'action': action})
                self.assertEqual(result['error'], 'ValueError')
                self.assertIn('current round from team status', result['message'])

    def test_initial_evidence_exposes_only_the_authenticated_researchers_reviews(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        self.service.reviews = [
            {'id': 'own-zero', 'research_slot': 0, 'review': {'summary': 'Private first idea'}},
            {'id': 'own-one', 'research_slot': 1, 'review': {'summary': 'Private second idea'}},
            {'id': 'formal', 'research_slot': None, 'grading': True},
        ]
        for slot, expected in ((0, 'own-zero'), (1, 'own-one')):
            result = self.post(team_token(self.master, slot), 'evidence')
            self.assertEqual([r['id'] for r in result['reviews']], [expected])
        for slot in (0, 1):
            receipt = self.post(team_token(self.master, slot), 'team',
                                {'action': 'propose', 'artifact_path': str(self.write_artifact(slot))})
            self.assertNotIn('error', receipt)
        result = self.post(team_token(self.master, 0), 'evidence')
        self.assertEqual([r['id'] for r in result['reviews']], ['own-zero', 'own-one', 'formal'])

    def test_source_ids_in_peer_issues_must_be_actually_retrieved(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        for slot in (0, 1):
            path = self.write_artifact(slot)
            receipt = self.post(team_token(self.master, slot), 'team',
                                {'action': 'propose', 'artifact_path': str(path)})
            self.assertNotIn('error', receipt)
        status = self.post(team_token(self.master, 0), 'team', {'action': 'status'})
        result = self.post(team_token(self.master, 0), 'team', {
            'action': 'review', 'round': status['round'], 'target_slot': status['review_target'],
            'proposal_sha256': status['target_primary_sha256'],
            'issues': [{'id': 'fixture-issue', 'candidate_id': 'C0', 'kind': 'factual',
                        'problem': 'Fixture issue', 'repair': 'Fixture repair',
                        'source_ids': ['invented-paper-id']}],
        })
        self.assertEqual(result['error'], 'ValueError')
        self.assertIn('actually retrieved', result['message'])
        self.assertEqual(self.service.team.summary()['review_count'], 0)

    def test_slow_search_and_read_do_not_block_team_status(self):
        self.register(0)
        self.register(1)
        for tool, arguments in (('search', {'query': 'fixture'}),
                                ('read', {'paper_id': 'p0', 'topic': 'fixture'})):
            with self.subTest(tool=tool):
                entered, release = threading.Event(), threading.Event()

                async def blocked(**kwargs):
                    entered.set()
                    if not await asyncio.to_thread(release.wait, 5):
                        raise AssertionError('Test did not release blocked provider fixture')
                    return {'fixture': tool}

                with mock.patch.object(self.service, tool, side_effect=blocked), \
                        ThreadPoolExecutor(max_workers=2) as pool:
                    pending = pool.submit(self.post, team_token(self.master, 0), tool, arguments)
                    try:
                        self.assertTrue(entered.wait(2), 'Slow call did not reach its provider boundary')
                        status = pool.submit(self.post, team_token(self.master, 1), 'team', {'action': 'status'})
                        result = status.result(timeout=2)
                        self.assertEqual(result['slot'], 1)
                        self.assertEqual(result['next_action'], 'propose')
                        self.assertFalse(pending.done(), 'Status only completed after the slow call returned')
                    finally:
                        release.set()
                    self.assertEqual(pending.result(timeout=2), {'fixture': tool})

    def test_incomplete_team_cannot_reach_model_grade_with_other_contracts_satisfied(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        checkout = self.root / 'native-run' / '.coral' / 'private' / 'grader_checkouts' / 'fixture'
        checkout.mkdir(parents=True)
        primary = checkout / 'conjectures.json'
        primary.write_text(json.dumps(candidate_document()), encoding='utf-8')
        (checkout / 'CONJECTURES.md').write_text('Synthetic complete report fixture.\n' * 10,
                                                encoding='utf-8')
        judgment = mock.AsyncMock(side_effect=AssertionError('Incomplete team must not be scored'))
        with mock.patch.object(self.service, 'judgment', judgment):
            result = asyncio.run(self.service.grade(primary, agent_id='researcher-0'))
        self.assertEqual(result['score'], 0.0)
        self.assertEqual(len(result['contract_errors']), 1)
        self.assertIn('completed team synthesis', result['contract_errors'][0])
        self.assertEqual(self.service.grades[-1]['contract_errors'], result['contract_errors'])
        judgment.assert_not_awaited()
        self.model.assert_not_called()

    def test_noncoordinator_cannot_grade_even_an_exact_completed_synthesis_copy(self):
        self.register(0)
        self.register(1)
        self.seed_evidence()
        paths = {slot: self.write_artifact(slot) for slot in (0, 1)}
        for slot in (0, 1):
            receipt = self.post(team_token(self.master, slot), 'team',
                                {'action': 'propose', 'artifact_path': str(paths[slot])})
            self.assertNotIn('error', receipt)
        for number in (1, 2):
            for slot in (0, 1):
                status = self.post(team_token(self.master, slot), 'team', {'action': 'status'})
                receipt = self.post(team_token(self.master, slot), 'team', {
                    'action': 'review', 'round': number, 'target_slot': status['review_target'],
                    'proposal_sha256': status['target_primary_sha256'], 'issues': [],
                })
                self.assertNotIn('error', receipt)
            for slot in (0, 1):
                receipt = self.post(team_token(self.master, slot), 'team', {
                    'action': 'revise', 'round': number, 'artifact_path': str(paths[slot]),
                    'decisions': [],
                })
                self.assertNotIn('error', receipt)
        status = self.post(team_token(self.master, 0), 'team', {'action': 'status'})
        synthesis = {'candidates': [], 'selected_ids': ['S0-C0']}
        for slot, record in status['frozen_proposals'].items():
            for candidate in record['document']['candidates']:
                item = copy.deepcopy(candidate)
                item['id'] = 'S' + slot + '-' + candidate['id']
                item['origin'] = {'slot': int(slot), 'candidate_id': candidate['id'],
                                  'proposal_sha256': record['primary_sha256']}
                synthesis['candidates'].append(item)
        primary = self.workspaces[0] / 'conjectures.json'
        primary.write_text(json.dumps(synthesis), encoding='utf-8')
        receipt = self.post(team_token(self.master, 0), 'team',
                            {'action': 'synthesize', 'artifact_path': str(primary)})
        self.assertNotIn('error', receipt)
        checkout = self.root / 'native-run' / '.coral' / 'private' / 'grader_checkouts' / 'exact-copy'
        checkout.mkdir(parents=True)
        copied = checkout / 'conjectures.json'
        copied.write_bytes(primary.read_bytes())
        (checkout / 'CONJECTURES.md').write_text('Synthetic completed report.\n' * 10, encoding='utf-8')
        judgment = mock.AsyncMock(return_value={'id': 'fixture-formal-grade', 'review': {'score': 0.5}})
        with mock.patch.object(self.service, 'judgment', judgment):
            for identity in ('researcher-1', None):
                with self.subTest(identity=identity):
                    denied = asyncio.run(self.service.grade(copied, agent_id=identity))
                    self.assertEqual(denied['score'], 0.0)
                    self.assertEqual(len(denied['contract_errors']), 1)
                    self.assertIn('manager-identified coordinator', denied['contract_errors'][0])
            judgment.assert_not_awaited()
            allowed = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertEqual(allowed['contract_errors'], [])
        self.assertEqual(allowed['score'], 0.5)
        judgment.assert_awaited_once()
        self.assertEqual(self.service.grades[-1]['agent_id'], 'researcher-0')
        self.model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
