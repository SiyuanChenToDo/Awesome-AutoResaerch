"""Offline contracts for tool-output archiving, compact team status and evidence filters.

No scholarly network or paid model calls: every oversized payload is synthetic
fixture data produced and inspected entirely inside a temporary run directory.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from sage.autonomous.service import (ResearchService, TOOL_OUTPUT_ARCHIVE_BYTES,
                                     summarize_tool_output)


def candidate_document(count=4):
    try:
        from test_autonomous_team_service import candidate_document as fixture
    except ImportError:  # running as an imported package module
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            'test_autonomous_team_service',
            Path(__file__).with_name('test_autonomous_team_service.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.candidate_document
    return fixture(count)


class ToolOutputArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'fixture topic')

    def events(self):
        return [json.loads(line) for line in
                (self.service.private / 'events.jsonl').read_text(encoding='utf-8').splitlines()]

    def seed_oversized_evidence(self):
        self.service.papers = {'p' + str(index): {'paper_id': 'p' + str(index),
                                                  'abstract': 'fixture abstract ' + 'x' * 30000}
                               for index in range(8)}

    def test_oversized_result_is_archived_and_returns_pointer(self):
        self.seed_oversized_evidence()
        full = self.service._call('evidence', {})
        wire = json.dumps(full, ensure_ascii=False).encode('utf-8')
        self.assertGreater(len(wire), TOOL_OUTPUT_ARCHIVE_BYTES)
        result = self.service.call('evidence', {})
        self.assertEqual(result['archived'], True)
        self.assertEqual(result['tool'], 'evidence')
        self.assertEqual(result['full_bytes'], len(wire))
        name = 'tool-output-' + hashlib.sha256(wire).hexdigest() + '.json'
        self.assertEqual(result['output_sha256'], hashlib.sha256(wire).hexdigest())
        self.assertEqual(result['output_file'], '.coral/public/tool-archive/' + name)
        pointer_bytes = json.dumps(result, ensure_ascii=False).encode('utf-8')
        self.assertLess(len(pointer_bytes), TOOL_OUTPUT_ARCHIVE_BYTES)
        archive = self.root / 'native-run' / '.coral' / 'public' / 'tool-archive' / name
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.read_bytes(), wire, 'shared archive must be byte-identical')
        self.assertEqual(archive.read_bytes(),
                         (self.service.private / name).read_bytes(),
                         'shared archive must match the manager-private copy')
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(archive.parent.stat().st_mode), 0o755)
        completed = next(event for event in self.events()
                         if event['kind'] == 'tool_transfer_completed')
        self.assertEqual(completed['output_file'], name)
        self.assertEqual(completed['archived_file'], result['output_file'])
        self.assertEqual(completed['wire_json_sha256'], result['output_sha256'])
        self.assertIsNone(completed['archive_error'])
        self.assertEqual(completed['output_keys'], sorted(full))

    def test_archive_summary_is_deterministic_and_structured(self):
        self.seed_oversized_evidence()
        full = self.service._call('evidence', {})
        first = summarize_tool_output(full)
        second = summarize_tool_output(full)
        self.assertEqual(first, second)
        self.assertEqual(first['type'], 'object')
        papers = first['keys']['papers']
        self.assertEqual(papers['type'], 'object')
        self.assertEqual(papers['key_count'], 8)
        described = papers['keys']['p0']
        self.assertEqual(described['type'], 'object')
        self.assertEqual(described['keys']['abstract']['type'], 'string')
        self.assertEqual(described['keys']['abstract']['length'], 30017)
        self.assertEqual(first['keys']['searches'], {'type': 'list', 'length': 0})

    def test_archive_summary_lists_sample_items_for_long_lists(self):
        value = {'items': [{'a': 1}, [1, 2, 3, 4], 'text', {'b': 2}], 'tail': list(range(30))}
        summary = summarize_tool_output(value)
        self.assertEqual(summary['keys']['items']['type'], 'list')
        self.assertEqual(summary['keys']['items']['length'], 4)
        self.assertEqual(len(summary['keys']['items']['sample_items']), 3)
        self.assertEqual(summary['keys']['tail']['length'], 30)
        self.assertEqual(len(summary['keys']['tail']['sample_items']), 3)
        self.assertEqual(summary['keys']['items']['sample_items'][1]['length'], 4)

    def test_small_result_is_returned_unchanged_without_archive(self):
        self.service.papers = {'p': {'paper_id': 'p', 'abstract': 'small'}}
        self.service.cards = {'p': {'claims': [{'claim': 'Fixture claim'}]}}
        result = self.service.call('evidence', {})
        self.assertEqual(result, {'papers': {'p': {'paper_id': 'p', 'abstract': 'small'}},
                                  'cards': {'p': {'claims': [{'claim': 'Fixture claim'}]}},
                                  'reviews': [], 'searches': [], 'independent_acceptance': False})
        self.assertNotIn('archived', result)
        self.assertFalse((self.root / 'native-run').exists(),
                         'below-threshold results must not create the shared tree')
        completed = next(event for event in self.events()
                         if event['kind'] == 'tool_transfer_completed')
        self.assertIsNone(completed['archived_file'])
        self.assertIsNone(completed['archive_error'])

    def test_archive_write_failure_falls_back_to_inline_result(self):
        self.seed_oversized_evidence()
        full = self.service._call('evidence', {})
        with mock.patch('sage.autonomous.service.write_shared_bytes',
                        side_effect=OSError('read-only shared tree')):
            result = self.service.call('evidence', {})
        self.assertEqual(result, full, 'failed archive must not lose or alter the result')
        self.assertNotIn('archived', result)
        completed = next(event for event in self.events()
                         if event['kind'] == 'tool_transfer_completed')
        self.assertIsNone(completed['archived_file'])
        self.assertEqual(completed['archive_error'], 'OSError')


class TeamStatusCompactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'fixture topic',
                                       researchers=2, discussion_rounds=1)
        self.workspaces = []
        for slot in range(2):
            workspace = self.root / 'native-run' / 'agents' / ('researcher-' + str(slot))
            workspace.mkdir(parents=True)
            self.workspaces.append(workspace)
            self.service.team.register(
                slot, 'researcher-' + str(slot), workspace,
                'session-00000000-0000-4000-8000-00000000000' + str(slot))
        self.service.papers = {'p' + str(index): {'paper_id': 'p' + str(index)}
                               for index in range(12)}
        self.service.cards = {'p' + str(index): {'claims': [{'claim': 'Fixture'}]}
                              for index in range(6)}
        self.block_model = mock.patch('sage.autonomous.service.OpenAIModel.from_env',
                                      side_effect=AssertionError('No paid API in offline tests'))
        self.block_model.start()
        self.addCleanup(self.block_model.stop)

    def team(self, slot, **arguments):
        return self.service.call('team', arguments, slot=slot)

    def write_proposal(self, slot):
        path = self.workspaces[slot] / 'proposal.json'
        path.write_text(json.dumps(candidate_document(4)), encoding='utf-8')
        return path

    def snapshot_path(self):
        return self.root / 'native-run' / '.coral' / 'public' / 'team-snapshot.json'

    def test_default_status_is_compact_with_snapshot_pointer(self):
        status = self.team(0, action='status')
        self.assertEqual(status['schema_version'], 'sage.autonomous.team.v1')
        self.assertEqual(status['phase'], 'proposing')
        self.assertEqual(status['next_action'], 'propose')
        self.assertEqual(status['role'], self.service.team.state['roster']['0']['role'])
        self.assertEqual(status['slot'], 0)
        self.assertEqual(status['proposal_count'], 0)
        self.assertEqual(status['frozen_slots'], [])
        self.assertEqual(status['incoming_issue_count'], 0)
        self.assertEqual(status['peer_advice_audit_count'], 0)
        self.assertIsNone(status['own_proposal'])
        self.assertNotIn('frozen_proposals', status)
        self.assertNotIn('incoming_issues', status)
        self.assertNotIn('syntheses', status)
        self.assertNotIn('peer_advice_audits', status)
        self.assertEqual(status['snapshot_file'], '.coral/public/team-snapshot.json')
        self.assertRegex(status['snapshot_sha256'], '^[0-9a-f]{64}$')
        stored = self.snapshot_path()
        self.assertTrue(stored.is_file())
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o644)
        body = stored.read_bytes()
        self.assertEqual(hashlib.sha256(body).hexdigest(), status['snapshot_sha256'])
        shared = json.loads(body)
        self.assertEqual(shared['schema_version'], 'sage.autonomous.team.v1')
        for slot_field in ('slot', 'role', 'next_action', 'own_proposal',
                           'incoming_issues', 'peer_advice_audits'):
            self.assertNotIn(slot_field, shared,
                             'shared all-agent snapshot must exclude slot-specific fields')

    def test_snapshot_file_updates_only_when_content_changes(self):
        self.team(0, action='status')
        stored = self.snapshot_path()
        before = stored.read_bytes()
        self.team(1, action='status')
        self.assertEqual(stored.read_bytes(), before,
                         'slot-neutral snapshot is identical across slots; no rewrite needed')
        self.team(0, action='propose', artifact_path=str(self.write_proposal(0)))
        status = self.team(1, action='status')
        self.assertNotEqual(stored.read_bytes(), before)
        self.assertEqual(status['proposal_count'], 1)
        self.assertEqual(status['frozen_slots'], [])
        after = stored.read_bytes()
        self.team(0, action='status')
        self.assertEqual(stored.read_bytes(), after)

    def test_frozen_round_compact_and_sections_inline_full_data(self):
        self.team(0, action='propose', artifact_path=str(self.write_proposal(0)))
        self.team(1, action='propose', artifact_path=str(self.write_proposal(1)))
        compact = self.team(0, action='status')
        self.assertEqual(compact['phase'], 'reviewing')
        self.assertEqual(compact['next_action'], 'review')
        self.assertEqual(compact['review_target'], 1)
        self.assertIn(compact['target_primary_sha256'], compact['frozen_shas'].values())
        self.assertEqual(sorted(compact['frozen_shas']), ['0', '1'])
        self.assertNotIn('frozen_proposals', compact)
        full_board = self.service.team.snapshot(0)
        sections = self.team(0, action='status', sections=['frozen_proposals'])
        self.assertEqual(sections['frozen_proposals'], full_board['frozen_proposals'])
        self.assertNotIn('syntheses', sections)
        detailed = self.team(0, action='status', detail='full')
        for key in ('own_proposal', 'frozen_proposals', 'review_history', 'incoming_issues',
                    'revision_history', 'syntheses'):
            self.assertEqual(detailed[key], full_board[key])
        self.assertEqual(detailed['frozen_proposals'], full_board['frozen_proposals'])
        self.assertEqual(detailed['peer_advice_audits'], [])

    def test_incoming_issues_available_through_sections(self):
        self.team(0, action='propose', artifact_path=str(self.write_proposal(0)))
        self.team(1, action='propose', artifact_path=str(self.write_proposal(1)))
        status = self.team(0, action='status')
        issue = {'id': 'I0', 'candidate_id': 'C0', 'kind': 'methodological',
                 'problem': 'Fixture problem', 'repair': 'Fixture repair',
                 'source_ids': [], 'target_fields': ['hypothesis']}
        receipt = self.team(0, action='review', round=status['round'],
                            target_slot=status['review_target'],
                            proposal_sha256=status['target_primary_sha256'], issues=[issue])
        self.assertNotIn('error', receipt)
        # With two researchers both reviews must freeze before revising opens.
        other = self.team(1, action='status')
        receipt = self.team(1, action='review', round=other['round'],
                            target_slot=other['review_target'],
                            proposal_sha256=other['target_primary_sha256'], issues=[])
        self.assertNotIn('error', receipt)
        compact = self.team(1, action='status')
        self.assertEqual(compact['next_action'], 'revise')
        self.assertEqual(compact['incoming_issue_count'], 1)
        self.assertNotIn('incoming_issues', compact)
        expanded = self.team(1, action='status', sections=['incoming_issues'])
        self.assertEqual(expanded['incoming_issues'], [issue])

    def test_invalid_status_parameters_raise_value_error(self):
        with self.assertRaisesRegex(ValueError, 'sections must be a list'):
            self.team(0, action='status', sections='frozen_proposals')
        with self.assertRaisesRegex(ValueError, 'sections must be a list'):
            self.team(0, action='status', sections=[42])
        with self.assertRaisesRegex(ValueError, 'Unknown team status sections'):
            self.team(0, action='status', sections=['frozen_proposals', 'invented'])
        with self.assertRaisesRegex(ValueError, 'detail must be exactly'):
            self.team(0, action='status', detail='verbose')

    def test_other_team_actions_are_untouched(self):
        receipt = self.team(0, action='propose', artifact_path=str(self.write_proposal(0)))
        self.assertEqual(receipt['operation'], 'propose')
        self.assertIn('payload_sha256', receipt)
        self.assertNotIn('archived', receipt)
        self.assertFalse((self.root / 'native-run' / '.coral' / 'public' / 'tool-archive').exists())


class EvidenceFilterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'fixture topic')
        self.service.papers = {'p' + str(index): {'paper_id': 'p' + str(index)}
                               for index in range(4)}
        self.service.cards = {'p0': {'claims': [{'claim': 'Fixture'}]},
                              'p1': {'claims': [{'claim': 'Other fixture'}]}}
        self.service.searches = [{'purpose': 'landscape', 'results': [{'paper_id': 'p0'}]}]
        self.service.reviews = [{'id': 'fixture-review', 'grading': False}]

    def test_default_evidence_response_is_unchanged(self):
        result = self.service.call('evidence', {})
        self.assertEqual(set(result), {'papers', 'cards', 'reviews', 'searches',
                                       'independent_acceptance'})
        self.assertEqual(len(result['papers']), 4)

    def test_paper_ids_filter_papers_and_cards_and_report_unknown(self):
        result = self.service.call('evidence', {'paper_ids': ['p1', 'p3', 'missing']})
        self.assertEqual(set(result), {'papers', 'cards', 'reviews', 'searches',
                                       'independent_acceptance', 'paper_ids',
                                       'unknown_paper_ids'})
        self.assertEqual(sorted(result['papers']), ['p1', 'p3'])
        self.assertEqual(sorted(result['cards']), ['p1'])
        self.assertEqual(result['paper_ids'], ['p1', 'p3', 'missing'])
        self.assertEqual(result['unknown_paper_ids'], ['missing'])
        self.assertEqual(result['reviews'], [{'id': 'fixture-review', 'grading': False}])
        self.assertEqual(result['searches'], self.service.searches)

    def test_include_selects_top_level_sections(self):
        result = self.service.call('evidence', {'include': ['papers']})
        self.assertEqual(set(result), {'papers', 'independent_acceptance'})
        result = self.service.call('evidence', {
            'include': ['papers', 'cards'], 'paper_ids': ['p0', 'p2']})
        self.assertEqual(set(result), {'papers', 'cards', 'independent_acceptance',
                                       'paper_ids', 'unknown_paper_ids'})
        self.assertEqual(sorted(result['papers']), ['p0', 'p2'])
        self.assertEqual(sorted(result['cards']), ['p0'])
        self.assertEqual(result['unknown_paper_ids'], [])

    def test_invalid_filter_arguments_raise_value_error(self):
        for arguments, message in (
                ({'paper_ids': 'p0'}, 'paper_ids must be a list'),
                ({'paper_ids': ['p0', 7]}, 'paper_ids must be a list'),
                ({'include': 'papers'}, 'include must be a list'),
                ({'include': ['papers', None]}, 'include must be a list'),
                ({'include': ['papers', 'invented']}, 'Unknown evidence sections')):
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, message):
                    self.service.call('evidence', arguments)


if __name__ == '__main__':
    unittest.main()
