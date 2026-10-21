"""Offline end-to-end service wiring for peer audits, protocols and bound reports."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from sage.autonomous.peer_audit import PEER_AUDIT_VERSION
from sage.autonomous.export import export_submissions
from sage.autonomous.repair import ReviewStageError
from sage.autonomous.report import render_report, validate_report
from sage.autonomous.revision_contract import revision_descriptor
from sage.autonomous.review import input_digest
from sage.autonomous.service import ResearchService
from test_autonomous_protocol import fixture_protocol
from test_autonomous_team_service import SESSIONS, candidate_document
from test_peer_advice_audit import FakeModel


class ServiceModel(FakeModel):
    async def aclose(self):
        pass


def audit_response(issue_id):
    return json.dumps({'audit_version': PEER_AUDIT_VERSION, 'advice_audits': [{
        'issue_id': issue_id, 'candidate_id': 'C0',
        'problem_verdict': 'supported', 'problem_reason': 'The frozen proposal leaves a logical ambiguity.',
        'repair_verdict': 'unknown', 'repair_reason': 'The remedy requires an explicit estimand before adoption.',
        'source_ids': [], 'source_refs': [], 'evidence_limit': 'Logical assessment; no research experiment.'}],
        'summary': 'Adjudicate the issue and remedy separately.'})


class AutonomousServiceRepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.service = ResearchService(self.root / 'private', self.root, 'Offline fixture topic',
            researchers=2, discussion_rounds=1, require_protocol=True, enable_peer_audit=True)
        self.workspaces, self.proposals = [], []
        for slot in range(2):
            workspace = self.root / 'native-run' / 'agents' / f'researcher-{slot}'
            workspace.mkdir(parents=True)
            self.workspaces.append(workspace)
            self.service.team.register(slot, f'researcher-{slot}', workspace, SESSIONS[slot])
            document = candidate_document(4)
            document['candidates'][0]['protocol'] = fixture_protocol()
            self.proposals.append(self.write(slot, 'proposal.json', document))
        self.service.papers = {f'p{i}': {'paper_id': f'p{i}', 'title': f'Offline source {i}'} for i in range(12)}
        self.service.cards = {f'p{i}': {'claims': [{'claim': 'Synthetic fixture statement'}]} for i in range(6)}
        self.service.searches = [{'purpose': purpose, 'results': [{'paper_id': 'p0'}]}
                                for purpose in ('landscape', 'novelty', 'counterevidence')]
        self.block_model = mock.patch('sage.autonomous.service.OpenAIModel.from_env',
                                     side_effect=AssertionError('No paid API in service regression tests'))
        self.block_model.start()
        self.addCleanup(self.block_model.stop)
        search = mock.patch('sage.autonomous.service.ArxivSource.search',
                            side_effect=AssertionError('No remote scholarly calls in service regressions'))
        search.start()
        self.addCleanup(search.stop)

    def write(self, slot, name, document):
        path = self.workspaces[slot] / name
        path.write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        return path

    def team(self, slot, **arguments):
        return self.service.call('team', arguments, slot=slot)

    def service_events(self):
        path = self.root / 'private' / 'events.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    def test_tool_trace_success_and_failure_pair_with_nested_events_and_full_digest(self):
        returned = {'papers': [{'paper_id': 'synthetic-' + str(index), 'text': '完整资料' * 100}
                               for index in range(20)], 'empty': None, 'status': 'fixture_complete'}

        async def search(query, **arguments):
            self.service.event('fixture_nested_search', query=query)
            if query == 'failure':
                raise ValueError('Fixture retrieval refusal')
            return copy.deepcopy(returned)

        with mock.patch.object(self.service, 'search', search):
            actual = self.service.call('search', {'query': 'success'}, slot=0)
            with self.assertRaisesRegex(ValueError, 'Fixture retrieval refusal'):
                self.service.call('search', {'query': 'failure'}, slot=0)
        self.assertEqual(actual, returned)
        events = self.service_events()
        starts = [event for event in events if event['kind'] == 'tool_transfer_started']
        self.assertEqual(len(starts), 2)
        self.assertEqual(len({event['request_id'] for event in starts}), 2)
        for start in starts:
            group = [event for event in events if event['request_id'] == start['request_id']]
            terminal = [event for event in group if event['kind'] in ('tool_transfer_completed', 'tool_transfer_failed')]
            self.assertEqual(len(terminal), 1)
            self.assertTrue(any(event['kind'] == 'fixture_nested_search' for event in group))
            self.assertEqual(start['input_sha256'], input_digest(start['arguments']))
            self.assertLess(start['event_sequence'], terminal[0]['event_sequence'])
            if start['arguments']['query'] == 'success':
                self.assertEqual(terminal[0]['kind'], 'tool_transfer_completed')
                expected_bytes = json.dumps(actual, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':'), allow_nan=False).encode('utf-8')
                self.assertEqual(terminal[0]['output_sha256'], hashlib.sha256(expected_bytes).hexdigest())
                self.assertEqual(terminal[0]['output_bytes'], len(expected_bytes))
            else:
                self.assertEqual(terminal[0]['kind'], 'tool_transfer_failed')
                self.assertEqual(terminal[0]['error'], 'ValueError')
                self.assertIn('Fixture retrieval refusal', terminal[0]['message'])
        self.assertEqual([event['event_sequence'] for event in events], list(range(1, len(events) + 1)))

    def test_tool_trace_parallel_requests_never_share_request_context(self):
        barrier = threading.Barrier(2)

        async def search(query, **arguments):
            self.service.event('fixture_parallel_before', query=query)
            barrier.wait(timeout=5)
            self.service.event('fixture_parallel_after', query=query)
            return {'query': query, 'status': 'fixture_complete'}

        with mock.patch.object(self.service, 'search', search), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.service.call, 'search', {'query': 'slot-' + str(slot)}, slot=slot)
                       for slot in (0, 1)]
            results = [future.result(timeout=10) for future in futures]
        events = self.service_events()
        starts = [event for event in events if event['kind'] == 'tool_transfer_started']
        self.assertEqual(len({event['request_id'] for event in starts}), 2)
        for start in starts:
            query = start['arguments']['query']
            group = [event for event in events if event['request_id'] == start['request_id']]
            nested = [event for event in group if event['kind'].startswith('fixture_parallel_')]
            self.assertEqual([event['query'] for event in nested], [query, query])
            complete = [event for event in group if event['kind'] == 'tool_transfer_completed']
            self.assertEqual(len(complete), 1)
            result = next(result for result in results if result['query'] == query)
            self.assertEqual(complete[0]['output_sha256'], input_digest(result))
        self.assertEqual([event['event_sequence'] for event in events], list(range(1, len(events) + 1)))
        self.service.event('fixture_outside_request', sequence=999)
        outside = self.service_events()[-1]
        self.assertIsNone(outside['request_id'])
        self.assertEqual(outside['event_sequence'], len(events) + 1)
        self.assertEqual(outside['sequence'], 999)

    def test_trace_restores_outer_request_after_nested_tool_call(self):
        async def search(query, **arguments):
            self.service.event('fixture_outer_before')
            self.service.call('protocol_schema', {}, slot=0)
            self.service.event('fixture_outer_after')
            return {'status': 'fixture_complete'}

        with mock.patch.object(self.service, 'search', search):
            self.service.call('search', {'query': 'nested fixture'}, slot=0)
        events = self.service_events()
        starts = {event['tool']: event for event in events if event['kind'] == 'tool_transfer_started'}
        self.assertNotEqual(starts['search']['request_id'], starts['protocol_schema']['request_id'])
        for event in events:
            if event['kind'] in ('fixture_outer_before', 'fixture_outer_after'):
                self.assertEqual(event['request_id'], starts['search']['request_id'])

    def test_trace_does_not_add_research_or_coordination_budget_usage(self):
        initial = self.service.tool_calls, self.service.coordination_calls
        self.service.call('team', {'action': 'status'}, slot=0)
        self.service.call('protocol_schema', {}, slot=0)
        with self.assertRaisesRegex(ValueError, 'Unknown research tool'):
            self.service.call('unknown-fixture-tool', {}, slot=0)
        self.assertEqual((self.service.tool_calls, self.service.coordination_calls),
                         (initial[0] + 2, initial[1] + 1))
        events = self.service_events()
        self.assertEqual(sum(event['kind'] == 'tool_transfer_started' for event in events), 3)
        self.assertEqual(sum(event['kind'] in ('tool_transfer_completed', 'tool_transfer_failed') for event in events), 3)

    def test_nonfinite_input_digest_failure_still_has_paired_trace(self):
        # Python's JSON decoder accepts NaN by default; trace input hashing must
        # not leave a terminal event with no corresponding start record.
        with self.assertRaises(ValueError):
            self.service.call('search', {'query': 'fixture', 'limit': float('nan')}, slot=0)
        events = self.service_events()
        starts = [event for event in events if event['kind'] == 'tool_transfer_started']
        failed = [event for event in events if event['kind'] == 'tool_transfer_failed']
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(failed), 1)
        self.assertEqual(starts[0]['request_id'], failed[0]['request_id'])
        self.assertFalse(any(event['kind'] == 'tool_transfer_completed' for event in events))

    def test_existing_manager_state_is_rejected_without_rewriting_any_bytes(self):
        self.service.call('protocol_schema', {}, slot=0)
        private = self.root / 'private'
        before = {str(path.relative_to(private)): path.read_bytes() for path in private.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'Existing research state'):
            ResearchService(private, self.root, 'Different topic', researchers=2, discussion_rounds=1)
        after = {str(path.relative_to(private)): path.read_bytes() for path in private.rglob('*') if path.is_file()}
        self.assertEqual(after, before)
        for marker in ('evidence.json', 'team-state.json', 'events.jsonl'):
            with self.subTest(marker=marker):
                existing = self.root / ('existing-' + marker.replace('.', '-'))
                existing.mkdir()
                original = b'opaque prior state\r\n\x00not to rewrite'
                (existing / marker).write_bytes(original)
                with self.assertRaisesRegex(ValueError, 'Existing research state'):
                    ResearchService(existing, self.root, 'Replacement rejected')
                self.assertEqual(list(existing.iterdir()), [existing / marker])
                self.assertEqual((existing / marker).read_bytes(), original)

    def freeze_proposals(self):
        for slot in range(2):
            self.team(slot, action='propose', artifact_path=str(self.proposals[slot]))

    def review_arguments(self, slot, *, with_issue=True):
        status = self.team(slot, action='status')
        issue = {'id': f'I{slot}', 'candidate_id': 'C0', 'kind': 'methodological',
                 'problem': 'The contrast leaves an ambiguity.', 'repair': 'Specify a narrower contrast.',
                 'source_ids': [], 'target_fields': ['hypothesis']}
        return {'action': 'review', 'round': status['round'], 'target_slot': status['review_target'],
                'proposal_sha256': status['target_primary_sha256'],
                'issues': [issue] if with_issue else []}

    def decision(self, issue_id):
        return {'issue_id': issue_id, 'decision': 'uncertain',
                'reason': 'The objection is plausible but requires checking the estimand.',
                'source_ids': [], 'change': '',
                'problem_assessment': 'The ambiguity is real under the given assumptions.',
                'remedy_assessment': 'The proposed restriction could change the target population.',
                'audit_response': 'Keep the proposed repair unresolved pending source inspection.',
                'remaining_uncertainty': 'No experiment or new source has resolved this issue.'}

    def complete_team_without_issues(self):
        self.freeze_proposals()
        for slot in range(2):
            receipt = self.team(slot, **self.review_arguments(slot, with_issue=False))
            self.assertEqual(receipt['advice_audit']['status'], 'not_needed')
        for slot in range(2):
            self.team(slot, action='revise', round=1, artifact_path=str(self.proposals[slot]), decisions=[])
        return self.synthesize()

    def synthesize(self):
        status = self.team(0, action='status', detail='full')
        synthesis = {'candidates': [], 'selected_ids': ['S0-C0'], 'selection_rationale': 'Offline selection.'}
        for slot, record in status['frozen_proposals'].items():
            for candidate in record['document']['candidates']:
                item = copy.deepcopy(candidate)
                item['id'] = f'S{slot}-' + candidate['id']
                item['origin'] = {'slot': int(slot), 'candidate_id': candidate['id'],
                                  'proposal_sha256': record['primary_sha256']}
                synthesis['candidates'].append(item)
        primary = self.write(0, 'conjectures.json', synthesis)
        receipt = self.team(0, action='synthesize', artifact_path=str(primary))
        return primary, receipt

    def checkout(self, primary, report):
        checkout = self.root / 'native-run' / '.coral' / 'private' / 'grader_checkouts' / 'offline-commit'
        checkout.mkdir(parents=True, exist_ok=True)
        copied = checkout / 'conjectures.json'
        copied.write_bytes(primary.read_bytes())
        (checkout / 'CONJECTURES.md').write_bytes(report)
        return copied

    def seed_advisory_receipts(self, sha):
        self.service.reviews = [{'id': f'advisory-{i}', 'grading': False, 'research_slot': 0,
            'input_sha256': sha, 'time': '9999-01-01T00:00:00+00:00'} for i in range(2)]

    def test_published_peer_audit_is_attached_visible_and_idempotent(self):
        self.freeze_proposals()
        arguments = self.review_arguments(0)
        model = ServiceModel(audit_response('I0'))
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model) as factory:
            first = self.team(0, **arguments)
            second = self.team(0, **arguments)
        self.assertEqual(first, second)
        self.assertEqual(first['advice_audit']['status'], 'completed')
        self.assertTrue(first['advice_audit']['complete_audit'])
        self.assertEqual(len(model.calls), 1)
        factory.assert_called_once()
        target = self.team(1, action='status', sections=['peer_advice_audits'])['peer_advice_audits']
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]['review_receipt']['proposal_sha256'], arguments['proposal_sha256'])
        self.assertEqual(target[0]['audit']['advice_audits'][0]['issue_id'], 'I0')
        self.assertEqual(self.team(0, action='status', sections=['peer_advice_audits'])['peer_advice_audits'], [])
        self.assertEqual(self.service.reviews, [], 'Peer audit must not be counted as an advisory grade')
        persisted = json.loads((self.root / 'private' / 'evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(len(persisted['peer_advice_audits']), 1)

    def test_pending_audit_does_not_block_status_but_blocks_revision(self):
        self.freeze_proposals()
        first_args = self.review_arguments(0)
        second_args = self.review_arguments(1)
        entered, release = threading.Event(), threading.Event()
        model = ServiceModel(audit_response('I0'))
        original = model.complete

        async def blocked(*args, **kwargs):
            entered.set()
            if not await asyncio.to_thread(release.wait, 5):
                raise AssertionError('Offline audit fixture was not released')
            return await original(*args, **kwargs)

        model.complete = blocked
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model), \
                ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(self.team, 0, **first_args)
            try:
                self.assertTrue(entered.wait(2))
                # Freeze the other review without paying for a second model;
                # this puts the board into the revision phase while I0 is pending.
                self.service.team_call(1, second_args)
                status = self.team(1, action='status', sections=['peer_advice_audits'])
                self.assertEqual(status['next_action'], 'wait')
                self.assertEqual(status['waiting_for'], 'peer_advice_audit')
                self.assertEqual(status['peer_advice_audits'][0]['status'], 'pending')
                self.assertFalse(pending.done())
                with self.assertRaisesRegex(ValueError, 'audit is pending'):
                    self.team(1, action='revise', round=1,
                              artifact_path=str(self.proposals[1]), decisions=[self.decision('I0')])
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=2)['advice_audit']['status'], 'completed')

    def test_client_cleanup_failure_cannot_leave_peer_audit_permanently_pending(self):
        self.freeze_proposals()
        model = ServiceModel(audit_response('I0'))

        async def failing_close():
            raise OSError('private provider cleanup detail')

        model.aclose = failing_close
        with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
            receipt = self.team(0, **self.review_arguments(0))
        self.assertEqual(receipt['advice_audit']['status'], 'completed')
        status = self.team(1, action='status', sections=['peer_advice_audits'])['peer_advice_audits'][0]
        self.assertNotEqual(status['status'], 'pending')
        self.assertNotIn('private provider cleanup detail', json.dumps(status))

    def test_every_postaudit_decision_requires_separate_scientific_assessments(self):
        self.freeze_proposals()
        for slot in range(2):
            model = ServiceModel(audit_response(f'I{slot}'))
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                self.team(slot, **self.review_arguments(slot))
        for field in ('problem_assessment', 'remedy_assessment', 'audit_response', 'remaining_uncertainty'):
            decision = self.decision('I1')
            decision.pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.team(0, action='revise', round=1, artifact_path=str(self.proposals[0]), decisions=[decision])
        receipt = self.team(0, action='revise', round=1, artifact_path=str(self.proposals[0]),
                            decisions=[self.decision('I1')])
        self.assertEqual(receipt['scientific_resolution'], 'not_verified')

    def test_unavailable_peer_audit_preserves_issue_and_cannot_supply_advisory_grade(self):
        self.freeze_proposals()
        for slot in range(2):
            model = ServiceModel('{}', '{}')
            with mock.patch('sage.autonomous.service.OpenAIModel.from_env', return_value=model):
                receipt = self.team(slot, **self.review_arguments(slot))
            self.assertEqual(receipt['advice_audit']['status'], 'unavailable')
            self.assertFalse(receipt['advice_audit']['complete_audit'])
            self.assertEqual(len(model.calls), 2)
        self.assertEqual(self.service.team.summary()['review_count'], 2)
        for slot in range(2):
            self.team(slot, action='revise', round=1, artifact_path=str(self.proposals[slot]),
                      decisions=[self.decision(f'I{1-slot}')])
        primary, _ = self.synthesize()
        result = self.service.call('report', {'artifact_path': str(primary)}, slot=0)
        copied = self.checkout(primary, Path(result['path']).read_bytes())
        judgment = mock.AsyncMock(side_effect=AssertionError('Unavailable peer audit is not a grade'))
        with mock.patch.object(self.service, 'judgment', judgment):
            denied = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertTrue(denied['contract_errors'])
        self.assertTrue(any('advisory' in error or 'fresh-context' in error for error in denied['contract_errors']))
        self.assertEqual(denied['score'], 0)
        judgment.assert_not_awaited()
        self.assertEqual(self.service.reviews, [])

    def test_report_tool_writes_exact_utf8_and_formal_archive_preserves_bytes(self):
        primary, synthesis = self.complete_team_without_issues()
        narrative = '## 中文科研说明\n\n保留假说、原文证据与未完成的功效分析。\n'
        result = self.service.call('report', {'artifact_path': str(primary), 'narrative': narrative}, slot=0)
        report = Path(result['path']).read_bytes()
        self.assertIn(narrative.encode('utf-8'), report)
        self.assertNotIn(b'\r\n', report, 'Windows text translation must not change bound report bytes')
        self.assertEqual(result['audit']['status'], 'verified_alignment')
        self.assertEqual(validate_report(primary.read_bytes(), report,
                         synthesis_version=synthesis['version'])['errors'], [])
        copied = self.checkout(primary, report)
        self.seed_advisory_receipts(synthesis['primary_sha256'])
        judgment = mock.AsyncMock(return_value={'id': 'offline-formal', 'review': {'score': 0.5}})
        with mock.patch.object(self.service, 'judgment', judgment):
            graded = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertEqual(graded['contract_errors'], [])
        self.assertEqual(graded['evaluation_status'], 'completed')
        self.assertEqual(graded['scientific_score'], 0.5)
        judgment.assert_awaited_once()
        record = self.service.grades[-1]
        self.assertEqual((self.service.private / record['report_file']).read_bytes(), report)
        self.assertEqual(record['report_sha256'], hashlib.sha256(report).hexdigest())

    def test_preflight_matches_formal_gate_without_model_or_attempt_and_invalidates_edits(self):
        primary, synthesis = self.complete_team_without_issues()
        rendered = self.service.call('report', {'artifact_path': str(primary)}, slot=0)
        copied = self.checkout(primary, Path(rendered['path']).read_bytes())
        pre = self.service.call('preflight', {'artifact_path': str(primary)}, slot=0)
        self.assertFalse(pre['ready_for_formal_grade'])
        self.assertEqual(self.service.formal_attempts, 0)
        formal = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertEqual(pre['contract_errors'], formal['contract_errors'])
        self.seed_advisory_receipts(synthesis['primary_sha256'])
        ready = self.service.call('preflight', {'artifact_path': str(primary)}, slot=0)
        self.assertTrue(ready['ready_for_formal_grade'])
        before = self.service.formal_attempts
        primary.write_bytes(primary.read_bytes() + b'\n')
        changed = self.service.call('preflight', {'artifact_path': str(primary)}, slot=0)
        self.assertFalse(changed['ready_for_formal_grade'])
        self.assertNotEqual(changed['primary_sha256'], ready['primary_sha256'])
        self.assertEqual(self.service.formal_attempts, before)

    def test_failed_formal_review_spends_attempt_preserves_partial_and_never_exports(self):
        primary, synthesis = self.complete_team_without_issues()
        rendered = self.service.call('report', {'artifact_path': str(primary)}, slot=0)
        copied = self.checkout(primary, Path(rendered['path']).read_bytes())
        self.seed_advisory_receipts(synthesis['primary_sha256'])
        self.service.max_formal_attempts = 1
        partial = {'score': 0.81, 'candidate_reviews': []}
        failure = ReviewStageError('novelty_feedback', 'Missing original-text reference',
            [{'stage': 'scientific_review', 'attempt': 1, 'validation': 'passed'},
             {'stage': 'novelty_feedback', 'attempt': 1, 'validation': 'failed'}],
            partial_review=partial)
        judgment = mock.AsyncMock(side_effect=failure)
        with mock.patch.object(self.service, 'judgment', judgment):
            failed = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
            exhausted = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        judgment.assert_awaited_once()
        self.assertEqual(self.service.formal_attempts, 1)
        self.assertEqual(failed['score'], 0, 'CORAL operational failure sentinel is not a scientific score')
        self.assertIsNone(failed['scientific_score'])
        self.assertEqual(failed['evaluation_status'], 'review_unavailable')
        self.assertEqual(failed['score_semantics'], 'operational_failure_sentinel_not_scientific_rating')
        self.assertEqual(failed['review_failure']['stage'], 'novelty_feedback')
        self.assertEqual(failed['review_failure']['partial_review'], partial)
        record = self.service.grades[-1]
        self.assertIsNone(record['score'])
        self.assertIsNone(record['scientific_score'])
        self.assertEqual(record['evaluation_status'], 'review_unavailable')
        self.assertEqual(exhausted['evaluation_status'], 'budget_exhausted')
        self.assertIsNone(exhausted['scientific_score'])
        exported = export_submissions(self.service.private, self.root / 'failed-export', self.service.grades)
        self.assertIsNone(exported['selected_grade'])
        self.assertFalse((self.root / 'failed-export' / 'CONJECTURES.md').exists())

    def test_readable_malformed_json_spends_formal_attempt_without_model_call(self):
        primary, _ = self.complete_team_without_issues()
        copied = self.checkout(primary, b'No report can authenticate malformed primary JSON.')
        bad_id = json.loads(primary.read_text(encoding='utf-8'))
        bad_id['candidates'][0]['id'] = ['not-a-string-id']
        bad_source = json.loads(primary.read_text(encoding='utf-8'))
        bad_source['candidates'][0]['source_ids'] = [['p0'], 'p1']
        payloads = [b'{"candidates": [broken JSON', json.dumps(bad_id).encode(), json.dumps(bad_source).encode()]
        self.service.max_formal_attempts = len(payloads)
        judgment = mock.AsyncMock(side_effect=AssertionError('Malformed JSON cannot reach scoring'))
        with mock.patch.object(self.service, 'judgment', judgment):
            for index, payload in enumerate(payloads):
                with self.subTest(payload=index):
                    copied.write_bytes(payload)
                    failed = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
                    self.assertEqual(failed['evaluation_status'], 'contract_failed')
                    self.assertIsNone(failed['scientific_score'])
                    self.assertTrue(failed['contract_errors'])
            exhausted = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertEqual(self.service.formal_attempts, len(payloads))
        self.assertEqual(exhausted['evaluation_status'], 'budget_exhausted')
        judgment.assert_not_awaited()

    def test_stale_report_version_and_changed_primary_are_rejected_before_paid_grade(self):
        primary, synthesis = self.complete_team_without_issues()
        self.seed_advisory_receipts(synthesis['primary_sha256'])
        stale_report = render_report(primary.read_bytes(), synthesis_version=99).encode('utf-8')
        copied = self.checkout(primary, stale_report)
        judgment = mock.AsyncMock(side_effect=AssertionError('Stale report cannot reach scoring provider'))
        with mock.patch.object(self.service, 'judgment', judgment):
            stale = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
            self.assertTrue(any('synthesis_version' in error for error in stale['contract_errors']))
            current_report = render_report(primary.read_bytes(), synthesis_version=synthesis['version']).encode('utf-8')
            (copied.parent / 'CONJECTURES.md').write_bytes(current_report)
            changed = json.loads(copied.read_text(encoding='utf-8'))
            changed['candidates'][0]['hypothesis'] = 'Changed after report generation.'
            copied.write_bytes(json.dumps(changed).encode('utf-8'))
            changed_result = asyncio.run(self.service.grade(copied, agent_id='researcher-0'))
        self.assertTrue(any('primary_sha256' in error for error in changed_result['contract_errors']))
        judgment.assert_not_awaited()

    def test_native_formal_submission_requires_latest_but_preserves_history_for_export(self):
        primary, first = self.complete_team_without_issues()
        report = self.service.call('report', {'artifact_path': str(primary)}, slot=0)
        old_report = Path(report['path']).read_bytes()
        old_checkout = self.checkout(primary, old_report)
        document = json.loads(primary.read_text(encoding='utf-8'))
        record = copy.deepcopy(revision_descriptor()['template'])
        record.update(parent_sha256=first['primary_sha256'], change_type='no_scientific_change',
                      basis=[], candidate_changes=[], context_changes=[], withdrawn_selected=[],
                      reason='Only the responsibility ledger is added; no scientific field changed.')
        document['revision_record'] = record
        newer = self.write(0, 'conjectures-v2.json', document)
        second = self.team(0, action='synthesize', artifact_path=str(newer))
        self.assertEqual(second['version'], 2)
        self.assertNotEqual(second['primary_sha256'], first['primary_sha256'])
        # Exact historical syntheses remain authentic for auditing/export, but
        # the live native submission path cannot jump backwards around revision.
        original = json.loads(primary.read_text(encoding='utf-8'))
        self.assertEqual(self.service.team.grade_errors(original, first['primary_sha256']), [])
        self.seed_advisory_receipts(first['primary_sha256'])
        judgment = mock.AsyncMock(return_value={'id': 'legacy-only', 'review': {'score': 0.5}})
        with mock.patch.object(self.service, 'judgment', judgment):
            blocked = asyncio.run(self.service.grade(old_checkout, agent_id='researcher-0'))
            self.assertTrue(any('latest registered synthesis' in error for error in blocked['contract_errors']))
            judgment.assert_not_awaited()
            self.service.require_protocol = False  # Explicit older embedded-caller compatibility.
            compatible = asyncio.run(self.service.grade(old_checkout, agent_id='researcher-0'))
        self.assertEqual(compatible['contract_errors'], [])
        judgment.assert_awaited_once()

    def test_protocol_tool_and_missing_protocol_gate_are_wired_without_models(self):
        descriptor = self.service.call('protocol_schema', {}, slot=0)
        self.assertIn('revision_contract', descriptor)
        self.assertEqual(descriptor['candidate_field'], 'protocol')
        document = candidate_document(4)
        missing = self.write(0, 'missing-protocol.json', document)
        with self.assertRaisesRegex(ValueError, 'canonical protocol'):
            self.team(0, action='propose', artifact_path=str(missing))
        self.assertEqual(self.service.team.summary()['proposal_count'], 0)
        self.assertEqual(self.service.reviews, [])


if __name__ == '__main__':
    unittest.main()
